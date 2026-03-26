#!/usr/bin/env python3
"""
gui_app.py
==========
Interface gráfica para o epub_translator.py usando CustomTkinter.

Funcionalidades:
- Área de drag-and-drop para seleção do EPUB
- Seletores de idioma de origem e destino
- Controles de OCR (on/off, motor, idiomas)
- Barra de progresso em tempo real por documento HTML
- Console de log colorido e integrado
- Seleção de arquivo de saída
- Cancelamento cooperativo da tradução em andamento
- Suporte a temas claro/escuro
"""

import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

# Tenta importar suporte a drag-and-drop; se não disponível, usa apenas Browse
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

# Importa o motor de tradução
from epub_translator import EPUBTranslator

# ---------------------------------------------------------------------------
# Constantes de layout e estilo
# ---------------------------------------------------------------------------
APP_TITLE = "EPUB Translator"
APP_VERSION = "1.0.0"
WINDOW_MIN_W = 760
WINDOW_MIN_H = 700
WINDOW_W = 820
WINDOW_H = 780

# Cores do console por nível de log
LOG_COLORS = {
    "INFO":    "#4fc3f7",   # azul claro
    "WARNING": "#ffb74d",   # laranja
    "ERROR":   "#ef5350",   # vermelho
    "SUCCESS": "#66bb6a",   # verde
    "DEBUG":   "#b0bec5",   # cinza
}

# ---------------------------------------------------------------------------
# Tabela de idiomas: (código_google, nome_exibição)
# ---------------------------------------------------------------------------
LANGUAGES = [
    ("auto",  "Detectar automaticamente"),
    ("af",    "Africâner"),
    ("sq",    "Albanês"),
    ("de",    "Alemão"),
    ("ar",    "Árabe"),
    ("hy",    "Armênio"),
    ("az",    "Azerbaijano"),
    ("eu",    "Basco"),
    ("be",    "Bielorrusso"),
    ("bn",    "Bengali"),
    ("bs",    "Bósnio"),
    ("bg",    "Búlgaro"),
    ("ca",    "Catalão"),
    ("ceb",   "Cebuano"),
    ("ny",    "Chichewa"),
    ("zh-CN", "Chinês Simplificado"),
    ("zh-TW", "Chinês Tradicional"),
    ("ko",    "Coreano"),
    ("co",    "Corso"),
    ("hr",    "Croata"),
    ("da",    "Dinamarquês"),
    ("sk",    "Eslovaco"),
    ("sl",    "Esloveno"),
    ("es",    "Espanhol"),
    ("eo",    "Esperanto"),
    ("et",    "Estoniano"),
    ("fi",    "Finlandês"),
    ("fr",    "Francês"),
    ("fy",    "Frisão"),
    ("gl",    "Galego"),
    ("cy",    "Galês"),
    ("ka",    "Georgiano"),
    ("el",    "Grego"),
    ("gu",    "Gujarati"),
    ("ht",    "Haitiano"),
    ("ha",    "Hauçá"),
    ("haw",   "Havaiano"),
    ("iw",    "Hebraico"),
    ("hi",    "Hindi"),
    ("hmn",   "Hmong"),
    ("nl",    "Holandês"),
    ("hu",    "Húngaro"),
    ("ig",    "Igbo"),
    ("id",    "Indonésio"),
    ("en",    "Inglês"),
    ("ga",    "Irlandês"),
    ("is",    "Islandês"),
    ("it",    "Italiano"),
    ("ja",    "Japonês"),
    ("jw",    "Javanês"),
    ("kn",    "Canarês"),
    ("kk",    "Cazaque"),
    ("km",    "Khmer"),
    ("ku",    "Curdo"),
    ("ky",    "Quirguiz"),
    ("lo",    "Laosiano"),
    ("la",    "Latim"),
    ("lv",    "Letão"),
    ("lt",    "Lituano"),
    ("lb",    "Luxemburguês"),
    ("mk",    "Macedônio"),
    ("mg",    "Malgaxe"),
    ("ms",    "Malaio"),
    ("ml",    "Malaiala"),
    ("mt",    "Maltês"),
    ("mi",    "Maori"),
    ("mr",    "Marata"),
    ("mn",    "Mongol"),
    ("my",    "Birmanês"),
    ("ne",    "Nepalês"),
    ("no",    "Norueguês"),
    ("or",    "Oriya"),
    ("ps",    "Pashto"),
    ("fa",    "Persa"),
    ("pl",    "Polonês"),
    ("pt",    "Português"),
    ("pa",    "Punjabi"),
    ("ro",    "Romeno"),
    ("ru",    "Russo"),
    ("sm",    "Samoano"),
    ("gd",    "Gaélico Escocês"),
    ("sr",    "Sérvio"),
    ("st",    "Sesoto"),
    ("sn",    "Shona"),
    ("sd",    "Sindi"),
    ("si",    "Cingalês"),
    ("so",    "Somali"),
    ("su",    "Sudanês"),
    ("sw",    "Suaíli"),
    ("sv",    "Sueco"),
    ("tg",    "Tadjique"),
    ("tl",    "Filipino"),
    ("ta",    "Tâmil"),
    ("te",    "Telugu"),
    ("th",    "Tailandês"),
    ("tr",    "Turco"),
    ("tk",    "Turcomano"),
    ("uk",    "Ucraniano"),
    ("ur",    "Urdu"),
    ("ug",    "Uigur"),
    ("uz",    "Uzbeque"),
    ("vi",    "Vietnamita"),
    ("xh",    "Xhosa"),
    ("yi",    "Iídiche"),
    ("yo",    "Iorubá"),
    ("zu",    "Zulu"),
]

# Mapas auxiliares para lookup rápido
_CODE_TO_NAME = {code: name for code, name in LANGUAGES}
_NAME_TO_CODE = {name: code for code, name in LANGUAGES}
_LANG_NAMES   = [name for _, name in LANGUAGES]


def lang_name(code: str) -> str:
    return _CODE_TO_NAME.get(code, code)


def lang_code(name: str) -> str:
    return _NAME_TO_CODE.get(name, name)


# ---------------------------------------------------------------------------
# Handler de logging que redireciona para a fila da GUI
# ---------------------------------------------------------------------------
class _QueueLogHandler(logging.Handler):
    """Envia registros de log para uma queue para consumo thread-safe pela GUI."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        level = record.levelname
        message = self.format(record)
        self._queue.put(("log", level, message))


# ---------------------------------------------------------------------------
# Widget personalizado: área de drop de arquivo
# ---------------------------------------------------------------------------
class DropZone(ctk.CTkFrame):
    """
    Área visual para drag-and-drop ou seleção de arquivo EPUB.
    Exibe ícone, nome do arquivo selecionado e instrução de uso.
    """

    def __init__(self, master, on_file_selected, **kwargs):
        super().__init__(master, **kwargs)
        self._on_file_selected = on_file_selected
        self._file_path: Optional[str] = None

        self.configure(cursor="hand2", corner_radius=12)

        # Ícone de livro (emoji unicode — sem dependência de imagem)
        self._icon_label = ctk.CTkLabel(
            self, text="📚", font=ctk.CTkFont(size=48)
        )
        self._icon_label.pack(pady=(20, 4))

        self._main_label = ctk.CTkLabel(
            self,
            text="Arraste o EPUB aqui",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self._main_label.pack()

        self._sub_label = ctk.CTkLabel(
            self,
            text="ou clique para selecionar o arquivo",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._sub_label.pack(pady=(2, 4))

        self._file_label = ctk.CTkLabel(
            self,
            text="Nenhum arquivo selecionado",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self._file_label.pack(pady=(0, 16))

        # Clique abre o diálogo de arquivo
        for widget in (self, self._icon_label, self._main_label,
                       self._sub_label, self._file_label):
            widget.bind("<Button-1>", self._on_click)

        # Bind para drag-and-drop (requer tkinterdnd2)
        if _DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

    def _on_click(self, _event=None) -> None:
        path = filedialog.askopenfilename(
            title="Selecionar arquivo EPUB",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if path:
            self.set_file(path)

    def _on_drop(self, event) -> None:
        """Recebe o caminho arrastado — tkinterdnd2 pode envolver em chaves."""
        raw = event.data.strip()
        # Remove chaves colocadas pelo TkinterDnD em caminhos com espaço
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        if raw.lower().endswith(".epub"):
            self.set_file(raw)
        else:
            messagebox.showwarning(
                "Formato inválido", "Por favor, selecione um arquivo .epub"
            )

    def set_file(self, path: str) -> None:
        self._file_path = path
        name = Path(path).name
        # Trunca nome longo para caber na UI
        display = name if len(name) <= 50 else name[:47] + "…"
        self._file_label.configure(
            text=f"✓  {display}",
            text_color="#66bb6a",
        )
        self._main_label.configure(text="Arquivo selecionado")
        self._icon_label.configure(text="📖")
        if self._on_file_selected:
            self._on_file_selected(path)

    def get_file(self) -> Optional[str]:
        return self._file_path

    def reset(self) -> None:
        self._file_path = None
        self._icon_label.configure(text="📚")
        self._main_label.configure(text="Arraste o EPUB aqui")
        self._file_label.configure(
            text="Nenhum arquivo selecionado", text_color="gray"
        )


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(ctk.CTk if not _DND_AVAILABLE else TkinterDnD.Tk):
    """
    Janela principal do EPUB Translator.
    Herda de TkinterDnD.Tk se disponível, senão de ctk.CTk normal.
    """

    def __init__(self):
        super().__init__()

        # --- Configuração da janela ---
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)

        # Tema e aparência inicial
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Fila thread-safe para comunicação worker → GUI
        self._queue: queue.Queue = queue.Queue()

        # Referência ao thread de tradução
        self._worker_thread: Optional[threading.Thread] = None
        self._translator: Optional[EPUBTranslator] = None

        # Rastreia tempo decorrido
        self._start_time: Optional[float] = None
        self._timer_running = False

        # Configura o handler de logging para redirecionar à GUI
        self._log_handler = _QueueLogHandler(self._queue)
        self._log_handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        logging.getLogger().addHandler(self._log_handler)

        # Constrói a interface
        self._build_ui()

        # Inicia o loop de polling da queue
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Monta todos os widgets da janela principal."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # header
        self.grid_rowconfigure(1, weight=0)  # drop zone
        self.grid_rowconfigure(2, weight=0)  # languages
        self.grid_rowconfigure(3, weight=0)  # OCR
        self.grid_rowconfigure(4, weight=0)  # output path
        self.grid_rowconfigure(5, weight=0)  # action buttons
        self.grid_rowconfigure(6, weight=0)  # progress
        self.grid_rowconfigure(7, weight=1)  # log console
        self.grid_rowconfigure(8, weight=0)  # footer

        pad = {"padx": 16, "pady": 6}

        # --- Cabeçalho ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="📚 EPUB Translator",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        # Toggle de tema claro/escuro
        self._theme_switch = ctk.CTkSwitch(
            header,
            text="Tema Escuro",
            command=self._toggle_theme,
            onvalue="dark",
            offvalue="light",
        )
        self._theme_switch.select()   # começa no modo escuro
        self._theme_switch.grid(row=0, column=2, sticky="e")

        # --- Área de Drop ---
        self._drop_zone = DropZone(
            self,
            on_file_selected=self._on_input_selected,
            height=140,
        )
        self._drop_zone.grid(row=1, column=0, sticky="ew", **pad)

        # --- Idiomas ---
        lang_frame = ctk.CTkFrame(self)
        lang_frame.grid(row=2, column=0, sticky="ew", **pad)
        lang_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(lang_frame, text="Idioma de Origem:").grid(
            row=0, column=0, sticky="w", padx=12, pady=8
        )
        self._source_var = ctk.StringVar(value=lang_name("auto"))
        self._source_combo = ctk.CTkComboBox(
            lang_frame,
            values=_LANG_NAMES,
            variable=self._source_var,
            width=220,
            state="readonly",
        )
        self._source_combo.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=8)

        ctk.CTkLabel(lang_frame, text="Idioma de Destino:").grid(
            row=0, column=2, sticky="w", padx=12, pady=8
        )
        self._target_var = ctk.StringVar(value=lang_name("pt"))
        self._target_combo = ctk.CTkComboBox(
            lang_frame,
            values=[n for n in _LANG_NAMES if n != lang_name("auto")],
            variable=self._target_var,
            width=220,
            state="readonly",
        )
        self._target_combo.grid(row=0, column=3, sticky="w", padx=(0, 12), pady=8)

        # --- Controles de OCR ---
        ocr_frame = ctk.CTkFrame(self)
        ocr_frame.grid(row=3, column=0, sticky="ew", **pad)
        ocr_frame.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(
            ocr_frame,
            text="OCR em Imagens",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4), columnspan=5)

        ctk.CTkLabel(ocr_frame, text="Ativar OCR:").grid(
            row=1, column=0, sticky="w", padx=12, pady=8
        )
        self._ocr_switch = ctk.CTkSwitch(
            ocr_frame,
            text="",
            command=self._on_ocr_toggle,
            onvalue=True,
            offvalue=False,
        )
        self._ocr_switch.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=8)

        ctk.CTkLabel(ocr_frame, text="Motor:").grid(
            row=1, column=2, sticky="w", padx=8, pady=8
        )
        self._ocr_engine_var = ctk.StringVar(value="EasyOCR")
        self._ocr_engine_combo = ctk.CTkComboBox(
            ocr_frame,
            values=["EasyOCR", "Tesseract"],
            variable=self._ocr_engine_var,
            width=140,
            state="disabled",
        )
        self._ocr_engine_combo.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=8)

        ctk.CTkLabel(ocr_frame, text="Idiomas OCR:").grid(
            row=1, column=4, sticky="w", padx=8, pady=8
        )
        self._ocr_langs_entry = ctk.CTkEntry(
            ocr_frame,
            placeholder_text="en  (ex: en pt es)",
            width=160,
            state="disabled",
        )
        self._ocr_langs_entry.grid(row=1, column=5, sticky="w", padx=(0, 12), pady=8)

        # Aviso sobre download de modelos EasyOCR
        self._ocr_note = ctk.CTkLabel(
            ocr_frame,
            text="ℹ  EasyOCR fará download dos modelos (~100 MB) na primeira execução.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self._ocr_note.grid(
            row=2, column=0, columnspan=6, sticky="w", padx=12, pady=(0, 8)
        )

        # --- Arquivo de saída ---
        out_frame = ctk.CTkFrame(self)
        out_frame.grid(row=4, column=0, sticky="ew", **pad)
        out_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(out_frame, text="Arquivo de saída:").grid(
            row=0, column=0, sticky="w", padx=12, pady=10
        )
        self._output_entry = ctk.CTkEntry(
            out_frame,
            placeholder_text="Será gerado automaticamente ao selecionar o EPUB…",
        )
        self._output_entry.grid(
            row=0, column=1, sticky="ew", padx=(0, 8), pady=10
        )
        ctk.CTkButton(
            out_frame,
            text="…",
            width=36,
            command=self._browse_output,
        ).grid(row=0, column=2, padx=(0, 12), pady=10)

        # --- Botões de ação ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 2))
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self._translate_btn = ctk.CTkButton(
            btn_frame,
            text="▶  TRADUZIR EPUB",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=44,
            fg_color="#1565c0",
            hover_color="#0d47a1",
            command=self._start_translation,
        )
        self._translate_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 8))

        self._cancel_btn = ctk.CTkButton(
            btn_frame,
            text="✕  Cancelar",
            height=44,
            fg_color="#b71c1c",
            hover_color="#7f0000",
            state="disabled",
            command=self._cancel_translation,
        )
        self._cancel_btn.grid(row=0, column=2, sticky="ew")

        # --- Barra de progresso ---
        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(6, 0))
        prog_frame.grid_columnconfigure(0, weight=1)

        self._progress_bar = ctk.CTkProgressBar(prog_frame, height=18, corner_radius=8)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=0, column=0, sticky="ew")

        status_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        status_row.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        status_row.grid_columnconfigure(1, weight=1)

        self._pct_label = ctk.CTkLabel(
            status_row,
            text="0%",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=42,
        )
        self._pct_label.grid(row=0, column=0, sticky="w")

        self._status_label = ctk.CTkLabel(
            status_row,
            text="Aguardando arquivo…",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._status_label.grid(row=0, column=1, sticky="w", padx=6)

        self._elapsed_label = ctk.CTkLabel(
            status_row,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self._elapsed_label.grid(row=0, column=2, sticky="e")

        # --- Console de log ---
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.grid(row=7, column=0, sticky="new", padx=16, pady=(10, 0))
        log_header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            log_header,
            text="Console de Log",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            log_header,
            text="Limpar",
            width=70,
            height=26,
            fg_color="transparent",
            border_width=1,
            command=self._clear_log,
        ).grid(row=0, column=2, sticky="e")

        self._log_box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Courier", size=11),
            wrap="word",
            state="disabled",
        )
        self._log_box.grid(row=7, column=0, sticky="nsew", padx=16, pady=(30, 4))

        # Configura tags de cor no widget Textbox (acessa o widget tk subjacente)
        for level, color in LOG_COLORS.items():
            self._log_box._textbox.tag_configure(level, foreground=color)

        # --- Rodapé ---
        footer = ctk.CTkLabel(
            self,
            text=f"EPUB Translator {APP_VERSION}  •  Powered by deep-translator & ebooklib",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        )
        footer.grid(row=8, column=0, pady=(0, 8))

    # ------------------------------------------------------------------
    # Callbacks de UI
    # ------------------------------------------------------------------

    def _toggle_theme(self) -> None:
        mode = self._theme_switch.get()
        ctk.set_appearance_mode(mode)
        label = "Tema Escuro" if mode == "dark" else "Tema Claro"
        self._theme_switch.configure(text=label)

    def _on_ocr_toggle(self) -> None:
        state = "normal" if self._ocr_switch.get() else "disabled"
        self._ocr_engine_combo.configure(state=state)
        self._ocr_langs_entry.configure(state=state)

    def _on_input_selected(self, path: str) -> None:
        """Sugere automaticamente o caminho de saída quando EPUB é selecionado."""
        p = Path(path)
        target_code = lang_code(self._target_var.get())
        suggested = p.parent / f"{p.stem}_{target_code}{p.suffix}"
        self._output_entry.delete(0, "end")
        self._output_entry.insert(0, str(suggested))

    def _browse_output(self) -> None:
        current = self._output_entry.get().strip()
        initial_dir = str(Path(current).parent) if current else str(Path.home())
        initial_file = Path(current).name if current else "output.epub"
        path = filedialog.asksaveasfilename(
            title="Salvar EPUB traduzido como",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".epub",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if path:
            self._output_entry.delete(0, "end")
            self._output_entry.insert(0, path)

    # ------------------------------------------------------------------
    # Lógica de tradução
    # ------------------------------------------------------------------

    def _validate_inputs(self) -> bool:
        """Valida os campos antes de iniciar a tradução."""
        input_path = self._drop_zone.get_file()
        if not input_path:
            messagebox.showwarning("Arquivo não selecionado", "Selecione um arquivo EPUB de entrada.")
            return False
        if not os.path.isfile(input_path):
            messagebox.showerror("Arquivo não encontrado", f"O arquivo não existe:\n{input_path}")
            return False

        output_path = self._output_entry.get().strip()
        if not output_path:
            messagebox.showwarning("Saída não definida", "Defina o caminho do arquivo EPUB de saída.")
            return False

        out_dir = Path(output_path).parent
        if not out_dir.exists():
            messagebox.showerror(
                "Diretório inválido",
                f"O diretório de destino não existe:\n{out_dir}",
            )
            return False

        if input_path == output_path:
            messagebox.showerror(
                "Caminhos idênticos",
                "O arquivo de entrada e saída não podem ser o mesmo.",
            )
            return False

        return True

    def _start_translation(self) -> None:
        if not self._validate_inputs():
            return

        input_path  = self._drop_zone.get_file()
        output_path = self._output_entry.get().strip()
        source_lang = lang_code(self._source_var.get())
        target_lang = lang_code(self._target_var.get())
        ocr_enabled = bool(self._ocr_switch.get())
        ocr_engine  = self._ocr_engine_var.get().lower()   # "easyocr" ou "tesseract"
        ocr_langs_raw = self._ocr_langs_entry.get().strip()
        ocr_langs   = ocr_langs_raw.split() if ocr_langs_raw else ["en"]

        # Reseta estado visual
        self._progress_bar.set(0)
        self._pct_label.configure(text="0%")
        self._status_label.configure(text="Iniciando…", text_color="gray")
        self._elapsed_label.configure(text="")
        self._set_controls_state("disabled")
        self._cancel_btn.configure(state="normal")

        # Registra início
        self._start_time = time.monotonic()
        self._timer_running = True
        self.after(1000, self._update_elapsed)

        # Inicia worker thread
        self._worker_thread = threading.Thread(
            target=self._translation_worker,
            args=(input_path, output_path, source_lang, target_lang,
                  ocr_enabled, ocr_engine, ocr_langs),
            daemon=True,
        )
        self._worker_thread.start()

    def _translation_worker(
        self,
        input_path: str,
        output_path: str,
        source_lang: str,
        target_lang: str,
        ocr_enabled: bool,
        ocr_engine: str,
        ocr_langs: list,
    ) -> None:
        """Roda em thread separada; comunica com a GUI via queue."""
        cancel_event = threading.Event()

        self._translator = EPUBTranslator(
            source_lang=source_lang,
            target_lang=target_lang,
            ocr_enabled=ocr_enabled,
            ocr_engine=ocr_engine,
            ocr_languages=ocr_langs,
            progress_callback=lambda cur, tot, lbl: self._queue.put(
                ("progress", cur, tot, lbl)
            ),
            log_callback=lambda lvl, msg: self._queue.put(("log", lvl, msg)),
            cancel_event=cancel_event,
        )

        try:
            success = self._translator.translate(input_path, output_path)
            if success:
                self._queue.put(("done", True, output_path))
            else:
                self._queue.put(("done", False, "Tradução cancelada pelo usuário."))
        except Exception as exc:
            self._queue.put(("error", str(exc)))

    def _cancel_translation(self) -> None:
        if self._translator:
            self._translator.cancel()
        self._cancel_btn.configure(state="disabled")
        self._status_label.configure(text="Cancelando…", text_color="#ffb74d")

    # ------------------------------------------------------------------
    # Polling da queue (thread-safe UI update)
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        """Processa até 20 mensagens da queue por ciclo de 100 ms."""
        try:
            for _ in range(20):
                msg = self._queue.get_nowait()
                self._handle_queue_message(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_queue_message(self, msg: tuple) -> None:
        kind = msg[0]

        if kind == "log":
            _, level, text = msg
            self._append_log(level, text)

        elif kind == "progress":
            _, current, total, label = msg
            if total > 0:
                ratio = current / total
                self._progress_bar.set(ratio)
                pct = int(ratio * 100)
                self._pct_label.configure(text=f"{pct}%")
                doc_info = f"Doc {current}/{total}"
                self._status_label.configure(
                    text=f"{label}  —  {doc_info}",
                    text_color="gray",
                )

        elif kind == "done":
            _, success, detail = msg
            self._timer_running = False
            self._set_controls_state("normal")
            self._cancel_btn.configure(state="disabled")
            if success:
                self._progress_bar.set(1.0)
                self._pct_label.configure(text="100%")
                self._status_label.configure(
                    text="Tradução concluída com sucesso!", text_color="#66bb6a"
                )
                self._append_log("SUCCESS", f"Arquivo salvo em: {detail}")
                messagebox.showinfo(
                    "Concluído!",
                    f"Tradução finalizada com sucesso!\n\nArquivo salvo em:\n{detail}",
                )
            else:
                self._status_label.configure(text=detail, text_color="#ffb74d")
                self._append_log("WARNING", detail)

        elif kind == "error":
            _, error_msg = msg
            self._timer_running = False
            self._set_controls_state("normal")
            self._cancel_btn.configure(state="disabled")
            self._status_label.configure(text="Erro durante a tradução.", text_color="#ef5350")
            self._append_log("ERROR", f"Erro fatal: {error_msg}")
            messagebox.showerror("Erro", f"Ocorreu um erro durante a tradução:\n\n{error_msg}")

    # ------------------------------------------------------------------
    # Helpers de UI
    # ------------------------------------------------------------------

    def _set_controls_state(self, state: str) -> None:
        """Habilita ou desabilita controles de entrada durante a tradução."""
        widgets = [
            self._translate_btn,
            self._source_combo,
            self._target_combo,
            self._ocr_switch,
            self._output_entry,
        ]
        for w in widgets:
            w.configure(state=state)
        # OCR sub-controles só ficam habilitados se o switch OCR estiver ON
        if state == "normal" and self._ocr_switch.get():
            self._ocr_engine_combo.configure(state="normal")
            self._ocr_langs_entry.configure(state="normal")
        elif state == "disabled":
            self._ocr_engine_combo.configure(state="disabled")
            self._ocr_langs_entry.configure(state="disabled")

    def _append_log(self, level: str, message: str) -> None:
        """Insere uma linha no console de log com colorização por nível."""
        self._log_box.configure(state="normal")
        prefix = f"[{level:7s}] "
        # Tag de cor para o prefixo; texto normal para o resto
        self._log_box._textbox.insert("end", prefix, level)
        self._log_box._textbox.insert("end", message + "\n")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("0.0", "end")
        self._log_box.configure(state="disabled")

    def _update_elapsed(self) -> None:
        """Atualiza o contador de tempo decorrido a cada segundo."""
        if not self._timer_running or self._start_time is None:
            return
        elapsed = int(time.monotonic() - self._start_time)
        mins, secs = divmod(elapsed, 60)
        self._elapsed_label.configure(text=f"⏱  {mins:02d}:{secs:02d}")
        self.after(1000, self._update_elapsed)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    # Se TkinterDnD estiver disponível, a classe App já herdou de TkinterDnD.Tk;
    # caso contrário, herda de ctk.CTk. Instanciação é a mesma em ambos os casos.
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
