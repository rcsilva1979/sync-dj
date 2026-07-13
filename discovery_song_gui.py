import warnings
import logging
import os
import sys
import json
import subprocess

logging.captureWarnings(True)
logging.getLogger("py.warnings").setLevel(logging.WARNING)

warnings.filterwarnings(
    "ignore",
    message=r"Call to deprecated function recognize_song.*",
    category=DeprecationWarning
)

import asyncio
import threading
import httpx
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from shazamio import Shazam
from shazamio.exceptions import FailedDecodeJson, BadMethod
from shazamio.interfaces.client import HTTPClientInterface
from shazamio.misc import Request
from aiohttp_retry import RetryClient, ExponentialRetry # type: ignore
import shutil # Keep shutil for later use
import imageio_ffmpeg # New import
from mutagen.easyid3 import EasyID3
from mutagen import File
from mutagen.id3 import ID3, TIT2, TPE1, APIC
from mutagen.mp4 import MP4, MP4Cover
from engine_sync_app import get_resource_path, SyncManager
from report_gui import ReportWindow # type: ignore
from constants import (IS_WIN, FONT_FAMILY, APP_NAME, VERSAO_ATUAL, 
                       COLOR_BG_DARK, COLOR_TEXT_NORMAL, COLOR_TEXT_MUTED, 
                       COLOR_SWITCH_OFF, CORNER_RADIUS_NONE)


class DebugShazamHTTPClient(HTTPClientInterface):
    """Cliente HTTP do Shazam com mensagens de erro mais úteis para debug."""

    def __init__(self, retry_options=None):
        self.retry_options = retry_options or ExponentialRetry(
            attempts=20,
            max_timeout=60,
            statuses={500, 502, 503, 504, 429},
        )

    async def request(self, method: str, url: str, *args, **kwargs):
        async with RetryClient(
            retry_options=self.retry_options,
            raise_for_status=False,
        ) as client:
            if method.upper() == "GET":
                request_cm = client.get(url, **kwargs)
            elif method.upper() == "POST":
                request_cm = client.post(url, **kwargs)
            else:
                raise BadMethod("Accept only GET/POST")

            async with request_cm as resp:
                body_text = await resp.text()
                content_type = resp.headers.get("Content-Type", "")
                try:
                    return json.loads(body_text)
                except Exception as exc:
                    snippet = body_text[:500].replace("\n", " ").replace("\r", " ")
                    raise FailedDecodeJson(
                        f"status={resp.status}, content_type={content_type}, body={snippet!r}"
                    ) from exc

# --- Utilitários de Tag ---
def has_cover(file_path):
    """Verifica se o arquivo já possui uma capa embutida."""
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.mp3':
            tags = ID3(file_path)
            return any(frame.startswith('APIC') for frame in tags.keys())
        elif ext == '.m4a':
            tags = MP4(file_path)
            return 'covr' in tags
    except:
        pass
    return False

# --- Lógica de Identificação e API ---
def get_song_tags(file_path):
    """Retorna título e artista do arquivo. Retorna (None, None) se não encontrar."""
    try:
        audio = File(file_path, easy=True)
        title = audio.get('title', [""])[0].strip()
        artist = audio.get('artist', [""])[0].strip()
        
        # Se a tag for algo genérico, tratamos como vazio
        if title.lower() in ["unknown", "track 1", "audio"] or len(title) < 2:
            title = None
        if artist.lower() in ["unknown", "artista desconhecido"] or len(artist) < 2:
            artist = None
            
        return title, artist
    except Exception:
        try:
            # Tentativa genérica para outros formatos (M4A, FLAC)
            audio = File(file_path, easy=True)
            return audio.get('title', [None])[0], audio.get('artist', [None])[0]
        except:
            return None, None

def update_song_tags(file_path, title, artist, genre=None, date=None, cover_data=None):
    """Escreve as tags de título e artista no arquivo."""
    try:
        # Tenta EasyID3 primeiro (MP3)
        try:
            audio = EasyID3(file_path)
        except Exception:
            # Se não tiver ID3, cria
            audio = File(file_path, easy=True)
            audio.add_tags()
        
        audio['title'] = title
        audio['artist'] = artist
        if genre:
            audio['genre'] = genre
        if date:
            audio['date'] = date
        audio.save()

        # Inserir Capa (Artwork) se fornecido
        if cover_data:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.mp3':
                tags = ID3(file_path)
                tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3, # 3 é a capa frontal
                    desc='Cover',
                    data=cover_data
                ))
                tags.save()
            elif ext == '.m4a':
                tags = MP4(file_path)
                tags['covr'] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
                tags.save()

        return True
    except Exception as e:
        print(f"Erro ao salvar tags: {e}")
        return False

# --- Interface Gráfica ---
class DiscoverySongWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(f"{self.txt['discovery_title']} ({VERSAO_ATUAL})")
        self.geometry("650x680")
        self.minsize(650, 680)
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        self.transient(master)
        self.grab_set()
        
        self.manager = SyncManager()
        self.folder_path = ctk.StringVar(value="")
        self.progress_val = ctk.DoubleVar(value=0)
        self.progress_text = ctk.StringVar(value=self.txt["discovery_status_waiting"])
        self.include_cover = ctk.BooleanVar(value=True)
        self.rename_files = ctk.BooleanVar(value=True)
        self.overwrite_tags = ctk.BooleanVar(value=False)
        self.simulation_mode = ctk.BooleanVar(value=False)
        self.start_offset_var = ctk.StringVar(value="Início")
        self.final_ffmpeg_path: str | None = None
        self._cancel_requested = threading.Event()

        self.log_paths = None
        self.report_content = [] # Alterado para lista de tuplas (mensagem, tag_cor)

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if os.path.exists(self.caminho_icone):
            def aplicar_icone():
                try:
                    if IS_WIN:
                        self.iconbitmap(self.caminho_icone)
                    else:
                        img = Image.open(self.caminho_icone)
                        self._icon_photo = ImageTk.PhotoImage(img)
                        self.iconphoto(False, self._icon_photo)
                except: pass
            self.after(200, aplicar_icone)

        # Rodapé (empacotado primeiro para garantir visibilidade na base)
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

        self.construir_ui()
        self.after(10, self.lift)

    def construir_ui(self):
        # Logo Superior
        img_carregada = False
        try:
            logo_path = get_resource_path(os.path.join("images", "logo_discovery_song.png"))
            if os.path.exists(logo_path):
                logo_img = ctk.CTkImage(Image.open(logo_path), size=(500, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(25, 10))
                img_carregada = True
        except:
            pass

        if not img_carregada:
            # Fallback para Título se a imagem falhar
            lbl_title = ctk.CTkLabel(self, text=self.txt["discovery_title"].upper(), 
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"), text_color="#9B59B6")
            lbl_title.pack(pady=(25, 15))

        # Seleção de Pasta
        frame_folder = ctk.CTkFrame(self, fg_color="transparent")
        frame_folder.pack(fill="x", padx=40, pady=5)
        
        ctk.CTkLabel(frame_folder, text=self.txt["discovery_folder_label"], 
                     font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        
        entry_folder = ctk.CTkEntry(frame_folder, textvariable=self.folder_path, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY))
        entry_folder.pack(side="left", fill="x", expand=True, pady=5, padx=(0, 10))
        
        btn_browse = ctk.CTkButton(frame_folder, text=self.txt["browse"], width=100, fg_color="#9B59B6", hover_color="#8E44AD",
                                   text_color="#FFFFFF", corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"),
                                   command=self.browse_folder)
        btn_browse.pack(side="right", pady=5)

        # Opções (Switches)
        frame_switches = ctk.CTkFrame(self, fg_color="transparent")
        frame_switches.pack(fill="x", padx=40, pady=10)

        sw_style = {"font": ctk.CTkFont(family=FONT_FAMILY, size=12), "progress_color": "#9B59B6", "fg_color": COLOR_SWITCH_OFF}

        ctk.CTkSwitch(frame_switches, text=self.txt["discovery_include_cover"], variable=self.include_cover, **sw_style).pack(anchor="w", pady=4)
        ctk.CTkSwitch(frame_switches, text=self.txt["discovery_rename_files"], variable=self.rename_files, **sw_style).pack(anchor="w", pady=4)
        ctk.CTkSwitch(frame_switches, text=self.txt["discovery_overwrite_tags"], variable=self.overwrite_tags, **sw_style).pack(anchor="w", pady=4)
        ctk.CTkSwitch(frame_switches, text=self.txt["discovery_simulation_mode"], variable=self.simulation_mode, **sw_style).pack(anchor="w", pady=4)

        # Seletor de Offset Inicial
        frame_offset = ctk.CTkFrame(self, fg_color="transparent")
        frame_offset.pack(fill="x", padx=40, pady=(0, 5))

        ctk.CTkLabel(
            frame_offset,
            text="Iniciar análise a partir de:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=COLOR_TEXT_NORMAL
        ).pack(side="left", padx=(0, 10))

        ctk.CTkSegmentedButton(
            frame_offset,
            values=["Início", "30s", "1min", "2min"],
            variable=self.start_offset_var,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            selected_color="#9B59B6",
            selected_hover_color="#8E44AD",
            unselected_color="#2a2a2a",
            unselected_hover_color="#3a3a3a",
            corner_radius=4
        ).pack(side="left")

        # Progresso
        lbl_status = ctk.CTkLabel(self, textvariable=self.progress_text, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        lbl_status.pack(padx=40, pady=(15, 2), anchor="w")
        
        self.progress_bar = ctk.CTkProgressBar(self, width=570, height=12, progress_color="#9B59B6", corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(padx=40, pady=5)
        self.progress_bar.set(0)

        # Botões de Ação
        frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        frame_actions.pack(pady=(20, 10), padx=40, fill="x")

        self.btn_start = ctk.CTkButton(frame_actions, text=self.txt["discovery_btn_action"], 
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                                       height=45, fg_color="#9B59B6", hover_color="#8E44AD", text_color="#FFFFFF",
                                       corner_radius=CORNER_RADIUS_NONE, command=self.start_thread,
                                       state="disabled")
        self.btn_start.pack(fill="x")

        self.btn_cancel = ctk.CTkButton(frame_actions, text="Cancelar", 
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                                        height=35, fg_color="#C0392B", hover_color="#A93226", text_color="#FFFFFF",
                                        corner_radius=CORNER_RADIUS_NONE, command=self.request_cancel,
                                        state="disabled")
        self.btn_cancel.pack(fill="x", pady=(8, 0))

        # Habilita o botão somente quando uma pasta for selecionada
        self.folder_path.trace_add("write", self._on_folder_changed)
        self._on_folder_changed()  # aplica estado inicial (desabilitado)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(os.path.normpath(folder))

    def _on_folder_changed(self, *_):
        """Habilita ou desabilita o botão de acordo com a pasta selecionada."""
        has_folder = bool(self.folder_path.get().strip())
        self.btn_start.configure(state="normal" if has_folder else "disabled")

    def log(self, message: str | list[tuple[str, str | None]], tag: str | None = None):
        """Registra no arquivo de log (se ativo) e acumula para o relatório final."""
        if isinstance(message, list): # message is a list of (text, tag) tuples
            full_message_for_file_log = "".join([text for text, _ in message])
            if self.log_paths:
                self.manager.log(self.log_paths, full_message_for_file_log)
            self.report_content.append(message) # Store the list of tuples
        else: # message is a single string
            if tag == "debug" and not self.manager.config.get("debug", False):
                return
            if self.log_paths:
                self.manager.log(self.log_paths, message)
            self.report_content.append([(message, tag)]) # Store as a list with one tuple

    def request_cancel(self):
        """Solicita o encerramento amigável do processamento em execução."""
        self._cancel_requested.set()
        if self.btn_cancel:
            self.btn_cancel.configure(state="disabled")
        self.progress_text.set("⏹️ Cancelando processo...")

    def start_thread(self):
        self._cancel_requested.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        threading.Thread(target=self.run_async_process, daemon=True).start()

    def run_async_process(self):
        """Ponto de entrada da thread para o loop de eventos assíncrono."""
        # 1. Configurar FFmpeg ANTES de iniciar o loop
        try:
            # Obtém o executável do pacote imageio_ffmpeg (que você mencionou que funcionava)
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            self.final_ffmpeg_path = ffmpeg_exe
            
            # Pega o diretório do binário
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            
            # injeta no PATH de forma absoluta
            current_path = os.environ.get("PATH", "")
            if ffmpeg_dir not in current_path:
                os.environ["PATH"] = f"{ffmpeg_dir}{os.pathsep}{current_path}"
            
            # Define variável de ambiente para bibliotecas que a consultam
            os.environ["FFMPEG_BINARY"] = ffmpeg_exe
            
            # Configura pydub explicitamente para usar o mesmo ffmpeg
            # (recognize_song() usa pydub internamente para converter o áudio)
            try:
                from pydub import AudioSegment
                AudioSegment.converter = ffmpeg_exe
                AudioSegment.ffmpeg = ffmpeg_exe
            except Exception:
                pass
            
            self.log(f"✅ FFmpeg configurado via PATH: {ffmpeg_exe}")
        except Exception as e:
            self.log(f"⚠️ Erro ao localizar FFmpeg via imageio: {e}", tag="error")
            self.final_ffmpeg_path = shutil.which("ffmpeg")
            if not self.final_ffmpeg_path:
                self.log(f"❌ Erro crítico: FFmpeg não encontrado no sistema.", tag="error")

        # 2. Configurar Política de Loop para Windows (necessário para subprocessos)
        if IS_WIN:
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass

        # 3. Inicia o loop
        asyncio.run(self.process_logic())
        if self._cancel_requested.is_set():
            self.progress_text.set("⏹️ Processo cancelado pelo usuário.")
        else:
            self.progress_text.set(self.txt.get("status_done", "✅ Concluído!"))

        self.after(0, lambda: self.btn_start.configure(state='normal'))
        self.after(0, lambda: self.btn_cancel.configure(state='disabled'))

        # Abrir relatório detalhado se configurado nas preferências
        if not self._cancel_requested.is_set() and self.manager.config.get("show_report", True):
            folder_name = os.path.basename(os.path.normpath(self.folder_path.get()))
            self.after(0, lambda: ReportWindow(
                self,
                title=self.txt["discovery_title"],
                header="SONG DISCOVERY LOG REPORT",
                log_entries=self.report_content, # Passa a lista de tuplas
                playlist_name=folder_name,
                txt=self.txt
            ))

    def _get_audio_duration(self, file_path: str) -> float:
        """Retorna a duração em segundos usando ffmpeg (stderr parsing).
        
        Não depende do ffprobe, que não está presente no bundle imageio_ffmpeg.
        """
        import re
        try:
            ffmpeg_exe = self.final_ffmpeg_path or "ffmpeg"
            cmd = [
                ffmpeg_exe, "-i", file_path,
                "-f", "null", "-"
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            )
            # ffmpeg imprime duração no stderr: "Duration: HH:MM:SS.ms"
            match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
            if match:
                h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
                return h * 3600 + m * 60 + s
        except Exception:
            pass
        return 0.0

    def _extract_audio_snippet(self, file_path: str, offset_seconds: int, duration: int = 12) -> str | None:
        """Extrai um trecho de áudio como arquivo WAV temporário e retorna o caminho.
        
        O shazamio.recognize() aceita caminhos de arquivo; raw PCM bytes são
        rejeitados internamente com 'FFmpeg not found or failed to convert audio'.
        O arquivo temp será apagado após uso pelo chamador.
        """
        import tempfile
        try:
            ffmpeg_exe = self.final_ffmpeg_path or "ffmpeg"
            # Cria arquivo temp com extensão .wav
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_path = tmp.name
            tmp.close()

            cmd = [
                ffmpeg_exe,
                "-ss", str(offset_seconds),  # seek para o offset
                "-i", file_path,
                "-t", str(duration),           # duração do trecho
                "-f", "wav",                   # container WAV (com cabeçalho)
                "-acodec", "pcm_s16le",        # 16-bit PCM
                "-ac", "1",                    # mono
                "-ar", "16000",                # 16 kHz (exact format shazamio needs)
                "-y",                          # sobrescreve sem perguntar
                tmp_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            )
            if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
                return tmp_path
            # Limpa arquivo vazio/falho
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return None
        except Exception as e:
            self.log(f"⚠️ [DEBUG] Erro ao extrair trecho no offset {offset_seconds}s: {e}", tag="debug")
            return None

    async def try_identify(self, shazam: Shazam, file_path: str, filename: str):
        """Identifica a música tentando múltiplos pontos do áudio.

        Estratégia de múltiplos offsets:
        - Tenta o arquivo completo (método padrão do shazamio)
        - Se falhar, extrai trechos de 12s em: 60s, 90s, 120s, 150s
        - Isso captura músicas com intros longas ou transições de DJ
        """
        abs_path = os.path.abspath(file_path)
        ffmpeg_exe = self.final_ffmpeg_path or "ffmpeg"

        # Determina o offset inicial escolhido pelo usuário na UI
        _offset_map = {"Início": 0, "30s": 30, "1min": 60, "2min": 120}
        user_start_offset = _offset_map.get(self.start_offset_var.get(), 0)

        if self._cancel_requested.is_set():
            self.log("⏹️ Cancelado antes da identificação.", tag="debug")
            return {}

        # --- Tentativa 1: início escolhido pelo usuário ---
        # recognize_song() usa pydub internamente, que precisa do ffmpeg para
        # decodificar MP3/M4A. Como o pydub não localiza o ffmpeg bundled com
        # confiabilidade, convertemos SEMPRE via nosso ffmpeg para WAV primeiro.
        # Carregamos com AudioSegment.from_wav() (que usa wave nativo do Python, sem ffprobe).
        self.log(f"🛠️ [DEBUG] Tentativa 1 - Extraindo WAV (offset {user_start_offset}s)", tag="debug")
        tmp_path = self._extract_audio_snippet(abs_path, user_start_offset)
        if tmp_path:
            try:
                from pydub import AudioSegment
                audio_segment = AudioSegment.from_wav(tmp_path)
                result = await shazam.recognize_song(audio_segment)
                if result and 'track' in result:
                    self.log(f"✅ [DEBUG] Identificado na tentativa 1 (offset {user_start_offset}s)", tag="debug")
                    return result
            except FailedDecodeJson as e:
                self.log(f"⚠️ Resposta inválida da API do Shazam para {filename}: {e}", tag="error")
                self.log("ℹ️ Isso normalmente indica bloqueio de rede, resposta HTML/403/429, ou instabilidade da API.", tag="error")
                return {}
            except Exception as e:
                self.log(f"⚠️ [DEBUG] Offset {user_start_offset}s falhou: {e}", tag="debug")
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        # --- Tentativas seguintes: outros offsets via ffmpeg ---
        # Obtém duração do arquivo para não ir além do fim
        duration_secs = self._get_audio_duration(abs_path)
        self.log(f"🕐 [DEBUG] Duração detectada: {duration_secs:.1f}s", tag="debug")

        # Gera lista de offsets complementares (exclui o já tentado)
        all_offsets = [0, 30, 60, 90, 120, 150]
        candidate_offsets = [o for o in all_offsets if o != user_start_offset]
        # Filtra offsets que estão além da duração do arquivo
        valid_offsets = [
            o for o in candidate_offsets
            if duration_secs == 0 or o + 10 < duration_secs
        ]

        for attempt_num, offset in enumerate(valid_offsets, start=2):
            if self._cancel_requested.is_set():
                self.log("⏹️ Cancelado durante as tentativas de identificação.", tag="debug")
                return {}

            self.log(
                f"🔄 [DEBUG] Tentativa {attempt_num} - Offset: {offset}s",
                tag="debug"
            )
            tmp_path = self._extract_audio_snippet(abs_path, offset)

            if not tmp_path:
                self.log(f"⚠️ [DEBUG] Não foi possível extrair trecho em {offset}s", tag="debug")
                continue

            try:
                from pydub import AudioSegment
                audio_segment = AudioSegment.from_wav(tmp_path)
                result = await shazam.recognize_song(audio_segment)
                if result and 'track' in result:
                    self.log(f"✅ [DEBUG] Identificado no offset {offset}s (tentativa {attempt_num})", tag="debug")
                    return result
                # Pequena pausa para não sobrecarregar a API
                await asyncio.sleep(1.0)
            except FailedDecodeJson as e:
                self.log(f"⚠️ [DEBUG] Resposta inválida no offset {offset}s: {e}", tag="debug")
                await asyncio.sleep(2.0)
                continue
            except Exception as e:
                self.log(f"⚠️ [DEBUG] Erro no offset {offset}s: {e}", tag="debug")
                continue
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return {}

    async def process_logic(self):
        folder = self.folder_path.get()
        self.report_content = [] # Limpa conteúdo de relatório anterior

        # Inicializa o log em arquivo conforme as preferências salvas no hub (main.py)
        self.log_paths = self.manager.iniciar_log( # type: ignore
            folder, "N/A", os.path.basename(folder),
            self.manager.config.get("log", True),
            self.manager.config.get("debug", False),
            tool_name="DISCOVERY"
        )

        if self.final_ffmpeg_path:
            self.log(f"🛠️ [DEBUG] PATH completo: {os.environ['PATH']}", tag="debug") # type: ignore
            self.log(f"✅ FFmpeg pronto para uso: {self.final_ffmpeg_path}")
            # Teste de execução direta para validar o ambiente
            cmd_test = [self.final_ffmpeg_path, "-version"]
            try:
                proc_res = subprocess.run(cmd_test, capture_output=True, text=True, check=True)
                self.log(f"🚀 Teste de execução FFmpeg: OK ({proc_res.stdout.splitlines()[0]})")
            except Exception as ex:
                self.log(f"⚠️ Falha no teste de execução do FFmpeg: {ex}", tag="error")
        else:
            self.log(f"❌ Erro crítico: FFmpeg não disponível.", tag="error")
            return

        if not os.path.exists(folder):
            self.log(f"❌ Erro: Pasta '{folder}' não encontrada.")
            return

        # Instancia o Shazam com um cliente HTTP que preserva detalhes do erro.
        shazam = Shazam(http_client=DebugShazamHTTPClient()) 
        self.log(f"--- Iniciando verificação de tags na pasta: {folder} ---")
        
        # Busca recursiva de arquivos
        all_files = []
        for root_dir, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg')):
                    # Normaliza o caminho do arquivo para evitar problemas com barras no Windows
                    all_files.append(os.path.normpath(os.path.join(root_dir, f)))
        
        total_files = len(all_files)
        if total_files == 0:
            self.log("Nenhum arquivo de áudio encontrado.")
            return
            
        # Contadores para o relatório
        stats = {
            "total": total_files,
            "identificados": 0,
            "atualizados": 0,
            "renomeados": 0,
            "falhas": 0,
            "ignorados": 0
        }

        for i, file_path in enumerate(all_files):
            filename = os.path.basename(file_path)
            current_folder = os.path.dirname(file_path)
            # Atualiza Barra de Progresso e Label
            percent = ((i + 1) / total_files) * 100
            def update_ui(p=percent/100, msg=f"Processando {i+1} de {total_files}: {filename}"):
                try:
                    if self.winfo_exists():
                        if self.progress_bar.winfo_exists():
                            self.progress_bar.set(p)
                        self.progress_text.set(msg)
                except Exception:
                    pass
            try:
                self.after(0, update_ui)
            except Exception:
                pass

            if self._cancel_requested.is_set():
                self.log("⏹️ Processo cancelado pelo usuário.")
                break

            title, artist = get_song_tags(file_path)

            # Quando a sobrescrita está desligada, só processamos arquivos sem title preenchida.
            # Isso evita reprocessar músicas já identificadas anteriormente.
            possui_title = bool(title and str(title).strip())
            precisa_de_capa = self.include_cover.get() and not has_cover(file_path)

            if not self.overwrite_tags.get() and possui_title:
                self.log(f"⏭️ Ignorado por já possuir title gravada: {artist or 'Artista desconhecido'} - {title}")
                stats["ignorados"] += 1
                continue

            faltando = []
            if not title: faltando.append("Tags")
            if precisa_de_capa: faltando.append("Capa")
            msg_identificando = f"🔍 {filename} (Faltando: {' & '.join(faltando)}). Identificando..."
            
            try:
                out = await self.try_identify(shazam, file_path, filename)
                if 'track' in out:
                    self.log(msg_identificando)
                    stats["identificados"] += 1
                    
                    track = out['track']
                    new_title = track.get('title', 'Unknown Title')
                    new_artist = track.get('subtitle', 'Unknown Artist')
                    
                    # Extrair Gênero
                    new_genre = track.get('genres', {}).get('primary', '')
                    
                    # Extrair Ano (Released) percorrendo as seções de metadados
                    new_date = None
                    for section in track.get('sections', []):
                        if section.get('type') == 'SONG':
                            for meta in section.get('metadata', []):
                                if meta.get('title') == 'Released':
                                    new_date = meta.get('text')
                                    break
                    
                    log_msg = f"✨ Identificado: {new_artist} - {new_title}"
                    
                    # Baixar Capa se o switch estiver ligado
                    cover_bytes = None
                    if self.include_cover.get():
                        cover_url = track.get('images', {}).get('coverart')
                        if cover_url:
                            try:
                                async with httpx.AsyncClient() as client:
                                    resp = await client.get(cover_url)
                                    if resp.status_code == 200:
                                        cover_bytes = resp.content
                                        self.log(f"🖼️ Capa encontrada e baixada!")
                            except Exception as e:
                                self.log(f"⚠️ Erro ao baixar capa: {e}")
                        else:
                            self.log(f"ℹ️ Capa não disponível no Shazam para esta faixa.")

                    if new_date: log_msg += f" ({new_date})"
                    self.log(log_msg)
                    
                    if self.simulation_mode.get():
                        self.log("🧪 [SIMULAÇÃO] Nenhuma alteração foi gravada.")
                        continue

                    if update_song_tags(file_path, new_title, new_artist, new_genre, new_date, cover_bytes):
                        stats["atualizados"] += 1
                        res_msg = "Tags" + (" e Capa" if cover_bytes else "")
                        self.log(f"💾 {res_msg} atualizadas com sucesso!")
                        
                        if self.rename_files.get():
                            # Renomear o arquivo para "Artista - Título.ext"
                            ext = os.path.splitext(filename)[1]
                            clean_name = f"{new_artist} - {new_title}{ext}".replace("/", "-").replace("\\", "-")
                            new_path = os.path.join(current_folder, clean_name)
                            try:
                                os.rename(file_path, new_path)
                                self.log(f"📝 Renomeado para: {clean_name}")
                                stats["renomeados"] += 1
                            except Exception:
                                pass # Evita erro se o arquivo já tiver o nome correto
                    else:
                        self.log(f"❌ Falha ao gravar tags no arquivo.")
                        stats["falhas"] += 1
                else:
                    self.log(msg_identificando, tag="error")
                    self.log("❌ Não foi possível identificar o áudio.", tag="error")
                    stats["falhas"] += 1
            except Exception as e:
                self.log(f"💥 Erro ao processar {filename}: {e}")
                stats["falhas"] += 1

        # Geração do Relatório Final no Log
        report = (
            f"\n" + "="*30 + "\n"
            f"📊 RELATÓRIO FINAL\n"
            f"{'='*30}\n"
            f"📁 Arquivos Processados: {stats['total']}\n"
            f"✨ Músicas Identificadas: {stats['identificados']}\n"
            f"💾 Tags Atualizadas: {stats['atualizados']}\n"
            f"📝 Arquivos Renomeados: {stats['renomeados']}\n"
            f"⏭️ Arquivos Ignorados: {stats['ignorados']}\n"
            f"❌ Falhas/Não Encontrados: {stats['falhas']}\n"
            f"{'='*30}\n"
            f"Modo Simulação: {'ATIVADO' if self.simulation_mode.get() else 'Desativado'}\n"
        )
        self.log(report)
