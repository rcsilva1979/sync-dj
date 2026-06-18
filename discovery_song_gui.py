import warnings
import logging
import os
import sys

logging.captureWarnings(True)
logging.getLogger("py.warnings").setLevel(logging.WARNING)

warnings.filterwarnings(
    "ignore",
    message=r"Call to deprecated function recognize_song.*",
    category=DeprecationWarning
)

import shutil

# Detecta plataforma antes do setup do FFmpeg para evitar NameError em modo congelado
_IS_WIN = sys.platform.startswith('win')

# Tenta carregar o FFmpeg via static-ffmpeg antes de importar o Shazam
try:
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            # Garante que a pasta temporária do executável esteja no topo do PATH
            os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ["PATH"]
    else:
        import static_ffmpeg
        static_ffmpeg.add_paths()
except ImportError:
    pass

import asyncio
import threading
import httpx
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from shazamio import Shazam
from mutagen.easyid3 import EasyID3
from mutagen import File
from mutagen.id3 import ID3, TIT2, TPE1, APIC
from mutagen.mp4 import MP4, MP4Cover
from engine_sync_app import get_resource_path, SyncManager
from report_gui import ReportWindow # type: ignore
from constants import (IS_WIN, FONT_FAMILY, APP_NAME, VERSAO_ATUAL, 
                       COLOR_BG_DARK, COLOR_TEXT_NORMAL, COLOR_TEXT_MUTED, 
                       COLOR_SWITCH_OFF, CORNER_RADIUS_NONE)

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
        self.geometry("650x550")
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

        # Progresso
        lbl_status = ctk.CTkLabel(self, textvariable=self.progress_text, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        lbl_status.pack(padx=40, pady=(15, 2), anchor="w")
        
        self.progress_bar = ctk.CTkProgressBar(self, width=570, height=12, progress_color="#9B59B6", corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(padx=40, pady=5)
        self.progress_bar.set(0)

        # Botão Ação
        self.btn_start = ctk.CTkButton(self, text=self.txt["discovery_btn_action"], 
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                                       height=45, fg_color="#9B59B6", hover_color="#8E44AD", text_color="#FFFFFF",
                                       corner_radius=CORNER_RADIUS_NONE, command=self.start_thread)
        self.btn_start.pack(pady=20, padx=40, fill="x")

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)

    def log(self, message: str | list[tuple[str, str | None]], tag: str | None = None):
        """Registra no arquivo de log (se ativo) e acumula para o relatório final.""" # type: ignore
        if isinstance(message, list): # message is a list of (text, tag) tuples
            full_message_for_file_log = "".join([text for text, _ in message])
            if self.log_paths:
                self.manager.log(self.log_paths, full_message_for_file_log)
            self.report_content.append(message) # Store the list of tuples
        else: # message is a single string
            if self.log_paths:
                self.manager.log(self.log_paths, message)
            self.report_content.append([(message, tag)]) # Store as a list with one tuple

    def start_thread(self):
        self.btn_start.configure(state="disabled")
        threading.Thread(target=self.run_async_process, daemon=True).start()

    def run_async_process(self):
        asyncio.run(self.process_logic())
        self.progress_text.set(self.txt.get("status_done", "✅ Concluído!"))
        self.after(0, lambda: self.btn_start.configure(state='normal'))

        # Abrir relatório detalhado se configurado nas preferências
        if self.manager.config.get("show_report", True):
            folder_name = os.path.basename(os.path.normpath(self.folder_path.get()))
            self.after(0, lambda: ReportWindow(
                self,
                title=self.txt["discovery_title"],
                header="SONG DISCOVERY LOG REPORT",
                log_entries=self.report_content, # Passa a lista de tuplas
                playlist_name=folder_name,
                txt=self.txt
            ))

    async def try_identify(self, shazam, file_path, filename):
        """Identifica a música usando o caminho do arquivo (mais estável e preciso)."""
        try:
            ### NAO MEXER NA LINHA LOGO ABAIXO #####
            out = await shazam.recognize_song(file_path)
            return out
        except Exception as e:
            self.log(f"⚠️ Erro na detecção de {filename}: {e}")
            
        return {}

    async def process_logic(self):
        folder = self.folder_path.get()
        self.report_content = [] # Limpa conteúdo de relatório anterior

        # Inicializa o log em arquivo conforme as preferências salvas no hub (main.py)
        self.log_paths = self.manager.iniciar_log(
            folder, "N/A", os.path.basename(folder),
            self.manager.config.get("log", True),
            self.manager.config.get("debug", False),
            tool_name="DISCOVERY"
        )

        # Verificação exaustiva de FFmpeg
        # Tenta nomes comuns (com e sem .exe) para cobrir Windows e Mac empacotados
        ffmpeg_names = ["ffmpeg.exe", "ffmpeg"]
        ffmpeg_path = None

        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # No modo compilado, verifica primeiro dentro da pasta raiz do bundle (onde injetamos via release.yml)
            for name in ffmpeg_names:
                candidate = os.path.join(sys._MEIPASS, name)
                if os.path.exists(candidate):
                    ffmpeg_path = candidate
                    # Reforça a inclusão do bundle no PATH caso não tenha ocorrido no import
                    if sys._MEIPASS not in os.environ["PATH"]:
                        os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ["PATH"]
                    break
        
        # Se não encontrou no bundle ou se não estiver congelado, tenta o sistema (fallback)
        if not ffmpeg_path:
            for name in ffmpeg_names:
                ffmpeg_path = shutil.which(name)
                if ffmpeg_path: break

        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            loc = sys._MEIPASS if getattr(sys, 'frozen', False) else "PATH"
            self.log(f"❌ Erro crítico: FFmpeg não encontrado em '{loc}'. Verifique se o antivírus não bloqueou o processo.", tag="error")
            return

        if not os.path.exists(folder):
            self.log(f"❌ Erro: Pasta '{folder}' não encontrada.")
            return

        shazam = Shazam()
        self.log(f"--- Iniciando verificação de tags na pasta: {folder} ---")
        
        # Busca recursiva de arquivos
        all_files = []
        for root_dir, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg')):
                    all_files.append(os.path.join(root_dir, f))
        
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
            self.after(0, lambda p=percent/100: self.progress_bar.set(p))
            self.progress_text.set(f"Processando {i+1} de {total_files}: {filename}")

            title, artist = get_song_tags(file_path)
            
            # Lógica: Só pulamos se já tiver tags E (se a capa for solicitada, ele já deve ter uma)
            possui_tags = title and artist
            precisa_de_capa = self.include_cover.get() and not has_cover(file_path)

            if not self.overwrite_tags.get() and possui_tags and not precisa_de_capa:
                self.log(f"✅ Já possui tags e capa (ou não solicitada): {artist} - {title}")
                stats["ignorados"] += 1
                continue

            faltando = []
            if not possui_tags: faltando.append("Tags")
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