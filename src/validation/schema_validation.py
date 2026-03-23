from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.domain.field_state import has_meaningful_value, is_non_empty_string
from src.io.json_codec import JsonObject


@dataclass(frozen=True)
class SchemaIssue:
    path: str | None
    code: str
    message: str


class SchemaValidator:
    COLLECTION_FIELDS_BY_CONTRACT: Final[dict[str, dict[str, list[str]]]] = {
        "internal": {
            "carrier_invoice": ["shipments[]", "shipments[].charges[]", "extras.raw_labels[]", "extras.notes[]"],
            "ocean_invoice": ["line_items[]", "extras.raw_labels[]", "extras.notes[]"],
            "customs_entry": ["line_items[]", "line_items[].subcodes[]", "extras.raw_labels[]", "extras.notes[]"],
            "supplier_workbook": ["categories[]", "categories[].line_items[]", "extras.raw_labels[]", "extras.notes[]"],
        },
        "published": {
            "carrier_invoice": ["shipments[]", "shipments[].charges[]"],
            "ocean_invoice": ["line_items[]"],
            "customs_entry": ["line_items[]", "line_items[].subcodes[]"],
            "supplier_workbook": ["categories[]", "categories[].line_items[]"],
        },
    }

    def load_json(self, path: Path) -> JsonObject:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            return loaded if isinstance(loaded, dict) else {}

    def validate(self, family: str, payload: JsonObject, contract: str = "internal") -> list[str]:
        return [issue.message for issue in self.inspect(family, payload, contract=contract)]

    def inspect(self, family: str, payload: JsonObject, contract: str = "internal") -> list[SchemaIssue]:
        issues: list[SchemaIssue] = []

        self._validate_collection_shapes(family, payload, issues, contract=contract)
        self._validate_extras(payload, issues, contract=contract)
        self._validate_scalar_types(payload, "", issues)
        return issues

    def _validate_collection_shapes(
        self,
        family: str,
        payload: JsonObject,
        issues: list[SchemaIssue],
        contract: str,
    ) -> None:
        collection_fields = self.COLLECTION_FIELDS_BY_CONTRACT[contract]
        for path in collection_fields.get(family, []):
            self._require_array_path(payload, path.split("."), path, issues)

    def _require_array_path(self, current: object, tokens: list[str], raw_path: str, issues: list[SchemaIssue]) -> None:
        if not tokens:
            return
        token = tokens[0]
        remaining = tokens[1:]

        if token.endswith("[]"):
            key = token[:-2]
            if not isinstance(current, dict) or key not in current:
                self._append_issue(issues, raw_path, "missing_collection", f"Missing collection field: {raw_path}")
                return
            if not isinstance(current[key], list):
                self._append_issue(issues, raw_path, "invalid_collection", f"Collection field must be an array: {raw_path}")
                return
            for item in current[key]:
                self._require_array_path(item, remaining, raw_path, issues)
            return

        if not isinstance(current, dict) or token not in current:
            self._append_issue(issues, raw_path, "missing_field", f"Missing field: {raw_path}")
            return

        next_value = current[token]
        if not remaining:
            return
        self._require_array_path(next_value, remaining, raw_path, issues)

    def _validate_extras(self, payload: JsonObject, issues: list[SchemaIssue], contract: str) -> None:
        extras = payload.get("extras")
        if not isinstance(extras, dict):
            if contract == "internal":
                self._append_issue(issues, "extras", "missing_extras", "extras must exist and be an object")
            return
        if not isinstance(extras.get("raw_labels"), list):
            self._append_issue(issues, "extras.raw_labels", "invalid_collection", "extras.raw_labels must be an array")
        if not isinstance(extras.get("notes"), list):
            self._append_issue(issues, "extras.notes", "invalid_collection", "extras.notes must be an array")
        if not isinstance(extras.get("unmapped_fields"), dict):
            self._append_issue(issues, "extras.unmapped_fields", "invalid_object", "extras.unmapped_fields must be an object")

    def _validate_scalar_types(self, current: object, path: str, issues: list[SchemaIssue]) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                child_path = f"{path}.{key}" if path else key
                self._validate_scalar_types(value, child_path, issues)
            return

        if isinstance(current, list):
            for index, item in enumerate(current):
                self._validate_scalar_types(item, f"{path}[{index}]", issues)
            return

        key_name = path.split(".")[-1]
        if key_name.endswith("date") or key_name in {"etd", "eta", "period_start", "period_end", "ship_date"}:
            if current is not None and (not isinstance(current, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", current)):
                self._append_issue(issues, path, "invalid_date", f"Expected ISO date string at {path}")
        elif key_name == "currency":
            if current is not None and (not isinstance(current, str) or not re.fullmatch(r"[A-Z]{3}", current)):
                self._append_issue(issues, path, "invalid_currency", f"Expected currency code at {path}")
        elif key_name == "quantity":
            if current is not None and not isinstance(current, (int, float, str)):
                self._append_issue(issues, path, "invalid_number", f"Expected numeric or string value at {path}")
        elif any(token in key_name for token in ("amount", "total", "subtotal", "weight", "rate")):
            if current is not None and not isinstance(current, (int, float)):
                self._append_issue(issues, path, "invalid_number", f"Expected numeric value at {path}")
        elif isinstance(current, str) and not has_meaningful_value(current):
            self._append_issue(issues, path, "invalid_placeholder", f"Invalid placeholder value at {path}")
        elif current is not None and key_name.endswith("number") and not is_non_empty_string(current):
            self._append_issue(issues, path, "invalid_string", f"Expected non-empty string at {path}")

    def _append_issue(self, issues: list[SchemaIssue], path: str | None, code: str, message: str) -> None:
        issues.append(SchemaIssue(path=path, code=code, message=message))


def to_internal_validation_payload(family: str, payload: JsonObject) -> JsonObject:
    normalized_payload = copy.deepcopy(payload)
    extras = normalized_payload.get("extras")
    if not isinstance(extras, dict):
        normalized_payload["extras"] = {
            "raw_labels": [],
            "unmapped_fields": {},
            "notes": [],
        }

    if family == "carrier_invoice":
        shipments = normalized_payload.get("shipments")
        if not isinstance(shipments, list):
            return normalized_payload
        for shipment in shipments:
            if not isinstance(shipment, dict):
                continue
            charges = shipment.get("charges")
            if not isinstance(charges, list):
                continue
            for charge in charges:
                if not isinstance(charge, dict):
                    continue
                if "description" not in charge and "type" in charge:
                    charge["description"] = charge["type"]

    return normalized_payload
