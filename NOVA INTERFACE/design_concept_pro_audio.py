import customtkinter as ctk
import tkinter as tk

class ProAudioDesign(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configurações de Janela
        self.title("ENGINE SYNC - INDUSTRIAL CONSOLE")
        self.geometry("600x500")
        self.resizable(False, False)
        
        # --- DESIGN PALETTE (Semantic Colors) ---
        self.color_bg = "#121212"        # Fundo Profundo
        self.color_surface = "#1E1E1E"   # Superfície de Módulos
        self.color_accent = "#FFB300"    # Âmbar (Clássico de equipamentos de áudio)
        self.color_success = "#00E676"   # Verde Ativo
        self.color_text_main = "#E0E0E0" # Texto Principal
        self.color_text_dim = "#757575"  # Texto Secundário / Desativado
        self.color_border = "#333333"    # Bordas de separação

        ctk.set_appearance_mode("Dark")
        self.configure(fg_color=self.color_bg)

        # --- LAYOUT BASE ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=25, pady=25)

        # 1. HEADER TÉCNICO
        self.header = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.header.pack(fill="x", pady=(0, 20))
        
        ctk.CTkLabel(
            self.header, text="ENGINE SYNC", 
            font=ctk.CTkFont(family="Inter", size=24, weight="bold"),
            text_color=self.color_text_main
        ).pack(side="left")
        
        ctk.CTkLabel(
            self.header, text="CONSOLE v2.0", 
            font=ctk.CTkFont(family="JetBrains Mono", size=10),
            text_color=self.color_accent,
            fg_color="#2A2A2A", corner_radius=5, padx=8
        ).pack(side="right")

        # 2. MÓDULO DE STATUS (Semantic Design)
        self.status_card = ctk.CTkFrame(
            self.main_container, fg_color=self.color_surface, 
            border_width=1, border_color=self.color_border, corner_radius=0
        )
        self.status_card.pack(fill="x", pady=(0, 20))
        
        self.status_indicator = ctk.CTkLabel(
            self.status_card, text="● SYSTEM STANDBY", 
            font=ctk.CTkFont(family="JetBrains Mono", size=11, weight="bold"),
            text_color=self.color_accent,
            padx=15, pady=10
        )
        self.status_indicator.pack(side="left")

        # 3. ÁREA DE INPUT (Minimalist & Clean)
        self.input_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.input_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.input_frame, text="SOURCE DIRECTORY", font=ctk.CTkFont(size=10, weight="bold"), text_color=self.color_text_dim).pack(anchor="w")
        self.entry = ctk.CTkEntry(
            self.input_frame, placeholder_text="C:/Users/Music/Library",
            height=40, border_width=1, corner_radius=0,
            fg_color="#0A0A0A", border_color=self.color_border,
            font=ctk.CTkFont(family="Consolas", size=12)
        )
        self.entry.pack(fill="x", pady=(5, 15))

        # 4. TOGGLES (Visual feedback switches)
        self.toggle_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.toggle_frame.pack(fill="x")

        self.switch_1 = ctk.CTkSwitch(
            self.toggle_frame, text="LOG REALTIME", 
            progress_color=self.color_accent, text_color=self.color_text_main,
            font=ctk.CTkFont(size=12)
        )
        self.switch_1.pack(side="left", padx=(0, 20))

        self.switch_2 = ctk.CTkSwitch(
            self.toggle_frame, text="AUTO-BACKUP", 
            progress_color=self.color_accent, text_color=self.color_text_main,
            font=ctk.CTkFont(size=12)
        )
        self.switch_2.pack(side="left")

        # 5. BOTÃO DE AÇÃO PRINCIPAL (High Impact)
        self.btn_execute = ctk.CTkButton(
            self.main_container, text="RUN SYNC PROCESS",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=self.color_accent, text_color="#000000",
            hover_color="#FFA000", height=50, corner_radius=0,
            command=self.on_execute
        )
        self.btn_execute.pack(fill="x", side="bottom")

    def on_execute(self):
        # Transição de design: O "Standby" (Âmbar) vira "Ativo" (Verde)
        self.status_indicator.configure(
            text="● SYNCHRONIZING...", 
            text_color=self.color_success
        )
        self.btn_execute.configure(state="disabled", text="PROCESSING")
        self.after(2000, self.reset_design)

    def reset_design(self):
        self.status_indicator.configure(
            text="● SYNC COMPLETED", 
            text_color=self.color_success
        )
        self.btn_execute.configure(state="normal", text="RUN SYNC PROCESS")

if __name__ == "__main__":
    app = ProAudioDesign()
    app.mainloop()