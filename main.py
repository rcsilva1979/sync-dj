import os
import sys
import customtkinter as ctk
from PIL import Image
from engine_gui import EngineSyncApp, get_resource_path
from Sync_VDJ.vdj_gui import VirtualDJWindow
from engine_sync_app import get_system_lang, STRINGS

class LauncherHub(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.lang = get_system_lang()
        self.txt = STRINGS[self.lang]

        self.title("Engine DJ Tools Hub")
        self.geometry("600x450")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a1a")

        # Configuração de Ícone
        self.caminho_icone = get_resource_path("sync_icon.ico")
        if sys.platform.startswith('win') and os.path.exists(self.caminho_icone):
            try: self.iconbitmap(self.caminho_icone)
            except: pass

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

        lbl_subtitle = ctk.CTkLabel(self, text="Selecione a ferramenta desejada:", font=ctk.CTkFont(size=14))
        lbl_subtitle.pack(pady=(0, 30))

        # Botão 1: Mirror Sync (Antigo EngineSyncApp)
        self.btn_mirror = ctk.CTkButton(
            self, 
            text="Mirror Sync (Pasta → Engine DJ)",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e",
            command=self.abrir_mirror_sync
        )
        self.btn_mirror.pack(pady=10)

        # Botão 2: Sync VDJ (Integração VirtualDJ)
        self.btn_vdj = ctk.CTkButton(
            self, 
            text="Sync VDJ (Engine ⟷ VirtualDJ)",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=60, width=400,
            fg_color="#D84343", text_color="#FFFFFF", hover_color="#CE2323",
            command=self.abrir_sync_vdj
        )
        self.btn_vdj.pack(pady=10)

        lbl_footer = ctk.CTkLabel(self, text="Engine DJ Tools Suite", font=ctk.CTkFont(size=10), text_color="#555555")
        lbl_footer.pack(side="bottom", pady=10)

    def abrir_mirror_sync(self):
        EngineSyncApp(self)

    def abrir_sync_vdj(self):
        VirtualDJWindow(self, self.txt)

def main():
    """Inicia o Launcher Hub."""
    app = LauncherHub()
    app.mainloop()

if __name__ == "__main__":
    main()