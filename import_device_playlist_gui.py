import os
import sys
import customtkinter as ctk
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox
import sqlite3
import threading
from datetime import datetime
from collections import defaultdict

from engine_sync_app import get_resource_path, SyncManager
from database_utils import (get_removable_drive_roots,
    localizar_bancos_dados_removiveis, get_playlists_from_db, get_tracks_from_playlist,
    get_database_uuid, get_all_playlists_hierarchical
)
from report_gui import ReportWindow
from constants import (IS_WIN, APP_NAME, VERSAO_ATUAL, FONT_FAMILY,
                       COLOR_BG_DARK, COLOR_TEXT_MUTED, CORNER_RADIUS_NONE,
                       COLOR_ACCENT_BLUE, COLOR_TEXT_NORMAL, COLOR_ACCENT_GREEN)

class ImportDevicePlaylistWindow(ctk.CTkToplevel):
    """
    Janela para importar playlists de um dispositivo Engine DJ (HD externo, pendrive)
    para um banco de dados Engine DJ local.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(f"{self.txt['engine_tools_import_device_playlist_title']} ({VERSAO_ATUAL})")
        self.geometry("700x650")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        self.manager = SyncManager()
        self.device_db_path = ctk.StringVar(value="")
        self.local_db_path = ctk.StringVar(value="")
        self.selected_device_playlist = ctk.StringVar(value="")
        self.selected_local_playlist_name = ctk.StringVar(value="") # Nome da playlist a ser criada/atualizada localmente

        self.progress_val = ctk.DoubleVar(value=0)
        self.status_var = ctk.StringVar(value="")

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

        self.construir_ui()
        self._load_device_dbs()
        self._load_local_dbs()
        self.combo_device_db.bind("<<ComboboxSelected>>", self._on_device_db_selected)

    def construir_ui(self):
        lbl_title = ctk.CTkLabel(self, text=self.txt["engine_tools_import_device_playlist_title"].upper(),
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"), text_color=COLOR_ACCENT_BLUE)
        lbl_title.pack(pady=(25, 20))

        # Frame para seleção do Disco Removível
        frame_device_db = ctk.CTkFrame(self, fg_color="transparent") # Renomeado para refletir a mudança
        frame_device_db.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(frame_device_db, text=self.txt["engine_tools_removable_drive_label"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w") # Novo label
        self.combo_device_db = ctk.CTkComboBox(frame_device_db, variable=self.device_db_path, values=[], width=500, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY), command=self._on_device_db_selected) # Command alterado
        self.combo_device_db.pack(fill="x", expand=True) # type: ignore
        
        # Label Informativo do Status do Banco do Dispositivo
        self.lbl_device_db_status = ctk.CTkLabel(frame_device_db, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_device_db_status.pack(pady=(2, 0), anchor="w")

        # Frame para seleção da Playlist do Dispositivo
        frame_device_playlist = ctk.CTkFrame(self, fg_color="transparent")
        frame_device_playlist.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(frame_device_playlist, text=self.txt["playlist"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        self.combo_device_playlist = ctk.CTkComboBox(frame_device_playlist, variable=self.selected_device_playlist, values=[], width=500, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY))
        self.combo_device_playlist.pack(fill="x", expand=True)
        self.combo_device_playlist.bind("<<ComboboxSelected>>", self._on_device_playlist_selected)

        # Label Informativo do Status de TODOS os Bancos Locais
        frame_all_local_dbs = ctk.CTkFrame(self, fg_color="transparent")
        frame_all_local_dbs.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(frame_all_local_dbs, text=self.txt["engine_tools_all_local_dbs_label"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        self.lbl_all_local_dbs_status = ctk.CTkLabel(frame_all_local_dbs, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_all_local_dbs_status.pack(pady=(2, 0), anchor="w")

        # Nome da Playlist Local (Editável)
        frame_local_playlist_name = ctk.CTkFrame(self, fg_color="transparent")
        frame_local_playlist_name.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(frame_local_playlist_name, text=self.txt["playlist"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        self.entry_local_playlist_name = ctk.CTkEntry(frame_local_playlist_name, textvariable=self.selected_local_playlist_name, width=500, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY))
        self.entry_local_playlist_name.pack(fill="x", expand=True)
        self.entry_local_playlist_name.configure(state="readonly") # type: ignore # Torna o campo somente leitura
        # Botão de Importar
        self.btn_import = ctk.CTkButton(self, text=self.txt["engine_tools_import_device_playlist_btn"],
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                                       height=45, fg_color=COLOR_ACCENT_BLUE, hover_color="#1F4E79", text_color=COLOR_TEXT_NORMAL,
                                       corner_radius=CORNER_RADIUS_NONE, command=self.start_import_thread)
        self.btn_import.pack(pady=20, padx=40, fill="x")

        # Progresso
        self.progress_bar = ctk.CTkProgressBar(self, width=620, height=12, progress_color=COLOR_ACCENT_BLUE, corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(pady=4)
        self.progress_bar.set(0)

        self.lbl_status = ctk.CTkLabel(self, textvariable=self.status_var, font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT_MUTED)
        self.lbl_status.pack(pady=(5, 10))

        # Rodapé
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

    def _on_device_db_selected(self, selected_drive_root):
        """Callback quando um disco removível é selecionado."""
        if not selected_drive_root or selected_drive_root == "Nenhum dispositivo encontrado":
            self.lbl_device_db_status.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            self.combo_device_playlist.configure(values=[])
            self.selected_device_playlist.set("")
            return

        # Tenta encontrar o m.db no drive selecionado
        device_db_path = os.path.join(selected_drive_root, "Engine Library", "Database2", "m.db")
        if os.path.exists(device_db_path):
            self.lbl_device_db_status.configure(text=f"✔ Banco de dados encontrado: {os.path.basename(device_db_path)}", text_color="#00E5A3")
            self.device_db_path.set(device_db_path) # Atualiza a variável com o caminho completo do DB
            self._load_device_playlists(device_db_path)
        else:
            self.lbl_device_db_status.configure(text=f"✖ Banco de dados não encontrado em {selected_drive_root}", text_color="#FF5555")
            self.device_db_path.set("") # Limpa o caminho do DB se não encontrado
            self.combo_device_playlist.configure(values=[])
            self.selected_device_playlist.set("")

    def _load_device_dbs(self):
        """Carrega os caminhos raiz dos discos removíveis."""
        removable_drives = get_removable_drive_roots()
        if removable_drives:
            self.combo_device_db.configure(values=removable_drives)
            self.device_db_path.set(removable_drives[0])
            self._on_device_db_selected(removable_drives[0]) # Dispara a busca do DB no primeiro drive
            
            # Identifica os drives para exibir no status
            drives = sorted(list({self.manager._get_vol_id(d) for d in removable_drives}))
            texto_drives = " | ".join(drives)
            self.lbl_device_db_status.configure(
                text=f"✔ {self.txt['engine_dbs_detected'].format(count=len(removable_drives))}: {texto_drives}", 
                text_color="#00E5A3"
            )
        else:
            self.combo_device_db.configure(values=["Nenhum dispositivo encontrado"])
            self.device_db_path.set("Nenhum dispositivo encontrado")
            self.combo_device_db.set("Nenhum dispositivo encontrado")
            self.combo_device_playlist.configure(values=[])
            self.selected_device_playlist.set("")
            self.lbl_device_db_status.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")

    def _show_local_dbs_tooltip(self, event):
        """Exibe um tooltip com a lista completa de bancos locais."""
        if hasattr(self, '_tooltip_window') and self._tooltip_window:
            return # Tooltip já visível

        tooltip_text = "\n".join(self.local_dbs_by_drive.values())
        if not tooltip_text:
            return

        x = self.lbl_all_local_dbs_status.winfo_rootx() + self.lbl_all_local_dbs_status.winfo_width()
        y = self.lbl_all_local_dbs_status.winfo_rooty()

        self._tooltip_window = ctk.CTkToplevel(self)
        self._tooltip_window.wm_overrideredirect(True) # Remove borda e barra de título
        self._tooltip_window.wm_geometry(f"+{x}+{y}")
        self._tooltip_window.configure(fg_color="#333333")

        label = ctk.CTkLabel(self._tooltip_window, text=tooltip_text, justify="left", # type: ignore
                             fg_color="#333333", text_color="white",
                             font=ctk.CTkFont(family=FONT_FAMILY, size=10))
        label.pack(padx=5, pady=5)

    def _hide_tooltip(self, event):
        """Esconde o tooltip."""
        if hasattr(self, '_tooltip_window') and self._tooltip_window:
            self._tooltip_window.destroy()
            del self._tooltip_window

    def _load_local_dbs(self):
        """Carrega todos os bancos de dados m.db locais (fixos e removíveis)."""
        local_dbs = self.manager.localizar_bancos_dados()
        self.local_dbs_by_drive = {} # Mapeia drive_id -> db_path

        if local_dbs:
            # Identifica os drives para exibir no status
            drives = sorted(list({self.manager._get_vol_id(d) for d in local_dbs}))
            texto_drives = " | ".join(drives)
            self.lbl_all_local_dbs_status.configure(
                text=f"✔ {self.txt['engine_dbs_detected'].format(count=len(local_dbs))}: {texto_drives}", 
                text_color="#00E5A3"
            )
            
            for db_path in local_dbs:
                drive_id = self.manager._get_vol_id(db_path)
                self.local_dbs_by_drive[drive_id] = db_path
        else:
            self.lbl_all_local_dbs_status.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            # Não exibe messagebox aqui, apenas atualiza o status na UI

    def _on_device_playlist_selected(self, event):
        """Callback quando uma playlist do dispositivo é selecionada."""
        selected_playlist_path = self.selected_device_playlist.get()
        self.selected_local_playlist_name.set(selected_playlist_path.split(" / ")[-1])

    def _load_device_playlists(self, db_path):
        """Carrega as playlists do banco de dados do dispositivo selecionado."""
        if not os.path.exists(db_path):
            self.combo_device_playlist.configure(values=[])
            self.selected_device_playlist.set("")
            return
        
        # get_all_playlists_hierarchical retorna tuplas (caminho_completo, id)
        playlists_raw = get_all_playlists_hierarchical(db_path)
        playlists_display = [pl_path for pl_path, _ in playlists_raw]
        
        if playlists_display:
            self.combo_device_playlist.configure(values=playlists_display)
            self.selected_device_playlist.set(playlists_display[0])
            self._on_device_playlist_selected(None) # Atualiza o nome da playlist local
        else:
            self.combo_device_playlist.configure(values=[])
            self.selected_device_playlist.set("")
            self.selected_local_playlist_name.set("")

    def start_import_thread(self):
        device_db = self.device_db_path.get()
        local_db = self.local_db_path.get()
        device_playlist_path = self.selected_device_playlist.get()
        local_playlist_name = self.selected_local_playlist_name.get().strip()

        if not os.path.exists(device_db) or not os.path.exists(local_db):
            messagebox.showerror(self.txt["error_title"], "Selecione bancos de dados válidos.") # type: ignore
            return # type: ignore
        if not device_playlist_path:
            messagebox.showerror(self.txt["error_title"], "Selecione uma playlist do dispositivo.")
            return
        if not local_playlist_name:
            messagebox.showerror(self.txt["error_title"], "Informe um nome para a playlist local.")
            return

        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a importação.\n\nNenhuma alteração foi feita."
            )
            return

        self.btn_import.configure(state="disabled")
        self.status_var.set("Iniciando importação...")
        self.progress_bar.set(0)

        threading.Thread(target=self._perform_import_logic, daemon=True).start()

    def _perform_import_logic(self):
        device_db = self.device_db_path.get()
        local_db = self.local_db_path.get()
        device_playlist_path = self.selected_device_playlist.get()
        local_playlist_name = self.selected_local_playlist_name.get().strip()

        log_paths = self.manager.iniciar_log(
            "N/A", local_db, local_playlist_name,
            self.manager.config.get("log", True),
            self.manager.config.get("debug", False),
            tool_name="IMPORT_DEVICE_PL"
        )

        self.manager.log(log_paths, f"Dispositivo DB: {device_db}")
        self.manager.log(log_paths, f"Playlist do Dispositivo: {device_playlist_path}")
        self.manager.log(log_paths, f"Local DB: {local_db}")
        self.manager.log(log_paths, f"Nome da Playlist Local: {local_playlist_name}")

        try:
            # 1. Obter tracks da playlist do dispositivo
            device_playlists_raw = get_all_playlists_hierarchical(device_db)
            device_playlist_id = next((pl_id for pl_path, pl_id in device_playlists_raw if pl_path == device_playlist_path), None)

            if not device_playlist_id:
                raise ValueError(f"Playlist '{device_playlist_path}' não encontrada no DB do dispositivo.")

            device_tracks = get_tracks_from_playlist(device_db, device_playlist_path)
            if not device_tracks:
                raise ValueError(f"Nenhuma faixa encontrada na playlist '{device_playlist_path}' do dispositivo.")

            self.manager.log(log_paths, f"Encontradas {len(device_tracks)} faixas na playlist do dispositivo.")

            # 2. Conectar ao banco de dados local
            conn_local = sqlite3.connect(local_db)
            cursor_local = self.manager.criar_cursor_log(conn_local, log_paths)
            
            # 3. Criar/Atualizar playlist local
            cursor_local.execute("SELECT id FROM Playlist WHERE title = ? AND (parentListId = 0 OR parentListId IS NULL) ORDER BY isPersisted DESC LIMIT 1", (local_playlist_name,))
            local_pl_row = cursor_local.fetchone()
            
            local_playlist_id = None
            if local_pl_row:
                local_playlist_id = local_pl_row[0]
                self.manager.log(log_paths, f"Usando playlist local existente: '{local_playlist_name}' (ID: {local_playlist_id})")
                # Limpar entidades existentes se a playlist já existe
                cursor_local.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (local_playlist_id,))
            else:
                lastEditTime_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor_local.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, 0, 1, 0, ?, 1)", (local_playlist_name, lastEditTime_iso))
                local_playlist_id = cursor_local.lastrowid
                self.manager.log(log_paths, f"Criada nova playlist local: '{local_playlist_name}' (ID: {local_playlist_id})")

            # 4. Adicionar faixas à playlist local
            db_uuid_local = get_database_uuid(local_db)
            added_count = 0
            for i, device_track in enumerate(device_tracks):
                self.after(0, lambda p=(i+1)/len(device_tracks), t=device_track.get('title', '...'): self.status_var.set(f"Importando: {t}"))
                
                artist = device_track.get('artist')
                title = device_track.get('title')
                
                local_track_id = self.manager.find_track_id_by_name(cursor_local, artist, title)
                
                if local_track_id:
                    # Adicionar à playlist local
                    cursor_local.execute(
                        "INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, membershipReference) VALUES (?, ?, ?, 0, 0)",
                        (local_playlist_id, local_track_id, db_uuid_local)
                    )
                    added_count += 1
                    self.manager.log(log_paths, f"  [ADICIONADO] '{artist} - {title}' (ID Local: {local_track_id})")
                else:
                    self.manager.log(log_paths, f"  [IGNORADO] '{artist} - {title}' não encontrada no banco de dados local.")

            conn_local.commit()
            conn_local.close()

            self.manager.log(log_paths, f"--- IMPORTAÇÃO CONCLUÍDA ---")
            self.manager.log(log_paths, f"Total de faixas na playlist do dispositivo: {len(device_tracks)}")
            self.manager.log(log_paths, f"Total de faixas adicionadas à playlist local: {added_count}")
            
            self.after(0, lambda: self._finalize_import(True, added_count, log_paths))

        except Exception as e:
            self.manager.log(log_paths, f"--- ERRO DURANTE A IMPORTAÇÃO: {e} ---", tag="error")
            self.after(0, lambda: self._finalize_import(False, 0, log_paths, error_msg=str(e)))

    def _finalize_import(self, success, count, log_paths, error_msg=""):
        """Finaliza a UI após a importação."""
        self.btn_import.configure(state="normal")
        self.progress_bar.set(1.0)
        if success:
            self.status_var.set(f"Importação concluída! {count} faixas adicionadas.")
            messagebox.showinfo(self.txt["success_title"], f"Playlist '{self.selected_local_playlist_name.get()}' importada com sucesso! {count} faixas adicionadas.")
        else:
            self.status_var.set(f"Erro na importação: {error_msg}")
            messagebox.showerror(self.txt["error_title"], f"Erro durante a importação: {error_msg}")

        if self.manager.config.get("show_report", True):
            # O ReportWindow espera uma lista de tuplas (mensagem, tag)
            report_content_list = []
            if log_paths and log_paths[0]: # Se houver log_path, lê o conteúdo
                try:
                    with open(log_paths[0], "r", encoding="utf-8") as f:
                        for line in f:
                            # Tenta inferir a tag com base no conteúdo da linha
                            tag = "error" if "[ERRO]" in line or "[ERRO CRÍTICO]" in line else None
                            report_content_list.append([(line.strip(), tag)])
                except Exception as e:
                    report_content_list.append([("Erro ao ler arquivo de log: " + str(e), "error")])

            ReportWindow(
                self,
                title=self.txt["engine_tools_import_device_playlist_title"],
                header="RELATÓRIO DE IMPORTAÇÃO DE PLAYLIST",
                log_entries=report_content_list,
                playlist_name=self.selected_local_playlist_name.get(),
                txt=self.txt
            )