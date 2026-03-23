from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Final, cast

from src.app.execution_context import ExecutionContext
from src.domain.enums import PipelineStatus
from src.domain.models import ExtractionPayload, is_extraction_payload
from src.domain.result import ExtractionResult
from src.extractors.base import BaseExtractor
from src.extractors.dedicated.fedex_carrier_invoice import FedExCarrierInvoiceExtractor
from src.extractors.generic.carrier_invoice import GenericCarrierInvoiceExtractor
from src.extractors.generic.customs_entry import GenericCustomsEntryExtractor
from src.extractors.generic.ocean_invoice import GenericOceanInvoiceExtractor
from src.extractors.generic.supplier_workbook import GenericSupplierWorkbookExtractor
from src.io.json_codec import JsonObject, as_json_object, merge_dicts, to_jsonable, write_json
from src.logging import events
from src.recovery.base import RecoveryProvider
from src.routing.probe import ProbeService
from src.routing.router import Router
from src.validation.business_validation import BusinessValidator
from src.validation.field_policy import FieldPolicyValidator
from src.validation.quality import compare_results
from src.validation.schema_validation import SchemaValidator


class InvoiceExtractionPipeline:
    router: Router
    probe_service: ProbeService
    schema_validator: SchemaValidator
    field_policy_validator: FieldPolicyValidator
    business_validator: BusinessValidator
    recovery_provider: RecoveryProvider

    def __init__(
        self,
        router: Router,
        probe_service: ProbeService,
        schema_validator: SchemaValidator,
        field_policy_validator: FieldPolicyValidator,
        business_validator: BusinessValidator,
        recovery_provider: RecoveryProvider,
    ) -> None:
        self.router = router
        self.probe_service = probe_service
        self.schema_validator = schema_validator
        self.field_policy_validator = field_policy_validator
        self.business_validator = business_validator
        self.recovery_provider = recovery_provider
        self.extractors: Final[dict[str, BaseExtractor]] = {
            "generic.carrier_invoice": GenericCarrierInvoiceExtractor(),
            "generic.ocean_invoice": GenericOceanInvoiceExtractor(),
            "generic.customs_entry": GenericCustomsEntryExtractor(),
            "generic.supplier_workbook": GenericSupplierWorkbookExtractor(),
            "dedicated.fedex_carrier_invoice": FedExCarrierInvoiceExtractor(),
        }

    def run(self, context: ExecutionContext) -> tuple[ExtractionResult, Path]:
        context.logger.log(context.artifact_id, events.PIPELINE_START, input_path=str(context.input_path))
        context.logger.log(
            context.artifact_id,
            events.FALLBACK_PROVIDER_CONFIGURED,
            provider=context.settings.app.fallback_provider.provider,
            stubbed=context.settings.app.fallback_provider.provider == "stub",
        )
        stored_input_path = context.artifact_store.store_input(context.artifact_id, context.input_path)
        context.logger.log(context.artifact_id, events.INPUT_STORED, stored_input_path=str(stored_input_path))

        probe = self.probe_service.probe(context.input_path)
        context.logger.log(context.artifact_id, events.PROBE_COMPLETED, probe=asdict(probe))

        routing = self.router.route_initial(context.artifact_id, context.input_path, probe)
        context.logger.log(
            context.artifact_id,
            events.FAMILY_SELECTED,
            family=routing.family,
            confidence=routing.family_confidence,
            evidence=routing.family_evidence,
        )
        context.logger.log(
            context.artifact_id,
            events.VENDOR_DETECTED,
            vendor=routing.vendor,
            confidence=routing.vendor_confidence,
            evidence=routing.vendor_evidence,
        )

        generic_extractor = self.extractors[routing.generic_extractor_key]
        context.logger.log(
            context.artifact_id,
            events.GENERIC_EXTRACTOR_SELECTED,
            extractor_key=generic_extractor.key,
            family=routing.family,
        )
        generic_result = self._validate_candidate(
            context=context,
            family=routing.family,
            vendor=(
                routing.vendor
                if routing.vendor_confidence
                >= context.settings.routing.families[routing.family].vendor_confidence_threshold
                else "unknown"
            ),
            extractor_key=generic_extractor.key,
            model=generic_extractor.extract(context.input_path, probe),
        )
        context.logger.log(
            context.artifact_id,
            events.GENERIC_VALIDATION_SUMMARY,
            missing_required_fields=generic_result.missing_required_fields,
            invalid_required_fields=generic_result.invalid_required_fields,
            contradictions=generic_result.contradictions,
        )
        self._log_contradictions(context, generic_result, stage="generic")

        best_deterministic = generic_result
        used_dedicated = False

        if self._should_attempt_reroute(context, generic_result):
            extra_text = str(to_jsonable(generic_result.data))
            vendor, confidence, evidence = self.router.redetect_vendor(routing.family, context.input_path, probe, extra_text)
            vendor_config = context.settings.routing.families[routing.family].vendors.get(vendor)
            if vendor_config is not None and confidence >= vendor_config.confidence_threshold:
                dedicated_extractor = self.extractors[vendor_config.dedicated_extractor]
                used_dedicated = True
                context.logger.log(
                    context.artifact_id,
                    events.REROUTE_TRIGGERED,
                    vendor=vendor,
                    confidence=confidence,
                    evidence=evidence,
                )
                context.logger.log(
                    context.artifact_id,
                    events.DEDICATED_EXTRACTOR_SELECTED,
                    extractor_key=dedicated_extractor.key,
                    vendor=vendor,
                )
                dedicated_result = self._validate_candidate(
                    context=context,
                    family=routing.family,
                    vendor=vendor,
                    extractor_key=dedicated_extractor.key,
                    model=dedicated_extractor.extract(context.input_path, probe),
                )
                context.logger.log(
                    context.artifact_id,
                    events.DEDICATED_VALIDATION_SUMMARY,
                    missing_required_fields=dedicated_result.missing_required_fields,
                    invalid_required_fields=dedicated_result.invalid_required_fields,
                    contradictions=dedicated_result.contradictions,
                )
                self._log_contradictions(context, dedicated_result, stage="dedicated")

                comparison = compare_results(
                    generic_result,
                    dedicated_result,
                    context.settings.field_policies[routing.family],
                )
                best_deterministic = comparison.preferred_result
                context.logger.log(
                    context.artifact_id,
                    events.QUALITY_COMPARISON,
                    preferred_extractor=best_deterministic.extractor_key,
                    reason=comparison.comparison_reason,
                    conflicts=comparison.conflicts,
                    scores=comparison.scores,
                )

        final_result = best_deterministic
        if self._requires_fallback(best_deterministic):
            context.logger.log(
                context.artifact_id,
                events.FALLBACK_INVOKED,
                extractor_key=best_deterministic.extractor_key,
                unresolved_fields=best_deterministic.unresolved_must_have_fields(),
                contradictions=best_deterministic.contradictions,
            )
            recovery = self.recovery_provider.recover(
                original_artifact_path=stored_input_path,
                best_deterministic_result=best_deterministic,
                missing_or_invalid_fields=best_deterministic.unresolved_must_have_fields(),
            )
            context.logger.log(
                context.artifact_id,
                events.FALLBACK_STUB,
                notes=recovery.notes,
                confidence=recovery.confidence,
            )
            merged_payload = merge_dicts(as_json_object(best_deterministic.data), as_json_object(recovery.data_patch))
            self._append_notes_to_payload(merged_payload, recovery.notes)
            final_result = self._validate_candidate(
                context=context,
                family=best_deterministic.family,
                vendor=best_deterministic.vendor,
                extractor_key=f"{best_deterministic.extractor_key}+fallback",
                model=merged_payload,
            )
            final_result.fallback_confidence = recovery.confidence
            context.logger.log(
                context.artifact_id,
                events.FALLBACK_VALIDATION_SUMMARY,
                missing_required_fields=final_result.missing_required_fields,
                invalid_required_fields=final_result.invalid_required_fields,
                contradictions=final_result.contradictions,
                fallback_confidence=final_result.fallback_confidence,
            )
            self._log_contradictions(context, final_result, stage="fallback")

        final_result.human_review_required = self._requires_human_review(context, final_result)
        if final_result.human_review_required:
            final_result.status = PipelineStatus.HUMAN_REVIEW_REQUIRED.value
            context.logger.log(
                context.artifact_id,
                events.HUMAN_REVIEW_REQUIRED,
                missing_required_fields=final_result.missing_required_fields,
                invalid_required_fields=final_result.invalid_required_fields,
                contradictions=final_result.contradictions,
                fallback_confidence=final_result.fallback_confidence,
            )
            review_context_path = context.artifact_store.write_review_context(
                context.artifact_id,
                self._build_review_context(context, final_result, stored_input_path),
            )
        elif final_result.fallback_confidence is not None:
            final_result.status = PipelineStatus.COMPLETED_WITH_FALLBACK.value
            review_context_path = None
        else:
            final_result.status = PipelineStatus.COMPLETED.value
            review_context_path = None

        normalized_payload = self._output_payload(final_result)
        artifact_output_path = context.artifact_store.write_output_json(context.artifact_id, normalized_payload)
        output_path = write_json(context.output_dir / f"{context.artifact_id}.json", normalized_payload)
        context.artifact_store.write_execution_metadata(
            context.artifact_id,
            {
                "artifact_id": context.artifact_id,
                "family": final_result.family,
                "vendor": final_result.vendor,
                "extractor_key": final_result.extractor_key,
                "status": final_result.status,
                "used_dedicated": used_dedicated,
                "missing_required_fields": final_result.missing_required_fields,
                "invalid_required_fields": final_result.invalid_required_fields,
                "contradictions": final_result.contradictions,
                "human_review_required": final_result.human_review_required,
                "fallback_confidence": final_result.fallback_confidence,
                "artifact_output_path": str(artifact_output_path),
                "final_output_path": str(output_path),
                "review_context_path": str(review_context_path) if review_context_path else None,
            },
        )
        context.logger.log(
            context.artifact_id,
            events.OUTPUT_WRITTEN,
            final_output_path=str(output_path),
            artifact_output_path=str(artifact_output_path),
            status=final_result.status,
        )
        return final_result, output_path

    def _validate_candidate(
        self,
        context: ExecutionContext,
        family: str,
        vendor: str,
        extractor_key: str,
        model: object,
    ) -> ExtractionResult:
        payload = as_json_object(model)
        schema_issues = self.schema_validator.inspect(family, payload)
        schema_errors = [issue.message for issue in schema_issues]
        policy_summary = self.field_policy_validator.validate(family, payload)
        policy_summary = self.field_policy_validator.apply_schema_issues(policy_summary, schema_issues)
        contradictions = self.business_validator.validate(family, payload)
        extracted_payload: ExtractionPayload
        if is_extraction_payload(model):
            extracted_payload = model
        else:
            extracted_payload = payload
        return ExtractionResult(
            artifact_id=context.artifact_id,
            family=family,
            vendor=vendor,
            extractor_key=extractor_key,
            status="validated",
            data=extracted_payload,
            field_states=policy_summary.field_states,
            missing_required_fields=policy_summary.missing_required_fields,
            invalid_required_fields=policy_summary.invalid_required_fields,
            valid_important_fields=policy_summary.valid_important_fields,
            invalid_important_fields=policy_summary.invalid_important_fields,
            validation_errors=schema_errors,
            contradictions=contradictions,
        )

    def _should_attempt_reroute(self, context: ExecutionContext, result: ExtractionResult) -> bool:
        return bool(
            context.settings.app.allow_within_family_reroute_once
            and result.unresolved_must_have_fields()
        )

    def _requires_fallback(self, result: ExtractionResult) -> bool:
        return bool(result.unresolved_must_have_fields() or result.contradictions)

    def _requires_human_review(self, context: ExecutionContext, result: ExtractionResult) -> bool:
        if result.unresolved_must_have_fields() or result.contradictions:
            return True
        if result.fallback_confidence is not None and result.fallback_confidence < context.settings.app.fallback_confidence_threshold:
            return True
        return False

    def _output_payload(self, result: ExtractionResult) -> JsonObject:
        payload = as_json_object(result.data)
        _ = payload.pop("family", None)
        _ = payload.pop("extras", None)

        if result.family == "carrier_invoice":
            payload["doc_type"] = "carrier_invoice"
            shipments = payload.get("shipments")
            if not isinstance(shipments, list):
                return payload
            for shipment in shipments:
                if not isinstance(shipment, dict):
                    continue
                charges = shipment.get("charges")
                if not isinstance(charges, list):
                    continue
                for charge in charges:
                    if not isinstance(charge, dict):
                        continue
                    if "description" in charge:
                        charge["type"] = charge.pop("description")
        elif result.family == "ocean_invoice":
            payload["doc_type"] = "freight_invoice"
        elif result.family == "customs_entry":
            payload["doc_type"] = "customs_entry"
        elif result.family == "supplier_workbook":
            payload["doc_type"] = "supplier_invoice_batch"
        return payload

    def _log_contradictions(self, context: ExecutionContext, result: ExtractionResult, stage: str) -> None:
        if not result.contradictions:
            return
        context.logger.log(
            context.artifact_id,
            events.CONTRADICTIONS_DETECTED,
            stage=stage,
            extractor_key=result.extractor_key,
            family=result.family,
            vendor=result.vendor,
            contradictions=result.contradictions,
        )

    def _append_notes_to_payload(self, payload: JsonObject, notes: list[str]) -> None:
        extras = payload.get("extras")
        if not isinstance(extras, dict):
            extras = {
                "raw_labels": [],
                "unmapped_fields": {},
                "notes": [],
            }
            payload["extras"] = extras
        extras = cast(JsonObject, extras)

        raw_notes: object = extras.get("notes")
        extras_notes: list[str]
        if isinstance(raw_notes, list):
            extras_notes = [note for note in raw_notes if isinstance(note, str)]
        else:
            extras_notes = []
        extras["notes"] = extras_notes

        for note in notes:
            if note not in extras_notes:
                extras_notes.append(note)

    def _build_review_context(
        self,
        context: ExecutionContext,
        result: ExtractionResult,
        stored_input_path: Path,
    ) -> JsonObject:
        return {
            "artifact_id": context.artifact_id,
            "input_artifact_path": str(stored_input_path),
            "family": result.family,
            "vendor": result.vendor,
            "extractor_key": result.extractor_key,
            "status": result.status,
            "missing_required_fields": result.missing_required_fields,
            "invalid_required_fields": result.invalid_required_fields,
            "validation_errors": result.validation_errors,
            "contradictions": result.contradictions,
            "fallback_confidence": result.fallback_confidence,
            "normalized_payload": self._output_payload(result),
            "review_guidance": [
                "Reviewers may edit any field.",
                "No garbage placeholders are allowed in any field.",
                "All must-have fields must be present and valid before completion.",
                "Validators must be rerun before review completion.",
            ],
        }
