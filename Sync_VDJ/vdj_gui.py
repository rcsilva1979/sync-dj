import os
import sys
from PIL import Image
import customtkinter as ctk

try:
    # Tenta importar como parte do pacote Sync_VDJ
    from .vdj_logic import VDJManager
except (ImportError, ValueError):
    # Fallback para importação direta via namespace do pacote
    from Sync_VDJ.vdj_logic import VDJManager

try:
    # O arquivo import_engine_to_vdj_gui.py está na raiz do projeto no contexto atual
    from export_engine_to_vdj_gui import ImportEngineToVDJWindow
except ImportError:
    # Fallback caso o arquivo tenha sido movido para dentro da pasta Sync_VDJ
    from .export_engine_to_vdj_gui import ImportEngineToVDJWindow

try:
    from .import_vdj_to_engine_gui import ImportVDJToEngineWindow
except (ImportError, ValueError):
    from Sync_VDJ.import_vdj_to_engine_gui import ImportVDJToEngineWindow

class VirtualDJWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        
        self.txt = txt_strings
        self.vdj_manager = VDJManager()

        # Garante que a janela abra na frente e ganhe foco
        self.after(100, self.lift)
        self.grab_set() 

        self.title("Sync VDJ")
        self.geometry("600x400")
        self.resizable(False, False)
        self.configure(fg_color="#242424")
        
        # UI Inicial do Menu VDJ
        self.construir_ui()

    def construir_ui(self):
        img_carregada = False
        try:
            # Como este arquivo está na pasta Sync_VDJ, a logo está no mesmo diretório
            vdj_logo_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_engine_VDJ.png"))
            if os.path.exists(vdj_logo_path):
                imagem_logo = Image.open(vdj_logo_path)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_logo = ctk.CTkLabel(self, text="", image=ctk_logo)
                lbl_logo.pack(pady=(15, 5))
                img_carregada = True
        except Exception as e:
            print(f"Erro ao carregar logo VDJ: {e}")
            pass
            
        if not img_carregada:
            lbl_titulo = ctk.CTkLabel(self, text="Sync VDJ", font=ctk.CTkFont(size=24, weight="bold"), text_color="#00E5A3")
            lbl_titulo.pack(pady=(30, 10))
        else:
            lbl_titulo = ctk.CTkLabel(self, text="Sync VDJ", font=ctk.CTkFont(size=18, weight="bold"), text_color="#00E5A3")
            lbl_titulo.pack(pady=(5, 10))

        lbl_desc = ctk.CTkLabel(
            self, 
            text="Interface de Sincronização Virtual DJ", 
            font=ctk.CTkFont(size=14)
        )
        lbl_desc.pack(pady=(0, 20))

        # Botão Importar (Engine -> VDJ)
        self.btn_import = ctk.CTkButton(
            self, 
            text=self.txt.get("vdj_import_btn", "Exportar Playlist do Engine para o VDJ"),
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#00E5A3",
            text_color="#000000",
            hover_color="#00b37e",
            height=40,
            width=300, # Largura ajustada para dar espaço aos dois botões
            command=self.importar_engine_para_vdj
        )
        self.btn_import.pack(pady=10)

        # Botão Exportar (VDJ -> Engine)
        self.btn_export = ctk.CTkButton(
            self, 
            text=self.txt.get("vdj_export_btn", "Exportar Playlist do VDJ para o Engine"),
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#00E5A3",
            text_color="#000000",
            hover_color="#00b37e",
            height=40,
            width=300, # Largura ajustada
            command=self.exportar_vdj_para_engine
        )
        self.btn_export.pack(pady=10)

        self.btn_voltar = ctk.CTkButton(
            self, 
            text=self.txt.get("vdj_back_btn", "Voltar"),
            command=self.destroy # Apenas fecha esta janela
        )
        self.btn_voltar.pack(pady=20)

        # Rodapé: Exibe caminhos de sistema (Settings e MyLists) do VirtualDJ
        settings = self.vdj_manager.settings_path
        folders = self.vdj_manager.localizar_diretorios_folders()

        footer_lines = []
        footer_lines.append(f"Configuração: {settings if settings else 'Não localizada'}")
        
        if folders:
            footer_lines.append("MyLists: " + " | ".join(folders))
        else:
            footer_lines.append("Subpastas 'MyLists' não localizadas nos discos.")
            
        text_footer = "\n".join(footer_lines)
        color_footer = "#AAAAAA" if settings and folders else "#FF5555"

        self.lbl_folders_info = ctk.CTkLabel(
            self, text=text_footer, font=ctk.CTkFont(size=9), 
            text_color=color_footer, wraplength=550, justify="center"
        )
        self.lbl_folders_info.pack(side="bottom", pady=(0, 15))

    def importar_engine_para_vdj(self):
        """Placeholder para a lógica de importação do Engine para o VDJ."""
        ImportEngineToVDJWindow(self, self.txt)

    def exportar_vdj_para_engine(self):
        """Placeholder para a lógica de exportação do VDJ para o Engine."""
        ImportVDJToEngineWindow(self, self.txt)