from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, cast

from src.parsers.text_utils import normalize_whitespace


def _import_optional_module(module_name: str) -> Any | None:
    """Load an optional module by name.

    Args:
        module_name: Fully qualified module name to import.

    Returns:
        The imported module object when available, otherwise ``None``.

    Edge cases:
        Any import-time failure, including missing packages and transitive import
        errors from optional native dependencies, returns ``None`` so callers can
        degrade gracefully.
    """
    try:
        return importlib.import_module(module_name)
    except Exception:  # pragma: no cover - optional import safety
        return None


pypdf = _import_optional_module("pypdf")
np = _import_optional_module("numpy")
pdfium = _import_optional_module("pypdfium2")
rapidocr_onnxruntime = _import_optional_module("rapidocr_onnxruntime")


class PdfTextExtractionError(RuntimeError):
    pass


class OcrEngine(Protocol):
    def __call__(self, image: object) -> tuple[list[tuple[object, str]], object]: ...


@lru_cache(maxsize=1)
def _get_ocr_engine() -> OcrEngine | None:
    if rapidocr_onnxruntime is None:
        return None
    try:
        return cast(OcrEngine, rapidocr_onnxruntime.RapidOCR())
    except Exception:
        return None


def _extract_page_texts_with_pypdf(path: Path) -> list[str]:
    if pypdf is None or path.read_bytes()[:4] != b"%PDF":
        return []
    try:
        reader = pypdf.PdfReader(str(path))
        return [normalize_whitespace(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return []


def _extract_page_texts_with_ocr(path: Path) -> list[str]:
    if pdfium is None or np is None:
        return []
    ocr_engine = _get_ocr_engine()
    if ocr_engine is None:
        return []
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception:
        return []

    page_texts: list[str] = []
    for page in document:
        try:
            rendered = page.render(scale=2).to_pil()
            image_array = np.array(rendered)
            ocr_result, _ = ocr_engine(image_array)
            if not ocr_result:
                page_texts.append("")
                continue
            page_texts.append(normalize_whitespace("\n".join(line[1] for line in ocr_result)))
        except Exception:
            page_texts.append("")
    return page_texts


@lru_cache(maxsize=16)
def _extract_pdf_page_texts(path_value: str) -> tuple[tuple[str, ...], int]:
    path = Path(path_value)
    if pypdf is None:
        raise PdfTextExtractionError(
            "Missing required PDF dependency 'pypdf'. Install the project requirements in the active venv."
        )

    page_texts = _extract_page_texts_with_pypdf(path)
    if any(text.strip() for text in page_texts):
        return tuple(page_texts), len(page_texts)

    if pdfium is None or np is None or rapidocr_onnxruntime is None:
        raise PdfTextExtractionError(
            "PDF has no usable embedded text and OCR dependencies are unavailable. "
            "Install 'pypdfium2' and 'rapidocr_onnxruntime' in the active venv."
        )

    page_texts = _extract_page_texts_with_ocr(path)
    return tuple(page_texts), len(page_texts)


def extract_pdf_text(path: Path, max_pages: int | None = None) -> tuple[str, int]:
    page_texts, page_count = _extract_pdf_page_texts(str(path.resolve()))
    page_limit = page_count if max_pages is None else min(page_count, max_pages)
    selected_pages = list(page_texts[:page_limit])
    return normalize_whitespace("\n".join(selected_pages)), page_count
