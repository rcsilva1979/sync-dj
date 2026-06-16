#!/usr/bin/env python3
"""Read MP3 ID3 tags and report possible DJ hotcue metadata as JSON.

The script is dependency-free on purpose. It understands the ID3 container and
decodes common text/object/private frames enough to find hotcue-like metadata
from DJ tools such as Serato, Rekordbox and Traktor.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HOTCUE_WORDS = (
    "hotcue",
    "hot cue",
    "cue",
    "marker",
    "markers",
    "serato",
    "rekordbox",
    "traktor",
    "mixxx",
    "beatgrid",
)


@dataclass
class Id3Frame:
    """
    Representa um frame ID3v2, contendo seu ID, tamanho, flags, dados e offset.
    """
    frame_id: str
    size: int
    flags: bytes
    data: bytes
    offset: int


def synchsafe_to_int(raw: bytes) -> int:
    """
    Converte um inteiro "synchsafe" (usado em ID3v2.3 e ID3v2.4) para um inteiro normal.
    """
    value = 0
    for byte in raw:
        value = (value << 7) | (byte & 0x7F)
    return value


def int24(raw: bytes) -> int:
    """
    Converte 3 bytes em um inteiro de 24 bits.
    """
    return (raw[0] << 16) | (raw[1] << 8) | raw[2]


def remove_unsynchronisation(data: bytes) -> bytes:
    """
    Remove bytes de "dessincronização" (0xFF 0x00) dos dados, conforme especificado em ID3v2.
    """
    return data.replace(b"\xff\x00", b"\xff")


def decode_text_payload(data: bytes) -> str:
    """
    Decodifica o payload de texto de um frame ID3, considerando diferentes codificações.
    """
    if not data:
        return ""

    encoding = data[0]
    payload = data[1:]
    if encoding == 0:
        return payload.rstrip(b"\x00").decode("latin-1", errors="replace")
    if encoding == 1:
        return payload.rstrip(b"\x00").decode("utf-16", errors="replace")
    if encoding == 2:
        return payload.rstrip(b"\x00").decode("utf-16-be", errors="replace")
    if encoding == 3:
        return payload.rstrip(b"\x00").decode("utf-8", errors="replace")

    return payload.decode("utf-8", errors="replace")


def split_encoded_pair(data: bytes) -> tuple[str, str]:
    """
    Divide um payload de texto codificado em dois, usando o separador nulo apropriado para a codificação.
    """
    if not data:
        return "", ""

    encoding = data[0]
    payload = data[1:]
    separator = b"\x00\x00" if encoding in (1, 2) else b"\x00"
    left, _, right = payload.partition(separator)

    return decode_text_payload(bytes([encoding]) + left), decode_text_payload(
        bytes([encoding]) + right
    )


def split_latin1_pair(data: bytes) -> tuple[str, bytes]:
    """
    Divide um payload de bytes em duas partes, usando o primeiro byte nulo como separador,
    decodificando a primeira parte como latin-1.
    """
    left, _, right = data.partition(b"\x00")
    return left.decode("latin-1", errors="replace"), right


def parse_id3_frames(path: Path) -> tuple[dict[str, Any], list[Id3Frame]]:
    """
    Analisa um arquivo MP3 para extrair o cabeçalho ID3v2 e todos os seus frames.
    """
    with path.open("rb") as handle:
        header = handle.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            raise ValueError("arquivo nao contem tag ID3v2 no inicio")

        version_major = header[3]
        version_minor = header[4]
        flags = header[5]
        tag_size = synchsafe_to_int(header[6:10])
        tag_data = handle.read(tag_size)

    if flags & 0x80:
        tag_data = remove_unsynchronisation(tag_data)

    position = 0
    if flags & 0x40 and version_major in (3, 4):
        if len(tag_data) < 4:
            raise ValueError("cabecalho estendido ID3 invalido")
        ext_size = (
            synchsafe_to_int(tag_data[:4])
            if version_major == 4
            else int.from_bytes(tag_data[:4], "big")
        )
        position += ext_size if version_major == 4 else ext_size + 4

    frames: list[Id3Frame] = []
    while position < len(tag_data):
        if version_major == 2:
            if position + 6 > len(tag_data):
                break
            frame_id_bytes = tag_data[position : position + 3]
            if not frame_id_bytes.strip(b"\x00"):
                break
            frame_id = frame_id_bytes.decode("latin-1", errors="replace")
            size = int24(tag_data[position + 3 : position + 6])
            data_start = position + 6
            flags_raw = b""
        else:
            if position + 10 > len(tag_data):
                break
            frame_id_bytes = tag_data[position : position + 4]
            if not frame_id_bytes.strip(b"\x00"):
                break
            frame_id = frame_id_bytes.decode("latin-1", errors="replace")
            size_raw = tag_data[position + 4 : position + 8]
            size = synchsafe_to_int(size_raw) if version_major == 4 else int.from_bytes(size_raw, "big")
            flags_raw = tag_data[position + 8 : position + 10]
            data_start = position + 10

        data_end = data_start + size
        if size <= 0 or data_end > len(tag_data):
            break

        frames.append(Id3Frame(frame_id, size, flags_raw, tag_data[data_start:data_end], position))
        position = data_end

    metadata = {
        "version": f"ID3v2.{version_major}.{version_minor}",
        "flags": flags,
        "tag_size": tag_size,
        "frame_count": len(frames),
    }
    return metadata, frames


def parse_frame(frame: Id3Frame) -> dict[str, Any]:
    """
    Analisa os dados de um frame ID3 específico e retorna um dicionário com suas propriedades.
    """
    item: dict[str, Any] = {
        "id": frame.frame_id,
        "size": frame.size,
        "offset": frame.offset,
    }

    if frame.frame_id.startswith("T"):
        if frame.frame_id == "TXXX":
            description, value = split_encoded_pair(frame.data)
            item.update({"description": description, "value": value})
        else:
            item["value"] = decode_text_payload(frame.data)
    elif frame.frame_id == "COMM":
        encoding = frame.data[0] if frame.data else 0
        language = frame.data[1:4].decode("latin-1", errors="replace") if len(frame.data) >= 4 else ""
        description, value = split_encoded_pair(bytes([encoding]) + frame.data[4:])
        item.update({"language": language, "description": description, "value": value})
    elif frame.frame_id == "GEOB":
        item.update(parse_geob(frame.data))
    elif frame.frame_id == "PRIV":
        owner, payload = split_latin1_pair(frame.data)
        item.update({"owner": owner, "payload": describe_binary(payload)})
    elif frame.frame_id == "UFID":
        owner, payload = split_latin1_pair(frame.data)
        item.update({"owner": owner, "identifier": describe_binary(payload)})
    else:
        item["payload"] = describe_binary(frame.data)

    return item


def parse_geob(data: bytes) -> dict[str, Any]:
    """
    Analisa os dados de um frame GEOB (General Encapsulated Object) e extrai suas propriedades.
    """
    if not data:
        return {"mime": "", "filename": "", "description": "", "payload": describe_binary(b"")}

    encoding = data[0]
    rest = data[1:]
    mime_raw, _, rest = rest.partition(b"\x00")
    mime = mime_raw.decode("latin-1", errors="replace")

    separator = b"\x00\x00" if encoding in (1, 2) else b"\x00"
    filename_raw, _, rest = rest.partition(separator)
    description_raw, _, payload = rest.partition(separator)

    filename = decode_text_payload(bytes([encoding]) + filename_raw)
    description = decode_text_payload(bytes([encoding]) + description_raw)

    return {
        "mime": mime,
        "filename": filename,
        "description": description,
        "payload": describe_binary(payload),
    }


def describe_binary(data: bytes) -> dict[str, Any]:
    """
    Descreve um blob de dados binários, incluindo seu tamanho e uma representação em base64.
    """
    text = printable_text(data)
    result: dict[str, Any] = {
        "size": len(data),
        "base64": base64.b64encode(data).decode("ascii") if data else "",
    }
    if text:
        result["text"] = text
    return result


def printable_text(data: bytes) -> str:
    """
    Tenta decodificar um blob de bytes em uma string legível, testando diferentes codificações.
    """
    if not data:
        return ""

    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        cleaned = text.replace("\x00", " ").strip()
        printable = sum(1 for char in cleaned if char.isprintable())
        if cleaned and printable / max(len(cleaned), 1) > 0.85:
            return re.sub(r"\s+", " ", cleaned)
    return ""


def is_hotcue_candidate(item: dict[str, Any]) -> bool:
    """
    Verifica se um item (frame ID3) é um candidato a conter informações de hotcue,
    procurando por palavras-chave relacionadas.
    """
    haystack = json.dumps(item, ensure_ascii=False).lower()
    return any(word in haystack for word in HOTCUE_WORDS)


def enrich_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """
    Enriquece um item candidato a hotcue, tentando analisar estruturas de dados embutidas (JSON, XML, pares chave-valor).
    """
    enriched = dict(item)
    text_values = collect_strings(item)

    for text in text_values:
        parsed = parse_embedded_structure(text)
        if parsed is not None:
            enriched["parsed"] = parsed
            break

    return enriched


def collect_strings(value: Any) -> list[str]:
    """
    Coleta todas as strings de uma estrutura de dados aninhada (dicionário, lista, string).
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(collect_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(collect_strings(child))
        return result
    return []


def parse_embedded_structure(text: str) -> Any | None:
    """
    Tenta analisar uma string para encontrar estruturas de dados embutidas (JSON, XML, pares chave-valor).
    """
    stripped = text.strip()
    if not stripped:
        return None

    if stripped[:1] in "[{":
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    if "<" in stripped and ">" in stripped:
        return {"xml_or_html": stripped}

    decoded = decode_base64_text(stripped)
    if decoded and decoded != stripped:
        return parse_embedded_structure(decoded)

    pairs = dict(re.findall(r"([A-Za-z_][\w.-]*)\s*[:=]\s*([^,;|]+)", stripped))
    if pairs:
        return pairs

    return None


def decode_base64_text(text: str) -> str | None:
    """
    Tenta decodificar uma string que pode ser base64 e retornar o texto resultante.
    """
    compact = re.sub(r"\s+", "", text.strip("\x00 "))
    if len(compact) < 12 or not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return None

    padding = "=" * (-len(compact) % 4)
    try:
        raw = base64.b64decode(compact + padding, validate=True)
    except ValueError:
        return None

    decoded = printable_text(raw)
    return decoded.strip("\x00 ") if decoded else None


def decode_base64_binary(text: str) -> bytes | None:
    """
    Tenta decodificar uma string que pode ser base64 e retornar os bytes resultantes.
    """
    compact = re.sub(r"\s+", "", text.strip("\x00 "))
    if not compact:
        return None

    start_match = re.search(r"[A-Za-z0-9+/=]{12,}", compact)
    if not start_match:
        return None

    compact = compact[start_match.start() :]
    padding = "=" * (-len(compact) % 4)
    try:
        return base64.b64decode(compact + padding, validate=True)
    except ValueError:
        return None


def argb_to_hex(value: str | int | None) -> str | None:
    """
    Converte um valor ARGB (string ou inteiro) para uma string hexadecimal de cor (#RRGGBB).
    """
    if value in (None, ""):
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    alpha = (number >> 24) & 0xFF
    red = (number >> 16) & 0xFF
    green = (number >> 8) & 0xFF
    blue = number & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}" if alpha else f"#{red:02X}{green:02X}{blue:02X}"


def seconds_to_timecode(value: str | float | int | None) -> str | None:
    """
    Converte um valor em segundos para um formato de timecode (MM:SS.mmm).
    """
    if value in (None, ""):
        return None

    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None

    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)
    return f"{minutes:02d}:{remaining:06.3f}"


def normalize_hotcue(raw: dict[str, Any], source: str, index: int | None = None) -> dict[str, Any]:
    """
    Normaliza um dicionário de hotcue bruto, extraindo e padronizando suas propriedades.
    """
    number = raw.get("num") or raw.get("Num") or raw.get("index") or raw.get("Index")
    number = number if number not in (None, "") else index

    position_key = next(
        (
            key
            for key in ("pos", "Pos", "position", "position_seconds", "position_ms", "time", "Time")
            if key in raw
        ),
        "",
    )
    position = raw.get(position_key) if position_key else None
    name = raw.get("name") or raw.get("Name") or raw.get("label") or raw.get("Label") or ""
    color = raw.get("color") or raw.get("Color")

    position_seconds: float | None = None
    if position not in (None, ""):
        try:
            numeric_position = float(str(position).removesuffix("ms"))
        except (TypeError, ValueError):
            position_seconds = None
        else:
            is_millisecond_key = position_key in ("position_ms",) or str(position).endswith("ms")
            is_probably_milliseconds = source == "mp3_tag" and position_key in ("time", "Time") and numeric_position > 1000
            position_seconds = (
                numeric_position / 1000
                if is_millisecond_key or is_probably_milliseconds
                else numeric_position
            )

    normalized: dict[str, Any] = {
        "source": source,
        "num": int(number) if str(number).isdigit() else number,
        "name": name,
        "pos_seconds": position_seconds,
        "time": seconds_to_timecode(position_seconds),
    }
    if color not in (None, ""):
        normalized["color"] = int(color) if str(color).isdigit() else color
        normalized["color_hex"] = argb_to_hex(color)
    return normalized


def extract_serato_markers2(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extrai hotcues do formato "serato markers2" encontrado em frames ID3 PRIV.
    """
    if "serato markers2" not in str(candidate.get("description", "")).lower():
        return []

    payload = candidate.get("payload", {})
    payload_text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(payload_text, str):
        return []

    raw = decode_base64_binary(payload_text)
    if not raw:
        return []

    cues: list[dict[str, Any]] = []
    for chunk in raw.split(b"CUE"):
        if len(chunk) < 17:
            continue

        header = chunk[:17]
        name = chunk[17:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        number = header[6] + 1
        position_ms = int.from_bytes(header[7:11], "big")
        color_hex = f"#{header[12]:02X}{header[13]:02X}{header[14]:02X}"

        cues.append(
            {
                "source": "serato_markers2",
                "num": number,
                "name": name,
                "pos_seconds": position_ms / 1000,
                "time": seconds_to_timecode(position_ms / 1000),
                "color_hex": color_hex,
            }
        )

    return cues


def merge_hotcue_details(hotcues: list[dict[str, Any]], details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Mescla uma lista de hotcues com detalhes adicionais, priorizando informações mais completas.
    """
    if not details:
        return hotcues

    details_by_num = {item.get("num"): item for item in details if item.get("num") is not None}
    merged: list[dict[str, Any]] = []
    used_nums = set()

    for hotcue in hotcues:
        detail = details_by_num.get(hotcue.get("num"))
        if not detail:
            merged.append(hotcue)
            continue

        used_nums.add(hotcue.get("num"))
        merged_item = dict(hotcue)
        if detail.get("name"):
            merged_item["name"] = detail["name"]
        if detail.get("color_hex") and "color_hex" not in merged_item:
            merged_item["color_hex"] = detail["color_hex"]
        merged_item["source"] = "mp3_tag"
        merged_item["detail_source"] = detail.get("source")
        merged.append(merged_item)

    for detail in details:
        if detail.get("num") not in used_nums:
            merged.append(dict(detail, source="mp3_tag", detail_source=detail.get("source")))

    return sorted(
        merged,
        key=lambda item: (
            item.get("num") if isinstance(item.get("num"), int) else 9999,
            item.get("pos_seconds") or 0,
        ),
    )


def extract_hotcues_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Extrai hotcues de uma lista de frames ID3 candidatos, analisando diferentes formatos.
    """
    hotcues: list[dict[str, Any]] = []
    serato_details: list[dict[str, Any]] = []
    for candidate in candidates:
        serato_details.extend(extract_serato_markers2(candidate))
        parsed = candidate.get("parsed")
        if isinstance(parsed, dict):
            cue_list = parsed.get("cues")
            if isinstance(cue_list, list):
                for index, item in enumerate(cue_list, start=1):
                    if isinstance(item, dict):
                        hotcue = normalize_hotcue(item, "mp3_tag", index=index)
                        if hotcue.get("pos_seconds") is not None or hotcue.get("num") is not None:
                            hotcues.append(hotcue)
            else:
                hotcue = normalize_hotcue(parsed, "mp3_tag")
                if hotcue.get("pos_seconds") is not None or hotcue.get("num") is not None:
                    hotcues.append(hotcue)
        elif isinstance(parsed, list):
            for index, item in enumerate(parsed, start=1):
                if isinstance(item, dict):
                    hotcue = normalize_hotcue(item, "mp3_tag", index=index)
                    if hotcue.get("pos_seconds") is not None or hotcue.get("num") is not None:
                        hotcues.append(hotcue)

    hotcues = sorted(
        hotcues,
        key=lambda item: (
            item.get("num") if isinstance(item.get("num"), int) else 9999,
            item.get("pos_seconds") or 0,
        ),
    )
    return merge_hotcue_details(hotcues, serato_details)


def parse_virtualdj_song(path: Path) -> dict[str, Any]:
    """
    Analisa um arquivo XML/TXT de banco de dados do Virtual DJ para extrair informações de uma música e seus POIs (incluindo hotcues).
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    root = ET.fromstring(text)

    if root.tag != "Song":
        song = root.find(".//Song")
        if song is None:
            raise ValueError("arquivo VirtualDJ nao contem elemento Song")
        root = song

    pois = []
    hotcues = []
    for poi in root.findall("Poi"):
        item = dict(poi.attrib)
        item["pos_seconds"] = float(item["Pos"]) if "Pos" in item else None
        item["time"] = seconds_to_timecode(item.get("Pos"))
        if "Color" in item:
            item["color_hex"] = argb_to_hex(item["Color"])
        pois.append(item)

        if item.get("Type") == "cue":
            hotcues.append(
                normalize_hotcue(
                    {
                        "Num": item.get("Num"),
                        "Name": item.get("Name", ""),
                        "Pos": item.get("Pos"),
                        "Color": item.get("Color"),
                    },
                    "virtualdj",
                )
            )

    return {
        "file": str(path),
        "song": dict(root.attrib),
        "hotcues": sorted(hotcues, key=lambda item: item.get("num") or 9999),
        "poi_count": len(pois),
        "pois": pois,
    }


def read_mp3(path: Path, dump_frames: bool = False) -> dict[str, Any]:
    """
    Lê um arquivo MP3, extrai tags ID3v2 e tenta encontrar hotcues.
    """
    metadata, frames = parse_id3_frames(path)
    decoded_frames = [parse_frame(frame) for frame in frames]
    hotcue_candidates = [enrich_candidate(frame) for frame in decoded_frames if is_hotcue_candidate(frame)]
    hotcues = extract_hotcues_from_candidates(hotcue_candidates)

    result: dict[str, Any] = {
        "file": str(path),
        "id3": metadata,
        "hotcues": hotcues,
        "hotcue_candidates": hotcue_candidates,
    }
    if dump_frames:
        result["frames"] = decoded_frames
    return result


def build_parser() -> argparse.ArgumentParser:
    """
    Constrói o parser de argumentos para a linha de comando.
    """
    parser = argparse.ArgumentParser(
        description="Le tags ID3 de MP3 e retorna possiveis hotcues em JSON."
    )
    parser.add_argument("mp3", nargs="+", type=Path, help="Arquivo(s) MP3 para analisar")
    parser.add_argument(
        "--dump-frames",
        action="store_true",
        help="Inclui todos os frames ID3 decodificados no JSON de saida",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Formata o JSON com indentacao",
    )
    parser.add_argument(
        "--virtualdj",
        type=Path,
        help="Arquivo XML/TXT do banco do VirtualDJ para mostrar hotcues Type=cue",
    )
    parser.add_argument(
        "--hotcues-only",
        action="store_true",
        help="Mostra somente a lista normalizada de hotcues",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Função principal para executar a ferramenta de leitura de tags MP3.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    results = []
    exit_code = 0
    for mp3_path in args.mp3:
        try:
            results.append(read_mp3(mp3_path, dump_frames=args.dump_frames))
        except Exception as exc:  # noqa: BLE001 - CLI should keep processing other files.
            exit_code = 1
            results.append({"file": str(mp3_path), "error": str(exc)})

    payload: Any = results[0] if len(results) == 1 else results
    if args.virtualdj:
        try:
            virtualdj = parse_virtualdj_song(args.virtualdj)
        except Exception as exc:  # noqa: BLE001 - CLI should return useful JSON.
            exit_code = 1
            virtualdj = {"file": str(args.virtualdj), "error": str(exc)}

        if isinstance(payload, dict):
            payload["virtualdj"] = virtualdj
        else:
            payload = {"mp3_files": payload, "virtualdj": virtualdj}

    if args.hotcues_only:
        if isinstance(payload, dict) and "mp3_files" not in payload:
            compact_payload: Any = {
                "file": payload.get("file"),
                "hotcues": payload.get("hotcues", []),
            }
            if "virtualdj" in payload:
                compact_payload["virtualdj_hotcues"] = payload["virtualdj"].get("hotcues", [])
            payload = compact_payload
        elif isinstance(payload, dict):
            payload = {
                "mp3_files": [
                    {"file": item.get("file"), "hotcues": item.get("hotcues", [])}
                    for item in payload.get("mp3_files", [])
                ],
                "virtualdj_hotcues": payload.get("virtualdj", {}).get("hotcues", []),
            }
        else:
            payload = [
                {"file": item.get("file"), "hotcues": item.get("hotcues", [])}
                for item in payload
            ]

    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
