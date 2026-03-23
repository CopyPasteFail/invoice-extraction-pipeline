from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.app.execution_context import ExecutionContext
from src.app.pipeline import InvoiceExtractionPipeline
from src.config.loader import load_settings
from src.logging.structured_logger import StructuredLogger
from src.parsers.pdf_text import PdfTextExtractionError
from src.recovery.stub_provider import StubRecoveryProvider
from src.routing.probe import ProbeService
from src.routing.router import Router
from src.storage.local_artifact_store import LocalArtifactStore
from src.validation.business_validation import BusinessValidator
from src.validation.field_policy import FieldPolicyValidator
from src.validation.schema_validation import SchemaValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Invoice extraction pipeline demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="Extract a document into normalized JSON")
    extract_parser.add_argument("--input", required=True, help="Input file path")
    extract_parser.add_argument("--out", default=None, help="Output directory, defaults to config/app.yaml")
    return parser


def generate_artifact_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"art_{timestamp}_{uuid4().hex[:8]}"


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "extract":
        parser.error("Only the extract command is supported.")

    repo_root = Path.cwd()
    settings = load_settings(repo_root)
    input_path = (repo_root / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    if not input_path.exists():
        parser.error(f"Input file does not exist: {input_path}")

    output_dir = Path(args.out) if args.out else Path(settings.app.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()
    artifact_store = LocalArtifactStore(output_dir / "artifacts")
    logger = StructuredLogger(artifact_store)
    artifact_id = generate_artifact_id()

    context = ExecutionContext(
        artifact_id=artifact_id,
        input_path=input_path,
        output_dir=output_dir,
        settings=settings,
        artifact_store=artifact_store,
        logger=logger,
    )
    pipeline = InvoiceExtractionPipeline(
        router=Router(settings),
        probe_service=ProbeService(),
        schema_validator=SchemaValidator(),
        field_policy_validator=FieldPolicyValidator(settings.field_policies),
        business_validator=BusinessValidator(),
        recovery_provider=StubRecoveryProvider(),
    )

    try:
        result, output_path = pipeline.run(context)
    except PdfTextExtractionError as exc:
        print(f"error: {exc}")
        return 2

    print(f"artifact_id: {artifact_id}")
    print(f"family: {result.family}")
    print(f"vendor: {result.vendor}")
    print(f"chosen_extractor: {result.extractor_key}")
    print(f"status: {result.status}")
    print(f"output_path: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
