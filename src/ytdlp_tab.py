# src/ytdlp_tab.py
import logging
import os
import queue
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from downloader import Downloader, RESULT_CANCELLED, RESULT_OK

logger = logging.getLogger(__name__)

# Qualidades fixas pra MP3 (sempre disponíveis via ffmpeg)
MP3_QUALITIES = ["320 kbps", "256 kbps", "192 kbps", "128 kbps", "96 kbps"]
DEFAULT_VIDEO_QUALITIES = ["1080p", "720p", "480p", "360p", "240p", "144p"]

FORMAT_MP3 = "MP3 (Áudio)"
FORMAT_MP4 = "MP4 (Vídeo)"
PLACEHOLDER = "Selecione..."
NAME_PLACEHOLDER = "Deixe vazio para usar o título original"

# Status de cada item da fila
STATUS_PENDING = "pending"
STATUS_DOWNLOADING = "downloading"
STATUS_ERROR = "error"

PANEL_COLOR = ("gray85", "gray20")
ITEM_COLOR = ("gray75", "gray25")
BTN_NEUTRAL = ("gray65", "gray35")
BTN_NEUTRAL_HOVER = ("gray60", "gray40")


class YtdlpTab:
    def __init__(self, parent_frame):
        self.parent = parent_frame
        self.root = parent_frame.winfo_toplevel()

        # Fila e estado do download
        self.download_queue = []
        self.is_downloading = False
        self.cancel_requested = False
        self.current_item = None
        self.current_fraction = 0.0
        self.batch_done = 0
        self.batch_failed = 0

        # Estado do formulário
        self.available_qualities = []
        self.qualities_fetched = False
        self.editing_item = None
        self.current_video_title = ""
        self._fetching = False

        # Playlist
        self.is_playlist = False
        self.playlist_data = None
        self.playlist_checkboxes = []

        # Controle de interface
        self.queue_rows = []
        self._queue_text_limit = 0
        self._resize_job = None
        self._status_job = None

        # Eventos vindos de outras threads: a UI só é tocada pela thread principal
        self.ui_queue = queue.Queue()

        self.downloader = Downloader(
            progress_callback=lambda value: self._post(self._on_progress, value),
            log_callback=lambda message: self._post(self._append_log, message),
        )

        self.setup_ui()
        self._poll_ui_queue()

        if self.downloader.missing_tools:
            self.root.after(500, self._warn_missing_tools)

    # ------------------------------------------------------------------
    # Comunicação thread -> interface
    # ------------------------------------------------------------------
    def _post(self, func, *args):
        """Agenda func(*args) para rodar na thread principal (seguro de qualquer thread)."""
        self.ui_queue.put((func, args))

    def _poll_ui_queue(self):
        try:
            while True:
                func, args = self.ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    logger.exception("Erro ao atualizar a interface")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def setup_ui(self):
        # Duas colunas: formulário (esquerda) e fila/status (direita)
        self.parent.grid_columnconfigure(0, weight=3, uniform="cols")
        self.parent.grid_columnconfigure(1, weight=2, uniform="cols")
        self.parent.grid_rowconfigure(0, weight=1)

        self._build_left_column()
        self._build_right_column()

        self.parent.bind("<Configure>", self._on_resize, add="+")

    def _build_left_column(self):
        self.left = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        self.left.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        left = self.left

        # Cabeçalho
        top_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        top_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            top_frame,
            text="🎬 Easy Visualise",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left", padx=15, pady=10)

        ctk.CTkButton(
            top_frame, text="ℹ️ Info", width=70, height=30,
            command=self.show_info
        ).pack(side="right", padx=(5, 15), pady=10)

        self.update_btn = ctk.CTkButton(
            top_frame, text="🔄 Atualizar", width=110, height=30,
            command=self.update_ytdlp
        )
        self.update_btn.pack(side="right", padx=5, pady=10)

        # Campo de URL
        url_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        url_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            url_frame, text="Cole o link aqui:", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        url_row = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_row.pack(fill="x", padx=15, pady=(0, 15))

        self.fetch_btn = ctk.CTkButton(
            url_row, text="🔍 Buscar", width=110, height=40,
            command=self.fetch_qualities
        )
        self.fetch_btn.pack(side="right")

        self.url_entry = ctk.CTkEntry(
            url_row, height=40,
            placeholder_text="https://www.youtube.com/watch?v=..."
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda event: self.fetch_qualities())

        # Título do vídeo
        self.video_title_label = ctk.CTkLabel(
            left, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray20", "gray80"),
            wraplength=440, justify="left"
        )
        self.video_title_label.pack(pady=(5, 5), padx=15, fill="x")

        # Container da playlist (escondido inicialmente)
        self.playlist_container = ctk.CTkFrame(left, fg_color=PANEL_COLOR)

        playlist_header = ctk.CTkFrame(self.playlist_container, fg_color="transparent")
        playlist_header.pack(fill="x", padx=15, pady=(15, 5))

        self.playlist_title_label = ctk.CTkLabel(
            playlist_header, text="📂 Playlist",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.playlist_title_label.pack(side="left")

        playlist_btns = ctk.CTkFrame(playlist_header, fg_color="transparent")
        playlist_btns.pack(side="right")

        ctk.CTkButton(
            playlist_btns, text="✅ Todos", width=75, height=28,
            font=ctk.CTkFont(size=11), command=self.select_all_playlist
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            playlist_btns, text="❌ Nenhum", width=75, height=28,
            font=ctk.CTkFont(size=11), command=self.deselect_all_playlist
        ).pack(side="left", padx=2)

        self.playlist_scroll = ctk.CTkScrollableFrame(
            self.playlist_container, height=180, fg_color="transparent"
        )
        self.playlist_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # Status de busca
        self.fetch_status = ctk.CTkLabel(
            left, text="", font=ctk.CTkFont(size=11),
            text_color="gray", wraplength=440, justify="left"
        )
        self.fetch_status.pack(pady=2, padx=15, fill="x")

        # Formato e qualidade
        format_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        format_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            format_frame, text="Formato e Qualidade:", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        options_row = ctk.CTkFrame(format_frame, fg_color="transparent")
        options_row.pack(fill="x", padx=15, pady=(0, 15))
        options_row.grid_columnconfigure((0, 1), weight=1, uniform="opts")

        format_inner = ctk.CTkFrame(options_row, fg_color="transparent")
        format_inner.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkLabel(format_inner, text="Formato:").pack(anchor="w")
        self.format_var = ctk.StringVar(value=PLACEHOLDER)
        self.format_menu = ctk.CTkOptionMenu(
            format_inner, values=[PLACEHOLDER], variable=self.format_var,
            width=120, command=self.on_format_change, state="disabled"
        )
        self.format_menu.pack(fill="x")

        quality_inner = ctk.CTkFrame(options_row, fg_color="transparent")
        quality_inner.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(quality_inner, text="Qualidade:").pack(anchor="w")
        self.quality_var = ctk.StringVar(value=PLACEHOLDER)
        self.quality_menu = ctk.CTkOptionMenu(
            quality_inner, values=[PLACEHOLDER], variable=self.quality_var,
            width=120, state="disabled"
        )
        self.quality_menu.pack(fill="x")

        # Nome do arquivo
        name_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        name_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            name_frame, text="Nome do arquivo (opcional):",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        self.name_entry = ctk.CTkEntry(
            name_frame, height=35,
            placeholder_text=NAME_PLACEHOLDER,
            state="disabled"
        )
        self.name_entry.pack(fill="x", padx=15, pady=(0, 15))

        # Adicionar / confirmar edição
        add_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        add_frame.pack(fill="x", pady=5)

        self.add_queue_btn = ctk.CTkButton(
            add_frame, text="➕ Adicionar à Fila", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.add_to_queue
        )
        self.add_queue_btn.pack(fill="x", pady=15, padx=15)
        self._set_add_button("disabled")

        self.cancel_edit_btn = ctk.CTkButton(
            add_frame, text="↩️ Cancelar edição", height=34,
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            command=self._cancel_edit
        )  # só aparece durante uma edição

        # Pasta de destino
        path_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        path_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(
            path_frame, text="Salvar em:", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        path_inner = ctk.CTkFrame(path_frame, fg_color="transparent")
        path_inner.pack(fill="x", padx=15, pady=(0, 15))

        browse_btn = ctk.CTkButton(
            path_inner, text="📁", width=50, height=35,
            command=self.browse_folder
        )
        browse_btn.pack(side="right")

        self.path_entry = ctk.CTkEntry(
            path_inner, height=35, placeholder_text="Selecione uma pasta..."
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        default_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
        self.path_entry.insert(0, default_path)

    def _build_right_column(self):
        self.right = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.right.grid(row=0, column=1, sticky="nsew", padx=(0, 5), pady=5)

        self.right.grid_columnconfigure(0, weight=1)
        # Fila e log dividem o espaço sobrando (3:2); os controles ficam com o tamanho natural
        self.right.grid_rowconfigure(0, weight=3, uniform="rows")
        self.right.grid_rowconfigure(1, weight=0)
        self.right.grid_rowconfigure(2, weight=2, uniform="rows")

        # --- Fila ---
        queue_container = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        queue_container.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        queue_header = ctk.CTkFrame(queue_container, fg_color="transparent")
        queue_header.pack(fill="x", padx=15, pady=(12, 4))

        ctk.CTkLabel(
            queue_header, text="📋 Fila de Downloads",
            font=ctk.CTkFont(weight="bold")
        ).pack(side="left")

        self.queue_count_label = ctk.CTkLabel(
            queue_header, text="", font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.queue_count_label.pack(side="right")

        self.queue_scroll = ctk.CTkScrollableFrame(
            queue_container, height=80, fg_color="transparent"
        )
        self.queue_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.empty_queue_label = ctk.CTkLabel(
            self.queue_scroll,
            text="Fila vazia - adicione links ao lado",
            text_color="gray", font=ctk.CTkFont(size=11)
        )
        self.empty_queue_label.pack(pady=15)

        # --- Controles + progresso ---
        controls = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        controls.grid(row=1, column=0, sticky="ew", pady=5)
        controls.grid_columnconfigure((0, 1), weight=1, uniform="ctl")

        self.download_btn = ctk.CTkButton(
            controls, text="⬇️ Iniciar Downloads", height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.start_downloads
        )
        self.download_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))

        self.cancel_btn = ctk.CTkButton(
            controls, text="⏹ Cancelar", height=34,
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            state="disabled", command=self.cancel_download
        )
        self.cancel_btn.grid(row=1, column=0, sticky="ew", padx=(12, 4), pady=4)

        self.clear_btn = ctk.CTkButton(
            controls, text="🗑️ Limpar Fila", height=34,
            fg_color="red", hover_color="darkred",
            command=self.clear_queue
        )
        self.clear_btn.grid(row=1, column=1, sticky="ew", padx=(4, 12), pady=4)

        self.progress_label = ctk.CTkLabel(
            controls, text="Aguardando...", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.progress_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 0))

        self.progress = ctk.CTkProgressBar(controls)
        self.progress.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 14))
        self.progress.set(0)

        # --- Log / status ---
        log_frame = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 0))

        ctk.CTkLabel(
            log_frame, text="📝 Status", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(12, 4))

        self.log_text = ctk.CTkTextbox(
            log_frame, height=80, font=ctk.CTkFont(size=11), wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ------------------------------------------------------------------
    # Responsividade
    # ------------------------------------------------------------------
    def _on_resize(self, event=None):
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._apply_resize)

    def _apply_resize(self):
        self._resize_job = None

        left_width = self.left.winfo_width()
        if left_width > 1:
            wrap = max(200, left_width - 70)
            self.video_title_label.configure(wraplength=wrap)
            self.fetch_status.configure(wraplength=wrap)

        if self._compute_queue_text_limit() != self._queue_text_limit:
            self.update_queue_display()

    def _compute_queue_text_limit(self):
        width = self.right.winfo_width()
        if width <= 1:
            return 30
        return max(18, (width - 170) // 7)

    # ------------------------------------------------------------------
    # Helpers de interface
    # ------------------------------------------------------------------
    def _set_status(self, text, color="gray", clear_after=None):
        if self._status_job is not None:
            self.root.after_cancel(self._status_job)
            self._status_job = None

        self.fetch_status.configure(text=text, text_color=color)

        if clear_after:
            self._status_job = self.root.after(clear_after, self._clear_status)

    def _clear_status(self):
        self._status_job = None
        self.fetch_status.configure(text="")

    def _set_add_button(self, mode):
        theme = ctk.ThemeManager.theme["CTkButton"]

        if mode == "add":
            self.add_queue_btn.configure(
                state="normal", text="➕ Adicionar à Fila",
                fg_color=theme["fg_color"], hover_color=theme["hover_color"]
            )
        elif mode == "confirm":
            self.add_queue_btn.configure(
                state="normal", text="✅ Confirmar Alteração",
                fg_color="green", hover_color="darkgreen"
            )
        else:
            self.add_queue_btn.configure(
                state="disabled", text="➕ Adicionar à Fila",
                fg_color=("gray75", "gray30"), hover_color=("gray70", "gray35")
            )

    def _show_cancel_edit(self, visible):
        if visible:
            self.cancel_edit_btn.pack(fill="x", padx=15, pady=(0, 15))
        else:
            self.cancel_edit_btn.pack_forget()

    def _truncate_text(self, text, max_len=40):
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    def _get_custom_name(self):
        """Nome digitado pelo usuário (já limpo). Vazio se não digitou nada.

        Em algumas versões do customtkinter, .get() devolve o texto do
        placeholder; por isso ele é ignorado explicitamente.
        """
        text = self.name_entry.get().strip()
        if text == NAME_PLACEHOLDER:
            return ""
        return Downloader.sanitize_filename(text)

    def _quality_values_for(self, format_type):
        if format_type == "mp3":
            return MP3_QUALITIES
        return self.available_qualities or DEFAULT_VIDEO_QUALITIES

    def _in_queue(self, item):
        return any(queued is item for queued in self.download_queue)

    def _remove_from_queue(self, item):
        self.download_queue[:] = [queued for queued in self.download_queue if queued is not item]

    def _warn_missing_tools(self):
        names = ", ".join(self.downloader.missing_tools)
        messagebox.showwarning(
            "Executáveis não encontrados",
            f"Não encontrei: {names}\n\nColoque os arquivos na pasta:\n{self.downloader.tools_dir}"
        )

    def show_info(self):
        info_text = """
📋 Versões Compatíveis:

• yt-dlp: 2024.03.10 ou superior
• ffmpeg: 6.0 ou superior

🔧 Como atualizar:

yt-dlp:
  - Use o botão "🔄 Atualizar" (recomendado), ou
  - Baixe em: github.com/yt-dlp/yt-dlp/releases
    e substitua o arquivo em tools/yt-dlp.exe

ffmpeg:
  - Baixe em: ffmpeg.org/download.html
  - Extraia e substitua os arquivos em tools/

💡 Dica: se algum vídeo parar de baixar, atualize o yt-dlp primeiro!
        """
        messagebox.showinfo("Informações do Sistema", info_text.strip())

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    # ------------------------------------------------------------------
    # Log e progresso (sempre na thread principal)
    # ------------------------------------------------------------------
    def log(self, message):
        self._append_log(message)

    def _append_log(self, message):
        self.log_text.insert("end", message + "\n")

        # Evita o log crescer sem limite
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 1000:
            self.log_text.delete("1.0", f"{line_count - 1000}.0")

        self.log_text.see("end")

    def _on_progress(self, value):
        self.current_fraction = max(0.0, min(float(value), 1.0))
        self._refresh_progress()

    def _refresh_progress(self):
        if not self.is_downloading:
            return

        active = sum(
            1 for item in self.download_queue
            if item["status"] in (STATUS_PENDING, STATUS_DOWNLOADING)
        )
        total = self.batch_done + active
        if total == 0:
            return

        fraction = (self.batch_done + self.current_fraction) / total
        self.progress.set(min(fraction, 1.0))

        current_number = min(self.batch_done + 1, total)
        percent = int(self.current_fraction * 100)
        self.progress_label.configure(
            text=f"Item {current_number} de {total} • {percent}%"
        )

    # ------------------------------------------------------------------
    # Busca de informações
    # ------------------------------------------------------------------
    def fetch_qualities(self):
        if self._fetching:
            return

        url = self.url_entry.get().strip()

        if not url:
            messagebox.showwarning("Aviso", "Cole um link primeiro!")
            return

        if not url.startswith("http"):
            messagebox.showerror("Erro", "Link inválido!")
            return

        self._fetching = True
        self.fetch_btn.configure(state="disabled", text="🔍 Buscando...")
        self._set_status("🔍 Buscando informações...", "orange")
        self.video_title_label.configure(text="")

        def fetch_thread():
            try:
                info = self.downloader.fetch_playlist_info(url)
                kind = info["type"]

                if kind == "playlist":
                    self._post(self._handle_playlist, info)
                elif kind == "video":
                    available = info.get("qualities") or self.downloader.fetch_available_qualities(url)
                    self._post(self._finish_fetch, url, available, None)
                else:
                    self._post(self._finish_fetch, url, None, info.get("message", "Erro desconhecido"))
            except Exception as e:
                logger.exception("Erro ao buscar informações")
                self._post(self._finish_fetch, url, None, str(e))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _end_fetch(self):
        self._fetching = False
        self.fetch_btn.configure(state="normal", text="🔍 Buscar")

    def _hide_playlist(self):
        self.playlist_container.pack_forget()
        self.is_playlist = False
        self.playlist_data = None
        self.playlist_checkboxes = []

    def _handle_playlist(self, playlist_info):
        self._end_fetch()

        if self.editing_item is not None:
            self._set_status(
                "❌ Não é possível trocar um item por uma playlist. Use um link de vídeo.",
                "red", 5000
            )
            return

        self.is_playlist = True
        self.playlist_data = playlist_info
        self.available_qualities = []
        self.current_video_title = ""

        self.video_title_label.configure(text="")

        playlist_name = self._truncate_text(playlist_info.get("title") or "Playlist", 40)
        self.playlist_title_label.configure(
            text=f"📂 {playlist_name} ({playlist_info['count']} vídeos)"
        )

        for widget in self.playlist_scroll.winfo_children():
            widget.destroy()
        self.playlist_checkboxes = []

        title_limit = max(30, (self.left.winfo_width() - 130) // 7)

        for i, entry in enumerate(playlist_info["entries"]):
            var = ctk.BooleanVar(value=True)
            title = entry.get("title") or f"Vídeo {i + 1}"

            checkbox = ctk.CTkCheckBox(
                self.playlist_scroll,
                text=f"{i + 1}. {self._truncate_text(title, title_limit)}",
                variable=var,
                font=ctk.CTkFont(size=11)
            )
            checkbox.pack(anchor="w", pady=2, padx=5, fill="x")
            self.playlist_checkboxes.append((var, entry))

        self.playlist_container.pack(fill="x", pady=5, before=self.fetch_status)

        self._enable_form_after_fetch()

        self._set_status(
            "✅ Playlist detectada! Selecione os vídeos e o formato/qualidade.",
            "green", 5000
        )
        self.log(f"📂 Playlist detectada: {playlist_info['count']} vídeos")

    def _finish_fetch(self, url, available, error=None):
        self._end_fetch()

        if error or not available:
            self._set_status(f"❌ Erro ao buscar: {(error or 'sem resposta')[:120]}", "red", 6000)
            return

        self._hide_playlist()

        self.current_video_title = available.get("title") or "Vídeo desconhecido"
        self.available_qualities = available.get("video", [])

        self.video_title_label.configure(
            text=f"📹 {self.current_video_title}",
            text_color=("gray10", "gray90")
        )

        self._enable_form_after_fetch()

        if available.get("ok", True):
            self._set_status(
                f"✅ Busca concluída! {len(self.available_qualities)} qualidade(s) de vídeo encontradas.",
                "green", 5000
            )
        else:
            self._set_status(
                "⚠️ Não consegui listar as qualidades; usando uma lista padrão.",
                "orange", 6000
            )
        self.log(f"✅ Vídeo: {self.current_video_title[:60]}")

    def _enable_form_after_fetch(self):
        self.format_menu.configure(state="normal", values=[FORMAT_MP3, FORMAT_MP4])
        self.format_var.set(PLACEHOLDER)

        self.quality_menu.configure(state="disabled", values=["Selecione o formato primeiro"])
        self.quality_var.set("Selecione o formato primeiro")

        self.name_entry.configure(state="normal")
        self._set_add_button("add")
        self.qualities_fetched = True

    def on_format_change(self, choice):
        if "Selecione" in choice or not self.qualities_fetched:
            return

        format_type = "mp3" if "MP3" in choice else "mp4"
        self.quality_menu.configure(state="normal", values=self._quality_values_for(format_type))
        self.quality_var.set(PLACEHOLDER)

    def select_all_playlist(self):
        for var, _ in self.playlist_checkboxes:
            var.set(True)

    def deselect_all_playlist(self):
        for var, _ in self.playlist_checkboxes:
            var.set(False)

    # ------------------------------------------------------------------
    # Fila
    # ------------------------------------------------------------------
    def _validate_selection(self):
        if "Selecione" in self.format_var.get():
            messagebox.showwarning("Aviso", "Selecione um formato (MP3 ou MP4)!")
            return False

        if "Selecione" in self.quality_var.get():
            messagebox.showwarning("Aviso", "Selecione uma qualidade!")
            return False

        return True

    def _new_item(self, url, format_type, quality, output_path, custom_name, video_title):
        return {
            "url": url,
            "format": format_type,
            "quality": quality,
            "output_path": output_path,
            "custom_name": custom_name or None,
            "video_title": video_title,
            "status": STATUS_PENDING,
        }

    def add_to_queue(self):
        if self.editing_item is not None:
            self._confirm_edit()
            return

        if not self.qualities_fetched:
            messagebox.showwarning("Aviso", "Busque as qualidades primeiro!")
            return

        if not self._validate_selection():
            return

        output_path = self.path_entry.get().strip()
        if not output_path:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino!")
            return

        format_type = "mp3" if "MP3" in self.format_var.get() else "mp4"
        quality = self.quality_var.get()
        base_name = self._get_custom_name()

        if self.is_playlist and self.playlist_data:
            added = 0
            for var, entry in self.playlist_checkboxes:
                if not var.get():
                    continue

                item_name = None
                if base_name:
                    item_name = Downloader.sanitize_filename(f"{base_name} - {entry['title']}")

                self.download_queue.append(self._new_item(
                    entry["url"], format_type, quality, output_path,
                    item_name, entry["title"]
                ))
                added += 1

            if added == 0:
                messagebox.showwarning("Aviso", "Marque pelo menos um vídeo da playlist!")
                return

            self._reset_form_after_add()
            self.log(f"✅ Playlist adicionada: {added} vídeo(s) marcado(s)")
        else:
            url = self.url_entry.get().strip()

            if not url or not url.startswith("http"):
                messagebox.showerror("Erro", "Link inválido!")
                return

            self.download_queue.append(self._new_item(
                url, format_type, quality, output_path,
                base_name, self.current_video_title
            ))

            title = self.current_video_title
            self._reset_form_after_add()
            self.log(f"✅ Adicionado à fila: {title[:50]}")

    def _reset_form_after_add(self, status_text="✅ Pronto! Cole outro link e clique em Buscar",
                              status_color="green"):
        self.editing_item = None
        self._show_cancel_edit(False)

        self.url_entry.delete(0, "end")
        self.name_entry.configure(state="normal")
        self.name_entry.delete(0, "end")
        self.name_entry.configure(state="disabled")
        self.video_title_label.configure(text="")

        self._hide_playlist()

        self.format_menu.configure(state="disabled", values=[PLACEHOLDER])
        self.format_var.set(PLACEHOLDER)

        self.quality_menu.configure(state="disabled", values=[PLACEHOLDER])
        self.quality_var.set(PLACEHOLDER)

        self._set_add_button("disabled")

        self.qualities_fetched = False
        self.available_qualities = []
        self.current_video_title = ""

        self.update_queue_display()
        self._set_status(status_text, status_color, 4000)

    def update_queue_display(self):
        limit = self._compute_queue_text_limit()
        self._queue_text_limit = limit

        for row in self.queue_rows:
            row.destroy()
        self.queue_rows = []

        total = len(self.download_queue)
        self.queue_count_label.configure(text=f"{total} item(ns)" if total else "")

        if not total:
            self.empty_queue_label.pack(pady=15)
            return

        self.empty_queue_label.pack_forget()
        for item in self.download_queue:
            self._build_queue_row(item, limit)

    def _build_queue_row(self, item, limit):
        status = item["status"]
        icon = {STATUS_DOWNLOADING: "⏳", STATUS_ERROR: "⚠️"}.get(status, "🔹")
        name = item.get("custom_name") or item.get("video_title") or "título original"
        locked = status == STATUS_DOWNLOADING

        row = ctk.CTkFrame(self.queue_scroll, fg_color=ITEM_COLOR)
        row.pack(fill="x", pady=3, padx=2)

        # Botões primeiro (lado direito) para nunca serem espremidos pelo texto
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame, text="✏️", width=32, height=28, font=ctk.CTkFont(size=12),
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            state="disabled" if locked else "normal",
            command=lambda it=item: self.edit_queue_item(it)
        ).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(
            btn_frame, text="❌", width=32, height=28, font=ctk.CTkFont(size=12),
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            state="disabled" if locked else "normal",
            command=lambda it=item: self.remove_queue_item(it)
        ).pack(side="left", padx=2, pady=6)

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=6)

        ctk.CTkLabel(
            text_frame,
            text=f"{icon} {self._truncate_text(name, limit)}",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
        ).pack(fill="x")

        detail = f"{item['format'].upper()} {item['quality']} • {self._truncate_text(item['url'], limit)}"
        if status == STATUS_ERROR:
            detail = f"Falhou • {detail}"

        ctk.CTkLabel(
            text_frame, text=detail,
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        ).pack(fill="x")

        self.queue_rows.append(row)

    # ------------------------------------------------------------------
    # Edição / remoção
    # ------------------------------------------------------------------
    def edit_queue_item(self, item):
        if item["status"] == STATUS_DOWNLOADING:
            messagebox.showinfo("Info", "Não é possível editar o item que está baixando!")
            return

        if self._fetching:
            messagebox.showinfo("Info", "Aguarde a busca atual terminar.")
            return

        self.editing_item = item
        self._hide_playlist()
        self.video_title_label.configure(text="")

        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, item["url"])

        self.name_entry.configure(state="normal")
        self.name_entry.delete(0, "end")
        if item.get("custom_name"):
            self.name_entry.insert(0, item["custom_name"])

        self._fetching = True
        self.fetch_btn.configure(state="disabled", text="🔍 Buscando...")
        self._set_status("🔍 Recarregando qualidades para edição...", "orange")

        def reload_thread():
            try:
                available = self.downloader.fetch_available_qualities(item["url"])
                self._post(self._finish_edit_load, item, available, None)
            except Exception as e:
                logger.exception("Erro ao recarregar qualidades")
                self._post(self._finish_edit_load, item, None, str(e))

        threading.Thread(target=reload_thread, daemon=True).start()

    def _finish_edit_load(self, item, available, error=None):
        self._end_fetch()

        if error:
            self.editing_item = None
            self._set_status(f"❌ Erro ao recarregar: {error[:100]}", "red", 6000)
            return

        if not self._in_queue(item) or item["status"] == STATUS_DOWNLOADING:
            self.editing_item = None
            self._set_status("⚠️ Esse item não está mais disponível para edição", "orange", 5000)
            return

        available = available or {}
        self.available_qualities = available.get("video", [])
        if available.get("ok"):
            self.current_video_title = available.get("title") or item.get("video_title", "")
        else:
            self.current_video_title = item.get("video_title", "")

        if self.current_video_title:
            self.video_title_label.configure(
                text=f"📹 {self.current_video_title}",
                text_color=("gray10", "gray90")
            )

        self._enable_form_after_fetch()

        # Pré-seleciona o formato e a qualidade atuais do item
        format_label = FORMAT_MP3 if item["format"] == "mp3" else FORMAT_MP4
        self.format_var.set(format_label)
        self.on_format_change(format_label)
        if item["quality"] in self._quality_values_for(item["format"]):
            self.quality_var.set(item["quality"])

        self._set_add_button("confirm")
        self._show_cancel_edit(True)

        self._set_status("✏️ Ajuste o que quiser e clique em Confirmar Alteração", "orange")
        self.url_entry.focus()
        self.log("✏️ Editando item da fila")

    def _confirm_edit(self):
        item = self.editing_item

        if item is None or not self._in_queue(item) or item["status"] == STATUS_DOWNLOADING:
            messagebox.showwarning(
                "Aviso",
                "Esse item não pode mais ser editado (já foi baixado, removido ou está em andamento)."
            )
            self._cancel_edit()
            return

        if not self._validate_selection():
            return

        url = self.url_entry.get().strip()
        if not url or not url.startswith("http"):
            messagebox.showerror("Erro", "Link inválido!")
            return

        output_path = self.path_entry.get().strip()
        if not output_path:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino!")
            return

        base_name = self._get_custom_name()

        # Atualiza no mesmo lugar, mantendo a posição na fila
        item.update({
            "url": url,
            "format": "mp3" if "MP3" in self.format_var.get() else "mp4",
            "quality": self.quality_var.get(),
            "output_path": output_path,
            "custom_name": base_name or None,
            "video_title": self.current_video_title or item.get("video_title", ""),
            "status": STATUS_PENDING,
        })

        self.log("✅ Alteração confirmada")
        self._reset_form_after_add()

    def _cancel_edit(self):
        self._reset_form_after_add("↩️ Edição cancelada", "gray")

    def remove_queue_item(self, item):
        if item["status"] == STATUS_DOWNLOADING:
            messagebox.showinfo("Info", "Não é possível remover o item que está baixando!")
            return

        name = item.get("custom_name") or item.get("video_title") or "(título original)"

        if messagebox.askyesno("Confirmar", f"Remover este item da fila?\n\n{name}"):
            self._remove_from_queue(item)
            if item is self.editing_item:
                self._cancel_edit()
            self.update_queue_display()
            self._refresh_progress()
            self.log(f"❌ Item removido da fila: {name}")

    def clear_queue(self):
        removable = [i for i in self.download_queue if i["status"] != STATUS_DOWNLOADING]

        if not removable:
            messagebox.showinfo("Info", "Não há itens para limpar!")
            return

        if messagebox.askyesno("Confirmar", f"Tem certeza que deseja limpar {len(removable)} item(ns) da fila?"):
            self.download_queue[:] = [i for i in self.download_queue if i["status"] == STATUS_DOWNLOADING]
            self.update_queue_display()
            self._refresh_progress()
            self.log(f"🗑️ Fila limpa: {len(removable)} item(ns) removido(s)")

    # ------------------------------------------------------------------
    # Execução dos downloads
    # ------------------------------------------------------------------
    def start_downloads(self):
        if self.is_downloading:
            messagebox.showinfo("Info", "Já existe um download em andamento!")
            return

        runnable = [i for i in self.download_queue if i["status"] in (STATUS_PENDING, STATUS_ERROR)]
        if not runnable:
            messagebox.showwarning("Aviso", "Adicione pelo menos um link à fila!")
            return

        # Itens que falharam antes são tentados de novo
        for item in runnable:
            item["status"] = STATUS_PENDING

        self.is_downloading = True
        self.cancel_requested = False
        self.current_item = None
        self.current_fraction = 0.0
        self.batch_done = 0
        self.batch_failed = 0

        self.download_btn.configure(state="disabled", text="⏳ Processando...")
        self.cancel_btn.configure(state="normal")
        self.update_btn.configure(state="disabled")
        self.progress.set(0)

        self.log_text.delete("1.0", "end")
        self.log("=" * 40)
        self.log(f"🚀 Iniciando fila com {len(runnable)} download(s)")
        self.log("=" * 40)

        self.update_queue_display()
        self._refresh_progress()
        self.process_queue()

    def process_queue(self):
        if self.cancel_requested:
            self._finish_batch(cancelled=True)
            return

        item = next((i for i in self.download_queue if i["status"] == STATUS_PENDING), None)
        if item is None:
            self._finish_batch()
            return

        item["status"] = STATUS_DOWNLOADING
        self.current_item = item
        self.current_fraction = 0.0

        remaining = sum(1 for i in self.download_queue if i["status"] in (STATUS_PENDING, STATUS_DOWNLOADING))
        self.log(f"\n📥 Baixando ({remaining} restante(s))")
        self.log(f"URL: {item['url']}")
        self.log(f"Formato: {item['format'].upper()} - {item['quality']}")
        if item.get("custom_name"):
            self.log(f"Nome: {item['custom_name']}")

        self.update_queue_display()
        self._refresh_progress()

        self.downloader.start_download(
            url=item["url"],
            format_type=item["format"],
            quality=item["quality"],
            output_path=item["output_path"],
            custom_name=item.get("custom_name"),
            done_callback=lambda result, it=item: self._post(self._on_item_finished, it, result)
        )

    def _on_item_finished(self, item, result):
        self.current_item = None
        self.current_fraction = 0.0

        if result == RESULT_OK:
            self._remove_from_queue(item)
            self.batch_done += 1
        elif result == RESULT_CANCELLED:
            item["status"] = STATUS_PENDING  # continua na fila para tentar depois
        else:
            item["status"] = STATUS_ERROR
            self.batch_done += 1
            self.batch_failed += 1
            self.log("⚠️ Item marcado com erro; seguindo para o próximo.")

        self.update_queue_display()
        self._refresh_progress()

        if result == RESULT_CANCELLED or self.cancel_requested:
            self._finish_batch(cancelled=True)
        else:
            self.root.after(500, self.process_queue)

    def _finish_batch(self, cancelled=False):
        self.is_downloading = False
        self.current_item = None

        self.download_btn.configure(state="normal", text="⬇️ Iniciar Downloads")
        self.cancel_btn.configure(state="disabled")
        self.update_btn.configure(state="normal")

        succeeded = self.batch_done - self.batch_failed

        if cancelled:
            self.log("\n⏹ Fila interrompida. Os itens restantes continuam na fila.")
            self.progress_label.configure(text="Interrompido")
        elif self.batch_failed:
            self.log(f"\n⚠️ Concluído: {succeeded} com sucesso, {self.batch_failed} com erro.")
            self.log("Clique em 'Iniciar Downloads' para tentar os que falharam de novo.")
            self.progress.set(1.0)
            self.progress_label.configure(text=f"Concluído • {succeeded} ok, {self.batch_failed} com erro")
        else:
            self.log("\n🎉 Todos os downloads foram concluídos!")
            self.progress.set(1.0)
            self.progress_label.configure(text=f"Concluído • {succeeded} download(s)")

        self.update_queue_display()

    def cancel_download(self):
        if not self.is_downloading:
            return

        if not messagebox.askyesno("Cancelar", "Cancelar o download atual e parar a fila?"):
            return

        self.cancel_requested = True
        self.cancel_btn.configure(state="disabled")
        self.log("⏹ Cancelando...")
        self.downloader.cancel()

    # ------------------------------------------------------------------
    # Manutenção do yt-dlp
    # ------------------------------------------------------------------
    def update_ytdlp(self):
        if self.is_downloading:
            messagebox.showinfo("Info", "Espere os downloads terminarem para atualizar o yt-dlp.")
            return

        self.update_btn.configure(state="disabled", text="⏳ Atualizando...")
        self.log("🔄 Verificando atualizações do yt-dlp...")

        def update_thread():
            ok, output = self.downloader.update_ytdlp()
            self._post(self._finish_update, ok, output)

        threading.Thread(target=update_thread, daemon=True).start()

    def _finish_update(self, ok, output):
        self.update_btn.configure(state="normal", text="🔄 Atualizar")

        for line in output.splitlines()[-6:]:
            if line.strip():
                self.log(line.strip())

        if ok:
            self._set_status("✅ yt-dlp verificado/atualizado", "green", 5000)
        else:
            self._set_status("❌ Não foi possível atualizar o yt-dlp (veja o log)", "red", 6000)

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------
    def confirm_close(self):
        """Chamado ao fechar a janela. Retorna True se pode fechar."""
        if self.is_downloading:
            if not messagebox.askyesno("Sair", "Há downloads em andamento. Sair mesmo assim?"):
                return False
            self.cancel_requested = True
            self.downloader.cancel()
        return True

    def is_busy(self):
        """True se há download em andamento."""
        return self.is_downloading

    def shutdown(self):
        """Cancela o download atual (usado ao fechar a janela)."""
        if self.is_downloading:
            self.cancel_requested = True
            self.downloader.cancel()
