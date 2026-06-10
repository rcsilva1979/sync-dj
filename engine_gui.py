import os
import sys
import threading
import webbrowser
import tkinter as tk
import re
from tkinter import filedialog, messagebox
from PIL import Image
import customtkinter as ctk

# Importações do nosso backend e constantes
from constants import VERSAO_ATUAL, URL_DOACAO, GITHUB_RELEASE_URL, STRINGS
from database_utils import get_playlists_from_db, get_database_uuid
from engine_sync_app import (
    SyncManager, get_system_lang, get_resource_path, 
    check_for_updates, _HOTCUE_DISPONIVEL
)

# ================= POP-UP DE ATUALIZAÇÃO =================
class PopUpAtualizacao(ctk.CTkToplevel):
    def __init__(self, master, txt, versao_nova):
        super().__init__(master)
        
        self.title(txt["update_title"])
        self.geometry("400x250")
        self.resizable(False, False)
        self.configure(fg_color="#242424")

        # Toca o som de notificação nativo do sistema (Aviso de Atualização)
        if sys.platform.startswith('win'):
            try:
                import winsound
                # Usa MB_ICONEXCLAMATION para soar como um alerta/aviso
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except:
                self.bell()
        else:
            self.bell()
        
        if sys.platform.startswith('win') and hasattr(master, 'caminho_icone') and os.path.exists(master.caminho_icone):
            def aplicar_icone():
                try:
                    self.iconbitmap(master.caminho_icone)
                    self.wm_iconbitmap(master.caminho_icone)
                except Exception:
                    pass
            self.after(250, aplicar_icone)
        
        self.transient(master)
        self.grab_set()

        lbl_header = ctk.CTkLabel(self, text=txt["update_title"], font=ctk.CTkFont(size=20, weight="bold"), text_color="#00E5A3")
        lbl_header.pack(pady=(20, 10))

        lbl_msg = ctk.CTkLabel(self, text=txt["update_msg"].format(VERSAO_ATUAL, versao_nova), font=ctk.CTkFont(size=14))
        lbl_msg.pack(pady=(5, 20))

        frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        frame_botoes.pack(pady=10)

        btn_baixar = ctk.CTkButton(frame_botoes, text=txt["btn_yes"], font=ctk.CTkFont(weight="bold"), fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", command=self.baixar_atualizacao)
        btn_baixar.pack(side="left", padx=10)

        btn_fechar = ctk.CTkButton(frame_botoes, text=txt["btn_no"], font=ctk.CTkFont(weight="bold"), fg_color="transparent", border_width=1, border_color="#555555", hover_color="#333333", command=self.destroy)
        btn_fechar.pack(side="left", padx=10)

    def baixar_atualizacao(self):
        webbrowser.open(GITHUB_RELEASE_URL)
        self.destroy()

# ================= INTERFACE GRÁFICA =================
ctk.set_appearance_mode("Dark")

class EngineSyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.lang = get_system_lang()
        self.txt = STRINGS[self.lang]
        
        self.title(f"{self.txt['title']} ({VERSAO_ATUAL})") # Adiciona a versão no título da janela
        self.geometry("700x700")  # Altura aumentada para todos os elementos ficarem visíveis
        self.resizable(False, False)
        
        self.configure(fg_color="#242424")
        
        if os.name == 'nt':
            try:
                import ctypes
                myappid = 'lehdeejay.enginesync.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        self.caminho_icone = get_resource_path("sync_icon.ico")

        if sys.platform.startswith('win'): 
            if os.path.exists(self.caminho_icone):
                def aplicar_janela_icone():
                    try:
                        self.iconbitmap(self.caminho_icone)
                    except Exception:
                        pass
                self.after(200, aplicar_janela_icone)
        
        # Inicializa o backend
        self.manager = SyncManager()
        
        # Mapeamento automático: Letra do Drive -> Caminho do m.db
        self.found_databases = self.manager.localizar_bancos_dados()
        self.dbs_by_drive = {os.path.splitdrive(db)[0].upper(): db for db in self.found_databases}

        self.path_musicas = ctk.StringVar(value=self.manager.config.get("pasta_musicas", ""))
        self.path_db = ctk.StringVar(value=self.manager.config.get("path_db", ""))

        # Adiciona observadores para validar os campos e habilitar o botão de sync em tempo real
        self.path_musicas.trace_add("write", self.validar_campos)
        self.path_db.trace_add("write", self.validar_campos)

        self.fazer_backup = ctk.BooleanVar(value=self.manager.config.get("fazer_backup", True))
        self.importar_hotcue = ctk.BooleanVar(value=False)
        self.sobrescrever_hotcue = ctk.BooleanVar(value=False)
        self.remover_orfas = ctk.BooleanVar(value=False)
        self.log_ativo = ctk.BooleanVar(value=self.manager.config.get("log", True))
        self.debug_ativo = ctk.BooleanVar(value=self.manager.config.get("debug", False))
        self.status_var = ctk.StringVar(value=self.txt["status_idle"])
        
        self.construir_ui()
        self.carregar_playlists()
        self.validar_campos() # Validação inicial
        
        # Dispara o espião do GitHub em segundo plano ao abrir o app
        threading.Thread(target=self._check_for_updates_thread, daemon=True).start()

    def _check_for_updates_thread(self):
        versao_github = check_for_updates(VERSAO_ATUAL)
        if versao_github:
            self.after(1000, lambda: PopUpAtualizacao(self, self.txt, versao_github))

    def construir_ui(self):
        img_carregada = False
        try:
            img_caminho = get_resource_path("logo_engine.png")
            if os.path.exists(img_caminho):
                imagem_logo = Image.open(img_caminho)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_titulo = ctk.CTkLabel(self, text="", image=ctk_logo)
                img_carregada = True
        except Exception as e:
            pass
            
        if not img_carregada:
            lbl_titulo = ctk.CTkLabel(self, text="ENGINE DJ SYNC", font=ctk.CTkFont(size=24, weight="bold"), text_color="#00E5A3")
            
        lbl_titulo.pack(pady=(25, 5))

        frame_config = ctk.CTkFrame(self)
        frame_config.pack(padx=30, pady=(10, 8), fill="x")

        lbl_pasta = ctk.CTkLabel(frame_config, text=self.txt["music_folder"], font=ctk.CTkFont(weight="bold"))
        lbl_pasta.grid(row=0, column=0, padx=(25, 15), pady=(10, 2), sticky="w")
        
        entry_pasta = ctk.CTkEntry(frame_config, textvariable=self.path_musicas, width=450)
        entry_pasta.grid(row=1, column=0, padx=(25, 15), pady=(0, 8), sticky="w")
        
        btn_pasta = ctk.CTkButton(frame_config, text=self.txt["browse"], width=100, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", font=ctk.CTkFont(weight="bold"), command=self.procurar_pasta)
        btn_pasta.grid(row=1, column=1, padx=(0, 20), pady=(0, 8), sticky="w")

        # Informativo de bancos localizados
        lbl_info_db = ctk.CTkLabel(frame_config, text=self.txt["dbs_found"].format(count=len(self.found_databases)), font=ctk.CTkFont(size=11, slant="italic"), text_color="#00E5A3")
        lbl_info_db.grid(row=2, column=0, padx=(25, 15), pady=(0, 10), sticky="w")

        lbl_playlist = ctk.CTkLabel(frame_config, text=self.txt["playlist"], font=ctk.CTkFont(weight="bold"))
        lbl_playlist.grid(row=3, column=0, padx=(25, 15), pady=(0, 2), sticky="w")

        self.combo_playlist = ctk.CTkComboBox(frame_config, width=450, command=self.on_playlist_changed)
        self.combo_playlist.grid(row=4, column=0, padx=(25, 15), pady=(0, 10), sticky="w")

        self.check_backup = ctk.CTkCheckBox(frame_config, text=self.txt["backup"], variable=self.fazer_backup, font=ctk.CTkFont(weight="bold"), fg_color="#00E5A3", hover_color="#00b37e", command=self.salvar_config_ui)
        self.check_backup.grid(row=5, column=0, padx=(25, 15), pady=(0, 4), sticky="w")

        estado_hotcue = "normal" if _HOTCUE_DISPONIVEL else "disabled"
        self.check_hotcue = ctk.CTkCheckBox(frame_config, text=self.txt["hotcue"], variable=self.importar_hotcue, font=ctk.CTkFont(weight="bold"), fg_color="#00E5A3", hover_color="#00b37e", state=estado_hotcue, command=self._toggle_hotcue)
        self.check_hotcue.grid(row=6, column=0, padx=(25, 15), pady=(0, 2), sticky="w")

        estado_overwrite = "normal" if (_HOTCUE_DISPONIVEL and self.importar_hotcue.get()) else "disabled"
        self.check_hotcue_overwrite = ctk.CTkCheckBox(
            frame_config,
            text=self.txt["hotcue_overwrite"],
            variable=self.sobrescrever_hotcue,
            font=ctk.CTkFont(size=12),
            fg_color="#00E5A3",
            hover_color="#00b37e",
            state=estado_overwrite,
            command=self.salvar_config_ui
        )
        self.check_hotcue_overwrite.grid(row=7, column=0, padx=(40, 15), pady=(0, 8), sticky="w")
        
        self.check_orfas = ctk.CTkCheckBox(
            frame_config, 
            text=self.txt["remover_orfas"], 
            variable=self.remover_orfas, 
            font=ctk.CTkFont(weight="bold"), 
            fg_color="#00E5A3", 
            hover_color="#00b37e", 
            command=self.salvar_config_ui
        )
        self.check_orfas.grid(row=8, column=0, padx=(25, 15), pady=(0, 10), sticky="w")

        self.lbl_status = ctk.CTkLabel(self, textvariable=self.status_var, font=ctk.CTkFont(size=14))
        self.lbl_status.pack(pady=(8, 3), fill="x", padx=30)

        self.progress_bar = ctk.CTkProgressBar(self, width=620, height=12, progress_color="#00E5A3")
        self.progress_bar.pack(pady=4)
        self.progress_bar.set(0)

        self.btn_sync = ctk.CTkButton(self, text=self.txt["sync_btn"], font=ctk.CTkFont(size=16, weight="bold"), 
                                      height=45, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", 
                                      state="disabled", command=self.iniciar_sincronizacao)
        self.btn_sync.pack(pady=(10, 6), fill="x", padx=60)

        self.btn_cancel = ctk.CTkButton(self, text=self.txt.get("cancel_btn", "Cancelar"), font=ctk.CTkFont(size=14, weight="bold"), 
                                        height=35, fg_color="#CC3333", text_color="#FFFFFF", hover_color="#AA2222", 
                                        state="disabled", command=self.cancelar_sincronizacao)
        self.btn_cancel.pack(pady=(0, 6), fill="x", padx=60)

        self.btn_doacao = ctk.CTkButton(self, text=self.txt["donation_text"], font=ctk.CTkFont(size=12, underline=True),
                                        fg_color="transparent", text_color="#00E5A3", hover_color=None,
                                        hover=False, cursor="hand2", command=self.abrir_link_doacao)
        self.btn_doacao.pack(pady=(4, 6))

        # ===== CHECKBOXES LOG / DEBUG (rodapé direito) =====
        frame_debug = ctk.CTkFrame(self, fg_color="transparent")
        frame_debug.pack(fill="x", padx=20, pady=(0, 8))

        self.chk_log = ctk.CTkCheckBox(
            frame_debug,
            text="LOG",
            variable=self.log_ativo,
            width=60,
            checkbox_width=14,
            checkbox_height=14,
            font=ctk.CTkFont(size=11),
            fg_color="#00E5A3",
            hover_color="#00b37e",
            command=self.salvar_config_ui
        )
        self.chk_log.pack(side="right", padx=(5, 0))

        self.chk_debug = ctk.CTkCheckBox(
            frame_debug,
            text="DEBUG",
            variable=self.debug_ativo,
            width=80,
            checkbox_width=14,
            checkbox_height=14,
            font=ctk.CTkFont(size=11),
            fg_color="#00E5A3",
            hover_color="#00b37e",
            command=self.salvar_config_ui
        )
        self.chk_debug.pack(side="right", padx=(5, 10))

        # ===== BOTÃO SYNC VDJ (Canto inferior esquerdo) =====
        self.btn_sync_vdj = ctk.CTkButton(
            frame_debug,
            text="Sync VDJ",
            width=70,
            height=20,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="transparent",
            text_color="#00E5A3",
            hover_color="#00b37e",
            anchor="w",
            command=self.abrir_sync_vdj
        )
        self.btn_sync_vdj.pack(side="left", padx=(5, 0))

    def abrir_sync_vdj(self):
        """Abre a interface Sync VDJ como uma janela sobreposta."""
        try:
            from Sync_VDJ.vdj_gui import VirtualDJWindow
            # Se a janela já estiver aberta, apenas foca nela
            if hasattr(self, "vdj_window") and self.vdj_window.winfo_exists():
                self.vdj_window.focus()
            else:
                self.vdj_window = VirtualDJWindow(self, self.txt)
        except ImportError as e:
            messagebox.showerror("Erro", f"Erro ao carregar a interface VDJ.\n\nVerifique se a pasta 'Sync_VDJ' e os arquivos internos estão corretos.\n\nDetalhe técnico: {e}")

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
        """Remove sufixos de criação de forma robusta, preservando o nome base original (incluindo prefixos como '-')."""
        if not nome: return ""
        res = nome

        for lang_data in STRINGS.values():
            s = lang_data.get("will_be_created_suffix")
            if s and res.endswith(s):
                res = res[:-len(s)]
                break

        return res.strip()

    def on_playlist_changed(self, choice):
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
                        self.combo_playlist.set(existing_playlists_map[folder_name.lower()])
                    else:
                        self.combo_playlist.set(folder_name + self.txt["will_be_created_suffix"])
        self.salvar_config_ui()

    def procurar_pasta(self):
        pasta = filedialog.askdirectory()
        if pasta:
            # Identifica o disco da pasta selecionada
            drive = os.path.splitdrive(pasta)[0].upper()
            db_correspondente = self.dbs_by_drive.get(drive)
            
            if not db_correspondente:
                messagebox.showerror(
                    "Erro de Drive", 
                    self.txt["error_no_db_on_drive"].format(drive=drive)
                )
                return
                
            self.path_musicas.set(os.path.normpath(pasta))
            self.path_db.set(db_correspondente)
            self.salvar_config_ui()
            self.carregar_playlists() 

    def carregar_playlists(self):
        db_path = self.path_db.get()
        pasta_atual = self.path_musicas.get()
        
        nome_padrao = None
        folder_name_from_path = None
        if pasta_atual and os.path.exists(pasta_atual):
            folder_name_from_path = os.path.basename(os.path.normpath(pasta_atual))

        raw_existing_playlists = get_playlists_from_db(db_path)
        
        # Mapeia o nome "limpo" para o nome real do banco para facilitar a busca
        existing_playlists_map = {self._limpar_nome_playlist(pl).lower(): pl for pl in raw_existing_playlists}
        
        display_options = []
        will_be_created_suffix = self.txt["will_be_created_suffix"]
        my_collection_actual_name = self.txt["collection_name"] # "MY COLLECTION"
        my_collection_display_name = self.txt["collection_name_display"] # "- MY COLLECTION"

        # 1. Adiciona a opção "MY COLLECTION" (limpa se existir no banco, com sufixo se não)
        base_mc_lower = self._limpar_nome_playlist(my_collection_actual_name).lower()
        if base_mc_lower not in existing_playlists_map:
            display_options.append(my_collection_display_name + will_be_created_suffix)
        else:
            # Usa o nome exatamente como está no banco (preserva casing e decorações originais)
            display_options.append(existing_playlists_map[base_mc_lower])

        # 2. Adiciona o nome da pasta de músicas se não for a coleção
        if folder_name_from_path:
            clean_folder_lower = self._limpar_nome_playlist(folder_name_from_path).lower()
            if clean_folder_lower != base_mc_lower:
                if clean_folder_lower not in existing_playlists_map:
                    display_options.append(folder_name_from_path + will_be_created_suffix)
                else:
                    display_options.append(existing_playlists_map[clean_folder_lower])

        # 3. Adiciona todas as outras playlists existentes sem duplicatas
        added_bases_lower = {self._limpar_nome_playlist(opt).lower() for opt in display_options}
        for pl in raw_existing_playlists:
            base_pl_lower = self._limpar_nome_playlist(pl).lower()
            if base_pl_lower not in added_bases_lower:
                display_options.append(pl)
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
            "path_db": self.path_db.get(),
            "playlist_alvo": playlist_alvo,
            "fazer_backup": self.fazer_backup.get(),
            "log": self.log_ativo.get(),
            "debug": self.debug_ativo.get()
        }
        self.manager.save_config(config_data)
    
    def cancelar_sincronizacao(self):
        if messagebox.askyesno(self.txt.get("cancel_title", "Confirmar"), 
                               self.txt.get("cancel_msg", "Deseja cancelar?")):
            self.manager.cancel_requested = True
            self.btn_cancel.configure(state="disabled")

    def iniciar_sincronizacao(self):
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
            novas, apagadas = self.manager.motor_sincronizacao(self.txt, callback_progresso)
            self.after(0, lambda: self.finalizar_sync(novas, apagadas))

        threading.Thread(target=thread_sync, daemon=True).start()

    def finalizar_sync(self, novas_musicas, apagadas_musicas):
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
        
        # Puxa o título diretamente do dicionário de idiomas
        titulo_msg = self.txt.get("success_title", "Success")
        messagebox.showinfo(title=titulo_msg, message=self.txt["success_msg"].format(novas=novas_musicas, apagadas=apagadas_musicas))

if __name__ == "__main__":
    app = EngineSyncApp()
    app.mainloop()