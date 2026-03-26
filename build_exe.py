#!/usr/bin/env python3
"""
build_exe.py
============
Script auxiliar para construir o executável do EPUB Translator usando PyInstaller.

Uso:
    python build_exe.py                # build padrão
    python build_exe.py --onefile      # gera um único .exe (mais lento para iniciar)
    python build_exe.py --clean        # remove dist/ e build/ antes de compilar
    python build_exe.py --no-ocr       # exclui EasyOCR/torch para executável menor

Requisitos:
    pip install pyinstaller
    pip install -r requirements.txt
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def clean_build_dirs() -> None:
    for d in ("dist", "build", "__pycache__"):
        if Path(d).exists():
            print(f"Removendo {d}/…")
            shutil.rmtree(d)


def check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller não encontrado. Instalando…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def pre_download_easyocr_models(languages: list[str]) -> None:
    """
    Faz o pré-download dos modelos EasyOCR antes do build.
    Isso garante que os modelos já estejam em cache no ambiente de build.
    """
    print("Pré-baixando modelos EasyOCR (isso pode demorar)…")
    try:
        import easyocr  # type: ignore
        _ = easyocr.Reader(languages, gpu=False, verbose=True)
        print("Modelos EasyOCR prontos.")
    except ImportError:
        print("EasyOCR não instalado — pulando pré-download.")
    except Exception as exc:
        print(f"Aviso: falha no pré-download EasyOCR: {exc}")


def build(onefile: bool, no_ocr: bool) -> None:
    """Executa o PyInstaller com as opções adequadas."""
    check_pyinstaller()

    if onefile:
        # Modo arquivo único: conveniente, mas torch torna o .exe > 2 GB
        # e o tempo de inicialização é muito lento. Use apenas sem OCR.
        print("AVISO: --onefile com EasyOCR gera executável > 2 GB.")
        print("       Recomendado somente com --no-ocr.\n")

    cmd = [sys.executable, "-m", "PyInstaller"]

    if onefile:
        cmd += ["--onefile"]
    else:
        cmd += ["--onedir"]

    cmd += [
        "--name", "EPUBTranslator",
        "--windowed",          # Sem console no Windows/macOS
        "--clean",
        "--noconfirm",
    ]

    # Adiciona CustomTkinter como dados
    try:
        import customtkinter
        ctk_path = Path(customtkinter.__file__).parent
        cmd += ["--add-data", f"{ctk_path}{os.pathsep}customtkinter"]
        print(f"Adicionando customtkinter de: {ctk_path}")
    except ImportError:
        print("ERRO: customtkinter não encontrado. Execute: pip install customtkinter")
        sys.exit(1)

    # Adiciona tkinterdnd2 se disponível
    try:
        import tkinterdnd2
        dnd_path = Path(tkinterdnd2.__file__).parent
        cmd += ["--add-data", f"{dnd_path}{os.pathsep}tkinterdnd2"]
        print(f"Adicionando tkinterdnd2 de: {dnd_path}")
    except ImportError:
        print("tkinterdnd2 não encontrado — drag-and-drop não estará disponível no .exe")

    # Hidden imports
    hidden = [
        "deep_translator", "ebooklib", "ebooklib.epub",
        "bs4", "bs4.builder._lxml", "lxml", "lxml.etree",
        "PIL", "PIL.Image", "customtkinter", "tkinterdnd2",
        "queue", "threading",
    ]

    if not no_ocr:
        hidden += [
            "easyocr", "easyocr.easyocr",
            "torch", "torchvision",
            "pytesseract",
        ]
    else:
        # Exclui módulos de OCR para executável menor
        cmd += [
            "--exclude-module", "easyocr",
            "--exclude-module", "torch",
            "--exclude-module", "torchvision",
            "--exclude-module", "pytesseract",
        ]

    for h in hidden:
        cmd += ["--hidden-import", h]

    # Sempre exclui módulos desnecessários
    for exc in ("matplotlib", "scipy", "pandas", "notebook", "IPython", "pytest"):
        cmd += ["--exclude-module", exc]

    cmd.append("gui_app.py")

    print("\n" + "=" * 60)
    print("Iniciando build PyInstaller…")
    print("=" * 60)
    print(f"Comando: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))

    if result.returncode == 0:
        mode = "dist/EPUBTranslator.exe" if onefile else "dist/EPUBTranslator/"
        print("\n" + "=" * 60)
        print(f"Build concluído com sucesso!")
        print(f"Executável em: {mode}")
        if not onefile:
            print("Distribua toda a pasta dist/EPUBTranslator/")
        print("=" * 60)
    else:
        print("\nBuild falhou. Verifique os erros acima.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build do EPUB Translator")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Gera arquivo .exe único (não recomendado com OCR/torch)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove dist/ e build/ antes de compilar",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        dest="no_ocr",
        help="Exclui EasyOCR e torch para executável menor (~50 MB vs ~1.5 GB)",
    )
    parser.add_argument(
        "--preload-easyocr",
        action="store_true",
        dest="preload",
        help="Faz pré-download dos modelos EasyOCR antes do build",
    )
    parser.add_argument(
        "--easyocr-langs",
        nargs="+",
        default=["en", "pt"],
        metavar="LANG",
        help="Idiomas para pré-download EasyOCR (padrão: en pt)",
    )
    args = parser.parse_args()

    if args.clean:
        clean_build_dirs()

    if args.preload and not args.no_ocr:
        pre_download_easyocr_models(args.easyocr_langs)

    build(onefile=args.onefile, no_ocr=args.no_ocr)


if __name__ == "__main__":
    main()
