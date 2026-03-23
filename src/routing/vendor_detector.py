from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.domain.enums import DocumentFamily
from src.routing.probe import ProbeResult


@dataclass
class VendorDetection:
    """Vendor signal outcome within an already selected document family."""

    vendor: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


class VendorDetector:
    """Family-scoped vendor detection. Only carrier invoices have rules today."""

    def detect_unknown(self) -> VendorDetection:
        return VendorDetection(vendor="unknown", confidence=0.0, evidence=[])

    def detect(self, family: str, input_path: Path, probe: ProbeResult, extra_text: str = "") -> VendorDetection:
        if family != DocumentFamily.CARRIER_INVOICE.value:
            return self.detect_unknown()

        # Vendor routing stays within the chosen family; this detector does not
        # reconsider the family itself.
        aggregate = f"{input_path.name}\n{probe.full_text}\n{extra_text}".lower()
        confidence = 0.0
        evidence: list[str] = []

        if "fedex" in aggregate:
            confidence += 0.55
            evidence.append("fedex_keyword")
        if "fedex express" in aggregate or "fedex ground" in aggregate:
            confidence += 0.25
            evidence.append("fedex_brand_variant")
        if "tracking id" in aggregate or "net charge" in aggregate:
            confidence += 0.2
            evidence.append("fedex_invoice_markers")
        confidence = min(confidence, 1.0)
        if confidence >= 0.4:
            return VendorDetection(vendor="fedex", confidence=confidence, evidence=evidence)
        return VendorDetection(vendor="unknown", confidence=confidence, evidence=evidence)
