import os
import sys
import customtkinter as ctk
from PIL import Image, ImageTk
from engine_sync_app import get_resource_path
from constants import (IS_WIN, APP_NAME, VERSAO_ATUAL, FONT_FAMILY,
                       COLOR_BG_DARK, COLOR_TEXT_MUTED, CORNER_RADIUS_NONE,
                       COLOR_ACCENT_BLUE, COLOR_TEXT_NORMAL,
                       COLOR_ACCENT_GREEN) # Importar COLOR_ACCENT_GREEN para o segundo botão
from import_device_playlist_gui import ImportDevicePlaylistWindow # Importar a nova janela
from engine_history_gui import EngineHistoryWindow
from smart_playlist_gui import SmartPlaylistWindow

class EngineToolsWindow(ctk.CTkToplevel):
    """
    Janela para agrupar ferramentas diversas relacionadas ao Engine DJ.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(f"{self.txt['engine_tools_title']} ({VERSAO_ATUAL})")
        self.geometry("600x510")
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

        self.construir_ui()

    def construir_ui(self):
        logo_path = get_resource_path(os.path.join("images", "logo_tools_engine.png"))
        if os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path)
                self.logo_engine_tools = ctk.CTkImage(
                    light_image=logo,
                    dark_image=logo,
                    size=(480, 90),
                )
                ctk.CTkLabel(self, text="", image=self.logo_engine_tools).pack(pady=(20, 8))
            except Exception:
                pass

        

        # Frame para os botões
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(pady=10)

        # Botão 1
        btn1 = ctk.CTkButton(button_frame, text=self.txt.get("engine_tools_import_device_playlist_btn"),
                             font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                             height=40, width=250, fg_color=COLOR_ACCENT_BLUE,
                             text_color=COLOR_TEXT_NORMAL, hover_color="#1F4E79",
                             corner_radius=CORNER_RADIUS_NONE, command=self.abrir_import_device_playlist)
        btn1.pack(pady=10)

        # Botão 2 - Exportar histórico de evento
        btn2 = ctk.CTkButton(button_frame, text=self.txt.get("engine_tools_export_history_btn", "Exportar Histórico"),
                     font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                     height=40, width=250, fg_color=COLOR_ACCENT_GREEN, # Usar uma cor diferente para o segundo botão
                     text_color=COLOR_TEXT_NORMAL, hover_color="#00b37e", # Cor de hover para o segundo botão
                     corner_radius=CORNER_RADIUS_NONE, command=self.abrir_export_history)
        btn2.pack(pady=10)

        btn3 = ctk.CTkButton(button_frame, text="Criar Smart Playlist",
                            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                            height=40, width=250, fg_color="#8E44AD",
                            text_color=COLOR_TEXT_NORMAL, hover_color="#6C3483",
                            corner_radius=CORNER_RADIUS_NONE, command=self.abrir_smart_playlist)
        btn3.pack(pady=10)

        # Rodapé
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

    def abrir_import_device_playlist(self):
        """Abre a janela para importar playlists de dispositivos externos."""
        ImportDevicePlaylistWindow(self, self.txt)

    def abrir_export_history(self):
        """Abre a janela para visualizar e exportar históricos encontrados em hm.db."""
        history_window = EngineHistoryWindow(self, self.txt)
        history_window.lift()
        history_window.focus()

    def abrir_smart_playlist(self):
        """Abre a janela para criar uma smart playlist a partir de uma música inicial."""
        smart_window = SmartPlaylistWindow(self, self.txt)
        smart_window.lift()
        smart_window.focus()
