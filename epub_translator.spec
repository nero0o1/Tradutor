# epub_translator.spec
# ====================
# Arquivo de especificação do PyInstaller para gerar o executável do EPUB Translator.
#
# Uso:
#   pyinstaller epub_translator.spec
#
# O executável gerado estará em: dist/EPUBTranslator/EPUBTranslator(.exe)
#
# NOTAS SOBRE EASYOCR:
#   Os modelos do EasyOCR (~100 MB cada) são baixados em tempo de execução para
#   ~/.EasyOCR/model/ na primeira vez que o OCR é ativado. Isso é intencional:
#   incluí-los no executável tornaria o .exe > 2 GB. O app informa o usuário
#   sobre o download automático via interface.
#
# NOTAS SOBRE TESSERACT:
#   O binário do Tesseract deve estar instalado separadamente no sistema e
#   adicionado ao PATH. No Windows, o instalador oficial está em:
#   https://github.com/UB-Mannheim/tesseract/wiki

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Descoberta de caminhos de pacotes (executado em tempo de build)
# ---------------------------------------------------------------------------

def get_package_path(pkg: str) -> str:
    import importlib
    spec = importlib.util.find_spec(pkg)
    if spec and spec.submodule_search_locations:
        return str(Path(list(spec.submodule_search_locations)[0]))
    raise ImportError(f"Pacote não encontrado: {pkg}")


# Caminho do customtkinter (contém themes e assets)
try:
    CTK_PATH = get_package_path("customtkinter")
except ImportError:
    CTK_PATH = None

# Caminho do tkinterdnd2 (contém extensão Tcl nativa)
try:
    DND_PATH = get_package_path("tkinterdnd2")
except ImportError:
    DND_PATH = None

# ---------------------------------------------------------------------------
# Dados extras a incluir no bundle
# ---------------------------------------------------------------------------
added_datas = []

if CTK_PATH:
    # Inclui todos os temas e imagens do CustomTkinter
    added_datas.append((CTK_PATH, "customtkinter"))

if DND_PATH:
    # Inclui a extensão Tcl/Tk do TkinterDnD2
    added_datas.append((DND_PATH, "tkinterdnd2"))

# ---------------------------------------------------------------------------
# Hidden imports — módulos não detectados automaticamente pelo PyInstaller
# ---------------------------------------------------------------------------
hidden_imports = [
    # deep_translator
    "deep_translator",
    "deep_translator.google_trans",
    "deep_translator.engines",
    # ebooklib
    "ebooklib",
    "ebooklib.epub",
    "ebooklib.utils",
    # beautifulsoup4
    "bs4",
    "bs4.builder",
    "bs4.builder._lxml",
    "bs4.builder._htmlparser",
    # lxml
    "lxml",
    "lxml.etree",
    "lxml._elementpath",
    # PIL / Pillow
    "PIL",
    "PIL.Image",
    "PIL.ImageOps",
    # EasyOCR (importações lazy — deve estar no hidden imports)
    "easyocr",
    "easyocr.easyocr",
    "easyocr.detection",
    "easyocr.recognition",
    # PyTorch (dependência do EasyOCR)
    "torch",
    "torchvision",
    "torch.nn",
    "torch.nn.functional",
    # pytesseract
    "pytesseract",
    # tkinter e extensões
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinterdnd2",
    # customtkinter
    "customtkinter",
    # stdlib
    "queue",
    "threading",
    "logging",
    "pathlib",
]

# ---------------------------------------------------------------------------
# Spec principal
# ---------------------------------------------------------------------------
block_cipher = None

a = Analysis(
    ["gui_app.py"],
    pathex=["."],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclui módulos desnecessários para reduzir tamanho do .exe
        "matplotlib",
        "scipy",
        "pandas",
        "notebook",
        "IPython",
        "pytest",
        "setuptools",
        "distutils",
    ],
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
    exclude_binaries=True,         # Modo COLLECT (pasta): melhor para torch
    name="EPUBTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                      # Compressão UPX (requer upx instalado)
    console=False,                 # Sem janela de console no Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",      # Descomente e forneça um .ico para ícone customizado
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
