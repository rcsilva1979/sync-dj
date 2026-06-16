import os
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import shutil
import threading
from collections import defaultdict
import unicodedata
from database_utils import (
    localizar_bancos_dados_engine, get_all_playlists_hierarchical, get_tracks_by_playlist_id, 
    update_track_path, get_track_id_by_path, update_playlist_entry_track
)
from engine_sync_app import get_resource_path, SyncManager
from report_gui import ReportWindow
from constants import (IS_WIN, IS_MAC, FONT_FAMILY, APP_NAME, 
                       VERSAO_ATUAL, COLOR_TEXT_MUTED, COLOR_BG_DARK)

class RelocateLostTracksWindow(ctk.CTkToplevel):
    """
    Janela da ferramenta para realocar faixas perdidas no banco de dados do Engine DJ.
    Permite ao usuário encontrar e corrigir caminhos de arquivos de música que foram movidos ou renomeados.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master
        """
        Inicializa a janela de realocação de faixas.
        """

        self.title(self.txt["relocate_title"])
        self.geometry("650x780")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        # Rodapé com informações do aplicativo.
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

        # Configuração de Ícone (Padrão multi-plataforma)
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

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Estado
        # Instância do SyncManager para gerenciar operações de backend e configurações.
        self.manager = SyncManager()
        # Variável para armazenar a playlist selecionada pelo usuário.
        self.selected_playlist = ctk.StringVar()
        # Mapeamento de caminhos de playlist para uma lista de tuplas (caminho_db, playlist_id).
        self.playlist_db_map = defaultdict(list)
        # Variável para armazenar o caminho da pasta onde o usuário deseja buscar os arquivos.
        self.search_folder = ctk.StringVar()
        # Variável para controlar o modo de realocação (copiar, relocar, fuzzy).
        self.relocate_mode = ctk.StringVar(value="relocate")
        # Variável para controlar a ação específica em modo fuzzy (renomear, copiar, mover).
        self.fuzzy_action = ctk.StringVar(value="") # Nenhuma ação fuzzy selecionada por padrão
        # Variável booleana para indicar se a operação deve ser apenas de verificação (dry run).
        self.just_verify = ctk.BooleanVar(value=False)
        # Lista de caminhos para todos os bancos de dados Engine DJ encontrados no sistema.
        self.found_databases = localizar_bancos_dados_engine()

        self.construir_ui()
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        self.relocate_mode.trace_add("write", lambda *args: self._handle_relocate_mode_change()) # Adiciona o trace para controlar as sub-opções
        self.carregar_playlists()

    def construir_ui(self):
        """
        Cria e organiza todos os elementos da interface gráfica da janela de realocação.
        """
        # Logo Superior
        img_carregada = False
        try:
            logo_path = get_resource_path(os.path.join("images", "logo_engine_relocate.png"))
            if os.path.exists(logo_path):
                logo_img = ctk.CTkImage(Image.open(logo_path), size=(500, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(15, 5))
                img_carregada = True
        except:
            pass

        # Título da tela (Sempre visível para identificação)
        titulo_texto = self.txt["relocate_title"].upper()
        font_size = 18 if img_carregada else 22
        pady_val = (5, 10) if img_carregada else (20, 10)
        
        lbl_title = ctk.CTkLabel(self, text=titulo_texto, font=ctk.CTkFont(family=FONT_FAMILY, size=font_size, weight="bold"), text_color="#F39C12")
        lbl_title.pack(pady=pady_val)

        # Label Informativo unificado seguindo o padrão do Mirror Sync
        # Exibe o status da detecção automática do banco de dados.
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_db_auto.pack(pady=(0, 5), padx=40)

        # Seleção de Playlist
        # Frame para agrupar os controles de seleção de playlist.
        frame_pl = ctk.CTkFrame(self, fg_color="transparent")
        frame_pl.pack(padx=40, pady=5, fill="x")
        
        # Label e ComboBox para selecionar a playlist.
        ctk.CTkLabel(frame_pl, text=self.txt["playlist"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        # O ComboBox é desabilitado inicialmente e populado após o carregamento das playlists.
        self.combo_playlist = ctk.CTkComboBox(frame_pl, variable=self.selected_playlist, values=[], width=450, state="disabled", font=ctk.CTkFont(family=FONT_FAMILY), dropdown_font=ctk.CTkFont(family=FONT_FAMILY))
        self.combo_playlist.pack(pady=2, fill="x")

        # Pasta de Busca
        frame_search = ctk.CTkFrame(self, fg_color="transparent")
        frame_search.pack(padx=40, pady=5, fill="x")
        
        # Label e campo de entrada para a pasta de busca.
        ctk.CTkLabel(frame_search, text=self.txt["search_folder_label"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        entry_search = ctk.CTkEntry(frame_search, textvariable=self.search_folder, width=350, font=ctk.CTkFont(family=FONT_FAMILY))
        entry_search.pack(side="left", pady=2, fill="x", expand=True, padx=(0, 10))
        
        # Botão para abrir o diálogo de seleção de pasta.
        btn_browse = ctk.CTkButton(frame_search, text=self.txt["browse"], width=100, fg_color="#F39C12", text_color="#000000", hover_color="#D68910", command=self.procurar_pasta_busca)
        btn_browse.pack(side="right", pady=2)
        # Botão para abrir o diálogo de seleção de pasta.

        # Opções de Modo (Alertar, Copiar, Relocar)
        frame_mode = ctk.CTkFrame(self, fg_color="transparent")
        frame_mode.pack(padx=40, pady=5, fill="x")
        
        ctk.CTkLabel(frame_mode, text=self.txt["relocate_mode_label"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w")
        
        # Switches para selecionar o modo de realocação (Comportamento de RadioButton).
        self.sw_copy = ctk.CTkSwitch(frame_mode, text=self.txt["relocate_mode_copy"], 
                                     command=lambda: self._set_mode("copy"), 
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=12), progress_color="#F39C12")
        self.sw_copy.pack(anchor="w", pady=2)
        
        self.sw_update = ctk.CTkSwitch(frame_mode, text=self.txt["relocate_mode_update"], 
                                       command=lambda: self._set_mode("relocate"), 
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=12), progress_color="#F39C12")
        self.sw_update.pack(anchor="w", pady=2)

        # Switch para ativar a busca inteligente (fuzzy search).
        self.sw_fuzzy = ctk.CTkSwitch(frame_mode, text=self.txt.get("fuzzy_search_label", "Busca inteligente (Arquivos renomeados)"), 
                                      command=lambda: self._set_mode("fuzzy"), 
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=12), progress_color="#F39C12")
        self.sw_fuzzy.pack(anchor="w", pady=2)

        # Sub-opções da Busca Inteligente
        # Frame para agrupar as sub-opções do modo fuzzy.
        self.frame_fuzzy_ops = ctk.CTkFrame(frame_mode, fg_color="transparent")
        self.frame_fuzzy_ops.pack(anchor="w", fill="x")
        
        # Switches para as ações específicas do modo fuzzy.
        self.sw_f_rename = ctk.CTkSwitch(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_rename", "Renomear arquivo (Se na mesma pasta)"), 
                                         command=lambda: self._set_fuzzy_action("rename"), 
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=10), progress_color="#F39C12")
        self.sw_f_rename.pack(anchor="w", padx=35, pady=1)

        self.sw_f_copy = ctk.CTkSwitch(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_copy", "Copiar arquivo para o local antigo"), 
                                       command=lambda: self._set_fuzzy_action("copy"), 
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=10), progress_color="#F39C12")
        self.sw_f_copy.pack(anchor="w", padx=35, pady=1)

        self.sw_f_move = ctk.CTkSwitch(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_move", "Mover arquivo para o local antigo"), 
                                       command=lambda: self._set_fuzzy_action("move"), 
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=10), progress_color="#F39C12")
        self.sw_f_move.pack(anchor="w", padx=35, pady=1)

        # Checkbox: Apenas Verificar
        # Permite ao usuário realizar uma simulação da operação sem fazer alterações reais.
        self.check_verify = ctk.CTkCheckBox(
            frame_mode, 
            text=self.txt.get("relocate_just_verify_label", "Apenas Verificar (Sem alteração)"),
            variable=self.just_verify,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color="#F39C12", hover_color="#D68910"
        )
        self.check_verify.pack(anchor="w", pady=(5, 5))

        # Botão para listar as músicas faltantes na playlist selecionada.
        # Botão: Listar Músicas Faltantes
        self.btn_view_missing = ctk.CTkButton( # type: ignore
            self,
            text=self.txt["view_tracks_btn"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            fg_color="#555555", text_color="#FFFFFF", hover_color="#777777",
            height=40, width=350,
            command=self.listar_musicas_faltantes
        )
        self.btn_view_missing.pack(pady=(5, 0))

        # Botão principal para iniciar a realocação.
        # Ação
        self.btn_action = ctk.CTkButton(
            self, # type: ignore
            text=self.txt["relocate_btn_action"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            fg_color="#F39C12", text_color="#000000", hover_color="#D68910",
            height=40, width=350,
            command=self.iniciar_relocacao
        )
        self.btn_action.pack(pady=15)

        # Barra de progresso para indicar o andamento da operação.
        # Progresso e Status
        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#F39C12")
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        # Label para exibir mensagens de status ao usuário.
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color="#AAAAAA")
        self.lbl_status.pack(pady=5)

        # Sincroniza estado inicial dos switches
        self._set_mode(self.relocate_mode.get())
        self._set_fuzzy_action(self.fuzzy_action.get())

    def _handle_relocate_mode_change(self, *args):
        """
        Define a ação padrão da busca inteligente quando o modo é selecionado/desselecionado.
        Quando o modo "fuzzy" é ativado, a ação "rename" é selecionada por padrão.
        Quando outro modo é selecionado, as sub-opções do modo fuzzy são limpas.
        """
        """Define a ação padrão da busca inteligente quando o modo é selecionado/desselecionado."""
        mode = self.relocate_mode.get()
        if mode == "fuzzy":
            if not self.fuzzy_action.get():
                self._set_fuzzy_action("rename") # Seleciona "Renomear" por padrão quando "Busca Inteligente" é escolhido
        else:
            self._set_fuzzy_action("") # Limpa a seleção das sub-opções quando outro modo é escolhido

    def _set_mode(self, mode):
        """Define o modo de realocação e atualiza visualmente os switches."""
        self.relocate_mode.set(mode)
        # Desseleciona todos e seleciona o alvo para simular comportamento de RadioButton
        self.sw_copy.deselect()
        self.sw_update.deselect()
        self.sw_fuzzy.deselect()
        if mode == "copy": self.sw_copy.select()
        elif mode == "relocate": self.sw_update.select()
        elif mode == "fuzzy": self.sw_fuzzy.select()

    def _set_fuzzy_action(self, action):
        """Define a ação fuzzy e atualiza visualmente os switches."""
        self.fuzzy_action.set(action)
        # Desseleciona todos e seleciona o alvo para simular comportamento de RadioButton
        self.sw_f_rename.deselect()
        self.sw_f_copy.deselect()
        self.sw_f_move.deselect()
        if action == "rename": self.sw_f_rename.select()
        elif action == "copy": self.sw_f_copy.select()
        elif action == "move": self.sw_f_move.select()

    def procurar_pasta_busca(self):
        """
        Abre um diálogo para o usuário selecionar a pasta onde os arquivos de música serão buscados.
        Atualiza a variável `self.search_folder` com o caminho selecionado.
        """
        pasta = filedialog.askdirectory()
        if pasta:
            self.search_folder.set(os.path.normpath(pasta))
            """Abre um diálogo para o usuário selecionar a pasta onde os arquivos de música serão buscados."""


    def carregar_playlists(self):
        if not self.found_databases:
            self.lbl_status.configure(text=self.txt.get("error_db", "Database error"), text_color="#FF5555")
            return

        self.playlist_db_map = defaultdict(list)
        for path in self.found_databases:
            if not os.path.exists(path): continue
            results = get_all_playlists_hierarchical(path)
            for pl_path, pl_id in results:
                self.playlist_db_map[pl_path].append((path, pl_id))

        all_playlists = sorted(list(self.playlist_db_map.keys()))
        if all_playlists:
            self.combo_playlist.configure(values=all_playlists, state="normal")
            self.selected_playlist.set(all_playlists[0])
            self.combo_playlist.set(all_playlists[0])
            self.atualizar_label_drives()
        else:
            self.combo_playlist.configure(values=[], state="disabled")
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")

    def _get_vol_id(self, path):
        """
        Helper para identificar o 'Drive' no Windows ou 'Volume' no macOS a partir de um caminho.
        """
        """Helper para identificar o 'Drive' no Win ou 'Volume' no Mac."""
        if not path: return ""
        abs_p = os.path.abspath(path)
        if IS_WIN:
            return os.path.splitdrive(abs_p)[0].upper()
        else:
            p = abs_p.split(os.sep)
            return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

    def atualizar_label_drives(self):
        """
        Atualiza o label que exibe os drives detectados, destacando aqueles que contêm a playlist selecionada.
        """
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {self._get_vol_id(db) for db in dbs_com_playlist}
        drives_totais = sorted(list({self._get_vol_id(d) for d in self.found_databases}))
        
        texto_drives = " | ".join([
            f"[{d}]" if d in drives_com_playlist else d 
            for d in drives_totais
        ])
        status_text = f"✔ {self.txt.get('engine_dbs_detected', 'Bancos detectados').format(count=len(self.found_databases))}: {texto_drives}"
        self.lbl_db_auto.configure(text=status_text, text_color="#00E5A3")

    def listar_musicas_faltantes(self):
        """
        Abre uma nova janela para exibir uma lista detalhada das músicas faltantes na playlist selecionada.
        """
        pl_nome = self.selected_playlist.get()
        if not pl_nome: return

        db_pl_pairs = self.playlist_db_map.get(pl_nome)
        if not db_pl_pairs: return

        content_lines = []
        total_missing_global = 0
        for db_path, pl_id in db_pl_pairs:
            drive = self._get_vol_id(db_path)
            content_lines.append(f"--- DRIVE {drive} ---\n")
            tracks = get_tracks_by_playlist_id(db_path, pl_id)
            missing = [t for t in tracks if not os.path.exists(t.get("caminho_absoluto", ""))]
            
            if not missing:
                content_lines.append("Todas as músicas localizadas neste drive.\n\n")
                continue
            
            total_missing_global += len(missing)
            for t in missing:
                artist = t.get('artist') or "Unknown"
                title = t.get('title') or "Untitled"
                content_lines.append(f"FAIXA: {artist} - {title}\n")
                content_lines.append(f"  Path: {t.get('caminho_absoluto')}\n\n")
            
        if total_missing_global == 0:
            content_lines.append("Nenhuma música faltante encontrada em nenhum drive.")

        ReportWindow(
            self,
            title=f"Músicas Faltantes: {pl_nome}",
            header="Músicas Faltantes",
            content="".join(content_lines),
            playlist_name=pl_nome,
            txt=self.txt
        )

    def iniciar_relocacao(self):
        """
        Inicia o processo de realocação de faixas em uma thread separada.
        """
        # Verifica se o Engine DJ está aberto (mesma lógica e mensagens do Mirror Sync)
        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."
            )
            return

        pl_nome = self.selected_playlist.get()
        busca_dir = self.search_folder.get()

        if not busca_dir or not pl_nome:
            messagebox.showwarning("Aviso", self.txt["error_paths"])
            return

        db_pl_pairs = self.playlist_db_map.get(pl_nome)
        if not db_pl_pairs: return

        def normalizar_nome(texto):
            """Normaliza caracteres acentuados e uniformiza espaços para busca robusta."""
            if not texto: return ""
            # Remove acentos, converte para minúsculas e remove a extensão para comparação parcial
            texto_norm = unicodedata.normalize('NFD', str(texto).lower())
            texto_norm = "".join([c for c in texto_norm if not unicodedata.combining(c)])
            # Remove espaços extras (múltiplos espaços viram um só) e strip
            texto_norm = " ".join(texto_norm.split())
            return os.path.splitext(texto_norm)[0]

        current_mode = self.relocate_mode.get()
        dry_run = self.just_verify.get()
        fuzzy_act_val = self.fuzzy_action.get()

        # Define o rótulo da ação principal baseado no modo selecionado para o relatório
        main_action_label = self.txt.get("relocate_mode_copy", "Restaurar") if current_mode == "copy" else \
                           (self.txt.get("fuzzy_search_label", "Busca Inteligente") if current_mode == "fuzzy" else \
                            self.txt.get("relocate_mode_update", "Atualizar Banco"))
        self.btn_action.configure(state="disabled")
        self.btn_view_missing.configure(state="disabled")
        self.combo_playlist.configure(state="disabled")
        
        # Inicializa caminhos de log
        log_paths = self.manager.iniciar_log(
            busca_dir, "Multi-DB Relocate", pl_nome, 
            self.manager.config.get("log", True), self.manager.config.get("debug", False), 
            tool_name="RELOCATE")

        def task():
            total_tracks_all = 0
            total_missing_all = 0
            total_relocated_all = 0
            skipped_duplicate = 0
            skipped_different_drive = 0
            report_lines = []

            self.manager.log(log_paths, f"--- INÍCIO DA RELOCAÇÃO [{pl_nome}] ---")
            self.manager.log(log_paths, f"Pasta de busca: {busca_dir}")
            self.manager.log(log_paths, f"Modo selecionado: {current_mode}")
            if dry_run: self.manager.log(log_paths, "!!! MODO VERIFICAÇÃO ATIVO - NENHUMA ALTERAÇÃO SERÁ FEITA !!!")

            # 1. Indexar a pasta de busca
            self.manager.log(log_paths, f"Iniciando mapeamento recursivo em: {busca_dir}")
            self.after(0, lambda: [self.lbl_status.configure(text=self.txt["status_searching_files"]), self.progress_bar.set(0)])
            
            file_index = defaultdict(list)
            size_index = defaultdict(list)
            
            for raiz, diretorios, arquivos in os.walk(busca_dir):
                # Pula pastas ocultas (ex: .trash) e de sistema para melhor performance
                diretorios[:] = [d for d in diretorios if not d.startswith('.') and not d.startswith('$')]
                for f in arquivos:
                    if f.startswith('.'): continue # Pula arquivos ocultos do Mac
                    
                    f_path = os.path.join(raiz, f)
                    key = normalizar_nome(f)
                    if key:
                        file_index[key].append(f_path)
                        try:
                            f_size = os.path.getsize(f_path)
                            size_index[f_size].append(f_path)
                        except: pass

            total_indexado = sum(len(v) for v in file_index.values())
            self.manager.log(log_paths, f"[INDEX] {total_indexado} arquivo(s) mapeados (Nomes e Tamanhos).")
            
            if total_indexado == 0:
                self.manager.log(log_paths, "[AVISO] Nenhum arquivo foi encontrado na pasta selecionada. Verifique as permissões de acesso.")

            # 2. Processar cada banco
            for db_path, pl_id in db_pl_pairs:
                drive = self._get_vol_id(db_path)
                report_lines.append(f"\n[BANCO DRIVE {drive}] {db_path}\n" + "="*50 + "\n")
                
                self.after(0, lambda d=drive: self.lbl_status.configure(text=f"[{d}] " + self.txt["status_scanning_missing"]))
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                missing_tracks = [t for t in tracks if not os.path.exists(t.get("caminho_absoluto", ""))]
                
                self.manager.log(log_paths, f"\n[BANCO] Processando: {db_path}")
                self.manager.log(log_paths, f"[INFO] {len(missing_tracks)} faixas marcadas como 'missing' na playlist.")

                total_tracks_all += len(tracks)
                total_missing_all += len(missing_tracks)

                if not missing_tracks and not self.manager.config.get("debug", False): # Não loga se não há missing e não está em debug
                    continue

                engine_library_parent = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))

                for i, track in enumerate(missing_tracks):
                    fname = track.get("filename")
                    if not fname: continue
                    artist_title = f"{track.get('artist', 'Desconhecido')} - {track.get('title', 'Sem Título')}"
                    track_id = track.get("id")
                    entry_id = track.get("entry_id")
                    track_size = track.get("fileBytes")
                    caminho_esperado = track.get("caminho_absoluto")
                    
                    self.manager.log(log_paths, f"  [BUSCANDO] {fname} (ID: {track_id})", nivel="debug")
                    
                    progress = (i + 1) / len(missing_tracks)
                    self.after(0, lambda p=progress, f=fname, d=drive: [
                        self.progress_bar.set(p),
                        self.lbl_status.configure(text=f"[{d}] " + self.txt["status_relocating"].format(filename=f))
                    ])

                    found_paths = []
                    match_type = "Exato"
                    search_key = normalizar_nome(fname) # Nome do arquivo que está no banco (sem extensão)
                    
                    # 1. Tentativa por nome exato (mais rápido)
                    if search_key in file_index:
                        found_paths = file_index[search_key]
                    
                    # 2. Busca Inteligente (Tamanho + Nome Parcial) 
                    # Agora a busca inteligente funciona em qualquer modo se o nome exato falhar, 
                    # mas o rótulo da ação respeita a UI
                    if not found_paths and track_size and track_size in size_index:
                        for cand_path in size_index[track_size]:
                            cand_name = normalizar_nome(os.path.basename(cand_path))
                            # Se o tamanho bate e o nome original está contido no novo (ou vice-versa)
                            if search_key in cand_name or cand_name in search_key:
                                found_paths.append(cand_path)
                                match_type = "Fuzzy"

                    if found_paths:
                        report_item = [f"MÚSICA: {fname}"]
                        self.manager.log(log_paths, f"  [BUSCA] '{artist_title}' (ID: {track_id})", nivel="debug")
                        self.manager.log(log_paths, f"  [FOLDER MATCH] Arquivo localizado na pasta de busca ({len(found_paths)} ocorrência(s)).")

                        # Tenta encontrar no mesmo drive/volume (Obrigatório para Engine DJ)
                        found_somewhere = True
                        novo_caminho_abs = None
                        
                        # Prioridade 1: Arquivo na MESMA PASTA (Crucial para a estratégia de Renomeação)
                        target_dir_abs = os.path.normpath(os.path.dirname(os.path.abspath(caminho_esperado))).lower()
                        for path_found in found_paths:
                            if os.path.normpath(os.path.dirname(os.path.abspath(path_found))).lower() == target_dir_abs:
                                novo_caminho_abs = path_found
                                break
                        
                        # Prioridade 2: Primeiro arquivo encontrado no mesmo Drive/Volume
                        if not novo_caminho_abs:
                            db_vol = self._get_vol_id(db_path)
                            for path_found in found_paths:
                                if self._get_vol_id(path_found) == db_vol:
                                    novo_caminho_abs = path_found
                                    break
                        
                        # Se a ação for restaurar/mover para o local antigo, permite buscar o arquivo em outro disco
                        permitir_outro_disco = current_mode == "copy" or (current_mode == "fuzzy" and fuzzy_act_val in ["copy", "move"])
                        if not novo_caminho_abs and found_somewhere and permitir_outro_disco:
                            novo_caminho_abs = found_paths[0]

                        if novo_caminho_abs:
                            try:
                                nome_no_disco = os.path.basename(novo_caminho_abs)
                                if match_type == "Fuzzy":
                                    report_item.append(f"  Status: ENCONTRADO COM NOME DIFERENTE")
                                    report_item.append(f"  ↳ Nome no Banco: {fname}")
                                    report_item.append(f"  ↳ Nome no Disco: {nome_no_disco}")
                                else:
                                    report_item.append(f"  Status: Localizado em {novo_caminho_abs}")
                                
                                if current_mode == "fuzzy":
                                    if fuzzy_act_val == "copy":
                                        report_item.append(f"  Ação: Copiar arquivo para o local antigo")
                                        report_item.append(f"  Origem:  {novo_caminho_abs}")
                                        report_item.append(f"  Alvo:    {caminho_esperado}")
                                        if not dry_run:
                                            try:
                                                os.makedirs(os.path.dirname(caminho_esperado), exist_ok=True)
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.copy2(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [COPIADO] '{artist_title}' para local original: {caminho_esperado}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                            except Exception as e:
                                                self.manager.log(log_paths, f"  [ERRO] Falha ao copiar: {e}")

                                    elif fuzzy_act_val == "move":
                                        same_dir = os.path.dirname(os.path.abspath(novo_caminho_abs)) == os.path.dirname(os.path.abspath(caminho_esperado))
                                        if not same_dir: # Só move se for uma pasta diferente
                                            report_item.append(f"  Ação: Mover para local original")
                                            report_item.append(f"  Origem:  {novo_caminho_abs}")
                                            report_item.append(f"  Alvo:    {caminho_esperado}")
                                            if not dry_run:
                                                os.makedirs(os.path.dirname(caminho_esperado), exist_ok=True)
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.move(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [MOVIDO] '{artist_title}' para local original: {caminho_esperado}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                        else:
                                            report_item.append(f"  Aviso: Mover ignorado (Já na mesma pasta).")
                                            report_item.append(f"  Pasta Atual: {os.path.dirname(novo_caminho_abs)}")
                                            report_item.append(f"  Pasta Alvo:  {os.path.dirname(caminho_esperado)}")
                                            
                                    elif fuzzy_act_val == "rename":
                                        same_dir = os.path.dirname(os.path.abspath(novo_caminho_abs)) == os.path.dirname(os.path.abspath(caminho_esperado))
                                        if same_dir:
                                            report_item.append(f"  Ação: Renomear arquivo (Mesma pasta)")
                                            report_item.append(f"  De:   {nome_no_disco}")
                                            report_item.append(f"  Para: {fname}")
                                            if not dry_run:
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.move(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [RENOMEADO] '{nome_no_disco}' para '{fname}' em {os.path.dirname(caminho_esperado)}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                        else:
                                            report_item.append(f"  Aviso: Renomear ignorado (Pastas diferentes).")
                                            report_item.append(f"  Pasta Atual: {os.path.dirname(novo_caminho_abs)}")
                                            report_item.append(f"  Pasta Alvo:  {os.path.dirname(caminho_esperado)}")

                                elif current_mode == "relocate":
                                    novo_rel_path = self.manager.formatar_caminho_engine(novo_caminho_abs, db_path)
                                    report_item.append(f"  Ação: Relocar (Atualizar Banco)")
                                    report_item.append(f"  Caminho Antigo: {caminho_esperado}")
                                    report_item.append(f"  Caminho Novo:   {novo_rel_path}")
                                    
                                    existing_id = get_track_id_by_path(db_path, novo_rel_path)
                                    if existing_id and existing_id != track_id:
                                        if dry_run: report_item.append("  Nota: Será vinculada à ID duplicada existente no banco.")
                                        self.manager.log(log_paths, f"  [DUPLICATA] '{artist_title}' já existe no banco (ID {existing_id}).")
                                        if not dry_run and entry_id and update_playlist_entry_track(db_path, entry_id, existing_id):
                                            total_relocated_all += 1
                                    else:
                                        self.manager.log(log_paths, f"  [RELOCADO] '{artist_title}' (ID: {track_id}) -> {novo_rel_path}")
                                        if not dry_run and update_track_path(db_path, track_id, novo_rel_path):
                                            total_relocated_all += 1

                                elif current_mode == "copy":
                                    dest_abs = track.get("caminho_absoluto")
                                    report_item.append(f"  Ação: Restaurar Arquivo (Copiar)")
                                    report_item.append(f"  Origem:  {novo_caminho_abs}")
                                    report_item.append(f"  Destino: {dest_abs}")
                                    if dest_abs:
                                        self.manager.log(log_paths, f"  [COPIADO] '{artist_title}' de '{novo_caminho_abs}' para '{dest_abs}'")
                                        if not dry_run:
                                            dest_dir = os.path.dirname(dest_abs)
                                            if not os.path.exists(dest_dir):
                                                os.makedirs(dest_dir, exist_ok=True)
                                            shutil.copy2(novo_caminho_abs, dest_abs)
                                            total_relocated_all += 1
                                
                                if dry_run: total_relocated_all += 1
                            except Exception as e:
                                self.manager.log(log_paths, f"  [ERRO TÉCNICO] Track {track_id}: {str(e)}", nivel="debug")
                                report_item.append(f"  [ERRO] Falha ao executar ação: {str(e)}")
                        elif found_somewhere:
                            report_item.append(f"  Status: Encontrado em outro disco ({found_paths[0]})")
                            report_item.append(f"  Caminho esperado: {caminho_esperado}")
                            self.manager.log(log_paths, f"  [AVISO] '{fname}' ignorado: está em disco diferente do banco e a ação selecionada não permite restauração entre discos.")
                            skipped_different_drive += 1

                        # Garante que o item seja adicionado ao relatório, independentemente de ter sido processado ou ignorado
                        report_lines.append("\n".join(report_item) + "\n" + "-"*40 + "\n")
                    else:
                        self.manager.log(log_paths, f"  [NÃO ENCONTRADO] '{fname}' não localizado na pasta de busca.", nivel="debug")
                        report_lines.append(f"MÚSICA: {fname}\n  Status: NÃO ENCONTRADO na pasta de busca\n  Caminho esperado: {caminho_esperado}\n" + "-"*40 + "\n")

            self.manager.log(log_paths, f"\n--- FIM DO PROCESSO ---\nRelocados: {total_relocated_all}\nNão encontrados: {total_missing_all - total_relocated_all}")
            
            final_report = "".join(report_lines)
            self.after(0, lambda: self.finalizar_processo(total_tracks_all, total_missing_all, total_relocated_all, skipped_duplicate, skipped_different_drive, log_paths, final_report, dry_run))

        threading.Thread(target=task, daemon=True).start()

    def finalizar_processo(self, total, missing, relocated, duplicates=0, diff_drive=0, log_paths=None, report="", is_dry_run=False):
        """
        Finaliza o processo de realocação, atualiza a UI e exibe um resumo ou relatório detalhado.
        """
        self.btn_action.configure(state="normal")
        self.btn_view_missing.configure(state="normal")
        self.combo_playlist.configure(state="normal")
        self.progress_bar.set(1.0)
        self.lbl_status.configure(text=self.txt["status_done"])

        if missing == 0:
            messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("error_no_missing_found", "Todas as músicas desta playlist foram localizadas no disco!"))
            return
        
        # Abre o relatório detalhado automaticamente ao final
        if self.manager.config.get("show_report", True):
            self._abrir_janela_relatorio(self.selected_playlist.get(), report, is_dry_run)
        
    def _abrir_janela_relatorio(self, playlist_name, content, is_dry_run=False):
        """
        Abre uma nova janela para exibir o relatório detalhado da operação de realocação.
        """
        title_prefix = "RELATÓRIO DE VERIFICAÇÃO" if is_dry_run else "RELATÓRIO DE EXECUÇÃO"
        ReportWindow(
            self,
            title=f"{title_prefix}: {playlist_name}",
            header=title_prefix,
            content=content,
            playlist_name=playlist_name,
            txt=self.txt
        )