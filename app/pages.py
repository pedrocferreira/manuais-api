"""Renderiza paginas dos PDFs como imagem PNG, com destaque dos termos buscados.

As imagens ficam em cache em disco (data/page_cache) para nao renderizar duas vezes.
"""
import hashlib
import pathlib
import re
import threading
import unicodedata

import fitz  # pymupdf

from . import db

CACHE_DIR = db.BASE / "data" / "page_cache"
MAX_ZOOM = 4.0
_render_lock = threading.Lock()  # PyMuPDF nao e thread-safe por documento


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _highlight_variants(page: fitz.Page, terms: list[str]) -> list[str]:
    """search_for do PyMuPDF diferencia acentos; busca no texto da pagina as
    grafias reais das palavras (ex.: termo 'oleo' vira tambem 'óleo')."""
    words = set(re.findall(r"[\w\-]{2,}", page.get_text("text")))
    by_norm: dict[str, set[str]] = {}
    for w in words:
        by_norm.setdefault(_strip_accents(w), set()).add(w)
    variants: set[str] = set()
    for t in terms:
        variants |= by_norm.get(_strip_accents(t), set())
        variants.add(t)
    return sorted(variants)


def render_page_png(manual: dict, page_number: int, zoom: float = 2.0,
                    highlight_terms: list[str] | None = None) -> bytes:
    """Renderiza a pagina (1-based) como PNG. Levanta ValueError se a pagina nao existe."""
    zoom = max(1.0, min(MAX_ZOOM, zoom))
    highlight_terms = [t for t in (highlight_terms or []) if t.strip()]

    key = hashlib.sha1(
        f"{manual['id']}|{page_number}|{zoom}|{'|'.join(sorted(highlight_terms))}".encode()
    ).hexdigest()[:20]
    cache_file = CACHE_DIR / manual["id"] / f"p{page_number}_{key}.png"
    if cache_file.exists():
        return cache_file.read_bytes()

    pdf_path = db.MANUALS_DIR / manual["file"]
    with _render_lock:
        doc = fitz.open(pdf_path)
        try:
            if not 1 <= page_number <= doc.page_count:
                raise ValueError(f"Pagina {page_number} fora do intervalo (1-{doc.page_count})")
            page = doc[page_number - 1]
            for term in _highlight_variants(page, highlight_terms):
                for rect in page.search_for(term):
                    annot = page.add_highlight_annot(rect)
                    annot.set_colors(stroke=(1, 0.85, 0.2))
                    annot.update()
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            png = pix.tobytes("png")
        finally:
            doc.close()

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(png)
    return png


def image_url(manual_id: str, page: int, terms: list[str] | None = None) -> str:
    from urllib.parse import quote
    url = f"/manuals/{manual_id}/pages/{page}/image"
    if terms:
        url += f"?highlight={quote(','.join(terms))}"
    return url
