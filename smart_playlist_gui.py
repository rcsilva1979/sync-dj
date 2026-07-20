import os
import queue
import random
import re
import sqlite3
import json
import tkinter as tk
import threading
from datetime import datetime
from tkinter import messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk
from mutagen import File

from constants import (
    APP_NAME,
    VERSAO_ATUAL,
    FONT_FAMILY,
    COLOR_BG_DARK,
    COLOR_TEXT_NORMAL,
    COLOR_TEXT_MUTED,
    CORNER_RADIUS_NONE,
    COLOR_SWITCH_OFF,
    COLOR_ACCENT_BLUE,
)
from engine_sync_app import get_app_storage_dir, get_resource_path
from database_utils import (
    localizar_bancos_dados_engine,
    engine_dj_esta_aberto,
    get_all_tracks_from_database,
    get_database_uuid,
)


# Valores numéricos usados pelo Engine DJ na coluna Track.key para a notação
# Camelot equivalente. A Smart Playlist trabalha sempre com esta última.
ENGINE_KEY_TO_CAMELOT = {
    0: "8B", 1: "8A", 2: "9B", 3: "9A", 4: "10B", 5: "10A",
    6: "11B", 7: "11A", 8: "12B", 9: "12A", 10: "1B", 11: "1A",
    12: "2B", 13: "2A", 14: "3B", 15: "3A", 16: "4B", 17: "4A",
    18: "5B", 19: "5A", 20: "6B", 21: "6A", 22: "7B", 23: "7A",
}


class SmartPlaylistWindow(ctk.CTkToplevel):
    """Janela para criar uma Smart Playlist baseada em uma música inicial."""

    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.master = master

        self.title(f"{self.txt.get('smart_playlist_title', 'Criar Smart Playlist')} ({VERSAO_ATUAL})")
        self.geometry("1280x780")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG_DARK)

        self.transient(master)
        self.grab_set()
        self.after(10, self.lift)

        self.initial_song = ctk.StringVar(value="")
        self.playlist_size = ctk.StringVar(value="20")
        self.playlist_name = ctk.StringVar(value="Smart Playlist")
        self.status_text = ctk.StringVar(value=self.txt.get("smart_playlist_loading_db", "Carregando bancos do Engine DJ..."))
        self.database_paths = []
        self.track_map = {}
        self.available_track_labels = []
        self.all_track_objects = []
        self.metadata_by_track_id = {}
        self.last_candidates = []
        self.current_selected_tracks = []
        self.generated_playlists = 0
        self.catalog_loading = False
        self.selection_loading = False
        self.catalog_events = queue.Queue()
        self.tree_sort_descending = {}
        self.tree_headings = {}

        self._setup_icon()
        self.construir_ui()
        self.after(100, self._processar_eventos_catalogo)
        self.carregar_bancos()

    def _setup_icon(self):
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if os.path.exists(self.caminho_icone):
            def aplicar_icone():
                try:
                    if os.name == "nt":
                        self.iconbitmap(self.caminho_icone)
                    else:
                        img = Image.open(self.caminho_icone)
                        self._icon_photo = ImageTk.PhotoImage(img)
                        self.iconphoto(False, self._icon_photo)
                except Exception:
                    pass

            self.after(200, aplicar_icone)

    def construir_ui(self):
        logo_path = get_resource_path(os.path.join("images", "logo_smart_playlist.png"))
        if os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path)
                self.logo_smart_playlist = ctk.CTkImage(
                    light_image=logo,
                    dark_image=logo,
                    size=(480, 90),
                )
                ctk.CTkLabel(self, text="", image=self.logo_smart_playlist).pack(pady=(20, 15))
            except Exception:
                pass

        frame_selection = ctk.CTkFrame(self, fg_color="transparent")
        frame_selection.pack(fill="x", padx=24, pady=(0, 3))

        ctk.CTkLabel(frame_selection, text=self.txt.get("smart_playlist_initial_song", "Música inicial"), font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold")).pack(anchor="w")
        entry_song = ctk.CTkEntry(frame_selection, textvariable=self.initial_song, state="readonly", font=ctk.CTkFont(family=FONT_FAMILY, size=12), width=500, corner_radius=CORNER_RADIUS_NONE)
        entry_song.pack(anchor="w", pady=(0, 4))

        btn_select = ctk.CTkButton(
            frame_selection,
            text=self.txt.get("smart_playlist_use_selected", "Usar música selecionada"),
            width=180,
            fg_color=COLOR_ACCENT_BLUE,
            hover_color="#1F4E79",
            text_color=COLOR_TEXT_NORMAL,
            corner_radius=CORNER_RADIUS_NONE,
            command=self.definir_musica_inicial,
        )
        btn_select.pack(anchor="w")

        quantity_frame = ctk.CTkFrame(frame_selection, fg_color="transparent")
        quantity_frame.pack(anchor="w", pady=(10, 0))
        ctk.CTkLabel(
            quantity_frame,
            text=self.txt.get("smart_playlist_quantity", "Quantidade de músicas"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        ).pack(side="left")
        self.quantity_menu = ctk.CTkOptionMenu(
            quantity_frame,
            values=["20", "40", "60", "80", "100"],
            variable=self.playlist_size,
            width=100,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            dropdown_font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=COLOR_ACCENT_BLUE,
            corner_radius=CORNER_RADIUS_NONE,
            button_color="#1F4E79",
        )
        self.quantity_menu.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            quantity_frame,
            text=self.txt.get("smart_playlist_name", "Nome da playlist"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        ).pack(side="left", padx=(24, 0))
        self.playlist_name_entry = ctk.CTkEntry(
            quantity_frame,
            textvariable=self.playlist_name,
            width=250,
            corner_radius=CORNER_RADIUS_NONE,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.playlist_name_entry.pack(side="left", padx=(10, 0))

        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=24, pady=(8, 10))

        left_frame = ctk.CTkFrame(content_frame, fg_color="#232323", corner_radius=CORNER_RADIUS_NONE)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_frame = ctk.CTkFrame(content_frame, fg_color="#232323", corner_radius=CORNER_RADIUS_NONE)
        right_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))

        # --- Frame do Cabeçalho da Lista de Músicas com Botão de Refresh ---
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkLabel(header_frame, text=self.txt.get("smart_playlist_available_tracks", "Músicas disponíveis"),
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")).pack(side="left", anchor="w")

        self.btn_refresh = ctk.CTkButton(header_frame, text="🔄", width=30, height=24,
                                         font=ctk.CTkFont(size=16),
                                         fg_color="#444444", hover_color="#555555",
                                         command=lambda: self.carregar_bancos(clear_cache=True))
        self.btn_refresh.pack(side="right", anchor="e")

        self._configure_treeview_style()
        columns = ("title", "artist", "bpm", "genre", "key", "energy")
        self.track_tree = ttk.Treeview(left_frame, columns=columns, show="headings", selectmode="browse", style="SmartPlaylist.Treeview")
        headings = {"title": self.txt.get("col_title", "Título"), "artist": self.txt.get("col_artist", "Artista"), "bpm": "BPM", "genre": self.txt.get("col_genre", "Gênero"), "key": "Key", "energy": self.txt.get("col_energy", "Energia")}
        self.tree_headings = headings
        widths = {"title": 205, "artist": 155, "bpm": 55, "genre": 90, "key": 55, "energy": 65}
        for column in columns:
            self.track_tree.heading(column, text=headings[column], command=lambda col=column: self._sort_tracks_by_column(col))
            self.track_tree.column(column, width=widths[column], minwidth=45, anchor="w")
        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.track_tree.yview)
        self.track_tree.configure(yscrollcommand=tree_scroll.set)
        self.track_tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        tree_scroll.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))
        self.track_tree.bind("<<TreeviewSelect>>", self.on_track_selected)

        ctk.CTkLabel(right_frame, text=self.txt.get("smart_playlist_suggested_tracks", "Faixas sugeridas"), font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")).pack(anchor="w", padx=10, pady=(10, 6))
        self.result_box = ctk.CTkTextbox(
            right_frame, height=18, fg_color="#1F1F1F", text_color=COLOR_TEXT_NORMAL,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=CORNER_RADIUS_NONE,
        )
        self.result_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.result_box.insert("0.0", self.txt.get("smart_playlist_suggested_placeholder", "As faixas selecionadas aparecerão aqui."))
        self.result_box.configure(state="disabled")

        bottom_area = ctk.CTkFrame(self, fg_color="transparent")
        bottom_area.pack(fill="x", padx=24, pady=(0, 6))
        status_frame = ctk.CTkFrame(bottom_area, fg_color="transparent")
        status_frame.pack(fill="x")
        bottom_frame = ctk.CTkFrame(bottom_area, fg_color="transparent")
        bottom_frame.pack(fill="x", pady=(8, 0))

        self.btn_create = ctk.CTkButton(
            bottom_frame,
            text=self.txt.get("smart_playlist_create_btn", "Criar Smart Playlist"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            height=42,
            fg_color="#27AE60",
            hover_color="#1E8449",
            text_color=COLOR_TEXT_NORMAL,
            corner_radius=CORNER_RADIUS_NONE,
            command=self.criar_playlist,
        )
        self.btn_create.pack(side="left")

        self.btn_regenerate = ctk.CTkButton(
            bottom_frame,
            text=self.txt.get("smart_playlist_regenerate_btn", "Gerar nova playlist"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            height=42,
            fg_color="#8E44AD",
            hover_color="#6C3483",
            text_color=COLOR_TEXT_NORMAL,
            corner_radius=CORNER_RADIUS_NONE,
            command=self.gerar_nova_playlist,
            state="disabled",
        )
        self.btn_regenerate.pack(side="left", padx=(10, 0))

        self.btn_save_engine = ctk.CTkButton(
            bottom_frame,
            text=self.txt.get("smart_playlist_save_btn", "Salvar no Engine DJ"),
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            height=42,
            fg_color="#D68910",
            hover_color="#B9770E",
            text_color=COLOR_TEXT_NORMAL,
            corner_radius=CORNER_RADIUS_NONE,
            command=self.salvar_no_engine,
            state="disabled",
        )
        self.btn_save_engine.pack(side="left", padx=(10, 0))

        self.status_label = ctk.CTkLabel(
            status_frame,
            textvariable=self.status_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=COLOR_TEXT_NORMAL,
            wraplength=800,
        )
        self.status_label.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(status_frame, progress_color=COLOR_ACCENT_BLUE, corner_radius=CORNER_RADIUS_NONE)
        self.progress_bar.pack(fill="x", pady=(4, 0))
        self.progress_bar.set(0)

        # Rodapé (empacotado por último para garantir visibilidade)
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.pack(side="bottom", fill="x", pady=(0, 10))
        ctk.CTkLabel(
            footer_frame, text=f"{APP_NAME} ({VERSAO_ATUAL})",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED
        ).pack()

    def on_track_selected(self, *_args):
        selection = self.track_tree.selection()
        if not selection:
            return
        label = self.track_tree.item(selection[0], "text")
        self.initial_song.set(label)

    def _configure_treeview_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "SmartPlaylist.Treeview",
            background="#1E1E1E", foreground="#FFFFFF", fieldbackground="#1E1E1E",
            rowheight=27, font=(FONT_FAMILY, 12), borderwidth=0,
        )
        style.configure(
            "SmartPlaylist.Treeview.Heading",
            background="#323232", foreground="#FFFFFF", font=(FONT_FAMILY, 12, "bold"), relief="flat",
        )
        style.map("SmartPlaylist.Treeview", background=[("selected", "#00A878")], foreground=[("selected", "#000000")])

    def _sort_tracks_by_column(self, column):
        """Ordena a tabela pelo cabeçalho clicado; um novo clique inverte a direção."""
        descending = not self.tree_sort_descending.get(column, False)
        numeric_columns = {"bpm", "energy"}
        values = []
        missing = []

        for item_id in self.track_tree.get_children(""):
            value = self.track_tree.set(item_id, column).strip()
            if not value or value == "—":
                missing.append(item_id)
                continue
            if column in numeric_columns:
                try:
                    sort_value = float(value.replace(",", "."))
                except ValueError:
                    missing.append(item_id)
                    continue
            else:
                sort_value = value.casefold()
            values.append((sort_value, item_id))

        values.sort(key=lambda pair: pair[0], reverse=descending)
        for position, (_, item_id) in enumerate(values):
            self.track_tree.move(item_id, "", position)
        for position, item_id in enumerate(missing, start=len(values)):
            self.track_tree.move(item_id, "", position)

        self.tree_sort_descending[column] = descending
        for heading_column, title in self.tree_headings.items():
            indicator = (" ↓" if descending else " ↑") if heading_column == column else ""
            self.track_tree.heading(heading_column, text=f"{title}{indicator}")

    def _pode_executar_acao(self):
        if not engine_dj_esta_aberto():
            return True
        self.status_text.set(self.txt.get("mik_engine_running_title", "Engine DJ em execução"))
        messagebox.showwarning(
            self.txt.get("mik_engine_running_title", "Engine DJ em execução"),
            self.txt.get("mik_engine_running_message", "Feche o Engine DJ antes de executar a sincronização ou limpeza.\n\nNenhuma alteração foi feita."),
        )
        return False

    def definir_musica_inicial(self):
        label = self.initial_song.get().strip()
        if not label:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_select_initial_song", "Selecione uma música da lista."))
            return
        if label not in self.track_map:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_initial_song_not_found", "A música selecionada não está disponível no catálogo atual."))
            return
        self.status_text.set(self.txt.get("smart_playlist_initial_song", "Música inicial") + f": {label}")

    def carregar_bancos(self, clear_cache=False):
        """Carrega o catálogo em segundo plano para não atrasar a abertura da janela."""
        if self.catalog_loading:
            return
        self.catalog_loading = True
        self.track_map = {}
        self.available_track_labels = []
        self.initial_song.set("")
        self.all_track_objects = []
        self.metadata_by_track_id = {}
        for item in self.track_tree.get_children():
            self.track_tree.delete(item)
        self.status_text.set(self.txt.get("smart_playlist_loading_catalog", "Carregando catálogo de músicas em segundo plano..."))
        self.progress_bar.set(0)
        threading.Thread(target=self._carregar_catalogo_em_segundo_plano, args=(clear_cache,), daemon=True).start()

    def _carregar_catalogo_em_segundo_plano(self, clear_cache=False):
        database_paths = [os.path.normpath(path) for path in localizar_bancos_dados_engine()]
        track_map = {}
        labels = []
        tracks = []
        metadata_by_track_id = {}

        if not database_paths:
            self.catalog_events.put(("complete", database_paths, track_map, labels, tracks, metadata_by_track_id))
            return

        cache_conn = None
        if not clear_cache:
            cache_conn = self._abrir_cache_metadados()

        processed = 0
        try:
            for db_path in database_paths:
                try:
                    for track in get_all_tracks_from_database(db_path):
                        label = self._build_track_label(track)
                        if label not in track_map:
                            metadata = self._extract_metadata_from_track(track)
                            track_map[label] = track
                            labels.append(label)
                            tracks.append(track)
                            metadata_by_track_id[id(track)] = metadata
                            processed += 1
                            if processed % 25 == 0:
                                self.catalog_events.put(("progress", processed))
                            if cache_conn and processed % 100 == 0:
                                cache_conn.commit()
                except Exception:
                    continue
        finally:
            if cache_conn:
                try:
                    cache_conn.commit()
                except sqlite3.Error:
                    pass
                cache_conn.close()

        self.catalog_events.put(("complete", database_paths, track_map, labels, tracks, metadata_by_track_id))

    def _extract_metadata_from_track(self, track):
        """Extrai metadados diretamente do objeto track vindo do banco de dados."""
        return {
            "genre": track.get("genre", ""),
            "key": self._engine_key_to_camelot(track.get("key")),
            "bpm": track.get("bpm"),
            "energy": self._extract_energy_from_comment(track.get("comment")),
            "description": track.get("comment", ""),
            "title": (track.get("title") or track.get("filename") or "").strip(),
        }

    @staticmethod
    def _engine_key_to_camelot(value):
        """Converte o código numérico do Engine DJ para a key Camelot."""
        if value is None:
            return ""
        try:
            numeric_value = int(str(value).strip())
            if str(numeric_value) == str(value).strip():
                return ENGINE_KEY_TO_CAMELOT.get(numeric_value, "")
        except (TypeError, ValueError):
            pass
        return str(value).strip()

    def _extract_energy_from_comment(self, comment):
        """Lê energia do comentário ID3, aceitando 'Energy: 7', 'Energia=7' ou só '7'."""
        if not comment:
            return None
        match = re.search(r"\b(?:energy|energia)\s*[:=#-]?\s*([0-9]+(?:\.[0-9]+)?)\b", comment, re.IGNORECASE)
        if match:
            return self._parse_energy(match.group(1))
        if re.fullmatch(r"\s*[0-9]+(?:\.[0-9]+)?\s*", comment):
            return self._parse_energy(comment)
        return None

    def _abrir_cache_metadados(self):
        """Abre o cache persistente das tags, sem impedir o catálogo se houver falha."""
        try:
            cache_path = os.path.join(get_app_storage_dir(), "smart_playlist_metadata_cache.sqlite3")
            conn = sqlite3.connect(cache_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata_cache ("
                "path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, metadata_json TEXT NOT NULL)"
            )
            return conn
        except sqlite3.Error:
            return None

    def _is_valid_candidate(self, base_meta, candidate_meta):
        # GÊNERO obrigatório
        if self._normalize_text(base_meta.get("genre")) != self._normalize_text(candidate_meta.get("genre")):
            return False

        # BPM obrigatório
        base_bpm = base_meta.get("bpm")
        candidate_bpm = candidate_meta.get("bpm")

        if base_bpm and candidate_bpm:
            if abs(base_bpm - candidate_bpm) > 6:
                return False

        # KEY obrigatória (harmônica)
        base_key = self._normalize_key(base_meta.get("key", ""))
        candidate_key = self._normalize_key(candidate_meta.get("key", ""))

        if not self._camelot_compatible(base_key, candidate_key):
            return False

        return True
    
    def _processar_eventos_catalogo(self):
        try:
            while True:
                event = self.catalog_events.get_nowait()
                if event[0] == "progress":
                    self._atualizar_status_carregamento(event[1])
                elif event[0] == "complete":
                    self._aplicar_catalogo_carregado(*event[1:])
                elif event[0] == "selection_progress":
                    processed, total = event[1:]
                    self.progress_bar.set(processed / total if total else 1)
                    self.status_text.set(f"Selecionando faixas similares: {processed}/{total}")
                elif event[0] == "selection_complete":
                    self._concluir_selecao_playlist(*event[1:])
                elif event[0] == "selection_error":
                    self.selection_loading = False
                    self.btn_create.configure(state="normal")
                    self.progress_bar.set(0)
                    messagebox.showerror(self.txt.get("error_title", "Erro"), f"{self.txt.get('smart_playlist_error_saving', 'Não foi possível selecionar as faixas.')}\n{event[1]}")
        except queue.Empty:
            pass
        try:
            self.after(100, self._processar_eventos_catalogo)
        except tk.TclError:
            pass

    def _atualizar_status_carregamento(self, processed):
        self.status_text.set(self.txt.get("smart_playlist_loading_metadata", "Carregando metadados: {processed} músicas analisadas...").format(processed=processed))

    def _aplicar_catalogo_carregado(self, database_paths, track_map, labels, tracks, metadata_by_track_id):
        self.catalog_loading = False
        self.database_paths = database_paths
        self.track_map = track_map
        self.available_track_labels = labels
        self.all_track_objects = tracks
        self.metadata_by_track_id = metadata_by_track_id

        for index, label in enumerate(labels):
            track = track_map[label]
            metadata = self.metadata_by_track_id.get(id(track), {})
            bpm = metadata.get("bpm")
            energy = metadata.get("energy")
            self.track_tree.insert(
                "", tk.END, iid=str(index), text=label,
                values=(
                    metadata.get("title") or track.get("title") or "Sem título",
                    track.get("artist") or "",
                    f"{bpm:g}" if bpm is not None else "—",
                    metadata.get("genre") or "—",
                    metadata.get("key") or "—",
                    f"{energy:g}" if energy is not None else "—",
                ),
            )

        self.progress_bar.set(1)
        if labels:
            self.status_text.set(self.txt.get("smart_playlist_catalog_loaded", "{count} faixas carregadas de {db_count} banco(s).").format(count=len(labels), db_count=len(database_paths)))
        else:
            self.status_text.set(self.txt.get("smart_playlist_no_tracks_found", "Nenhuma faixa disponível nos bancos encontrados."))

    def criar_playlist(self):
        if self.catalog_loading:
            messagebox.showinfo(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_loading_catalog", "Aguarde o carregamento do catálogo terminar..."))
            return
        if self.selection_loading:
            messagebox.showinfo(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_analyzing", "Aguarde a seleção atual terminar."))
            return
        selected_label = self.initial_song.get().strip()
        if not selected_label:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_select_initial_song", "Selecione uma música inicial antes de criar a playlist."))
            return

        track = self.track_map.get(selected_label)
        if not track:
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("smart_playlist_initial_song_not_found", "A música inicial não foi encontrada no catálogo carregado."))
            return

        self.btn_regenerate.configure(state="disabled")
        self.btn_save_engine.configure(state="disabled")
        self.btn_create.configure(state="disabled")
        self.selection_loading = True
        self.status_text.set(self.txt.get("smart_playlist_analyzing", "Analisando e selecionando faixas similares..."))
        self.progress_bar.set(0)
        metadata = self.metadata_by_track_id.get(id(track))
        if metadata is None:
            metadata = self._extract_metadata_from_track(track)
        tracks = list(self.all_track_objects)
        metadata_by_track_id = dict(self.metadata_by_track_id)
        threading.Thread(
            target=self._selecionar_faixas_em_segundo_plano,
            args=(selected_label, track, metadata, tracks, metadata_by_track_id),
            daemon=True,
        ).start()

    def _selecionar_faixas_em_segundo_plano(self, selected_label, base_track, base_metadata, tracks, metadata_by_track_id):
        try:
            quantidade = int(self.playlist_size.get())

            playlist = [base_track]
            usados = {id(base_track)}

            total_tracks = len(tracks)

            for step in range(quantidade - 1):
                ultima = playlist[-1]
                ultima_meta = metadata_by_track_id.get(id(ultima), {})

                candidatos = []

                for index, other_track in enumerate(tracks, start=1):
                    if id(other_track) in usados:
                        continue

                    candidate_meta = metadata_by_track_id.get(id(other_track), {})

                    # 🔒 FILTRO obrigatório
                    if not self._is_valid_candidate(ultima_meta, candidate_meta):
                        continue

                    score = self._score_track(ultima_meta, candidate_meta)

                    if score > 0:
                        candidatos.append((score, other_track))

                    if index % 50 == 0:
                        self.catalog_events.put(("selection_progress", index, total_tracks))

                if not candidatos:
                    break

                candidatos.sort(key=lambda item: item[0], reverse=True)

                # 🎲 leve variação controlada (top 5)
                top = candidatos[:5] if len(candidatos) >= 5 else candidatos
                escolhido = random.choice(top)[1]

                playlist.append(escolhido)
                usados.add(id(escolhido))

            # mantém compatibilidade com resto do código
            result = [(1, track) for track in playlist[1:]]

            self.catalog_events.put(("selection_progress", total_tracks, total_tracks))
            self.catalog_events.put(("selection_complete", selected_label, result))

        except Exception as error:
            self.catalog_events.put(("selection_error", str(error)))

    def _concluir_selecao_playlist(self, selected_label, candidates):
        self.selection_loading = False
        self.btn_create.configure(state="normal")
        if not candidates:
            messagebox.showinfo(self.txt.get("success_title", "Resultado"), self.txt.get("smart_playlist_no_similar_found", "Nenhuma faixa semelhante foi encontrada."))
            self._write_playlist([], selected_label)
            self.progress_bar.set(1)
            self.status_text.set(self.txt.get("smart_playlist_no_similar_found", "Nenhuma faixa semelhante encontrada."))
            return
        self.last_candidates = candidates
        self.generated_playlists = 0
        self._finalizar_playlist(selected_label, candidates)

    def gerar_nova_playlist(self):
        """Gera outra combinação a partir da mesma música inicial."""
        selected_label = self.initial_song.get().strip()
        if not selected_label or not self.last_candidates:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_create_btn", "Crie uma playlist antes de gerar uma nova versão."))
            return
        self._finalizar_playlist(selected_label, self.last_candidates, shuffle=True)

    def _finalizar_playlist(self, selected_label, candidates, shuffle=False):
        quantity = int(self.playlist_size.get())
        base_track = self.track_map.get(selected_label)

        if shuffle:
            # Mantém as faixas mais semelhantes no grupo de escolha, variando a combinação.
            pool_size = min(len(candidates), max(quantity * 2, quantity - 1))
            selected_pairs = random.sample(candidates[:pool_size], min(quantity - 1, pool_size))
        else:
            selected_pairs = candidates[:quantity - 1]

        selected_tracks = [base_track] + [track_data for _, track_data in selected_pairs]
        self.current_selected_tracks = selected_tracks

        self.generated_playlists += 1
        self._write_playlist(selected_tracks, selected_label, self.generated_playlists)

        preview = "\n".join(
            f"{index}. {self._build_track_label(item)}" for index, item in enumerate(selected_tracks, start=1)
        )
        self.result_box.configure(state="normal")
        self.result_box.delete("0.0", tk.END)
        self.result_box.insert("0.0", preview)
        self.result_box.configure(state="disabled")

        self.progress_bar.set(1)
        self.btn_regenerate.configure(state="normal")
        self.btn_save_engine.configure(state="normal")
        self.status_text.set(self.txt.get("smart_playlist_created", "Playlist {count} criada com {song} faixas.").format(count=len(selected_tracks), song=selected_label))
        messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("smart_playlist_created", "Playlist criada com {count} faixas a partir da música '{song}'.").format(count=len(selected_tracks), song=selected_label))

    def salvar_no_engine(self):
        """Persiste a playlist exibida no primeiro banco Engine DJ encontrado."""
        if not self._pode_executar_acao():
            return
        playlist_name = self.playlist_name.get().strip()
        if not playlist_name:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_type_name", "Digite um nome para a playlist."))
            self.playlist_name_entry.focus_set()
            return
        if not self.current_selected_tracks:
            messagebox.showwarning(self.txt.get("warning_title", "Atenção"), self.txt.get("smart_playlist_generate_before_save", "Gere uma playlist antes de salvá-la no Engine DJ."))
            return
        if not self.database_paths:
            messagebox.showerror(self.txt.get("error_title", "Erro"), self.txt.get("smart_playlist_no_db_to_save", "Nenhum banco do Engine DJ está disponível para salvar a playlist."))
            return

        try:
            self._save_playlist_to_engine(self.database_paths[0], playlist_name, self.current_selected_tracks)
        except ValueError as error:
            messagebox.showwarning(self.txt.get("warning_title", "Nome já utilizado"), str(error))
            return
        except Exception as error:
            messagebox.showerror("Erro ao salvar", f"Não foi possível salvar a playlist no Engine DJ.\n{error}")
            return

        self.status_text.set(f"Playlist '{playlist_name}' salva no banco do Engine DJ.")
        messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("smart_playlist_saved", "Playlist '{playlist_name}' salva no Engine DJ com {count} faixas.").format(playlist_name=playlist_name, count=len(self.current_selected_tracks)))

    def _save_playlist_to_engine(self, db_path, playlist_name, tracks):
        """Cria uma playlist raiz e seus vínculos no formato encadeado do Engine DJ."""
        database_uuid = get_database_uuid(db_path)
        if not database_uuid:
            raise RuntimeError("Não foi possível identificar o banco do Engine DJ.")

        with sqlite3.connect(db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM Playlist WHERE title = ? AND (parentListId = 0 OR parentListId IS NULL) LIMIT 1",
                (playlist_name,),
            ).fetchone()
            if existing:
                raise ValueError(self.txt.get("smart_playlist_name_in_use", "Já existe uma playlist com este nome. Escolha outro nome para preservar a playlist existente."))

            now = datetime.now().astimezone().isoformat()
            cursor = conn.execute(
                "INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported) "
                "VALUES (?, 0, 1, 0, ?, 1)",
                (playlist_name, now),
            )
            playlist_id = cursor.lastrowid
            previous_entity_id = None

            for track in tracks:
                track_id = track.get("id")
                if track_id is None:
                    continue
                track_uuid = track.get("databaseUuid") or database_uuid
                cursor = conn.execute(
                    "INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, membershipReference) "
                    "VALUES (?, ?, ?, 0, 0)",
                    (playlist_id, track_id, track_uuid),
                )
                entity_id = cursor.lastrowid
                if previous_entity_id is not None:
                    conn.execute("UPDATE PlaylistEntity SET nextEntityId = ? WHERE id = ?", (entity_id, previous_entity_id))
                previous_entity_id = entity_id

    def _write_playlist(self, selected_tracks, selected_label, version=1):
        base_name = self._sanitize_name(selected_label)
        output_dir = os.path.dirname(self.database_paths[0]) if self.database_paths else os.getcwd()
        suffix = "" if version == 1 else f"_{version}"
        playlist_path = os.path.join(output_dir, f"smart_playlist_{base_name}{suffix}.m3u8")
        with open(playlist_path, "w", encoding="utf-8") as handle:
            handle.write("#EXTM3U\n")
            for track in selected_tracks:
                path = track.get("caminho_absoluto") or track.get("path") or ""
                if path:
                    handle.write(f"{path}\n")

    def _build_track_label(self, track):
        title = track.get("title") or track.get("filename") or "Sem título"
        artist = track.get("artist") or ""
        return f"{title} - {artist}".strip(" -") or "Sem título"

    def _score_track(self, base_meta, candidate_meta):
        score = 0

        # 🎧 KEY (PRIORIDADE MÁXIMA)
        base_key = self._normalize_key(base_meta.get("key", ""))
        candidate_key = self._normalize_key(candidate_meta.get("key", ""))

        base_num = self._camelot_number(base_key)
        candidate_num = self._camelot_number(candidate_key)

        if base_key == candidate_key:
            score += 50  # perfeita
        elif base_num == candidate_num:
            score += 45  # relativo (8A ↔ 8B)
        elif abs(base_num - candidate_num) == 1:
            score += 35  # vizinha

        # 🎚️ BPM
        base_bpm = base_meta.get("bpm")
        candidate_bpm = candidate_meta.get("bpm")

        if base_bpm and candidate_bpm:
            diff = abs(base_bpm - candidate_bpm)
            if diff <= 2:
                score += 30
            elif diff <= 4:
                score += 20
            elif diff <= 6:
                score += 10

        # ⚡ ENERGIA (FLOW)
        base_energy = base_meta.get("energy")
        candidate_energy = candidate_meta.get("energy")

        if base_energy is not None and candidate_energy is not None:
            diff = candidate_energy - base_energy

            if -0.1 <= diff <= 0.2:
                score += 25  # mantém ou sobe leve
            elif -0.2 <= diff <= 0.3:
                score += 15
            else:
                score += 5
                
        return score

    def _normalize_text(self, value):
        if not value:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    def _first_value(self, value):
        if isinstance(value, list):
            return str(value[0]).strip() if value else ""
        if value is None:
            return ""
        return str(value).strip()

    def _normalize_key(self, value):
        if not value:
            return ""
        text = str(value).strip().upper().replace("♭", "B").replace("♯", "#")
        text = text.replace(" ", "")
        text = text.replace("MINOR", "M").replace("MAJOR", "")
        if text.endswith("MIN"):
            text = text[:-3] + "M"
        return text

    def _camelot_compatible(self, base_key, candidate_key):
        if not base_key or not candidate_key:
            return False

        base_num = self._camelot_number(base_key)
        candidate_num = self._camelot_number(candidate_key)

        if not base_num or not candidate_num:
            return False

        base_letter = base_key[-1] if base_key[-1] in ["A", "B"] else None
        candidate_letter = candidate_key[-1] if candidate_key[-1] in ["A", "B"] else None

        return (
            base_num == candidate_num or  # mesma
            abs(base_num - candidate_num) == 1 or  # vizinha
            (base_num == candidate_num and base_letter != candidate_letter)  # relativo
        )

    def _camelot_number(self, key):
        mapping = {
            "1A": 1,
            "2A": 2,
            "3A": 3,
            "4A": 4,
            "5A": 5,
            "6A": 6,
            "7A": 7,
            "8A": 8,
            "9A": 9,
            "10A": 10,
            "11A": 11,
            "12A": 12,
            "1B": 1,
            "2B": 2,
            "3B": 3,
            "4B": 4,
            "5B": 5,
            "6B": 6,
            "7B": 7,
            "8B": 8,
            "9B": 9,
            "10B": 10,
            "11B": 11,
            "12B": 12,
            "C": 8,
            "CM": 8,
            "G": 10,
            "GM": 10,
            "D": 2,
            "DM": 2,
            "A": 4,
            "AM": 4,
            "E": 6,
            "EM": 6,
            "B": 8,
            "BM": 8,
            "F#": 10,
            "F#M": 10,
            "DB": 12,
            "DBM": 12,
            "EB": 1,
            "EBM": 1,
            "AB": 3,
            "ABM": 3,
            "BB": 5,
            "BBM": 5,
            "F": 7,
            "FM": 7,
            "AM": 4,
            "EM": 6,
            "BM": 8,
            "C#": 3,
            "C#M": 3,
            "D#": 12,
            "D#M": 12,
            "G#": 11,
            "G#M": 11,
            "A#": 5,
            "A#M": 5,
        }

        if key in mapping:
            return mapping[key]

        cleaned = key.replace("M", "")
        if cleaned in mapping:
            return mapping[cleaned]
        return None

    def _parse_bpm(self, value):
        if value is None:
            return None
        text = str(value).strip()
        match = re.search(r"(\d{2,4})", text)
        if match:
            return float(match.group(1))
        return None

    def _parse_energy(self, value):
        if value is None:
            return None
        text = str(value).strip()
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        if match:
            return float(match.group(1))
        return None

    def _extract_from_text(self, text, label):
        if not text:
            return ""
        pattern = rf"{label}\s*[:=]\s*([^|,;\n]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_energy_from_comment(self, comment):
        """Lê energia do comentário ID3, aceitando 'Energy: 7', 'Energia=7' ou só '7'."""
        if not comment:
            return None
        match = re.search(r"\b(?:energy|energia)\s*[:=#-]?\s*([0-9]+(?:\.[0-9]+)?)\b", comment, re.IGNORECASE)
        if match:
            return self._parse_energy(match.group(1))
        if re.fullmatch(r"\s*[0-9]+(?:\.[0-9]+)?\s*", comment):
            return self._parse_energy(comment)
        return None

    def _sanitize_name(self, name):
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
        return safe.strip("._") or "playlist"
