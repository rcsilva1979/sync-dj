#!/usr/bin/env python3

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')

from backup_utils import create_database_backup


# -----------------------------
# ARGUMENTOS
# -----------------------------
"""
Função para analisar os argumentos da linha de comando.
"""
def parse_args():
    parser = argparse.ArgumentParser(description="Sync Engine DJ playlists tree")
    parser.add_argument("--db", required=True)
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


# -----------------------------
# CONEXÃO
# -----------------------------
"""
Função para estabelecer a conexão com o banco de dados SQLite.
"""
def connect(db_path, apply):
    if apply:
        con = sqlite3.connect(db_path)
    else:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    con.row_factory = sqlite3.Row
    return con


# -----------------------------
# PLAYLIST TREE
# -----------------------------
"""
Carrega os nós das playlists do banco de dados.
"""
def load_nodes(con):
    rows = con.execute("""
    SELECT
        id,
        title,
        parentListId
    FROM Playlist
    WHERE isPersisted = 1
      AND isExplicitlyExported = 1
""").fetchall()

    nodes = {r["id"]: r for r in rows}
    children = {}

    for r in rows:
        children.setdefault(r["parentListId"], []).append(r["id"])

    return nodes, children


"""
Constrói o caminho completo de uma playlist a partir de seu ID.
"""
def build_path(node_id, nodes):
    parts = []
    current = nodes.get(node_id)

    while current:
        title = current["title"]
        parts.append(title.strip())

        current = nodes.get(current["parentListId"])

    return " / ".join(reversed(parts))


"""
Encontra o ID de uma playlist raiz pelo seu nome.
"""
def find_root_playlist(con, target):
    nodes, _ = load_nodes(con)

    for nid in nodes:
        if build_path(nid, nodes).lower() == target.lower():
            return nid

    return None


# -----------------------------
# TRACKS
# -----------------------------
"""
Obtém as faixas de uma playlist específica do Engine DJ.
"""
def get_engine_tracks(con, playlist_id):
    rows = con.execute("""
        SELECT t.id, t.path
        FROM PlaylistEntity pe
        JOIN Track t ON t.id = pe.trackId
        WHERE pe.listId = ?
    """, (playlist_id,)).fetchall()

    data = {}
    for r in rows:
        if r["path"]:
            name = r["path"].replace("\\", "/").split("/")[-1].lower()
            data[name] = r["id"]

    return data


"""
Obtém os arquivos de áudio de uma pasta no disco.
"""
def get_disk_files(folder):

    AUDIO_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".flac",
        ".m4a",
        ".aac",
        ".ogg",
        ".aiff",
        ".aif",
        ".wma",
        ".alac"
    }

    files = {}

    for f in folder.iterdir():

        if not f.is_file():
            continue

        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        files[f.name.lower()] = f.resolve()

    return files


"""
Converte um caminho de arquivo para o formato esperado pelo Engine DJ.
"""
def to_engine_path(file_path):
    return str(file_path.resolve()).replace("\\", "/")


"""
Obtém o UUID do banco de dados.
"""
def get_uuid(con):
    return con.execute("SELECT uuid FROM Information LIMIT 1").fetchone()[0]

"""
Encontra o ID de uma faixa pelo seu caminho no banco de dados.
"""
def find_track_by_path(con, file_path):
    engine_path = str(file_path.resolve()).replace("\\", "/")

    row = con.execute("""
        SELECT id
        FROM Track
        WHERE LOWER(path) = LOWER(?)
        LIMIT 1
    """, (engine_path,)).fetchone()

    if row:
        return row["id"]

    return None

# -----------------------------
# INSERT
# -----------------------------
"""
Insere uma nova faixa no banco de dados do Engine DJ.
"""
def insert_track(con, file_path, engine_path):
    stat = file_path.stat()
    now = int(time.time())

    con.execute("""
        INSERT INTO Track (
            path, filename, fileBytes, title, fileType,
            dateCreated, dateAdded, isAvailable
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        engine_path,
        file_path.name,
        stat.st_size,
        file_path.stem,
        file_path.suffix.replace(".", ""),
        now,
        now
    ))

    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


"""
Adiciona uma faixa a uma playlist no banco de dados do Engine DJ.
"""
def add_to_playlist(con, playlist_id, track_id, uuid):
    tail = con.execute("""
        SELECT id FROM PlaylistEntity
        WHERE listId = ? AND nextEntityId = 0
        ORDER BY id DESC LIMIT 1
    """, (playlist_id,)).fetchone()

    con.execute("""
        INSERT INTO PlaylistEntity (
            listId, trackId, databaseUuid, nextEntityId, membershipReference
        ) VALUES (?, ?, ?, 0, 0)
    """, (playlist_id, track_id, uuid))

    new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    if tail:
        con.execute("UPDATE PlaylistEntity SET nextEntityId = ? WHERE id = ?", (new_id, tail["id"]))


# -----------------------------
# PROCESSAR ÁRVORE
# -----------------------------
"""
Converte o caminho de uma playlist para um caminho de pasta no sistema de arquivos.
"""
def playlist_path_to_folder(base_folder, playlist_path, root_name):
    parts = [p.strip() for p in playlist_path.split("/")]

    if parts and parts[0].lower() == root_name.lower():
        parts = parts[1:]

    if not parts:
        return base_folder

    return base_folder.joinpath(*parts)


"""
Processa uma playlist e suas subpastas, sincronizando as faixas com o banco de dados.
"""
def process_playlist(
        con,
        playlist_id,
        nodes,
        children,
        base_folder,
        root_name,
        uuid,
        apply):

    full_path = build_path(playlist_id, nodes)

    folder = playlist_path_to_folder(
        base_folder,
        full_path,
        root_name
    )

    if folder.exists():

        engine_tracks = get_engine_tracks(con, playlist_id)
        disk_files = get_disk_files(folder)

        missing = set(disk_files.keys()) - set(engine_tracks.keys())

        # 🔥 MOSTRA APENAS SE TIVER DIFERENÇA
        if missing:

            print(f"=== {full_path} ===")
            print(f"Pasta: {folder}")
            print(f"Novas: {len(missing)}")

            for m in sorted(missing):
                print(f"  {m}")

            if apply:
                print("MODO APPLY ATIVO")

                with con:
                    for name in sorted(missing):

                        file_path = disk_files[name]
                        engine_path = to_engine_path(file_path)

                        existing_track = find_track_by_path(con, file_path)

                        if existing_track:

                            print(f"[OK] Já existe (id={existing_track})")

                            add_to_playlist(
                                con,
                                playlist_id,
                                existing_track,
                                uuid
                            )

                        else:

                            track_id = insert_track(
                                con,
                                file_path,
                                engine_path
                            )

                            add_to_playlist(
                                con,
                                playlist_id,
                                track_id,
                                uuid
                            )

                            print(f"[OK] Inserido: {name}")

    # continua descendo na árvore
    for child_id in children.get(playlist_id, []):
        process_playlist(
            con,
            child_id,
            nodes,
            children,
            base_folder,
            root_name,
            uuid,
            apply
        )
        

"""
Cria um backup do banco de dados do Engine DJ.
"""
def create_backup(db_path):
    db_path = Path(db_path)
    backup_path = create_database_backup(db_path)

    print("\n==============================")
    print("CRIANDO BACKUP")
    print("==============================")
    print(f"Origem : {db_path.parent}")
    print(f"Destino: {backup_path}")

    if backup_path:
        print("[OK] Backup concluído\n")
    else:
        print("[ERRO] Não foi possível criar o backup\n")

# -----------------------------
# MAIN
# -----------------------------
"""
Função principal para executar a sincronização da árvore de playlists.
"""
def main():
    args = parse_args()
    
    if args.apply:
        create_backup(args.db)

    con = connect(args.db, args.apply)

    try:
        nodes, children = load_nodes(con)

        root_id = find_root_playlist(con, args.playlist)

        if not root_id:
            print("Playlist raiz não encontrada")
            return

        print(f"ROOT: {args.playlist}")

        uuid = get_uuid(con)

        root_name = args.playlist

        process_playlist(
            con,
            root_id,
            nodes,
            children,
            Path(args.folder),
            root_name,
            uuid,
            args.apply
        )

    finally:
        con.close()


if __name__ == "__main__":
    main()