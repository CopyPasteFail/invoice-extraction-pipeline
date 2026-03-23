from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.io.files import read_text_best_effort
from src.parsers.pdf_probe import probe_pdf
from src.parsers.spreadsheet import inspect_workbook


@dataclass
class ProbeResult:
    extension: str
    file_size: int
    text_available: bool = False
    page_count: int = 0
    first_page_text: str = ""
    full_text: str = ""
    sheet_names: list[str] = field(default_factory=list)
    workbook_labels: list[str] = field(default_factory=list)
    lexical_signals: list[str] = field(default_factory=list)


class ProbeService:
    def probe(self, input_path: Path) -> ProbeResult:
        extension = input_path.suffix.lower()
        result = ProbeResult(extension=extension, file_size=input_path.stat().st_size)

        if extension == ".pdf":
            pdf_result = probe_pdf(input_path)
            result.text_available = pdf_result.text_available
            result.page_count = pdf_result.page_count
            result.first_page_text = pdf_result.first_page_text
            result.full_text = pdf_result.full_text
        elif extension in {".xlsx", ".xlsm", ".xls"}:
            workbook_snapshot = inspect_workbook(input_path)
            result.text_available = bool(workbook_snapshot.full_text.strip())
            result.sheet_names = workbook_snapshot.sheet_names
            result.workbook_labels = workbook_snapshot.top_rows_text
            result.full_text = workbook_snapshot.full_text
        else:
            raw_text = read_text_best_effort(input_path)
            result.text_available = bool(raw_text.strip())
            result.first_page_text = raw_text[:1000]
            result.full_text = raw_text

        lowered = f"{input_path.name}\n{result.first_page_text}\n{result.full_text}".lower()
        signals: list[str] = []
        for token in (
            "fedex",
            "carrier",
            "tracking",
            "ocean",
            "vessel",
            "customs",
            "entry",
            "hts",
            "supplier",
            "batch",
            "workbook",
        ):
            if token in lowered:
                signals.append(token)
        result.lexical_signals = signals
        return result
