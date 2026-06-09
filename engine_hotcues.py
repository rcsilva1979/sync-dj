#!/usr/bin/env python3
"""
Read Engine DJ m.db files and display hotcues stored in PerformanceData.quickCues.

The script opens the SQLite database read-only. It does not modify the Engine DJ
library.
"""

from __future__ import annotations

import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from mutagen import File


@dataclass
class Hotcue:
    performance_id: Any
    track_id: Any
    cue_number: int
    label: str
    position_samples: float
    position_seconds: float | None
    color_hex: str | None
    raw_offset: int


@dataclass
class CueWrite:
    cue_number: int
    label: str
    position_seconds: float
    color_bytes: bytes | None = None


@dataclass
class TrackInfo:
    track_id: Any
    title: str
    artist: str
    album: str
    path: str
    filename: str
    length: float | None
    bpm: float | None
    key: str
    rating: int | None


@dataclass
class VdjTrack:
    key: str
    filepath: str
    directory: str
    filename: str
    title: str
    artist: str
    cues: list[CueWrite]


ENGINE_DJ_CUE_COLORS: dict[int, bytes] = {
    1: bytes.fromhex("FFF4D338"),
    2: bytes.fromhex("FFEF8130"),
    3: bytes.fromhex("FFAA55C4"),
    4: bytes.fromhex("FFCE3239"),
    5: bytes.fromhex("FF86C64B"),
    6: bytes.fromhex("FF20C670"),
    7: bytes.fromhex("FF00A8A9"),
    8: bytes.fromhex("FF1571E2"),
}

def get_sample_rate(path: str) -> float:
    audio = File(path)
    return float(audio.info.sample_rate)

def samples_to_seconds(samples: float, sample_rate: float) -> float:
    return samples / sample_rate

def normalize_cue_time(value: float, mode: str, sample_rate: float) -> float:
    if mode == "samples":
        return value / sample_rate
    return value  # seconds direto

def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def find_name(names: Iterable[str], wanted: str) -> str | None:
    wanted_lower = wanted.lower()
    for name in names:
        if name.lower() == wanted_lower:
            return name
    return None


def maybe_decompress(blob: bytes) -> tuple[bytes, bool]:
    if len(blob) > 6 and blob[4:6] in (b"\x78\x01", b"\x78\x9c", b"\x78\xda"):
        try:
            data = zlib.decompress(blob[4:])
            expected_size = int.from_bytes(blob[:4], "big")
            if expected_size in (0, len(data)):
                return data, True
        except zlib.error:
            pass

    try:
        return zlib.decompress(blob), True
    except zlib.error:
        return blob, False


def decode_color(raw: bytes) -> str | None:
    if len(raw) >= 4 and raw[0] == 0xFF:
        r, g, b = raw[1], raw[2], raw[3]
    elif len(raw) >= 3:
        r, g, b = raw[0], raw[1], raw[2]
    else:
        return None
    if (r, g, b) == (0, 0, 0):
        return None
    return f"#{r:02X}{g:02X}{b:02X}"


def argb_to_rgb(color: bytes) -> tuple[int, int, int] | None:
    if len(color) >= 4 and color[0] == 0xFF:
        return color[1], color[2], color[3]
    if len(color) >= 3:
        return color[0], color[1], color[2]
    return None


def nearest_engine_color(red: int, green: int, blue: int) -> bytes:
    def distance(color: bytes) -> int:
        rgb = argb_to_rgb(color)
        if rgb is None:
            return 1_000_000
        cr, cg, cb = rgb
        return (red - cr) ** 2 + (green - cg) ** 2 + (blue - cb) ** 2

    return min(ENGINE_DJ_CUE_COLORS.values(), key=distance)


def parse_quick_cues(
    blob: bytes,
    performance_id: Any = None,
    track_id: Any = None,
    sample_rate: float | None = 44100.0,
    max_slots: int = 8,
) -> list[Hotcue]:
    data, _ = maybe_decompress(blob)
    cues: list[Hotcue] = []

    if len(data) < 8:
        return cues

    offset = 8
    for slot in range(1, max_slots + 1):
        if offset >= len(data):
            break

        raw_offset = offset
        label_len = data[offset]
        offset += 1

        if label_len == 0:
            if offset + 8 <= len(data):
                offset += 8
            continue

        if offset + label_len > len(data):
            break

        label_bytes = data[offset : offset + label_len]
        label = label_bytes.decode("utf-8", errors="replace")
        offset += label_len

        if offset + 8 > len(data):
            break

        position_samples = struct.unpack(">d", data[offset : offset + 8])[0]
        offset += 8

        color_hex = None
        if offset + 4 <= len(data):
            color_hex = decode_color(data[offset : offset + 4])
            offset += 4

        if position_samples < 0:
            continue

        position_seconds = (
            position_samples / sample_rate if sample_rate and sample_rate > 0 else None
        )
        cues.append(
            Hotcue(
                performance_id=performance_id,
                track_id=track_id,
                cue_number=slot,
                label=label,
                position_samples=position_samples,
                position_seconds=position_seconds,
                color_hex=color_hex,
                raw_offset=raw_offset,
            )
        )

    return cues


def split_quick_cues_blob(blob: bytes, max_slots: int = 8) -> tuple[bytes, dict[int, bytes], bytes]:
    data, _ = maybe_decompress(blob)
    header = data[:8] if len(data) >= 8 else (max_slots).to_bytes(8, "big")
    colors: dict[int, bytes] = {}
    offset = 8

    for slot in range(1, max_slots + 1):
        if offset >= len(data):
            break

        label_len = data[offset]
        offset += 1
        if label_len == 0:
            if offset + 8 <= len(data):
                offset += 8
            continue

        if offset + label_len + 8 > len(data):
            break
        offset += label_len + 8

        if offset + 4 <= len(data):
            colors[slot] = data[offset : offset + 4]
            offset += 4

    return header, colors, data[offset:]


def vdj_color_to_bytes(color_value: str | None) -> bytes | None:
    if not color_value:
        return None
    try:
        value = int(color_value)
    except ValueError:
        return None
    red = (value >> 16) & 0xFF
    green = (value >> 8) & 0xFF
    blue = value & 0xFF
    return nearest_engine_color(red, green, blue)


def encode_quick_cues(
    cues: list[CueWrite],
    existing_blob: bytes | None = None,
    sample_rate: float = 44100.0,
    max_slots: int = 8,
) -> bytes:
    header = max_slots.to_bytes(8, "big")
    existing_colors: dict[int, bytes] = {}
    tail = b""
    if existing_blob:
        header, existing_colors, tail = split_quick_cues_blob(existing_blob, max_slots=max_slots)

    cues_by_slot = {cue.cue_number: cue for cue in cues if 1 <= cue.cue_number <= max_slots}
    payload = bytearray(header)

    for slot in range(1, max_slots + 1):
        cue = cues_by_slot.get(slot)
        if cue is None:
            payload += b"\x00" + struct.pack(">d", -1.0)
            continue

        label = cue.label or f"Cue {slot}"
        label_bytes = label.encode("utf-8")[:255]
        color = cue.color_bytes or existing_colors.get(slot) or ENGINE_DJ_CUE_COLORS[slot]
        position_samples = cue.position_seconds * sample_rate

        payload.append(len(label_bytes))
        payload += label_bytes
        payload += struct.pack(">d", position_samples)
        payload += color[:4].ljust(4, b"\x00")

    payload += tail
    compressed = zlib.compress(bytes(payload))
    return len(payload).to_bytes(4, "big") + compressed


def best_id_column(cols: list[str]) -> str | None:
    for candidate in ("id", "ID", "uuid", "trackId", "track_id", "trackID"):
        found = find_name(cols, candidate)
        if found:
            return found
    return cols[0] if cols else None


def find_track_id_column(cols: list[str]) -> str | None:
    candidates = (
        "trackId",
        "track_id",
        "trackID",
        "trackUuid",
        "trackUUID",
        "track_id_fk",
    )
    for candidate in candidates:
        found = find_name(cols, candidate)
        if found:
            return found
    for col in cols:
        lower = col.lower()
        if "track" in lower and ("id" in lower or "uuid" in lower):
            return col
    return None


def get_track_title_map(conn: sqlite3.Connection) -> dict[Any, str]:
    titles: dict[Any, str] = {}
    for track_id, info in get_track_info_map(conn).items():
        title = info.title or info.filename or str(track_id)
        titles[track_id] = f"{info.artist} - {title}" if info.artist else title
    return titles


def get_track_info_map(conn: sqlite3.Connection) -> dict[Any, TrackInfo]:
    tables = table_names(conn)
    track_table = find_name(tables, "Track")
    if not track_table:
        return {}

    cols = columns(conn, track_table)
    id_col = best_id_column(cols)
    if not id_col:
        return {}

    wanted = {
        "title": find_name(cols, "title") or find_name(cols, "song"),
        "artist": find_name(cols, "artist"),
        "album": find_name(cols, "album"),
        "path": find_name(cols, "path"),
        "filename": find_name(cols, "filename"),
        "length": find_name(cols, "length"),
        "bpm": find_name(cols, "bpm"),
        "key": find_name(cols, "key"),
        "rating": find_name(cols, "rating"),
    }
    selected = [id_col] + [col for col in wanted.values() if col]
    sql = f"SELECT {', '.join(quote_ident(c) for c in selected)} FROM {quote_ident(track_table)}"

    tracks: dict[Any, TrackInfo] = {}
    for row in conn.execute(sql):
        values = dict(zip(selected, row))
        track_id = values.get(id_col)
        tracks[track_id] = TrackInfo(
            track_id=track_id,
            title=values.get(wanted["title"]) or "" if wanted["title"] else "",
            artist=values.get(wanted["artist"]) or "" if wanted["artist"] else "",
            album=values.get(wanted["album"]) or "" if wanted["album"] else "",
            path=values.get(wanted["path"]) or "" if wanted["path"] else "",
            filename=values.get(wanted["filename"]) or "" if wanted["filename"] else "",
            length=values.get(wanted["length"]) if wanted["length"] else None,
            bpm=values.get(wanted["bpm"]) if wanted["bpm"] else None,
            key=values.get(wanted["key"]) or "" if wanted["key"] else "",
            rating=values.get(wanted["rating"]) if wanted["rating"] else None,
        )
    return tracks


def split_music_path(path: str) -> tuple[str, str]:
    normalized = (path or "").replace("\\", "/").strip()
    if "/" not in normalized:
        return "", normalized
    directory, filename = normalized.rsplit("/", 1)
    return directory, filename


def normalize_directory(directory: str) -> str:
    parts = []
    for part in directory.replace("\\", "/").split("/"):
        part = part.strip()
        if not part or part == "." or part == "..":
            continue
        if part.endswith(":"):
            continue
        parts.append(part.lower())
    return "/".join(parts)


def normalize_filename(filename: str) -> str:
    return (filename or "").strip().lower()


def music_match_key(path: str, filename: str = "") -> str:
    directory, path_filename = split_music_path(path)
    final_filename = filename or path_filename
    return f"{normalize_directory(directory)}|{normalize_filename(final_filename)}"


def read_hotcues(conn: sqlite3.Connection, sample_rate: float | None) -> list[Hotcue]:
    tables = table_names(conn)
    perf_table = find_name(tables, "PerformanceData")
    if not perf_table:
        raise RuntimeError("Tabela PerformanceData nao encontrada.")

    cols = columns(conn, perf_table)
    quick_cues_col = find_name(cols, "quickCues")
    if not quick_cues_col:
        raise RuntimeError("Coluna quickCues nao encontrada em PerformanceData.")

    id_col = best_id_column(cols)
    track_id_col = find_track_id_column(cols)

    selected: list[str] = []
    if id_col:
        selected.append(id_col)
    if track_id_col and track_id_col != id_col:
        selected.append(track_id_col)

    selected.append(quick_cues_col)

    sql = f"""
        SELECT {', '.join(quote_ident(c) for c in selected)}
        FROM {quote_ident(perf_table)}
        WHERE {quote_ident(quick_cues_col)} IS NOT NULL
    """

    cues: list[Hotcue] = []

    cursor = conn.execute(sql)

    for row in cursor:
        # garante alinhamento seguro com colunas selecionadas
        values = dict(zip(selected, row))

        blob = values.get(quick_cues_col)

        if blob is None:
            continue

        # SQLite pode retornar memoryview ou str em alguns casos
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        elif isinstance(blob, str):
            blob = blob.encode("latin1", errors="ignore")
        elif not isinstance(blob, (bytes, bytearray)):
            continue

        parsed = parse_quick_cues(
            bytes(blob),
            performance_id=values.get(id_col) if id_col else None,
            track_id=values.get(track_id_col) if track_id_col else None,
            sample_rate=sample_rate,
        )

        if parsed:
            cues.extend(parsed)

    return cues

def get_mp3_tag_cues(track_filename: str) -> list[CueWrite]:
    """
    Lê hotcues diretamente da tag MP3 (ex: serato_markers2)
    e retorna no mesmo formato usado pelo Engine/VinylDJ.
    """
    return []

def format_time(seconds: float | None) -> str:
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes:02d}:{remainder:06.3f}"


def build_web_payload(conn: sqlite3.Connection, sample_rate: float | None) -> dict[str, Any]:
    cues = read_hotcues(conn, sample_rate=sample_rate)
    tracks = get_track_info_map(conn)
    grouped: dict[Any, dict[str, Any]] = {}

    for cue in cues:
        info = tracks.get(cue.track_id)
        title = info.title if info else ""
        filename = info.filename if info else ""
        artist = info.artist if info else ""
        display_title = title or filename or f"Track {cue.track_id}"
        track = grouped.setdefault(
            cue.track_id,
            {
                "track_id": cue.track_id,
                "title": display_title,
                "artist": artist,
                "album": info.album if info else "",
                "path": info.path if info else "",
                "filename": filename,
                "length": info.length if info else None,
                "length_time": format_time(info.length) if info and info.length else "",
                "bpm": info.bpm if info else None,
                "key": info.key if info else "",
                "rating": info.rating if info else None,
                "cues": [],
            },
        )
        track["cues"].append(
            {
                "cue_number": cue.cue_number,
                "label": cue.label,
                "position_samples": cue.position_samples,
                "position_seconds": cue.position_seconds,
                "time": format_time(cue.position_seconds),
                "color_hex": cue.color_hex or "#9CA3AF",
            }
        )

    tracks_list = list(grouped.values())
    tracks_list.sort(key=lambda item: ((item["artist"] or "").lower(), item["title"].lower()))
    for track in tracks_list:
        track["cues"].sort(key=lambda item: item["cue_number"])

    return {
        "generated_by": "engine_hotcues.py",
        "sample_rate": sample_rate,
        "track_count": len(tracks_list),
        "cue_count": len(cues),
        "tracks": tracks_list,
    }


def read_vdj_cues(xml_path: Path, target_filename: str) -> tuple[str, list[CueWrite]]:
    target = target_filename.lower()
    matches: list[tuple[str, list[CueWrite]]] = []

    for _event, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag != "Song":
            continue

        filepath = elem.attrib.get("FilePath", "")
        filename = filepath.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if filename == target or target in filepath.lower():
            cues: list[CueWrite] = []
            for child in elem:
                if child.tag != "Poi" or child.attrib.get("Type", "").lower() != "cue":
                    continue
                try:
                    cue_number = int(child.attrib.get("Num", "0"))
                    position_seconds = float(child.attrib["Pos"])
                except (KeyError, ValueError):
                    continue
                if not 1 <= cue_number <= 8:
                    continue
                label = child.attrib.get("Name") or f"Cue {cue_number}"
                cues.append(
                    CueWrite(
                        cue_number=cue_number,
                        label=label,
                        position_seconds=position_seconds,
                        color_bytes=vdj_color_to_bytes(child.attrib.get("Color")),
                    )
                )
            matches.append((filepath, sorted(cues, key=lambda cue: cue.cue_number)))
        elem.clear()

    if not matches:
        raise RuntimeError(f"Musica nao encontrada no VirtualDJ: {target_filename}")
    if len(matches) > 1:
        paths = "\n".join(path for path, _cues in matches)
        raise RuntimeError(f"Mais de uma musica encontrada no VirtualDJ:\n{paths}")

    return matches[0]


def read_vdj_tracks(xml_path: Path) -> dict[str, VdjTrack]:
    tracks: dict[str, VdjTrack] = {}

    for _event, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag != "Song":
            continue

        filepath = elem.attrib.get("FilePath", "")
        directory, filename = split_music_path(filepath)
        if not filename:
            elem.clear()
            continue

        title = ""
        artist = ""
        cues: list[CueWrite] = []
        for child in elem:
            if child.tag == "Tags":
                title = child.attrib.get("Title", "")
                artist = child.attrib.get("Author", "")
            elif child.tag == "Poi" and child.attrib.get("Type", "").lower() == "cue":
                try:
                    cue_number = int(child.attrib.get("Num", "0"))
                    position_seconds = float(child.attrib["Pos"])
                except (KeyError, ValueError):
                    continue
                if not 1 <= cue_number <= 8:
                    continue
                cues.append(
                    CueWrite(
                        cue_number=cue_number,
                        label=child.attrib.get("Name") or f"Cue {cue_number}",
                        position_seconds=position_seconds,
                        color_bytes=vdj_color_to_bytes(child.attrib.get("Color")),
                    )
                )

        key = music_match_key(filepath)
        if cues:
            tracks[key] = VdjTrack(
                key=key,
                filepath=filepath,
                directory=normalize_directory(directory),
                filename=filename,
                title=title or Path(filename).stem,
                artist=artist,
                cues=sorted(cues, key=lambda cue: cue.cue_number),
            )
        elem.clear()

    return tracks


def build_engine_compare_tracks(conn: sqlite3.Connection, sample_rate: float) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT Track.id, Track.path, Track.filename, Track.title, Track.artist,
               Track.album, Track.length, Track.bpm, Track.key, PerformanceData.quickCues
        FROM Track
        LEFT JOIN PerformanceData ON PerformanceData.trackId = Track.id
        """
    ).fetchall()

    tracks: dict[str, dict[str, Any]] = {}
    for row in rows:
        (
            track_id,
            path,
            filename,
            title,
            artist,
            album,
            length,
            bpm,
            track_key,
            quick_cues,
        ) = row
        match_key = music_match_key(path or "", filename or "")
        cues = (
            parse_quick_cues(bytes(quick_cues), track_id=track_id, sample_rate=sample_rate)
            if quick_cues
            else []
        )
        directory, _path_filename = split_music_path(path or "")
        tracks[match_key] = {
            "track_id": track_id,
            "path": path or "",
            "directory": normalize_directory(directory),
            "filename": filename or "",
            "title": title or Path(filename or "").stem or f"Track {track_id}",
            "artist": artist or "",
            "album": album or "",
            "length": length,
            "bpm": bpm,
            "key": track_key or "",
            "cues": cues,
        }
    return tracks


def cue_to_payload(cue: Hotcue | CueWrite) -> dict[str, Any]:
    if isinstance(cue, Hotcue):
        color_hex = cue.color_hex or "#9CA3AF"
        position_seconds = cue.position_seconds
    else:
        color_hex = decode_color(cue.color_bytes or b"") or "#9CA3AF"
        position_seconds = cue.position_seconds
    return {
        "cue_number": cue.cue_number,
        "label": cue.label,
        "time": format_time(position_seconds),
        "position_seconds": position_seconds,
        "color_hex": color_hex,
    }

def normalize_cue_from_tag(cue: CueWrite, tag_time: float | None) -> CueWrite:
    """
    Ajusta o cue usando referência da TAG (Serato / MP3).
    Essa função passa a ser a fonte única de verdade.
    """
    if tag_time is not None:
        cue.position_seconds = tag_time
    return cue

def expected_vdj_cue_payload(cue: CueWrite, engine_color_by_slot: dict[int, str]) -> dict[str, Any]:
    color_hex = decode_color(cue.color_bytes or b"")
    if color_hex is None:
        color_hex = engine_color_by_slot.get(cue.cue_number)
    if color_hex is None:
        color_hex = decode_color(ENGINE_DJ_CUE_COLORS.get(cue.cue_number, b"")) or "#9CA3AF"
    return {
        "cue_number": cue.cue_number,
        "label": cue.label,
        "time": format_time(cue.position_seconds),
        "position_seconds": cue.position_seconds,
        "color_hex": color_hex,
    }


def cue_compare_signature(cues: list[dict[str, Any]]) -> list[tuple[int, str, float, str]]:
    signature = []
    for cue in cues:
        seconds = cue.get("position_seconds")
        signature.append(
            (
                int(cue.get("cue_number") or 0),
                str(cue.get("label") or ""),
                round(float(seconds or 0), 3),
                str(cue.get("color_hex") or ""),
            )
        )
    return sorted(signature)


def build_compare_payload(db_path: Path, xml_path: Path, sample_rate: float) -> dict[str, Any]:
    with connect_readonly(db_path) as conn:
        engine_tracks = build_engine_compare_tracks(conn, sample_rate)
    vdj_tracks = read_vdj_tracks(xml_path)

    matches = []
    for key in sorted(set(engine_tracks) & set(vdj_tracks)):
        engine = engine_tracks[key]
        vdj = vdj_tracks[key]
        engine_cues = [cue_to_payload(cue) for cue in engine["cues"]]
        engine_color_by_slot = {
            int(cue["cue_number"]): str(cue["color_hex"])
            for cue in engine_cues
            if cue.get("color_hex")
        }
        vdj_cues = [expected_vdj_cue_payload(cue, engine_color_by_slot) for cue in vdj.cues]
        is_synced = cue_compare_signature(engine_cues) == cue_compare_signature(vdj_cues)
        matches.append(
            {
                "key": key,
                "track_id": engine["track_id"],
                "is_synced": is_synced,
                "engine": {
                    "title": engine["title"],
                    "artist": engine["artist"],
                    "directory": engine["directory"],
                    "filename": engine["filename"],
                    "path": engine["path"],
                    "cues": engine_cues,
                },
                "virtualdj": {
                    "title": vdj.title,
                    "artist": vdj.artist,
                    "directory": vdj.directory,
                    "filename": vdj.filename,
                    "path": vdj.filepath,
                    "cues": vdj_cues,
                },
            }
        )

    return {
        "engine_count": len(engine_tracks),
        "virtualdj_with_cues_count": len(vdj_tracks),
        "match_count": len(matches),
        "synced_count": sum(1 for match in matches if match["is_synced"]),
        "matches": matches,
    }


def import_vdj_matches(
    db_path: Path,
    xml_path: Path,
    selected_keys: list[str],
    sample_rate: float,
) -> dict[str, Any]:
    if not selected_keys:
        return {"updated": 0, "backup": "", "tracks": []}

    vdj_tracks = read_vdj_tracks(xml_path)
    selected = [key for key in selected_keys if key in vdj_tracks]
    if not selected:
        return {"updated": 0, "backup": "", "tracks": []}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.backup-{stamp}")
    shutil.copy2(db_path, backup_path)

    updated_tracks = []
    conn = sqlite3.connect(db_path)
    try:
        engine_tracks = build_engine_compare_tracks(conn, sample_rate)
        with conn:
            for key in selected:
                engine = engine_tracks.get(key)
                vdj = vdj_tracks.get(key)
                if not engine or not vdj:
                    continue
                existing_row = conn.execute(
                    "SELECT quickCues FROM PerformanceData WHERE trackId = ?",
                    (engine["track_id"],),
                ).fetchone()
                existing_blob = existing_row[0] if existing_row else None
                new_blob = encode_quick_cues(
                    vdj.cues,
                    existing_blob=bytes(existing_blob) if existing_blob else None,
                    sample_rate=sample_rate,
                )
                if existing_row:
                    conn.execute(
                        "UPDATE PerformanceData SET quickCues = ? WHERE trackId = ?",
                        (sqlite3.Binary(new_blob), engine["track_id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO PerformanceData (trackId, quickCues) VALUES (?, ?)",
                        (engine["track_id"], sqlite3.Binary(new_blob)),
                    )
                updated_tracks.append(
                    {
                        "track_id": engine["track_id"],
                        "filename": engine["filename"],
                        "cue_count": len(vdj.cues),
                    }
                )
    finally:
        conn.close()

    return {
        "updated": len(updated_tracks),
        "backup": str(backup_path.resolve()),
        "tracks": updated_tracks,
    }


def render_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Engine DJ Hotcues</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-soft: #eef2f6;
      --text: #16202a;
      --muted: #617080;
      --line: #d9e0e7;
      --accent: #0f766e;
      --accent-strong: #0b5f59;
      --shadow: 0 14px 34px rgba(22, 32, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.4;
    }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    header {{
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 18px 24px;
      position: sticky;
      top: 0;
      z-index: 5;
    }}
    .topbar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: center;
      max-width: 1180px;
      margin: 0 auto;
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 4px;
      font-weight: 720;
      letter-spacing: 0;
    }}
    .summary {{
      color: var(--muted);
      font-size: 14px;
    }}
    .search {{
      width: min(360px, 42vw);
      border: 1px solid var(--line);
      background: var(--panel-soft);
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 15px;
      color: var(--text);
      outline: none;
    }}
    .search:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.15);
    }}
    main {{
      max-width: 1180px;
      width: 100%;
      margin: 0 auto;
      padding: 24px;
    }}
    .track-list {{
      display: grid;
      gap: 16px;
    }}
    .track-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .track-head {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      padding: 18px 18px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .track-title {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .artist {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      align-content: start;
    }}
    .pill {{
      min-height: 30px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      background: #fafbfc;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .cue-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      padding: 14px 18px 18px;
    }}
    .cue {{
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 10px;
      min-height: 72px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfd;
    }}
    .cue-number {{
      width: 42px;
      height: 42px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--cue-color);
      color: #111827;
      font-weight: 800;
      border: 1px solid rgba(0, 0, 0, 0.12);
    }}
    .cue-label {{
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .cue-time {{
      margin-top: 2px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      font-size: 13px;
    }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }}
    @media (max-width: 720px) {{
      header {{ padding: 16px; }}
      .topbar {{ grid-template-columns: 1fr; }}
      .search {{ width: 100%; }}
      main {{ padding: 16px; }}
      .track-head {{ grid-template-columns: 1fr; }}
      .meta {{ justify-content: flex-start; }}
      .cue-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="topbar">
        <div>
          <h1>Engine DJ Hotcues</h1>
          <div class="summary" id="summary"></div>
        </div>
        <input class="search" id="search" type="search" placeholder="Buscar musica, artista ou cue">
      </div>
    </header>
    <main>
      <div class="track-list" id="trackList"></div>
      <div class="empty" id="empty" hidden>Nenhuma musica encontrada.</div>
    </main>
  </div>
  <script>
    const data = {payload_json};
    const trackList = document.querySelector("#trackList");
    const search = document.querySelector("#search");
    const empty = document.querySelector("#empty");
    const summary = document.querySelector("#summary");

    function text(value) {{
      return value === null || value === undefined || value === "" ? "" : String(value);
    }}

    function metaPill(label) {{
      const span = document.createElement("span");
      span.className = "pill";
      span.textContent = label;
      return span;
    }}

    function render(tracks) {{
      trackList.textContent = "";
      empty.hidden = tracks.length !== 0;

      for (const track of tracks) {{
        const card = document.createElement("article");
        card.className = "track-card";

        const head = document.createElement("div");
        head.className = "track-head";

        const titleBox = document.createElement("div");
        const title = document.createElement("h2");
        title.className = "track-title";
        title.textContent = track.title;
        const artist = document.createElement("div");
        artist.className = "artist";
        artist.textContent = track.artist || track.filename || `Track ID ${{track.track_id}}`;
        titleBox.append(title, artist);

        const meta = document.createElement("div");
        meta.className = "meta";
        meta.append(metaPill(`${{track.cues.length}} hotcues`));
        if (track.length_time) meta.append(metaPill(track.length_time));
        if (track.bpm) meta.append(metaPill(`${{Number(track.bpm).toFixed(1)}} BPM`));
        if (track.key) meta.append(metaPill(track.key));
        if (track.rating) meta.append(metaPill(`${{track.rating}} estrelas`));

        head.append(titleBox, meta);

        const cueGrid = document.createElement("div");
        cueGrid.className = "cue-grid";
        for (const cue of track.cues) {{
          const cueEl = document.createElement("div");
          cueEl.className = "cue";
          cueEl.style.setProperty("--cue-color", cue.color_hex || "#9CA3AF");

          const num = document.createElement("div");
          num.className = "cue-number";
          num.textContent = cue.cue_number;

          const body = document.createElement("div");
          const label = document.createElement("div");
          label.className = "cue-label";
          label.textContent = cue.label || `Cue ${{cue.cue_number}}`;
          const time = document.createElement("div");
          time.className = "cue-time";
          time.textContent = cue.time;
          body.append(label, time);

          cueEl.append(num, body);
          cueGrid.append(cueEl);
        }}

        card.append(head, cueGrid);
        trackList.append(card);
      }}
    }}

    function matches(track, query) {{
      const haystack = [
        track.title,
        track.artist,
        track.album,
        track.filename,
        ...track.cues.map((cue) => `${{cue.label}} ${{cue.time}} ${{cue.cue_number}}`)
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    }}

    function update() {{
      const query = search.value.trim().toLowerCase();
      const tracks = query ? data.tracks.filter((track) => matches(track, query)) : data.tracks;
      summary.textContent = `${{tracks.length}} musica(s), ${{tracks.reduce((sum, track) => sum + track.cues.length, 0)}} hotcue(s)`;
      render(tracks);
    }}

    search.addEventListener("input", update);
    update();
  </script>
</body>
</html>
"""


def render_compare_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comparar Hotcues</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-soft: #eef3f6;
      --text: #17212b;
      --muted: #647282;
      --line: #d8e0e7;
      --accent: #0f766e;
      --accent-dark: #0b5f59;
      --warn: #a16207;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.4;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 16px 22px;
    }}
    .topbar {{
      max-width: 1380px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 23px;
      letter-spacing: 0;
    }}
    .summary {{
      color: var(--muted);
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    input[type="search"] {{
      width: 320px;
      max-width: 42vw;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 14px;
      outline: none;
    }}
    input[type="search"]:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.16);
    }}
    button {{
      border: 0;
      border-radius: 8px;
      min-height: 40px;
      padding: 0 14px;
      font-weight: 700;
      background: var(--accent);
      color: #fff;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-dark); }}
    button:disabled {{
      opacity: 0.48;
      cursor: not-allowed;
    }}
    .secondary {{
      background: #334155;
    }}
    .secondary:hover {{
      background: #1f2937;
    }}
    main {{
      max-width: 1380px;
      margin: 0 auto;
      padding: 18px 22px 28px;
    }}
    .status {{
      min-height: 22px;
      color: var(--muted);
      margin-bottom: 12px;
      font-size: 14px;
    }}
    .status strong {{ color: var(--accent-dark); }}
    .match-list {{
      display: grid;
      gap: 14px;
    }}
    .match {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .row-head {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }}
    .filename {{
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .dir {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .select-box {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
      font-weight: 650;
      color: var(--text);
      white-space: nowrap;
    }}
    .select-box input {{
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .badge.synced {{
      border-color: rgba(15, 118, 110, .28);
      background: rgba(15, 118, 110, .09);
      color: var(--accent-dark);
    }}
    .badge.pending {{
      border-color: rgba(161, 98, 7, .28);
      background: rgba(161, 98, 7, .09);
      color: var(--warn);
    }}
    .columns {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      min-height: 150px;
    }}
    .side {{
      padding: 14px 16px 16px;
    }}
    .side + .side {{
      border-left: 1px solid var(--line);
    }}
    .side-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
      text-transform: uppercase;
    }}
    .track-title {{
      font-size: 16px;
      font-weight: 720;
      overflow-wrap: anywhere;
    }}
    .artist {{
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
      margin-top: 2px;
    }}
    .cue-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(136px, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .cue {{
      display: grid;
      grid-template-columns: 34px 1fr;
      gap: 8px;
      align-items: center;
      min-height: 58px;
      border: 1px solid var(--line);
      background: #fbfcfd;
      border-radius: 8px;
      padding: 8px;
    }}
    .num {{
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      border-radius: 7px;
      background: var(--cue);
      border: 1px solid rgba(0,0,0,.14);
      font-weight: 800;
      font-size: 13px;
    }}
    .cue-label {{
      font-weight: 650;
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .cue-time {{
      color: var(--muted);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }}
    @media (max-width: 860px) {{
      .topbar {{ grid-template-columns: 1fr; }}
      .actions {{ justify-content: stretch; }}
      input[type="search"] {{ width: 100%; max-width: none; }}
      button {{ width: 100%; }}
      .columns {{ grid-template-columns: 1fr; }}
      .side + .side {{ border-left: 0; border-top: 1px solid var(--line); }}
      .row-head {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>Comparar Hotcues</h1>
        <div class="summary" id="summary"></div>
      </div>
      <div class="actions">
        <input id="search" type="search" placeholder="Buscar musica ou diretorio">
        <button class="secondary" id="refreshBtn">Atualizar informacoes</button>
        <button id="updateBtn" disabled>Atualizar selecionadas</button>
      </div>
    </div>
  </header>
  <main>
    <div class="status" id="status"></div>
    <div class="match-list" id="matchList"></div>
    <div class="empty" id="empty" hidden>Nenhuma musica igual encontrada.</div>
  </main>
  <script>
    let data = {payload_json};
    const selected = new Set();
    const search = document.querySelector("#search");
    const refreshBtn = document.querySelector("#refreshBtn");
    const updateBtn = document.querySelector("#updateBtn");
    const matchList = document.querySelector("#matchList");
    const summary = document.querySelector("#summary");
    const status = document.querySelector("#status");
    const empty = document.querySelector("#empty");

    function cueCard(cue) {{
      const el = document.createElement("div");
      el.className = "cue";
      el.style.setProperty("--cue", cue.color_hex || "#9CA3AF");
      const num = document.createElement("div");
      num.className = "num";
      num.textContent = cue.cue_number;
      const body = document.createElement("div");
      const label = document.createElement("div");
      label.className = "cue-label";
      label.textContent = cue.label || `Cue ${{cue.cue_number}}`;
      const time = document.createElement("div");
      time.className = "cue-time";
      time.textContent = cue.time || "";
      body.append(label, time);
      el.append(num, body);
      return el;
    }}

    function side(title, track) {{
      const el = document.createElement("section");
      el.className = "side";
      const head = document.createElement("div");
      head.className = "side-title";
      head.textContent = title;
      const trackTitle = document.createElement("div");
      trackTitle.className = "track-title";
      trackTitle.textContent = track.title || track.filename;
      const artist = document.createElement("div");
      artist.className = "artist";
      artist.textContent = track.artist || track.path;
      const cueGrid = document.createElement("div");
      cueGrid.className = "cue-grid";
      for (const cue of track.cues) cueGrid.append(cueCard(cue));
      el.append(head, trackTitle, artist, cueGrid);
      return el;
    }}

    function visibleMatches() {{
      const q = search.value.trim().toLowerCase();
      if (!q) return data.matches;
      return data.matches.filter((match) => [
        match.engine.title,
        match.engine.artist,
        match.engine.directory,
        match.engine.filename,
        match.virtualdj.title,
        match.virtualdj.artist,
        match.virtualdj.directory,
        match.virtualdj.filename
      ].join(" ").toLowerCase().includes(q));
    }}

    function render() {{
      const matches = visibleMatches();
      matchList.textContent = "";
      empty.hidden = matches.length !== 0;
      summary.textContent = `${{data.match_count}} musica(s) iguais | ${{data.synced_count}} sincronizada(s) | Engine DJ: ${{data.engine_count}} | VirtualDJ com cues: ${{data.virtualdj_with_cues_count}}`;

      for (const match of matches) {{
        const row = document.createElement("article");
        row.className = "match";

        const rowHead = document.createElement("div");
        rowHead.className = "row-head";
        const left = document.createElement("div");
        const filename = document.createElement("div");
        filename.className = "filename";
        filename.textContent = match.engine.filename;
        const dir = document.createElement("div");
        dir.className = "dir";
        dir.textContent = match.engine.directory;
        left.append(filename, dir);

        const statusBadge = document.createElement("span");
        statusBadge.className = `badge ${{match.is_synced ? "synced" : "pending"}}`;
        statusBadge.textContent = match.is_synced ? "Sincronizada" : "Diferente";

        const label = document.createElement("label");
        label.className = "select-box";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = selected.has(match.key);
        cb.addEventListener("change", () => {{
          if (cb.checked) selected.add(match.key);
          else selected.delete(match.key);
          updateBtn.disabled = selected.size === 0;
        }});
        label.append(cb, document.createTextNode("Selecionar"));
        const rowActions = document.createElement("div");
        rowActions.className = "actions";
        rowActions.append(statusBadge, label);
        rowHead.append(left, rowActions);

        const columns = document.createElement("div");
        columns.className = "columns";
        columns.append(side("Engine DJ", match.engine), side("VirtualDJ", match.virtualdj));

        row.append(rowHead, columns);
        matchList.append(row);
      }}
      updateBtn.disabled = selected.size === 0;
    }}

    async function refreshData(message) {{
      refreshBtn.disabled = true;
      updateBtn.disabled = true;
      status.textContent = message || "Atualizando informacoes dos bancos...";
      try {{
        const response = await fetch(`/api/matches?ts=${{Date.now()}}`);
        const nextData = await response.json();
        if (!response.ok) {{
          status.textContent = nextData.error || "Erro ao atualizar informacoes.";
          return;
        }}
        data = nextData;
        for (const key of Array.from(selected)) {{
          if (!data.matches.some((match) => match.key === key)) selected.delete(key);
        }}
        status.textContent = `Informacoes atualizadas. ${{data.synced_count}} de ${{data.match_count}} musica(s) sincronizada(s).`;
        render();
      }} catch (error) {{
        status.textContent = `Erro ao atualizar informacoes: ${{error.message}}`;
      }} finally {{
        refreshBtn.disabled = false;
        updateBtn.disabled = selected.size === 0;
      }}
    }}

    async function updateSelected() {{
      if (selected.size === 0) return;
      const keysToUpdate = Array.from(selected);
      const total = selected.size;
      const ok = confirm(`Atualizar ${{total}} musica(s) selecionada(s) no banco do Engine DJ?`);
      if (!ok) return;
      refreshBtn.disabled = true;
      updateBtn.disabled = true;
      status.textContent = "Atualizando...";
      const response = await fetch("/api/import", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ keys: keysToUpdate }})
      }});
      const result = await response.json();
      if (!response.ok) {{
        status.textContent = result.error || "Erro ao atualizar.";
        refreshBtn.disabled = false;
        render();
        return;
      }}
      selected.clear();
      const freshResponse = await fetch(`/api/matches?ts=${{Date.now()}}`);
      data = await freshResponse.json();
      const updatedSet = new Set(keysToUpdate);
      const verified = data.matches.filter((match) => updatedSet.has(match.key) && match.is_synced).length;
      status.innerHTML = `<strong>${{result.updated}}</strong> musica(s) atualizada(s). Verificadas no Engine DJ: <strong>${{verified}}</strong>. Backup: ${{result.backup}}`;
      refreshBtn.disabled = false;
      render();
    }}

    search.addEventListener("input", render);
    refreshBtn.addEventListener("click", () => refreshData());
    updateBtn.addEventListener("click", updateSelected);
    render();
  </script>
</body>
</html>
"""


def cmd_inspect(args: argparse.Namespace) -> int:
    with connect_readonly(Path(args.db)) as conn:
        for table in table_names(conn):
            cols = columns(conn, table)
            count = conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0]
            print(f"{table} ({count} linhas)")
            print("  " + ", ".join(cols))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with connect_readonly(Path(args.db)) as conn:
        cues = read_hotcues(conn, sample_rate=args.sample_rate)
        track_titles = get_track_title_map(conn)

    if args.format == "json":
        print(json.dumps([asdict(cue) for cue in cues], indent=2, ensure_ascii=False))
        return 0

    if args.format == "csv":
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=[
                "performance_id",
                "track_id",
                "track",
                "cue_number",
                "label",
                "position_samples",
                "position_seconds",
                "time",
                "color_hex",
            ],
        )
        writer.writeheader()
        for cue in cues:
            row = asdict(cue)
            row["track"] = track_titles.get(cue.track_id, "")
            row["time"] = format_time(cue.position_seconds)
            row.pop("raw_offset", None)
            writer.writerow(row)
        return 0

    if not cues:
        print("Nenhum hotcue encontrado.")
        return 0

    for cue in cues:
        track = track_titles.get(cue.track_id, "")
        track_text = f" | {track}" if track else ""
        color_text = f" | {cue.color_hex}" if cue.color_hex else ""
        print(
            f"track_id={cue.track_id} cue={cue.cue_number} "
            f"time={format_time(cue.position_seconds)} "
            f"samples={cue.position_samples:.0f} label={cue.label!r}"
            f"{color_text}{track_text}"
        )
    print(f"\nTotal: {len(cues)} hotcue(s).")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    output_path = Path(args.output)
    with connect_readonly(db_path) as conn:
        payload = build_web_payload(conn, sample_rate=args.sample_rate)

    output_path.write_text(render_html(payload), encoding="utf-8")
    print(f"Pagina criada: {output_path.resolve()}")
    print(f"Musicas: {payload['track_count']} | Hotcues: {payload['cue_count']}")
    return 0


def cmd_import_vdj(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    xml_path = Path(args.xml)
    target_filename = args.filename

    vdj_path, vdj_cues = read_vdj_cues(xml_path, target_filename)
    if not vdj_cues:
        raise RuntimeError(f"Nenhum hotcue Type='cue' encontrado no VirtualDJ para {target_filename}.")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        row = conn.execute(
            """
            SELECT Track.id, Track.filename, Track.title, Track.artist, PerformanceData.quickCues
            FROM Track
            JOIN PerformanceData ON PerformanceData.trackId = Track.id
            WHERE lower(Track.filename) = lower(?)
            """,
            (target_filename,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Musica nao encontrada no Engine DJ: {target_filename}")

        track_id, filename, title, artist, existing_blob = row
        new_blob = encode_quick_cues(
            vdj_cues,
            existing_blob=bytes(existing_blob) if existing_blob else None,
            sample_rate=args.sample_rate,
        )

        backup_path = None
        if not args.no_backup and not args.dry_run:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = db_path.with_name(f"{db_path.name}.backup-{stamp}")
            shutil.copy2(db_path, backup_path)

        if args.dry_run:
            print("DRY RUN: nenhuma alteracao foi gravada.")
        else:
            with conn:
                conn.execute(
                    "UPDATE PerformanceData SET quickCues = ? WHERE trackId = ?",
                    (sqlite3.Binary(new_blob), track_id),
                )

        track_name = f"{artist} - {title}" if artist else title or filename
        print(f"VirtualDJ: {vdj_path}")
        print(f"Engine DJ: track_id={track_id} | {track_name}")
        if backup_path:
            print(f"Backup: {backup_path.resolve()}")
        for cue in vdj_cues:
            print(f"cue={cue.cue_number} time={format_time(cue.position_seconds)} label={cue.label!r}")
        return 0
    finally:
        conn.close()


def make_compare_handler(db_path: Path, xml_path: Path, sample_rate: float):
    class CompareHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}")

        def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/api/matches":
                    self.send_json(build_compare_payload(db_path, xml_path, sample_rate))
                    return
                if path in ("/", "/index.html"):
                    payload = build_compare_payload(db_path, xml_path, sample_rate)
                    body = render_compare_html(payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/import":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8")) if body else {}
                keys = payload.get("keys", [])
                if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                    self.send_json({"error": "Lista de musicas selecionadas invalida."}, status=400)
                    return
                result = import_vdj_matches(db_path, xml_path, keys, sample_rate)
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

    return CompareHandler


def cmd_compare_web(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    xml_path = Path(args.xml)
    payload = build_compare_payload(db_path, xml_path, args.sample_rate)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_compare_handler(db_path, xml_path, args.sample_rate),
    )
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"Painel aberto em: {url}", flush=True)
    print(
        f"Iguais: {payload['match_count']} | "
        f"Engine DJ: {payload['engine_count']} | "
        f"VirtualDJ com cues: {payload['virtualdj_with_cues_count']}",
        flush=True,
    )
    print("Pressione Ctrl+C para encerrar.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and list Engine DJ hotcues from an m.db database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Show tables and columns in the Engine DJ database."
    )
    inspect_parser.add_argument("db", help="Path to Engine DJ m.db")
    inspect_parser.set_defaults(func=cmd_inspect)

    list_parser = subparsers.add_parser(
        "list", help="Decode and list PerformanceData.quickCues hotcues."
    )
    list_parser.add_argument("db", help="Path to Engine DJ m.db")
    list_parser.add_argument(
        "--sample-rate",
        type=float,
        default=44100.0,
        help="Sample rate used to convert Engine sample positions to seconds.",
    )
    list_parser.add_argument(
        "--format",
        choices=("text", "csv", "json"),
        default="text",
        help="Output format.",
    )
    list_parser.set_defaults(func=cmd_list)

    web_parser = subparsers.add_parser(
        "web", help="Generate a standalone HTML page grouped by music."
    )
    web_parser.add_argument("db", help="Path to Engine DJ m.db")
    web_parser.add_argument(
        "--output",
        default="hotcues.html",
        help="HTML file to create.",
    )
    web_parser.add_argument(
        "--sample-rate",
        type=float,
        default=44100.0,
        help="Sample rate used to convert Engine sample positions to seconds.",
    )
    web_parser.set_defaults(func=cmd_web)

    import_parser = subparsers.add_parser(
        "import-vdj", help="Import VirtualDJ hotcues into one Engine DJ track."
    )
    import_parser.add_argument("xml", help="Path to VirtualDJ database.xml")
    import_parser.add_argument("db", help="Path to Engine DJ m.db")
    import_parser.add_argument(
        "--filename",
        required=True,
        help="Exact audio filename to update in Engine DJ.",
    )
    import_parser.add_argument(
        "--sample-rate",
        type=float,
        default=44100.0,
        help="Sample rate used to convert VirtualDJ seconds to Engine sample positions.",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without writing to m.db.",
    )
    import_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create an automatic m.db backup before writing.",
    )
    import_parser.set_defaults(func=cmd_import_vdj)

    compare_parser = subparsers.add_parser(
        "compare-web",
        help="Open a local web panel to compare and selectively import VirtualDJ hotcues.",
    )
    compare_parser.add_argument("xml", help="Path to VirtualDJ database.xml")
    compare_parser.add_argument("db", help="Path to Engine DJ m.db")
    compare_parser.add_argument("--host", default="127.0.0.1", help="HTTP host.")
    compare_parser.add_argument("--port", type=int, default=8765, help="HTTP port.")
    compare_parser.add_argument(
        "--sample-rate",
        type=float,
        default=44100.0,
        help="Sample rate used to convert VirtualDJ seconds to Engine sample positions.",
    )
    compare_parser.set_defaults(func=cmd_compare_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except sqlite3.Error as exc:
        print(f"Erro SQLite: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
