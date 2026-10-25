"""PDF text extraction (pdfplumber) and the text similarity used to pair a .pdf with its .txt.

Extraction never raises: a corrupt, encrypted or image-only PDF comes back with
``has_text=False`` and a reason, and the caller marks the document unparseable.
"""
from __future__ import annotations

import difflib
import io
import logging
import re
from dataclasses import dataclass

MIN_TEXT_CHARS = 20          # less than this after stripping = no usable text layer
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class PdfText:
    text: str
    pages: int
    has_text: bool
    reason: str | None = None


def extract_pdf_text(data: bytes) -> PdfText:
    logging.getLogger("pdfminer").setLevel(logging.ERROR)  # font warnings on every page otherwise
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - depends on the install
        return PdfText("", 0, False, "pdfplumber is not installed (pip install -r requirements.txt)")
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:  # noqa: BLE001 - any parser failure means "unparseable", never a crash
        return PdfText("", 0, False, f"could not read the PDF ({type(exc).__name__}: {str(exc)[:200]})")
    text = "\n\n".join(p.rstrip() for p in pages).strip("\n")
    if len(text.strip()) < MIN_TEXT_CHARS:
        return PdfText(text, len(pages), False,
                       f"no text layer ({len(pages)} page(s), {len(text.strip())} characters): a scanned image? "
                       "OCR is not available; upload the .txt or a text-based PDF")
    return PdfText(text, len(pages), True)


def text_similarity(a: str, b: str) -> float:
    """0..1 similarity of two texts by their word sequences (case, punctuation and layout ignored)."""
    wa, wb = _WORD_RE.findall(a.lower()), _WORD_RE.findall(b.lower())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()
