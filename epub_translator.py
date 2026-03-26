#!/usr/bin/env python3
"""
epub_translator.py
==================
Script completo para tradução de arquivos EPUB preservando formatação HTML.

Funcionalidades:
- Extração de texto mantendo tags HTML (negrito, itálico, cabeçalhos, etc.)
- OCR em imagens usando EasyOCR ou PyTesseract
- Tradução gratuita via deep_translator (GoogleTranslator)
- Chunking automático para lidar com limites de caracteres
- Reconstrução do EPUB com textos traduzidos

Uso:
    python epub_translator.py input.epub output.epub --source en --target pt
    python epub_translator.py input.epub output.epub --source auto --target pt --ocr
"""

import argparse
import logging
import os
import re
import sys
import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

# Processamento de EPUB
import ebooklib
from ebooklib import epub

# Parsing HTML
from bs4 import BeautifulSoup, NavigableString, Tag

# Tradução
from deep_translator import GoogleTranslator

# Imagens
from PIL import Image

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
MAX_CHUNK_CHARS = 4500      # Limite seguro abaixo dos 5 000 do GoogleTranslator
TRANSLATE_DELAY = 0.3       # Segundos entre chamadas para evitar rate-limit
OCR_MIN_CONFIDENCE = 0.4    # Confiança mínima para aceitar texto do OCR


# ---------------------------------------------------------------------------
# Funções de OCR
# ---------------------------------------------------------------------------

def _load_ocr_engine(engine: str, languages: list[str]):
    """Carrega o motor de OCR escolhido e retorna uma função de extração."""

    if engine == "easyocr":
        try:
            import easyocr  # type: ignore
            reader = easyocr.Reader(languages, gpu=False, verbose=False)
            logger.info("EasyOCR carregado com idiomas: %s", languages)

            def extract_easyocr(img_bytes: bytes) -> str:
                image = Image.open(BytesIO(img_bytes)).convert("RGB")
                results = reader.readtext(
                    image,
                    detail=1,
                    paragraph=False,
                )
                texts = [
                    text
                    for (_, text, conf) in results
                    if conf >= OCR_MIN_CONFIDENCE
                ]
                return " ".join(texts).strip()

            return extract_easyocr

        except ImportError:
            logger.error("EasyOCR não instalado. Execute: pip install easyocr")
            raise

    elif engine == "tesseract":
        try:
            import pytesseract  # type: ignore

            # Monta string de idiomas no formato Tesseract (eng+por)
            lang_str = "+".join(languages)
            logger.info("PyTesseract carregado com idiomas: %s", lang_str)

            def extract_tesseract(img_bytes: bytes) -> str:
                image = Image.open(BytesIO(img_bytes))
                text = pytesseract.image_to_string(image, lang=lang_str)
                return text.strip()

            return extract_tesseract

        except ImportError:
            logger.error(
                "pytesseract não instalado. Execute: pip install pytesseract"
            )
            raise

    else:
        raise ValueError(f"Motor de OCR desconhecido: {engine}")


# ---------------------------------------------------------------------------
# Funções de tradução com chunking
# ---------------------------------------------------------------------------

def split_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    Divide um texto longo em partes menores respeitando sentenças/parágrafos.
    Prioridade: quebra por parágrafo > por sentença > por tamanho bruto.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    # Tenta quebrar por parágrafo primeiro
    paragraphs = text.split("\n")
    current = ""

    for para in paragraphs:
        # Parágrafo individual maior que o limite — quebra por sentença
        if len(para) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sub = ""
            for sent in sentences:
                if len(sub) + len(sent) + 1 > max_chars:
                    if sub:
                        chunks.append(sub.strip())
                    # Sentença ainda maior que o limite — quebra bruta
                    while len(sent) > max_chars:
                        chunks.append(sent[:max_chars])
                        sent = sent[max_chars:]
                    sub = sent
                else:
                    sub = (sub + " " + sent).strip()
            if sub:
                chunks.append(sub.strip())
        elif len(current) + len(para) + 1 > max_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n" + para).strip()

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c]


def translate_text(
    text: str,
    translator: GoogleTranslator,
    delay: float = TRANSLATE_DELAY,
) -> str:
    """
    Traduz um bloco de texto usando GoogleTranslator com chunking automático.
    Preserva linhas em branco entre parágrafos após a tradução.
    """
    text = text.strip()
    if not text:
        return text

    chunks = split_into_chunks(text)
    translated_parts: list[str] = []

    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(delay)
        try:
            result = translator.translate(chunk)
            translated_parts.append(result if result else chunk)
        except Exception as exc:
            logger.warning("Falha ao traduzir chunk %d: %s — mantendo original.", i, exc)
            translated_parts.append(chunk)

    return "\n".join(translated_parts)


# ---------------------------------------------------------------------------
# Traversal e tradução de nós HTML
# ---------------------------------------------------------------------------

# Tags cujo conteúdo textual NÃO deve ser traduzido
SKIP_TAGS = {
    "script", "style", "code", "pre", "kbd", "samp", "var",
    "math", "svg", "ruby", "rt", "rp",
}

# Tags de bloco onde o texto filho pode ser coletado como unidade
BLOCK_TAGS = {
    "p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "figcaption", "caption", "dt", "dd", "div",
}


def _collect_text_nodes(tag: Tag) -> list[NavigableString]:
    """Retorna todos os nós de texto folha dentro de uma tag."""
    nodes = []
    for child in tag.descendants:
        if isinstance(child, NavigableString) and child.parent.name not in SKIP_TAGS:
            if child.strip():
                nodes.append(child)
    return nodes


def translate_soup_element(element: Tag, translator: GoogleTranslator) -> None:
    """
    Percorre a árvore DOM de um elemento BeautifulSoup e traduz os textos
    de forma a preservar todas as tags HTML originais.

    Estratégia:
    1. Para tags de bloco (p, h1, li, …) coleta o texto interno completo,
       traduz como unidade e reinjeta preservando as tags filhas.
    2. Para nós de texto soltos fora de blocos, traduz cada nó individualmente.
    """
    if element.name in SKIP_TAGS:
        return

    # Processa blocos de texto como unidade para manter coerência de tradução
    for block in element.find_all(list(BLOCK_TAGS), recursive=True):
        if block.name in SKIP_TAGS:
            continue

        # Coleta os nós de texto diretamente filhos (não aninhados em sub-blocos)
        direct_text_nodes: list[NavigableString] = []
        for child in block.children:
            if isinstance(child, NavigableString):
                if child.strip():
                    direct_text_nodes.append(child)
            elif isinstance(child, Tag) and child.name not in BLOCK_TAGS | SKIP_TAGS:
                # Inline tags (span, a, strong, em, …) — coleta nós internos
                for node in _collect_text_nodes(child):
                    direct_text_nodes.append(node)

        # Traduz cada nó de texto individual dentro do bloco
        for node in direct_text_nodes:
            original = str(node)
            stripped = original.strip()
            if not stripped:
                continue
            translated = translate_text(stripped, translator)
            # Preserva espaços em branco ao redor do texto
            leading = original[: len(original) - len(original.lstrip())]
            trailing = original[len(original.rstrip()):]
            node.replace_with(NavigableString(leading + translated + trailing))


# ---------------------------------------------------------------------------
# Processamento do EPUB
# ---------------------------------------------------------------------------

class EPUBTranslator:
    """Orquestra a tradução completa de um arquivo EPUB."""

    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        ocr_enabled: bool = False,
        ocr_engine: str = "easyocr",
        ocr_languages: Optional[list[str]] = None,
        # Callback chamado a cada documento processado: (atual, total, nome_arquivo)
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        # Callback de log extra além do logger padrão: (level, mensagem)
        log_callback: Optional[Callable[[str, str], None]] = None,
        # Event para cancelamento cooperativo a partir de outra thread
        cancel_event: Optional[threading.Event] = None,
    ):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.ocr_enabled = ocr_enabled
        self.ocr_engine_name = ocr_engine
        self.ocr_languages = ocr_languages or ["en"]
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.cancel_event = cancel_event or threading.Event()
        self._cancelled = False

        # Inicializa tradutor
        self.translator = GoogleTranslator(
            source=source_lang,
            target=target_lang,
        )
        self._log("INFO", f"Tradutor inicializado: {source_lang} → {target_lang}")

        # Inicializa OCR se necessário
        self._ocr_fn = None
        if ocr_enabled:
            self._ocr_fn = _load_ocr_engine(ocr_engine, self.ocr_languages)

    def cancel(self) -> None:
        """Sinaliza cancelamento cooperativo; a tradução para na próxima iteração."""
        self._cancelled = True
        self.cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.cancel_event.is_set()

    def _log(self, level: str, message: str) -> None:
        """Emite log pelo logger padrão E pelo callback da GUI (se configurado)."""
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(message)
        if self.log_callback:
            self.log_callback(level, message)

    def _emit_progress(self, current: int, total: int, label: str) -> None:
        """Emite evento de progresso para a GUI."""
        if self.progress_callback:
            self.progress_callback(current, total, label)

    # ------------------------------------------------------------------
    # Processamento de imagens
    # ------------------------------------------------------------------

    def _process_image_item(self, item: epub.EpubImage) -> Optional[str]:
        """
        Executa OCR em um item de imagem do EPUB.
        Retorna o texto extraído ou None se não houver texto.
        """
        if self._ocr_fn is None:
            return None
        try:
            text = self._ocr_fn(item.content)
            if text:
                self._log("INFO", f"OCR extraiu texto de '{item.file_name}': {text[:60]}…")
            return text or None
        except Exception as exc:
            self._log("WARNING", f"OCR falhou em '{item.file_name}': {exc}")
            return None

    def _inject_ocr_caption(
        self,
        soup: BeautifulSoup,
        img_tag: Tag,
        ocr_text: str,
    ) -> None:
        """
        Injeta o texto extraído via OCR como <figcaption> logo após a imagem.
        Se a imagem já estiver dentro de <figure>, adiciona ali.
        Caso contrário, envolve a imagem em <figure>.
        """
        translated_ocr = translate_text(ocr_text, self.translator)

        parent = img_tag.parent
        if parent and parent.name == "figure":
            # Verifica se já existe figcaption
            existing = parent.find("figcaption")
            if existing:
                existing.string = translated_ocr
            else:
                caption_tag = soup.new_tag("figcaption")
                caption_tag.string = translated_ocr
                parent.append(caption_tag)
        else:
            # Envolve em <figure> + <figcaption>
            figure_tag = soup.new_tag("figure")
            img_tag.insert_before(figure_tag)
            img_tag.extract()
            figure_tag.append(img_tag)
            caption_tag = soup.new_tag("figcaption")
            caption_tag.string = translated_ocr
            figure_tag.append(caption_tag)

    # ------------------------------------------------------------------
    # Processamento de documentos HTML
    # ------------------------------------------------------------------

    def _translate_html_document(
        self,
        html_content: bytes,
        image_ocr_map: dict[str, str],
    ) -> bytes:
        """
        Recebe o conteúdo HTML de um documento EPUB, traduz os textos e
        retorna o HTML modificado como bytes.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Traduz o título do documento (tag <title>)
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            original_title = title_tag.string.strip()
            if original_title:
                title_tag.string = translate_text(original_title, self.translator)

        # Processa imagens com OCR
        if self.ocr_enabled and image_ocr_map:
            for img_tag in soup.find_all("img"):
                src = img_tag.get("src", "")
                # Normaliza o caminho (remove prefixos relativos)
                src_basename = Path(src).name
                ocr_text = image_ocr_map.get(src_basename)
                if ocr_text:
                    self._inject_ocr_caption(soup, img_tag, ocr_text)

        # Traduz o corpo do documento
        body = soup.find("body")
        if body:
            translate_soup_element(body, self.translator)
        else:
            # EPUB sem <body> — processa o documento inteiro
            translate_soup_element(soup, self.translator)

        return str(soup).encode("utf-8")

    # ------------------------------------------------------------------
    # Ponto de entrada principal
    # ------------------------------------------------------------------

    def translate(self, input_path: str, output_path: str) -> bool:
        """
        Lê o EPUB de entrada, traduz todos os documentos de texto e imagens
        (via OCR), e grava o novo EPUB no caminho de saída.

        Retorna True em caso de sucesso, False se cancelado.
        Lança exceção em caso de erro fatal.
        """
        self._log("INFO", f"Lendo EPUB: {input_path}")
        book = epub.read_epub(input_path, options={"ignore_ncx": False})

        # --- Fase 1: OCR nas imagens ---
        image_ocr_map: dict[str, str] = {}
        if self.ocr_enabled:
            self._log("INFO", "Iniciando fase de OCR em imagens…")
            image_items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            total_imgs = len(image_items)
            self._log("INFO", f"Total de imagens encontradas: {total_imgs}")
            for img_idx, img_item in enumerate(image_items, start=1):
                if self._is_cancelled():
                    self._log("WARNING", "Tradução cancelada pelo usuário.")
                    return False
                self._emit_progress(img_idx, total_imgs, f"OCR {img_item.file_name}")
                ocr_text = self._process_image_item(img_item)
                if ocr_text:
                    basename = Path(img_item.file_name).name
                    image_ocr_map[basename] = ocr_text

        # --- Fase 2: Tradução dos documentos HTML ---
        html_items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        total_docs = len(html_items)
        self._log("INFO", f"Total de documentos HTML encontrados: {total_docs}")
        self._emit_progress(0, total_docs, "Iniciando tradução…")

        for idx, item in enumerate(html_items, start=1):
            if self._is_cancelled():
                self._log("WARNING", "Tradução cancelada pelo usuário.")
                return False

            self._log("INFO", f"[{idx}/{total_docs}] Traduzindo: {item.file_name}")
            self._emit_progress(idx, total_docs, item.file_name)

            try:
                translated_content = self._translate_html_document(
                    item.content, image_ocr_map
                )
                item.content = translated_content
            except Exception as exc:
                self._log(
                    "ERROR",
                    f"Falha ao traduzir '{item.file_name}': {exc} — mantido original.",
                )

        if self._is_cancelled():
            return False

        # --- Fase 3: Tradução dos metadados do livro ---
        self._translate_metadata(book)

        # --- Fase 4: Gravação do novo EPUB ---
        self._log("INFO", f"Gravando EPUB traduzido em: {output_path}")
        epub.write_epub(output_path, book)
        self._log("INFO", "Tradução concluída com sucesso!")
        self._emit_progress(total_docs, total_docs, "Concluído!")
        return True

    def _translate_metadata(self, book: epub.EpubBook) -> None:
        """Traduz título e descrição do livro nos metadados."""
        # Título
        titles = book.get_metadata("DC", "title")
        if titles:
            original_title = titles[0][0] if titles[0] else ""
            if original_title:
                new_title = translate_text(original_title, self.translator)
                book.metadata.get("DC", {}).pop("title", None)
                book.set_title(new_title)
                self._log("INFO", f"Título traduzido: '{original_title}' → '{new_title}'")

        # Descrição
        descs = book.get_metadata("DC", "description")
        if descs:
            original_desc = descs[0][0] if descs[0] else ""
            if original_desc:
                new_desc = translate_text(original_desc, self.translator)
                book.metadata.get("DC", {}).pop("description", None)
                book.add_metadata("DC", "description", new_desc)


# ---------------------------------------------------------------------------
# Interface de linha de comando
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Traduz um arquivo EPUB preservando a formatação HTML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Tradução básica de inglês para português
  python epub_translator.py livro.epub livro_pt.epub --source en --target pt

  # Detecção automática de idioma origem com OCR usando EasyOCR
  python epub_translator.py livro.epub livro_pt.epub --target pt --ocr

  # Usar PyTesseract como motor de OCR
  python epub_translator.py livro.epub livro_pt.epub --target pt --ocr --ocr-engine tesseract --ocr-langs eng por

  # Espanhol para francês
  python epub_translator.py libro.epub livre.epub --source es --target fr

Códigos de idioma aceitos (exemplos):
  auto, af, sq, am, ar, hy, az, eu, be, bn, bs, bg, ca, ceb, ny,
  zh-CN, zh-TW, co, hr, cs, da, nl, en, eo, et, tl, fi, fr, fy,
  gl, ka, de, el, gu, ht, ha, haw, iw, hi, hmn, hu, is, ig, id,
  ga, it, ja, jw, kn, kk, km, ko, ku, ky, lo, la, lv, lt, lb,
  mk, mg, ms, ml, mt, mi, mr, mn, my, ne, no, or, ps, fa, pl,
  pt, pa, ro, ru, sm, gd, sr, st, sn, sd, si, sk, sl, so, es,
  su, sw, sv, tg, ta, te, th, tr, uk, ur, ug, uz, vi, cy, xh,
  yi, yo, zu
        """,
    )
    parser.add_argument("input", help="Caminho do arquivo EPUB de entrada")
    parser.add_argument("output", help="Caminho do arquivo EPUB de saída")
    parser.add_argument(
        "--source", "-s",
        default="auto",
        metavar="LANG",
        help="Idioma de origem (padrão: auto)",
    )
    parser.add_argument(
        "--target", "-t",
        default="pt",
        metavar="LANG",
        help="Idioma de destino (padrão: pt)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Ativa OCR em imagens para extrair e traduzir texto",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=["easyocr", "tesseract"],
        default="easyocr",
        help="Motor de OCR a utilizar (padrão: easyocr)",
    )
    parser.add_argument(
        "--ocr-langs",
        nargs="+",
        default=["en"],
        metavar="LANG",
        help="Idiomas para o OCR (padrão: en). Ex: --ocr-langs en pt",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=TRANSLATE_DELAY,
        metavar="SECONDS",
        help=f"Pausa entre requisições de tradução em segundos (padrão: {TRANSLATE_DELAY})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_CHUNK_CHARS,
        metavar="CHARS",
        help=f"Tamanho máximo de cada chunk em caracteres (padrão: {MAX_CHUNK_CHARS})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Exibe mensagens de debug detalhadas",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validações básicas
    if not os.path.isfile(args.input):
        logger.error("Arquivo de entrada não encontrado: %s", args.input)
        return 1

    if not args.input.lower().endswith(".epub"):
        logger.warning("O arquivo de entrada pode não ser um EPUB válido.")

    output_dir = os.path.dirname(os.path.abspath(args.output))
    if not os.path.isdir(output_dir):
        logger.error("Diretório de saída não existe: %s", output_dir)
        return 1

    # Aplica configurações de CLI às constantes globais
    global TRANSLATE_DELAY, MAX_CHUNK_CHARS
    TRANSLATE_DELAY = args.delay
    MAX_CHUNK_CHARS = args.chunk_size

    # Executa tradução
    translator = EPUBTranslator(
        source_lang=args.source,
        target_lang=args.target,
        ocr_enabled=args.ocr,
        ocr_engine=args.ocr_engine,
        ocr_languages=args.ocr_langs,
    )

    try:
        translator.translate(args.input, args.output)
    except KeyboardInterrupt:
        logger.warning("Tradução interrompida pelo usuário.")
        return 130
    except Exception as exc:
        logger.error("Erro fatal durante a tradução: %s", exc, exc_info=args.verbose)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
