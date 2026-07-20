import os
import sqlite3
import string
import subprocess
from constants import IS_WIN, IS_MAC


def engine_dj_esta_aberto():
    """Informa se o Engine DJ ou seu serviço de biblioteca está em execução."""
    try:
        if IS_WIN:
            processes = subprocess.check_output("tasklist", shell=True, text=True).lower()
        elif IS_MAC:
            processes = subprocess.check_output(["ps", "-ax"], text=True).lower()
        else:
            return False
        return any(name in processes for name in ("enginedj.exe", "engine dj.exe", "engine dj", "engine library service"))
    except Exception:
        return False
 
# Função para obter os títulos das playlists de um banco de dados Engine DJ
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
 
# Função para obter detalhes das faixas de uma playlist específica por nome
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
        conn.close()

        if playlist_row:
            return get_tracks_by_playlist_id(db_path, playlist_row["id"])
    except Exception as e:
        print(f"Erro ao obter faixas da playlist '{playlist_name}': {e}")
    return tracks_info

# Função para obter detalhes das faixas de uma playlist específica por ID
def get_tracks_by_playlist_id(db_path, playlist_id):
    """
    Retorna uma lista de dicionários com os detalhes das faixas de uma playlist específica por ID.
    """
    if not db_path or not os.path.exists(db_path) or playlist_id is None:
        return []
    
    tracks_info = []
    try:
        # 1. Localiza todos os bancos disponíveis e cria um mapa UUID -> Caminho do Banco
        encontrados = localizar_bancos_dados_engine()
        uuid_to_db = {get_database_uuid(b): b for b in encontrados if b}
        
        # Cache de diretórios raiz da biblioteca para cada banco (Engine Library)
        lib_dirs = {u: os.path.dirname(os.path.dirname(os.path.abspath(p))) for u, p in uuid_to_db.items()}

        # 2. Busca as entidades da playlist no banco de origem
        conn_origem = sqlite3.connect(db_path)
        conn_origem.row_factory = sqlite3.Row
        entities = conn_origem.execute(
            "SELECT id AS entry_id, trackId, databaseUuid FROM PlaylistEntity WHERE listId = ? ORDER BY id ASC", 
            (playlist_id,)
        ).fetchall()

        # Cache de conexões para evitar abrir/fechar repetidamente durante a análise
        conexoes = {get_database_uuid(db_path): conn_origem}

        for ent in entities:
            t_id = ent["trackId"]
            db_uuid = ent["databaseUuid"]
            
            # Resolve qual banco contém os dados desta música específica
            target_db_path = uuid_to_db.get(db_uuid) or db_path
            target_uuid = db_uuid if db_uuid in uuid_to_db else get_database_uuid(db_path)

            if target_uuid not in conexoes:
                try:
                    c = sqlite3.connect(target_db_path)
                    c.row_factory = sqlite3.Row
                    conexoes[target_uuid] = c
                except: continue

            # 3. Busca detalhes da música no banco correto (onde ela reside)
            cursor = conexoes[target_uuid].execute(
                "SELECT id, title, artist, album, path, filename, length, bpm, year, fileType, fileBytes FROM Track WHERE id = ?",
                (t_id,)
            )
            row = cursor.fetchone()
            
            if row:
                track_data = dict(row)
                track_data["entry_id"] = ent["entry_id"]
                # Preserva a origem da faixa para que playlists possam referenciá-la
                # corretamente, mesmo quando ela pertence a outro banco Engine DJ.
                track_data["databaseUuid"] = target_uuid
                rel_path = track_data.get("path")
                engine_lib_dir = lib_dirs.get(target_uuid) or os.path.dirname(os.path.dirname(os.path.abspath(target_db_path)))
                
                if rel_path:
                    track_data["caminho_absoluto"] = os.path.normpath(os.path.join(engine_lib_dir, rel_path))
                tracks_info.append(track_data)

        # 4. Fecha todas as conexões abertas
        for c in conexoes.values():
            c.close()
    except Exception as e:
        print(f"Erro ao obter faixas da playlist ID '{playlist_id}': {e}")
    return tracks_info


def get_all_tracks_from_database(db_path):
    """Retorna o catálogo de faixas de um banco em uma única consulta."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        database_uuid = get_database_uuid(db_path)
        library_dir = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title, artist, album, path, filename, length, bpm, year, fileType, fileBytes, "
                "genre, \"key\" AS key, comment "
                "FROM Track"
            ).fetchall()
        tracks = []
        for row in rows:
            track = dict(row)
            track["databaseUuid"] = database_uuid
            if track.get("path"):
                track["caminho_absoluto"] = os.path.normpath(os.path.join(library_dir, track["path"]))
            tracks.append(track)
        return tracks
    except sqlite3.Error:
        return []

# Função para obter o UUID de um banco de dados Engine DJ
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

# Função para obter todas as playlists de forma hierárquica
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
        
        # Busca apenas playlists que possuem músicas vinculadas.
        # Isso evita que o usuário selecione "Pastas" de sistema que podem conter links indesejados.
        rows = conn.execute("""
            SELECT DISTINCT P.id, P.title, P.parentListId 
            FROM Playlist P
            INNER JOIN PlaylistEntity PE ON P.id = PE.listId
            WHERE P.isPersisted = 1
        """).fetchall()
        
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

# Função para localizar bancos de dados Engine DJ em locais padrão
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
        
    # 2. Varre a raiz de volumes do sistema (Windows)
    if IS_WIN:
        for letra in string.ascii_uppercase:
            raiz = f"{letra}:\\"
            if os.path.exists(raiz):
                try:
                    import ctypes
                    if ctypes.windll.kernel32.GetDriveTypeW(raiz) == 3: # DRIVE_FIXED
                        path_disco = os.path.join(raiz, "Engine Library", "Database2", "m.db")
                        if os.path.exists(path_disco):
                            norm = os.path.normpath(path_disco)
                            if norm not in encontrados:
                                encontrados.append(norm)
                except Exception:
                    pass
    
    # 3. Varre volumes montados no macOS (/Volumes)
    elif IS_MAC:
        volumes_dir = "/Volumes"
        if os.path.exists(volumes_dir):
            try:
                for vol in os.listdir(volumes_dir):
                    path_vol = os.path.join(volumes_dir, vol)
                    path_disco = os.path.join(path_vol, "Engine Library", "Database2", "m.db")
                    if os.path.exists(path_disco):
                        norm = os.path.normpath(path_disco)
                        if norm not in encontrados:
                            encontrados.append(norm)
            except Exception:
                pass

    return encontrados

def get_removable_drive_roots():
    """
    Busca e retorna os caminhos raiz de todos os discos removíveis.
    """
    roots = []
    if IS_WIN:
        import ctypes
        drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26): # A a Z
            if (drive_mask >> i) & 1: # Se o drive existe
                letra = chr(ord('A') + i)
                raiz = f"{letra}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(raiz)
                # DRIVE_REMOVABLE = 2
                if drive_type == 2: 
                    roots.append(raiz)
    elif IS_MAC:
        volumes_dir = "/Volumes"
        if os.path.exists(volumes_dir):
            try:
                for vol in os.listdir(volumes_dir):
                    path_vol = os.path.join(volumes_dir, vol)
                    if os.path.isdir(path_vol) and not os.path.islink(path_vol):
                        roots.append(path_vol)
            except Exception as e:
                print(f"Erro ao listar volumes no macOS: {e}")
    return roots

def localizar_bancos_dados_removiveis():
    """
    Busca o banco de dados m.db apenas em discos removíveis (ex: pendrives, HDs externos).
    """
    encontrados = []

    if IS_WIN:
        import ctypes
        # Obtém uma máscara de bits dos drives disponíveis
        drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26): # A a Z
            if (drive_mask >> i) & 1: # Se o drive existe
                letra = chr(ord('A') + i)
                raiz = f"{letra}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(raiz)
                # DRIVE_REMOVABLE = 2
                if drive_type == 2: 
                    path_disco = os.path.join(raiz, "Engine Library", "Database2", "m.db")
                    if os.path.exists(path_disco):
                        norm = os.path.normpath(path_disco)
                        if norm not in encontrados:
                            encontrados.append(norm)
    elif IS_MAC:
        volumes_dir = "/Volumes"
        if os.path.exists(volumes_dir):
            try:
                for vol in os.listdir(volumes_dir):
                    # Ignora volumes de sistema ou internos que podem aparecer em /Volumes
                    if vol in ["Macintosh HD", "Preboot", "Recovery", "VM"]:
                        continue
                    path_vol = os.path.join(volumes_dir, vol)
                    # Verifica se é um diretório e não um link simbólico para evitar loops ou erros
                    if os.path.isdir(path_vol) and not os.path.islink(path_vol):
                        path_disco = os.path.join(path_vol, "Engine Library", "Database2", "m.db")
                        if os.path.exists(path_disco):
                            norm = os.path.normpath(path_disco)
                            if norm not in encontrados:
                                encontrados.append(norm)
            except Exception as e:
                print(f"Erro ao listar volumes no macOS: {e}")

    return encontrados

# Função para atualizar o caminho de uma faixa no banco de dados
def update_track_path(db_path, track_id, new_path):
    """Atualiza o caminho de uma música no banco de dados Engine DJ."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE Track SET path = ?, isAvailable = 1 WHERE id = ?", (new_path, track_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# Função para obter o ID de uma faixa pelo seu caminho relativo
def get_track_id_by_path(db_path, rel_path):
    """Busca o ID de uma música através do seu caminho relativo."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT id FROM Track WHERE REPLACE(path, '\\', '/') = ? LIMIT 1", (rel_path.replace("\\", "/"),)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

# Função para atualizar o trackId vinculado a uma entrada de playlist
def update_playlist_entry_track(db_path, entry_id, new_track_id):
    """Altera o trackId vinculado a uma entrada específica da playlist (PlaylistEntity)."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE PlaylistEntity SET trackId = ? WHERE id = ?", (new_track_id, entry_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False
