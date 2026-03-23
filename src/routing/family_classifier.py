from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from src.domain.enums import DocumentFamily
from src.parsers.text_utils import keyword_score
from src.routing.probe import ProbeResult


@dataclass
class FamilyClassification:
    """Single family decision with confidence, evidence, and raw scores."""

    family: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


class FamilyClassifier:
    """Heuristic classifier used exactly once at the start of the pipeline."""

    KEYWORDS: Final[dict[str, list[str]]] = {
        DocumentFamily.CARRIER_INVOICE.value: [
            "tracking",
            "customer number",
            "net charge",
            "service type",
            "fedex",
        ],
        DocumentFamily.OCEAN_INVOICE.value: [
            "ocean freight",
            "vessel",
            "voyage",
            "port of loading",
            "port of discharge",
        ],
        DocumentFamily.CUSTOMS_ENTRY.value: [
            "entry summary",
            "cbp form 7501",
            "customs entry",
            "entry number",
            "entry no",
            "hts",
            "broker",
            "customs value",
            "total taxes",
        ],
        DocumentFamily.SUPPLIER_WORKBOOK.value: [
            "batch",
            "category",
            "subtotal",
            "supplier",
            "period start",
        ],
    }

    def classify(self, input_path: Path, probe: ProbeResult) -> FamilyClassification:
        # Combine lightweight probe signals into a single lexical surface so the
        # family decision remains deterministic and easy to audit.
        full_text = "\n".join(
            [input_path.name, probe.first_page_text, probe.full_text, "\n".join(probe.sheet_names), "\n".join(probe.workbook_labels)]
        ).lower()

        scores: dict[str, float] = {}
        evidence_by_family: dict[str, list[str]] = {}
        for family, keywords in self.KEYWORDS.items():
            keyword_value, hits = keyword_score(full_text, keywords)
            extension_bias = 0.0
            if family == DocumentFamily.SUPPLIER_WORKBOOK.value and probe.extension in {".xlsx", ".xlsm", ".xls"}:
                extension_bias = 0.45
            elif family != DocumentFamily.SUPPLIER_WORKBOOK.value and probe.extension == ".pdf":
                extension_bias = 0.15
            elif probe.extension in {".txt", ".json"}:
                extension_bias = 0.05
            scores[family] = min(1.0, keyword_value + extension_bias)
            evidence_by_family[family] = hits

        best_family = max(scores, key=lambda family: scores[family])
        confidence = scores[best_family]
        evidence = evidence_by_family.get(best_family, [])

        # Low-signal fallbacks are intentionally simple: spreadsheets default to
        # workbook handling, while low-signal PDFs/text fall back to carrier flow.
        if confidence < 0.2 and probe.extension in {".xlsx", ".xlsm", ".xls"}:
            best_family = DocumentFamily.SUPPLIER_WORKBOOK.value
            confidence = 0.5
            evidence = ["spreadsheet_extension"]
        elif confidence < 0.2:
            best_family = DocumentFamily.CARRIER_INVOICE.value
            confidence = 0.25
            evidence = ["default_pdf_or_text_routing"]

        return FamilyClassification(family=best_family, confidence=confidence, evidence=evidence, scores=scores)
