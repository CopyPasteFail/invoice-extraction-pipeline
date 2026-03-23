from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.models import ExtractionPayload


@dataclass
class ExtractionResult:
    artifact_id: str
    family: str
    vendor: str
    extractor_key: str
    status: str
    data: ExtractionPayload
    field_states: dict[str, str] = field(default_factory=dict)
    missing_required_fields: list[str] = field(default_factory=list)
    invalid_required_fields: list[str] = field(default_factory=list)
    valid_important_fields: list[str] = field(default_factory=list)
    invalid_important_fields: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    fallback_confidence: float | None = None
    human_review_required: bool = False
    extras: dict[str, object] = field(default_factory=dict)

    def unresolved_must_have_fields(self) -> list[str]:
        return sorted(set(self.missing_required_fields + self.invalid_required_fields))
