import os
import sys
import customtkinter as ctk
from PIL import Image
from tkinter import messagebox
from collections import defaultdict
from pathlib import Path
import sqlite3
import threading

# Importações do projeto
from database_utils import localizar_bancos_dados_engine, get_all_playlists_hierarchical, get_tracks_by_playlist_id
from engine_sync_app import get_resource_path
from le_json import read_mp3
from constants import IS_WIN, IS_MAC
from hotcue_normalizer import normalize_hotcues
from engine_hotcues import format_time, parse_quick_cues, CueWrite, encode_quick_cues

class MixedInKeyWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(self.txt.get("mik_sync_title", "Mixed In Key Hotcue Sync"))
        self.geometry("650x620")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a1a")

        # Garante foco e modalidade
        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if sys.platform.startswith('win') and os.path.exists(self.caminho_icone):
            try: self.iconbitmap(self.caminho_icone)
            except: pass

        self.selected_playlist = ctk.StringVar()
        self.sobrescrever_hotcue = ctk.BooleanVar(value=False)
        self.found_databases = localizar_bancos_dados_engine()
        self.playlist_db_map = defaultdict(list)

        self.construir_ui()
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        self.carregar_playlists()

    def construir_ui(self):
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
            lbl_title = ctk.CTkLabel(self, text="MIXED IN KEY HOTCUE SYNC", font=ctk.CTkFont(size=22, weight="bold"), text_color="#3498DB")
            lbl_title.pack(pady=(30, 15))

        # Label Informativo unificado seguindo o padrão do Mirror Sync
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_db_auto.pack(pady=(5, 10), padx=40)

        # Seleção de Playlist
        lbl_playlist = ctk.CTkLabel(self, text=self.txt.get("select_playlist_full_path", "Select Playlist:"), font=ctk.CTkFont(weight="bold"))
        lbl_playlist.pack(pady=(15, 5))

        self.combo_playlist = ctk.CTkComboBox(
            self,
            variable=self.selected_playlist,
            values=[],
            width=500,
            height=35,
            state="disabled"
        )
        self.combo_playlist.pack(pady=5)

        # Checkbox: Sobrescrever (Reutilizando string do constants.py)
        self.check_overwrite = ctk.CTkCheckBox(
            self,
            text=self.txt.get("hotcue_overwrite", "Sobrescrever hotcues").strip().replace("↳", "").strip(),
            variable=self.sobrescrever_hotcue,
            font=ctk.CTkFont(size=12),
            fg_color="#3498DB", hover_color="#2980B9"
        )
        self.check_overwrite.pack(pady=10)

        # Botão de Listagem
        self.btn_list = ctk.CTkButton(
            self,
            text=self.txt.get("mik_list_btn", "List Songs and Hotcues (Tags)"),
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#555555", hover_color="#777777",
            height=40, width=350,
            command=self.listar_musicas_hotcues
        )
        self.btn_list.pack(pady=(10, 0))

        # Botão de Ação
        self.btn_import = ctk.CTkButton(
            self,
            text=self.txt.get("mik_import_btn_action", "Start Tag Import"),
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#3498DB", hover_color="#2980B9",
            height=50, width=350,
            command=self.iniciar_importacao
        )
        self.btn_import.pack(pady=30)

        # Barra de Progresso
        self.progress_bar = ctk.CTkProgressBar(self, width=500, height=12, progress_color="#3498DB")
        self.progress_bar.pack(pady=(0, 10))
        self.progress_bar.set(0)

        # Status Label
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="#3498DB")
        self.lbl_status.pack(side="bottom", pady=20)

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
            self.combo_playlist.set(all_playlists[0]) # Define o valor inicial do combobox
            self.atualizar_label_drives()
        else:
            self.combo_playlist.configure(values=[], state="disabled")
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")

    def atualizar_label_drives(self):
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {os.path.splitdrive(db)[0].upper() for db in dbs_com_playlist}

        drives_totais = sorted(list({os.path.splitdrive(d)[0].upper() for d in self.found_databases}))
        
        # Monta a string de drives destacando os que contêm a playlist (ex: [C:] | D:)
        texto_drives = " | ".join([
            f"[{d}]" if d in drives_com_playlist else d 
            for d in drives_totais
        ])

        status_text = f"✔ {self.txt.get('engine_dbs_detected', 'Bancos detectados').format(count=len(self.found_databases))}: {texto_drives}"
        self.lbl_db_auto.configure(text=status_text, text_color="#00E5A3")

    def listar_musicas_hotcues(self):
        playlist_name = self.selected_playlist.get()
        if not playlist_name:
            messagebox.showwarning("Aviso", "Por favor, selecione uma playlist.")
            return

        db_pl_pairs = self.playlist_db_map.get(playlist_name)
        if not db_pl_pairs:
            return

        # Janela de visualização
        viewer = ctk.CTkToplevel(self)
        viewer.title(f"Músicas e Hotcues: {playlist_name}")
        viewer.geometry("900x700")
        viewer.transient(self)
        viewer.grab_set()

        lbl_header = ctk.CTkLabel(viewer, text=f"Conteúdo da Playlist: {playlist_name}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_header.pack(pady=10)

        textbox = ctk.CTkTextbox(viewer, width=860, height=600, font=ctk.CTkFont(family="Consolas", size=11))
        textbox.pack(padx=20, pady=(0, 20), fill="both", expand=True)

        total_tracks_found = 0

        for db_path, pl_id in db_pl_pairs:
            drive = os.path.splitdrive(db_path)[0]
            textbox.insert("end", f"--- BANCO DETECTADO NO DRIVE {drive} ---\n")
            
            tracks = get_tracks_by_playlist_id(db_path, pl_id)
            if not tracks:
                textbox.insert("end", "Nenhuma música encontrada neste banco.\n\n")
                continue
            
            total_tracks_found += len(tracks)
            for t in tracks:
                artist = t.get('artist', self.txt.get('unknown_artist', 'Desconhecido'))
                title = t.get('title', self.txt.get('untitled_track', 'Sem Título'))
                filename = t.get('filename', self.txt.get('not_found', 'Não localizada'))
                filepath = t.get("caminho_absoluto")

                textbox.insert("end", f"FAIXA: {artist} - {title}\n")
                textbox.insert("end", f"  {self.txt.get('mik_filename_label', 'Nome do Arquivo:')} {filename}\n")
                textbox.insert("end", f"  {self.txt.get('mik_location_label', 'Localização:')} {filepath}\n")
                
                if filepath and os.path.exists(filepath) and filepath.lower().endswith(".mp3"):
                    try:
                        mp3_data = read_mp3(Path(filepath))
                        hotcues = normalize_hotcues(mp3_data.get("hotcues", []))
                        if hotcues:
                            hotcues_left = hotcues[:4]
                            hotcues_right = hotcues[4:8] # Assuming max 8 hotcues

                            # Prepare lines for left and right columns
                            left_lines = []
                            for hc in hotcues_left:
                                cue_info = f"Cue {hc.get('num')}: {hc.get('name', '')} @ {format_time(hc.get('pos_seconds'))}"
                                left_lines.append(cue_info)

                            right_lines = []
                            for hc in hotcues_right:
                                cue_info = f"Cue {hc.get('num')}: {hc.get('name', '')} @ {format_time(hc.get('pos_seconds'))}"
                                right_lines.append(cue_info)

                            # Pad shorter lists with empty strings
                            max_lines = max(len(left_lines), len(right_lines))
                            left_lines.extend([""] * (max_lines - len(left_lines)))
                            right_lines.extend([""] * (max_lines - len(right_lines)))

                            # Headers
                            header_left = self.txt.get('mik_hotcue_left_col_header', 'Hotcues (1-4)')
                            header_right = self.txt.get('mik_hotcue_right_col_header', 'Hotcues (5-8)')
                            textbox.insert("end", f"  ↳ [TAG] {header_left:<40} {header_right}\n")
                            textbox.insert("end", f"  {'-'*45} {'-'*45}\n") # Separator, adjusted for padding

                            # Print hotcues side-by-side
                            for i in range(max_lines):
                                textbox.insert("end", f"  {left_lines[i]:<45} {right_lines[i]}\n")
                        else:
                            textbox.insert("end", f"  ↳ [TAG] {self.txt.get('mik_no_hotcues_found', 'Nenhum Hotcue encontrado na tag MP3.')}\n")
                    except Exception as e:
                        textbox.insert("end", f"  ↳ [ERRO] {self.txt.get('mik_error_reading_hotcues', 'Falha ao ler hotcues:')} {str(e)}\n")
                else:
                    textbox.insert("end", f"  ↳ [INFO] {self.txt.get('mik_detection_info', 'Detecção disponível apenas para arquivos MP3 locais.')}\n")
                textbox.insert("end", "-" * 40 + "\n")
            textbox.insert("end", "\n")

        if total_tracks_found == 0:
            textbox.insert("end", "Nenhuma música localizada.")

        textbox.configure(state="disabled")

    def iniciar_importacao(self):
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

        def task():
            total_tracks = 0
            for db_path, pl_id in db_pl_pairs:
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                total_tracks += len(tracks)

            if total_tracks == 0:
                self.after(0, lambda: self.finalizar_importacao(0))
                return

            updated_tracks_count = 0
            processed_tracks = 0
            overwriting = self.sobrescrever_hotcue.get()

            for db_path, pl_id in db_pl_pairs:
                drive = os.path.splitdrive(db_path)[0]
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                
                try:
                    conn = sqlite3.connect(db_path)
                    for t in tracks:
                        processed_tracks += 1
                        progress = processed_tracks / total_tracks
                        self.after(0, lambda p=progress, m=t.get('title'): [self.progress_bar.set(p), self.lbl_status.configure(text=f"[{drive}] {m}")])

                        filepath = t.get("caminho_absoluto")
                        if not filepath or not os.path.exists(filepath) or not filepath.lower().endswith(".mp3"):
                            continue

                        track_id = t.get("id")
                        
                        # 1. Obter Hotcues atuais do Banco
                        row = conn.execute("SELECT quickCues FROM PerformanceData WHERE trackId = ?", (track_id,)).fetchone()
                        existing_blob = row[0] if row else None
                        db_cues = {}
                        if existing_blob:
                            try:
                                parsed = parse_quick_cues(existing_blob)
                                for hc in parsed: db_cues[hc.cue_number] = hc
                            except: pass

                        # 2. Obter Hotcues das Tags MP3
                        try:
                            mp3_data = read_mp3(Path(filepath))
                            tag_hotcues = normalize_hotcues(mp3_data.get("hotcues", []))
                            tags_by_slot = {int(hc["num"]): hc for hc in tag_hotcues if str(hc.get("num", "")).isdigit()}
                        except: continue

                        if not tags_by_slot: continue

                        # 3. Mesclar de acordo com a regra
                        final_cues = []
                        has_changes = False
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
                            new_blob = encode_quick_cues(final_cues, existing_blob=existing_blob)
                            conn.execute("INSERT INTO PerformanceData (trackId, quickCues) VALUES (?, ?) ON CONFLICT(trackId) DO UPDATE SET quickCues = excluded.quickCues", (track_id, sqlite3.Binary(new_blob)))
                            updated_tracks_count += 1

                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Erro no banco {db_path}: {e}")

            self.after(0, lambda: self.finalizar_importacao(updated_tracks_count))

        threading.Thread(target=task, daemon=True).start()

    def finalizar_importacao(self, count):
        self.btn_import.configure(state="normal")
        self.btn_list.configure(state="normal")
        self.combo_playlist.configure(state="normal")
        self.progress_bar.set(1.0)
        
        msg = f"Importação concluída: {count} músicas atualizadas."
        self.lbl_status.configure(text=msg, text_color="#00E5A3")
        messagebox.showinfo("Sucesso", msg)