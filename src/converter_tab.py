# src/converter_tab.py
import logging
import os
import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from converter import (
    Converter, RESULT_OK, RESULT_CANCELLED, check_compatibility,
    CAT_AUDIO_TO_AUDIO, CAT_VIDEO_TO_VIDEO, CAT_VIDEO_TO_AUDIO,
    CAT_VIDEO_TO_GIF, CAT_CUT, CATEGORY_LABELS,
    AUDIO_FORMATS, VIDEO_FORMATS, VIDEO_TO_AUDIO_FORMATS,
    AUDIO_BITRATES, VIDEO_RESOLUTIONS, VIDEO_QUALITIES,
    MPEG2_BITRATES, GIF_FPS, GIF_WIDTHS,
    AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, ALL_MEDIA_EXTENSIONS,
)

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_CONVERTING = "converting"
STATUS_ERROR = "error"

PANEL_COLOR = ("gray85", "gray20")
ITEM_COLOR = ("gray75", "gray25")
BTN_NEUTRAL = ("gray65", "gray35")
BTN_NEUTRAL_HOVER = ("gray60", "gray40")

PLACEHOLDER = "Selecione..."
NAME_PLACEHOLDER = "Ex: Aula (será salvo como Aula_001, Aula_002...)"


class ConverterTab:
    def __init__(self, parent_frame):
        self.parent = parent_frame
        self.root = parent_frame.winfo_toplevel()

        # Fila
        self.conversion_queue = []
        self.is_converting = False
        self.cancel_requested = False
        self.current_item = None
        self.current_fraction = 0.0
        self.batch_done = 0
        self.batch_failed = 0

        # Estado do formulário
        self.selected_files = []
        self.editing_item = None
        self._probing = False
        self._current_category = None

        # Variáveis de opção (recriadas conforme a categoria)
        self._option_vars = {}

        # UI
        self.queue_rows = []
        self.file_rows = []
        self._queue_text_limit = 0
        self._file_text_limit = 0
        self._resize_job = None

        # Thread safety
        self.ui_queue = queue.Queue()
        self.converter = Converter(
            progress_callback=lambda v: self._post(self._on_progress, v),
            log_callback=lambda m: self._post(self._append_log, m),
        )

        self.setup_ui()
        self._poll_ui_queue()

        if self.converter.missing_tools:
            self.root.after(500, self._warn_missing_tools)

    # ------------------------------------------------------------------
    # Comunicação thread -> interface
    # ------------------------------------------------------------------
    def _post(self, func, *args):
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
            text="🔄 Conversor de Arquivo",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left", padx=15, pady=10)

        # Seletor de arquivos
        files_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        files_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            files_frame, text="Arquivos de entrada:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        files_btns = ctk.CTkFrame(files_frame, fg_color="transparent")
        files_btns.pack(fill="x", padx=15, pady=(0, 5))
        self.select_btn = ctk.CTkButton(
            files_btns, text="📂 Selecionar Arquivos", height=38,
            command=self.select_files
        )
        self.select_btn.pack(side="left")
        ctk.CTkButton(
            files_btns, text="🗑️ Limpar Seleção", height=38,
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            command=self.clear_selected_files
        ).pack(side="right")

        self.files_scroll = ctk.CTkScrollableFrame(
            files_frame, height=140, fg_color="transparent"
        )
        self.files_scroll.pack(fill="x", padx=15, pady=(0, 15))

        self.empty_files_label = ctk.CTkLabel(
            self.files_scroll,
            text="Nenhum arquivo selecionado",
            text_color="gray", font=ctk.CTkFont(size=11)
        )
        self.empty_files_label.pack(pady=10)

        # Categoria
        cat_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        cat_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            cat_frame, text="Categoria:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        self.category_var = ctk.StringVar(value=PLACEHOLDER)
        self.category_menu = ctk.CTkOptionMenu(
            cat_frame,
            values=list(CATEGORY_LABELS.values()),
            variable=self.category_var,
            width=200,
            command=self._on_category_change,
            state="disabled"
        )
        self.category_menu.pack(fill="x", padx=15, pady=(0, 15))

        # Opções dinâmicas
        opts_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        opts_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            opts_frame, text="Opções:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        self.options_panel = ctk.CTkFrame(opts_frame, fg_color="transparent")
        self.options_panel.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(
            self.options_panel,
            text="Selecione uma categoria acima",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(pady=10)

        # Nome base
        name_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        name_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            name_frame, text="Nome base (opcional):",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        self.name_entry = ctk.CTkEntry(
            name_frame, height=35,
            placeholder_text=NAME_PLACEHOLDER,
            state="disabled"
        )
        self.name_entry.pack(fill="x", padx=15, pady=(0, 15))

        # Botão adicionar
        add_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        add_frame.pack(fill="x", pady=5)
        self.add_queue_btn = ctk.CTkButton(
            add_frame, text="➕ Adicionar à Fila", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.add_to_queue, state="disabled"
        )
        self.add_queue_btn.pack(fill="x", pady=15, padx=15)
        self.cancel_edit_btn = ctk.CTkButton(
            add_frame, text="↩️ Cancelar edição", height=34,
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            command=self._cancel_edit
        )

        # Pasta de destino
        path_frame = ctk.CTkFrame(left, fg_color=PANEL_COLOR)
        path_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            path_frame, text="Salvar em:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        path_inner = ctk.CTkFrame(path_frame, fg_color="transparent")
        path_inner.pack(fill="x", padx=15, pady=(0, 15))
        browse_btn = ctk.CTkButton(
            path_inner, text="📁", width=50, height=35,
            command=self.browse_folder
        )
        browse_btn.pack(side="right")
        self.path_entry = ctk.CTkEntry(
            path_inner, height=35,
            placeholder_text="Selecione uma pasta..."
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        default_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "converted")
        self.path_entry.insert(0, default_path)

    def _build_right_column(self):
        self.right = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.right.grid(row=0, column=1, sticky="nsew", padx=(0, 5), pady=5)
        self.right.grid_columnconfigure(0, weight=1)
        self.right.grid_rowconfigure(0, weight=3, uniform="rows")
        self.right.grid_rowconfigure(1, weight=0)
        self.right.grid_rowconfigure(2, weight=2, uniform="rows")

        # Fila
        queue_container = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        queue_container.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        queue_header = ctk.CTkFrame(queue_container, fg_color="transparent")
        queue_header.pack(fill="x", padx=15, pady=(12, 4))
        ctk.CTkLabel(
            queue_header, text="📋 Fila de Conversões",
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
            text="Fila vazia - adicione arquivos ao lado",
            text_color="gray", font=ctk.CTkFont(size=11)
        )
        self.empty_queue_label.pack(pady=15)

        # Controles + progresso
        controls = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        controls.grid(row=1, column=0, sticky="ew", pady=5)
        controls.grid_columnconfigure((0, 1), weight=1, uniform="ctl")
        self.convert_btn = ctk.CTkButton(
            controls, text="⬇️ Iniciar Conversões", height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.start_conversions
        )
        self.convert_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
        self.cancel_btn = ctk.CTkButton(
            controls, text="⏹ Cancelar", height=34,
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            state="disabled", command=self.cancel_conversion
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

        # Log
        log_frame = ctk.CTkFrame(self.right, fg_color=PANEL_COLOR)
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        ctk.CTkLabel(
            log_frame, text="📝 Status",
            font=ctk.CTkFont(weight="bold")
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
        if self._compute_queue_text_limit() != self._queue_text_limit:
            self.update_queue_display()
        if self.selected_files and self._compute_file_text_limit() != self._file_text_limit:
            self._update_files_display()

    def _compute_file_text_limit(self):
        width = self.left.winfo_width()
        if width <= 1:
            return 40
        return max(20, (width - 190) // 7)

    def _compute_queue_text_limit(self):
        width = self.right.winfo_width()
        if width <= 1:
            return 30
        return max(18, (width - 170) // 7)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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

    def _get_custom_base(self):
        text = self.name_entry.get().strip()
        if text == NAME_PLACEHOLDER:
            return ""
        return Converter.sanitize_filename(text)

    def _clear_name_entry(self):
        """Limpa e desabilita o campo de nome.
        (Campo desabilitado ignora delete(), então precisa reabilitar antes.)"""
        self.name_entry.configure(state="normal")
        self.name_entry.delete(0, "end")
        self.name_entry.configure(state="disabled")

    def _in_queue(self, item):
        return any(queued is item for queued in self.conversion_queue)

    def _remove_from_queue(self, item):
        self.conversion_queue[:] = [q for q in self.conversion_queue if q is not item]

    def _warn_missing_tools(self):
        names = ", ".join(self.converter.missing_tools)
        messagebox.showwarning(
            "Executáveis não encontrados",
            f"Não encontrei: {names}\n\nColoque os arquivos na pasta:\n{self.converter.tools_dir}"
        )

    # ------------------------------------------------------------------
    # Log e progresso
    # ------------------------------------------------------------------
    def _append_log(self, message):
        self.log_text.insert("end", message + "\n")
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 1000:
            self.log_text.delete("1.0", f"{line_count - 1000}.0")
        self.log_text.see("end")

    def _on_progress(self, value):
        self.current_fraction = max(0.0, min(float(value), 1.0))
        self._refresh_progress()

    def _refresh_progress(self):
        if not self.is_converting:
            return
        active = sum(
            1 for item in self.conversion_queue
            if item["status"] in (STATUS_PENDING, STATUS_CONVERTING)
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

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    # ------------------------------------------------------------------
    # Seleção de arquivos
    # ------------------------------------------------------------------
    def select_files(self):
        if self._probing:
            return
        if self.editing_item is not None:
            messagebox.showinfo("Info", "Termine ou cancele a edição antes de selecionar novos arquivos.")
            return
        filetypes = [
            ("Todos os mídias", " ".join(f"*{e}" for e in sorted(ALL_MEDIA_EXTENSIONS))),
            ("Vídeos", " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))),
            ("Áudios", " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))),
            ("Todos os arquivos", "*.*"),
        ]
        paths = filedialog.askopenfilenames(title="Selecionar arquivos", filetypes=filetypes)
        if not paths:
            return

        self._probing = True
        self.select_btn.configure(state="disabled", text="🔍 Lendo...")

        def probe_thread():
            results = []
            try:
                for p in paths:
                    try:
                        info = self.converter.probe_file(p)
                    except Exception as e:
                        info = {"error": str(e)}
                    results.append({"path": p, "info": info})
            finally:
                # Sempre devolve o controle à interface, mesmo se algo falhar
                self._post(self._finish_select, results)

        threading.Thread(target=probe_thread, daemon=True).start()

    def _finish_select(self, results):
        self._probing = False
        self.select_btn.configure(state="normal", text="📂 Selecionar Arquivos")

        existing = {f["path"] for f in self.selected_files}
        added = 0
        for r in results:
            name = Path(r["path"]).name
            info = r["info"]

            if r["path"] in existing:
                continue
            if "error" in info:
                self._append_log(f"⚠️ Ignorado: {name} ({info['error']})")
                continue
            if info.get("type") == "unknown":
                self._append_log(f"⚠️ Ignorado: {name} (sem faixa de áudio ou vídeo)")
                continue

            self.selected_files.append(r)
            existing.add(r["path"])
            added += 1

        self._update_files_display()

        if added > 0:
            self._append_log(f"📂 {added} arquivo(s) adicionado(s)")
            self.category_menu.configure(state="normal")
            self.name_entry.configure(state="normal")
            self._set_add_button("add")
            # Só sugere categoria se o usuário ainda não escolheu uma
            if self._current_category is None:
                self._suggest_category()

    def clear_selected_files(self):
        self.selected_files.clear()
        self._update_files_display()
        self.category_menu.configure(state="disabled")
        self.category_var.set(PLACEHOLDER)
        self._current_category = None
        self._clear_name_entry()
        self._set_add_button("disabled")
        self._reset_options_panel()

    def _update_files_display(self):
        for row in self.file_rows:
            row.destroy()
        self.file_rows = []

        if not self.selected_files:
            self.empty_files_label.pack(pady=10)
            return

        self.empty_files_label.pack_forget()

        limit = self._compute_file_text_limit()
        self._file_text_limit = limit
        for f in self.selected_files:
            row = self._build_file_row(f, limit)
            self.file_rows.append(row)

    def _build_file_row(self, f, limit=40):
        info = f["info"]
        path = f["path"]
        name = Path(path).name

        row = ctk.CTkFrame(self.files_scroll, fg_color=ITEM_COLOR)
        row.pack(fill="x", pady=2, padx=2)

        # Botão remover
        ctk.CTkButton(
            row, text="❌", width=32, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=BTN_NEUTRAL, hover_color=BTN_NEUTRAL_HOVER,
            command=lambda ff=f: self._remove_selected_file(ff)
        ).pack(side="right", padx=5, pady=4)

        # Info
        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=4)

        icon = "🎬" if info.get("type") == "video" else "🎵" if info.get("type") == "audio" else "📄"
        ctk.CTkLabel(
            text_frame, text=f"{icon} {self._truncate_text(name, limit)}",
            font=ctk.CTkFont(size=11, weight="bold"), anchor="w"
        ).pack(fill="x")

        detail = self._format_file_info(info)
        ctk.CTkLabel(
            text_frame, text=detail,
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w"
        ).pack(fill="x")

        return row

    def _format_file_info(self, info):
        parts = []
        size = info.get("size", 0)
        if size:
            if size > 1_000_000_000:
                parts.append(f"{size / 1_000_000_000:.1f} GB")
            elif size > 1_000_000:
                parts.append(f"{size / 1_000_000:.1f} MB")
            else:
                parts.append(f"{size / 1_000:.0f} KB")

        duration = info.get("duration", 0)
        if duration:
            parts.append(self._format_duration(duration))

        if info.get("type") == "video":
            w, h = info.get("width"), info.get("height")
            if w and h:
                parts.append(f"{w}x{h}")
            if info.get("video_codec"):
                parts.append(info["video_codec"])
        elif info.get("type") == "audio":
            if info.get("audio_codec"):
                parts.append(info["audio_codec"])

        return " • ".join(parts) if parts else "info indisponível"

    @staticmethod
    def _format_duration(seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _remove_selected_file(self, f):
        self.selected_files[:] = [x for x in self.selected_files if x is not f]
        self._update_files_display()
        if not self.selected_files:
            self.clear_selected_files()

    def _suggest_category(self):
        """Sugere a categoria baseado nos arquivos selecionados."""
        if not self.selected_files:
            return
        types = {f["info"].get("type") for f in self.selected_files}
        if types == {"audio"}:
            self.category_var.set(CATEGORY_LABELS[CAT_AUDIO_TO_AUDIO])
            self._on_category_change(CATEGORY_LABELS[CAT_AUDIO_TO_AUDIO])
        elif "video" in types:
            self.category_var.set(CATEGORY_LABELS[CAT_VIDEO_TO_VIDEO])
            self._on_category_change(CATEGORY_LABELS[CAT_VIDEO_TO_VIDEO])

    # ------------------------------------------------------------------
    # Opções dinâmicas
    # ------------------------------------------------------------------
    def _on_category_change(self, label):
        for cat, lbl in CATEGORY_LABELS.items():
            if lbl == label:
                self._current_category = cat
                break
        self._update_options_panel()

    def _reset_options_panel(self):
        for w in self.options_panel.winfo_children():
            w.destroy()
        self._option_vars = {}
        ctk.CTkLabel(
            self.options_panel,
            text="Selecione uma categoria acima",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(pady=10)

    def _update_options_panel(self):
        for w in self.options_panel.winfo_children():
            w.destroy()
        self._option_vars = {}

        cat = self._current_category
        if cat == CAT_AUDIO_TO_AUDIO:
            self._build_audio_to_audio_options()
        elif cat == CAT_VIDEO_TO_VIDEO:
            self._build_video_to_video_options()
        elif cat == CAT_VIDEO_TO_AUDIO:
            self._build_video_to_audio_options()
        elif cat == CAT_VIDEO_TO_GIF:
            self._build_video_to_gif_options()
        elif cat == CAT_CUT:
            self._build_cut_options()

    def _add_option_row(self, label_text, var, values, default=None):
        row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text=label_text, width=100, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        menu = ctk.CTkOptionMenu(row, values=values, variable=var, width=160)
        menu.grid(row=0, column=1, sticky="ew")
        if default and default in values:
            var.set(default)
        return menu

    def _build_audio_to_audio_options(self):
        fmt_var = ctk.StringVar(value="MP3")
        self._option_vars["format"] = fmt_var
        self._add_option_row("Formato:", fmt_var, list(AUDIO_FORMATS.keys()), "MP3")

        br_var = ctk.StringVar(value="320")
        self._option_vars["bitrate"] = br_var
        self.bitrate_row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        self.bitrate_row.pack(fill="x", pady=3)
        self.bitrate_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.bitrate_row, text="Bitrate (kbps):", width=100, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.bitrate_menu = ctk.CTkOptionMenu(
            self.bitrate_row, values=AUDIO_BITRATES, variable=br_var, width=160
        )
        self.bitrate_menu.grid(row=0, column=1, sticky="ew")

        fmt_var.trace_add("write", self._on_audio_format_change)
        self._on_audio_format_change()

    def _on_audio_format_change(self, *args):
        fmt = self._option_vars["format"].get()
        has_br = AUDIO_FORMATS.get(fmt, {}).get("has_bitrate", False)
        if has_br:
            self.bitrate_row.pack(fill="x", pady=3)
        else:
            self.bitrate_row.pack_forget()

    def _build_video_to_video_options(self):
        fmt_var = ctk.StringVar(value="MP4")
        self._option_vars["format"] = fmt_var
        self._add_option_row("Formato:", fmt_var, list(VIDEO_FORMATS.keys()), "MP4")

        res_var = ctk.StringVar(value="Original")
        self._option_vars["resolution"] = res_var
        self._add_option_row("Resolução:", res_var, VIDEO_RESOLUTIONS, "Original")

        # Qualidade (CRF) - aparece pra formatos CRF/VP9
        self.qual_row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        qual_var = ctk.StringVar(value="Média (CRF 23)")
        self._option_vars["quality"] = qual_var
        ctk.CTkLabel(self.qual_row, text="Qualidade:", width=100, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ctk.CTkOptionMenu(self.qual_row, values=VIDEO_QUALITIES, variable=qual_var, width=160).grid(
            row=0, column=1, sticky="ew"
        )
        self.qual_row.grid_columnconfigure(1, weight=1)

        # Bitrate MPEG-2 - aparece só pra MPEG-2
        self.mpeg2_row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        mpeg2_var = ctk.StringVar(value="5M")
        self._option_vars["mpeg2_bitrate"] = mpeg2_var
        ctk.CTkLabel(self.mpeg2_row, text="Bitrate:", width=100, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ctk.CTkOptionMenu(self.mpeg2_row, values=MPEG2_BITRATES, variable=mpeg2_var, width=160).grid(
            row=0, column=1, sticky="ew"
        )
        self.mpeg2_row.grid_columnconfigure(1, weight=1)

        fmt_var.trace_add("write", self._on_video_format_change)
        self._on_video_format_change()

    def _on_video_format_change(self, *args):
        fmt = self._option_vars["format"].get()
        vtype = VIDEO_FORMATS.get(fmt, {}).get("type", "crf")
        if vtype == "bitrate":
            self.qual_row.pack_forget()
            self.mpeg2_row.pack(fill="x", pady=3)
        else:
            self.mpeg2_row.pack_forget()
            self.qual_row.pack(fill="x", pady=3)

    def _build_video_to_audio_options(self):
        fmt_var = ctk.StringVar(value="MP3")
        self._option_vars["format"] = fmt_var
        self._add_option_row("Formato:", fmt_var, list(VIDEO_TO_AUDIO_FORMATS.keys()), "MP3")

        br_var = ctk.StringVar(value="320")
        self._option_vars["bitrate"] = br_var
        self.v2a_bitrate_row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        self.v2a_bitrate_row.pack(fill="x", pady=3)
        self.v2a_bitrate_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.v2a_bitrate_row, text="Bitrate (kbps):", width=100, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.v2a_bitrate_menu = ctk.CTkOptionMenu(
            self.v2a_bitrate_row, values=AUDIO_BITRATES, variable=br_var, width=160
        )
        self.v2a_bitrate_menu.grid(row=0, column=1, sticky="ew")

        fmt_var.trace_add("write", self._on_v2a_format_change)
        self._on_v2a_format_change()

    def _on_v2a_format_change(self, *args):
        fmt = self._option_vars["format"].get()
        has_br = VIDEO_TO_AUDIO_FORMATS.get(fmt, {}).get("has_bitrate", False)
        if has_br:
            self.v2a_bitrate_row.pack(fill="x", pady=3)
        else:
            self.v2a_bitrate_row.pack_forget()

    def _build_video_to_gif_options(self):
        fps_var = ctk.StringVar(value="10")
        self._option_vars["fps"] = fps_var
        self._add_option_row("FPS:", fps_var, GIF_FPS, "10")

        width_var = ctk.StringVar(value="320")
        self._option_vars["width"] = width_var
        self._add_option_row("Largura (px):", width_var, GIF_WIDTHS, "320")

    def _build_cut_options(self):
        row = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text="Início (HH:MM:SS):", width=130, anchor="w").pack(side="left")
        start_var = ctk.StringVar(value="00:00:00")
        self._option_vars["start"] = start_var
        ctk.CTkEntry(row, textvariable=start_var, width=120, height=30).pack(side="left")

        row2 = ctk.CTkFrame(self.options_panel, fg_color="transparent")
        row2.pack(fill="x", pady=3)
        ctk.CTkLabel(row2, text="Fim (HH:MM:SS):", width=130, anchor="w").pack(side="left")
        end_var = ctk.StringVar(value="00:00:30")
        self._option_vars["end"] = end_var
        ctk.CTkEntry(row2, textvariable=end_var, width=120, height=30).pack(side="left")

        precise_var = ctk.BooleanVar(value=False)
        self._option_vars["precise"] = precise_var
        ctk.CTkCheckBox(
            self.options_panel, text="Corte preciso (recodifica, mais lento)",
            variable=precise_var, font=ctk.CTkFont(size=11)
        ).pack(anchor="w", pady=(10, 0))

        ctk.CTkLabel(
            self.options_panel,
            text=("💡 O formato de saída é o mesmo do arquivo original.\n"
                  "Rápido: não recodifica, mas corta no quadro-chave mais próximo.\n"
                  "Preciso: recodifica para cortar exatamente no tempo pedido."),
            text_color="gray", font=ctk.CTkFont(size=10), justify="left"
        ).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------
    # Fila
    # ------------------------------------------------------------------
    def _get_options(self):
        opts = {}
        cat = self._current_category
        if cat == CAT_AUDIO_TO_AUDIO:
            opts["format"] = self._option_vars["format"].get()
            if AUDIO_FORMATS[opts["format"]]["has_bitrate"]:
                opts["bitrate"] = self._option_vars["bitrate"].get()
        elif cat == CAT_VIDEO_TO_VIDEO:
            opts["format"] = self._option_vars["format"].get()
            opts["resolution"] = self._option_vars["resolution"].get()
            fmt_type = VIDEO_FORMATS[opts["format"]]["type"]
            if fmt_type == "bitrate":
                opts["mpeg2_bitrate"] = self._option_vars["mpeg2_bitrate"].get()
            else:
                opts["quality"] = self._option_vars["quality"].get()
        elif cat == CAT_VIDEO_TO_AUDIO:
            opts["format"] = self._option_vars["format"].get()
            if VIDEO_TO_AUDIO_FORMATS[opts["format"]]["has_bitrate"]:
                opts["bitrate"] = self._option_vars["bitrate"].get()
        elif cat == CAT_VIDEO_TO_GIF:
            opts["fps"] = self._option_vars["fps"].get()
            opts["width"] = self._option_vars["width"].get()
        elif cat == CAT_CUT:
            opts["start"] = self._option_vars["start"].get().strip()
            opts["end"] = self._option_vars["end"].get().strip()
            opts["precise"] = bool(self._option_vars["precise"].get())
        return opts

    def _new_item(self, input_path, output_path, category, options, custom_base, index, file_info):
        return {
            "input_path": input_path,
            "output_path": output_path,
            "category": category,
            "options": options,
            "custom_base": custom_base or None,
            "index": index,
            "file_info": file_info,
            "status": STATUS_PENDING,
        }

    def _validate_options(self, options):
        """Retorna uma mensagem de erro, ou None se estiver tudo certo."""
        if self._current_category == CAT_CUT:
            start = Converter.parse_time(options.get("start"))
            end = Converter.parse_time(options.get("end"))
            if start is None or end is None:
                return "Tempo inválido! Use HH:MM:SS, MM:SS ou segundos (ex: 00:01:30)."
            if end <= start:
                return "O tempo de fim precisa ser maior que o de início!"
        return None

    @staticmethod
    def _format_skipped(skipped, limit=8):
        lines = [f"• {name}: {reason}" for name, reason in skipped[:limit]]
        if len(skipped) > limit:
            lines.append(f"... e mais {len(skipped) - limit}")
        return "\n".join(lines)

    def _next_index(self, custom_base):
        """Continua a numeração (Aula_001, Aula_002...) entre lotes com o mesmo nome."""
        if not custom_base:
            return 1
        indexes = [i.get("index", 0) for i in self.conversion_queue
                   if i.get("custom_base") == custom_base]
        return max(indexes, default=0) + 1

    def add_to_queue(self):
        if self.editing_item is not None:
            self._confirm_edit()
            return

        if not self.selected_files:
            messagebox.showwarning("Aviso", "Selecione arquivos primeiro!")
            return

        if not self._current_category:
            messagebox.showwarning("Aviso", "Selecione uma categoria!")
            return

        output_path = self.path_entry.get().strip()
        if not output_path:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino!")
            return

        options = self._get_options()
        error = self._validate_options(options)
        if error:
            messagebox.showwarning("Aviso", error)
            return

        custom_base = self._get_custom_base()

        # Só entra na fila o que a categoria escolhida consegue converter
        accepted = []
        skipped = []
        for f in self.selected_files:
            ok, reason = check_compatibility(self._current_category, f["info"], options)
            if ok:
                accepted.append(f)
            else:
                skipped.append((Path(f["path"]).name, reason))

        if not accepted:
            messagebox.showwarning(
                "Aviso",
                "Nenhum dos arquivos é compatível com essa categoria:\n\n"
                + self._format_skipped(skipped)
            )
            return

        start_index = self._next_index(custom_base)
        for offset, f in enumerate(accepted):
            self.conversion_queue.append(self._new_item(
                f["path"], output_path, self._current_category,
                options, custom_base, start_index + offset, f["info"]
            ))

        self._append_log(f"✅ {len(accepted)} arquivo(s) adicionado(s) à fila")
        if skipped:
            for name, reason in skipped:
                self._append_log(f"⚠️ Ignorado: {name} ({reason})")
            messagebox.showinfo(
                "Alguns arquivos foram ignorados",
                self._format_skipped(skipped)
            )

        self._reset_form_after_add()

    def _reset_form_after_add(self, status_text="✅ Pronto! Selecione mais arquivos",
                               status_color="green"):
        self.editing_item = None
        self._show_cancel_edit(False)
        self.selected_files.clear()
        self._update_files_display()
        self.category_menu.configure(state="disabled")
        self.category_var.set(PLACEHOLDER)
        self._current_category = None
        self._clear_name_entry()
        self._set_add_button("disabled")
        self._reset_options_panel()
        self.update_queue_display()
        self._append_log(status_text)

    def update_queue_display(self):
        limit = self._compute_queue_text_limit()
        self._queue_text_limit = limit
        for row in self.queue_rows:
            row.destroy()
        self.queue_rows = []

        total = len(self.conversion_queue)
        self.queue_count_label.configure(text=f"{total} item(ns)" if total else "")

        if not total:
            self.empty_queue_label.pack(pady=15)
            return

        self.empty_queue_label.pack_forget()
        for item in self.conversion_queue:
            self._build_queue_row(item, limit)

    def _build_queue_row(self, item, limit):
        status = item["status"]
        icon = {STATUS_CONVERTING: "⏳", STATUS_ERROR: "⚠️"}.get(status, "🔹")
        input_name = Path(item["input_path"]).name
        cat_label = CATEGORY_LABELS.get(item["category"], "")

        opts = item.get("options") or {}
        detail_parts = [cat_label]
        if "format" in opts:
            detail_parts.append(opts["format"])
        if "resolution" in opts and opts["resolution"] != "Original":
            detail_parts.append(opts["resolution"])
        if "bitrate" in opts:
            detail_parts.append(f"{opts['bitrate']}k")
        if "start" in opts and "end" in opts:
            detail_parts.append(f"{opts['start']} → {opts['end']}")
        if item.get("custom_base"):
            detail_parts.append(f"→ {item['custom_base']}_{item['index']:03d}")

        row = ctk.CTkFrame(self.queue_scroll, fg_color=ITEM_COLOR)
        row.pack(fill="x", pady=3, padx=2)

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=5)
        locked = status == STATUS_CONVERTING
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
            text=f"{icon} {self._truncate_text(input_name, limit)}",
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
        ).pack(fill="x")
        detail = " • ".join(detail_parts)
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
        if item["status"] == STATUS_CONVERTING:
            messagebox.showinfo("Info", "Não é possível editar o item que está convertendo!")
            return
        if self._probing:
            messagebox.showinfo("Info", "Aguarde a leitura dos arquivos terminar.")
            return

        self.editing_item = item

        # Recarrega arquivos selecionados (só o arquivo sendo editado)
        self.selected_files = [{"path": item["input_path"], "info": item["file_info"]}]
        self._update_files_display()

        # Restaura categoria
        cat_label = CATEGORY_LABELS.get(item["category"], PLACEHOLDER)
        self.category_menu.configure(state="normal")
        self.category_var.set(cat_label)
        self._on_category_change(cat_label)

        # Restaura opções
        opts = item.get("options") or {}
        for key, value in opts.items():
            if key in self._option_vars:
                try:
                    self._option_vars[key].set(value)
                except Exception:
                    pass

        # Restaura nome base
        self.name_entry.configure(state="normal")
        self.name_entry.delete(0, "end")
        if item.get("custom_base"):
            self.name_entry.insert(0, item["custom_base"])

        self._set_add_button("confirm")
        self._show_cancel_edit(True)
        self._append_log("✏️ Editando item da fila")

    def _confirm_edit(self):
        item = self.editing_item
        if item is None or not self._in_queue(item) or item["status"] == STATUS_CONVERTING:
            messagebox.showwarning(
                "Aviso",
                "Esse item não pode mais ser editado."
            )
            self._cancel_edit()
            return

        output_path = self.path_entry.get().strip()
        if not output_path:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino!")
            return

        options = self._get_options()
        error = self._validate_options(options)
        if error:
            messagebox.showwarning("Aviso", error)
            return

        ok, reason = check_compatibility(self._current_category, item.get("file_info"), options)
        if not ok:
            messagebox.showwarning("Aviso", f"Essa categoria não serve para este arquivo: {reason}.")
            return

        custom_base = self._get_custom_base()

        item.update({
            "category": self._current_category,
            "options": options,
            "custom_base": custom_base or None,
            "output_path": output_path,
            "status": STATUS_PENDING,
        })

        self._append_log("✅ Alteração confirmada")
        self._reset_form_after_add()

    def _cancel_edit(self):
        self._reset_form_after_add("↩️ Edição cancelada", "gray")

    def remove_queue_item(self, item):
        if item["status"] == STATUS_CONVERTING:
            messagebox.showinfo("Info", "Não é possível remover o item que está convertendo!")
            return
        name = Path(item["input_path"]).name
        if messagebox.askyesno("Confirmar", f"Remover este item da fila?\n\n{name}"):
            self._remove_from_queue(item)
            if item is self.editing_item:
                self._cancel_edit()
            self.update_queue_display()
            self._refresh_progress()
            self._append_log(f"❌ Item removido: {name}")

    def clear_queue(self):
        removable = [i for i in self.conversion_queue if i["status"] != STATUS_CONVERTING]
        if not removable:
            messagebox.showinfo("Info", "Não há itens para limpar!")
            return
        if messagebox.askyesno("Confirmar", f"Tem certeza que deseja limpar {len(removable)} item(ns)?"):
            self.conversion_queue[:] = [i for i in self.conversion_queue if i["status"] == STATUS_CONVERTING]
            self.update_queue_display()
            self._refresh_progress()
            self._append_log(f"🗑️ Fila limpa: {len(removable)} item(ns)")

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------
    def start_conversions(self):
        if self.is_converting:
            messagebox.showinfo("Info", "Já existe uma conversão em andamento!")
            return
        runnable = [i for i in self.conversion_queue if i["status"] in (STATUS_PENDING, STATUS_ERROR)]
        if not runnable:
            messagebox.showwarning("Aviso", "Adicione arquivos à fila primeiro!")
            return

        for item in runnable:
            item["status"] = STATUS_PENDING

        self.is_converting = True
        self.cancel_requested = False
        self.current_item = None
        self.current_fraction = 0.0
        self.batch_done = 0
        self.batch_failed = 0

        self.convert_btn.configure(state="disabled", text="⏳ Processando...")
        self.cancel_btn.configure(state="normal")
        self.select_btn.configure(state="disabled")
        self.progress.set(0)
        self.log_text.delete("1.0", "end")
        self._append_log("=" * 40)
        self._append_log(f"🚀 Iniciando fila com {len(runnable)} conversão(ões)")
        self._append_log("=" * 40)
        self.update_queue_display()
        self._refresh_progress()
        self.process_queue()

    def process_queue(self):
        if self.cancel_requested:
            self._finish_batch(cancelled=True)
            return
        item = next((i for i in self.conversion_queue if i["status"] == STATUS_PENDING), None)
        if item is None:
            self._finish_batch()
            return

        item["status"] = STATUS_CONVERTING
        self.current_item = item
        self.current_fraction = 0.0
        remaining = sum(1 for i in self.conversion_queue if i["status"] in (STATUS_PENDING, STATUS_CONVERTING))
        self._append_log(f"\n🔄 Convertendo ({remaining} restante(s))")
        self._append_log(f"Arquivo: {Path(item['input_path']).name}")
        self._append_log(f"Categoria: {CATEGORY_LABELS.get(item['category'], '')}")
        self.update_queue_display()
        self._refresh_progress()

        self.converter.start_conversion(
            item,
            done_callback=lambda result, fp, it=item: self._post(self._on_item_finished, it, result, fp)
        )

    def _on_item_finished(self, item, result, final_path):
        self.current_item = None
        self.current_fraction = 0.0
        if result == RESULT_OK:
            self._remove_from_queue(item)
            self.batch_done += 1
        elif result == RESULT_CANCELLED:
            item["status"] = STATUS_PENDING
        else:
            item["status"] = STATUS_ERROR
            self.batch_done += 1
            self.batch_failed += 1
            self._append_log("⚠️ Item marcado com erro; seguindo para o próximo.")

        self.update_queue_display()
        self._refresh_progress()

        if result == RESULT_CANCELLED or self.cancel_requested:
            self._finish_batch(cancelled=True)
        else:
            self.root.after(500, self.process_queue)

    def _finish_batch(self, cancelled=False):
        self.is_converting = False
        self.current_item = None
        self.convert_btn.configure(state="normal", text="⬇️ Iniciar Conversões")
        self.cancel_btn.configure(state="disabled")
        self.select_btn.configure(state="normal")

        succeeded = self.batch_done - self.batch_failed
        if cancelled:
            self._append_log("\n⏹ Fila interrompida.")
            self.progress_label.configure(text="Interrompido")
        elif self.batch_failed:
            self._append_log(f"\n⚠️ Concluído: {succeeded} ok, {self.batch_failed} com erro.")
            self.progress.set(1.0)
            self.progress_label.configure(text=f"Concluído • {succeeded} ok, {self.batch_failed} erro(s)")
        else:
            self._append_log("\n🎉 Todas as conversões foram concluídas!")
            self.progress.set(1.0)
            self.progress_label.configure(text=f"Concluído • {succeeded} conversão(ões)")

        self.update_queue_display()

    def cancel_conversion(self):
        if not self.is_converting:
            return
        if not messagebox.askyesno("Cancelar", "Cancelar a conversão atual e parar a fila?"):
            return
        self.cancel_requested = True
        self.cancel_btn.configure(state="disabled")
        self._append_log("⏹ Cancelando...")
        self.converter.cancel()

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------
    def is_busy(self):
        """True se há conversão em andamento."""
        return self.is_converting

    def shutdown(self):
        """Cancela a conversão atual (usado ao fechar a janela)."""
        if self.is_converting:
            self.cancel_requested = True
            self.converter.cancel()
