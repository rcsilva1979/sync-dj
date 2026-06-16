import customtkinter as ctk 
from tkinter import filedialog, messagebox
import os
import sys
import json
from PIL import Image, ImageTk
from datetime import datetime
from collections import defaultdict
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

# Adiciona o diretório pai (Engine-Sync) ao sys.path para importar engine_sync_app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) #
from database_utils import get_tracks_by_playlist_id, localizar_bancos_dados_engine, get_database_uuid, get_all_playlists_hierarchical #
from engine_sync_app import SyncManager, get_resource_path, IS_WIN, IS_MAC
from constants import (VERSAO_ATUAL, APP_NAME, FONT_FAMILY,
                       COLOR_BG_DARK, COLOR_TEXT_NORMAL,
                       COLOR_TEXT_MUTED, COLOR_SWITCH_OFF,
                       CORNER_RADIUS_NONE)
from Sync_VDJ.vdj_logic import VDJManager

class ImportEngineToVDJWindow(ctk.CTkToplevel):
    """
    Janela da ferramenta para exportar playlists do Engine DJ para o Virtual DJ.
    Permite ao usuário selecionar um banco de dados do Engine DJ, uma playlist
    e um diretório de destino no Virtual DJ para gerar um arquivo .vdjfolder.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master # Mantém uma referência à janela pai, se necessário
        """Inicializa a janela de exportação do Engine DJ para o Virtual DJ."""

        self.title(f"{self.txt.get('vdj_export_btn', 'Exportar Playlist do Engine para o VDJ')} ({VERSAO_ATUAL})")
        self.geometry("600x600") 
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        self.manager = SyncManager()
        self.vdj_manager = VDJManager()
        self.transient(master)   # Vincula esta janela à janela pai (Sync VDJ)
        self.grab_set()          # Restaura o modo modal para a janela ficar sempre no topo e focar
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

        self.selected_playlist = ctk.StringVar()
        # Variável para armazenar o caminho de destino no Virtual DJ.
        self.target_vdj_path = ctk.StringVar()
        # Lista de opções de playlists disponíveis para seleção.
        self.playlists_options = []
        # Mapeamento de caminhos de playlist para uma lista de tuplas (caminho_db, playlist_id).
        self.playlist_db_map = defaultdict(list) # Mapeia o caminho da playlist para uma LISTA de (caminho_db, playlist_id)

        # Busca automática de bancos de dados
        # Lista de caminhos para todos os bancos de dados Engine DJ encontrados no sistema.
        self.found_databases = localizar_bancos_dados_engine()

        self.build_ui()

        # Adiciona observador para atualizar os drives destacados ao selecionar uma playlist
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        
        # Carrega automaticamente as playlists de TODOS os bancos localizados
        # Isso garante que o ComboBox de playlists seja preenchido ao iniciar a janela,
        # mostrando playlists de todos os bancos detectados para uma visão abrangente.
        # O label ">>> TODOS OS BANCOS LOCALIZADOS <<<" é usado para indicar essa opção.
        if self.found_databases: # type: ignore
            self.load_playlists_from_db(self.txt.get("all_dbs_label", ">>> TODOS OS BANCOS LOCALIZADOS <<<"))

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
            lbl_title = ctk.CTkLabel(self, text=self.txt.get("vdj_export_btn", "Exportar Playlist do Engine para o VDJ"), font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"), text_color="#00E5A3")
            lbl_title.pack(pady=(20, 10))
        else:
            # Se o logo for carregado, o título pode ter um padding menor ou fonte ligeiramente menor
            lbl_title = ctk.CTkLabel(self, text=self.txt.get("vdj_export_btn", "Exportar Playlist do Engine para o VDJ"), font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"), text_color="#00E5A3")
            lbl_title.pack(pady=(5, 10))

        # Label para exibir o status da detecção automática de bancos de dados.
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"), text_color="#00E5A3")
        self.lbl_db_auto.pack(pady=(10, 5))

        # Frame para seleção da playlist
        # Agrupa os controles relacionados à seleção da playlist a ser exportada.
        playlist_frame = ctk.CTkFrame(self, fg_color="transparent")
        playlist_frame.pack(padx=20, pady=10, fill="x")

        # Label para a seleção da playlist.
        lbl_playlist = ctk.CTkLabel(playlist_frame, text=self.txt.get("select_playlist_full_path", "Selecionar Playlist (Caminho Completo):"), font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"))
        lbl_playlist.pack(anchor="w")

        # ComboBox para selecionar a playlist a ser exportada.
        # Seletor de playlist usando ComboBox padrão (estável e com rolagem nativa)
        self.combo_playlist = ctk.CTkComboBox(
            playlist_frame,
            variable=self.selected_playlist,
            values=[],
            width=540,
            corner_radius=CORNER_RADIUS_NONE,
            state="disabled",
            font=ctk.CTkFont(family=FONT_FAMILY),
            dropdown_font=ctk.CTkFont(family=FONT_FAMILY)
        )
        self.combo_playlist.pack(fill="x", expand=True, pady=(5, 0))

        # Frame para seleção da pasta de destino no VDJ
        # Agrupa os controles relacionados à seleção do diretório de destino no Virtual DJ.
        target_frame = ctk.CTkFrame(self, fg_color="transparent")
        target_frame.pack(padx=20, pady=10, fill="x")

        # Label para o diretório de destino no Virtual DJ.
        lbl_target = ctk.CTkLabel(target_frame, text=self.txt.get("vdj_target_label", "Destino no Virtual DJ:"), font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"))
        lbl_target.pack(anchor="w")

        # ComboBox para selecionar o diretório de destino no Virtual DJ.
        # Obtém as pastas MyLists/My List automaticamente
        vdj_destinos = self.vdj_manager.localizar_diretorios_folders()
        vdj_destinos_display = [os.path.normpath(p) for p in vdj_destinos] # Normaliza para exibição

        self.combo_target = ctk.CTkComboBox(
            target_frame,
            variable=self.target_vdj_path,
            values=vdj_destinos_display,
            width=450,
            corner_radius=CORNER_RADIUS_NONE,
            font=ctk.CTkFont(family=FONT_FAMILY),
            dropdown_font=ctk.CTkFont(family=FONT_FAMILY)
        )
        self.combo_target.pack(fill="x", expand=True)
        if vdj_destinos:
            # Define o primeiro destino localizado como padrão
            self.target_vdj_path.set(vdj_destinos_display[0])
        # Botão para iniciar o processo de exportação da playlist.

        # Botão de Importar
        btn_import = ctk.CTkButton(
            self,
            text=self.txt.get("vdj_export_btn", "Importar Playlist Selecionada"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), corner_radius=CORNER_RADIUS_NONE,
            fg_color="#00E5A3",
            text_color="#000000",
            hover_color="#00b37e",
            height=40,
            width=350,
            command=self.perform_import
        )
        btn_import.pack(pady=20)

        # Botão para exportar informações detalhadas da playlist do Engine DJ para um arquivo JSON.
        # Botão para Exportar informações da Playlist do Engine DJ
        btn_export_info = ctk.CTkButton(
            self,
            text=self.txt.get("export_engine_info_btn", "Exportar Info da Playlist (Engine)"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            fg_color="#555555",
            text_color=COLOR_TEXT_NORMAL,
            hover_color="#777777",
            height=40, corner_radius=CORNER_RADIUS_NONE,
            width=350,
            command=self.export_engine_playlist_info
        )
        btn_export_info.pack(pady=5)

        # Status/Log
        # Label para exibir mensagens de status e feedback ao usuário.
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT_MUTED, wraplength=450)
        self.lbl_status.pack(pady=(0, 10))

        # Rodapé com informações do aplicativo.
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

    def load_playlists_from_db(self, db_path):
        """
        Carrega as playlists do banco de dados selecionado (ou de todos os bancos detectados)
        e as exibe no ComboBox de playlists.
        Atualiza o label de status e o destaque dos drives.
        """
        """Carrega as playlists do banco selecionado ou de todos os bancos detectados."""
        if not db_path:
            return # type: ignore
            
        if db_path != self.txt.get("all_dbs_label", ">>> TODOS OS BANCOS LOCALIZADOS <<<") and not os.path.exists(db_path):
            self.update_status(self.txt.get("error_db_file_not_found_vdj_export", "Erro: Arquivo de banco de dados não encontrado."), "red")
            self.selected_playlist.set("")
            return

        try:
            self.playlist_db_map = defaultdict(list)
            
            # Define quais bancos carregar
            paths_to_load = self.found_databases if db_path == self.txt.get("all_dbs_label", ">>> TODOS OS BANCOS LOCALIZADOS <<<") else [db_path]
            
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
            self.update_status(self.txt.get("multi_db_mode_active", "Modo Multi-Banco ativo ({count} discos).").format(count=len(paths_to_load)))
            
            if all_playlists_display:
                self.playlists_options = all_playlists_display
                self.combo_playlist.configure(values=all_playlists_display, state="normal")
                self.selected_playlist.set(all_playlists_display[0])
                self.update_status(self.txt.get("playlists_loaded_count", "{count} playlists carregadas.").format(count=len(all_playlists_display)))
                self.atualizar_label_drives()
            else:
                self.playlists_options = []
                self.combo_playlist.configure(values=[], state="disabled")
                self.selected_playlist.set("")
                self.update_status(self.txt.get("no_playlists_found_generic", "Nenhuma playlist encontrada."), "orange")
        except Exception as e:
            self.update_status(self.txt.get("error_loading_playlists_vdj_export", "Erro ao carregar playlists: {error}").format(error=e), "red")
            self.combo_playlist.configure(values=[], state="disabled")
            self.selected_playlist.set("")

    def _get_vol_id(self, path):
        """
        Helper para identificar o 'Drive' no Windows ou 'Volume' no macOS a partir de um caminho.
        """
        """Helper para identificar o 'Drive' no Win ou 'Volume' no Mac."""
        abs_p = os.path.abspath(path)
        if IS_WIN:
            return os.path.splitdrive(abs_p)[0].upper()
        else:
            p = abs_p.split(os.sep)
            return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

    def atualizar_label_drives(self):
        """
        Atualiza o label que exibe os drives detectados, destacando aqueles que contêm a playlist selecionada.
        """
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        if not playlist_atual:
            return

        # Identifica em quais bancos/drives a playlist selecionada existe
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {self._get_vol_id(db) for db in dbs_com_playlist}
        drives_totais = sorted(list({self._get_vol_id(d) for d in self.found_databases}))
        
        texto_drives = " | ".join([
            f"[{d}]" if d in drives_com_playlist else d 
            for d in drives_totais
        ])
        status_text = f"✔ {self.txt['engine_dbs_detected'].format(count=len(self.found_databases))}: {texto_drives}"
        self.lbl_db_auto.configure(text=status_text, text_color="#00E5A3")

    def perform_import(self):
        """
        Executa a exportação da playlist selecionada do Engine DJ para o Virtual DJ.
        Coleta as faixas de todos os bancos onde a playlist existe, unifica-as e gera um arquivo .vdjfolder.
        """
        display_name = self.selected_playlist.get()
        sources = self.playlist_db_map.get(display_name) # type: ignore
        dest_path = self.target_vdj_path.get()

        if not sources: # type: ignore
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_select_playlist_to_import_vdj", "Por favor, selecione uma playlist para importar."))
            return

        if not dest_path: # type: ignore
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("error_vdj_dest_not_found", "Pasta de destino do VirtualDJ não identificada."))
            return

        num_fontes = len(sources)
        hybrid_msg = self.txt.get("hybrid_playlist_detected_msg", " (Playlist Híbrida detectada em {num_drives} discos)").format(num_drives=num_fontes) if num_fontes > 1 else ""
        
        try: # type: ignore
            self.update_status(self.txt.get("status_collecting_tracks_vdj", "Coletando faixas de '{playlist_name}'...").format(playlist_name=display_name), "blue")
            
            # Inicializa log para Exportação VDJ
            log_paths = self.manager.iniciar_log(
                dest_path, "Engine to VDJ", display_name, 
                self.manager.config.get("log", True), self.manager.config.get("debug", False), 
                tool_name="VDJ_EXPORT")

            self.manager.log(log_paths, "=== INÍCIO DA EXPORTAÇÃO ENGINE -> VIRTUAL DJ ===")
            self.manager.log(log_paths, f"Playlist selecionada : {display_name}")
            self.manager.log(log_paths, f"Pasta de destino      : {dest_path}")
            self.manager.log(log_paths, f"Drives fontes         : {len(sources)} banco(s) detectado(s)")
            
            all_tracks = []
            seen_paths = set()
            count_missing = 0
            count_duplicate = 0

            for db_path, pl_id in sources: # type: ignore
                self.manager.log(log_paths, f"Processando banco: {db_path}", nivel="debug")
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                self.manager.log(log_paths, f"  -> {len(tracks)} faixas encontradas no banco.", nivel="debug")

                for track in tracks:
                    title = track.get('title', 'Unknown')
                    path_abs = track.get("caminho_absoluto")
                    
                    if not path_abs:
                        self.manager.log(log_paths, f"  [AVISO] Faixa '{title}' (ID {track.get('id')}) sem caminho absoluto no banco.", nivel="debug")
                        continue

                    norm_path = os.path.normcase(os.path.abspath(path_abs))

                    if not os.path.exists(path_abs):
                        self.manager.log(log_paths, f"  [FALTANTE] Arquivo não existe no disco: {path_abs}")
                        count_missing += 1
                        continue

                    if norm_path in seen_paths:
                        self.manager.log(log_paths, f"  [SKIP] Duplicada ignorada: {title} ({path_abs})", nivel="debug")
                        count_duplicate += 1
                        continue

                    self.manager.log(log_paths, f"  [OK] Validada: {title}", nivel="debug")
                    all_tracks.append(track)
                    seen_paths.add(norm_path)

            self.manager.log(log_paths, f"Coleta finalizada: {len(all_tracks)} válidas, {count_missing} faltantes, {count_duplicate} duplicadas.")

            if not all_tracks:
                self.manager.log(log_paths, "ERRO: Nenhuma faixa válida encontrada para exportação.")
                self.update_status(self.txt.get("no_tracks_found_in_playlist_vdj_export", "Nenhuma faixa encontrada em '{playlist_name}'.").format(playlist_name=display_name), "orange")
                return

            self.manager.log(log_paths, f"Gerando arquivo XML .vdjfolder para {len(all_tracks)} faixas...")

            # Cria estrutura XML do Virtual DJ (VirtualFolder)
            root = ET.Element("VirtualFolder", noDuplicates="yes")

            for idx, track in enumerate(all_tracks):
                path_abs = str(track.get("caminho_absoluto") or "")
                
                # O arquivo já foi validado na coleta, podemos obter o tamanho com segurança
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
                self.manager.log(log_paths, f"Escrita concluída: {output_file} ({os.path.getsize(output_file)} bytes)")

            self.update_status(self.txt.get("success_playlist_exported_vdj_status", "Sucesso! '{playlist_name}' exportada.").format(playlist_name=display_name), "green")
            self.manager.log(log_paths, "=== EXPORTAÇÃO CONCLUÍDA COM SUCESSO ===")
            messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("vdj_export_success_msg_detail", "Playlist exportada para o Virtual DJ!\n{num_tracks} músicas processadas.\n{hybrid_msg}\n\nArquivo: {output_file}").format(num_tracks=len(all_tracks), hybrid_msg=hybrid_msg, output_file=output_file))
            self.destroy() # Fecha a janela após o sucesso

        except Exception as e: # type: ignore
            self.update_status(self.txt.get("error_exporting_vdj_generic", "Erro na exportação: {error}").format(error=e), "red")
            messagebox.showerror(self.txt.get("error_export_title", "Erro de Exportação"), self.txt.get("error_generating_xml_vdj", "Não foi possível gerar o arquivo XML:\n{error}").format(error=e))

    def export_engine_playlist_info(self):
        """
        Exporta as informações detalhadas da playlist selecionada do Engine DJ para um arquivo JSON.
        Coleta as faixas de todos os bancos onde a playlist existe, unifica-as e salva em um arquivo JSON.
        """
        display_name = self.selected_playlist.get()
        sources = self.playlist_db_map.get(display_name)

        if not sources:
            messagebox.showerror("Erro", "Por favor, selecione uma playlist válida.")
            return # type: ignore
        
        dest_dir = os.path.join(self.manager.base_dir, "Reports")
        self.update_status(self.txt.get("status_extracting_playlist_info", "Extraindo informações da playlist '{playlist_name}'...").format(playlist_name=display_name), "blue")

        # Inicializa log para Extração de Info
        log_paths = self.manager.iniciar_log(
            dest_dir, "Engine Playlist Info", display_name, 
            self.manager.config.get("log", True), self.manager.config.get("debug", False), 
            tool_name="ENGINE_INFO")

        self.manager.log(log_paths, "=== INÍCIO DA EXTRAÇÃO DE INFORMAÇÕES DA PLAYLIST (JSON) ===")
        self.manager.log(log_paths, f"Playlist: {display_name}")
        
        all_tracks = []
        seen_paths = set()
        count_missing = 0
        count_duplicate = 0

        for db_path, pl_id in sources: # type: ignore
            self.manager.log(log_paths, f"Lendo banco: {db_path}", nivel="debug")
            # Agora buscamos pelo ID garantido para cada banco
            tracks = get_tracks_by_playlist_id(db_path, pl_id)
            self.manager.log(log_paths, f"  -> {len(tracks)} faixas encontradas.", nivel="debug")

            for track in tracks:
                title = track.get('title', 'Unknown')
                path_abs = track.get("caminho_absoluto")
                
                if not path_abs:
                    self.manager.log(log_paths, f"  [AVISO] Faixa '{title}' sem caminho.", nivel="debug")
                    continue

                norm_path = os.path.normcase(os.path.abspath(path_abs))

                if not os.path.exists(path_abs):
                    self.manager.log(log_paths, f"  [FALTANTE] Arquivo físico não encontrado: {path_abs}")
                    count_missing += 1
                    continue

                if norm_path in seen_paths:
                    self.manager.log(log_paths, f"  [SKIP] Duplicada ignorada: {title}", nivel="debug")
                    count_duplicate += 1
                    continue

                self.manager.log(log_paths, f"  [OK] Coletada: {title}", nivel="debug")
                all_tracks.append(track)
                seen_paths.add(norm_path)

        if not all_tracks:
            self.update_status(self.txt.get("no_tracks_found_in_playlist_vdj_export", "Nenhuma faixa encontrada em '{playlist_name}'.").format(playlist_name=display_name), "orange")
            messagebox.showinfo(self.txt.get("export_title", "Exportar"), self.txt.get("no_tracks_found_in_playlist_vdj_export", "Nenhuma faixa encontrada em '{playlist_name}'.").format(playlist_name=display_name))
            return

        try:
            # Obter o diretório base da aplicação (do SyncManager na janela principal, que é o master do master)
            base_dir = self.manager.base_dir
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

            self.manager.log(log_paths, f"JSON exportado com sucesso: {output_file_path}")
            self.manager.log(log_paths, "=== EXTRAÇÃO CONCLUÍDA ===")
            self.update_status(self.txt.get("exported_tracks_from_dbs_count", "Exportadas {num_tracks} faixas de {num_dbs} banco(s).").format(num_tracks=len(all_tracks), num_dbs=len(sources)), "green")
            messagebox.showinfo(
                self.txt.get("export_title", "Exportar"),
                self.txt.get("success_playlist_info_exported_detail_vdj").format(
                    playlist_name=display_name, num_tracks=len(all_tracks), output_file_path=output_file_path
                )
            )
        except Exception as e:
            if 'log_paths' in locals():
                self.manager.log(log_paths, f"Erro ao exportar JSON: {e}")
            self.update_status(self.txt.get("error_exporting_playlist_info", "Erro: {error}").format(error=e), "red")
            messagebox.showerror(self.txt.get("error_export_title", "Erro"), self.txt.get("error_exporting_playlist_info_detail", "{error}").format(error=e))

    def update_status(self, message, color="#AAAAAA"):
        """
        Atualiza o label de status na parte inferior da janela com uma mensagem e cor específicas.
        """
        self.lbl_status.configure(text=message, text_color=color)