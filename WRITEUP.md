# Invoice Extraction Pipeline Solution

## 1. Solution overview

This solution implements a deterministic-first extraction pipeline for four document families: carrier invoices, ocean freight invoices, customs entries, and supplier invoice workbooks. The runtime flow is: probe input, classify family once, optionally detect vendor within that family, run the generic extractor, optionally reroute once to a dedicated extractor within the same family, validate the candidate, compare results when both generic and dedicated outputs exist, and then either complete, invoke fallback, or escalate to human review.

## 1.1 Decision flow

At a high level, the deterministic path moves through four stages:

1. Extraction phase
2. Validation phase
3. Scoring and ranking phase
4. Preferred-result selection

When only one deterministic extraction result exists, the pipeline validates that result and either completes or continues to fallback. When both a generic result and a dedicated result exist for the same artifact, the scoring and ranking stage compares those two results before selecting the preferred deterministic result.

```mermaid
flowchart TD
    A[Input artifact] --> B[Generate artifact_id and open artifact/log context]
    B --> C[Probe input
PDF text first, then OCR if needed]
    C --> D[Classify family once]
    D --> E[Detect vendor within chosen family]
    E --> F[Run family generic deterministic extractor]
    F --> G[Validate generic candidate
schema, field policy, business rules]
    G --> H{Generic candidate complete?}
    H -- Yes --> N[Publish normalized JSON output]
    H -- No --> I{Within-family reroute enabled and unused?}
    I -- No --> L[Invoke fallback provider stub]
    I -- Yes --> J[Redetect vendor within same family and run dedicated extractor when configured]
    J --> K[Validate dedicated candidate]
    K --> M[Compare generic vs dedicated quality
must-have completeness first, then invalid required fields, contradictions, important fields]
    M --> O{Best deterministic candidate complete?}
    O -- Yes --> N
    O -- No --> L
    L --> P[Merge fallback patch if any and revalidate]
    P --> Q{Still unresolved, contradictory, or low fallback confidence?}
    Q -- No --> N
    Q -- Yes --> R[Write review context and trigger human review]
    R --> N
```

## 2. Design goals

- Keep routing simple, explainable, and single-pass at the family level.
- Prefer deterministic extraction over opaque model behavior.
- Separate family routing, vendor routing, extraction, validation, fallback, review, and storage concerns.
- Make every run traceable through `artifact_id`-keyed artifacts and structured logs.
- Preserve a clean production path for replacing local storage and stubbed fallback components later.

## 3. Routing model

Family routing is single-pass. `FamilyClassifier` scores the document once from filename, probe text, sheet names, workbook labels, and extension bias, and the selected family is not reclassified later. Filename is still used as a weak heuristic input, so routing is not purely content-only.

Within the selected family, vendor routing is independent and optional. `VendorDetector` currently recognizes FedEx signals for `carrier_invoice`; other families keep vendor detection enabled structurally but resolve to `unknown` unless a dedicated vendor rule is configured.

The extractor flow is generic-first. The selected family always starts with its generic extractor. If required-field validation leaves unresolved must-have fields and within-family reroute is enabled, the pipeline redetects vendor once, stays in the same family, and may run a dedicated extractor. The final deterministic result is chosen by quality comparison rather than by automatically preferring the dedicated branch.

## 4. Required-field gating via YAML policy

Required, important, optional, and conditional fields are defined in [config/field_policies.yaml](config/field_policies.yaml). `FieldPolicyValidator` evaluates path-level presence and value quality, including array paths such as `shipments[].tracking_number` and conditional requirements such as requiring charge details when charges exist. This makes gating configuration-driven instead of hard-coded per extractor.

## 5. Validation model

**Validation is layered**:
- [Schema validation](src/validation/schema_validation.py) checks structure and field shapes.
- [Field-policy validation](src/validation/field_policy.py) checks must-have and important-field coverage.
- [Business validation](src/validation/business_validation.py) checks family-specific contradictions such as arithmetic mismatches, duplicate identifiers, or invalid date ordering.

Any unresolved must-have field or contradiction is treated as an incomplete deterministic result.

The solution now distinguishes between:

- the internal candidate payload used during extraction, reroute comparison, and fallback merging
- the published normalized JSON contract written to `out/{artifact_id}.json`, where `{artifact_id}` uses the template `art_YYYYMMDDHHMMSS_<8 hex chars>`.

## 6. Result quality comparison

When both generic and dedicated candidates exist, the pipeline compares them on must-have completeness first, then invalid required fields, contradictions, and valid important fields. For the canonical FedEx document, the dedicated extractor won because it scored higher on must-have validity; the comparison is score-based, not hard-wired to prefer dedicated output.

### Detailed explanation of the selection rule

This paragraph is describing the selection algorithm, then giving one concrete example of how that algorithm behaved on one file.

The pipeline can sometimes produce two deterministic candidates for the same document:

- a generic candidate - the broad extractor for that document family
- a dedicated candidate - a vendor-specific extractor, such as the FedEx extractor

The dedicated extractor is therefore not hard-coded as the winner. It wins only when its validated output is better.
The pipeline then needs a ranking step to decide which candidate becomes the preferred result.
The algorithm compares the two candidates in a fixed priority order:

1. Must-have completeness:
    Whether the required fields are present and usable. Examples include invoice number, invoice date, total amount, and tracking number.
2. Invalid required fields:
    Whether a required field exists but is malformed or unusable. For example, a date might be present but have an invalid value such as `13/99/abcd`.
3. Contradictions:
    Whether the extracted data disagrees with itself or violates business checks. For example, subtotal plus tax may fail to equal total. 
4. Valid important fields:
    Helpful but non-blocking fields, such as service type, zone, or reference number.

So the pipeline is effectively asking the following:

1. Which candidate has more valid required data?
2. If that is tied, which candidate has fewer broken required fields?
3. If that is tied, which candidate has fewer contradictions?
4. If that is tied, which candidate has more valid important fields?

##### Example
Suppose the pipeline produces two results for the same FedEx invoice: one from the generic extractor and one from the dedicated FedEx extractor.

**Result from the generic extractor**:

- invoice number: valid
- invoice date: valid
- total amount: valid
- tracking number: missing
- service type: missing

**Result from the dedicated FedEx extractor**:

- invoice number: valid
- invoice date: valid
- total amount: valid
- tracking number: valid
- service type: valid

In that case, both candidates contain useful data, but the dedicated candidate has stronger must-have completeness, so the dedicated candidate wins.

The reverse outcome is also possible. Suppose the dedicated extractor introduces an invalid invoice date or produces a totals mismatch, while the generic candidate remains internally consistent:

**Result from the generic extractor**:

- invoice number: valid
- invoice date: valid
- total amount: valid
- tracking number: valid
- contradictions: none

**Result from the dedicated FedEx extractor**:

- invoice number: valid
- invoice date: invalid format
- total amount: valid
- tracking number: valid
- contradictions: total does not match charges

In that case, the dedicated extractor still exists, but its output is worse, so the generic candidate should win. That is why the writeup says the comparison is not hard-wired to prefer dedicated output.


## 7. Fallback stub design

Fallback is implemented behind a provider interface and is currently configured as a stub. If deterministic extraction still has unresolved must-have fields or contradictions, the pipeline invokes the recovery provider, merges its patch into the best deterministic payload, and revalidates the merged result. The merged payload is now revalidated directly as a dict so fallback does not silently drop fields through a lossy model rebuild. In the current implementation, the stub returns no data patch, zero confidence, and explicit notes that no external model call was performed.

## 8. PDF and OCR runtime behavior

PDF handling is explicit. The pipeline first attempts embedded-text extraction through `pypdf`. If no usable embedded text is present, it falls back to page rendering with `pypdfium2` plus OCR through `rapidocr_onnxruntime`. The previous raw-binary PDF text fallback was removed.

If a PDF has no usable embedded text and the OCR stack is unavailable in the active venv, the CLI now fails clearly instead of silently degrading.

## 9. Human review trigger rules

Human review is triggered when unresolved required fields remain, when business contradictions remain, or when fallback runs with confidence below the configured threshold. When review is required, the solution writes a review context artifact containing the normalized payload, validation issues, fallback confidence, and reviewer guidance.

## 10. Artifact storage abstraction

Artifacts are written through an `ArtifactStore` interface. The current implementation is local and stores the original input, normalized output, execution metadata, review context, and event log under `out/artifacts/{artifact_id}/`. These generated artifacts are runtime output, not canonical source files.

The abstraction is already shaped for a bucket-oriented production design. A future implementation can preserve the same logical layout while moving persistence to object storage without changing pipeline orchestration or logging semantics.

## 11. `artifact_id` and structured logging

Each run receives a generated `artifact_id` and all persisted outputs and JSONL events are keyed by it. The structured logger records pipeline milestones such as probe completion, family selection, vendor detection, extractor selection, validation summaries, quality comparison, fallback events, review escalation, and final output write. This gives the solution an audit trail suitable for operational debugging and downstream observability.

## 12. Adding a format

Plan for adding a new format:

1. **Choose the routing level**
    Decide whether the new format is a new document family or a new vendor-specific pattern inside an existing family.
    This choice determines whether you add a new generic family path or a dedicated extractor behind the existing within-family reroute path.

2. **Update routing rules**
    If the format is a new family, add or extend family signals in [`src/routing/family_classifier.py`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/routing/family_classifier.py) and add the family route in `config/routing.yaml`. If the format is a vendor-specific pattern inside an existing family, keep the family the same and extend [`src/routing/vendor_detector.py`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/routing/vendor_detector.py) plus the vendor mapping in `config/routing.yaml`.

3. **Implement the extractor class**
    All extractor classes inherit from [`BaseExtractor`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/extractors/base.py). A new family usually needs a new generic extractor under `src/extractors/generic/`. A new vendor-specific format usually needs a new dedicated extractor under `src/extractors/dedicated/`. The pipeline instantiates these extractor classes in [`InvoiceExtractionPipeline`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/app/pipeline.py), so that file must be updated to register the new extractor key and class.

4. **Update the normalized output contract for that family**
    Add or update the family model in [`src/domain/models.py`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/domain/models.py) if the new format introduces fields that are part of the normalized schema for that family.

5. **Update validation rules**
    Add required, important, optional, or conditional fields in `config/field_policies.yaml`. If the new format introduces family-specific consistency checks, add them in [`src/validation/business_validation.py`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/validation/business_validation.py). Structural validation continues to run through [`src/validation/schema_validation.py`](/mnt/d/codex_projects/invoice-extraction-pipeline/src/validation/schema_validation.py).

6. **Add end-to-end verification data**
    Add a sample input file in `invoices/` and its expected normalized JSON in `expected_output/` so the full flow can be checked end to end.

Code architecture note:
[router.py](/mnt/d/codex_projects/invoice-extraction-pipeline/src/routing/router.py) makes one family decision first and only then refines routing within that family.
`InvoiceExtractionPipeline`in [pipeline.py](/mnt/d/codex_projects/invoice-extraction-pipeline/src/app/pipeline.py) owns the extractor registry and runs the selected extractor. This means most format additions are additive extensions to routing configuration, one `BaseExtractor` subclass, and validation rules, rather than changes to top-level orchestration.

## 13. Out-of-scope items

- Reclassifying document family after the initial family decision.
- A production LLM or external recovery service behind the fallback interface.
- Multi-vendor dedicated extractors beyond FedEx.
- Queueing, orchestration, and reviewer workflow UX beyond emitting review artifacts.
- Remote object storage implementation and retention policy.

## 14. Verification summary

The end-to-end match results against `expected_output/` are described in `README.md`.
This section only lists the additional verification facts from `src/verification/report.py`:

- all 4 input files in `invoices/` were classified into the correct family on the first pass
- rerouting within the same family happened at most once per file
- the FedEx PDF file in `invoices/` does not contain usable embedded text, so the pipeline uses OCR to read it, routes it to the dedicated FedEx extractor, and completes successfully
- fallback and human review are implemented, but they were not triggered in the final FedEx run

## Tradeoffs

This solution is intentionally deterministic-first because deterministic routing, extraction, and validation are easier to audit, tune, and operate than an always-generative pipeline. The fallback path remains stubbed because the production integration point is deliberately isolated behind an interface, but the current pipeline in this repo does not depend on any external recovery service.
Family reclassification is intentionally out of scope because the design optimizes for predictable control flow and bounded routing complexity rather than recursive retry behavior.

## AI Collaboration

AI was used as a copilot for design framing, implementation iteration, and document review, not as the runtime extraction engine. The primary setup was the Codex app and VS Code using GPT-5.4 for code and writeup iteration, with ChatGPT used for design oversight and initial prompt generation, plus targeted review and rewrite passes.

The working pattern was narrow prompts, inspect the generated change, then tighten constraints and iterate until the behavior or explanation matched the intended architecture. AI helped most with accelerating boilerplate-heavy refactors, tightening technical prose, and surfacing edge cases to verify. It was less reliable on architecture-specific details, especially when asked to infer pipeline invariants or claim behavior without checking the current code, so deterministic logic, validation rules, and final wording still required manual review.
