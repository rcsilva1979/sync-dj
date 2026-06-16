import os
import sys
import customtkinter as ctk
from PIL import Image, ImageTk
from tkinter import messagebox
from collections import defaultdict
from pathlib import Path
import sqlite3
import threading
from datetime import datetime

# Importações do projeto
from database_utils import localizar_bancos_dados_engine, get_all_playlists_hierarchical, get_tracks_by_playlist_id
from engine_sync_app import get_resource_path, SyncManager
from le_json import read_mp3
from constants import (IS_WIN, IS_MAC, VERSAO_ATUAL, APP_NAME,
                       FONT_FAMILY, COLOR_BG_DARK,
                       COLOR_TEXT_NORMAL, COLOR_TEXT_MUTED,
                       COLOR_SWITCH_OFF, CORNER_RADIUS_NONE)
from hotcue_normalizer import normalize_hotcues
from engine_hotcues import format_time, parse_quick_cues, CueWrite, encode_quick_cues
from report_gui import ReportWindow

class MixedInKeyWindow(ctk.CTkToplevel):
    """
    Janela da ferramenta para sincronizar hotcues do Mixed In Key (lidos de tags MP3)
    com o banco de dados do Engine DJ.
    Permite ao usuário listar hotcues existentes e importar novos, com opção de sobrescrever.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master
        """Inicializa a janela da ferramenta Mixed In Key Hotcue Sync."""

        self.title(f"{self.txt.get('mik_sync_title', 'Mixed In Key Hotcue Sync')} ({VERSAO_ATUAL})")
        self.geometry("650x620")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        # Garante foco e modalidade
        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Instância do SyncManager para gerenciar operações de backend e configurações.
        self.manager = SyncManager()
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
        # Variável booleana para controlar a opção de sobrescrever hotcues existentes.
        self.sobrescrever_hotcue = ctk.BooleanVar(value=False)
        # Lista de caminhos para todos os bancos de dados Engine DJ encontrados no sistema.
        self.found_databases = localizar_bancos_dados_engine()
        # Mapeamento de caminhos de playlist para uma lista de tuplas (caminho_db, playlist_id).
        self.playlist_db_map = defaultdict(list)

        self.construir_ui()
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        self.carregar_playlists()

    def construir_ui(self):
        """Cria e organiza todos os elementos da interface gráfica da janela Mixed In Key."""
        # Logo Superior
        img_carregada = False
        try:
            logo_path = get_resource_path(os.path.join("images", "syncDJ_MixedinKey.png"))
            if os.path.exists(logo_path):
                img_obj = Image.open(logo_path)
                logo_img = ctk.CTkImage(light_image=img_obj, dark_image=img_obj, size=(500, 110))
                lbl_logo = ctk.CTkLabel(self, text="", image=logo_img)
                lbl_logo.pack(pady=(25, 10))
                img_carregada = True
        except Exception as e:
            print(f"Erro ao carregar logo MIK: {e}")
            pass

        if not img_carregada:
            # Fallback para o título se a imagem do logo não puder ser carregada.
            lbl_title = ctk.CTkLabel(self, text=self.txt.get("mik_sync_title", "MIXED IN KEY HOTCUE SYNC").upper(), font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"), text_color="#3498DB")
            lbl_title.pack(pady=(30, 15))

        # Label Informativo unificado seguindo o padrão do Mirror Sync
        # Exibe o status da detecção automática do banco de dados.
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=COLOR_TEXT_MUTED)
        self.lbl_db_auto.pack(pady=(5, 10), padx=40)
        # Label para a seleção da playlist.

        # Seleção de Playlist
        lbl_playlist = ctk.CTkLabel(self, text=self.txt.get("select_playlist_full_path", "Select Playlist:"), font=ctk.CTkFont(family=FONT_FAMILY, weight="bold"))
        lbl_playlist.pack(pady=(15, 5))

        self.combo_playlist = ctk.CTkComboBox(
            self,
            variable=self.selected_playlist,
            values=[],
            width=500,
            height=35,
            state="disabled",
            corner_radius=CORNER_RADIUS_NONE,
            font=ctk.CTkFont(family=FONT_FAMILY)
        )
        self.combo_playlist.pack(pady=5)

        # Switch para controlar a opção de sobrescrever hotcues existentes.
        # Switch: Sobrescrever
        self.check_overwrite = ctk.CTkSwitch( # Alterado de CTkCheckBox para CTkSwitch
            self,
            text=self.txt.get("hotcue_overwrite", "Sobrescrever hotcues").strip().replace("↳", "").strip(),
            variable=self.sobrescrever_hotcue,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=COLOR_SWITCH_OFF, progress_color="#3498DB"
        )
        self.check_overwrite.pack(pady=10)

        # Botão para listar as músicas e seus hotcues (lidos das tags MP3).
        # Botão de Listagem
        self.btn_list = ctk.CTkButton(
            self,
            text=self.txt.get("mik_list_btn", "List Songs and Hotcues (Tags)"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), corner_radius=CORNER_RADIUS_NONE,
            fg_color=COLOR_SWITCH_OFF, hover_color="#777777",
            height=40, width=350,
            command=self.listar_musicas_hotcues
        )
        self.btn_list.pack(pady=(10, 0))

        # Botão principal para iniciar a importação dos hotcues.
        # Botão de Ação
        self.btn_import = ctk.CTkButton(
            self,
            text=self.txt.get("mik_import_btn_action", "Start Tag Import"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"), corner_radius=CORNER_RADIUS_NONE,
            fg_color="#3498DB", hover_color="#2980B9",
            height=50, width=350,
            command=self.iniciar_importacao
        )
        self.btn_import.pack(pady=30)

        # Barra de progresso para indicar o andamento da operação.
        # Barra de Progresso
        self.progress_bar = ctk.CTkProgressBar(self, width=500, height=12, progress_color="#3498DB", corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(pady=(0, 10))
        self.progress_bar.set(0)

        # Rodapé com informações do aplicativo (agora como o primeiro 'bottom', ficando na base)
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side="bottom", pady=(5, 10))

        # Label para exibir mensagens de status ao usuário.
        # Status Label
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color="#3498DB")
        self.lbl_status.pack(side="bottom", pady=(0, 10))

    def carregar_playlists(self):
        """
        Carrega as playlists de todos os bancos de dados Engine DJ detectados e popula o ComboBox de playlists.
        """
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
            self.combo_playlist.set(all_playlists[0]) # Define o valor inicial do combobox
            self.atualizar_label_drives()
        else:
            self.combo_playlist.configure(values=[], state="disabled")
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")

    def atualizar_label_drives(self):
        """
        Atualiza o label que exibe os drives detectados, destacando aqueles que contêm a playlist selecionada.
        """
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {self.manager._get_vol_id(db) for db in dbs_com_playlist}

        drives_totais = sorted(list({self.manager._get_vol_id(d) for d in self.found_databases}))
        
        # Monta a string de drives destacando os que contêm a playlist (ex: [C:] | D:)
        texto_drives = " | ".join([
            f"[{d}]" if d in drives_com_playlist else d 
            for d in drives_totais
        ])

        status_text = f"✔ {self.txt.get('engine_dbs_detected', 'Bancos detectados').format(count=len(self.found_databases))}: {texto_drives}"
        self.lbl_db_auto.configure(text=status_text, text_color="#00E5A3")

    def listar_musicas_hotcues(self):
        """
        Lista as músicas da playlist selecionada e seus hotcues lidos das tags MP3.
        Abre uma nova janela para exibir o relatório detalhado.
        """
        playlist_name = self.selected_playlist.get()
        if not playlist_name:
            messagebox.showwarning("Aviso", "Por favor, selecione uma playlist.")
            return

        db_pl_pairs = self.playlist_db_map.get(playlist_name)
        if not db_pl_pairs:
            return

        # UI feedback inicial
        self.btn_list.configure(state="disabled")
        self.btn_import.configure(state="disabled")
        self.combo_playlist.configure(state="disabled")
        self.progress_bar.set(0)
        self.lbl_status.configure(text=self.txt.get("status_counting", "Calculando..."), text_color="#3498DB")

        def task_list():
            total_tracks = 0
            # Conta o total de faixas primeiro (consultas ao banco são rápidas)
            for db_path, pl_id in db_pl_pairs:
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                total_tracks += len(tracks)

            if total_tracks == 0:
                self.after(0, lambda: [
                    self.btn_list.configure(state="normal"),
                    self.btn_import.configure(state="normal"),
                    self.combo_playlist.configure(state="normal"),
                    self.lbl_status.configure(text=self.txt.get("no_tracks_found_generic", "Nenhuma música encontrada."))
                ])
                return

            all_report_lines = []
            processed = 0
            for db_path, pl_id in db_pl_pairs:
                drive = self.manager._get_vol_id(db_path)
                all_report_lines.append(f"--- BANCO DETECTADO NO DRIVE {drive} ---\n")
                
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                
                for t in tracks:
                    processed += 1
                    progress = processed / total_tracks
                    title_track = t.get('title', '...')
                    # Atualiza progresso e status na janela principal
                    self.after(0, lambda p=progress, m=title_track, d=drive: [
                        self.progress_bar.set(p),
                        self.lbl_status.configure(text=f"[{d}] Lendo: {m}")
                    ])

                    artist = t.get('artist', self.txt.get('unknown_artist', 'Desconhecido'))
                    title = t.get('title', self.txt.get('untitled_track', 'Sem Título'))
                    filename = t.get('filename', self.txt.get('not_found', 'Não localizada'))
                    filepath = t.get("caminho_absoluto")

                    lines = [
                        f"FAIXA: {artist} - {title}\n",
                        f"  {self.txt.get('mik_filename_label', 'Nome do Arquivo:')} {filename}\n",
                        f"  {self.txt.get('mik_location_label', 'Localização:')} {filepath}\n"
                    ]
                    
                    if filepath and os.path.exists(filepath) and filepath.lower().endswith(".mp3"):
                        try:
                            mp3_data = read_mp3(Path(filepath))
                            hotcues = normalize_hotcues(mp3_data.get("hotcues", []))
                            if hotcues:
                                header_left = self.txt.get('mik_hotcue_left_col_header', 'Hotcues (1-4)')
                                header_right = self.txt.get('mik_hotcue_right_col_header', 'Hotcues (5-8)')
                                lines.append(f"  ↳ [TAG] {header_left:<40} {header_right}\n")
                                lines.append(f"  {'-'*45} {'-'*45}\n")

                                hotcues_left = hotcues[:4]
                                hotcues_right = hotcues[4:8]
                                max_cues = max(len(hotcues_left), len(hotcues_right))
                                for i in range(max_cues):
                                    l_info = f"Cue {hotcues_left[i].get('num')}: {hotcues_left[i].get('name', '')} @ {format_time(hotcues_left[i].get('pos_seconds'))}" if i < len(hotcues_left) else ""
                                    r_info = f"Cue {hotcues_right[i].get('num')}: {hotcues_right[i].get('name', '')} @ {format_time(hotcues_right[i].get('pos_seconds'))}" if i < len(hotcues_right) else ""
                                    lines.append(f"  {l_info:<45} {r_info}\n")
                            else:
                                lines.append(f"  ↳ [TAG] {self.txt.get('mik_no_hotcues_found', 'Nenhum Hotcue encontrado na tag MP3.')}\n")
                        except Exception as e:
                            lines.append(f"  ↳ [ERRO] {self.txt.get('mik_error_reading_hotcues', 'Falha ao ler hotcues:')} {str(e)}\n")
                    else:
                        lines.append(f"  ↳ [INFO] {self.txt.get('mik_detection_info', 'Detecção disponível apenas para arquivos MP3 locais.')}\n")
                    
                    lines.append("-" * 40 + "\n")
                    all_report_lines.extend(lines)
                
                all_report_lines.append("\n")

            report_text = "".join(all_report_lines)
            self.after(0, lambda: [
                self.btn_list.configure(state="normal"),
                self.btn_import.configure(state="normal"),
                self.combo_playlist.configure(state="normal"),
                self.progress_bar.set(1.0),
                self.lbl_status.configure(text=self.txt.get("status_done", "Concluído"), text_color="#00E5A3"),
                self._abrir_janela_relatorio(playlist_name, report_text)
            ])

        threading.Thread(target=task_list, daemon=True).start()

    def _abrir_janela_relatorio(self, playlist_name, content):
        """
        Abre uma nova janela para exibir o relatório detalhado das músicas e hotcues processados.
        """
        ReportWindow(
            self,
            title=f"Músicas e Hotcues: {playlist_name}",
            header="CONTEÚDO DA PLAYLIST",
            content=content,
            playlist_name=playlist_name,
            txt=self.txt
        )

    def iniciar_importacao(self):
        """
        Inicia o processo de importação de hotcues das tags MP3 para o banco de dados do Engine DJ.
        """
        # Verifica se o Engine DJ está aberto (mesma lógica e mensagens do Mirror Sync)
        if self.manager.engine_esta_aberto():
            messagebox.showwarning(
                "Engine DJ em execução",
                "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."
            )
            return

        playlist_name = self.selected_playlist.get()
        if not playlist_name:
            messagebox.showwarning("Aviso", "Por favor, selecione uma playlist.")
            return

        db_pl_pairs = self.playlist_db_map.get(playlist_name)
        if not db_pl_pairs:
            return

        # UI feedback inicial
        self.btn_import.configure(state="disabled")
        self.btn_list.configure(state="disabled")
        self.combo_playlist.configure(state="disabled")
        self.lbl_status.configure(text=self.txt.get("status_counting", "Calculando..."), text_color="#3498DB")

        # Inicializa o log para Mixed In Key
        log_paths = self.manager.iniciar_log(
            "N/A", "Multi-DB Hotcues", playlist_name, 
            self.manager.config.get("log", True), self.manager.config.get("debug", False), 
            tool_name="MIXED_IN_KEY")

        def task():
            self.manager.log(log_paths, f"--- INÍCIO DA IMPORTAÇÃO DE HOTCUES [{playlist_name}] ---")
            overwriting = self.sobrescrever_hotcue.get()
            report_lines = [
                f"INÍCIO DA IMPORTAÇÃO (MIK): {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n",
                f"Playlist: {playlist_name}\n",
                f"Modo Sobrescrever: {'Ativado' if overwriting else 'Desativado'}\n",
                "="*60 + "\n\n"
            ]
            total_tracks = 0
            for db_path, pl_id in db_pl_pairs:
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                total_tracks += len(tracks)

            if total_tracks == 0:
                self.after(0, lambda: self.finalizar_importacao(0))
                return

            updated_tracks_count = 0
            processed_tracks = 0

            for db_path, pl_id in db_pl_pairs:
                drive = self.manager._get_vol_id(db_path)
                self.manager.log(log_paths, f"\n--- PROCESSANDO BANCO: {db_path} (Drive {drive}) ---")
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                
                seen_paths_in_db = set()
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = self.manager.criar_cursor_log(conn, log_paths)
                    
                    for t in tracks:
                        processed_tracks += 1
                        progress = processed_tracks / total_tracks
                        self.after(0, lambda p=progress, m=t.get('title'): [self.progress_bar.set(p), self.lbl_status.configure(text=f"[{drive}] {m}")])
                        title_full = f"{t.get('artist')} - {t.get('title')}"
                        self.manager.log(log_paths, f"[ARQUIVO] {title_full}")

                        filepath = t.get("caminho_absoluto")
                        if not filepath or not os.path.exists(filepath) or not filepath.lower().endswith(".mp3"):
                            self.manager.log(log_paths, f"  [AVISO] Arquivo não encontrado ou não é MP3: {filepath}")
                            continue

                        # Evita processar o mesmo arquivo físico duas vezes no mesmo banco (se houver trackId duplicado)
                        norm_path = os.path.normcase(os.path.abspath(filepath))
                        if norm_path in seen_paths_in_db:
                            self.manager.log(log_paths, f"  [SKIP] Arquivo já processado neste banco (ID duplicado ignorado).", nivel="debug")
                            continue
                        seen_paths_in_db.add(norm_path)

                        track_id = t.get("id")
                        
                        # 1. Obter Hotcues atuais do Banco
                        cursor.execute("SELECT quickCues FROM PerformanceData WHERE trackId = ?", (track_id,))
                        row = cursor.fetchone()
                        existing_blob = row[0] if row else None
                        db_cues = {}
                        if existing_blob:
                            try:
                                parsed = parse_quick_cues(existing_blob)
                                self.manager.log(log_paths, f"  [DB] Encontrados {len(parsed)} hotcues no banco.", nivel="debug")
                                for hc in parsed: 
                                    db_cues[hc.cue_number] = hc
                                    self.manager.log(log_paths, f"    [DB] ↳ Cue {hc.cue_number}: '{hc.label}' em {format_time(hc.position_seconds)}", nivel="debug")
                            except: pass

                        # 2. Obter Hotcues das Tags MP3
                        try:
                            mp3_data = read_mp3(Path(filepath))
                            tag_hotcues = normalize_hotcues(mp3_data.get("hotcues", []))
                            
                            tags_by_slot = {}
                            slots_encontrados = []
                            for hc in tag_hotcues:
                                if str(hc.get("num", "")).isdigit():
                                    num = int(hc["num"])
                                    tags_by_slot[num] = hc
                                    slots_encontrados.append(f"#{num}")
                                    self.manager.log(log_paths, f"    [TAG] ↳ Cue {num}: '{hc.get('name')}' em {hc.get('time')}", nivel="debug")
                            
                            resumo_tags = ", ".join(slots_encontrados) if slots_encontrados else "Nenhum"
                            self.manager.log(log_paths, f"  [TAGS] {len(tag_hotcues)} hotcue(s) identificado(s): {resumo_tags}")
                        except: 
                            self.manager.log(log_paths, f"  [ERRO] Falha ao ler tags de: {os.path.basename(filepath)}")
                            continue

                        if not tags_by_slot:
                            self.manager.log(log_paths, f"  [INFO] Nenhuma tag de hotcue encontrada.")
                            continue

                        # 3. Mesclar de acordo com a regra
                        final_cues = []
                        has_changes = False
                        self.manager.log(log_paths, f"  [AÇÃO] Mesclando Hotcues (Sobrescrever: {overwriting})", nivel="debug")
                        for slot in range(1, 9):
                            if overwriting:
                                # Se marcado, Tag tem prioridade. Se Tag não tem, mantém Banco.
                                if slot in tags_by_slot:
                                    hc = tags_by_slot[slot]
                                    final_cues.append(CueWrite(cue_number=slot, label=hc.get("name") or f"Cue {slot}", position_seconds=float(hc["pos_seconds"])))
                                    has_changes = True
                                elif slot in db_cues:
                                    hc = db_cues[slot]
                                    final_cues.append(CueWrite(cue_number=slot, label=hc.label, position_seconds=hc.position_seconds))
                            else:
                                # Se NÃO marcado, Banco tem prioridade. Vagas vazias são preenchidas pelas Tags.
                                if slot in db_cues:
                                    hc = db_cues[slot]
                                    final_cues.append(CueWrite(cue_number=slot, label=hc.label, position_seconds=hc.position_seconds))
                                elif slot in tags_by_slot:
                                    hc = tags_by_slot[slot]
                                    final_cues.append(CueWrite(cue_number=slot, label=hc.get("name") or f"Cue {slot}", position_seconds=float(hc["pos_seconds"])))
                                    has_changes = True

                        if has_changes:
                            self.manager.log(log_paths, f"  [AÇÃO] Gravando {len(final_cues)} hotcues no Engine DJ.")
                            new_blob = encode_quick_cues(final_cues, existing_blob=existing_blob)
                            # Usando cursor para que o comando SQL seja registrado no Log de Debug via LoggingCursor
                            cursor.execute("INSERT INTO PerformanceData (trackId, quickCues) VALUES (?, ?) ON CONFLICT(trackId) DO UPDATE SET quickCues = excluded.quickCues", (track_id, sqlite3.Binary(new_blob)))
                            updated_tracks_count += 1
                            
                            acao_label = "SOBREESCRITO" if overwriting else "IMPORTADO"
                            report_lines.append(f"[{acao_label}] {title_full}\n  ↳ {len(final_cues)} hotcues gravados no banco.\n")
                        else:
                            self.manager.log(log_paths, f"  [SKIP] Nenhuma alteração necessária (Banco e Tags já sincronizados).", nivel="debug")

                    conn.commit()
                    conn.close()
                except Exception as e:
                    self.manager.log(log_paths, f"  [ERRO CRÍTICO] Falha no banco {db_path}: {e}")

            if updated_tracks_count == 0:
                report_lines.append("Nenhuma alteração foi necessária. Todas as músicas já possuem hotcues sincronizados ou não foram encontrados hotcues nas tags.")

            self.manager.log(log_paths, f"\n{'='*60}\nIMPORTAÇÃO CONCLUÍDA\nTotal analisado: {processed_tracks}\nAtualizados: {updated_tracks_count}\n{'='*60}")
            self.after(0, lambda: self.finalizar_importacao(updated_tracks_count, "\n".join(report_lines)))

        threading.Thread(target=task, daemon=True).start()

    def finalizar_importacao(self, count, report_content):
        """
        Finaliza o processo de importação, atualiza a UI e exibe o relatório de execução.
        """
        self.btn_import.configure(state="normal")
        self.btn_list.configure(state="normal")
        self.combo_playlist.configure(state="normal")
        self.progress_bar.set(1.0)
        
        status_msg = f"Importação concluída: {count} músicas atualizadas."
        self.lbl_status.configure(text=status_msg, text_color="#00E5A3")

        # Abre o relatório padronizado usando o Template ReportWindow
        ReportWindow(
            self,
            title=f"Relatório Mixed In Key: {self.selected_playlist.get()}",
            header="RELATÓRIO DE SINCRONIZAÇÃO DE HOTCUES",
            content=report_content,
            playlist_name=self.selected_playlist.get(),
            txt=self.txt
        )