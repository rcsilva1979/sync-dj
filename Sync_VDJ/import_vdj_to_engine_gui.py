import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import sys
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from PIL import Image, ImageTk
from collections import defaultdict

# Adiciona o diretório pai ao sys.path para importar módulos da raiz e pacotes irmãos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database_utils import localizar_bancos_dados_engine, get_database_uuid
from engine_sync_app import SyncManager, get_resource_path
from constants import (IS_WIN, IS_MAC, VERSAO_ATUAL, APP_NAME,
                       FONT_FAMILY, COLOR_BG_DARK, COLOR_TEXT_NORMAL,
                       COLOR_TEXT_MUTED, COLOR_SWITCH_OFF,
                       CORNER_RADIUS_NONE)
from report_gui import ReportWindow

try:
    # Tenta importar o VDJManager para localizar as pastas MyLists
    from .vdj_logic import VDJManager
except (ImportError, ValueError):
    from Sync_VDJ.vdj_logic import VDJManager

class PlaylistContentWindow(ctk.CTkToplevel):
    def __init__(self, master, title, xml_paths):
        super().__init__(master)
        self.txt = master.txt
        self.title(f"{self.txt.get('content_title', 'Conteúdo:').format(title=title)} ({VERSAO_ATUAL})") # type: ignore
        self.geometry("850x600")
        self.configure(fg_color=COLOR_BG_DARK)

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)
        
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
                except Exception:
                    pass
            self.after(200, aplicar_icone)

        lbl = ctk.CTkLabel(self, text=self.txt.get("music_list_header", "Lista de Músicas: {title}").format(title=title), font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color="#00E5A3")
        lbl.pack(pady=10)
        
        self.textbox = ctk.CTkTextbox(self, font=ctk.CTkFont(family=FONT_FAMILY, size=11), width=800)
        self.textbox.pack(padx=20, pady=10, fill="both", expand=True)
        # Configuração de tags de cores para o relatório
        self.textbox.tag_config("exists", foreground="#00E5A3")
        self.textbox.tag_config("missing", foreground="#FF5555")

        try:
            total_tracks = 0
            found_count = 0
            missing_count = 0
            for xml_path in xml_paths:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                songs = root.findall("song")
                
                if songs:
                    drive = "PC"
                    if IS_WIN:
                        drive = os.path.splitdrive(xml_path)[0] or "PC"
                    elif IS_MAC:
                        p = os.path.abspath(xml_path).split(os.sep)
                        if len(p) > 2 and p[1] == 'Volumes':
                            drive = p[2]
                        else:
                            drive = "System"

                    self.textbox.insert("end", f">>> DISCO {drive.upper()} <<<\n")
                    for song in songs:
                        total_tracks += 1
                        path = song.get("path", "N/A")
                        artist = song.get("artist", "Desconhecido")
                        title_song = song.get("title", "Sem Título")
                        
                        # Verifica a existência do arquivo no disco
                        if path != "N/A" and os.path.exists(path):
                            found_count += 1
                            tag = "exists"
                        else:
                            missing_count += 1
                            tag = "missing"
                            
                        self.textbox.insert("end", f"{total_tracks:03d} | {artist} - {title_song}\n      path=\"{path}\"\n\n", tag)
            
            if total_tracks == 0:
                self.textbox.insert("end", self.txt.get("no_tracks_in_playlist", "Nenhuma música encontrada nesta playlist.")) # type: ignore
            else:
                # Adiciona o resumo consolidado ao final do relatório
                self.textbox.insert("end", "\n" + "="*60 + "\n")
                self.textbox.insert("end", "RESUMO DE DISPONIBILIDADE NO DISCO:\n")
                self.textbox.insert("end", f"  Músicas Localizadas: {found_count}\n", "exists")
                self.textbox.insert("end", f"  Músicas Não Encontradas: {missing_count}\n", "missing")
                self.textbox.insert("end", "="*60 + "\n")
        except Exception as e: # type: ignore
            self.textbox.insert("end", self.txt.get("error_reading_xml", "Erro ao ler XML:").format(error=e)) # type: ignore

        self.textbox.configure(state="disabled")

        btn_close = ctk.CTkButton(self, text=self.txt.get("close_btn", "Fechar"), corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), command=self.destroy)
        btn_close.pack(pady=10)
        
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

class ImportVDJToEngineWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.manager = SyncManager()

        self.title(f"{self.txt.get('vdj_import_btn', 'Importar Playlist do VDJ para o Engine')} ({VERSAO_ATUAL})")

        self.geometry("600x520")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if os.path.exists(self.caminho_icone):
            def aplicar_icone():
                try:
                    if IS_WIN:
                        self.iconbitmap(self.caminho_icone)
                        self.wm_iconbitmap(self.caminho_icone)
                    else:
                        img = Image.open(self.caminho_icone)
                        self._icon_photo = ImageTk.PhotoImage(img)
                        self.iconphoto(False, self._icon_photo)
                except Exception:
                    pass
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
                                font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"), text_color="#00E5A3")
        lbl_title.pack(pady=(5, 10))

        # Seletor de Playlist do VirtualDJ
        vdj_frame = ctk.CTkFrame(self, fg_color="transparent")
        vdj_frame.pack(padx=20, pady=10, fill="x")
        ctk.CTkLabel(vdj_frame, text=self.txt.get("select_vdj_playlist_label", "Selecionar Playlist do VirtualDJ (.vdjfolder):"), font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        
        # Frame auxiliar para o combo e o botão de visualização
        vdj_selector_frame = ctk.CTkFrame(vdj_frame, fg_color="transparent")
        vdj_selector_frame.pack(fill="x", pady=(5, 0))

        self.vdj_options = self.scan_vdj_playlists()
        self.combo_vdj = ctk.CTkComboBox(vdj_selector_frame, variable=self.selected_vdj_playlist, values=self.vdj_options, width=420, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY), dropdown_font=ctk.CTkFont(family=FONT_FAMILY))
        self.combo_vdj.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_view = ctk.CTkButton( # type: ignore
            vdj_selector_frame, 
            text=self.txt.get("view_tracks_btn", "Ver Músicas"), 
            width=100, 
            fg_color=COLOR_SWITCH_OFF, corner_radius=CORNER_RADIUS_NONE,
            text_color=COLOR_TEXT_NORMAL, # type: ignore
            hover_color="#777777",
            command=self.show_playlist_contents
        )
        btn_view.pack(side="right")

        if self.vdj_options: # type: ignore
            self.selected_vdj_playlist.set(self.vdj_options[0]) # type: ignore

        def get_vol_id(path):
            abs_p = os.path.abspath(path)
            if IS_WIN:
                return os.path.splitdrive(abs_p)[0].upper()
            else:
                p = abs_p.split(os.sep)
                return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

        # Label Informativo unificado (Padrão Mirror Sync)
        drives_totais = sorted(list({get_vol_id(d) for d in self.found_databases}))
        texto_drives = " | ".join(drives_totais)
        self.lbl_db_auto = ctk.CTkLabel(self, font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"))
        self.lbl_db_auto.configure(text=f"✔ {self.txt['engine_dbs_detected'].format(count=len(self.found_databases))}: {texto_drives}", text_color="#00E5A3")
        self.lbl_db_auto.pack(pady=(5, 0))

        # Status e Progresso
        self.lbl_status = ctk.CTkLabel(self, text=self.txt.get("select_playlist_to_start", "Selecione a playlist para começar"), font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT_MUTED, wraplength=450)
        self.lbl_status.pack(pady=(20, 5))
        
        self.progress_bar = ctk.CTkProgressBar(self, width=500, height=10, progress_color="#00E5A3", corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        self.btn_run = ctk.CTkButton(self, text=self.txt.get("start_import_vdj_btn", "Iniciar Importação para o Engine DJ"), 
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                     fg_color="#D84343", text_color=COLOR_TEXT_NORMAL, hover_color="#CE2323", height=45, width=350, 
                                     corner_radius=CORNER_RADIUS_NONE, command=self.run_import)
        self.btn_run.pack(pady=20)

        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

    def scan_vdj_playlists(self):
        """Varre as pastas MyLists em todos os discos e retorna a lista de arquivos .vdjfolder agrupados por nome."""
        temp_map = defaultdict(list)
        directories = self.vdj_manager.localizar_diretorios_folders()
        
        for folder in directories:
            if os.path.exists(folder):
                for file in os.listdir(folder):
                    if file.lower().endswith('.vdjfolder'):
                        name = os.path.splitext(file)[0]
                        full_path = os.path.join(folder, file)
                        temp_map[name].append(full_path)
        
        self.playlist_map = {}
        options = []
        for name, paths in temp_map.items():
            display_name = name
            if len(paths) > 1:
                display_name += " (Híbrida)"
            
            self.playlist_map[display_name] = paths
            options.append(display_name)
        
        return sorted(options)

    def update_status(self, msg, color="#AAAAAA"):
        self.lbl_status.configure(text=msg, text_color=color)
        self.update_idletasks()

    def show_playlist_contents(self):
        display_name = self.selected_vdj_playlist.get()
        xml_paths = self.playlist_map.get(display_name)
        
        if not xml_paths:
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_select_valid_playlist_to_view", "Selecione uma playlist válida para visualizar seu conteúdo."))
            return

        PlaylistContentWindow(self, display_name, xml_paths) # type: ignore

    def run_import(self):
        # Verifica se o Engine DJ está aberto (mesma lógica e mensagens do Mirror Sync)
        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."
            )
            return

        display_name = self.selected_vdj_playlist.get()
        xml_paths = self.playlist_map.get(display_name)
        
        if not xml_paths:
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_select_valid_vdj_xml", "Selecione um arquivo XML do VirtualDJ válido."))
            return

        def get_disk_id(path):
            """Retorna um identificador único de disco (Letra no Win, /Volumes/Nome no Mac)."""
            if IS_WIN:
                return os.path.splitdrive(os.path.abspath(path))[0].upper()
            elif IS_MAC:
                abs_path = os.path.normpath(os.path.abspath(path))
                if abs_path.startswith("/Volumes/"):
                    parts = abs_path.split(os.sep)
                    return f"{os.sep}{parts[1]}{os.sep}{parts[2]}" # Ex: /Volumes/MEUHD
                return "INTERNAL"
            return ""

        # Mapeia discos para seus respectivos bancos de dados
        dbs_by_drive = {get_disk_id(db): db for db in self.found_databases}
        playlist_name = display_name.split(" (")[0]

        # Inicializa log para Importação VDJ
        log_paths = self.manager.iniciar_log(
            "N/A", "VDJ to Engine", playlist_name, 
            self.manager.config.get("log", True), self.manager.config.get("debug", False), 
            tool_name="VDJ_IMPORT")

        self.manager.log(log_paths, "=== INÍCIO DA IMPORTAÇÃO VIRTUAL DJ -> ENGINE DJ ===")
        self.manager.log(log_paths, f"Playlist selecionada : {display_name}")
        self.manager.log(log_paths, f"XMLs de origem        : {xml_paths}")

        try: # type: ignore
            self.update_status(self.txt.get("status_reading_vdj_playlist", "Lendo playlist VDJ..."), "#00E5A3")
            self.manager.log(log_paths, "Lendo arquivos XML e mapeando faixas por drive...", nivel="debug")
            
            report_lines = [
                f"RELATÓRIO DE IMPORTAÇÃO VIRTUAL DJ -> ENGINE DJ\n",
                f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n",
                f"Playlist: {playlist_name}\n",
                "="*60 + "\n\n"
            ]
            tracks_added = 0
            tracks_existed = 0
            tracks_missing_file = 0

            # Agrupa músicas pelo disco de origem
            tracks_by_drive = defaultdict(list)
            for xml_path in xml_paths:
                self.manager.log(log_paths, f"Analisando XML: {xml_path}", nivel="debug")
                tree = ET.parse(xml_path)
                root = tree.getroot()
                for song in root.findall("song"):
                    path_abs = str(song.get("path") or "")
                    if not path_abs: continue
                    
                    drive = get_disk_id(path_abs)
                    if drive in dbs_by_drive:
                        tracks_by_drive[drive].append({
                            "path": path_abs,
                            "artist": str(song.get("artist") or ""),
                            "title": str(song.get("title") or "")
                        })
                    else:
                        self.manager.log(log_paths, f"  [AVISO] Drive {drive} não encontrado ou sem banco Engine para: {path_abs}", nivel="debug")

            total_tracks = sum(len(t) for t in tracks_by_drive.values())
            self.manager.log(log_paths, f"Total de faixas identificadas para importação: {total_tracks}")

            if total_tracks == 0: # type: ignore
                self.manager.log(log_paths, "ERRO: Nenhuma faixa válida encontrada nos XMLs para os bancos de dados conectados.")
                messagebox.showwarning(self.txt.get("warning_title", "Aviso"), self.txt.get("warning_no_tracks_in_xml", "Nenhuma faixa encontrada no arquivo XML."))
                return

            processed_count = 0
            for drive, tracks in tracks_by_drive.items():
                db_path = dbs_by_drive[drive]
                self.manager.log(log_paths, f"\n--- PROCESSANDO DISCO {drive} ---")
                self.manager.log(log_paths, f"Banco de dados: {db_path}", nivel="debug")

                self.update_status(self.txt.get("importing_tracks_to_drive", "Importando {count} faixas para o banco do disco {drive}...").format(count=len(tracks), drive=drive), "#00E5A3")
                
                conn = sqlite3.connect(db_path) # type: ignore
                report_lines.append(f"--- DISCO {drive} ---\n")
                cursor = conn.cursor()
                db_uuid = get_database_uuid(db_path)
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                now_ts = int(datetime.now().timestamp())

                # Cria ou limpa a playlist neste banco específico
                cursor.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = 0", (playlist_name,))
                row = cursor.fetchone()
                if row: # type: ignore
                    playlist_id = row[0]
                    self.manager.log(log_paths, f"Limpando playlist existente '{playlist_name}' (ID {playlist_id})")
                    cursor.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (playlist_id,))
                else:
                    self.manager.log(log_paths, f"Criando nova playlist raiz: '{playlist_name}'")
                    cursor.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, 0, 1, 0, ?, 1)", (playlist_name, now_iso))
                    playlist_id = cursor.lastrowid

                added_track_ids = set()
                for vtrack in tracks:
                    processed_count += 1
                    title_v = vtrack.get('title') or "Sem Título"
                    self.manager.log(log_paths, f"  [OK] Validando: {vtrack.get('artist')} - {title_v}", nivel="debug")
                    self.progress_bar.set(processed_count / total_tracks)
                    path_abs = vtrack["path"]
                    if not os.path.exists(path_abs):
                        self.manager.log(log_paths, f"    [FALTANTE] Arquivo físico não encontrado: {path_abs}")
                        report_lines.append(f"  [ERRO] Arquivo não encontrado: {vtrack.get('artist')} - {title_v}\n")
                        tracks_missing_file += 1
                        continue
                    
                    # O manager resolve o caminho relativo baseado no m.db deste disco
                    engine_rel = self.manager.formatar_caminho_engine(path_abs, db_path)
                    cursor.execute("SELECT id FROM Track WHERE REPLACE(path, '\\', '/') = ?", (engine_rel.replace("\\", "/"),))
                    tr_row = cursor.fetchone()
                    
                    if tr_row:
                        track_id = tr_row[0]
                        self.manager.log(log_paths, f"    ↳ Faixa já existe na coleção (ID {track_id}).", nivel="debug")
                        tracks_existed += 1
                        report_lines.append(f"  [EXISTE] {vtrack.get('artist')} - {title_v}\n")
                    else:
                        fname = os.path.basename(path_abs)
                        self.manager.log(log_paths, f"    [TRACK +] Adicionando nova faixa à coleção: {fname}")
                        ext = os.path.splitext(fname)[1].replace('.', '')
                        cursor.execute("""
                            INSERT INTO Track (path, filename, title, artist, fileType, dateCreated, dateAdded, isAnalyzed, isAvailable, fileBytes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
                        """, (engine_rel, fname, vtrack["title"] or os.path.splitext(fname)[0], vtrack["artist"], ext, now_ts, now_ts, os.path.getsize(path_abs)))
                        track_id = cursor.lastrowid
                        tracks_added += 1
                        report_lines.append(f"  [NOVA] {vtrack.get('artist')} - {title_v}\n")

                    # Evita o erro 'Unique Constraint Failed' se a música estiver duplicada na playlist do VDJ
                    if track_id in added_track_ids:
                        self.manager.log(log_paths, f"    [SKIP] Ignorada por duplicidade na playlist.", nivel="debug")
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
                self.manager.log(log_paths, f"--- DISCO {drive} FINALIZADO ---")
                report_lines.append("\n")
            
            resumo = [
                "="*60,
                "RESUMO DA OPERAÇÃO",
                f"Novas faixas adicionadas: {tracks_added}",
                f"Faixas já existentes:    {tracks_existed}",
                f"Arquivos não encontrados: {tracks_missing_file}",
                "="*60
            ]
            report_content = "\n".join(report_lines) + "\n".join(resumo)

            self.update_status(self.txt.get("status_import_complete").format(processed_count=processed_count, num_drives=len(tracks_by_drive)), "green")
            self.manager.log(log_paths, f"Processamento concluído: {processed_count} faixas sincronizadas entre os discos.")
            self.manager.log(log_paths, "=== IMPORTAÇÃO CONCLUÍDA COM SUCESSO ===")

            if self.manager.config.get("show_report", True):
                ReportWindow(
                    self,
                    title=f"Relatório Importação VDJ: {playlist_name}",
                    header="RESULTADO DA IMPORTAÇÃO",
                    content=report_content,
                    playlist_name=playlist_name,
                    txt=self.txt
                )

        except Exception as e:
            self.manager.log(log_paths, f"ERRO CRÍTICO NA IMPORTAÇÃO: {e}")
            self.update_status(self.txt.get("error_importing_vdj_playlist").format(error=e), "red")
            messagebox.showerror(self.txt.get("error_import_title", "Erro de Importação"), self.txt.get("error_importing_vdj_playlist_detail").format(error=e))