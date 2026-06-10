import customtkinter as ctk 
from tkinter import filedialog, messagebox
import os
import sys
import json
from PIL import Image
from datetime import datetime
from collections import defaultdict
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

# Adiciona o diretório pai (Engine-Sync) ao sys.path para importar engine_sync_app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) #
from database_utils import get_tracks_from_playlist, localizar_bancos_dados_engine, get_database_uuid, get_all_playlists_hierarchical #
from engine_sync_app import get_resource_path
from Sync_VDJ.vdj_logic import VDJManager

ALL_DBS_LABEL = ">>> TODOS OS BANCOS LOCALIZADOS <<<"

class ImportEngineToVDJWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master # Mantém uma referência à janela pai, se necessário

        self.title(self.txt.get("vdj_import_btn", "Exportar Playlist do Engine para o VDJ"))
        self.geometry("600x500") 
        self.resizable(False, False)
        self.configure(fg_color="#242424")

        self.vdj_manager = VDJManager()
        self.transient(master)   # Vincula esta janela à janela pai (Sync VDJ)
        self.grab_set()          # Restaura o modo modal para a janela ficar sempre no topo e focar
        self.after(10, self.lift)

        self.selected_playlist = ctk.StringVar()
        self.target_vdj_path = ctk.StringVar()
        self.playlists_options = []
        self.playlist_db_map = defaultdict(list) # Mapeia o caminho da playlist para uma LISTA de (caminho_db, playlist_id)

        # Busca automática de bancos de dados
        self.found_databases = localizar_bancos_dados_engine()

        self.build_ui()
        
        # Carrega automaticamente as playlists de TODOS os bancos localizados
        if self.found_databases:
            self.load_playlists_from_db(ALL_DBS_LABEL)

    def build_ui(self):
        img_carregada = False
        try:
            vdj_logo_path = get_resource_path(os.path.join("images", "logo_engine_VDJ.png"))
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

        # Informativo de bancos localizados (Substitui a seleção manual)
        self.lbl_db_info = ctk.CTkLabel(self, text=f"Bancos Engine detectados: {len(self.found_databases)}", font=ctk.CTkFont(size=12, slant="italic"), text_color="#00E5A3")
        self.lbl_db_info.pack(pady=(5, 5))

        # Frame para seleção da playlist
        playlist_frame = ctk.CTkFrame(self, fg_color="transparent")
        playlist_frame.pack(padx=20, pady=10, fill="x")

        lbl_playlist = ctk.CTkLabel(playlist_frame, text=self.txt.get("playlist_label", "Selecionar Playlist (Caminho Completo):"), font=ctk.CTkFont(weight="bold"))
        lbl_playlist.pack(anchor="w")

        # Seletor de playlist usando ComboBox padrão (estável e com rolagem nativa)
        self.combo_playlist = ctk.CTkComboBox(
            playlist_frame,
            variable=self.selected_playlist,
            values=[],
            width=540,
            state="disabled"
        )
        self.combo_playlist.pack(fill="x", expand=True, pady=(5, 0))

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
            # Garante que o valor inicial seja um dos valores válidos
            if self.target_vdj_path.get() not in vdj_destinos_display and vdj_destinos_display:
                self.target_vdj_path.set(vdj_destinos_display[0])
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

    def load_playlists_from_db(self, db_path):
        if not db_path:
            return
            
        if db_path != ALL_DBS_LABEL and not os.path.exists(db_path):
            self.update_status("Erro: Arquivo de banco de dados não encontrado.", "red")
            self.selected_playlist.set("")
            return

        try:
            self.playlist_db_map = defaultdict(list)
            
            # Define quais bancos carregar
            paths_to_load = self.found_databases if db_path == ALL_DBS_LABEL else [db_path]
            
            for path in paths_to_load:
                if not os.path.exists(path):
                    continue
                
                # Obtém todas as playlists (incluindo subpastas) em formato de tupla (caminho, id)
                results = get_all_playlists_hierarchical(path)
                for pl_path, pl_id in results:
                    # Usamos o caminho hierárquico puro como chave para agrupar playlists de discos diferentes
                    self.playlist_db_map[pl_path].append((path, pl_id))

            all_playlists_display = sorted(list(self.playlist_db_map.keys()))

            # Atualiza UUID ou status de multi-banco
            self.update_status(f"Modo Multi-Banco ativo ({len(paths_to_load)} discos).")
            
            if all_playlists_display:
                self.playlists_options = all_playlists_display
                self.combo_playlist.configure(values=all_playlists_display, state="normal")
                self.selected_playlist.set(all_playlists_display[0])
                self.update_status(f"{len(all_playlists_display)} playlists carregadas.")
            else:
                self.playlists_options = []
                self.combo_playlist.configure(values=[], state="disabled")
                self.selected_playlist.set("")
                self.update_status("Nenhuma playlist encontrada.", "orange")
        except Exception as e:
            self.update_status(f"Erro ao carregar playlists: {e}", "red")
            self.combo_playlist.configure(values=[], state="disabled")
            self.selected_playlist.set("")

    def perform_import(self):
        display_name = self.selected_playlist.get()
        sources = self.playlist_db_map.get(display_name)
        dest_path = self.target_vdj_path.get()

        if not sources:
            messagebox.showerror("Erro", "Por favor, selecione uma playlist para importar.")
            return

        if not dest_path:
            messagebox.showerror("Erro", "Pasta de destino do VirtualDJ não identificada.")
            return

        num_fontes = len(sources)
        msg_hibrida = f" (Playlist Híbrida detectada em {num_fontes} discos)" if num_fontes > 1 else ""
        
        try:
            self.update_status(f"Coletando faixas de '{display_name}'...", "blue")
            
            all_tracks = []
            for db_path, pl_id in sources:
                tracks = get_tracks_from_playlist(db_path, playlist_id=pl_id)
                all_tracks.extend(tracks)

            if not all_tracks:
                self.update_status(f"Nenhuma faixa encontrada em '{display_name}'.", "orange")
                return

            # Cria estrutura XML do Virtual DJ (VirtualFolder)
            root = ET.Element("VirtualFolder", noDuplicates="yes")

            for idx, track in enumerate(all_tracks):
                path_abs = str(track.get("caminho_absoluto") or "")
                
                # Virtual DJ precisa do tamanho do arquivo para validação interna
                size = "0"
                if path_abs and os.path.exists(path_abs):
                    size = str(os.path.getsize(path_abs))

                song = ET.SubElement(root, "song")
                song.set("path", path_abs)
                song.set("size", size)
                song.set("songlength", str(track.get("length") or 0))
                song.set("bpm", str(track.get("bpm") or 0.0))
                song.set("key", str(track.get("key") or ""))
                song.set("artist", str(track.get("artist") or ""))
                song.set("title", str(track.get("title") or ""))
                song.set("idx", str(idx))

            # Formatação "Pretty Print" para o XML
            xml_bytes = ET.tostring(root, encoding='utf-8')
            dom = minidom.parseString(xml_bytes)
            pretty_xml = dom.toprettyxml(indent="\t", encoding="UTF-8").decode("UTF-8")

            # Sanitiza o nome do arquivo (Troca ' / ' por ' - ' e remove caracteres inválidos)
            safe_name = display_name.replace(" / ", " - ").strip()
            safe_name = "".join([c for c in safe_name if c.isalnum() or c in (' ', '-', '_', '.')]).rstrip()
            output_file = os.path.join(dest_path, f"{safe_name}.vdjfolder")

            with open(output_file, "wb") as f:
                f.write(pretty_xml.encode("UTF-8"))

            self.update_status(f"Sucesso! '{display_name}' exportada.", "green")
            messagebox.showinfo("Sucesso", f"Playlist exportada para o Virtual DJ!\n{len(all_tracks)} músicas processadas.\n{msg_hibrida}\n\nArquivo: {output_file}")
            self.destroy() # Fecha a janela após o sucesso

        except Exception as e:
            self.update_status(f"Erro na exportação: {e}", "red")
            messagebox.showerror("Erro de Exportação", f"Não foi possível gerar o arquivo XML:\n{e}")

    def export_engine_playlist_info(self):
        display_name = self.selected_playlist.get()
        sources = self.playlist_db_map.get(display_name)

        if not sources:
            messagebox.showerror("Erro", "Por favor, selecione uma playlist válida.")
            return
        
        self.update_status(f"Extraindo informações da playlist '{display_name}'...", "blue")
        
        all_tracks = []
        for db_path, pl_id in sources:
            # Agora buscamos pelo ID garantido para cada banco
            tracks = get_tracks_from_playlist(db_path, playlist_id=pl_id)
            all_tracks.extend(tracks)

        if not all_tracks:
            self.update_status(f"Nenhuma faixa encontrada na playlist '{display_name}'.", "orange")
            messagebox.showinfo("Exportar", f"Nenhuma faixa encontrada na playlist '{display_name}'.")
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
            output_filename = f"{display_name.replace(' / ', '_')}_combined_{timestamp}.json"
            output_file_path = os.path.join(reports_dir, output_filename)

            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_tracks, f, indent=4, ensure_ascii=False)

            self.update_status(f"Exportadas {len(all_tracks)} faixas de {len(sources)} banco(s).", "green")
            messagebox.showinfo(
                "Exportar",
                f"Playlist '{display_name}' exportada ({len(all_tracks)} faixas unificadas).\n\nArquivo: {output_file_path}"
            )
        except Exception as e:
            self.update_status(f"Erro ao exportar informações da playlist: {e}", "red")
            messagebox.showerror("Erro de Exportação", f"Não foi possível exportar as informações da playlist: {e}")

    def update_status(self, message, color="#AAAAAA"):
        self.lbl_status.configure(text=message, text_color=color)