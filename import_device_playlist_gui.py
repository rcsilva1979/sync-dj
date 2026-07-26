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
    get_tracks_by_playlist_id, get_database_uuid, get_all_playlists_hierarchical
)
from report_gui import ReportWindow
from constants import (IS_WIN, APP_NAME, VERSAO_ATUAL, FONT_FAMILY,
                       COLOR_BG_DARK, COLOR_TEXT_MUTED, CORNER_RADIUS_NONE,
                       COLOR_ACCENT_BLUE, COLOR_TEXT_NORMAL, COLOR_ACCENT_GREEN,
                       STRINGS)

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
        self.local_dbs_by_drive = {}

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
        self._load_local_dbs()
        self._load_device_dbs()
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
        self.combo_device_playlist = ctk.CTkComboBox(frame_device_playlist, variable=self.selected_device_playlist, values=[], width=500, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY), command=self._on_device_playlist_selected)
        self.combo_device_playlist.pack(fill="x", expand=True)

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
        self.combo_local_playlist_name = ctk.CTkComboBox(frame_local_playlist_name, variable=self.selected_local_playlist_name, values=[], width=500, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY))
        self.combo_local_playlist_name.pack(fill="x", expand=True)
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

    def _limpar_nome_playlist(self, nome):
        """Remove sufixos de criação de forma robusta."""
        if not nome: return ""
        res = nome
        for lang_data in STRINGS.values():
            s = lang_data.get("will_be_created_suffix")
            if s and res.endswith(s):
                res = res[:-len(s)]
                break
        return res.strip()

    def _ensure_local_playlist_hierarchy(self, cursor, path_parts, log_paths):
        """
        Garante que a hierarquia de playlists local exista conforme `path_parts`.
        Retorna o `id` da playlist final (último elemento da hierarquia).
        Para cada nó existente, reativa `isPersisted` e `isExplicitlyExported`.
        """
        parent_id = 0
        last_id = None
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for part in path_parts:
            part = part.strip()
            if not part:
                continue
            # Procura elemento com mesmo título e parent_id
            cursor.execute(
                "SELECT id FROM Playlist WHERE title = ? AND parentListId = ? ORDER BY isPersisted DESC LIMIT 1",
                (part, parent_id)
            )
            row = cursor.fetchone()
            if row:
                node_id = row[0]
                self.manager.log(log_paths, f"Usando nó de playlist existente: '{part}' (ID: {node_id}) parent={parent_id}")
                cursor.execute(
                    "UPDATE Playlist SET isPersisted = 1, isExplicitlyExported = 1, lastEditTime = ? WHERE id = ?",
                    (now_iso, node_id)
                )
            else:
                # Tenta reaproveitar nó com mesmo título em outro parent, se houver apenas um candidato
                cursor.execute("SELECT id, parentListId FROM Playlist WHERE title = ?", (part,))
                duplicates = cursor.fetchall()
                if len(duplicates) == 1:
                    node_id, existing_parent = duplicates[0]
                    self.manager.log(log_paths, f"Reaproveitando nó de playlist existente com título '{part}' (ID: {node_id}) parent={existing_parent} -> {parent_id}")
                    cursor.execute(
                        "UPDATE Playlist SET parentListId = ?, isPersisted = 1, isExplicitlyExported = 1, lastEditTime = ? WHERE id = ?",
                        (parent_id, now_iso, node_id)
                    )
                else:
                    # Insere novo nó com parent_id
                    cursor.execute(
                        "INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) VALUES (?, ?, 1, 0, ?, 1)",
                        (part, parent_id, now_iso)
                    )
                    node_id = cursor.lastrowid
                    self.manager.log(log_paths, f"Criado nó de playlist local: '{part}' (ID: {node_id}) parent={parent_id}")
            parent_id = node_id
            last_id = node_id
        return last_id

    def _get_device_playlist_tree(self, db_path, root_playlist_id):
        """
        Retorna lista de tuplas (playlist_id, path_parts) para a árvore de playlists
        sob o playlist root selecionado no dispositivo.
        """
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        rows = cursor.execute("SELECT id, title, parentListId FROM Playlist").fetchall()
        conn.close()

        if not rows:
            return []

        playlists = {row["id"]: {"title": row["title"], "parent": row["parentListId"] or 0} for row in rows}
        children = defaultdict(list)
        for pid, data in playlists.items():
            children[data["parent"]].append(pid)

        if root_playlist_id not in playlists:
            return []

        def build_path(pid):
            path_parts = []
            current = pid
            while current and current in playlists:
                path_parts.append(playlists[current]["title"])
                current = playlists[current]["parent"]
            return list(reversed(path_parts))

        subtree = []
        def walk(pid):
            subtree.append((pid, build_path(pid)))
            for child_id in sorted(children.get(pid, []), key=lambda x: playlists[x]["title"]):
                walk(child_id)

        walk(root_playlist_id)
        return subtree

    def _activate_local_playlist_subtree(self, cursor, root_id, log_paths):
        """
        Ativa todos os nós de playlist na subárvore local do playlist root_id.
        """
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query = """
            UPDATE Playlist
            SET isPersisted = 1, isExplicitlyExported = 1, lastEditTime = ?
            WHERE id IN (
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM Playlist WHERE id = ?
                    UNION ALL
                    SELECT p.id FROM Playlist p INNER JOIN descendants d ON p.parentListId = d.id
                )
                SELECT id FROM descendants
            )
        """
        cursor.execute(query, (now_iso, root_id))
        self.manager.log(log_paths, f"Ativada subárvore local para playlist ID {root_id}: {cursor.rowcount} nós")

    def _update_local_playlists(self):
        """Atualiza a lista de playlists locais na combo box."""
        # 1. Obter todas as playlists de todos os bancos locais
        todas_playlists = set()
        for db_path in self.local_dbs_by_drive.values():
            if os.path.exists(db_path):
                todas_playlists.update(get_playlists_from_db(db_path))

        local_playlists_clean = {self._limpar_nome_playlist(pl).lower(): pl for pl in todas_playlists}

        # 2. Obter a playlist selecionada do dispositivo
        selected_device = self.selected_device_playlist.get()
        display_options = []
        target_to_select = None

        if selected_device:
            playlist_name = selected_device.split(" / ")[-1]
            playlist_name_clean = self._limpar_nome_playlist(playlist_name)
            
            # Se a playlist selecionada não existe nos bancos locais, adiciona com sufixo
            if playlist_name_clean.lower() not in local_playlists_clean:
                suffix = self.txt.get("will_be_created_suffix", " (Nova, será criada)")
                target_to_select = playlist_name_clean + suffix
                display_options.append(target_to_select)
            else:
                target_to_select = local_playlists_clean[playlist_name_clean.lower()]
                display_options.append(target_to_select)

        # 3. Adicionar todas as outras playlists locais
        added_lowers = {self._limpar_nome_playlist(opt).lower() for opt in display_options}
        for pl in sorted(list(todas_playlists)):
            pl_clean = self._limpar_nome_playlist(pl)
            if pl_clean.lower() not in added_lowers:
                display_options.append(pl_clean)
                added_lowers.add(pl_clean.lower())

        self.combo_local_playlist_name.configure(values=display_options)
        if target_to_select:
            self.selected_local_playlist_name.set(target_to_select)
        elif display_options:
            self.selected_local_playlist_name.set(display_options[0])
        else:
            self.selected_local_playlist_name.set("")

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

            self._update_local_playlists()
        else:
            self.lbl_all_local_dbs_status.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            self.combo_local_playlist_name.configure(values=[])
            # Não exibe messagebox aqui, apenas atualiza o status na UI

    def _on_device_playlist_selected(self, selected_value=None):
        """Callback quando uma playlist do dispositivo é selecionada."""
        self._update_local_playlists()

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

    def _find_best_local_db(self, device_tracks):
        """
        Encontra o banco de dados local (m.db) que contém a maior quantidade das músicas
        especificadas em device_tracks (comparando por artista e título).
        """
        local_dbs = self.manager.localizar_bancos_dados()
        if not local_dbs:
            return None, 0

        best_db = None
        max_matches = -1

        for db_path in local_dbs:
            if not os.path.exists(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                matches = 0
                for track in device_tracks:
                    artist = track.get('artist')
                    title = track.get('title')
                    if artist and title:
                        cursor.execute(
                            "SELECT id FROM Track WHERE LOWER(artist) = LOWER(?) AND LOWER(title) = LOWER(?) LIMIT 1",
                            (artist, title)
                        )
                        if cursor.fetchone():
                            matches += 1
                conn.close()
                if matches > max_matches:
                    max_matches = matches
                    best_db = db_path
            except Exception as e:
                print(f"Erro ao verificar matches no banco {db_path}: {e}")
                
        if best_db is None or max_matches == 0:
            return local_dbs[0], 0
            
        return best_db, max_matches

    def start_import_thread(self):
        device_db = self.device_db_path.get()
        device_playlist_path = self.selected_device_playlist.get()
        local_playlist_name = self.selected_local_playlist_name.get().strip()

        if not os.path.exists(device_db):
            messagebox.showerror(self.txt["error_title"], "Selecione um banco de dados do dispositivo válido.")
            return
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
        log_paths = None
        device_db = self.device_db_path.get()
        device_playlist_path = self.selected_device_playlist.get()
        local_playlist_name = self.selected_local_playlist_name.get().strip()

        # Limpar o sufixo "will_be_created_suffix"
        local_playlist_name = self._limpar_nome_playlist(local_playlist_name)

        # 1. Obter tracks da playlist do dispositivo
        try:
            device_playlists_raw = get_all_playlists_hierarchical(device_db)
            device_playlist_id = next((pl_id for pl_path, pl_id in device_playlists_raw if pl_path == device_playlist_path), None)

            if not device_playlist_id:
                raise ValueError(f"Playlist '{device_playlist_path}' não encontrada no DB do dispositivo.")

            device_tracks = get_tracks_by_playlist_id(device_db, device_playlist_id)
            if not device_tracks:
                raise ValueError(f"Nenhuma faixa encontrada na playlist '{device_playlist_path}' do dispositivo.")

            # Identificar o banco de dados do disco local que contém as músicas da playlist
            local_db, matches = self._find_best_local_db(device_tracks)
            if not local_db or not os.path.exists(local_db):
                raise ValueError("Nenhum banco de dados local válido foi encontrado.")

            self.local_db_path.set(local_db)

            log_paths = self.manager.iniciar_log(
                "N/A", local_db, local_playlist_name,
                self.manager.config.get("log", True),
                self.manager.config.get("debug", False),
                tool_name="IMPORT_DEVICE_PL"
            )

            self.manager.log(log_paths, f"Dispositivo DB: {device_db}")
            self.manager.log(log_paths, f"Playlist do Dispositivo: {device_playlist_path}")
            self.manager.log(log_paths, f"Local DB: {local_db} (Matches: {matches})")
            self.manager.log(log_paths, f"Nome da Playlist Local: {local_playlist_name}")

            self.manager.log(log_paths, f"Encontradas {len(device_tracks)} faixas na playlist do dispositivo.")

            # 2. Conectar ao banco de dados local
            conn_local = sqlite3.connect(local_db)
            cursor_local = self.manager.criar_cursor_log(conn_local, log_paths)
            
            # 3. Criar/Atualizar toda a subárvore de playlists local correspondente à seleção do dispositivo
            device_subtree = self._get_device_playlist_tree(device_db, device_playlist_id)
            if not device_subtree:
                raise ValueError(f"Não foi possível obter a árvore de playlists do dispositivo para '{device_playlist_path}'.")

            db_uuid_local = get_database_uuid(local_db)
            total_added_count = 0
            for subtree_playlist_id, path_parts in device_subtree:
                local_playlist_id = self._ensure_local_playlist_hierarchy(cursor_local, path_parts, log_paths)
                self.manager.log(log_paths, f"Playlist local sincronizada: {' / '.join(path_parts)} (ID: {local_playlist_id})")

                self._activate_local_playlist_subtree(cursor_local, local_playlist_id, log_paths)
                cursor_local.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (local_playlist_id,))

                device_tracks_for_playlist = get_tracks_by_playlist_id(device_db, subtree_playlist_id)
                if not device_tracks_for_playlist:
                    continue

                tail_entity_id = None
                added_track_ids = set()
                for i, device_track in enumerate(device_tracks_for_playlist):
                    self.after(0, lambda p=(i+1)/len(device_tracks_for_playlist), t=device_track.get('title', '...'): self.status_var.set(f"Importando: {t}"))

                    artist = device_track.get('artist')
                    title = device_track.get('title')
                    local_track_id = self.manager.find_track_id_by_name(cursor_local, artist, title)

                    if local_track_id:
                        if local_track_id in added_track_ids:
                            self.manager.log(log_paths, f"  [IGNORADO] '{artist} - {title}' (ID Local: {local_track_id}) já está na playlist.")
                            continue

                        cursor_local.execute(
                            "INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, membershipReference) VALUES (?, ?, ?, 0, 0)",
                            (local_playlist_id, local_track_id, db_uuid_local)
                        )
                        new_entity_id = cursor_local.lastrowid
                        if tail_entity_id is not None:
                            cursor_local.execute(
                                "UPDATE PlaylistEntity SET nextEntityId = ? WHERE id = ?",
                                (new_entity_id, tail_entity_id)
                            )
                        tail_entity_id = new_entity_id
                        added_track_ids.add(local_track_id)
                        total_added_count += 1
                        self.manager.log(log_paths, f"  [ADICIONADO] '{artist} - {title}' (ID Local: {local_track_id})")
                    else:
                        self.manager.log(log_paths, f"  [IGNORADO] '{artist} - {title}' não encontrada no banco de dados local.")

            added_count = total_added_count

            conn_local.commit()
            conn_local.close()

            self.manager.log(log_paths, f"--- IMPORTAÇÃO CONCLUÍDA ---")
            self.manager.log(log_paths, f"Total de faixas na playlist do dispositivo: {len(device_tracks)}")
            self.manager.log(log_paths, f"Total de faixas adicionadas à playlist local: {added_count}")
            
            self.after(0, lambda: self._finalize_import(True, added_count, log_paths))

        except Exception as e:
            error_text = str(e)
            if log_paths:
                self.manager.log(log_paths, f"--- ERRO DURANTE A IMPORTAÇÃO: {error_text} ---")
            self.after(0, lambda err=error_text: self._finalize_import(False, 0, log_paths, error_msg=err))

    def _finalize_import(self, success, count, log_paths, error_msg=""):
        """Finaliza a UI após a importação."""
        self.btn_import.configure(state="normal")
        self.progress_bar.set(1.0)
        if success:
            self.status_var.set(f"Importação concluída! {count} faixas adicionadas.")
            self._load_local_dbs()
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