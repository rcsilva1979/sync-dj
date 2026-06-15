import os
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import shutil
import threading
from collections import defaultdict
import unicodedata
from database_utils import (
    localizar_bancos_dados_engine, get_all_playlists_hierarchical, get_tracks_by_playlist_id, 
    update_track_path, get_track_id_by_path, update_playlist_entry_track
)
from engine_sync_app import get_resource_path, SyncManager
from constants import IS_WIN, IS_MAC

class RelocateLostTracksWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(self.txt["relocate_title"])
        self.geometry("650x700")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a1a")

        # Configuração de Ícone (Padrão multi-plataforma)
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

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Estado
        self.manager = SyncManager()
        self.selected_playlist = ctk.StringVar()
        self.playlist_db_map = defaultdict(list)
        self.search_folder = ctk.StringVar()
        self.relocate_mode = ctk.StringVar(value="relocate")
        self.fuzzy_action = ctk.StringVar(value="") # Nenhuma ação fuzzy selecionada por padrão
        self.just_verify = ctk.BooleanVar(value=False)
        self.found_databases = localizar_bancos_dados_engine()

        self.construir_ui()
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        self.relocate_mode.trace_add("write", self._handle_relocate_mode_change) # Adiciona o trace para controlar as sub-opções
        self.carregar_playlists()

    def construir_ui(self):
        # Logo Superior
        img_carregada = False
        try:
            logo_path = get_resource_path(os.path.join("images", "logo_engine_relocate.png"))
            if os.path.exists(logo_path):
                logo_img = ctk.CTkImage(Image.open(logo_path), size=(500, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(15, 5))
                img_carregada = True
        except:
            pass

        if not img_carregada:
            lbl_title = ctk.CTkLabel(self, text=self.txt["relocate_title"].upper(), font=ctk.CTkFont(size=22, weight="bold"), text_color="#F39C12")
            lbl_title.pack(pady=(20, 10))

        # Label Informativo unificado seguindo o padrão do Mirror Sync
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_db_auto.pack(pady=(0, 5), padx=40)

        # Seleção de Playlist
        frame_pl = ctk.CTkFrame(self, fg_color="transparent")
        frame_pl.pack(padx=40, pady=5, fill="x")
        
        ctk.CTkLabel(frame_pl, text=self.txt["playlist"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        self.combo_playlist = ctk.CTkComboBox(frame_pl, variable=self.selected_playlist, values=[], width=450, state="disabled")
        self.combo_playlist.pack(pady=2, fill="x")

        # Pasta de Busca
        frame_search = ctk.CTkFrame(self, fg_color="transparent")
        frame_search.pack(padx=40, pady=5, fill="x")
        
        ctk.CTkLabel(frame_search, text=self.txt["search_folder_label"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        entry_search = ctk.CTkEntry(frame_search, textvariable=self.search_folder, width=350)
        entry_search.pack(side="left", pady=2, fill="x", expand=True, padx=(0, 10))
        
        btn_browse = ctk.CTkButton(frame_search, text=self.txt["browse"], width=100, fg_color="#F39C12", text_color="#000000", hover_color="#D68910", command=self.procurar_pasta_busca)
        btn_browse.pack(side="right", pady=2)

        # Opções de Modo (Alertar, Copiar, Relocar)
        frame_mode = ctk.CTkFrame(self, fg_color="transparent")
        frame_mode.pack(padx=40, pady=5, fill="x")
        
        ctk.CTkLabel(frame_mode, text=self.txt["relocate_mode_label"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        self.r_copy = ctk.CTkRadioButton(frame_mode, text=self.txt["relocate_mode_copy"], variable=self.relocate_mode, value="copy", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_copy.pack(anchor="w", pady=2)
        
        self.r_update = ctk.CTkRadioButton(frame_mode, text=self.txt["relocate_mode_update"], variable=self.relocate_mode, value="relocate", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_update.pack(anchor="w", pady=2)

        self.r_fuzzy = ctk.CTkRadioButton(frame_mode, text=self.txt.get("fuzzy_search_label", "Busca inteligente (Arquivos renomeados)"), variable=self.relocate_mode, value="fuzzy", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_fuzzy.pack(anchor="w", pady=2)

        # Sub-opções da Busca Inteligente
        self.frame_fuzzy_ops = ctk.CTkFrame(frame_mode, fg_color="transparent")
        self.frame_fuzzy_ops.pack(anchor="w", fill="x")
        
        self.r_f_rename = ctk.CTkRadioButton(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_rename", "Renomear arquivo (Se na mesma pasta)"), 
                                           variable=self.fuzzy_action, value="rename", font=ctk.CTkFont(size=10))
        self.r_f_rename.pack(anchor="w", padx=35, pady=1)

        self.r_f_copy = ctk.CTkRadioButton(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_copy", "Copiar arquivo para o local antigo"), 
                                         variable=self.fuzzy_action, value="copy", font=ctk.CTkFont(size=10))
        self.r_f_copy.pack(anchor="w", padx=35, pady=1)

        self.r_f_move = ctk.CTkRadioButton(self.frame_fuzzy_ops, text=self.txt.get("fuzzy_action_move", "Mover arquivo para o local antigo"), 
                                         variable=self.fuzzy_action, value="move", font=ctk.CTkFont(size=10))
        self.r_f_move.pack(anchor="w", padx=35, pady=1)

        # Checkbox: Apenas Verificar
        self.check_verify = ctk.CTkCheckBox(
            frame_mode, 
            text=self.txt.get("relocate_just_verify_label", "Apenas Verificar (Sem alteração)"),
            variable=self.just_verify,
            font=ctk.CTkFont(size=12),
            fg_color="#F39C12", hover_color="#D68910"
        )
        self.check_verify.pack(anchor="w", pady=(5, 5))

        # Botão: Listar Músicas Faltantes
        self.btn_view_missing = ctk.CTkButton(
            self,
            text=self.txt["view_tracks_btn"],
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#555555", text_color="#FFFFFF", hover_color="#777777",
            height=40, width=350,
            command=self.listar_musicas_faltantes
        )
        self.btn_view_missing.pack(pady=(5, 0))

        # Ação
        self.btn_action = ctk.CTkButton(
            self,
            text=self.txt["relocate_btn_action"],
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#F39C12", text_color="#000000", hover_color="#D68910",
            height=40, width=350,
            command=self.iniciar_relocacao
        )
        self.btn_action.pack(pady=15)

        # Progresso e Status
        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#F39C12")
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="#AAAAAA")
        self.lbl_status.pack(pady=5)

    def _handle_relocate_mode_change(self, *args):
        """Define a ação padrão da busca inteligente quando o modo é selecionado/desselecionado."""
        if self.relocate_mode.get() == "fuzzy":
            self.fuzzy_action.set("rename") # Seleciona "Renomear" por padrão quando "Busca Inteligente" é escolhido
        else:
            self.fuzzy_action.set("") # Limpa a seleção das sub-opções quando outro modo é escolhido

    def procurar_pasta_busca(self):
        pasta = filedialog.askdirectory()
        if pasta:
            self.search_folder.set(os.path.normpath(pasta))

    def carregar_playlists(self):
        if not self.found_databases:
            self.lbl_status.configure(text=self.txt.get("error_db", "Database error"), text_color="#FF5555")
            return

        self.playlist_db_map = defaultdict(list)
        for path in self.found_databases:
            if not os.path.exists(path): continue
            results = get_all_playlists_hierarchical(path)
            for pl_path, pl_id in results:
                self.playlist_db_map[pl_path].append((path, pl_id))

        all_playlists = sorted(list(self.playlist_db_map.keys()))
        if all_playlists:
            self.combo_playlist.configure(values=all_playlists, state="normal")
            self.selected_playlist.set(all_playlists[0])
            self.combo_playlist.set(all_playlists[0])
            self.atualizar_label_drives()
        else:
            self.combo_playlist.configure(values=[], state="disabled")
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")

    def _get_vol_id(self, path):
        """Helper para identificar o 'Drive' no Win ou 'Volume' no Mac."""
        if not path: return ""
        abs_p = os.path.abspath(path)
        if IS_WIN:
            return os.path.splitdrive(abs_p)[0].upper()
        else:
            p = abs_p.split(os.sep)
            return p[2] if len(p) > 2 and p[1] == 'Volumes' else 'System'

    def atualizar_label_drives(self):
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {self._get_vol_id(db) for db in dbs_com_playlist}
        drives_totais = sorted(list({self._get_vol_id(d) for d in self.found_databases}))
        
        texto_drives = " | ".join([
            f"[{d}]" if d in drives_com_playlist else d 
            for d in drives_totais
        ])
        status_text = f"✔ {self.txt.get('engine_dbs_detected', 'Bancos detectados').format(count=len(self.found_databases))}: {texto_drives}"
        self.lbl_db_auto.configure(text=status_text, text_color="#00E5A3")

    def listar_musicas_faltantes(self):
        pl_nome = self.selected_playlist.get()
        if not pl_nome: return

        db_pl_pairs = self.playlist_db_map.get(pl_nome)
        if not db_pl_pairs: return

        # Janela de visualização
        viewer = ctk.CTkToplevel(self)
        viewer.title(f"Músicas Faltantes: {pl_nome}")
        viewer.geometry("800x600")
        viewer.transient(self)
        viewer.grab_set()

        lbl_header = ctk.CTkLabel(viewer, text=f"Músicas Faltantes em: {pl_nome}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_header.pack(pady=10)

        textbox = ctk.CTkTextbox(viewer, width=760, height=500, font=ctk.CTkFont(family="Consolas", size=11))
        textbox.pack(padx=20, pady=(0, 20), fill="both", expand=True)

        total_missing_global = 0
        for db_path, pl_id in db_pl_pairs:
            drive = self._get_vol_id(db_path)
            textbox.insert("end", f"--- DRIVE {drive} ---\n")
            tracks = get_tracks_by_playlist_id(db_path, pl_id)
            missing = [t for t in tracks if not os.path.exists(t.get("caminho_absoluto", ""))]
            
            if not missing:
                textbox.insert("end", "Todas as músicas localizadas neste drive.\n\n")
                continue
            
            total_missing_global += len(missing)
            for t in missing:
                artist = t.get('artist') or "Unknown"
                title = t.get('title') or "Untitled"
                textbox.insert("end", f"FAIXA: {artist} - {title}\n")
                textbox.insert("end", f"  Path: {t.get('caminho_absoluto')}\n\n")
            
        if total_missing_global == 0:
            textbox.insert("end", "Nenhuma música faltante encontrada em nenhum drive.")
        textbox.configure(state="disabled")

    def iniciar_relocacao(self):
        # Verifica se o Engine DJ está aberto (mesma lógica e mensagens do Mirror Sync)
        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."
            )
            return

        pl_nome = self.selected_playlist.get()
        busca_dir = self.search_folder.get()

        if not busca_dir or not pl_nome:
            messagebox.showwarning("Aviso", self.txt["error_paths"])
            return

        db_pl_pairs = self.playlist_db_map.get(pl_nome)
        if not db_pl_pairs: return

        def normalizar_nome(texto):
            """Normaliza caracteres acentuados e uniformiza espaços para busca robusta."""
            if not texto: return ""
            # Remove acentos, converte para minúsculas e remove a extensão para comparação parcial
            texto_norm = unicodedata.normalize('NFD', str(texto).lower())
            texto_norm = "".join([c for c in texto_norm if not unicodedata.combining(c)])
            # Remove espaços extras (múltiplos espaços viram um só) e strip
            texto_norm = " ".join(texto_norm.split())
            return os.path.splitext(texto_norm)[0]

        current_mode = self.relocate_mode.get()
        dry_run = self.just_verify.get()
        fuzzy_act_val = self.fuzzy_action.get()

        # Define o rótulo da ação principal baseado no modo selecionado para o relatório
        main_action_label = self.txt.get("relocate_mode_copy", "Restaurar") if current_mode == "copy" else \
                           (self.txt.get("fuzzy_search_label", "Busca Inteligente") if current_mode == "fuzzy" else \
                            self.txt.get("relocate_mode_update", "Atualizar Banco"))
        self.btn_action.configure(state="disabled")
        self.btn_view_missing.configure(state="disabled")
        self.combo_playlist.configure(state="disabled")
        
        # Inicializa caminhos de log
        log_paths = self.manager.iniciar_log(
            busca_dir, "Multi-DB Relocate", pl_nome, 
            self.manager.config.get("log", True), self.manager.config.get("debug", False), 
            tool_name="RELOCATE")

        def task():
            total_tracks_all = 0
            total_missing_all = 0
            total_relocated_all = 0
            skipped_duplicate = 0
            skipped_different_drive = 0
            report_lines = []

            self.manager.log(log_paths, f"--- INÍCIO DA RELOCAÇÃO [{pl_nome}] ---")
            self.manager.log(log_paths, f"Pasta de busca: {busca_dir}")
            self.manager.log(log_paths, f"Modo selecionado: {current_mode}")
            if dry_run: self.manager.log(log_paths, "!!! MODO VERIFICAÇÃO ATIVO - NENHUMA ALTERAÇÃO SERÁ FEITA !!!")

            # 1. Indexar a pasta de busca
            self.manager.log(log_paths, f"Iniciando mapeamento recursivo em: {busca_dir}")
            self.after(0, lambda: [self.lbl_status.configure(text=self.txt["status_searching_files"]), self.progress_bar.set(0)])
            
            file_index = defaultdict(list)
            size_index = defaultdict(list)
            
            for raiz, diretorios, arquivos in os.walk(busca_dir):
                # Pula pastas ocultas (ex: .trash) e de sistema para melhor performance
                diretorios[:] = [d for d in diretorios if not d.startswith('.') and not d.startswith('$')]
                for f in arquivos:
                    if f.startswith('.'): continue # Pula arquivos ocultos do Mac
                    
                    f_path = os.path.join(raiz, f)
                    key = normalizar_nome(f)
                    if key:
                        file_index[key].append(f_path)
                        try:
                            f_size = os.path.getsize(f_path)
                            size_index[f_size].append(f_path)
                        except: pass

            total_indexado = sum(len(v) for v in file_index.values())
            self.manager.log(log_paths, f"[INDEX] {total_indexado} arquivo(s) mapeados (Nomes e Tamanhos).")
            
            if total_indexado == 0:
                self.manager.log(log_paths, "[AVISO] Nenhum arquivo foi encontrado na pasta selecionada. Verifique as permissões de acesso.")

            # 2. Processar cada banco
            for db_path, pl_id in db_pl_pairs:
                drive = self._get_vol_id(db_path)
                report_lines.append(f"\n[BANCO DRIVE {drive}] {db_path}\n" + "="*50 + "\n")
                
                self.after(0, lambda d=drive: self.lbl_status.configure(text=f"[{d}] " + self.txt["status_scanning_missing"]))
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                missing_tracks = [t for t in tracks if not os.path.exists(t.get("caminho_absoluto", ""))]
                
                self.manager.log(log_paths, f"\n[BANCO] Processando: {db_path}")
                self.manager.log(log_paths, f"[INFO] {len(missing_tracks)} faixas marcadas como 'missing' na playlist.")

                total_tracks_all += len(tracks)
                total_missing_all += len(missing_tracks)

                if not missing_tracks and not self.manager.config.get("debug", False): # Não loga se não há missing e não está em debug
                    continue

                engine_library_parent = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))

                for i, track in enumerate(missing_tracks):
                    fname = track.get("filename")
                    if not fname: continue
                    artist_title = f"{track.get('artist', 'Desconhecido')} - {track.get('title', 'Sem Título')}"
                    track_id = track.get("id")
                    entry_id = track.get("entry_id")
                    track_size = track.get("fileBytes")
                    caminho_esperado = track.get("caminho_absoluto")
                    
                    self.manager.log(log_paths, f"  [BUSCANDO] {fname} (ID: {track_id})", nivel="debug")
                    
                    progress = (i + 1) / len(missing_tracks)
                    self.after(0, lambda p=progress, f=fname, d=drive: [
                        self.progress_bar.set(p),
                        self.lbl_status.configure(text=f"[{d}] " + self.txt["status_relocating"].format(filename=f))
                    ])

                    found_paths = []
                    match_type = "Exato"
                    search_key = normalizar_nome(fname) # Nome do arquivo que está no banco (sem extensão)
                    
                    # 1. Tentativa por nome exato (mais rápido)
                    if search_key in file_index:
                        found_paths = file_index[search_key]
                    
                    # 2. Busca Inteligente (Tamanho + Nome Parcial) 
                    # Agora a busca inteligente funciona em qualquer modo se o nome exato falhar, 
                    # mas o rótulo da ação respeita a UI
                    if not found_paths and track_size and track_size in size_index:
                        for cand_path in size_index[track_size]:
                            cand_name = normalizar_nome(os.path.basename(cand_path))
                            # Se o tamanho bate e o nome original está contido no novo (ou vice-versa)
                            if search_key in cand_name or cand_name in search_key:
                                found_paths.append(cand_path)
                                match_type = "Fuzzy"

                    if found_paths:
                        report_item = [f"MÚSICA: {fname}"]
                        self.manager.log(log_paths, f"  [BUSCA] '{artist_title}' (ID: {track_id})", nivel="debug")
                        self.manager.log(log_paths, f"  [FOLDER MATCH] Arquivo localizado na pasta de busca ({len(found_paths)} ocorrência(s)).")

                        # Tenta encontrar no mesmo drive/volume (Obrigatório para Engine DJ)
                        found_somewhere = True
                        novo_caminho_abs = None
                        
                        # Prioridade 1: Arquivo na MESMA PASTA (Crucial para a estratégia de Renomeação)
                        target_dir_abs = os.path.normpath(os.path.dirname(os.path.abspath(caminho_esperado))).lower()
                        for path_found in found_paths:
                            if os.path.normpath(os.path.dirname(os.path.abspath(path_found))).lower() == target_dir_abs:
                                novo_caminho_abs = path_found
                                break
                        
                        # Prioridade 2: Primeiro arquivo encontrado no mesmo Drive/Volume
                        if not novo_caminho_abs:
                            db_vol = self._get_vol_id(db_path)
                            for path_found in found_paths:
                                if self._get_vol_id(path_found) == db_vol:
                                    novo_caminho_abs = path_found
                                    break
                        
                        # Se a ação for restaurar/mover para o local antigo, permite buscar o arquivo em outro disco
                        permitir_outro_disco = current_mode == "copy" or (current_mode == "fuzzy" and fuzzy_act_val in ["copy", "move"])
                        if not novo_caminho_abs and found_somewhere and permitir_outro_disco:
                            novo_caminho_abs = found_paths[0]

                        if novo_caminho_abs:
                            try:
                                nome_no_disco = os.path.basename(novo_caminho_abs)
                                if match_type == "Fuzzy":
                                    report_item.append(f"  Status: ENCONTRADO COM NOME DIFERENTE")
                                    report_item.append(f"  ↳ Nome no Banco: {fname}")
                                    report_item.append(f"  ↳ Nome no Disco: {nome_no_disco}")
                                else:
                                    report_item.append(f"  Status: Localizado em {novo_caminho_abs}")
                                
                                if current_mode == "fuzzy":
                                    if fuzzy_act_val == "copy":
                                        report_item.append(f"  Ação: Copiar arquivo para o local antigo")
                                        report_item.append(f"  Origem:  {novo_caminho_abs}")
                                        report_item.append(f"  Alvo:    {caminho_esperado}")
                                        if not dry_run:
                                            try:
                                                os.makedirs(os.path.dirname(caminho_esperado), exist_ok=True)
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.copy2(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [COPIADO] '{artist_title}' para local original: {caminho_esperado}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                            except Exception as e:
                                                self.manager.log(log_paths, f"  [ERRO] Falha ao copiar: {e}")

                                    elif fuzzy_act_val == "move":
                                        same_dir = os.path.dirname(os.path.abspath(novo_caminho_abs)) == os.path.dirname(os.path.abspath(caminho_esperado))
                                        if not same_dir: # Só move se for uma pasta diferente
                                            report_item.append(f"  Ação: Mover para local original")
                                            report_item.append(f"  Origem:  {novo_caminho_abs}")
                                            report_item.append(f"  Alvo:    {caminho_esperado}")
                                            if not dry_run:
                                                os.makedirs(os.path.dirname(caminho_esperado), exist_ok=True)
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.move(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [MOVIDO] '{artist_title}' para local original: {caminho_esperado}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                        else:
                                            report_item.append(f"  Aviso: Mover ignorado (Já na mesma pasta).")
                                            report_item.append(f"  Pasta Atual: {os.path.dirname(novo_caminho_abs)}")
                                            report_item.append(f"  Pasta Alvo:  {os.path.dirname(caminho_esperado)}")
                                            
                                    elif fuzzy_act_val == "rename":
                                        same_dir = os.path.dirname(os.path.abspath(novo_caminho_abs)) == os.path.dirname(os.path.abspath(caminho_esperado))
                                        if same_dir:
                                            report_item.append(f"  Ação: Renomear arquivo (Mesma pasta)")
                                            report_item.append(f"  De:   {nome_no_disco}")
                                            report_item.append(f"  Para: {fname}")
                                            if not dry_run:
                                                if not os.path.exists(caminho_esperado):
                                                    shutil.move(novo_caminho_abs, caminho_esperado)
                                                    self.manager.log(log_paths, f"  [RENOMEADO] '{nome_no_disco}' para '{fname}' em {os.path.dirname(caminho_esperado)}")
                                                update_track_path(db_path, track_id, track.get("path"))
                                                total_relocated_all += 1
                                        else:
                                            report_item.append(f"  Aviso: Renomear ignorado (Pastas diferentes).")
                                            report_item.append(f"  Pasta Atual: {os.path.dirname(novo_caminho_abs)}")
                                            report_item.append(f"  Pasta Alvo:  {os.path.dirname(caminho_esperado)}")

                                elif current_mode == "relocate":
                                    novo_rel_path = self.manager.formatar_caminho_engine(novo_caminho_abs, db_path)
                                    report_item.append(f"  Ação: Relocar (Atualizar Banco)")
                                    report_item.append(f"  Caminho Antigo: {caminho_esperado}")
                                    report_item.append(f"  Caminho Novo:   {novo_rel_path}")
                                    
                                    existing_id = get_track_id_by_path(db_path, novo_rel_path)
                                    if existing_id and existing_id != track_id:
                                        if dry_run: report_item.append("  Nota: Será vinculada à ID duplicada existente no banco.")
                                        self.manager.log(log_paths, f"  [DUPLICATA] '{artist_title}' já existe no banco (ID {existing_id}).")
                                        if not dry_run and entry_id and update_playlist_entry_track(db_path, entry_id, existing_id):
                                            total_relocated_all += 1
                                    else:
                                        self.manager.log(log_paths, f"  [RELOCADO] '{artist_title}' (ID: {track_id}) -> {novo_rel_path}")
                                        if not dry_run and update_track_path(db_path, track_id, novo_rel_path):
                                            total_relocated_all += 1

                                elif current_mode == "copy":
                                    dest_abs = track.get("caminho_absoluto")
                                    report_item.append(f"  Ação: Restaurar Arquivo (Copiar)")
                                    report_item.append(f"  Origem:  {novo_caminho_abs}")
                                    report_item.append(f"  Destino: {dest_abs}")
                                    if dest_abs:
                                        self.manager.log(log_paths, f"  [COPIADO] '{artist_title}' de '{novo_caminho_abs}' para '{dest_abs}'")
                                        if not dry_run:
                                            dest_dir = os.path.dirname(dest_abs)
                                            if not os.path.exists(dest_dir):
                                                os.makedirs(dest_dir, exist_ok=True)
                                            shutil.copy2(novo_caminho_abs, dest_abs)
                                            total_relocated_all += 1
                                
                                if dry_run: total_relocated_all += 1
                            except Exception as e:
                                self.manager.log(log_paths, f"  [ERRO TÉCNICO] Track {track_id}: {str(e)}", nivel="debug")
                                report_item.append(f"  [ERRO] Falha ao executar ação: {str(e)}")
                        elif found_somewhere:
                            report_item.append(f"  Status: Encontrado em outro disco ({found_paths[0]})")
                            report_item.append(f"  Caminho esperado: {caminho_esperado}")
                            self.manager.log(log_paths, f"  [AVISO] '{fname}' ignorado: está em disco diferente do banco e a ação selecionada não permite restauração entre discos.")
                            skipped_different_drive += 1

                        # Garante que o item seja adicionado ao relatório, independentemente de ter sido processado ou ignorado
                        report_lines.append("\n".join(report_item) + "\n" + "-"*40 + "\n")
                    else:
                        self.manager.log(log_paths, f"  [NÃO ENCONTRADO] '{fname}' não localizado na pasta de busca.", nivel="debug")
                        report_lines.append(f"MÚSICA: {fname}\n  Status: NÃO ENCONTRADO na pasta de busca\n  Caminho esperado: {caminho_esperado}\n" + "-"*40 + "\n")

            self.manager.log(log_paths, f"\n--- FIM DO PROCESSO ---\nRelocados: {total_relocated_all}\nNão encontrados: {total_missing_all - total_relocated_all}")
            
            final_report = "".join(report_lines)
            self.after(0, lambda: self.finalizar_processo(total_tracks_all, total_missing_all, total_relocated_all, skipped_duplicate, skipped_different_drive, log_paths, final_report, dry_run))

        threading.Thread(target=task, daemon=True).start()

    def finalizar_processo(self, total, missing, relocated, duplicates=0, diff_drive=0, log_paths=None, report="", is_dry_run=False):
        self.btn_action.configure(state="normal")
        self.btn_view_missing.configure(state="normal")
        self.combo_playlist.configure(state="normal")
        self.progress_bar.set(1.0)
        self.lbl_status.configure(text=self.txt["status_done"])

        if missing == 0:
            messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("error_no_missing_found", "Todas as músicas desta playlist foram localizadas no disco!"))
            return
        
        # Abre o relatório detalhado automaticamente ao final
        self._abrir_janela_relatorio(self.selected_playlist.get(), report, is_dry_run)
        
    def _abrir_janela_relatorio(self, playlist_name, content, is_dry_run=False):
        viewer = ctk.CTkToplevel(self)
        title_prefix = "RELATÓRIO DE VERIFICAÇÃO" if is_dry_run else "RELATÓRIO DE EXECUÇÃO"
        viewer.title(f"{title_prefix}: {playlist_name}")
        viewer.geometry("900x700")
        viewer.transient(self)
        viewer.grab_set()

        lbl_header = ctk.CTkLabel(viewer, text=f"{title_prefix}\nPlaylist: {playlist_name}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_header.pack(pady=10)

        textbox = ctk.CTkTextbox(viewer, width=860, height=600, font=ctk.CTkFont(family="Consolas", size=11))
        textbox.pack(padx=20, pady=(0, 20), fill="both", expand=True)
        
        textbox.insert("end", content)
        textbox.configure(state="disabled")