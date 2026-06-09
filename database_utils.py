import os
import sqlite3
import string
 
def get_playlists_from_db(db_path):
    """Retorna lista de títulos de playlists do banco de dados Engine DJ."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title FROM Playlist WHERE parentListId = 0 AND isPersisted = 1").fetchall()
        conn.close()
        return [r["title"] for r in rows]
    except Exception:
        return []
 
def get_tracks_from_playlist(db_path, playlist_name=None, playlist_id=None):
    """
    Retorna uma lista de dicionários com os detalhes das faixas de uma playlist específica (por nome ou ID).
    """
    if not db_path or not os.path.exists(db_path) or (not playlist_name and playlist_id is None):
        return []
    
    tracks_info = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Encontra o ID da playlist pelo título
        if playlist_id is not None:
            playlist_row = {"id": playlist_id}
        else:
            cursor = conn.execute("SELECT id FROM Playlist WHERE title = ? AND isPersisted = 1", (playlist_name,))
            playlist_row = cursor.fetchone()
        
        if playlist_row:
            p_id = playlist_row["id"]
            
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
            """, (p_id,))

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
    Retorna uma lista de tuplas (caminho_hierárquico, id_da_playlist).
    """
    if not db_path or not os.path.exists(db_path):
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Busca TODAS as playlists para garantir que o mapa de hierarquia esteja completo,
        # mesmo que alguns nós intermediários não estejam marcados como persistidos.
        all_rows = conn.execute("SELECT id, title, parentListId, isPersisted FROM Playlist").fetchall()
        nodes_map = {row["id"]: row for row in all_rows}
        
        def build_full_path(playlist_id):
            path_parts = []
            curr_id = playlist_id
            depth = 0
            # Percorre a árvore para cima até a raiz (parentListId=0 ou nó inexistente)
            while curr_id != 0 and curr_id in nodes_map and depth < 20:
                node = nodes_map[curr_id]
                title = node["title"] if node["title"] else "Untitled"
                path_parts.append(title.strip())
                curr_id = node["parentListId"]
                depth += 1
            
            if not path_parts: return ""
            return " / ".join(reversed(path_parts))

        all_results = []
        for row in all_rows:
            # Apenas adicionamos à lista final as playlists que o Engine DJ exibe para o usuário
            if row["isPersisted"] == 1 and row["title"]:
                path = build_full_path(row["id"])
                if path:
                    all_results.append((path, row["id"]))
        
        all_results.sort(key=lambda x: x[0])
        
        conn.close()
        return all_results
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
        
    # 2. Varre a raiz de volumes do sistema
    for letra in string.ascii_uppercase:
        raiz = f"{letra}:\\"
        if os.path.exists(raiz):
            # No Windows, verifica se é um disco fixo (DRIVE_FIXED = 3)
            if os.name == 'nt':
                try:
                    import ctypes
                    if ctypes.windll.kernel32.GetDriveTypeW(raiz) == 3:
                        path_disco = os.path.join(raiz, "Engine Library", "Database2", "m.db")
                        if os.path.exists(path_disco):
                            norm = os.path.normpath(path_disco)
                            if norm not in encontrados:
                                encontrados.append(norm)
                except Exception:
                    pass
            else:
                # Lógica simplificada para outros sistemas (se houver ponto de montagem fixo)
                pass
    return encontrados