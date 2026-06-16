import os
import sys
import threading
import webbrowser
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk
from engine_gui import EngineSyncApp, get_resource_path
from Sync_VDJ.vdj_gui import VirtualDJWindow
from engine_sync_app import get_system_lang, SyncManager, check_for_updates
from constants import (IS_WIN, IS_MAC, VERSAO_ATUAL, APP_NAME, STRINGS,
                       FONT_FAMILY, COLOR_BG_DARK, GITHUB_RELEASE_URL,
                       COLOR_TEXT_NORMAL, COLOR_TEXT_MUTED, COLOR_SWITCH_OFF,
                       CORNER_RADIUS_NONE)

# ================= POP-UP DE ATUALIZAÇÃO =================
class PopUpAtualizacao(ctk.CTkToplevel):
    """
    Janela pop-up para notificar o usuário sobre uma nova versão disponível do aplicativo.
    """
    def __init__(self, master, txt, versao_nova):
        super().__init__(master)
        
        self.txt = txt

        self.title(txt["update_title"])
        self.geometry("400x250")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

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

        lbl_header = ctk.CTkLabel(self, text=txt["update_title"], font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"), text_color="#00E5A3")
        lbl_header.pack(pady=(20, 10))

        lbl_msg = ctk.CTkLabel(self, text=txt["update_msg"].format(VERSAO_ATUAL, versao_nova), font=ctk.CTkFont(family=FONT_FAMILY, size=14))
        lbl_msg.pack(pady=(5, 20))

        frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        frame_botoes.pack(pady=10)

        btn_baixar = ctk.CTkButton(frame_botoes, text=txt["btn_yes"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", corner_radius=CORNER_RADIUS_NONE, command=self.baixar_atualizacao)
        btn_baixar.pack(side="left", padx=10)

        btn_fechar = ctk.CTkButton(frame_botoes, text=txt["btn_no"], font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"), fg_color="transparent", border_width=1, border_color=COLOR_SWITCH_OFF, hover_color="#333333", corner_radius=CORNER_RADIUS_NONE, command=self.destroy)
        btn_fechar.pack(side="left", padx=10)

    def baixar_atualizacao(self):
        webbrowser.open(GITHUB_RELEASE_URL)
        self.destroy()

class LauncherHub(ctk.CTk):
    """
    Classe principal do aplicativo, atuando como um hub para lançar as diferentes ferramentas.
    Gerencia a interface principal, verificação de atualizações e configurações globais de log.
    """
    def __init__(self):
        super().__init__()

        # Garante que as cores Pro Audio sejam renderizadas corretamente ignorando o tema do SO
        # Define o modo de aparência para "Dark" para uma estética consistente.
        # Isso garante que a interface do usuário tenha um tema escuro, independentemente das configurações do sistema operacional.
        ctk.set_appearance_mode("Dark")

        # Força o Windows a reconhecer o ícone na barra de tarefas (Taskbar)
        if IS_WIN:
            try:
                import ctypes
                # Altere para um identificador único do seu projeto
                myappid = 'syncdj.tools.hub.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        # Inicializa o backend para carregar configurações de log
        # Cria uma instância do SyncManager para gerenciar configurações e funcionalidades de backend.
        self.manager = SyncManager()
        # Variáveis de controle para os checkboxes de log e debug, carregando seus estados das configurações.
        self.log_ativo = ctk.BooleanVar(value=self.manager.config.get("log", True))
        self.debug_ativo = ctk.BooleanVar(value=self.manager.config.get("debug", False))

        # Detecta o idioma do sistema e carrega as strings de texto correspondentes.
        self.lang = get_system_lang()
        self.txt = STRINGS[self.lang]

        # Configurações da janela principal
        self.title(f"Engine DJ Tools Hub ({VERSAO_ATUAL})")
        self.geometry("720x650")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if os.path.exists(self.caminho_icone):
            def aplicar_icone():
                try:
                    if IS_WIN:
                        self.iconbitmap(self.caminho_icone)
                        self.wm_iconbitmap(self.caminho_icone)
                    else:
                        # No Mac/Linux, usamos iconphoto com suporte do PIL para ler o .ico
                        img = Image.open(self.caminho_icone)
                        self._icon_photo = ImageTk.PhotoImage(img) # Mantém referência para evitar Garbage Collection
                        self.iconphoto(False, self._icon_photo)
                except Exception as e:
                    pass
            self.after(200, aplicar_icone)
            
        # Dispara a verificação de atualizações em segundo plano ao iniciar o aplicativo.
        # Isso evita que a interface do usuário congele enquanto a verificação é realizada.
        threading.Thread(target=self._check_for_updates_thread, daemon=True).start()

        # Constrói a interface do usuário do hub.
        # Este método é responsável por criar e organizar todos os widgets na janela principal.
        self.construir_ui()

    def construir_ui(self):
        # Logo Superior
        try:
            img_path = get_resource_path(os.path.join("images", "logo_engine_hub.png"))
            if os.path.exists(img_path):
                logo_img = ctk.CTkImage(Image.open(img_path), size=(450, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(35, 10))
        except:
            lbl_title = ctk.CTkLabel(self, text="ENGINE DJ TOOLS", font=ctk.CTkFont(family=FONT_FAMILY, size=28, weight="bold"), text_color="#00E5A3")
            # Fallback para o título se a imagem do logo não puder ser carregada.
            lbl_title.pack(pady=(30, 20))
        
        # Subtítulo que instrui o usuário a selecionar uma ferramenta.
        lbl_subtitle = ctk.CTkLabel(self, text=self.txt["select_tool_prompt"].upper(), font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"), text_color="#777777")
        lbl_subtitle.pack(pady=(0, 25))

        # Grid Container para os botões (estilo "Pro Audio Cards")
        # Frame para organizar os botões das ferramentas em um layout de grade.
        grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        grid_frame.pack(expand=True, padx=40, pady=10)
        grid_frame.grid_columnconfigure((0, 1), weight=1, minsize=300)

        button_style = {
            "font": ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            "height": 90,
            "corner_radius": CORNER_RADIUS_NONE,
            "border_width": 1,
            "border_color": "#333333"
        }

        # Botão para a ferramenta "Mirror Sync"
        # Botão 1: Mirror Sync
        btn_mirror = ctk.CTkButton(
            grid_frame, text=self.txt["mirror_sync_btn"].replace(" (", "\n("),
            fg_color=COLOR_BG_DARK, hover_color="#00E5A3", text_color=COLOR_TEXT_NORMAL,
            command=self.abrir_mirror_sync, **button_style
        )
        btn_mirror.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Botão para a ferramenta "Sync VDJ"
        # Botão 2: Sync VDJ
        btn_vdj = ctk.CTkButton(
            grid_frame, text=self.txt["sync_vdj_btn"].replace(" (", "\n("),
            fg_color=COLOR_BG_DARK, hover_color="#E70E0E", text_color=COLOR_TEXT_NORMAL,
            command=self.abrir_sync_vdj, **button_style
        )
        btn_vdj.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        # Botão para a ferramenta "Mixed In Key Hotcue Sync"
        # Botão 3: Mixed In Key
        btn_hotcue = ctk.CTkButton(
            grid_frame, text=self.txt["hotcue_import_btn"].replace(" (", "\n("),
            fg_color=COLOR_BG_DARK, hover_color="#3498DB", text_color=COLOR_TEXT_NORMAL,
            command=self.abrir_import_hotcue, **button_style
        )
        btn_hotcue.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        # Botão para a ferramenta "Relocate Lost Tracks"
        # Botão 4: Relocate
        btn_relocate = ctk.CTkButton(
            grid_frame, text=self.txt["relocate_lost_tracks_btn"].replace(" (", "\n("),
            fg_color=COLOR_BG_DARK, hover_color="#F39C12", text_color=COLOR_TEXT_NORMAL,
            command=self.abrir_relocate, **button_style
        )
        btn_relocate.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

        # Rodapé e Configurações
        # Frame para agrupar o rodapé e as configurações de log.
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", pady=(20, 15))

        # Frame para configurações globais de log
        # Contém os switches para ativar/desativar o log e o modo debug.
        settings_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        settings_frame.pack(pady=(0, 10))

        lbl_settings = ctk.CTkLabel(settings_frame, text="Preferências:", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=COLOR_TEXT_MUTED)
        lbl_settings.pack(side="left", padx=10)

        self.chk_log = ctk.CTkSwitch(
            settings_frame, text=self.txt.get("log_checkbox", "LOG"),
            variable=self.log_ativo, command=self.salvar_config_log,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            fg_color=COLOR_SWITCH_OFF,
            progress_color="#00E5A3"
        )
        self.chk_log.pack(side="right", padx=(0, 5))
        self.chk_debug = ctk.CTkSwitch(
            settings_frame, text=self.txt.get("debug_checkbox", "DEBUG"),
            variable=self.debug_ativo, command=self.salvar_config_log,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            fg_color=COLOR_SWITCH_OFF,
            progress_color="#00E5A3"
        )
        self.chk_debug.pack(side="right", padx=(0, 10))
        lbl_footer = ctk.CTkLabel(bottom_frame, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        # Exibe o nome e a versão do aplicativo no rodapé.
        lbl_footer.pack()

    def salvar_config_log(self):
        """Salva as configurações de log no arquivo global."""
        """
        Salva o estado atual dos switches de log e debug no arquivo de configuração global.
        Isso garante que as preferências do usuário sejam persistidas entre as sessões.
        """
        self.manager.save_config({
            "log": self.log_ativo.get(),
            "debug": self.debug_ativo.get()
        })

    def abrir_mirror_sync(self):
        """
        Abre a janela da ferramenta "Mirror Sync".
        """
        EngineSyncApp(self, self.txt) # Passa a instância do LauncherHub e as strings de texto

    def abrir_import_hotcue(self):
        """
        Abre a janela da ferramenta "Mixed In Key Hotcue Sync".
        """
        from mik_gui import MixedInKeyWindow
        MixedInKeyWindow(self, self.txt)

    def abrir_sync_vdj(self):
        """Abre a janela da ferramenta "Sync VDJ"."""
        VirtualDJWindow(self, self.txt)

    def abrir_relocate(self):
        """Abre a janela da ferramenta "Relocate Lost Tracks"."""
        from relocate_gui import RelocateLostTracksWindow
        RelocateLostTracksWindow(self, self.txt)
        
    def _check_for_updates_thread(self):
        """
        Verifica se há atualizações disponíveis em uma thread separada.
        Se uma nova versão for encontrada, exibe um pop-up de atualização.
        """
        versao_github = check_for_updates(VERSAO_ATUAL)
        if versao_github:
            self.after(1000, lambda: PopUpAtualizacao(self, self.txt, versao_github))

def main():
    """
    Função principal para iniciar o Launcher Hub.
    Cria uma instância do LauncherHub e inicia o loop principal da interface gráfica.
    """
    app = LauncherHub()
    app.mainloop()

if __name__ == "__main__":
    main()