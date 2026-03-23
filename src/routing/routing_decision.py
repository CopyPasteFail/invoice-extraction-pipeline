from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingDecision:
    artifact_id: str
    family: str
    family_confidence: float
    vendor: str
    vendor_confidence: float
    generic_extractor_key: str
    family_evidence: list[str] = field(default_factory=list)
    vendor_evidence: list[str] = field(default_factory=list)
