# epub_translator.spec
# ====================
# Especificação PyInstaller para o executável auto-instalável do EPUB Translator.
#
# Uso:
#   pyinstaller epub_translator.spec
#
# Gera: dist/EPUBTranslator/EPUBTranslator.exe  (Windows)
#        dist/EPUBTranslator/EPUBTranslator      (Linux/macOS)
#
# ARQUITETURA DE AUTO-INSTALAÇÃO:
#   O .exe inclui APENAS:
#     - launcher.py         (entry point + splash screen)
#     - setup_wizard.py     (assistente de primeira execução)
#     - gui_app.py          (GUI principal)
#     - epub_translator.py  (motor de tradução)
#     - customtkinter       (necessário para as UIs de setup e principal)
#     - pip                 (para instalar as deps pesadas no primeiro run)
#
#   Na PRIMEIRA EXECUÇÃO o app:
#     1. Exibe o assistente de configuração (setup_wizard.py)
#     2. Instala deps via pip em %APPDATA%\EPUBTranslator\packages
#     3. Salva flag de configuração concluída
#
#   Nas EXECUÇÕES SEGUINTES:
#     1. Carrega os pacotes já instalados de %APPDATA%\EPUBTranslator\packages
#     2. Abre a GUI diretamente (com splash rápido)
#
# VANTAGENS desta abordagem:
#   - .exe inicial PEQUENO (~80 MB sem torch)
#   - Usuário escolhe instalar ou não o OCR (que pesa ~1,5 GB)
#   - Instalação ocorre apenas uma vez
#   - Funciona mesmo sem Python instalado no sistema

import os
import sys
from pathlib import Path


def get_pkg_path(pkg: str) -> Path:
    import importlib.util
    spec = importlib.util.find_spec(pkg)
    if spec and spec.submodule_search_locations:
        return Path(list(spec.submodule_search_locations)[0])
    raise ImportError(f"Pacote não encontrado: {pkg}")


# ---------------------------------------------------------------------------
# Dados a incluir no bundle (apenas o que é necessário ANTES da instalação)
# ---------------------------------------------------------------------------
added_datas = []

# CustomTkinter — necessário para o setup wizard e GUI principal
try:
    ctk_path = get_pkg_path("customtkinter")
    added_datas.append((str(ctk_path), "customtkinter"))
    print(f"[spec] customtkinter: {ctk_path}")
except ImportError:
    print("[spec] AVISO: customtkinter não encontrado!")

# TkinterDnD2 — drag & drop (opcional, app funciona sem)
try:
    dnd_path = get_pkg_path("tkinterdnd2")
    added_datas.append((str(dnd_path), "tkinterdnd2"))
    print(f"[spec] tkinterdnd2: {dnd_path}")
except ImportError:
    print("[spec] tkinterdnd2 não encontrado — drag-and-drop desativado no .exe")


# ---------------------------------------------------------------------------
# Hidden imports — apenas stdlib + customtkinter + pip (tudo já no Python)
# ---------------------------------------------------------------------------
hidden_imports = [
    # Tkinter
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinterdnd2",
    # CustomTkinter
    "customtkinter",
    "customtkinter.windows",
    "customtkinter.windows.widgets",
    # pip — necessário para auto-instalação no primeiro run
    "pip",
    "pip._internal",
    "pip._internal.cli",
    "pip._internal.cli.main",
    "pip._internal.commands",
    "pip._internal.commands.install",
    "pip._internal.network",
    "pip._internal.network.session",
    "pip._vendor",
    "pip._vendor.certifi",
    "pip._vendor.urllib3",
    # Módulos da aplicação
    "launcher",
    "setup_wizard",
    "gui_app",
    "epub_translator",
    # stdlib usada internamente
    "queue",
    "threading",
    "logging",
    "json",
    "subprocess",
    "pathlib",
    "runpy",
    "importlib",
    "importlib.util",
]

# ---------------------------------------------------------------------------
# Módulos a excluir (não são usados antes da instalação online)
# ---------------------------------------------------------------------------
excludes = [
    # Estes serão instalados em runtime pelo setup_wizard
    "ebooklib",
    "bs4",
    "lxml",
    "deep_translator",
    "PIL",
    "easyocr",
    "torch",
    "torchvision",
    "pytesseract",
    # Outros desnecessários
    "matplotlib",
    "scipy",
    "pandas",
    "notebook",
    "IPython",
    "pytest",
    "numpy",       # instalado junto com easyocr se necessário
]

# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EPUBTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Sem janela de console preta no Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",   # Forneça um .ico para ícone personalizado
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EPUBTranslator",
)
