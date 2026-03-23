from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.parsers.pdf_text import extract_pdf_text


@dataclass
class PdfProbeResult:
    text_available: bool
    page_count: int
    first_page_text: str
    full_text: str


def probe_pdf(path: Path) -> PdfProbeResult:
    first_page_text, _ = extract_pdf_text(path, max_pages=1)
    full_text, page_count = extract_pdf_text(path)
    return PdfProbeResult(
        text_available=bool(full_text.strip()),
        page_count=page_count,
        first_page_text=first_page_text,
        full_text=full_text,
    )
