#!/usr/bin/env python3
"""
setup_wizard.py
===============
Assistente de primeira execução do EPUB Translator.
Instala todas as dependências automaticamente sem exigir nada do usuário.

Só é importado pelo launcher.py quando dependências estão faltando.
Usa APENAS stdlib + customtkinter (que já vêm no .exe).
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Diretório de pacotes do usuário (persistente entre execuções)
# ---------------------------------------------------------------------------
APP_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EPUBTranslator"
PACKAGES_DIR  = APP_DATA_DIR / "packages"
SETUP_FLAG    = APP_DATA_DIR / "setup_complete.json"


def get_packages_dir() -> Path:
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    return PACKAGES_DIR


def is_setup_complete() -> bool:
    """Verifica se a configuração inicial já foi concluída."""
    if not SETUP_FLAG.exists():
        return False
    try:
        data = json.loads(SETUP_FLAG.read_text())
        return data.get("complete", False)
    except Exception:
        return False


def mark_setup_complete(ocr_installed: bool) -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETUP_FLAG.write_text(
        json.dumps({"complete": True, "ocr": ocr_installed, "version": "1.0.0"})
    )


def inject_packages_path() -> None:
    """Adiciona o diretório de pacotes ao sys.path para importação."""
    pkg_dir = str(PACKAGES_DIR)
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


# ---------------------------------------------------------------------------
# Instalador — roda pip de dentro do executável
# ---------------------------------------------------------------------------

# Pacotes core (sempre instalados, ~30 MB)
CORE_PACKAGES = [
    ("EbookLib",        "Processador de EPUB"),
    ("beautifulsoup4",  "Parser HTML"),
    ("lxml",            "Motor XML"),
    ("deep-translator", "Motor de tradução Google"),
    ("Pillow",          "Processamento de imagens"),
]

# Pacotes OCR (opcionais, ~1.5 GB com torch)
OCR_PACKAGES = [
    ("easyocr",  "EasyOCR + PyTorch (pode demorar ~10 min no download)"),
]


def _run_pip_install(package: str, target_dir: Path, log_fn: Callable[[str], None]) -> bool:
    """
    Instala um pacote usando pip no diretório alvo.
    Funciona tanto no modo frozen (PyInstaller) quanto em desenvolvimento.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # Monta o comando pip
    pip_cmd = [
        sys.executable, "-m", "pip", "install",
        "--target", str(target_dir),
        "--quiet",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        package,
    ]

    # No modo frozen do PyInstaller, sys.executable é o .exe.
    # pip está incluído nos hidden imports — chamamos via subprocess
    try:
        proc = subprocess.Popen(
            pip_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            line = line.strip()
            if line:
                log_fn(line)
        proc.wait()
        return proc.returncode == 0
    except Exception as exc:
        log_fn(f"ERRO ao instalar {package}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Janela do Assistente de Configuração
# ---------------------------------------------------------------------------

class SetupWizard(ctk.CTk):
    """
    Interface de configuração de primeira execução.
    Apresenta o app, instala dependências e prepara o ambiente.
    """

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("EPUB Translator — Configuração Inicial")
        self.geometry("620x580")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._queue: queue.Queue = queue.Queue()
        self._ocr_choice: bool = False
        self._install_done: bool = False
        self._install_success: bool = False

        self._build_ui()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # --- Cabeçalho com branding Francisco ---
        header = ctk.CTkFrame(self, fg_color="#0d47a1", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="📚  EPUB Translator",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="white",
        ).grid(row=0, column=0, pady=(20, 4))

        ctk.CTkLabel(
            header,
            text="por Francisco  •  Assistente de Configuração",
            font=ctk.CTkFont(size=13),
            text_color="#90caf9",
        ).grid(row=1, column=0, pady=(0, 16))

        # --- Boas-vindas ---
        welcome = ctk.CTkFrame(self, fg_color="transparent")
        welcome.grid(row=1, column=0, sticky="ew", padx=24, pady=(18, 4))
        welcome.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            welcome,
            text="Bem-vindo! Vamos preparar tudo para você.",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            welcome,
            text=(
                "Esta é a única vez que este processo será necessário.\n"
                "Os pacotes serão instalados automaticamente e ficam\n"
                "salvos no seu computador para uso futuro."
            ),
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        # --- Opção de OCR ---
        ocr_frame = ctk.CTkFrame(self)
        ocr_frame.grid(row=2, column=0, sticky="ew", padx=24, pady=12)
        ocr_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            ocr_frame,
            text="Instalar suporte a OCR (leitura de texto em imagens)?",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            ocr_frame,
            text=(
                "  ✓  Sim — Traduz texto dentro de imagens (EasyOCR + PyTorch)\n"
                "       Download adicional de ~1,5 GB. Recomendado para livros com infográficos.\n\n"
                "  ✗  Não — Apenas tradução de texto (mais rápido, ~30 MB total)"
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 6))

        self._ocr_switch = ctk.CTkSwitch(
            ocr_frame,
            text="Instalar OCR (EasyOCR + PyTorch)",
            font=ctk.CTkFont(size=12),
            onvalue=True,
            offvalue=False,
        )
        self._ocr_switch.grid(row=2, column=0, sticky="w", padx=14, pady=(4, 14))

        # --- Progresso ---
        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 4))
        prog_frame.grid_columnconfigure(0, weight=1)
        prog_frame.grid_rowconfigure(2, weight=1)

        self._step_label = ctk.CTkLabel(
            prog_frame,
            text="Pronto para começar.",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._step_label.grid(row=0, column=0, sticky="w")

        self._progress_bar = ctk.CTkProgressBar(prog_frame, height=16, corner_radius=8)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=1, column=0, sticky="ew", pady=(6, 4))

        self._log_box = ctk.CTkTextbox(
            prog_frame,
            font=ctk.CTkFont(family="Courier", size=10),
            state="disabled",
            height=140,
        )
        self._log_box.grid(row=2, column=0, sticky="nsew")

        # --- Botão de ação ---
        self._start_btn = ctk.CTkButton(
            self,
            text="▶  Instalar e Iniciar",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            fg_color="#1565c0",
            hover_color="#0d47a1",
            command=self._start_install,
        )
        self._start_btn.grid(row=4, column=0, sticky="ew", padx=24, pady=(8, 16))

    # ------------------------------------------------------------------
    # Instalação
    # ------------------------------------------------------------------

    def _start_install(self) -> None:
        self._ocr_choice = bool(self._ocr_switch.get())
        self._start_btn.configure(state="disabled", text="Instalando…")
        self._ocr_switch.configure(state="disabled")

        thread = threading.Thread(target=self._install_worker, daemon=True)
        thread.start()

    def _install_worker(self) -> None:
        pkg_dir = get_packages_dir()
        total = len(CORE_PACKAGES) + (len(OCR_PACKAGES) if self._ocr_choice else 0)
        done = 0

        self._queue.put(("step", "Instalando pacotes essenciais…", 0))
        self._log("Iniciando instalação em: " + str(pkg_dir))

        # Instala core
        for pkg_name, pkg_desc in CORE_PACKAGES:
            self._log(f"Instalando {pkg_desc} ({pkg_name})…")
            ok = _run_pip_install(pkg_name, pkg_dir, self._log)
            done += 1
            self._queue.put(("progress", done / total))
            if not ok:
                self._queue.put(("error", f"Falha ao instalar {pkg_name}."))
                return

        # Instala OCR (opcional)
        if self._ocr_choice:
            self._queue.put(("step", "Instalando EasyOCR e PyTorch (pode demorar)…", done / total))
            for pkg_name, pkg_desc in OCR_PACKAGES:
                self._log(f"Instalando {pkg_desc}…")
                ok = _run_pip_install(pkg_name, pkg_dir, self._log)
                done += 1
                self._queue.put(("progress", done / total))
                if not ok:
                    self._queue.put(("error", f"Falha ao instalar {pkg_name}."))
                    return

        mark_setup_complete(ocr_installed=self._ocr_choice)
        self._queue.put(("done",))

    def _log(self, message: str) -> None:
        self._queue.put(("log", message))

    # ------------------------------------------------------------------
    # Polling da queue
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            for _ in range(30):
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                elif kind == "progress":
                    self._progress_bar.set(msg[1])
                elif kind == "step":
                    self._step_label.configure(text=msg[1])
                    self._progress_bar.set(msg[2])
                elif kind == "done":
                    self._on_install_done()
                elif kind == "error":
                    self._on_install_error(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _append_log(self, text: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _on_install_done(self) -> None:
        self._progress_bar.set(1.0)
        self._step_label.configure(text="Instalação concluída! Iniciando o app…")
        self._append_log("\n✓ Tudo pronto! O EPUB Translator vai abrir agora.")
        self._install_done = True
        self._install_success = True
        self.after(1800, self.destroy)

    def _on_install_error(self, msg: str) -> None:
        self._step_label.configure(text="Erro durante a instalação.", text_color="#ef5350")
        self._append_log(f"\n✗ ERRO: {msg}")
        self._append_log("Verifique sua conexão com a internet e tente novamente.")
        self._start_btn.configure(
            state="normal",
            text="Tentar novamente",
            fg_color="#b71c1c",
        )

    def _on_close(self) -> None:
        if not self._install_success:
            import tkinter.messagebox as mb
            if mb.askyesno(
                "Cancelar configuração?",
                "A configuração não foi concluída.\nO aplicativo não funcionará sem ela.\n\nDeseja sair mesmo assim?",
            ):
                self.destroy()
                sys.exit(0)
        else:
            self.destroy()


def run_setup_if_needed() -> bool:
    """
    Ponto de entrada para o launcher:
    - Retorna True se já configurado ou após configuração bem-sucedida.
    - Retorna False se o usuário cancelou.
    """
    inject_packages_path()

    if is_setup_complete():
        return True

    wizard = SetupWizard()
    wizard.mainloop()

    if wizard._install_success:
        inject_packages_path()
        return True
    return False
