# Pipeline Routing

## Purpose

This document explains how the repository routes an input artifact through family selection, vendor detection, extractor selection, and within-family reroute.

It is implementation-focused. The source of truth remains the current code in:

- `src/routing/family_classifier.py`
- `src/routing/vendor_detector.py`
- `src/routing/router.py`
- `src/app/pipeline.py`
- `config/routing.yaml`
- `config/app.yaml`

## Routing model

The routing model is intentionally deterministic, simple, and bounded:

- document family is classified once
- vendor detection stays inside the selected family
- the first extractor is always the family's generic extractor
- a dedicated extractor is only attempted as a within-family reroute
- reroute can happen at most once

This means the pipeline does not recursively reclassify a document family and does not start with a vendor-specific extractor.

## Step-by-step flow

1. Probe the input artifact.
   The probe stage extracts lightweight signals such as file extension, embedded PDF text, OCR text, workbook sheet names, and workbook labels.

2. Classify the document family once.
   `FamilyClassifier` builds a single text surface from the filename, probe text, sheet names, and workbook labels, then scores each supported family using fixed keywords plus a small extension bias.

3. Select the generic extractor for that family.
   `Router.route_initial()` always returns the generic extractor configured for the chosen family in `config/routing.yaml`.

4. Detect vendor inside that family.
   Vendor detection does not change the family. It only provides a possible vendor label such as `fedex` within the already selected family.

5. Run the generic extractor first.
   The pipeline always validates the generic candidate before deciding whether a dedicated extractor should run.

6. Attempt a within-family reroute only if the generic result is incomplete.
   If the generic result still has unresolved must-have fields, and `allow_within_family_reroute_once` is enabled, the pipeline redetects vendor and may run a dedicated extractor for that vendor.

7. Compare generic and dedicated results when both exist.
   The preferred deterministic result is chosen by validation quality, not by automatically preferring the dedicated extractor.

## Family classification

Family classification is implemented in `FamilyClassifier`.

The classifier creates one lowercase aggregate text value from:

- the input filename
- `probe.first_page_text`
- `probe.full_text`
- workbook sheet names
- workbook labels

It then scores each supported family using fixed keyword lists:

- `carrier_invoice`
- `ocean_invoice`
- `customs_entry`
- `supplier_workbook`

The scoring also applies a small file-type bias:

- spreadsheets favor `supplier_workbook`
- PDFs slightly favor non-workbook families
- `.txt` and `.json` receive a small general bias

The family with the highest score wins.

If the signal is too weak, the classifier falls back deliberately:

- low-signal spreadsheets default to `supplier_workbook`
- other low-signal files default to `carrier_invoice`

This is a heuristic classifier. It is not model-based.

## Vendor detection

Vendor detection is implemented in `VendorDetector`.

Vendor detection is family-scoped:

- if the family is not `carrier_invoice`, the detector returns `unknown`
- for `carrier_invoice`, the detector currently looks for FedEx-specific lexical signals

Those signals include terms such as:

- `fedex`
- `fedex express`
- `fedex ground`
- `tracking id`
- `net charge`

If the confidence passes the configured threshold, the detected vendor becomes `fedex`. Otherwise the vendor remains `unknown`.

Vendor detection can run twice:

- once during initial routing
- once during the reroute check, using both probe text and the generic extraction output as additional text surface

Even on the second pass, vendor detection still cannot change the family.

## Why extraction is generic-first

The extractor flow is intentionally generic-first.

The initial route establishes the family and selects the family's generic extractor. This keeps the first-pass routing simple and consistent across families, and avoids hard-coding vendor-specific behavior as the default path.

The dedicated path is a bounded recovery path inside the same family. It exists to improve extraction when the generic candidate fails required-field validation, not to replace the generic path entirely.

## FedEx example

For a FedEx invoice, the normal path is:

1. classify the artifact as `carrier_invoice`
2. detect vendor signals that may indicate `fedex`
3. run `generic.carrier_invoice`
4. validate the generic candidate
5. if must-have fields are still unresolved, redetect vendor and possibly run `dedicated.fedex_carrier_invoice`
6. compare generic and dedicated candidates
7. keep the better validated result

This is why a FedEx document can pass through the generic extractor before the dedicated FedEx extractor runs.

## Selection rule

When both a generic candidate and a dedicated candidate exist for the same artifact, the pipeline compares them and selects the preferred deterministic result by validation quality.

The comparison uses this priority order:

1. Must-have completeness.
   The pipeline first prefers the candidate with stronger required-field completeness.

2. Invalid required fields.
   If must-have completeness is tied, the pipeline prefers the candidate with fewer malformed or unusable required fields.

3. Contradictions.
   If required-field quality is still tied, the pipeline prefers the candidate with fewer business-rule contradictions.

4. Valid important fields.
   If the candidates are still tied, the pipeline prefers the candidate with stronger coverage of important but non-blocking fields.

This means the dedicated extractor is not hard-coded as the winner. It wins only when its validated result is better than the generic candidate.

### Example

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

In that case, the dedicated extractor still exists, but its output is worse, so the generic candidate should win.

## Configuration points

The main routing configuration lives in:

- `config/routing.yaml` for family-to-generic-extractor mapping and vendor-to-dedicated-extractor mapping
- `config/app.yaml` for reroute enablement

The relevant controls are:

- `families.<family>.generic_extractor`
- `families.<family>.vendor_detection_enabled`
- `families.<family>.vendor_confidence_threshold`
- `families.<family>.vendors.<vendor>.confidence_threshold`
- `families.<family>.vendors.<vendor>.dedicated_extractor`
- `app.allow_within_family_reroute_once`

## Change guide

When adding a new format, decide first whether it is:

- a new document family
- a vendor-specific format inside an existing family

If it is a new family:

- extend `FamilyClassifier`
- add the family route in `config/routing.yaml`
- implement a new generic extractor

If it is a vendor-specific format inside an existing family:

- extend `VendorDetector`
- add the vendor mapping in `config/routing.yaml`
- implement a new dedicated extractor

If the change affects required-field completeness or comparison behavior, update field policies and validation rules as well.

## Extending the pipeline

Use this checklist when adding a new vendor, a new vendor-specific format, or a new document family.

1. Choose the routing level.
   Decide whether the new format is a new document family or a vendor-specific pattern inside an existing family. This determines whether you add a new generic family path or a dedicated extractor behind the existing within-family reroute path. See [Change guide](#change-guide).

2. Update routing rules.
   If the format is a new family, add or extend family signals in `src/routing/family_classifier.py` and add the family route in `config/routing.yaml`. If the format is a vendor-specific pattern inside an existing family, keep the family the same and extend `src/routing/vendor_detector.py` plus the vendor mapping in `config/routing.yaml`.

3. Implement the extractor class.
   All extractor classes inherit from `BaseExtractor`. A new family usually needs a new generic extractor under `src/extractors/generic/`. A new vendor-specific format usually needs a new dedicated extractor under `src/extractors/dedicated/`. The pipeline registers these extractor classes in `src/app/pipeline.py`, so that file must be updated to register the new extractor key and class.

4. Update the normalized output contract for that family.
   Add or update the family model in `src/domain/models.py` if the new format introduces fields that are part of the normalized schema for that family.

5. Update validation rules.
   Add required, important, optional, or conditional fields in `config/field_policies.yaml`. If the new format introduces family-specific consistency checks, add them in `src/validation/business_validation.py`. Structural validation continues to run through `src/validation/schema_validation.py`.

6. Add end-to-end verification data.
   Add a sample input file in `invoices/` and its expected normalized JSON in `expected_output/` so the full flow can be checked end to end.

## Code ownership notes

- `src/routing/router.py` makes one family decision first and only then refines routing within that family.
- `src/app/pipeline.py` owns the extractor registry and runs the selected extractor.

Most new formats should therefore be additive changes to routing configuration, one extractor implementation, and validation rules rather than changes to the top-level orchestration flow.
