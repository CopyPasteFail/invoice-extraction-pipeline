from __future__ import annotations

from dataclasses import dataclass, field

from src.config.loader import FamilyFieldPolicy
from src.domain.result import ExtractionResult
from src.io.json_codec import to_jsonable
from src.validation.field_policy import extract_values


@dataclass
class QualityComparison:
    preferred_result: ExtractionResult
    comparison_reason: str
    conflicts: list[str] = field(default_factory=list)
    scores: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


def _score(result: ExtractionResult) -> tuple[int, int, int, int]:
    return (
        len(set(result.field_states.values()) & {"valid"}) and len(result.field_states),
        -len(result.invalid_required_fields),
        -len(result.contradictions),
        len(result.valid_important_fields),
    )


def _normalize_values(values: list[object]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if isinstance(value, (dict, list)):
            normalized.append(str(to_jsonable(value)))
        else:
            normalized.append(str(value))
    return sorted(normalized)


def compare_results(first: ExtractionResult, second: ExtractionResult, policy: FamilyFieldPolicy) -> QualityComparison:
    first_score = (
        len(policy.required) - len(first.missing_required_fields) - len(first.invalid_required_fields),
        -len(first.invalid_required_fields),
        -len(first.contradictions),
        len(first.valid_important_fields),
    )
    second_score = (
        len(policy.required) - len(second.missing_required_fields) - len(second.invalid_required_fields),
        -len(second.invalid_required_fields),
        -len(second.contradictions),
        len(second.valid_important_fields),
    )

    conflicts: list[str] = []
    first_payload = to_jsonable(first.data)
    second_payload = to_jsonable(second.data)
    for path in policy.required:
        first_values = _normalize_values(extract_values(first_payload, path))
        second_values = _normalize_values(extract_values(second_payload, path))
        if first_values and second_values and first_values != second_values:
            conflicts.append(path)

    if second_score > first_score:
        preferred = second
        reason = "Dedicated candidate scored higher on must-have validity."
    else:
        preferred = first
        reason = "Generic candidate retained higher or equal quality."

    return QualityComparison(
        preferred_result=preferred,
        comparison_reason=reason,
        conflicts=conflicts,
        scores={"first": first_score, "second": second_score},
    )
