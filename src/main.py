# src/main.py
import logging
from tkinter import messagebox

import customtkinter as ctk
from ytdlp_tab import YtdlpTab
from converter_tab import ConverterTab

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


class App:
    MIN_WIDTH = 940
    MIN_HEIGHT = 560
    START_WIDTH = 1180
    START_HEIGHT = 780

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.window = ctk.CTk()
        self.window.title("Easy Visualise")
        self._setup_geometry()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.tabs = ctk.CTkTabview(self.window)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)

        # Aba yt-dlp
        self.tabs.add("🎬 yt-dlp")
        ytdlp_frame = self.tabs.tab("🎬 yt-dlp")
        self.ytdlp_tab = YtdlpTab(ytdlp_frame)

        # Aba Conversor
        self.tabs.add("🔄 Conversor")
        converter_frame = self.tabs.tab("🔄 Conversor")
        self.converter_tab = ConverterTab(converter_frame)

    def _setup_geometry(self):
        try:
            scaling = ctk.ScalingTracker.get_window_scaling(self.window)
        except Exception:
            scaling = 1.0
        screen_w = int(self.window.winfo_screenwidth() / scaling)
        screen_h = int(self.window.winfo_screenheight() / scaling)
        width = min(self.START_WIDTH, max(self.MIN_WIDTH, screen_w - 100))
        height = min(self.START_HEIGHT, max(self.MIN_HEIGHT, screen_h - 140))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.window.resizable(True, True)

    def on_close(self):
        # Pergunta uma única vez e só cancela os processos depois de confirmado
        busy = []
        if self.ytdlp_tab.is_busy():
            busy.append("downloads")
        if self.converter_tab.is_busy():
            busy.append("conversões")

        if busy:
            if not messagebox.askyesno(
                "Sair", f"Há {' e '.join(busy)} em andamento. Sair mesmo assim?"
            ):
                return
            self.ytdlp_tab.shutdown()
            self.converter_tab.shutdown()

        self.window.destroy()

    def run(self):
        self.window.mainloop()


if __name__ == "__main__":
    app = App()
    app.run()