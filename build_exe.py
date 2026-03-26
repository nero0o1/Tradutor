#!/usr/bin/env python3
"""
build_exe.py
============
Script para construir o executável auto-instalável do EPUB Translator.

O .exe gerado:
  - Não exige Python nem dependências instaladas no computador do usuário
  - Na primeira abertura, instala tudo automaticamente com uma interface amigável
  - Pesquisa ~80 MB (sem OCR) ou ~1,5 GB (com OCR pré-instalado)

Uso:
    python build_exe.py              # build padrão (recomendado)
    python build_exe.py --clean      # apaga dist/ e build/ antes
    python build_exe.py --with-ocr   # inclui EasyOCR+torch no bundle (grande)
    python build_exe.py --onefile    # um único .exe (não recomendado com OCR)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean() -> None:
    for d in ("dist", "build", "__pycache__"):
        p = Path(d)
        if p.exists():
            print(f"  Removendo {d}/…")
            shutil.rmtree(p)
    for f in Path(".").glob("*.spec.bak"):
        f.unlink()


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
        print("  PyInstaller OK.")
    except ImportError:
        print("  PyInstaller não encontrado — instalando…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  PyInstaller instalado.")


def get_pkg_path(pkg: str) -> Path:
    import importlib.util
    spec = importlib.util.find_spec(pkg)
    if spec and spec.submodule_search_locations:
        return Path(list(spec.submodule_search_locations)[0])
    raise ImportError(f"Pacote '{pkg}' não encontrado. Execute: pip install {pkg}")


def build(onefile: bool, with_ocr: bool) -> None:
    ensure_pyinstaller()
    print()

    # --- Monta o comando base ---
    cmd = [sys.executable, "-m", "PyInstaller"]
    cmd += ["--onefile"] if onefile else ["--onedir"]
    cmd += [
        "--name", "EPUBTranslator",
        "--windowed",          # sem console preto no Windows
        "--clean",
        "--noconfirm",
    ]

    # --- Dados obrigatórios: customtkinter ---
    try:
        ctk_path = get_pkg_path("customtkinter")
        sep = ";" if sys.platform == "win32" else ":"
        cmd += ["--add-data", f"{ctk_path}{sep}customtkinter"]
        print(f"  + customtkinter de {ctk_path}")
    except ImportError as e:
        print(f"\nERRO: {e}")
        print("Execute: pip install customtkinter")
        sys.exit(1)

    # --- TkinterDnD2 (opcional) ---
    try:
        dnd_path = get_pkg_path("tkinterdnd2")
        sep = ";" if sys.platform == "win32" else ":"
        cmd += ["--add-data", f"{dnd_path}{sep}tkinterdnd2"]
        print(f"  + tkinterdnd2 de {dnd_path}")
    except ImportError:
        print("  ! tkinterdnd2 não encontrado — drag-and-drop não incluído no .exe")

    # --- Hidden imports base ---
    base_hidden = [
        "tkinter", "tkinter.filedialog", "tkinter.messagebox",
        "tkinterdnd2",
        "customtkinter",
        # pip completo — necessário para auto-instalação no primeiro run
        "pip", "pip._internal", "pip._internal.cli", "pip._internal.cli.main",
        "pip._internal.commands", "pip._internal.commands.install",
        "pip._internal.network", "pip._internal.network.session",
        "pip._vendor", "pip._vendor.certifi", "pip._vendor.urllib3",
        # app
        "launcher", "setup_wizard", "gui_app", "epub_translator",
        "queue", "threading", "logging", "json", "subprocess",
        "pathlib", "runpy", "importlib", "importlib.util",
    ]

    for h in base_hidden:
        cmd += ["--hidden-import", h]

    # --- Se --with-ocr: inclui os pacotes pesados diretamente ---
    if with_ocr:
        print("\n  Modo --with-ocr: incluindo EasyOCR e PyTorch no bundle.")
        print("  AVISO: o executável final será > 2 GB e a build pode demorar 30+ min.")
        ocr_hidden = [
            "ebooklib", "ebooklib.epub",
            "bs4", "bs4.builder._lxml", "lxml", "lxml.etree",
            "deep_translator", "PIL", "PIL.Image",
            "easyocr", "easyocr.easyocr",
            "torch", "torchvision",
            "pytesseract",
        ]
        for h in ocr_hidden:
            cmd += ["--hidden-import", h]
    else:
        # Exclui explicitamente os módulos pesados para manter o .exe leve
        for exc_mod in [
            "matplotlib", "scipy", "pandas", "notebook", "IPython",
            "pytest", "easyocr", "torch", "torchvision", "pytesseract",
        ]:
            cmd += ["--exclude-module", exc_mod]

    # --- Entry point ---
    cmd.append("launcher.py")

    # --- Executa ---
    print("\n" + "=" * 62)
    print("Iniciando build do PyInstaller…")
    print("=" * 62)
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))

    if result.returncode != 0:
        print("\n✗ Build falhou. Verifique os erros acima.")
        sys.exit(1)

    # --- Relatório final ---
    if onefile:
        exe_path = Path("dist") / "EPUBTranslator.exe"
        if not exe_path.exists():
            exe_path = Path("dist") / "EPUBTranslator"
    else:
        exe_path = Path("dist") / "EPUBTranslator"

    size_mb = (
        sum(f.stat().st_size for f in exe_path.rglob("*") if f.is_file()) / 1_048_576
        if exe_path.is_dir()
        else exe_path.stat().st_size / 1_048_576
        if exe_path.exists()
        else 0
    )

    print("\n" + "=" * 62)
    print("✓  Build concluído com sucesso!")
    print(f"   Tamanho total: {size_mb:.1f} MB")
    print(f"   Saída: {exe_path.resolve()}")
    if not onefile:
        print("   → Distribua toda a pasta dist/EPUBTranslator/")
    print()
    print("  Na primeira execução pelo usuário:")
    print("  1. O app mostrará o assistente de configuração")
    print("  2. Instalará as dependências automaticamente (~30 MB sem OCR)")
    print("  3. Abrirá a interface de tradução normalmente")
    print("=" * 62)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build do executável auto-instalável do EPUB Translator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python build_exe.py                  # .exe leve (~80MB), instala deps no 1º run
  python build_exe.py --clean          # limpa builds anteriores antes
  python build_exe.py --with-ocr       # inclui EasyOCR no bundle (>2 GB)
  python build_exe.py --onefile        # arquivo único (lento para iniciar)
        """,
    )
    parser.add_argument("--clean",    action="store_true", help="Remove dist/ e build/ antes")
    parser.add_argument("--with-ocr", action="store_true", dest="with_ocr",
                        help="Inclui EasyOCR+torch no bundle (>2 GB)")
    parser.add_argument("--onefile",  action="store_true", help="Gera único arquivo .exe")
    args = parser.parse_args()

    print("=" * 62)
    print("  EPUB Translator — Build Script")
    print("=" * 62)
    print(f"  Modo:      {'onefile' if args.onefile else 'onedir (pasta)'}")
    print(f"  OCR:       {'incluído no bundle' if args.with_ocr else 'instalado em runtime'}")
    print(f"  Limpeza:   {'sim' if args.clean else 'não'}")
    print("=" * 62)

    if args.clean:
        print("\nLimpando diretórios de build…")
        clean()

    print("\nVerificando dependências de build…")
    build(onefile=args.onefile, with_ocr=args.with_ocr)


if __name__ == "__main__":
    main()
