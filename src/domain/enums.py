from __future__ import annotations

from enum import Enum


class DocumentFamily(str, Enum):
    CARRIER_INVOICE = "carrier_invoice"
    OCEAN_INVOICE = "ocean_invoice"
    CUSTOMS_ENTRY = "customs_entry"
    SUPPLIER_WORKBOOK = "supplier_workbook"


class FieldState(str, Enum):
    MISSING = "missing"
    INVALID = "invalid"
    VALID = "valid"


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_FALLBACK = "completed_with_fallback"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
