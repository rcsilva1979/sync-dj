import os
import sqlite3
import string
from constants import IS_WIN, IS_MAC
 
def get_playlists_from_db(db_path):
    """Retorna lista de títulos de playlists do banco de dados Engine DJ."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Busca playlists de raiz (parentListId 0 ou NULL) que estejam persistidas
        rows = conn.execute("SELECT id, title FROM Playlist WHERE (parentListId = 0 OR parentListId IS NULL) AND isPersisted = 1").fetchall()
        conn.close()
        return [r["title"] for r in rows]
    except Exception:
        return []
 
def get_tracks_from_playlist(db_path, playlist_name):
    """
    Retorna uma lista de dicionários com os detalhes das faixas de uma playlist específica.
    """
    if not db_path or not os.path.exists(db_path) or not playlist_name:
        return []
    
    tracks_info = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Encontra o ID da playlist pelo título
        cursor = conn.execute("SELECT id FROM Playlist WHERE title = ? AND isPersisted = 1", (playlist_name,))
        playlist_row = cursor.fetchone()
        
        if playlist_row:
            playlist_id = playlist_row["id"]
            
            # O Engine DJ armazena caminhos relativos à pasta "Engine Library"
            # O banco m.db fica em: .../Engine Library/Database2/m.db
            engine_library_dir = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))

            # Busca faixas associadas
            cursor = conn.execute("""
                SELECT T.title, T.artist, T.album, T.path, T.filename, T.length, T.bpm, T.year, T.fileType
                FROM PlaylistEntity PE
                JOIN Track T ON PE.trackId = T.id
                WHERE PE.listId = ?
                ORDER BY PE.id ASC
            """, (playlist_id,))

            for row in cursor.fetchall():
                track_data = dict(row)
                rel_path = track_data.get("path")
                if rel_path:
                    # Resolve o caminho absoluto e normaliza as barras para o formato do Windows (\)
                    track_data["caminho_absoluto"] = os.path.normpath(os.path.join(engine_library_dir, rel_path))
                tracks_info.append(track_data)
        conn.close()
    except Exception as e:
        print(f"Erro ao obter faixas da playlist '{playlist_name}': {e}")
    return tracks_info

def get_tracks_by_playlist_id(db_path, playlist_id):
    """
    Retorna uma lista de dicionários com os detalhes das faixas de uma playlist específica por ID.
    """
    if not db_path or not os.path.exists(db_path) or playlist_id is None:
        return []
    
    tracks_info = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # O Engine DJ armazena caminhos relativos à pasta "Engine Library"
        # O banco m.db fica em: .../Engine Library/Database2/m.db
        engine_library_dir = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))

        # Busca faixas associadas
        cursor = conn.execute("""
            SELECT PE.id AS entry_id, T.id, T.title, T.artist, T.album, T.path, T.filename, T.length, T.bpm, T.year, T.fileType
            FROM PlaylistEntity PE
            JOIN Track T ON PE.trackId = T.id
            WHERE PE.listId = ?
            ORDER BY PE.id ASC
        """, (playlist_id,))

        for row in cursor.fetchall():
            track_data = dict(row)
            rel_path = track_data.get("path")
            if rel_path:
                # Resolve o caminho absoluto e normaliza as barras para o formato do Windows (\)
                track_data["caminho_absoluto"] = os.path.normpath(os.path.join(engine_library_dir, rel_path))
            tracks_info.append(track_data)
        conn.close()
    except Exception as e:
        print(f"Erro ao obter faixas da playlist ID '{playlist_id}': {e}")
    return tracks_info

def get_database_uuid(db_path):
    """Retorna o UUID do banco de dados Engine DJ a partir da tabela Information."""
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

def get_all_playlists_hierarchical(db_path):
    """
    Retorna uma lista de strings, onde cada string é o caminho hierárquico completo
    de uma playlist (ex: "Root Playlist / Sub-Playlist / Minha Playlist").
    """
    if not db_path or not os.path.exists(db_path):
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Busca todas as playlists persistidas
        rows = conn.execute("SELECT id, title, parentListId FROM Playlist WHERE isPersisted = 1").fetchall()
        
        # Cria um dicionário para busca rápida por ID
        playlists_by_id = {row["id"]: row for row in rows}
        
        def build_full_path(playlist_id):
            path_parts = []
            current_id = playlist_id
            while current_id != 0 and current_id in playlists_by_id:
                playlist = playlists_by_id[current_id]
                path_parts.append(playlist["title"])
                current_id = playlist["parentListId"]
            return " / ".join(reversed(path_parts))
        
        all_paths_with_ids = []
        for playlist_id in playlists_by_id:
            full_path = build_full_path(playlist_id)
            if full_path: # Garante que o caminho não seja vazio
                all_paths_with_ids.append((full_path, playlist_id))
        
        all_paths_with_ids.sort(key=lambda x: x[0]) # Ordena alfabeticamente pelo caminho completo
        
        conn.close()
        return all_paths_with_ids
    except Exception as e:
        print(f"Erro ao obter playlists com caminhos hierárquicos: {e}")
        return []

def localizar_bancos_dados_engine():
    """
    Busca o banco de dados m.db em locais padrão (Pasta Música) e na raiz de discos fixos (D:, E:, etc).
    """
    encontrados = []
    
    # 1. Pasta Música do usuário
    user_music = os.path.join(os.path.expanduser("~"), "Music")
    path_music = os.path.join(user_music, "Engine Library", "Database2", "m.db")
    if os.path.exists(path_music):
        encontrados.append(os.path.normpath(path_music))
        
    # 2. Varre volumes externos/secundários (Windows e Mac)
    if IS_WIN:
        for letra in string.ascii_uppercase:
            raiz = f"{letra}:\\"
            if os.path.exists(raiz):
                try:
                    import ctypes
                    # DRIVE_FIXED = 3, DRIVE_REMOVABLE = 2
                    if ctypes.windll.kernel32.GetDriveTypeW(raiz) in (2, 3):
                        path_disco = os.path.join(raiz, "Engine Library", "Database2", "m.db")
                        if os.path.exists(path_disco):
                            norm = os.path.normpath(path_disco)
                            if norm not in encontrados:
                                encontrados.append(norm)
                except Exception: pass
    elif IS_MAC:
        volumes_path = "/Volumes"
        if os.path.exists(volumes_path):
            for volume in os.listdir(volumes_path):
                raiz = os.path.join(volumes_path, volume)
                path_disco = os.path.join(raiz, "Engine Library", "Database2", "m.db")
                if os.path.exists(path_disco):
                    norm = os.path.normpath(path_disco)
                    if norm not in encontrados:
                        encontrados.append(norm)

    return encontrados

def get_track_id_by_path(db_path, rel_path):
    """Retorna o ID da track se o caminho relativo já existir no banco (normalizando slashes)."""
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        normalized_path = rel_path.replace('\\', '/')
        row = conn.execute("SELECT id FROM Track WHERE REPLACE(path, '\\', '/') = ?", (normalized_path,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

def update_playlist_entry_track(db_path, entry_id, new_track_id):
    """Atualiza o trackId de uma entrada específica na PlaylistEntity (Swapping)."""
    if not db_path or not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE PlaylistEntity SET trackId = ? WHERE id = ?", (new_track_id, entry_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao atualizar entrada {entry_id} da playlist: {e}")
        return False

def update_track_path(db_path, track_id, new_rel_path):
    """Atualiza o caminho relativo de uma música no banco de dados Engine DJ."""
    if not db_path or not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        # Verifica se o caminho já existe em outra track para evitar erro de UNIQUE constraint
        # Se o Engine DJ já conhece o arquivo em outro registro, não podemos duplicar o path
        check = conn.execute("SELECT id FROM Track WHERE path = ? AND id != ?", (new_rel_path, track_id)).fetchone()
        if check:
            conn.close()
            return False
            
        conn.execute("UPDATE Track SET path = ? WHERE id = ?", (new_rel_path, track_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao atualizar caminho da música {track_id}: {e}")
        return False