import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import sys
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from PIL import Image
from collections import defaultdict

# Adiciona o diretório pai ao sys.path para importar módulos da raiz e pacotes irmãos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database_utils import localizar_bancos_dados_engine, get_database_uuid
from engine_sync_app import SyncManager, get_resource_path

try:
    # Tenta importar o VDJManager para localizar as pastas MyLists
    from .vdj_logic import VDJManager
except (ImportError, ValueError):
    from Sync_VDJ.vdj_logic import VDJManager

class PlaylistContentWindow(ctk.CTkToplevel):
    def __init__(self, master, title, xml_path):
        super().__init__(master)
        self.txt = master.txt
        self.title(self.txt.get("content_title", "Conteúdo:").format(title=title)) # type: ignore
        self.geometry("850x600")
        self.configure(fg_color="#1a1a1a")

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)
        
        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if sys.platform.startswith('win') and os.path.exists(self.caminho_icone):
            def aplicar_icone():
                try:
                    self.iconbitmap(self.caminho_icone)
                except: pass
            self.after(200, aplicar_icone)

        lbl = ctk.CTkLabel(self, text=self.txt.get("music_list_header", "Lista de Músicas: {title}").format(title=title), font=ctk.CTkFont(size=14, weight="bold"), text_color="#00E5A3")
        lbl.pack(pady=10)
        
        self.textbox = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=11))
        self.textbox.pack(padx=20, pady=10, fill="both", expand=True)

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            songs = root.findall("song")
            
            if not songs:
                self.textbox.insert("end", self.txt.get("no_tracks_in_playlist", "Nenhuma música encontrada nesta playlist.")) # type: ignore
            else:
                for i, song in enumerate(songs, 1):
                    path = song.get("path", "N/A")
                    artist = song.get("artist", "Desconhecido")
                    title_song = song.get("title", "Sem Título")
                    self.textbox.insert("end", f"{i:03d} | {artist} - {title_song}\n      path=\"{path}\"\n\n")
        except Exception as e: # type: ignore
            self.textbox.insert("end", self.txt.get("error_reading_xml", "Erro ao ler XML:").format(error=e)) # type: ignore

        self.textbox.configure(state="disabled")

        btn_close = ctk.CTkButton(self, text=self.txt.get("close_btn", "Fechar"), command=self.destroy)
        btn_close.pack(pady=10)

class ImportVDJToEngineWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.manager = SyncManager()

        self.title(self.txt.get("vdj_import_btn", "Importar Playlist do VDJ para o Engine"))
        self.geometry("600x520")
        self.resizable(False, False)
        self.configure(fg_color="#242424")

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if sys.platform.startswith('win'):
            if os.path.exists(self.caminho_icone):
                def aplicar_icone():
                    try:
                        self.iconbitmap(self.caminho_icone)
                        self.wm_iconbitmap(self.caminho_icone)
                    except: pass
                self.after(200, aplicar_icone)

        self.selected_vdj_playlist = ctk.StringVar()
        self.vdj_manager = VDJManager()
        self.playlist_map = {} # Mapeia "Nome Exibido" -> "Caminho Real"
        
        # Busca automática de bancos de dados Engine
        self.found_databases = localizar_bancos_dados_engine()
        self.build_ui()

    def build_ui(self):
        try:
            vdj_logo_path = get_resource_path(os.path.join("images", "logo_engine_VDJ.png"))
            if os.path.exists(vdj_logo_path):
                imagem_logo = Image.open(vdj_logo_path)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_logo = ctk.CTkLabel(self, text="", image=ctk_logo)
                lbl_logo.pack(pady=(10, 5))
        except: pass

        lbl_title = ctk.CTkLabel(self, text=self.txt.get("vdj_import_btn", "Importar Playlist do VDJ para o Engine"), 
                                font=ctk.CTkFont(size=16, weight="bold"), text_color="#00E5A3")
        lbl_title.pack(pady=(5, 10))

        # Seletor de Playlist do VirtualDJ
        vdj_frame = ctk.CTkFrame(self, fg_color="transparent")
        vdj_frame.pack(padx=20, pady=10, fill="x")
        ctk.CTkLabel(vdj_frame, text=self.txt.get("select_vdj_playlist_label", "Selecionar Playlist do VirtualDJ (.vdjfolder):"), font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        # Frame auxiliar para o combo e o botão de visualização
        vdj_selector_frame = ctk.CTkFrame(vdj_frame, fg_color="transparent")
        vdj_selector_frame.pack(fill="x", pady=(5, 0))

        self.vdj_options = self.scan_vdj_playlists() # type: ignore
        self.combo_vdj = ctk.CTkComboBox(vdj_selector_frame, variable=self.selected_vdj_playlist, values=self.vdj_options, width=420)
        self.combo_vdj.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_view = ctk.CTkButton(
            vdj_selector_frame, 
            text=self.txt.get("view_tracks_btn", "Ver Músicas"), 
            width=100, 
            fg_color="#555555", 
            text_color="#FFFFFF", # type: ignore
            hover_color="#777777",
            command=self.show_playlist_contents
        )
        btn_view.pack(side="right")

        if self.vdj_options:
            self.selected_vdj_playlist.set(self.vdj_options[0]) # type: ignore

        # Info sobre bancos detectados
        dbs_info = " | ".join([os.path.splitdrive(d)[0] for d in self.found_databases])
        lbl_dbs = ctk.CTkLabel(self, text=self.txt.get("dbs_found_label", "Bancos de Dados Engine DJ Localizados:").format(dbs_info=dbs_info), font=ctk.CTkFont(size=11), text_color="#00E5A3")
        lbl_dbs.pack(pady=(5, 0))

        # Status e Progresso
        self.lbl_status = ctk.CTkLabel(self, text=self.txt.get("select_playlist_to_start", "Selecione a playlist para começar"), font=ctk.CTkFont(size=12), text_color="#AAAAAA", wraplength=450)
        self.lbl_status.pack(pady=(20, 5))
        
        self.progress_bar = ctk.CTkProgressBar(self, width=500, height=10, progress_color="#00E5A3")
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        # Botão de Execução
        self.btn_run = ctk.CTkButton(self, text=self.txt.get("start_import_vdj_btn", "Iniciar Importação para o Engine DJ"), font=ctk.CTkFont(size=14, weight="bold"),
                                     fg_color="#D84343", text_color="#FFFFFF", hover_color="#CE2323", height=45, width=350, 
                                     command=self.run_import)
        self.btn_run.pack(pady=20)

    def scan_vdj_playlists(self):
        """Varre as pastas MyLists em todos os discos e retorna a lista de arquivos .vdjfolder."""
        self.playlist_map = {}
        options = []
        directories = self.vdj_manager.localizar_diretorios_folders()
        
        for folder in directories:
            if os.path.exists(folder):
                drive = os.path.splitdrive(folder)[0] or "PC"
                
                for file in os.listdir(folder):
                    if file.lower().endswith('.vdjfolder'):
                        name = os.path.splitext(file)[0]
                        # Formato: [C:] Nome da Playlist
                        display_name = f"[{drive.upper()}] {name}"
                        full_path = os.path.join(folder, file)
                        self.playlist_map[display_name] = full_path
                        options.append(display_name)
        
        return sorted(options)

    def update_status(self, msg, color="#AAAAAA"):
        self.lbl_status.configure(text=msg, text_color=color)
        self.update_idletasks()

    def show_playlist_contents(self):
        display_name = self.selected_vdj_playlist.get()
        xml_path = self.playlist_map.get(display_name)
        
        if not xml_path or not os.path.exists(xml_path):
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_select_valid_playlist_to_view", "Selecione uma playlist válida para visualizar seu conteúdo."))
            return

        PlaylistContentWindow(self, display_name, xml_path) # type: ignore

    def run_import(self):
        display_name = self.selected_vdj_playlist.get()
        xml_path = self.playlist_map.get(display_name)
        
        if not xml_path or not os.path.exists(xml_path):
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_select_valid_vdj_xml", "Selecione um arquivo XML do VirtualDJ válido."))
            return

        # Mapeia discos para seus respectivos bancos de dados
        dbs_by_drive = {os.path.splitdrive(db)[0].upper(): db for db in self.found_databases}
        playlist_name = os.path.splitext(os.path.basename(xml_path))[0]

        try: # type: ignore
            self.update_status(self.txt.get("status_reading_vdj_playlist", "Lendo playlist VDJ..."), "#00E5A3")
            tree = ET.parse(xml_path) # type: ignore
            root = tree.getroot()
            
            # Agrupa músicas pelo disco de origem
            tracks_by_drive = defaultdict(list)
            for song in root.findall("song"):
                path_abs = str(song.get("path") or "")
                if not path_abs: continue
                
                drive = os.path.splitdrive(path_abs)[0].upper()
                if drive in dbs_by_drive:
                    tracks_by_drive[drive].append({
                        "path": path_abs,
                        "artist": str(song.get("artist") or ""),
                        "title": str(song.get("title") or "")
                    })

            total_tracks = sum(len(t) for t in tracks_by_drive.values())
            if total_tracks == 0: # type: ignore
                messagebox.showwarning(self.txt.get("warning_title", "Aviso"), self.txt.get("warning_no_tracks_in_xml", "Nenhuma faixa encontrada no arquivo XML."))
                return

            processed_count = 0
            for drive, tracks in tracks_by_drive.items():
                db_path = dbs_by_drive[drive]
                self.update_status(self.txt.get("importing_tracks_to_drive", "Importando {count} faixas para o banco do disco {drive}...").format(count=len(tracks), drive=drive), "#00E5A3")
                
                conn = sqlite3.connect(db_path) # type: ignore
                cursor = conn.cursor()
                db_uuid = get_database_uuid(db_path)
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                now_ts = int(datetime.now().timestamp())

                # Cria ou limpa a playlist neste banco específico
                cursor.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = 0", (playlist_name,))
                row = cursor.fetchone()
                if row: # type: ignore
                    playlist_id = row[0]
                    cursor.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (playlist_id,))
                else:
                    cursor.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, 0, 1, 0, ?, 1)", (playlist_name, now_iso))
                    playlist_id = cursor.lastrowid

                added_track_ids = set()
                for vtrack in tracks:
                    processed_count += 1
                    self.progress_bar.set(processed_count / total_tracks)
                    path_abs = vtrack["path"]
                    if not os.path.exists(path_abs): continue # type: ignore
                    
                    # O manager resolve o caminho relativo baseado no m.db deste disco
                    engine_rel = self.manager.formatar_caminho_engine(path_abs, db_path)
                    cursor.execute("SELECT id FROM Track WHERE REPLACE(path, '\\', '/') = ?", (engine_rel.replace("\\", "/"),))
                    tr_row = cursor.fetchone()
                    
                    if tr_row:
                        track_id = tr_row[0]
                    else:
                        fname = os.path.basename(path_abs)
                        ext = os.path.splitext(fname)[1].replace('.', '')
                        cursor.execute("""
                            INSERT INTO Track (path, filename, title, artist, fileType, dateCreated, dateAdded, isAnalyzed, isAvailable, fileBytes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
                        """, (engine_rel, fname, vtrack["title"] or os.path.splitext(fname)[0], vtrack["artist"], ext, now_ts, now_ts, os.path.getsize(path_abs)))
                        track_id = cursor.lastrowid

                    # Evita o erro 'Unique Constraint Failed' se a música estiver duplicada na playlist do VDJ
                    if track_id in added_track_ids:
                        continue
                    added_track_ids.add(track_id)

                    # Link PlaylistEntity (estilo lista encadeada do Engine)
                    tail = cursor.execute("SELECT id FROM PlaylistEntity WHERE listId = ? AND nextEntityId = 0 ORDER BY id DESC LIMIT 1", (playlist_id,)).fetchone()
                    cursor.execute("INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, membershipReference) VALUES (?, ?, ?, 0, 0)", (playlist_id, track_id, db_uuid)) # type: ignore
                    new_id = cursor.lastrowid
                    if tail:
                        cursor.execute("UPDATE PlaylistEntity SET nextEntityId = ? WHERE id = ?", (new_id, tail[0]))

                conn.commit()
                conn.close()
            
            self.update_status(self.txt.get("status_import_complete").format(processed_count=processed_count, num_drives=len(tracks_by_drive)), "green")
            messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("success_vdj_import").format(playlist_name=playlist_name))
            self.destroy()

        except Exception as e:
            self.update_status(self.txt.get("error_importing_vdj_playlist").format(error=e), "red")
            messagebox.showerror(self.txt.get("error_import_title", "Erro de Importação"), self.txt.get("error_importing_vdj_playlist_detail").format(error=e))