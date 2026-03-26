#!/usr/bin/env python3
"""
launcher.py
===========
Ponto de entrada do executável EPUBTranslator.exe

Responsabilidades:
1. Na primeira execução: abre o assistente de configuração que instala
   todas as dependências automaticamente (sem intervenção do usuário além
   de clicar "Instalar").
2. Nas execuções seguintes: carrega os pacotes instalados e abre a GUI.
3. Exibe uma splash screen rápida durante o carregamento.

Este arquivo é o único compilado pelo PyInstaller como entry point.
Todos os outros módulos (gui_app, epub_translator) são importados
APÓS a instalação dos pacotes.
"""

import os
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Ajuste de sys.path para modo frozen (PyInstaller)
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Estamos rodando como executável PyInstaller
    _BUNDLE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    sys.path.insert(0, str(_BUNDLE_DIR))
    # Adiciona diretório do exe para módulos irmãos
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    _BUNDLE_DIR = Path(__file__).parent

# Importa customtkinter ANTES de qualquer outra coisa — já está no bundle
import customtkinter as ctk  # noqa: E402


# ---------------------------------------------------------------------------
# Splash Screen
# ---------------------------------------------------------------------------

class SplashScreen(ctk.CTkToplevel):
    """
    Tela de carregamento exibida enquanto os módulos pesados são importados.
    """

    def __init__(self):
        # Cria uma janela raiz oculta para hospedar o Toplevel
        self._root = ctk.CTk()
        self._root.withdraw()
        super().__init__(self._root)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.overrideredirect(True)   # Sem barra de título
        self.attributes("-topmost", True)

        w, h = 460, 260
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._build()
        self.update()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 1, 2, 3, 4), weight=1)

        # Fundo colorido
        bg = ctk.CTkFrame(self, fg_color="#0d47a1", corner_radius=16)
        bg.place(relx=0, rely=0, relwidth=1, relheight=1)
        bg.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bg, text="📚", font=ctk.CTkFont(size=52)
        ).pack(pady=(30, 4))

        ctk.CTkLabel(
            bg,
            text="EPUB Translator",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="white",
        ).pack()

        ctk.CTkLabel(
            bg,
            text="por Francisco",
            font=ctk.CTkFont(size=13),
            text_color="#90caf9",
        ).pack(pady=(2, 12))

        self._status = ctk.CTkLabel(
            bg,
            text="Carregando…",
            font=ctk.CTkFont(size=11),
            text_color="#bbdefb",
        )
        self._status.pack()

        self._bar = ctk.CTkProgressBar(bg, mode="indeterminate", height=8)
        self._bar.pack(fill="x", padx=30, pady=(8, 20))
        self._bar.start()

    def set_status(self, text: str) -> None:
        self._status.configure(text=text)
        self.update()

    def close(self) -> None:
        self._bar.stop()
        self._root.destroy()


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Passo 1: verificar e executar configuração inicial ---
    from setup_wizard import run_setup_if_needed, inject_packages_path

    inject_packages_path()

    if not run_setup_if_needed():
        # Usuário cancelou a configuração
        sys.exit(0)

    # --- Passo 2: splash screen durante importação dos módulos pesados ---
    splash = SplashScreen()
    splash.set_status("Iniciando o aplicativo…")

    try:
        splash.set_status("Carregando motor de tradução…")
        import gui_app  # noqa: F401 — importação aqui carrega ebooklib, bs4, etc.

        splash.set_status("Pronto!")
        time.sleep(0.4)
        splash.close()

    except ImportError as exc:
        splash.close()
        import tkinter.messagebox as mb
        mb.showerror(
            "Erro de importação",
            f"Não foi possível carregar um módulo necessário:\n\n{exc}\n\n"
            "Tente deletar a pasta:\n"
            f"  %APPDATA%\\EPUBTranslator\n\n"
            "e executar o programa novamente para reinstalar.",
        )
        sys.exit(1)

    # --- Passo 3: iniciar a GUI principal ---
    gui_app.main()


if __name__ == "__main__":
    main()
