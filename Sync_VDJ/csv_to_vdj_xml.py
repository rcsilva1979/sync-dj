import os
import sys
import csv
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path

# Importação do utilitário de caminho
if os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) not in sys.path:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine_sync_app import get_resource_path
from constants import STRINGS, get_system_lang

class CSVToVDJConverter(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.txt = STRINGS[get_system_lang()]
        self.title(self.txt.get("csv_converter_title", "Engine DJ CSV to Virtual DJ XML Converter"))
        self.geometry("600x400")
        self.resizable(False, False)
        ctk.set_appearance_mode("Dark")

        # Configuração de Ícone
        self.caminho_icone = get_resource_path(os.path.join("images", "sync_icon.ico"))
        if sys.platform.startswith('win') and os.path.exists(self.caminho_icone):
            try: self.iconbitmap(self.caminho_icone)
            except: pass

        # Variáveis
        self.csv_path = ctk.StringVar()
        self.output_xml = ctk.StringVar()

        self.setup_ui()

    def setup_ui(self):
        # Título
        lbl_title = ctk.CTkLabel(self, text="Conversor de Playlist", font=ctk.CTkFont(size=20, weight="bold"), text_color="#00E5A3")
        lbl_title.pack(pady=(20, 10))

        # Frame Seleção
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=10, fill="x")

        # Selecionar CSV
        lbl_csv = ctk.CTkLabel(frame, text="Arquivo CSV do Engine DJ:", font=ctk.CTkFont(weight="bold"))
        lbl_csv.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        
        entry_csv = ctk.CTkEntry(frame, textvariable=self.csv_path, width=400)
        entry_csv.grid(row=1, column=0, padx=10, pady=5)
        
        btn_csv = ctk.CTkButton(frame, text="Procurar", width=100, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", command=self.select_csv)
        btn_csv.grid(row=1, column=1, padx=10, pady=5)

        # Log de status
        self.txt_log = ctk.CTkTextbox(self, height=150, width=560)
        self.txt_log.pack(pady=10, padx=20)
        self.log("Pronto para converter.")

        # Botão Converter
        self.btn_convert = ctk.CTkButton(self, text="Transformar em XML", font=ctk.CTkFont(size=16, weight="bold"), 
                                         height=45, fg_color="#00E5A3", text_color="#000000", hover_color="#00b37e", 
                                         command=self.process_conversion)
        self.btn_convert.pack(pady=20)

    def log(self, message):
        self.txt_log.insert("end", f"[{Path(self.csv_path.get()).name if self.csv_path.get() else 'SISTEMA'}] {message}\n")
        self.txt_log.see("end")

    def select_csv(self):
        path = filedialog.askopenfilename(filetypes=[("Arquivo CSV", "*.csv")])
        if path:
            self.csv_path.set(path) # type: ignore
            self.log(f"CSV selecionado: {path}")

    def time_to_seconds(self, time_str):
        """Converte MM:SS ou HH:MM:SS para segundos."""
        try:
            parts = list(map(int, time_str.split(':')))
            if len(parts) == 2: return float(parts[0] * 60 + parts[1])
            if len(parts) == 3: return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
            return float(time_str)
        except:
            return 0.0

    def process_conversion(self):
        csv_file = self.csv_path.get()
        if not csv_file or not os.path.exists(csv_file): # type: ignore
            messagebox.showerror("Erro", "Selecione um arquivo CSV válido.")
            return

        output_path = filedialog.asksaveasfilename(defaultextension=".xml", filetypes=[("XML Playlist", "*.xml")], 
                                                   initialfile=Path(csv_file).stem + ".xml")
        if not output_path:
            return

        try:
            # Criar estrutura XML do Virtual DJ
            root = ET.Element("VirtualFolder", noDuplicates="yes")

            with open(csv_file, mode='r', encoding='utf-8-sig') as f:
                # O Engine DJ costuma usar vírgula ou ponto e vírgula
                sample = f.read(2048)
                f.seek(0)
                dialect = csv.Sniffer().sniff(sample)
                reader = csv.DictReader(f, dialect=dialect)

                count = 0
                for idx, row in enumerate(reader):
                    # Mapeamento de campos (Ajuste os nomes das colunas se o seu CSV for diferente)
                    # Campos comuns no CSV do Engine DJ: Title, Artist, Album, Length, Location, BPM, Key
                    raw_path = row.get("File name") or row.get("Location") or row.get("Path") or row.get("File Path") or ""
                    # Normaliza barras para o padrão Windows
                    path = raw_path.replace('/', '\\')
                    
                    title = row.get("Title") or ""
                    artist = row.get("Artist") or ""
                    bpm = row.get("BPM") or "0.000"
                    key = row.get("Key") or ""
                    length = self.time_to_seconds(row.get("Length", "0"))
                    
                    size = "0"
                    if raw_path and os.path.exists(raw_path):
                        size = str(os.path.getsize(raw_path))

                    # Criar elemento song
                    song = ET.SubElement(root, "song")
                    song.set("path", path)
                    song.set("size", size)
                    song.set("songlength", str(length))
                    song.set("bpm", bpm)
                    song.set("key", key)
                    song.set("artist", artist)
                    song.set("title", title)
                    song.set("idx", str(idx))

                    count += 1

            # Salvar com indentação (Pretty Print)
            xml_str = ET.tostring(root, encoding='utf-8')
            dom = minidom.parseString(xml_str)
            # Virtual DJ costuma preferir tabulações ou espaços simples
            pretty_xml = dom.toprettyxml(indent="\t", encoding="UTF-8").decode("UTF-8")

            with open(output_path, "wb") as f:
                f.write(pretty_xml.encode("UTF-8"))

            self.log(self.txt.get("success_tracks_converted", "Sucesso! {count} músicas convertidas.").format(count=count))
            messagebox.showinfo(self.txt.get("success_title", "Sucesso"), self.txt.get("success_xml_generated", "Playlist XML gerada com sucesso!\n{count} músicas processadas.").format(count=count))

        except Exception as e:
            self.log(f"ERRO: {str(e)}")
            messagebox.showerror(self.txt.get("error_conversion_title", "Erro na Conversão"), self.txt.get("error_processing_csv", "Ocorreu um erro ao processar o CSV:\n{error}").format(error=e))

if __name__ == "__main__":
    app = CSVToVDJConverter()
    app.mainloop()