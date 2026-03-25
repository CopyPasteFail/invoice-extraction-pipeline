# Invoice Extraction Pipeline

Architecture demo for deterministic-first invoice and document extraction with:

- a single CLI entry point
- family routing
- within-family vendor detection
- deterministic generic and dedicated extractors
- validation, quality comparison, fallback, and review escalation
- local artifact storage and structured logs keyed by `artifact_id`

## Architecture

- [System Architecture](docs/architecture/system-architecture.md)
- [Architecture Overview Diagram](docs/architecture/architecture-overview.md)
- [Design Review Notes](docs/architecture/design-review-notes.md)
- [Pipeline Routing](docs/architecture/pipeline-routing.md)

## Quick start

Runtime: Python 3.13 in a local repo-root venv.

### Linux

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m src.cli extract --input invoices/ocean_freight_INV2025001.pdf --out out
```

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m src.cli extract --input invoices/ocean_freight_INV2025001.pdf --out out
```

## Developers

Install the dedicated hook venv once:

### Linux

```bash
./scripts/setup-dev-hooks.sh
```

### Windows PowerShell

```powershell
.\scripts\setup-dev-hooks.ps1
```

`pre-push` then runs `mypy`, `ruff`, and `bandit` from `.venv-hooks`.

The dependency set includes PDF text extraction, spreadsheet parsing, PDF rasterization, and OCR support:

- `pypdf` for embedded PDF text extraction
- `openpyxl` for workbook inputs
- `pypdfium2` for rendering PDF pages when a PDF does not contain usable embedded text
- `rapidocr_onnxruntime` for OCR on rendered page images
- `opencv-python` as the `rapidocr_onnxruntime` image backend dependency

The current implementation does not require system Tesseract or Poppler. If a future OCR backend adds system-level dependencies, those must be installed separately.

> If embedded text is unavailable in the PDF and the OCR packages are not installed, the CLI fails clearly instead of silently reading raw PDF bytes as text.

## Repo structure

```text
repo/
├── src/                # pipeline implementation
├── config/             # application settings
├── invoices/           # sample input documents
├── expected_output/    # canonical expected normalized JSON
├── generators/         # sample-data generation helpers
├── out/                # generated runtime output
├── validate.py         # single-file contract validator
├── README.md           # usage and setup
└── WRITEUP.md          # architecture notes
```

### Generated after running the pipeline

The pipeline writes runtime output under `out/`. These files are generated artifacts, not source files.

```text
out/
├── {artifact_id}.json
├── artifacts/
│   └── {artifact_id}/
│       ├── input/
│       │   └── original{input_extension}
│       ├── output/
│       │   ├── extracted.json
│       │   └── execution_metadata.json
│       ├── logs/
│       │   └── events.jsonl
│       └── review/
│           └── context.json   # only when human review is required
└── verification_report.json   # generated only by the verification runner
```

Template notes:

- `{artifact_id}` is generated per run in the format `art_YYYYMMDDHHMMSS_<8 hex chars>`.
- `{input_extension}` matches the original input file suffix such as `.pdf` or `.xlsx`.
- The top-level published output file is written as `out/{artifact_id}.json`.

- `out/*.json`: published normalized extraction output for each processed input.
- `out/artifacts/{artifact_id}/`: per-run artifact directory keyed by the generated `artifact_id`.
- `out/artifacts/{artifact_id}/input/`: a copy of the original input file for that run.
- `out/artifacts/{artifact_id}/output/`: per-run extracted JSON and execution metadata.
- `out/artifacts/{artifact_id}/logs/events.jsonl`: structured JSONL event log for pipeline milestones and decisions.
- `out/artifacts/{artifact_id}/review/`: emitted review context when the run requires human review.
- `out/verification_report.json`: latest regression summary produced by running the pipeline against the canonical input set and comparing the results to the canonical expected outputs. It is generated only by the verification runner, not by normal pipeline runs.

The pipeline writes:

- normalized JSON to `out/`
- runtime artifacts to `out/artifacts/{artifact_id}/`
- structured runtime events to `out/artifacts/{artifact_id}/logs/events.jsonl`

## Validation

This repo has two verification layers with different scopes

### `validate.py`

validates one published normalized JSON file against the output contract (i.e. the JSON matches the expected schema/business rules).

The pipeline uses an internal payload during extraction, and a different published payload for the final JSON output.

- Internal payloads may include runtime-only fields such as `extras`.
- The final published JSON omits those runtime-only fields.
- The final published JSON includes `doc_type`.
- Carrier-invoice charge rows use `type` in the final published JSON.
- `validate.py` validates the final published JSON shape.

Example against a pipeline-produced output file:

```bash
./.venv/bin/python -m src.cli extract --input invoices/fedex_901234567.pdf --out out
./.venv/bin/python validate.py --family carrier_invoice --file out/fedex_901234567.json
```

The CLI supports only these arguments:

- `--family`: required document family name such as `carrier_invoice`
- `--file`: required path to the JSON file to validate

The command prints:

- `schema_errors`
- `missing_required_fields`
- `invalid_required_fields`
- `contradictions`

It exits with status `1` when any schema errors, missing required fields, invalid required fields, or business-rule contradictions are present.
Otherwise it exits with status `0`.

### `src.verification.report`

This command performs end-to-end verification of the extraction pipeline.

What it does:

- runs the pipeline on the canonical input corpus in `invoices/`
- loads the matching expected JSON files from `expected_output/`
- compares actual output to expected output
- records exact-match status and diffs in `out/verification_report.json`

```bash
./.venv/bin/python -m src.verification.report
```

What it is for:

- regression testing against the benchmark corpus
- checking pipeline behavior after code changes
- confirming that classification, routing, extraction, and final normalization still produce the expected results

A file can pass `validate.py` and still fail this check if the pipeline extracted the wrong values, selected the wrong family, or produced output that differs from the canonical expected file.

## Notes

- The fallback provider is intentionally stubbed: the stage exists in the control flow for architecture completeness, but this demo does not send documents to any remote LLM, OCR API, or third-party extraction service when fallback is reached.
- Family classification is single-pass only in this demo: this means the classifier makes one document-family decision and the pipeline proceeds with that result, rather than running a second classification attempt, re-ranking alternatives, or revisiting the decision after extraction feedback.
- Dedicated vendor routing is implemented for FedEx carrier invoices. In practice, this means FedEx carrier invoices have a vendor-specific extraction path with specialized logic, while other supported document families continue through the generic family-level routing and extraction flow.
- Family classification uses the filename as a low-weight signal when inferring the document family, but the filename is not used to directly infer the vendor identity.
- The current end-to-end verification result against `expected_output/` has two cases:
  - The ocean freight, customs, and supplier canonical inputs match their expected normalized JSON exactly.
  - The FedEx canonical PDF does not contain usable embedded text, so this path depends on OCR. It is not yet perfectly aligned because `actual_weight_kg` and `billed_weight_kg` still differ. These remaining differences are precision-only and OCR-limited, which means the mismatch is caused by the OCR-visible source exposing lower numeric precision than the canonical JSON, not by incorrect routing or a broader extraction failure.
