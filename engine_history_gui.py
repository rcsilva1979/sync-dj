import os
import sqlite3
import string
import textwrap
import traceback
from datetime import datetime
import threading
from tkinter import filedialog, messagebox, Label

import customtkinter as ctk
from constants import (FONT_FAMILY, COLOR_TEXT_NORMAL, COLOR_TEXT_MUTED, COLOR_BG_DARK,
                       COLOR_ACCENT_BLUE, CORNER_RADIUS_NONE, COLOR_ACCENT_GREEN,
                       APP_NAME, VERSAO_ATUAL)
from engine_sync_app import get_resource_path
from PIL import Image, ImageDraw, ImageFont, ImageTk
from database_utils import localizar_bancos_dados_engine, localizar_bancos_dados_removiveis


class EngineHistoryWindow(ctk.CTkToplevel):
    """
    Janela para listar arquivos hm.db encontrados nos discos, listar os historylists
    e, ao selecionar um historylist, mostrar as faixas tocadas na ordem.
    """
    def __init__(self, master, txt_strings):
        super().__init__(master)
        self.txt = txt_strings
        self.title(self.txt.get('history_title', 'Histórico de Eventos'))
        self.geometry("900x520")
        self.resizable(True, True)

        self.configure(fg_color=COLOR_BG_DARK)
        
        # Trazer janela para frente e capturar foco
        self.grab_set()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

        # Header (logo fallback to title)
        try:
            img_caminho = get_resource_path(os.path.join('images', 'logo_engine.png'))
            if os.path.exists(img_caminho):
                imagem_logo = Image.open(img_caminho)
                ctk_logo = ctk.CTkImage(light_image=imagem_logo, dark_image=imagem_logo, size=(480, 90))
                lbl_logo = ctk.CTkLabel(self, text='', image=ctk_logo)
                lbl_logo.pack(pady=(8, 6))
            else:
                raise FileNotFoundError
        except Exception:
            header = ctk.CTkLabel(self, text=self.txt.get('history_title', 'Histórico de Eventos').upper(),
                                  font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"), text_color=COLOR_ACCENT_BLUE)
            header.pack(pady=(12, 6))

        # Containers
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=12)
        left_frame = ctk.CTkFrame(container, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right_frame = ctk.CTkFrame(container, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True)

        # Left: controls + history list
        ctrl_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        ctrl_frame.pack(fill="x", pady=(0, 8))

        self.btn_refresh = ctk.CTkButton(ctrl_frame, text=self.txt.get('refresh', 'Atualizar'), command=self.start_scan_thread,
                 fg_color=COLOR_ACCENT_GREEN, text_color=COLOR_TEXT_NORMAL,
                 font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                 height=40, width=140, corner_radius=CORNER_RADIUS_NONE)
        self.btn_refresh.pack(side="left")

        self.lbl_status = ctk.CTkLabel(ctrl_frame, text="", anchor="w", text_color=COLOR_TEXT_MUTED,
                           font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.lbl_status.pack(side="left", padx=8)

        self.history_scroll = ctk.CTkScrollableFrame(left_frame, fg_color="#141414")
        self.history_scroll.pack(fill="both", expand=True)

        # Right: tracks for selected history
        self.tracks_scroll = ctk.CTkScrollableFrame(right_frame, fg_color="#141414")
        self.tracks_scroll.pack(fill="both", expand=True)

        # internal
        self.hm_paths = []  # list of found hm.db paths
        self.history_items = []  # tuples (db_path, rowdict)
        self.selected_history = None
        self.selected_tracks = []
        self.selected_share_tracks = []
        self.font_size_var = ctk.IntVar(value=26)
        self.alignment_var = ctk.StringVar(value='Esquerdo')

        # initial scan (run in background to avoid blocking UI)
        self.start_scan_thread()

        # Actions
        actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        actions_frame.pack(fill="x", padx=20, pady=(10, 4))

        self.btn_export = ctk.CTkButton(actions_frame, text=self.txt.get('export_title', 'Exportar'),
                                         command=self.export_history,
                                         fg_color=COLOR_ACCENT_BLUE, text_color=COLOR_TEXT_NORMAL,
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                         corner_radius=CORNER_RADIUS_NONE, height=42, width=180)
        self.btn_export.pack(side='left', padx=(0, 10))

        self.btn_share = ctk.CTkButton(actions_frame, text=self.txt.get('share_btn', 'Compartilhar'),
                                        command=self.share_history,
                                        fg_color=COLOR_ACCENT_GREEN, text_color=COLOR_TEXT_NORMAL,
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                        corner_radius=CORNER_RADIUS_NONE, height=42, width=180)
        self.btn_share.pack(side='left')

        # Footer
        lbl_footer = ctk.CTkLabel(self, text=f"{APP_NAME} ({VERSAO_ATUAL})",
                                  font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLOR_TEXT_MUTED)
        lbl_footer.pack(side='bottom', pady=(5, 10))

    def start_scan_thread(self):
        """Inicia a varredura por hm.db em thread separada."""
        try:
            self.btn_refresh.configure(state="disabled")
        except Exception:
            pass
        self.lbl_status.configure(text="Procurando hm.db...")
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()

    def _scan_worker(self):
        history_items = []
        hm_paths = []
        # Reaproveita a lógica existente que localiza os m.db e procura hm.db nas mesmas pastas
        try:
            mdbs = localizar_bancos_dados_engine() or []
        except Exception:
            mdbs = []
        try:
            removable = localizar_bancos_dados_removiveis() or []
        except Exception:
            removable = []

        all_mdbs = sorted(set(mdbs + removable))
        found = []
        for mdb in all_mdbs:
            try:
                parent_dir = os.path.dirname(mdb)
                candidate = os.path.join(parent_dir, 'hm.db')
                if os.path.exists(candidate):
                    found.append(os.path.normpath(candidate))
                else:
                    # Também verifica na raiz da Engine Library (um nível acima)
                    alt = os.path.join(os.path.dirname(parent_dir), 'hm.db')
                    if os.path.exists(alt):
                        found.append(os.path.normpath(alt))
            except Exception:
                continue

        hm_paths = sorted(set(found))

        for dbpath in hm_paths:
            try:
                conn = sqlite3.connect(dbpath)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT id, title, startTime, timezone, originDriveName FROM historylist WHERE isDeleted IS NULL OR isDeleted = 0 ORDER BY startTime DESC")
                rows = cur.fetchall()
                for r in rows:
                    rd = dict(r)
                    rd['_dbpath'] = dbpath
                    history_items.append((dbpath, rd))
                conn.close()
            except Exception:
                traceback.print_exc()
                continue

        # sort global by startTime desc
        history_items.sort(key=lambda x: x[1].get('startTime') or 0, reverse=True)

        # schedule UI update in main thread
        self.after(0, lambda: self.on_scan_complete(history_items, hm_paths))

    def on_scan_complete(self, history_items, hm_paths):
        self.history_items = history_items
        self.hm_paths = hm_paths
        if not self.hm_paths:
            self.lbl_status.configure(text="Nenhum hm.db encontrado nas unidades.")
        else:
            self.lbl_status.configure(text=f"{len(self.history_items)} históricos encontrados em {len(self.hm_paths)} banco(s)")
        self.populate_history_list()
        try:
            self.btn_refresh.configure(state="normal")
        except Exception:
            pass

    def populate_history_list(self):
        # clear
        for w in self.history_scroll.winfo_children():
            w.destroy()

        if not self.history_items:
            if self.hm_paths:
                lbl = ctk.CTkLabel(self.history_scroll, text=self.txt.get('all_dbs_label', '>>> TODOS OS BANCOS LOCALIZADOS <<<'),
                                    text_color=COLOR_ACCENT_BLUE, font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight='bold'))
                lbl.pack(pady=(6, 4))
                for p in self.hm_paths:
                    p_label = ctk.CTkLabel(self.history_scroll, text=p, text_color=COLOR_TEXT_MUTED,
                                           font=ctk.CTkFont(family=FONT_FAMILY, size=11))
                    p_label.pack(anchor='w', padx=6, pady=2)
            else:
                lbl = ctk.CTkLabel(self.history_scroll, text=self.txt.get('no_playlists_found_generic', '(nenhum histórico disponível)'),
                                    text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
                lbl.pack(pady=6)
            return

        for dbpath, rd in self.history_items:
            ts = rd.get('startTime')
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts))
                    date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    date_str = str(ts)
            else:
                date_str = ''

            title = rd.get('title') or ''
            origin = rd.get('originDriveName') or os.path.basename(os.path.dirname(dbpath))

            text = f"{date_str} — {title} ({origin})"

            btn = ctk.CTkButton(self.history_scroll, text=text, anchor='w', width=1000,
                                 command=lambda d=dbpath, lid=rd.get('id'): self.load_history_tracks(d, lid),
                                 fg_color=COLOR_BG_DARK, text_color=COLOR_TEXT_NORMAL,
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                 height=40, corner_radius=CORNER_RADIUS_NONE)
            btn.pack(fill='x', pady=4, padx=4)

    def load_history_tracks(self, dbpath, list_id):
        # clear tracks
        for w in self.tracks_scroll.winfo_children():
            w.destroy()

        if not dbpath or list_id is None:
            lbl = ctk.CTkLabel(self.tracks_scroll, text="Histórico inválido selecionado",
                               text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
            lbl.pack(pady=6)
            return

        try:
            conn = sqlite3.connect(dbpath)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            q = ("SELECT e.startTime as entryTime, t.id as trackId, t.title as title, t.artist as artist, t.filename as filename, t.path as path "
                 "FROM historyListEntity e JOIN track t ON e.trackId = t.id "
                 "WHERE e.listId = ? ORDER BY e.startTime ASC")
            cur.execute(q, (list_id,))
            rows = cur.fetchall()

            self.selected_tracks = []
            self.selected_history = None

            if not rows:
                lbl = ctk.CTkLabel(self.tracks_scroll, text="(nenhuma faixa encontrada)",
                                   text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
                lbl.pack(pady=6)
                conn.close()
                return

            # Save selected history title from loaded list item
            matching = next((item for item in self.history_items if item[0] == dbpath and item[1].get('id') == list_id), None)
            if matching:
                self.selected_history = matching[1].get('title') or self.txt.get('history_title', 'Histórico de Eventos')
            else:
                self.selected_history = self.txt.get('history_title', 'Histórico de Eventos')

            idx = 1
            for r in rows:
                rd = dict(r)
                et = rd.get('entryTime')
                try:
                    dt = datetime.fromtimestamp(int(et))
                    time_str = dt.strftime('%H:%M:%S')
                except Exception:
                    time_str = str(et)

                title = rd.get('title') or rd.get('filename') or ''
                artist = rd.get('artist') or ''
                display = f"{idx:02d}. {title} — {artist}  [{time_str}]"
                share_text = f"{artist} - {title}" if artist and title else title or artist

                self.selected_tracks.append(display)
                self.selected_share_tracks.append(share_text)

                lbl = ctk.CTkLabel(self.tracks_scroll, text=display, anchor='w', text_color=COLOR_TEXT_NORMAL,
                                   font=ctk.CTkFont(family=FONT_FAMILY, size=11))
                lbl.pack(fill='x', padx=6, pady=2)
                idx += 1

            conn.close()
        except Exception:
            traceback.print_exc()
            lbl = ctk.CTkLabel(self.tracks_scroll, text="Erro ao abrir o banco de dados ou consultar faixas",
                               text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=12))
            lbl.pack(pady=6)

    def export_history(self):
        """Placeholder para futura exportação de histórico."""
        messagebox.showinfo(self.txt.get('export_title', 'Exportar'),
                            self.txt.get('export_history_placeholder', 'Função de exportação será implementada em breve.'))

    def decrease_font_size(self):
        current = self.font_size_var.get()
        if current > 12:
            self.font_size_var.set(current - 2)
            self._refresh_share_preview()

    def increase_font_size(self):
        current = self.font_size_var.get()
        if current < 48:
            self.font_size_var.set(current + 2)
            self._refresh_share_preview()

    def on_alignment_changed(self, value):
        self.alignment_var.set(value)
        self._refresh_share_preview()

    def save_share_image(self):
        if not hasattr(self, '_last_shared_image') or self._last_shared_image is None:
            messagebox.showwarning(self.txt.get('warning_title', 'Aviso'),
                                   self.txt.get('no_tracks_in_playlist', 'Nenhuma música encontrada nesta playlist.'))
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension='.png',
            filetypes=[('PNG Image', '*.png')],
            title=self.txt.get('save_btn', 'Salvar'))
        if save_path:
            try:
                self._last_shared_image.save(save_path)
                messagebox.showinfo(self.txt.get('success_title', 'Sucesso'),
                                    self.txt.get('saved_image_message', 'Imagem salva com sucesso.'))
            except Exception as e:
                messagebox.showerror(self.txt.get('error_title', 'Erro'), str(e))

    def _create_share_image(self):
        wallpaper_path = get_resource_path(os.path.join('images', 'SETLIST_1.jpg'))
        if not os.path.exists(wallpaper_path):
            raise FileNotFoundError(f"Wallpaper não encontrado: {wallpaper_path}")

        img = Image.open(wallpaper_path).convert('RGBA')
        draw = ImageDraw.Draw(img)

        min_x, min_y = 63.6, 433.5
        max_x, max_y = 1014.9, 1846.4
        font_size = self.font_size_var.get()
        line_height = int(font_size * 1.4)
        current_y = min_y
        max_width = int(max_x - min_x)

        try:
            small_font = ImageFont.truetype('Consolas.ttf', font_size)
        except Exception:
            try:
                small_font = ImageFont.truetype('consola.ttf', font_size)
            except Exception:
                small_font = ImageFont.load_default()

        def wrapped_lines(text, font_obj):
            words = text.split()
            lines = []
            current = ''
            for word in words:
                test = f"{current} {word}".strip()
                bbox = draw.textbbox((0, 0), test, font=font_obj)
                if bbox[2] - bbox[0] <= max_width:
                    current = test
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            return lines

        align = self.alignment_var.get()
        for share_text in self.selected_share_tracks:
            if current_y + line_height > max_y:
                break
            wrapped = wrapped_lines(share_text, small_font)
            for line in wrapped:
                if current_y + line_height > max_y:
                    break
                bbox = draw.textbbox((0, 0), line, font=small_font)
                text_width = bbox[2] - bbox[0]
                if align == 'Centralizado':
                    x = min_x + max(0, (max_width - text_width) / 2)
                elif align == 'Direito':
                    x = min_x + max(0, max_width - text_width)
                else:
                    x = min_x
                draw.text((x, current_y), line, font=small_font, fill=(255, 255, 255, 255))
                current_y += line_height
            current_y += 4
            if current_y > max_y:
                break

        return img

    def _refresh_share_preview(self):
        """Atualiza o preview da imagem compartilhada em tempo real.
        
        Dimensões do thumbnail para preview:
        - Largura: 420px (ajustado para janela de 600px com padding)
        - Altura: 750px (proporcional à imagem original 1080x1920)
        - A imagem salva permanece no tamanho original 1080x1920
        """
        if not hasattr(self, '_share_preview_label') or self._share_preview_label is None:
            return
        try:
            self._last_shared_image = self._create_share_image()
            preview_image = self._last_shared_image.copy()
            preview_image.thumbnail((420, 750), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(preview_image)
            self._share_preview_label.configure(image=self._preview_photo)
        except Exception:
            pass

    def share_history(self):
        """Cria uma imagem com wallpaper e lista de músicas e abre a janela de preview."""
        if not self.selected_tracks:
            messagebox.showwarning(self.txt.get('warning_title', 'Aviso'),
                                   self.txt.get('no_tracks_in_playlist', 'Nenhuma música encontrada nesta playlist.'))
            return

        try:
            self._last_shared_image = self._create_share_image()
            self._open_share_preview(self._last_shared_image)
        except Exception as e:
            messagebox.showerror(self.txt.get('error_title', 'Erro'), str(e))

    def _open_share_preview(self, image):
        """Abre janela de preview com controles de customização.
        
        Dimensões da janela de preview (600x800):
        - Largura: 600px (fixa)
        - Altura: 800px (fixa)
        - Composição interna:
          * Título: ~50px
          * Controles (Fonte + Alinhamento): ~60px
          * Preview da imagem: 420x750px (thumbnail redimensionado)
          * Botões (Salvar/Fechar): ~50px
          * Paddings internos: ~40px
        
        A imagem final salva tem dimensões originais (1080x1920).
        """
        preview = ctk.CTkToplevel(self)
        preview.title(self.txt.get('share_btn', 'Compartilhar'))
        preview.geometry('600x750')
        preview.configure(fg_color=COLOR_BG_DARK)
        preview.lift()
        preview.attributes('-topmost', True)
        preview.after(100, lambda: preview.attributes('-topmost', False))

        lbl_title = ctk.CTkLabel(preview, text=self.txt.get('share_btn', 'Compartilhar'),
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight='bold'),
                                 text_color=COLOR_ACCENT_BLUE)
        lbl_title.pack(pady=(16, 12))

        controls_frame = ctk.CTkFrame(preview, fg_color='transparent')
        controls_frame.pack(fill='x', padx=20, pady=(0, 12))

        lbl_font = ctk.CTkLabel(controls_frame, text='Fonte:',
                                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight='bold'),
                                text_color=COLOR_TEXT_NORMAL)
        lbl_font.pack(side='left', padx=(0, 8))

        btn_decrease = ctk.CTkButton(controls_frame, text='-', command=self.decrease_font_size,
                                     fg_color=COLOR_BG_DARK, text_color=COLOR_TEXT_NORMAL,
                                     width=32, height=32, corner_radius=CORNER_RADIUS_NONE)
        btn_decrease.pack(side='left')

        lbl_font_size = ctk.CTkLabel(controls_frame, textvariable=self.font_size_var,
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                                     text_color=COLOR_TEXT_NORMAL)
        lbl_font_size.pack(side='left', padx=8)

        btn_increase = ctk.CTkButton(controls_frame, text='+', command=self.increase_font_size,
                                     fg_color=COLOR_BG_DARK, text_color=COLOR_TEXT_NORMAL,
                                     width=32, height=32, corner_radius=CORNER_RADIUS_NONE)
        btn_increase.pack(side='left', padx=(0, 18))

        lbl_align = ctk.CTkLabel(controls_frame, text='Alinhamento:',
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight='bold'),
                                 text_color=COLOR_TEXT_NORMAL)
        lbl_align.pack(side='left', padx=(0, 8))

        align_buttons = ctk.CTkSegmentedButton(controls_frame,
                                               values=['Esquerdo', 'Centralizado', 'Direito'],
                                               variable=self.alignment_var,
                                               command=self.on_alignment_changed,
                                               fg_color=COLOR_BG_DARK,
                                               selected_color=COLOR_ACCENT_BLUE,
                                               text_color=COLOR_TEXT_NORMAL,
                                               width=260,
                                               corner_radius=CORNER_RADIUS_NONE)
        align_buttons.pack(side='left')

        img_preview = image.copy()
        # Thumbnail para preview: 420x750px (proporcional a 1080x1920, cabe em 600x800)
        img_preview.thumbnail((420, 750), Image.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(img_preview)
        self._share_preview_label = Label(preview, image=self._preview_photo, bd=0)
        self._share_preview_label.pack(padx=12, pady=(0, 12))

        btn_frame = ctk.CTkFrame(preview, fg_color='transparent')
        btn_frame.pack(pady=(0, 12))

        btn_save = ctk.CTkButton(btn_frame, text=self.txt.get('save_btn', 'Salvar'),
                                  command=self.save_share_image,
                                  fg_color=COLOR_ACCENT_BLUE, text_color=COLOR_TEXT_NORMAL,
                                  font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight='bold'),
                                  corner_radius=CORNER_RADIUS_NONE, height=36, width=120)
        btn_save.pack(side='left', padx=(0, 10))

        btn_close = ctk.CTkButton(btn_frame, text=self.txt.get('close_btn', 'Fechar'),
                                   command=preview.destroy,
                                   fg_color=COLOR_ACCENT_BLUE, text_color=COLOR_TEXT_NORMAL,
                                   font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight='bold'),
                                   corner_radius=CORNER_RADIUS_NONE, height=36, width=120)
        btn_close.pack(side='left')
