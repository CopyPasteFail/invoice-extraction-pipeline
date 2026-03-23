from __future__ import annotations

import argparse
from pathlib import Path

from src.config.loader import load_settings
from src.validation.business_validation import BusinessValidator
from src.validation.field_policy import FieldPolicyValidator
from src.validation.schema_validation import SchemaValidator, to_internal_validation_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a normalized extraction JSON file.")
    parser.add_argument("--family", required=True, help="Document family, for example carrier_invoice")
    parser.add_argument("--file", required=True, help="Path to JSON file")
    args = parser.parse_args()

    settings = load_settings(Path.cwd())
    validator = FieldPolicyValidator(settings.field_policies)
    schema_validator = SchemaValidator()
    business_validator = BusinessValidator()

    json_path = Path(args.file)
    payload = schema_validator.load_json(json_path)
    schema_errors = schema_validator.validate(args.family, payload, contract="published")
    validation_payload = to_internal_validation_payload(args.family, payload)
    summary = validator.validate(args.family, validation_payload)
    contradictions = business_validator.validate(args.family, payload)

    print(f"schema_errors={len(schema_errors)}")
    print(f"missing_required_fields={summary.missing_required_fields}")
    print(f"invalid_required_fields={summary.invalid_required_fields}")
    print(f"contradictions={contradictions}")

    return 1 if schema_errors or summary.missing_required_fields or summary.invalid_required_fields or contradictions else 0


if __name__ == "__main__":
    raise SystemExit(main())
