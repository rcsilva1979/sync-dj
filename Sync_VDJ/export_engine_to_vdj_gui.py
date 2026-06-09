import customtkinter as ctk 
from tkinter import filedialog, messagebox
import os
import sys
import json
from PIL import Image
from datetime import datetime

# Adiciona o diretório pai (Engine-Sync) ao sys.path para importar engine_sync_app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) #
from database_utils import get_tracks_from_playlist, localizar_bancos_dados_engine, get_database_uuid, get_all_playlists_hierarchical #
from Sync_VDJ.vdj_logic import VDJManager


class ImportEngineToVDJWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master # Mantém uma referência à janela pai, se necessário

        self.title(self.txt.get("vdj_import_btn", "Exportar Playlist do Engine para o VDJ"))
        self.geometry("600x580") #
        self.resizable(False, False)
        self.configure(fg_color="#242424")

        self.vdj_manager = VDJManager()
        self.grab_set() # Torna esta janela modal
        self.after(100, self.lift) # Traz a janela para a frente

        self.engine_db_path = ctk.StringVar()
        self.selected_playlist = ctk.StringVar()
        self.target_vdj_path = ctk.StringVar()
        self.playlists_options = []

        # Busca automática de bancos de dados
        self.found_databases = localizar_bancos_dados_engine()
        if self.found_databases:
            self.engine_db_path.set(self.found_databases[0])

        self.build_ui()
        
        # Se encontrou um banco, já carrega as playlists inicialmente
        if self.engine_db_path.get():
            self.load_playlists_from_db(self.engine_db_path.get())

    def build_ui(self):
        img_carregada = False
        try:
            # Caminho para a logo dentro da subpasta Sync_VDJ relativa a este script
            vdj_logo_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Sync_VDJ", "logo_engine_VDJ.png"))
            if os.path.exists(vdj_logo_path):
                imagem_logo = Image.open(vdj_logo_path)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_logo = ctk.CTkLabel(self, text="", image=ctk_logo)
                lbl_logo.pack(pady=(10, 5))
                img_carregada = True
        except Exception as e:
            print(f"Erro ao carregar logo VDJ: {e}")
            pass
            
        if not img_carregada:
            lbl_title = ctk.CTkLabel(self, text=self.txt.get("vdj_import_btn", "Exportar Playlist do Engine para o VDJ"), font=ctk.CTkFont(size=18, weight="bold"), text_color="#00E5A3")
            lbl_title.pack(pady=(20, 10))
        else:
            # Se o logo for carregado, o título pode ter um padding menor ou fonte ligeiramente menor
            lbl_title = ctk.CTkLabel(self, text=self.txt.get("vdj_import_btn", "Exportar Playlist do Engine para o VDJ"), font=ctk.CTkFont(size=16, weight="bold"), text_color="#00E5A3")
            lbl_title.pack(pady=(5, 10))

        # Frame para seleção do banco de dados
        db_frame = ctk.CTkFrame(self, fg_color="transparent")
        db_frame.pack(padx=20, pady=10, fill="x")

        self.lbl_db = ctk.CTkLabel(db_frame, text=self.txt.get("db_file", "Banco de Dados (m.db):"), font=ctk.CTkFont(weight="bold"))
        self.lbl_db.pack(anchor="w")

        # Substituído Entry por ComboBox para busca automática
        self.combo_db = ctk.CTkComboBox(
            db_frame,
            variable=self.engine_db_path,
            values=self.found_databases,
            width=350,
            command=self.load_playlists_from_db
        )
        self.combo_db.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse_db = ctk.CTkButton(
            db_frame,
            text=self.txt.get("browse", "Procurar"),
            width=100,
            fg_color="#00E5A3",
            text_color="#000000",
            hover_color="#00b37e",
            command=self.browse_engine_db
        )
        btn_browse_db.pack(side="right")

        # Frame para seleção da playlist
        playlist_frame = ctk.CTkFrame(self, fg_color="transparent")
        playlist_frame.pack(padx=20, pady=10, fill="x")

        lbl_playlist = ctk.CTkLabel(playlist_frame, text=self.txt.get("playlist", "Playlist Raiz:"), font=ctk.CTkFont(weight="bold"))
        lbl_playlist.pack(anchor="w")

        self.combo_playlist = ctk.CTkComboBox(
            playlist_frame,
            variable=self.selected_playlist,
            values=[], # Será preenchido após a seleção do DB
            width=450,
            state="disabled" # Desabilitado até que o DB seja selecionado
        )
        self.combo_playlist.pack(fill="x", expand=True)

        # Frame para seleção da pasta de destino no VDJ
        target_frame = ctk.CTkFrame(self, fg_color="transparent")
        target_frame.pack(padx=20, pady=10, fill="x")

        lbl_target = ctk.CTkLabel(target_frame, text="Destino no Virtual DJ:", font=ctk.CTkFont(weight="bold"))
        lbl_target.pack(anchor="w")

        # Obtém as pastas MyLists/My List automaticamente
        vdj_destinos = self.vdj_manager.localizar_diretorios_folders()
        vdj_destinos_display = [os.path.normpath(p) for p in vdj_destinos] # Normaliza para exibição

        self.combo_target = ctk.CTkComboBox(
            target_frame,
            variable=self.target_vdj_path,
            values=vdj_destinos_display,
            width=450
        )
        self.combo_target.pack(fill="x", expand=True)
        if vdj_destinos:
            self.target_vdj_path.set(vdj_destinos[0])

        # Botão de Importar
        btn_import = ctk.CTkButton(
            self,
            text=self.txt.get("vdj_import_btn", "Importar Playlist Selecionada"),
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#00E5A3",
            text_color="#000000",
            hover_color="#00b37e",
            height=40,
            width=350,
            command=self.perform_import
        )
        btn_import.pack(pady=20)

        # Botão para Exportar informações da Playlist do Engine DJ
        btn_export_info = ctk.CTkButton(
            self,
            text="Exportar Info da Playlist (Engine)",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#555555",
            text_color="#FFFFFF",
            hover_color="#777777",
            height=40,
            width=350,
            command=self.export_engine_playlist_info
        )
        btn_export_info.pack(pady=5)


        # Status/Log
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="#AAAAAA", wraplength=450)
        self.lbl_status.pack(pady=(0, 10))

    def browse_engine_db(self):
        db_path = filedialog.askopenfilename(
            title=self.txt.get("db_file", "Selecionar Banco de Dados Engine DJ (m.db)"),
            filetypes=[("Engine DJ Database", "*.db")]
        )
        if db_path:
            db_path_norm = os.path.normpath(db_path)
            self.engine_db_path.set(db_path_norm)
            
            # Atualiza a lista do combo se o usuário selecionou um local novo manualmente
            current_values = list(self.combo_db.cget("values"))
            if db_path_norm not in current_values:
                current_values.insert(0, db_path_norm)
                self.combo_db.configure(values=current_values)

            self.update_status(f"Banco de dados selecionado: {os.path.basename(db_path_norm)}")
            self.load_playlists_from_db(db_path_norm)
        else:
            self.update_status("Seleção de banco de dados cancelada.")

    def load_playlists_from_db(self, db_path):
        if not os.path.exists(db_path):
            self.update_status("Erro: Arquivo de banco de dados não encontrado.", "red")
            self.combo_playlist.configure(values=[], state="disabled")
            self.selected_playlist.set("")
            return

        try:
            # Atualiza o UUID na interface
            uuid = get_database_uuid(db_path)
            if uuid:
                self.lbl_db.configure(text=f"{self.txt.get('db_file', 'Banco de Dados (m.db):')} [{uuid}]")
            else:
                self.lbl_db.configure(text=self.txt.get('db_file', 'Banco de Dados (m.db):'))

            playlists = get_all_playlists_hierarchical(db_path)

            if playlists:
                self.playlists_options = playlists
                self.combo_playlist.configure(values=playlists, state="normal")
                self.selected_playlist.set(playlists[0]) # Seleciona a primeira por padrão
                self.update_status(f"{len(playlists)} playlists encontradas.")
            else:
                self.playlists_options = []
                self.selected_playlist.set("")
                self.update_status("Nenhuma playlist encontrada neste banco de dados.", "orange")
        except Exception as e:
            self.update_status(f"Erro ao carregar playlists: {e}", "red")
            self.selected_playlist.set("")

    def perform_import(self):
        db_path = self.engine_db_path.get()
        playlist_name = self.selected_playlist.get()
        dest_path = self.target_vdj_path.get()

        if not db_path or not os.path.exists(db_path):
            messagebox.showerror("Erro", "Por favor, selecione um banco de dados Engine DJ válido.")
            return
        if not playlist_name:
            messagebox.showerror("Erro", "Por favor, selecione uma playlist para importar.")
            return
        if not dest_path:
            messagebox.showerror("Erro", "Pasta de destino do VirtualDJ não identificada.")
            return

        self.update_status(f"Importando '{playlist_name}' para {os.path.basename(dest_path)}...", "blue")
        messagebox.showinfo("Importar", f"Playlist: {playlist_name}\nDestino: {dest_path}")
        self.update_status(f"Importação de '{playlist_name}' concluída (placeholder).", "green")
        self.destroy() # Fecha a janela após a ação

    def export_engine_playlist_info(self):
        db_path = self.engine_db_path.get()
        playlist_name = self.selected_playlist.get()

        if not db_path or not os.path.exists(db_path):
            messagebox.showerror("Erro", "Por favor, selecione um banco de dados Engine DJ válido.")
            return
        if not playlist_name:
            messagebox.showerror("Erro", "Por favor, selecione uma playlist para exportar.")
            return
        
        self.update_status(f"Extraindo informações da playlist '{playlist_name}'...", "blue")
        tracks = get_tracks_from_playlist(db_path, playlist_name) #

        if not tracks:
            self.update_status(f"Nenhuma faixa encontrada na playlist '{playlist_name}'.", "orange")
            messagebox.showinfo("Exportar", f"Nenhuma faixa encontrada na playlist '{playlist_name}'.")
            return

        try:
            # Obter o diretório base da aplicação (do SyncManager na janela principal, que é o master do master)
            base_dir = self.master.master.manager.base_dir
            reports_dir = os.path.join(base_dir, "Reports")

            # Criar a pasta Reports se não existir
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir)

            # Gerar um nome de arquivo com timestamp para evitar sobrescrever
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_filename = f"{playlist_name}_engine_tracks_{timestamp}.json"
            output_file_path = os.path.join(reports_dir, output_filename)

            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(tracks, f, indent=4, ensure_ascii=False)

            self.update_status(f"Informações da playlist exportadas para: {output_file_path}", "green")
            messagebox.showinfo(
                "Exportar",
                f"Informações da playlist '{playlist_name}' exportadas com sucesso para:\n{output_file_path}"
            )
        except Exception as e:
            self.update_status(f"Erro ao exportar informações da playlist: {e}", "red")
            messagebox.showerror("Erro de Exportação", f"Não foi possível exportar as informações da playlist: {e}")

    def update_status(self, message, color="#AAAAAA"):
        self.lbl_status.configure(text=message, text_color=color)