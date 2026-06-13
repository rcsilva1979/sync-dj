import os
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox
import shutil
import threading
from collections import defaultdict
from database_utils import (
    localizar_bancos_dados_engine, get_all_playlists_hierarchical, get_tracks_by_playlist_id, 
    update_track_path, get_track_id_by_path, update_playlist_entry_track
)
from engine_sync_app import get_resource_path
from constants import IS_WIN, IS_MAC

class RelocateLostTracksWindow(ctk.CTkToplevel):
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(self.txt["relocate_title"])
        self.geometry("650x850")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a1a")

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        # Estado
        self.selected_playlist = ctk.StringVar()
        self.playlist_db_map = defaultdict(list)
        self.search_folder = ctk.StringVar()
        self.relocate_mode = ctk.StringVar(value="alert")
        self.found_databases = localizar_bancos_dados_engine()

        self.construir_ui()
        self.selected_playlist.trace_add("write", lambda *args: self.atualizar_label_drives())
        self.carregar_playlists()

    def construir_ui(self):
        lbl_title = ctk.CTkLabel(self, text=self.txt["relocate_title"].upper(), font=ctk.CTkFont(size=22, weight="bold"), text_color="#F39C12")
        lbl_title.pack(pady=(30, 20))

        # Label Informativo unificado seguindo o padrão do Mirror Sync
        self.lbl_db_auto = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#AAAAAA")
        self.lbl_db_auto.pack(pady=(5, 10), padx=40)

        # Seleção de Playlist
        frame_pl = ctk.CTkFrame(self, fg_color="transparent")
        frame_pl.pack(padx=40, pady=10, fill="x")
        
        ctk.CTkLabel(frame_pl, text=self.txt["playlist"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        self.combo_playlist = ctk.CTkComboBox(frame_pl, variable=self.selected_playlist, values=[], width=450, state="disabled")
        self.combo_playlist.pack(pady=5, fill="x")

        # Pasta de Busca
        frame_search = ctk.CTkFrame(self, fg_color="transparent")
        frame_search.pack(padx=40, pady=10, fill="x")
        
        ctk.CTkLabel(frame_search, text=self.txt["search_folder_label"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        entry_search = ctk.CTkEntry(frame_search, textvariable=self.search_folder, width=350)
        entry_search.pack(side="left", pady=5, fill="x", expand=True, padx=(0, 10))
        
        btn_browse = ctk.CTkButton(frame_search, text=self.txt["browse"], width=100, fg_color="#F39C12", text_color="#000000", hover_color="#D68910", command=self.procurar_pasta_busca)
        btn_browse.pack(side="right")

        # Opções de Modo (Alertar, Copiar, Relocar)
        frame_mode = ctk.CTkFrame(self, fg_color="transparent")
        frame_mode.pack(padx=40, pady=10, fill="x")
        
        ctk.CTkLabel(frame_mode, text=self.txt["relocate_mode_label"], font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        self.r_alert = ctk.CTkRadioButton(frame_mode, text=self.txt["relocate_mode_alert"], variable=self.relocate_mode, value="alert", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_alert.pack(anchor="w", pady=5)
        
        self.r_copy = ctk.CTkRadioButton(frame_mode, text=self.txt["relocate_mode_copy"], variable=self.relocate_mode, value="copy", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_copy.pack(anchor="w", pady=5)
        
        self.r_update = ctk.CTkRadioButton(frame_mode, text=self.txt["relocate_mode_update"], variable=self.relocate_mode, value="relocate", font=ctk.CTkFont(size=12), fg_color="#F39C12", hover_color="#D68910")
        self.r_update.pack(anchor="w", pady=5)

        # Botão: Listar Músicas Faltantes
        self.btn_view_missing = ctk.CTkButton(
            self,
            text=self.txt["view_tracks_btn"],
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#555555", text_color="#FFFFFF", hover_color="#777777",
            height=40, width=350,
            command=self.listar_musicas_faltantes
        )
        self.btn_view_missing.pack(pady=(20, 0))

        # Ação
        self.btn_action = ctk.CTkButton(
            self,
            text=self.txt["relocate_btn_action"],
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#F39C12", text_color="#000000", hover_color="#D68910",
            height=50, width=350,
            command=self.iniciar_relocacao
        )
        self.btn_action.pack(pady=30)

        # Progresso e Status
        self.progress_bar = ctk.CTkProgressBar(self, width=500, progress_color="#F39C12")
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)

        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="#AAAAAA")
        self.lbl_status.pack(pady=10)

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

    def atualizar_label_drives(self):
        """Atualiza a visualização dos drives destacando onde a playlist selecionada está presente."""
        if not self.found_databases:
            self.lbl_db_auto.configure(text=f"✖ {self.txt.get('not_found', 'Não localizada')}", text_color="#FF5555")
            return

        playlist_atual = self.selected_playlist.get()
        dbs_com_playlist = [pair[0] for pair in self.playlist_db_map.get(playlist_atual, [])]
        drives_com_playlist = {os.path.splitdrive(db)[0].upper() for db in dbs_com_playlist}
        drives_totais = sorted(list({os.path.splitdrive(d)[0].upper() for d in self.found_databases}))
        
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
            drive = os.path.splitdrive(db_path)[0]
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
        pl_nome = self.selected_playlist.get()
        busca_dir = self.search_folder.get()

        if not busca_dir or not pl_nome:
            messagebox.showwarning("Aviso", self.txt["error_paths"])
            return

        db_pl_pairs = self.playlist_db_map.get(pl_nome)
        if not db_pl_pairs: return

        current_mode = self.relocate_mode.get()
        self.btn_action.configure(state="disabled")
        self.btn_view_missing.configure(state="disabled")
        self.combo_playlist.configure(state="disabled")
        
        def task():
            total_tracks_all = 0
            total_missing_all = 0
            total_relocated_all = 0
            skipped_duplicate = 0
            skipped_different_drive = 0

            # 1. Indexar a pasta de busca
            self.after(0, lambda: self.lbl_status.configure(text=self.txt["status_searching_files"]))
            file_index = defaultdict(list)
            for raiz, diretorios, arquivos in os.walk(busca_dir):
                # Pula pastas ocultas (ex: .trash) e de sistema para melhor performance
                diretorios[:] = [d for d in diretorios if not d.startswith('.') and not d.startswith('$')]
                for f in arquivos:
                    file_index[f.lower()].append(os.path.join(raiz, f))

            # 2. Processar cada banco
            for db_path, pl_id in db_pl_pairs:
                drive = os.path.splitdrive(db_path)[0]
                self.after(0, lambda d=drive: self.lbl_status.configure(text=f"[{d}] " + self.txt["status_scanning_missing"]))
                tracks = get_tracks_by_playlist_id(db_path, pl_id)
                missing_tracks = [t for t in tracks if not os.path.exists(t.get("caminho_absoluto", ""))]
                
                total_tracks_all += len(tracks)
                total_missing_all += len(missing_tracks)

                if not missing_tracks:
                    continue

                engine_library_parent = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))

                for i, track in enumerate(missing_tracks):
                    fname = track.get("filename")
                    track_id = track.get("id")
                    entry_id = track.get("entry_id")
                    
                    progress = (i + 1) / len(missing_tracks)
                    self.after(0, lambda p=progress, f=fname, d=drive: [
                        self.progress_bar.set(p),
                        self.lbl_status.configure(text=f"[{d}] " + self.txt["status_relocating"].format(filename=f))
                    ])

                    if fname.lower() in file_index:
                        # Tenta encontrar no mesmo drive/volume (Obrigatório para Engine DJ)
                        found_somewhere = True
                        novo_caminho_abs = None
                        for path_found in file_index[fname.lower()]:
                            abs_f = os.path.abspath(path_found)
                            abs_db = os.path.abspath(db_path)
                            
                            if IS_WIN:
                                same_drive = os.path.splitdrive(abs_f)[0].upper() == os.path.splitdrive(abs_db)[0].upper()
                            else: # Mac logic
                                # Compara o nome do volume em /Volumes/NomeVolume/...
                                p_f = abs_f.split('/')
                                p_db = abs_db.split('/')
                                vol_f = p_f[2] if len(p_f) > 2 and p_f[1] == 'Volumes' else 'system'
                                vol_db = p_db[2] if len(p_db) > 2 and p_db[1] == 'Volumes' else 'system'
                                same_drive = vol_f == vol_db
                            
                            if same_drive:
                                novo_caminho_abs = path_found
                                break
                        
                        # Se modo for restauração (cópia) e não achou no mesmo drive, tenta usar qualquer um encontrado
                        if not novo_caminho_abs and found_somewhere and current_mode == "copy":
                            novo_caminho_abs = file_index[fname.lower()][0]

                        if novo_caminho_abs and current_mode != "alert":
                            try:
                                if current_mode == "relocate":
                                    novo_rel_path = os.path.relpath(novo_caminho_abs, engine_library_parent).replace("\\", "/")
                                    
                                    # Verifica se o arquivo já existe no banco com outro ID (Evita erro de UNIQUE)
                                    existing_id = get_track_id_by_path(db_path, novo_rel_path)
                                    
                                    if existing_id and existing_id != track_id:
                                        # CASO ESPECIAL: A música já está no banco. 
                                        # Atualizamos a playlist para usar o ID que já funciona.
                                        if entry_id and update_playlist_entry_track(db_path, entry_id, existing_id):
                                            total_relocated_all += 1
                                        else:
                                            skipped_duplicate += 1
                                    else:
                                        # CASO NORMAL: Atualiza o caminho do registro atual
                                        if update_track_path(db_path, track_id, novo_rel_path):
                                            total_relocated_all += 1
                                        else:
                                            skipped_duplicate += 1
                                elif current_mode == "copy":
                                    dest_abs = track.get("caminho_absoluto")
                                    if dest_abs:
                                        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                                        shutil.copy2(novo_caminho_abs, dest_abs)
                                        total_relocated_all += 1
                            except:
                                continue
                        elif found_somewhere:
                            if current_mode == "relocate" and not novo_caminho_abs:
                                skipped_different_drive += 1

            self.after(0, lambda: self.finalizar_processo(total_tracks_all, total_missing_all, total_relocated_all, skipped_duplicate, skipped_different_drive))

        threading.Thread(target=task, daemon=True).start()

    def finalizar_processo(self, total, missing, relocated, duplicates=0, diff_drive=0):
        self.btn_action.configure(state="normal")
        self.btn_view_missing.configure(state="normal")
        self.combo_playlist.configure(state="normal")
        self.progress_bar.set(1.0)
        self.lbl_status.configure(text=self.txt["status_done"])
        
        detail = self.txt["success_relocate_detail"].format(
            total=total,
            missing=missing,
            relocated=relocated
        )

        not_found = missing - relocated - duplicates - diff_drive
        extra = ""
        if duplicates > 0:
            extra += f"\n• {self.txt['skipped_duplicate']}: {duplicates}"
        if diff_drive > 0:
            extra += f"\n• {self.txt['skipped_different_drive']}: {diff_drive}"
        if not_found > 0:
            extra += f"\n• {self.txt['skipped_not_found']}: {max(0, not_found)}"
            
        if extra:
            detail += "\n" + extra

        messagebox.showinfo(self.txt["success_title"], detail)
        if relocated > 0:
            self.destroy() # Fecha se houve progresso