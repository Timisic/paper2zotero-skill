"""Real PDFs for extraction tests, drawn with PyMuPDF."""
from __future__ import annotations

import pymupdf


def pdf_with_text(*pages: str) -> bytes:
    """One page per argument, each drawing that text."""
    with pymupdf.open() as document:
        for body in pages:
            page = document.new_page()
            page.insert_textbox(page.rect + (36, 36, -36, -36), body, fontsize=6)
        return document.tobytes()


def pdf_without_text() -> bytes:
    """A scan: a page that draws only an image, never a glyph."""
    with pymupdf.open() as document:
        page = document.new_page()
        page.draw_rect(page.rect + (72, 72, -72, -72), fill=(0.2, 0.2, 0.2))
        return document.tobytes()
