import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image
import customtkinter as ctk
# Importações do nosso backend e constantes
from constants import (
    VERSAO_ATUAL, 
    URL_DOACAO, 
    GITHUB_RELEASE_URL, 
    STRINGS,
    APP_NAME,
    IS_WIN, IS_MAC,
    FONT_FAMILY,
    COLOR_BG_DARK,
    COLOR_TEXT_NORMAL,
    COLOR_TEXT_MUTED,
    COLOR_SWITCH_OFF,
    CORNER_RADIUS_NONE
)
from database_utils import get_playlists_from_db, get_database_uuid
from engine_sync_app import (
    SyncManager, get_system_lang, get_resource_path, 
    _HOTCUE_DISPONIVEL
)
from report_gui import ReportWindow

# ================= INTERFACE GRÁFICA =================
ctk.set_appearance_mode("Dark")

class EngineSyncApp(ctk.CTkToplevel): # Alterado para CTkToplevel
    """
    Classe principal da interface gráfica para a ferramenta Engine DJ Sync.
    Gerencia a sincronização de pastas de música com o banco de dados do Engine DJ,
    incluindo backup, importação de hotcues e remoção de músicas órfãs.
    """
    def __init__(self, master, txt_strings): # Adicionados master e txt_strings
        """
        Inicializa a janela principal do aplicativo.
        """
        super().__init__(master) # Passa o master para o construtor da classe pai
        
        self.txt = txt_strings # Usa as strings passadas
        
        self.title(f"{self.txt['title']} ({VERSAO_ATUAL})") # Define o título da janela com a versão atual
        self.geometry("700x650")  # Altura aumentada para todos os elementos ficarem visíveis
        self.resizable(False, False)

        # Garante que a janela abra na frente e ganhe foco, e seja modal
        self.transient(master)
        self.grab_set()
        
        self.configure(fg_color=COLOR_BG_DARK)
        
        # Configuração do AppUserModelID para Windows (ícone na barra de tarefas)
        if os.name == 'nt':
            try:
                import ctypes
                myappid = 'syncdj.tools.hub.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        # Carrega e aplica o ícone da janela
        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if os.path.exists(self.caminho_icone):
            def aplicar_janela_icone():
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
            self.after(200, aplicar_janela_icone)
        
        # Inicializa o backend
        self.manager = SyncManager()

        # Busca automática de bancos de dados Engine
        self.found_databases = self.manager.localizar_bancos_dados()

        self.path_musicas = ctk.StringVar(value=self.manager.config.get("pasta_musicas", "")) # Mantém para estado interno
        self.path_db = ctk.StringVar(value="") # Volátil, selecionado automaticamente por disco

        self.fazer_backup = ctk.BooleanVar(value=self.manager.config.get("fazer_backup", True))
        self.importar_hotcue = ctk.BooleanVar(value=False)
        self.sobrescrever_hotcue = ctk.BooleanVar(value=False)
        self.remover_orfas = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value=self.txt["status_idle"])
        
        # Adiciona observadores para validar os campos e habilitar o botão de sync em tempo real
        self.path_musicas.trace_add("write", self.validar_campos)
        # Sempre que a pasta de músicas mudar, tentamos detectar o banco no mesmo disco
        self.path_musicas.trace_add("write", lambda *args: self.detectar_banco_por_drive())

        self.construir_ui()
        self.detectar_banco_por_drive() # Tenta localizar o banco e carregar playlists no início
        self.validar_campos() # Validação inicial

    def _check_for_updates_thread(self):
        versao_github = check_for_updates(VERSAO_ATUAL)
        if versao_github:
            self.after(1000, lambda: PopUpAtualizacao(self, self.txt, versao_github))

    def construir_ui(self):
        """
        Cria e organiza todos os elementos da interface gráfica da janela principal.
        """
        img_carregada = False
        try:
            img_caminho = get_resource_path(os.path.join("images", "logo_engine.png"))
            if os.path.exists(img_caminho):
                imagem_logo = Image.open(img_caminho)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_titulo = ctk.CTkLabel(self, text="", image=ctk_logo)
                img_carregada = True
        except Exception as e:
            pass
            
        if not img_carregada: # Fallback se a imagem não carregar
            lbl_titulo = ctk.CTkLabel(self, text=self.txt.get("engine_sync_title", "ENGINE DJ SYNC"), font=ctk.CTkFont(family=FONT_FAMILY, size=24, weight="bold"), text_color="#00E5A3")
            
        lbl_titulo.pack(pady=(25, 5))

        # Frame principal para agrupar os controles de configuração
        frame_config = ctk.CTkFrame(self, fg_color="transparent")
        frame_config.pack(padx=30, pady=(10, 8), fill="x")

        # Pasta de Músicas
        # Label e campo de entrada para o caminho da pasta de músicas
        lbl_pasta = ctk.CTkLabel(frame_config, text=self.txt["music_folder"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"))
        lbl_pasta.pack(padx=(25, 0), pady=(10, 2), anchor="w")
        
        # Frame para agrupar o campo de entrada e o botão de procurar pasta
        frame_pasta_browse = ctk.CTkFrame(frame_config, fg_color="transparent")
        frame_pasta_browse.pack(padx=25, pady=(0, 8), fill="x")

        # Campo de entrada para o caminho da pasta de músicas
        entry_pasta = ctk.CTkEntry(frame_pasta_browse, textvariable=self.path_musicas, width=400, corner_radius=CORNER_RADIUS_NONE, font=ctk.CTkFont(family=FONT_FAMILY))
        entry_pasta.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # Botão para abrir o diálogo de seleção de pasta
        btn_pasta = ctk.CTkButton(frame_pasta_browse, text=self.txt["browse"], width=100, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), corner_radius=CORNER_RADIUS_NONE, command=self.procurar_pasta)
        btn_pasta.pack(side="right", padx=(0, 0))

        # Label Informativo de Banco de Dados Detectado (Substitui a seleção manual)
        # Exibe o status da detecção automática do banco de dados
        self.lbl_db_auto = ctk.CTkLabel(frame_config, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_db_auto.pack(padx=(25, 0), pady=(2, 10), anchor="w")

        # Seleção de Playlist
        # Label para a seleção da playlist raiz
        lbl_playlist = ctk.CTkLabel(frame_config, text=self.txt["playlist"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"))
        lbl_playlist.pack(padx=(25, 0), pady=(0, 2), anchor="w")

        # ComboBox para selecionar a playlist raiz
        self.combo_playlist = ctk.CTkComboBox(frame_config, width=400, command=self.on_playlist_changed, corner_radius=0, font=ctk.CTkFont(family=FONT_FAMILY))
        self.combo_playlist.pack(padx=(25, 0), pady=(0, 10), anchor="w")

        # Switches de Configuração
        self.check_backup = ctk.CTkSwitch(frame_config, text=self.txt["backup"], variable=self.fazer_backup, font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), fg_color="#555555", progress_color="#00E5A3", command=self.salvar_config_ui)
        self.check_backup.pack(padx=(25, 0), pady=(0, 4), anchor="w")

        # Switch para importar hotcues (habilitado apenas se a funcionalidade estiver disponível)
        estado_hotcue = "normal" if _HOTCUE_DISPONIVEL else "disabled"
        self.check_hotcue = ctk.CTkSwitch(frame_config, text=self.txt["hotcue"], variable=self.importar_hotcue, font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), fg_color="#555555", progress_color="#00E5A3", state=estado_hotcue, command=self._toggle_hotcue)
        self.check_hotcue.pack(padx=(25, 0), pady=(0, 2), anchor="w")

        # Switch para sobrescrever hotcues existentes (depende do switch de importar hotcues)
        estado_overwrite = "normal" if (_HOTCUE_DISPONIVEL and self.importar_hotcue.get()) else "disabled"
        self.check_hotcue_overwrite = ctk.CTkSwitch(
            frame_config, text=self.txt["hotcue_overwrite"], variable=self.sobrescrever_hotcue,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12), fg_color="#555555", progress_color="#00E5A3",
            state=estado_overwrite, command=self.salvar_config_ui)
        self.check_hotcue_overwrite.pack(padx=(40, 0), pady=(0, 8), anchor="w")
        # Switch para remover músicas órfãs
        self.check_orfas = ctk.CTkSwitch(
            frame_config, text=self.txt["remover_orfas"], variable=self.remover_orfas,
            font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), fg_color="#555555", progress_color="#00E5A3",
            command=self.salvar_config_ui)
        self.check_orfas.pack(padx=(25, 0), pady=(0, 10), anchor="w")

        # Label para exibir o status atual da operação
        self.lbl_status = ctk.CTkLabel(self, textvariable=self.status_var, font=ctk.CTkFont(family=FONT_FAMILY, size=14))
        self.lbl_status.pack(pady=(8, 3), fill="x", padx=30)

        # Barra de progresso
        self.progress_bar = ctk.CTkProgressBar(self, width=620, height=12, progress_color="#00E5A3", corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(pady=4)
        self.progress_bar.set(0)

        # Botão para iniciar a sincronização
        self.btn_sync = ctk.CTkButton(self, text=self.txt["sync_btn"], font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"), 
                                      height=45, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", corner_radius=CORNER_RADIUS_NONE,
                                      state="disabled", command=self.iniciar_sincronizacao)
        self.btn_sync.pack(pady=(10, 6), fill="x", padx=60)

        # Botão para cancelar a sincronização
        self.btn_cancel = ctk.CTkButton(self, text=self.txt.get("cancel_btn", "Cancelar"), font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), 
                                        height=35, fg_color="#CC3333", text_color="#FFFFFF", hover_color="#AA2222", corner_radius=CORNER_RADIUS_NONE,
                                        state="disabled", command=self.cancelar_sincronizacao)
        self.btn_cancel.pack(pady=(0, 6), fill="x", padx=60)

        # self.btn_doacao = ctk.CTkButton(self, text=self.txt["donation_text"], font=ctk.CTkFont(size=12, underline=True),
        #                                 fg_color="transparent", text_color="#00E5A3", hover_color=None,
        #                                 hover=False, cursor="hand2", command=self.abrir_link_doacao)
        # self.btn_doacao.pack(pady=(4, 6))

        # Rodapé com informações do aplicativo
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))
    def detectar_banco_por_drive(self):
        """Localiza o m.db automaticamente no mesmo disco da pasta de músicas."""
        pasta = self.path_musicas.get()
        
        banco_alvo = None
        drive_musica = None

        def get_vol_id(path):
            """Helper para identificar o 'Drive' no Win ou 'Volume' no Mac."""
            abs_p = os.path.abspath(path)
            if IS_WIN:
                return os.path.splitdrive(abs_p)[0].upper()
            else:
                p = abs_p.split(os.sep)
                return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

        # Busca dinâmica em todos os discos conectados
        self.found_databases = self.manager.localizar_bancos_dados()

        # O banco de dados alvo deve obrigatoriamente estar no mesmo disco que a pasta de músicas
        if pasta and os.path.exists(pasta):
            drive_musica = get_vol_id(pasta)
            for b in self.found_databases:
                if get_vol_id(b) == drive_musica:
                    banco_alvo = b
                    break

        if banco_alvo and os.path.exists(banco_alvo):
            self.path_db.set(banco_alvo) # Define o caminho do banco
            
            # Informar os locais (discos) localizados destacando o alvo automático
            drives_encontrados = sorted(list({get_vol_id(d) for d in self.found_databases}))
            drive_alvo = get_vol_id(banco_alvo)
            
            texto_drives = " | ".join([f"[{d}]" if d == drive_alvo else d for d in drives_encontrados])
            self.lbl_db_auto.configure(text=f"✔ {self.txt['engine_dbs_detected'].format(count=len(self.found_databases))}: {texto_drives}", text_color=COLOR_TEXT_NORMAL)
        else: # Nenhum banco válido encontrado
            self.path_db.set("") # Limpa o caminho do banco

            if drive_musica:
                self.lbl_db_auto.configure(
                    text=self.txt.get("error_no_db_on_drive", "Erro: Banco de Dados não encontrado no disco {drive}").format(drive=drive_musica),
                    text_color="#FF5555"
                )
            else:
                drives_encontrados = sorted(list({get_vol_id(d) for d in self.found_databases}))
                texto_drives = " | ".join(drives_encontrados) if drives_encontrados else self.txt.get("not_found", "Não localizada")
                self.lbl_db_auto.configure(text=f"✖ {self.txt.get('db_file', 'Banco de Dados (m.db):')} {texto_drives}", text_color="#FF5555")
        
        self.carregar_playlists() # Always call carregar_playlists after attempting to set db_path

    def validar_campos(self, *args):
        """Habilita ou desabilita o botão de sincronização baseado no preenchimento dos caminhos."""
        pasta = self.path_musicas.get().strip()
        db = self.path_db.get().strip()
        if pasta and db:
            self.btn_sync.configure(state="normal")
        else:
            self.btn_sync.configure(state="disabled")

    def abrir_link_doacao(self):
        webbrowser.open(URL_DOACAO)

    def _toggle_hotcue(self):
        """Habilita ou desabilita o checkbox de sobrescrever conforme o estado do importar_hotcue."""
        if self.importar_hotcue.get() and _HOTCUE_DISPONIVEL:
            self.check_hotcue_overwrite.configure(state="normal")
        else:
            self.sobrescrever_hotcue.set(False)
            self.check_hotcue_overwrite.configure(state="disabled")
        self.salvar_config_ui()

    def _limpar_nome_playlist(self, nome):
        """
        Remove sufixos de criação de forma robusta, preservando o nome base original (incluindo prefixos como '-').
        """
        """Remove sufixos de criação de forma robusta, preservando o nome base original (incluindo prefixos como '-')."""
        if not nome: return ""
        res = nome

        for lang_data in STRINGS.values():
            s = lang_data.get("will_be_created_suffix")
            if s and res.endswith(s):
                res = res[:-len(s)]
                break

        return res.strip()

    def procurar_pasta(self):
        """
        Abre um diálogo para o usuário selecionar a pasta de músicas e atualiza a UI.
        """
        pasta = filedialog.askdirectory()
        if pasta:
            self.path_musicas.set(pasta)
            self.salvar_config_ui()
            # Recarrega as playlists após mudar a pasta, para atualizar o nome padrão
            self.carregar_playlists() 

    def procurar_db(self):
        """
        Abre um diálogo para o usuário selecionar o arquivo m.db e atualiza a UI.
        """
        arquivo = filedialog.askopenfilename(filetypes=[("Engine DB", "*.db")])
        if arquivo:
            arquivo_norm = os.path.normpath(arquivo)
            self.path_db.set(arquivo_norm)
            
            # Atualiza a lista do combo se for um novo local
            current_values = list(self.combo_db.cget("values"))
            if arquivo_norm not in current_values:
                current_values.insert(0, arquivo_norm)
                self.combo_db.configure(values=current_values)

            self.salvar_config_ui()
            # Recarrega as playlists após mudar o DB, para refletir as playlists existentes
            # no novo banco
            self.carregar_playlists()

    def carregar_playlists(self):
        """
        Carrega as playlists do banco de dados selecionado e popula o ComboBox de playlists.
        """
        db_path = self.path_db.get()
        pasta_atual = self.path_musicas.get()
        
        nome_padrao = None
        folder_name_from_path = None
        if pasta_atual and os.path.exists(pasta_atual):
            folder_name_from_path = os.path.basename(os.path.normpath(pasta_atual))

        # 1, 2 e 3: Localiza todos os bancos, abre e lista todas as playlists
        todas_playlists_nomes = set()
        for db in self.found_databases:
            if os.path.exists(db):
                todas_playlists_nomes.update(get_playlists_from_db(db))

        # 4: Suffix (Nova...) só aparece se não houver em NENHUM banco de dados detectado
        global_existing_map = {self._limpar_nome_playlist(pl).lower(): pl for pl in todas_playlists_nomes}
        
        # Para manter o casing do banco ALVO se a playlist já existir nele
        playlists_alvo = get_playlists_from_db(db_path) if db_path else []
        target_existing_map = {self._limpar_nome_playlist(pl).lower(): pl for pl in playlists_alvo}
        
        display_options = []
        will_be_created_suffix = self.txt["will_be_created_suffix"]
        my_collection_actual_name = self.txt["collection_name"] # "MY COLLECTION"
        my_collection_display_name = self.txt["collection_name_display"] # "- MY COLLECTION"

        # 1. Adiciona a opção "MY COLLECTION"
        base_mc_lower = self._limpar_nome_playlist(my_collection_actual_name).lower()
        if base_mc_lower in global_existing_map:
            # Se existe em algum disco, usa o nome limpo (do alvo se possível, para manter o casing)
            display_options.append(target_existing_map.get(base_mc_lower, global_existing_map[base_mc_lower]))
        else:
            display_options.append(my_collection_display_name + will_be_created_suffix)

        # 2. Adiciona o nome da pasta de músicas se não for a coleção
        if folder_name_from_path:
            clean_folder_lower = self._limpar_nome_playlist(folder_name_from_path).lower()
            if clean_folder_lower != base_mc_lower:
                if clean_folder_lower in global_existing_map:
                    display_options.append(target_existing_map.get(clean_folder_lower, global_existing_map[clean_folder_lower]))
                else:
                    display_options.append(folder_name_from_path + will_be_created_suffix)

        # 3. Adiciona todas as outras playlists existentes sem duplicatas
        added_bases_lower = {self._limpar_nome_playlist(opt).lower() for opt in display_options}
        for pl in sorted(list(todas_playlists_nomes)):
            base_pl_lower = self._limpar_nome_playlist(pl).lower()
            if base_pl_lower not in added_bases_lower:
                # Nunca terá sufixo aqui porque veio de 'todas_playlists_nomes'
                display_options.append(target_existing_map.get(base_pl_lower, pl))
                added_bases_lower.add(base_pl_lower)

        # Ordena alfabeticamente, mantendo "MY COLLECTION" no topo
        def custom_sort_key(item):
            if self._limpar_nome_playlist(item).lower() == base_mc_lower:
                return "0" + item # Garante que venha primeiro
            return "1" + item # Todos os outros vêm depois, ordenados alfabeticamente

        display_options.sort(key=custom_sort_key)

        if not display_options:
            self.combo_playlist.configure(values=[])
            self.combo_playlist.set("")
        else:
            self.combo_playlist.configure(values=display_options)
            
            # Lógica de seleção automática:
            # 1. Tenta selecionar a playlist que combina com o nome da pasta de música
            # 2. Fallback para My Collection se a pasta for inválida ou não encontrada
            
            target_to_select = None
            
            # Busca por pasta
            if folder_name_from_path:
                folder_clean = self._limpar_nome_playlist(folder_name_from_path).lower()
                for option in display_options:
                    if self._limpar_nome_playlist(option).lower() == folder_clean:
                        target_to_select = option
                        break
            
            # Se não encontrou pasta (ou campo vazio), busca My Collection
            if not target_to_select:
                mc_clean = self._limpar_nome_playlist(my_collection_actual_name).lower()
                for option in display_options:
                    if self._limpar_nome_playlist(option).lower() == mc_clean:
                        target_to_select = option
                        break

            # Define a seleção final (ou o primeiro item se nada for encontrado)
            if target_to_select:
                self.combo_playlist.set(target_to_select)
            else:
                self.combo_playlist.set(display_options[0])

    def on_playlist_changed(self, choice):
        """
        Acionado quando o usuário altera manualmente a playlist no ComboBox.
        """
        """Acionado quando o usuário altera manualmente a playlist no ComboBox."""
        cleaned_choice = self._limpar_nome_playlist(choice)

        pasta_path = self.path_musicas.get()
        if pasta_path:
            folder_name = os.path.basename(os.path.normpath(pasta_path))
            if cleaned_choice and folder_name and cleaned_choice.lower() != folder_name.lower():
                if not messagebox.askyesno(self.txt.get("confirm_playlist_title", "Aviso"), 
                                          self.txt["confirm_playlist_msg"].format(playlist=cleaned_choice, folder=folder_name)):
                    # Se o usuário cancelar, reverte para o nome da pasta (com ou sem sufixo)
                    db_playlists = get_playlists_from_db(self.path_db.get())
                    existing_playlists_map = {self._limpar_nome_playlist(pl).lower(): pl for pl in db_playlists}
                    
                    if folder_name.lower() in existing_playlists_map:
                        # Encontra o casing real do banco de dados para o nome da pasta
                        self.combo_playlist.set(existing_playlists_map[folder_name.lower()])
                    else:
                        self.combo_playlist.set(folder_name + self.txt["will_be_created_suffix"])
        self.salvar_config_ui()

    def salvar_config_ui(self):
        """
        Salva as configurações atuais da UI no objeto de configuração do manager e no arquivo.
        """
        # Limpa o nome da playlist antes de salvar (remove sufixo e traço)
        playlist_alvo = self._limpar_nome_playlist(self.combo_playlist.get())

        # Atualiza os valores da sessão no manager para o motor de sync
        # Isso permite que o motor use os valores atuais, mesmo que não sejam salvos no JSON
        self.manager.config.update({
            "importar_hotcue": self.importar_hotcue.get(),
            "sobrescrever_hotcue": self.sobrescrever_hotcue.get(),
            "remover_orfas": self.remover_orfas.get()
        })
        
        config_data = {
            "pasta_musicas": self.path_musicas.get(),
            "playlist_alvo": playlist_alvo,
            "fazer_backup": self.fazer_backup.get()
        }
        self.manager.save_config(config_data)
    
    def cancelar_sincronizacao(self):
        """
        Solicita o cancelamento da sincronização e exibe uma mensagem de confirmação.
        """
        if messagebox.askyesno(self.txt.get("cancel_title", "Confirmar"), 
                               self.txt.get("cancel_msg", "Deseja cancelar?")):
            self.manager.cancel_requested = True
            self.btn_cancel.configure(state="disabled")

    def iniciar_sincronizacao(self):
        """
        Inicia o processo de sincronização em uma thread separada.
        """
        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."
            )
            return

        pasta_path = self.path_musicas.get()
        db_path = self.path_db.get()

        if not pasta_path or not db_path:
            self.status_var.set(self.txt["error_paths"])
            return
        if not os.path.exists(db_path):
            self.status_var.set(self.txt["error_db"])
            return

        # Validação de drives (relpath falha no Windows entre discos diferentes)
        if os.name == 'nt' and os.path.splitdrive(os.path.abspath(pasta_path))[0].lower() != os.path.splitdrive(os.path.abspath(db_path))[0].lower():
            messagebox.showerror("Erro", self.txt["error_different_drives"])
            return

        self.btn_sync.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.status_var.set(self.txt["status_counting"])
        self.progress_bar.set(0)

        # Atualiza a configuração do manager com os valores da UI antes de iniciar
        self.salvar_config_ui()

        def callback_progresso(msg, progresso):
            self.after(0, lambda: [self.status_var.set(msg), self.progress_bar.set(progresso) if progresso is not None else None])

        def thread_sync():
            novas, apagadas, hotcues_manipulados, relatorio = self.manager.motor_sincronizacao(self.txt, callback_progresso, db_path)
            self.after(0, lambda: self.finalizar_sync(novas, apagadas, relatorio))

        threading.Thread(target=thread_sync, daemon=True).start()

    def finalizar_sync(self, novas_musicas, apagadas_musicas, relatorio):
        """
        Finaliza o processo de sincronização, atualiza a UI e exibe o relatório.
        """
        self.btn_sync.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

        # Recarrega a lista de playlists para refletir as alterações no banco de dados (ex: nova playlist criada)
        self.carregar_playlists()

        if novas_musicas is None:
            self.status_var.set(self.txt.get("status_cancelled", "Cancelado."))
            self.progress_bar.set(0)
            return

        self.status_var.set(self.txt["status_done"])
        self.progress_bar.set(1.0)
        
        # Abre o relatório detalhado em uma nova janela
        if self.manager.config.get("show_report", True):
            self._abrir_janela_relatorio(self.combo_playlist.get(), relatorio)

    def _abrir_janela_relatorio(self, playlist_name, content):
        """
        Abre uma nova janela para exibir o relatório detalhado da sincronização.
        """
        nome_limpo = self._limpar_nome_playlist(playlist_name)
        ReportWindow(
            self,
            title=f"Relatório Mirror Sync: {nome_limpo}",
            header="RELATÓRIO DE SINCRONIZAÇÃO",
            content=content,
            playlist_name=nome_limpo,
            txt=self.txt
        )