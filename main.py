import os
import sys
import customtkinter as ctk
from PIL import Image, ImageTk
from engine_gui import EngineSyncApp, get_resource_path
from Sync_VDJ.vdj_gui import VirtualDJWindow
from engine_sync_app import get_system_lang, STRINGS, SyncManager
from constants import IS_WIN, IS_MAC, VERSAO_ATUAL

class LauncherHub(ctk.CTk):
    def __init__(self):
        super().__init__()

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
        self.manager = SyncManager()
        self.log_ativo = ctk.BooleanVar(value=self.manager.config.get("log", True))
        self.debug_ativo = ctk.BooleanVar(value=self.manager.config.get("debug", False))

        self.lang = get_system_lang()
        self.txt = STRINGS[self.lang]

        self.title(f"Engine DJ Tools Hub ({VERSAO_ATUAL})")
        self.geometry("600x600")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a1a")

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

        self.construir_ui()

    def construir_ui(self):
        # Logo Superior
        try:
            img_path = get_resource_path(os.path.join("images", "logo_engine_hub.png"))
            if os.path.exists(img_path):
                logo_img = ctk.CTkImage(Image.open(img_path), size=(450, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(25, 15))
        except:
            lbl_title = ctk.CTkLabel(self, text="ENGINE DJ TOOLS", font=ctk.CTkFont(size=24, weight="bold"), text_color="#00E5A3")
            lbl_title.pack(pady=(30, 20))

        lbl_subtitle = ctk.CTkLabel(self, text=self.txt["select_tool_prompt"], font=ctk.CTkFont(size=14))
        lbl_subtitle.pack(pady=(0, 30))

        # Botão 1: Mirror Sync (Antigo EngineSyncApp)
        self.btn_mirror = ctk.CTkButton(
            self, 
            text=self.txt["mirror_sync_btn"],
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e",
            command=self.abrir_mirror_sync
        )
        self.btn_mirror.pack(pady=10)

        # Botão 2: Sync VDJ (Integração VirtualDJ)
        self.btn_vdj = ctk.CTkButton(
            self, 
            text=self.txt["sync_vdj_btn"],
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#D84343", text_color="#FFFFFF", hover_color="#CE2323",
            command=self.abrir_sync_vdj
        )
        self.btn_vdj.pack(pady=10)

        # Botão 3: Importar Hotcues (Mixed In Key / Serato)
        self.btn_hotcue = ctk.CTkButton(
            self,
            text=self.txt["hotcue_import_btn"],
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#3498DB", text_color="#FFFFFF", hover_color="#2980B9",
            command=self.abrir_import_hotcue
        )
        self.btn_hotcue.pack(pady=10)

        # Botão 4: Reencontrar Músicas Perdidas
        self.btn_relocate = ctk.CTkButton(
            self,
            text=self.txt["relocate_lost_tracks_btn"],
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#F39C12", text_color="#000000", hover_color="#D68910",
            command=self.abrir_relocate
        )
        self.btn_relocate.pack(pady=10)

        # Frame para configurações globais de log
        frame_log = ctk.CTkFrame(self, fg_color="transparent")
        frame_log.pack(side="bottom", fill="x", padx=40, pady=(0, 5))

        self.chk_log = ctk.CTkCheckBox(
            frame_log, text=self.txt.get("log_checkbox", "LOG"), 
            variable=self.log_ativo, command=self.salvar_config_log,
            width=60, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11),
            fg_color="#00E5A3", hover_color="#00b37e"
        )
        self.chk_log.pack(side="right")

        self.chk_debug = ctk.CTkCheckBox(
            frame_log, text=self.txt.get("debug_checkbox", "DEBUG"), 
            variable=self.debug_ativo, command=self.salvar_config_log,
            width=80, checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11),
            fg_color="#00E5A3", hover_color="#00b37e"
        )
        self.chk_debug.pack(side="right", padx=(5, 10))

        lbl_footer = ctk.CTkLabel(self, text=f"Engine DJ Tools Suite ({VERSAO_ATUAL})", font=ctk.CTkFont(size=10), text_color="#555555")
        lbl_footer.pack(side="bottom", pady=(5, 10))

    def salvar_config_log(self):
        """Salva as configurações de log no arquivo global."""
        self.manager.save_config({
            "log": self.log_ativo.get(),
            "debug": self.debug_ativo.get()
        })

    def abrir_mirror_sync(self):
        EngineSyncApp(self, self.txt) # Passa a instância do LauncherHub e as strings de texto

    def abrir_import_hotcue(self):
        from mik_gui import MixedInKeyWindow
        MixedInKeyWindow(self, self.txt)

    def abrir_sync_vdj(self):
        VirtualDJWindow(self, self.txt)

    def abrir_relocate(self):
        from relocate_gui import RelocateLostTracksWindow
        RelocateLostTracksWindow(self, self.txt)

def main():
    """Inicia o Launcher Hub."""
    app = LauncherHub()
    app.mainloop()

if __name__ == "__main__":
    main()