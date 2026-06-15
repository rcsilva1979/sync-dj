import os
import sys
import json
import sqlite3
import threading
import locale
import webbrowser
import ssl
from datetime import datetime
from collections import defaultdict
import urllib.request
from tkinter import messagebox
import shutil
import subprocess
from pathlib import Path as _Path
from tinytag import TinyTag
from constants import (
    VERSAO_ATUAL, 
    STRINGS, 
    LATEST_RELEASE_API,
    GITHUB_TOKEN,
    IS_WIN, 
    IS_MAC
)
from database_utils import (
    get_playlists_from_db as _get_playlists,
    get_tracks_from_playlist as _get_tracks,
    localizar_bancos_dados_engine
)

def get_base_dir():
    """Retorna o diretório base do aplicativo, compatível com PyInstaller."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_playlists_from_db(db_path):
    return _get_playlists(db_path)

def get_tracks_from_playlist(db_path, playlist_name):
    return _get_tracks(db_path, playlist_name)

# ===== Importa scripts de hotcue =====
def importar_scripts_hotcue():
    try:
        # Importar scripts diretamente da pasta raiz do projeto
        from le_json import read_mp3
        from engine_hotcues import CueWrite, encode_quick_cues
        from hotcue_normalizer import normalize_hotcues
        return read_mp3, CueWrite, encode_quick_cues, normalize_hotcues, True
    except ImportError:
        return None, None, None, None, False

read_mp3, CueWrite, encode_quick_cues, normalize_hotcues, _HOTCUE_DISPONIVEL = importar_scripts_hotcue()

# ================= FUNÇÕES AUXILIARES ========================
#COMPARA VERSAO ATUAL COM A VERSAO DO GITHUB (RETORNA TRUE SE A VERSAO DO GITHUB FOR MAIOR)
def versao_maior(versao_nova: str, versao_atual: str) -> bool:
    """Retorna True somente se versao_nova for MAIOR que versao_atual."""
    def _parse(v: str):
        v = v.lstrip("vV").strip()
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return _parse(versao_nova) > _parse(versao_atual)

#PEGA LINGUAGEM DO SISTEMA
def get_system_lang():
    """Detecta o idioma do sistema e retorna o código correspondente."""
    # --- INICIO: AJUSTE PARA TESTE DE IDIOMA (REMOVER NO FUTURO) ---
    # Altere o valor abaixo para "pt", "en" ou "es" para forçar o idioma
    forced_lang = "pt" 
    if forced_lang in STRINGS:
        return forced_lang
    # --- FIM: AJUSTE PARA TESTE DE IDIOMA (REMOVER NO FUTURO) ---
    try:
        if sys.platform.startswith('win'):
            import ctypes
            idioma_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            lang = locale.windows_locale.get(idioma_id, 'en_US')
        else:
            lang, _ = locale.getdefaultlocale()
        if lang:
            sigla = lang.split("_")[0].lower()
            return sigla if sigla in STRINGS else "en"
    except Exception:
        pass
    return "en"

#PEGA PASTA LOCAL DO APP (PY OU EXE)
def get_resource_path(relative_path):
    """Retorna o caminho absoluto para recursos, compatível com PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

#VERIFICA ATUALIZACAO
def check_for_updates(current_version: str) -> str | None:
    """Verifica no GitHub se há uma nova versão disponível."""
    print(f"DEBUG: Checking for updates. Current version: {current_version}")
    try:
        ctx = ssl._create_unverified_context()
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        if GITHUB_TOKEN:
            headers['Authorization'] = f'token {GITHUB_TOKEN}'
            print("DEBUG: Using local GitHub Token for authentication.")
            
        req = urllib.request.Request(LATEST_RELEASE_API, headers=headers)
        
        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            print(f"DEBUG: GitHub API response status: {response.status}")
            if response.status == 200:
                data = json.loads(response.read().decode())
                
                # O endpoint /tags retorna uma lista. Pegamos o primeiro item (mais recente).
                if isinstance(data, list) and len(data) > 0:
                    github_version = data[0].get("name", "")
                else:
                    github_version = ""
                    
                print(f"DEBUG: GitHub latest version: {github_version}")
                
                if github_version and versao_maior(github_version, current_version):
                    print(f"DEBUG: New version {github_version} found!")
                    return github_version
                else:
                    print(f"DEBUG: No new version or current is up-to-date.")
    except Exception as e: # Captura a exceção como 'e'
        print(f"DEBUG: Error checking for updates: {e}")
    return None

# ==============================================================




# ================= DETECÇÃO DE HOTCUE ========================
# Funções extraídas do engine_hotcues.py — sem dependência externa.

import zlib as _zlib
import struct as _struct


def _maybe_decompress(blob: bytes) -> bytes:
    """Descomprime o blob quickCues se estiver comprimido (zlib), senão retorna cru."""
    if len(blob) > 6 and blob[4:6] in (b"\x78\x01", b"\x78\x9c", b"\x78\xda"):
        try:
            data = _zlib.decompress(blob[4:])
            expected = int.from_bytes(blob[:4], "big")
            if expected in (0, len(data)):
                return data
        except _zlib.error:
            pass
    try:
        return _zlib.decompress(blob)
    except _zlib.error:
        return blob


def _track_tem_hotcue_real(blob) -> bool:
    """
    Retorna True se o blob quickCues contém pelo menos um hotcue com posição >= 0.

    O Engine DJ armazena o blob comprimido. Descomprimido:
      - Blob vazio / None           → sem hotcue
      - 129 bytes (só header+slots) → sem hotcue (todos os slots em -1.0)
      - > 129 bytes com label_len>0 → COM hotcue

    Estratégia:
      1. Heurística rápida por hex (padrão de blob vazio detectado pelo viewer).
      2. Decompress + varredura dos slots buscando position_samples >= 0.
    """
    if blob is None:
        return False

    if isinstance(blob, memoryview):
        blob = bytes(blob)

    # Heurística rápida: assinatura de blob sem hotcue real
    if b"\x63\x60\x00\x03\x0e\x86\xfd\x1f\x18" in blob:
        return False

    try:
        data = _maybe_decompress(blob)
    except Exception:
        return False

    # Varredura dos slots procurando pelo menos um ativo (label_len > 0 e pos >= 0)
    # Formato: 8 bytes header + por slot: 1 byte label_len, [label], 8 bytes double pos, [4 bytes cor]
    # Slot vazio: label_len=0 → apenas 1+8=9 bytes; slot ativo: 1+len+8+4 bytes
    if len(data) < 8:
        return False

    offset = 8   # pula o header de 8 bytes
    for _ in range(8):   # max 8 slots
        if offset >= len(data):
            break
        label_len = data[offset]
        offset += 1
        if label_len == 0:
            if offset + 8 <= len(data):
                offset += 8  # pula o double de posição
            continue
        if offset + label_len + 8 > len(data):
            break
        offset += label_len
        if offset + 8 > len(data):
            break
        pos = _struct.unpack(">d", data[offset: offset + 8])[0]
        offset += 8
        if offset + 4 <= len(data):
            offset += 4  # cor
        if pos >= 0:
            return True   # achou um slot ativo

    return False

# ================= CURSOR COM LOG SQL ======================
import time as _time

class LoggingCursor:
    """
    Wrapper sobre sqlite3.Cursor que registra SQLs no arquivo de log.

    Comportamento controlado pelas flags do app:
      - log=True , debug=False  ->  grava INSERT / UPDATE / DELETE (sem parâmetros)
      - log=True , debug=True   ->  grava TODOS os SQLs + parâmetros + tempo de execução
      - log=False, debug=False  ->  não grava nada (transparente)
    """

    # Prefixos que são sempre gravados no modo LOG normal
    _DML_PREFIXES = ("INSERT", "UPDATE", "DELETE")

    def __init__(self, cursor, log_fn, log_path, debug: bool):
        self._cur = cursor
        self._log = log_fn        # self.log do EngineSyncApp
        self._log_path = log_path
        self._debug = debug

    # ---- delegação de atributos do cursor original ----
    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    # ---- método principal ----
    def execute(self, sql, params=()):
        sql_upper = sql.strip().upper()

        if self._debug:
            # Modo DEBUG: loga tudo com parâmetros e tempo
            t0 = _time.perf_counter()
            result = self._cur.execute(sql, params)
            elapsed = (_time.perf_counter() - t0) * 1000  # ms

            sql_oneline = " ".join(sql.split())
            params_str = repr(params) if params else "()"
            self._log(
                self._log_path,
                f"[SQL] {sql_oneline} | params={params_str} | {elapsed:.2f}ms",
                nivel="debug"
            )
        else:
            # Modo LOG normal: só grava DML
            result = self._cur.execute(sql, params)
            if any(sql_upper.startswith(p) for p in self._DML_PREFIXES):
                sql_oneline = " ".join(sql.split())
                self._log(
                    self._log_path,
                    f"[SQL] {sql_oneline}",
                    nivel="log"
                )

        return result

    def __iter__(self):
        return iter(self._cur)
# ==========================================================

class SyncManager:
    def __init__(self):
        self.base_dir = get_base_dir()
        self.config_file = os.path.join(self.base_dir, "engine_sync_config.json")
        self.config = self.load_config()
        self.cancel_requested = False

    def load_config(self):
        if not os.path.exists(self.config_file): return {}
        try:
            with open(self.config_file, "r") as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def localizar_bancos_dados(self):
        return localizar_bancos_dados_engine()

    def save_config(self, data):
        self.config.update(data)
        # Filtra opções que o usuário pediu para não persistir no arquivo JSON
        excluir = {"importar_hotcue", "sobrescrever_hotcue", "remover_orfas"}
        config_persistente = {k: v for k, v in self.config.items() if k not in excluir}
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config_persistente, f, indent=4, ensure_ascii=False)
        except Exception: pass

    def engine_esta_aberto(self):
        try:
            if IS_WIN:
                resultado = subprocess.check_output("tasklist", shell=True, text=True).lower()
                return any(p in resultado for p in ["enginedj.exe", "engine dj.exe", "engine library service"])
            elif IS_MAC:
                # No macOS, usamos ps -ax para listar processos e verificamos o nome do app
                resultado = subprocess.check_output(["ps", "-ax"], text=True).lower()
                return any(p in resultado for p in ["engine dj", "engine library service"])
        except Exception:
            return False
        return False

    def _get_vol_id(self, path):
        """Helper para identificar o 'Drive' no Win ou 'Volume' no Mac."""
        if not path: return ""
        abs_p = os.path.abspath(path)
        if IS_WIN:
            return os.path.splitdrive(abs_p)[0].upper()
        else:
            p = abs_p.split(os.sep)
            # No Mac, o volume fica em /Volumes/NomeVolume
            return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

    def formatar_caminho_engine(self, caminho_arquivo, caminho_db):
        engine_library_dir = os.path.dirname(os.path.dirname(os.path.abspath(caminho_db)))
        arquivo_abs = os.path.abspath(caminho_arquivo)
        return os.path.relpath(arquivo_abs, engine_library_dir).replace("\\", "/")

    def iniciar_log(self, pasta, db_path, nome_colecao, ativo_log, ativo_debug, tool_name="SYNC"):
        if not ativo_log and not ativo_debug: return None, None
        
        log_dir = os.path.join(self.base_dir, "Reports")
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                print(f"Erro ao criar diretório de logs '{log_dir}': {e}")
                return None, None # Retorna None para evitar erros de escrita

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        def _criar_arquivo(modo):
            path = os.path.join(log_dir, f"{tool_name.lower()}_{modo.lower()}_{timestamp}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n" + f"  ENGINE DJ - {tool_name.upper().replace('_', ' ')}  ({VERSAO_ATUAL})\n" + "=" * 60 + "\n")
                f.write(f"Inicio        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" + f"Pasta Musicas : {pasta}\n" + f"Banco de Dados: {db_path}\n")
                f.write(f"Playlist Alvo : {nome_colecao}\n" + f"Modo Log      : {modo}\n" + "-" * 60 + "\n\n")
            return path
        return (_criar_arquivo("LOG") if ativo_log else None, _criar_arquivo("DEBUG") if ativo_debug else None)

    def log(self, caminhos, mensagem, nivel="log"):
        if not caminhos: return
        log_path, debug_path = caminhos if isinstance(caminhos, tuple) else (caminhos, None)
        linha = f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem}\n"
        try:
            if nivel == "log" and log_path:
                with open(log_path, "a", encoding="utf-8") as f: f.write(linha)
            if debug_path:
                with open(debug_path, "a", encoding="utf-8") as f: f.write(linha)
        except: pass

    def criar_cursor_log(self, conn, caminhos):
        raw = conn.cursor()
        if not caminhos or (caminhos[0] is None and caminhos[1] is None): return raw
        return LoggingCursor(cursor=raw, log_fn=self.log, log_path=caminhos, debug=self.config.get("debug", False))

    def format_time(self, seconds: float | None) -> str:
        """Converte segundos para o formato MM:SS.mmm para exibição amigável."""
        if seconds is None: return ""
        minutes = int(seconds // 60)
        remainder = seconds - minutes * 60
        return f"{minutes:02d}:{remainder:06.3f}"

    def _importar_hotcue_track(self, cursor, caminho_completo, track_id, log_paths, modo_sobrescrever, progress_callback):
        try:
            if not modo_sobrescrever:
                cursor.execute("SELECT quickCues FROM PerformanceData WHERE trackId = ? LIMIT 1", (track_id,))
                row_pd = cursor.fetchone()
                if _track_tem_hotcue_real(row_pd[0] if row_pd else None): return
            progress_callback(STRINGS[get_system_lang()]["status_hotcue"].format(filename=os.path.basename(caminho_completo)), None)
            dados_mp3 = read_mp3(_Path(caminho_completo))
            hotcues = normalize_hotcues(dados_mp3.get("hotcues", []))
            cues = [CueWrite(cue_number=int(hc["num"]), label=hc.get("name") or f"Cue {hc['num']}", position_seconds=float(hc["pos_seconds"]))
                    for hc in hotcues if hc.get("pos_seconds") is not None and str(hc.get("num", "")).isdigit() and 1 <= int(hc["num"]) <= 8]
            if not cues: return
            blob = encode_quick_cues(cues, sample_rate=44100.0)
            cursor.execute("INSERT INTO PerformanceData (trackId, quickCues) VALUES (?, ?) ON CONFLICT(trackId) DO UPDATE SET quickCues = excluded.quickCues", (track_id, sqlite3.Binary(blob)))
            self.log(log_paths, f"  [HOTCUE {'Sobrescrito' if modo_sobrescrever else 'Importado'}] id={track_id} | {os.path.basename(caminho_completo)}")
            for c in cues:
                self.log(log_paths, f"    ↳ Cue {c.cue_number}: '{c.label}' em {self.format_time(c.position_seconds)}")
        except Exception as e: self.log(log_paths, f"    [HOTCUE] ERRO em {os.path.basename(caminho_completo)}: {e}")

    def verificar_tracks_faltantes_na_pasta(self, cursor, pasta_base, db_path, log_paths):
        self.log(log_paths, f"--- VERIFICACAO: Tracks faltantes na pasta [{os.path.normpath(pasta_base)}] ---")
        engine_library_dir = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))
        
        # Prepara o caminho base para comparação robusta
        pasta_base_abs = os.path.normpath(os.path.abspath(pasta_base)).lower()
        if not pasta_base_abs.endswith(os.sep):
            pasta_base_abs += os.sep
            
        cursor.execute("SELECT id, path, filename FROM Track")
        all_tracks = cursor.fetchall()
        self.log(log_paths, f"[DEBUG] Total de tracks no banco para análise: {len(all_tracks)}", nivel="debug")
        
        tracks_para_remover = []
        for track_id, path, filename in all_tracks:
            if not path:
                continue
            
            # Resolve o caminho absoluto do arquivo guardado no banco (lida com ../ e caminhos diretos)
            path_normalizado = path.replace("\\", "/")
            caminho_full_db = os.path.join(engine_library_dir, path_normalizado)
            caminho_abs_db = os.path.normpath(os.path.abspath(caminho_full_db))
            
            # Log de debug para ver o que está sendo comparado se o modo debug estiver on
            if self.config.get("debug"):
                self.log(log_paths, f"[PATH_CHECK] DB_ABS: {caminho_abs_db.lower()} | BASE: {pasta_base_abs}", nivel="debug")

            # 1. Verifica se a música pertence à hierarquia da pasta selecionada
            if caminho_abs_db.lower().startswith(pasta_base_abs):
                # 2. Se pertence, verifica se o arquivo físico ainda existe no disco
                if not os.path.exists(caminho_abs_db):
                    tracks_para_remover.append((track_id, filename))
                    self.log(log_paths, f"[FALTANTE] id={track_id} | {filename} | path={path}")
        
        removidas_count = 0
        if self.config.get("remover_orfas") and tracks_para_remover:
            self.log(log_paths, f"--- AÇÃO: Removendo {len(tracks_para_remover)} músicas órfãs do banco de dados ---")
            for t_id, tfname in tracks_para_remover:
                # Remove de todas as tabelas para manter integridade
                cursor.execute("DELETE FROM PerformanceData WHERE trackId = ?", (t_id,))
                cursor.execute("DELETE FROM PlaylistEntity WHERE trackId = ?", (t_id,))
                cursor.execute("DELETE FROM Track WHERE id = ?", (t_id,))
                removidas_count += 1
                self.log(log_paths, f"  [DELETADA] id={t_id} | {tfname}")

            self.log(log_paths, f"[SUCESSO] {removidas_count} músicas órfãs foram removidas da coleção.")
            
        return removidas_count

    def motor_sincronizacao(self, ui_strings, progress_callback):
        self.cancel_requested = False
        pasta = self.config.get("pasta_musicas", "")
        db_path = self.config.get("path_db", "")
        # Prioriza a playlist selecionada na UI, senão usa o nome da pasta
        nome_colecao = self.config.get("playlist_alvo") or (os.path.basename(os.path.normpath(pasta)) if pasta else ui_strings["collection_name"])

        log_paths = self.iniciar_log(pasta, db_path, nome_colecao, self.config.get("log", True), self.config.get("debug", False), tool_name="MIRROR_SYNC") # type: ignore

        # Validação de drives (relpath falha no Windows entre discos diferentes)
        if os.name == 'nt' and os.path.splitdrive(os.path.abspath(pasta))[0].lower() != os.path.splitdrive(os.path.abspath(db_path))[0].lower():
            self.log(log_paths, f"[ERRO CRITICO] {ui_strings['error_different_drives']}")
            return None, None

        # log_paths agora é uma tupla (log_path, debug_path)
        arquivos_totais = []
        report_lines = []

        if self.config.get("fazer_backup"):
            progress_callback(ui_strings["status_backup"], 0)
            try:
                backup_dir = os.path.join(self.base_dir, "Backup_DB")
                if not os.path.exists(backup_dir):
                    os.makedirs(backup_dir)

                db_folder = os.path.dirname(db_path)
                # Identifica o disco (ex: C, D) para incluir no nome do backup
                drive = self._get_vol_id(db_path).replace(":", "").replace(" ", "_") or "PC"

                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_name = os.path.join(backup_dir, f"Backup_Engine_Drive_{drive}_{timestamp}")
                shutil.make_archive(backup_name, "zip", db_folder) # type: ignore
                self.log(log_paths, f"[BACKUP] Backup criado: {backup_name}.zip")
            except Exception as e:
                self.log(log_paths, f"[BACKUP] ERRO ao criar backup: {e}")
        
        for raiz, _, arquivos in os.walk(pasta):
            for arquivo in arquivos:
                # Suporte aos formatos principais
                if arquivo.lower().endswith(('.mp3', '.flac', '.wav', '.aiff', '.m4a')):
                    arquivos_totais.append(os.path.join(raiz, arquivo))
        
        total_arquivos = len(arquivos_totais)
        self.log(log_paths, f"[SCAN] {total_arquivos} arquivo(s) de audio encontrado(s) em: {pasta}")
    
        if total_arquivos == 0:
            self.log(log_paths, "[INFO] Nenhum arquivo encontrado na pasta. Prosseguindo para limpeza de orfas no banco...")

        conn = sqlite3.connect(db_path) # type: ignore
        try:
            cursor = self.criar_cursor_log(conn, log_paths)

            cursor.execute("SELECT uuid FROM Information LIMIT 1")
            row = cursor.fetchone() # type: ignore
            db_uuid = row[0] if row else "" # type: ignore
            data_atual = int(datetime.now().timestamp())   # para campos dateCreated/dateAdded (int)
            lastEditTime_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # para lastEditTime (string ISO)

            self.log(log_paths, f"[DB] Conectado ao banco: {db_path}")
            report_lines.append(f"INÍCIO DA SINCRONIZAÇÃO: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            report_lines.append(f"Banco de Dados : {db_path}")
            report_lines.append(f"Pasta de Músicas: {pasta}")
            report_lines.append(f"Playlist Alvo  : {nome_colecao}\n" + "="*60)
            
            self.log(log_paths, f"[DB] UUID do banco: {db_uuid}")
            self.log(log_paths, "")
            self.log(log_paths, "--- FASE 1: Importacao de Faixas ---")

            novas_musicas = 0
            for idx, caminho_completo in enumerate(arquivos_totais):
                if self.cancel_requested:
                    self.log(log_paths, "[CANCEL] Interrompido pelo usuário.")
                    return None, None, ""

                if idx % 20 == 0 or idx == total_arquivos - 1:
                    progresso = (idx + 1) / total_arquivos * 0.5 
                    msg = ui_strings["status_fase1"].format(current=idx+1, total=total_arquivos)
                    progress_callback(msg, progresso)

                caminho_engine = self.formatar_caminho_engine(caminho_completo, db_path)
                nome_arquivo = os.path.basename(caminho_completo)
                cursor.execute(
                    "SELECT id FROM Track WHERE REPLACE(path, '\\', '/') = ? LIMIT 1",
                    (caminho_engine,)
                )
                row_existente = cursor.fetchone()

                if row_existente: # type: ignore
                    track_id_existente = row_existente[0] # type: ignore

                    #  BUSCAR path atual no banco
                    cursor.execute("SELECT path FROM Track WHERE id = ?", (track_id_existente,))
                    row_path = cursor.fetchone() # type: ignore

                    path_db = (row_path[0] or "").replace("\\", "/") if row_path else "" # type: ignore
                    path_novo = caminho_engine.replace("\\", "/") # type: ignore
                    
                    # Otimização: Para músicas que já existem no banco, só processamos hotcues se a opção 
                    # 'Sobrescrever' estiver ativa. Se apenas 'Importar' estiver marcado, pulamos estas tracks
                    # para que a sincronização seja instantânea, focando hotcues apenas em arquivos novos.
                    if self.config.get("importar_hotcue") and self.config.get("sobrescrever_hotcue", False) and _HOTCUE_DISPONIVEL and caminho_completo.lower().endswith('.mp3'):
                        self._importar_hotcue_track(
                            cursor=cursor, 
                            caminho_completo=caminho_completo, 
                            track_id=track_id_existente,
                            log_paths=log_paths, 
                            modo_sobrescrever=self.config.get("sobrescrever_hotcue", False),
                            progress_callback=progress_callback) # type: ignore
                        report_lines.append(f"[HOTCUE] Atualizado: {os.path.basename(caminho_completo)}")

                    continue


                try:
                    tag = TinyTag.get(caminho_completo)
                    titulo = getattr(tag, 'title', None) or os.path.basename(caminho_completo)
                    artista = getattr(tag, 'artist', None) or "Desconhecido"
                    album = getattr(tag, 'album', None) or ""
                    bpm = int(getattr(tag, 'bpm', 0) or 0)
                    duracao = int(getattr(tag, 'duration', 0) or 0)
                    try:
                        ano = int(str(getattr(tag, 'year', 0))[:4]) if getattr(tag, 'year', 0) else 0
                    except ValueError:
                        ano = 0
                    
                    stat = os.stat(caminho_completo)
                    extensao = os.path.splitext(caminho_completo)[1].replace('.', '')
                    
                    cursor.execute("""
                        INSERT INTO Track (
                            path, filename, fileBytes, title, artist, album, length, bpm, year, fileType, dateCreated, dateAdded, isAnalyzed, isAvailable
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
                    """, (caminho_engine, os.path.basename(caminho_completo), stat.st_size, titulo, artista, album, duracao, bpm, ano, extensao, data_atual, data_atual))
                    track_id_novo = cursor.lastrowid
                    novas_musicas += 1
                    self.log(log_paths, f"  [TRACK +] id={track_id_novo} | {artista} - {titulo} | {os.path.basename(caminho_completo)}")
                    report_lines.append(f"[TRACK +] {artista} - {titulo} ({os.path.basename(caminho_completo)})")

                    # Importa hotcues do MP3 se o checkbox estiver ativado
                    # Track nova: sempre importa (não há nada para sobrescrever)
                    if self.config.get("importar_hotcue") and _HOTCUE_DISPONIVEL and caminho_completo.lower().endswith('.mp3'):
                        self._importar_hotcue_track(
                            cursor=cursor, 
                            caminho_completo=caminho_completo, 
                            track_id=track_id_novo,
                            log_paths=log_paths, 
                            modo_sobrescrever=True,  # nova track: sempre grava
                            progress_callback=progress_callback) # type: ignore
                except Exception as e:
                    self.log(log_paths, f"  [ERRO] Falha ao processar: {os.path.basename(caminho_completo)} -> {e}")

            if self.cancel_requested: return None, None

            self.log(log_paths, "")
            self.log(log_paths, "--- VERIFICACAO DE TRACKS FALTANTES ---")

            #  NOVA FASE: VERIFICAÇÃO DE TRACKS FALTANTES
            apagadas_musicas = self.verificar_tracks_faltantes_na_pasta(
                    cursor,
                    pasta,
                    db_path,
                    log_paths
                )

            if self.cancel_requested: return None, None

            progress_callback(ui_strings["status_fase2"], 0.6)
            self.log(log_paths, "")
            self.log(log_paths, "--- FASE 2: Construcao da Arvore de Playlists ---")
            
            tracks_orfas = []

            # Busca a playlist raiz preferindo a que já estiver persistida se houver duplicatas
            cursor.execute("SELECT id FROM Playlist WHERE title = ? AND (parentListId = 0 OR parentListId IS NULL) ORDER BY isPersisted DESC", (nome_colecao,))
            row = cursor.fetchone() # type: ignore

            if not row: # type: ignore
                cursor.execute("SELECT id FROM Playlist WHERE (parentListId = 0 OR parentListId IS NULL) AND nextListId = 0")
                last_root = cursor.fetchone() # type: ignore
                cursor.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, 0, 1, 0, ?, 1)", (nome_colecao, lastEditTime_iso))
                my_collection_id = cursor.lastrowid
                if last_root:
                    cursor.execute("UPDATE Playlist SET nextListId = ? WHERE id = ?", (my_collection_id, last_root[0])) # type: ignore
                self.log(log_paths, f"  [PLAYLIST +] Criada raiz: '{nome_colecao}' (id={my_collection_id})")
                report_lines.append(f"[PLAYLIST] Raiz processada: {nome_colecao}")
            else:
                my_collection_id = row[0] # type: ignore
                self.log(log_paths, f"  [PLAYLIST] Usando playlist existente: '{nome_colecao}' (id={my_collection_id})")
                
                # PONTO CHAVE: Força isPersisted=1 e isExplicitlyExported=1. Sem isso, o Engine DJ 
                # pode ignorar os itens adicionados em Phase 3 se a playlist for considerada "shadow" ou temporária.
                cursor.execute("UPDATE Playlist SET lastEditTime = ?, isExplicitlyExported = 1, isPersisted = 1 WHERE id = ?", (lastEditTime_iso, my_collection_id))

                cte_query = "WITH RECURSIVE descendants(id) AS (SELECT id FROM Playlist WHERE parentListId = ? UNION ALL SELECT p.id FROM Playlist p INNER JOIN descendants d ON p.parentListId = d.id) SELECT id FROM descendants;"
                cursor.execute(cte_query, (my_collection_id,))
                descendants = [r[0] for r in cursor.fetchall()]

                if descendants:
                    placeholders = ','.join('?' * len(descendants))
                    cursor.execute(f"DELETE FROM PlaylistEntity WHERE listId IN ({placeholders})", descendants)
                    cursor.execute(f"DELETE FROM Playlist WHERE id IN ({placeholders})", descendants) # type: ignore
                    self.log(log_paths, f"  [PLAYLIST] Removidas {len(descendants)} sub-playlist(s) antigas")

                # Antes de apagar as entidades da playlist raiz, salva as tracks que
                # existem no banco mas nao estao mais no disco (arquivos removidos/movidos).
                # Elas serao preservadas na playlist para nao perder referencias.
                cursor.execute("""
                    SELECT pe.trackId, t.path, t.filename
                    FROM PlaylistEntity pe
                    JOIN Track t ON t.id = pe.trackId
                    WHERE pe.listId = ?
                """, (my_collection_id,)) # type: ignore
                tracks_no_banco = cursor.fetchall()

                # Monta conjunto dos filenames presentes no disco agora
                arquivos_no_disco = set()
                for raiz_walk, dirs_walk, arqs_walk in os.walk(pasta):
                    # Filtro recursivo otimizado
                    dirs_walk[:] = [d for d in dirs_walk if not d.startswith('.') and not d.startswith('$')]
                    for f in arqs_walk:
                        if f.lower().endswith(('.mp3', '.flac', '.wav', '.aiff', '.m4a')):
                            arquivos_no_disco.add(f.lower())

                tracks_orfas = []
                for tid, tpath, tfname in tracks_no_banco:
                    fname_lower = (tfname or "").lower()
                    if fname_lower and fname_lower not in arquivos_no_disco:
                        tracks_orfas.append((tid, tpath, tfname)) # type: ignore
                        self.log(log_paths,
                            f"  [ORFA] Track id={tid} nao encontrada no disco, sera preservada na playlist: {tfname}")

                cursor.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (my_collection_id,)) # type: ignore

            cursor.execute("SELECT id, path, filename FROM Track") # type: ignore
            mapa_tracks = {}
            for row in cursor.fetchall():
                track_id, path, filename = row[0], row[1], row[2]
                if not path:
                    continue
                # Índice SOMENTE por path normalizado — garante unicidade entre pastas.
                mapa_tracks[path.replace("\\", "/").lower()] = track_id
                # Fallback por filename: ajuda a encontrar a track se o relpath falhar
                # (ex: se o banco usa caminhos absolutos ou mudou de letra de drive)
                if filename and filename.lower() not in mapa_tracks:
                    mapa_tracks[filename.lower()] = track_id

            mapa_playlists = {pasta.lower(): my_collection_id} 
            mapa_hierarquia = {my_collection_id: None}
            tracks_por_playlist = defaultdict(dict)

            for raiz, diretorios, arquivos in os.walk(pasta):
                if self.cancel_requested: return None, None, ""

                # Filtro recursivo otimizado para a árvore de playlists
                diretorios[:] = [d for d in diretorios if not d.startswith('.') and not d.startswith('$')]

                parent_id = mapa_playlists.get(raiz.lower(), my_collection_id)
                diretorios.sort(reverse=True) 
                
                arquivos_validos = [f for f in arquivos if f.lower().endswith(('.mp3', '.flac', '.wav', '.aiff', '.m4a'))]
                tem_sub = len(diretorios) > 0
                tem_arquivos = len(arquivos_validos) > 0
                
                id_proxima_pasta = 0 
                playlist_alvo_id = parent_id

                for d in diretorios:
                    caminho_subpasta = os.path.join(raiz, d)
                    cursor.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, ?, 1, ?, ?, 1)", (d, parent_id, id_proxima_pasta, lastEditTime_iso)) # type: ignore
                    novo_id = cursor.lastrowid
                    id_proxima_pasta = novo_id 
                    mapa_playlists[caminho_subpasta.lower()] = novo_id
                    mapa_hierarquia[novo_id] = parent_id
                    report_lines.append(f"[SUB-PLAYLIST +] {d}")
                    self.log(log_paths, f"  [PLAYLIST +] Sub-playlist: '{d}' (id={novo_id}, pai={parent_id})")

                if tem_sub and tem_arquivos:
                    nome_pasta_atual = os.path.basename(raiz)
                    if raiz == pasta:
                        nome_pasta_atual = "Faixas Soltas"
                    nome_gemea = f"[ {nome_pasta_atual} ]"

                    cursor.execute("""
                        INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported)
                        VALUES (?, ?, 1, ?, ?, 1)
                    """, (nome_gemea, parent_id, id_proxima_pasta, lastEditTime_iso))
                    gemea_id = cursor.lastrowid
                    
                    mapa_hierarquia[gemea_id] = parent_id
                    playlist_alvo_id = gemea_id

                for arquivo in arquivos_validos:
                    caminho_completo = os.path.join(raiz, arquivo)
                    caminho_engine = self.formatar_caminho_engine(caminho_completo, db_path)
                    # Tenta buscar pelo caminho relativo (ideal) ou pelo nome do arquivo (fallback)
                    track_id = mapa_tracks.get(caminho_engine.lower()) or mapa_tracks.get(arquivo.lower())
                    
                    if track_id:
                        curr_list_id = playlist_alvo_id
                        while curr_list_id is not None:
                            tracks_por_playlist[curr_list_id][track_id] = caminho_completo
                            curr_list_id = mapa_hierarquia.get(curr_list_id)

            # Reinsere as tracks orfas na playlist raiz para preservar as referencias
            if tracks_orfas:
                for tid, tpath, tfname in tracks_orfas:
                    tracks_por_playlist[my_collection_id][tid] = tpath or tfname or str(tid)
                self.log(log_paths, f"  [ORFA] {len(tracks_orfas)} track(s) sem arquivo no disco preservada(s) na playlist raiz")

            if self.cancel_requested: return None, None, ""

            progress_callback(ui_strings["status_saving"], 0.85)
            self.log(log_paths, "")
            self.log(log_paths, "--- FASE 3: Gravando Entidades nas Playlists ---")
            
            total_entidades = 0
            for list_id, dict_tracks in tracks_por_playlist.items():
                if self.cancel_requested: return None, None, ""

                for track_id, caminho in sorted(dict_tracks.items(), key=lambda item: item[1]):
                    # Busca o tail atual: a entidade que ninguém aponta (nextEntityId=0)
                    tail = cursor.execute( # type: ignore
                        "SELECT id FROM PlaylistEntity WHERE listId = ? AND nextEntityId = 0 ORDER BY id DESC LIMIT 1",
                        (list_id,)
                    ).fetchone()

                    # Insere o novo no final (nextEntityId=0 = é o novo tail)
                    cursor.execute( # type: ignore
                        "INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, membershipReference) VALUES (?, ?, ?, 0, 0)",
                        (list_id, track_id, db_uuid)
                    )
                    novo_id = cursor.lastrowid

                    # Aponta o tail anterior para o novo (encadeamento correto)
                    if tail: # type: ignore
                        cursor.execute( # type: ignore
                            "UPDATE PlaylistEntity SET nextEntityId = ? WHERE id = ?",
                            (novo_id, tail[0])
                        )

                    total_entidades += 1
            self.log(log_paths, f"  {total_entidades} entrada(s) inserida(s) em {len(tracks_por_playlist)} playlist(s)")

            conn.commit()
            
            self.log(log_paths, "")
            self.log(log_paths, "=" * 60)
            self.log(log_paths, f"SINCRONIZACAO CONCLUIDA")
            self.log(log_paths, f"  Faixas novas inseridas : {novas_musicas}")
            self.log(log_paths, f"  Playlists na arvore    : {len(tracks_por_playlist)}")
            self.log(log_paths, f"  Fim                    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            _lp, _dp = log_paths if isinstance(log_paths, tuple) else (log_paths, None)
            if _lp:
                self.log(log_paths, f"  Arquivo de log         : {_lp}")
            if _dp:
                self.log(log_paths, f"  Arquivo de debug       : {_dp}")
            self.log(log_paths, "=" * 60)
            
            resumo_final = [
                "\n" + "="*60,
                "RESUMO DA OPERAÇÃO",
                f"Músicas Novas Injetadas : {novas_musicas}",
                f"Músicas Órfãs Removidas : {apagadas_musicas}",
                f"Playlists na Árvore     : {len(tracks_por_playlist)}",
                f"Total de Referências    : {total_entidades}",
                "="*60
            ]
            
            return novas_musicas, apagadas_musicas, "\n".join(report_lines + resumo_final)
        finally:
            conn.close()