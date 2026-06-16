import os
import customtkinter as ctk
from PIL import Image, ImageTk
from engine_sync_app import get_resource_path
from constants import (
    IS_WIN, APP_NAME, VERSAO_ATUAL, FONT_FAMILY,
    COLOR_BG_DARK, COLOR_TEXT_MUTED
)

class ReportWindow(ctk.CTkToplevel):
    """
    Template único e padronizado para exibição de relatórios em todo o ecossistema Sync DJ.
    Centraliza o design, ícones, cabeçalhos e rodapés para manter a identidade visual.
    """
    def __init__(self, master, title, header, content, playlist_name="", txt=None):
        super().__init__(master)
        self.txt = txt
        
        # Configuração da Janela
        self.title(f"{title} ({VERSAO_ATUAL})")
        self.geometry("900x700")
        self.configure(fg_color=COLOR_BG_DARK)
        
        # Comportamento modal (fica sempre sobre a janela pai)
        self.transient(master)
        self.grab_set()
        
        # Configuração de Ícone (Padrão multi-plataforma herdado do Hub)
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

        # Cabeçalho do Relatório
        header_text = f"{header}"
        if playlist_name:
            header_text += f"\nPlaylist: {playlist_name}"
            
        lbl_header = ctk.CTkLabel(
            self, 
            text=header_text.upper(), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold")
        )
        lbl_header.pack(pady=15)

        # Área de Conteúdo (Textbox com scroll e fonte mono para logs alinhados)
        self.textbox = ctk.CTkTextbox(
            self, 
            width=860, 
            height=580, 
            font=ctk.CTkFont(family=FONT_FAMILY, size=11)
        )
        self.textbox.pack(padx=20, pady=(0, 20), fill="both", expand=True)
        
        self.textbox.insert("end", content)
        self.textbox.configure(state="disabled")

        # Rodapé Unificado
        lbl_footer = ctk.CTkLabel(
            self, 
            text=f"{APP_NAME} ({VERSAO_ATUAL})", 
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), 
            text_color=COLOR_TEXT_MUTED
        )
        lbl_footer.pack(side="bottom", pady=(5, 10))
        
        # Garante que a janela ganhe foco imediato
        self.after(10, self.lift)