from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config.loader import FamilyFieldPolicy
from src.domain.enums import FieldState
from src.domain.field_state import has_meaningful_value
from src.io.json_codec import JsonObject
from src.validation.schema_validation import SchemaIssue


def _tokenize(path: str) -> list[str]:
    return path.split(".")


def extract_values(payload: object, path: str) -> list[object]:
    return _extract_tokens(payload, _tokenize(path))


def _extract_tokens(current: object, tokens: list[str]) -> list[object]:
    if not tokens:
        return [current]

    token = tokens[0]
    remaining = tokens[1:]

    if token.endswith("[]"):
        key = token[:-2]
        if not isinstance(current, dict):
            return []
        values = current.get(key)
        if not isinstance(values, list):
            return []
        matches: list[object] = []
        for item in values:
            matches.extend(_extract_tokens(item, remaining))
        return matches

    if not isinstance(current, dict) or token not in current:
        return []
    return _extract_tokens(current[token], remaining)


def path_exists(payload: JsonObject, expression: str) -> bool:
    path = expression.replace(" exists", "").strip()
    return bool(extract_values(payload, path))


@dataclass
class ValidationSummary:
    """Normalized validation view used for gating, comparison, and review."""

    field_states: dict[str, str] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    important_fields: list[str] = field(default_factory=list)
    missing_required_fields: list[str] = field(default_factory=list)
    invalid_required_fields: list[str] = field(default_factory=list)
    valid_important_fields: list[str] = field(default_factory=list)
    invalid_important_fields: list[str] = field(default_factory=list)


class FieldPolicyValidator:
    """Applies YAML-defined required and important field rules to a payload."""

    policies: dict[str, FamilyFieldPolicy]

    def __init__(self, policies: dict[str, FamilyFieldPolicy]) -> None:
        self.policies = policies

    def validate(self, family: str, payload: JsonObject) -> ValidationSummary:
        policy = self.policies[family]
        required_paths = list(policy.required)
        # Conditional rules allow the policy file to express "if present, then
        # these child fields also become required" without extractor-specific code.
        for rule in policy.conditional:
            if path_exists(payload, rule.when):
                required_paths.extend(rule.require)

        summary = ValidationSummary(
            required_fields=sorted(dict.fromkeys(required_paths)),
            important_fields=list(policy.important),
        )
        for path in required_paths:
            state = self._evaluate_path(payload, path)
            summary.field_states[path] = state.value
            if state == FieldState.MISSING:
                summary.missing_required_fields.append(path)
            elif state == FieldState.INVALID:
                summary.invalid_required_fields.append(path)

        for path in policy.important:
            state = self._evaluate_path(payload, path)
            summary.field_states[path] = state.value
            if state == FieldState.VALID:
                summary.valid_important_fields.append(path)
            elif state == FieldState.INVALID:
                summary.invalid_important_fields.append(path)

        return summary

    def apply_schema_issues(self, summary: ValidationSummary, issues: list[SchemaIssue]) -> ValidationSummary:
        # Schema issues are folded back into the field-policy summary so later
        # stages can gate on one consolidated validation picture.
        required_fields = set(summary.required_fields)
        important_fields = set(summary.important_fields)
        missing_required = set(summary.missing_required_fields)
        invalid_required = set(summary.invalid_required_fields)
        valid_important = set(summary.valid_important_fields)
        invalid_important = set(summary.invalid_important_fields)

        for issue in issues:
            if not issue.path:
                continue

            normalized_path = normalize_schema_path(issue.path)
            is_missing = issue.code.startswith("missing")

            if normalized_path in required_fields:
                summary.field_states[normalized_path] = FieldState.MISSING.value if is_missing else FieldState.INVALID.value
                if is_missing:
                    missing_required.add(normalized_path)
                    invalid_required.discard(normalized_path)
                else:
                    invalid_required.add(normalized_path)
                    missing_required.discard(normalized_path)

            if normalized_path in important_fields and not is_missing:
                summary.field_states[normalized_path] = FieldState.INVALID.value
                invalid_important.add(normalized_path)
                valid_important.discard(normalized_path)

        summary.missing_required_fields = sorted(missing_required)
        summary.invalid_required_fields = sorted(invalid_required)
        summary.valid_important_fields = sorted(valid_important)
        summary.invalid_important_fields = sorted(invalid_important)
        return summary

    def _evaluate_path(self, payload: JsonObject, path: str) -> FieldState:
        matches = extract_values(payload, path)
        if not matches:
            return FieldState.MISSING
        if all(has_meaningful_value(match) for match in matches):
            return FieldState.VALID
        return FieldState.INVALID


def normalize_schema_path(path: str) -> str:
    """Convert indexed schema paths like items[0].value into policy paths like items[].value."""

    return re.sub(r"\[\d+\]", "[]", path)
