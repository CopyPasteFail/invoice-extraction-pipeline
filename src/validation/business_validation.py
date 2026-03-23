from __future__ import annotations

from collections import Counter

from src.io.json_codec import JsonObject


class BusinessValidator:
    """Family-specific consistency checks beyond structural/schema validation."""

    def validate(self, family: str, payload: JsonObject) -> list[str]:
        handler = getattr(self, f"_validate_{family}", None)
        if handler is None:
            return []
        return handler(payload)

    def _validate_carrier_invoice(self, payload: JsonObject) -> list[str]:
        # Allow either shipment subtotals alone or shipment subtotals plus VAT
        # rows to reconcile against the document total.
        contradictions: list[str] = []
        shipments = payload.get("shipments", [])
        if isinstance(shipments, list):
            totals: list[float] = [
                float(value)
                for shipment in shipments
                if isinstance(shipment, dict)
                for value in [shipment.get("subtotal_usd")]
                if isinstance(value, (int, float))
            ]
            document_total = payload.get("total_amount_usd")
            if isinstance(document_total, (int, float)) and totals:
                vat_rows = payload.get("vat_summary", [])
                vat_total = 0.0
                if isinstance(vat_rows, list):
                    vat_total = sum(
                        float(row.get("vat_usd") or 0.0)
                        for row in vat_rows
                        if isinstance(row, dict) and isinstance(row.get("vat_usd"), (int, float))
                    )
                if abs((sum(totals) + vat_total) - float(document_total)) > 0.01 and abs(sum(totals) - float(document_total)) > 0.01:
                    contradictions.append("Arithmetic mismatch between shipment subtotals and total_amount_usd.")
            tracking_numbers = [shipment.get("tracking_number") for shipment in shipments if isinstance(shipment, dict)]
            duplicates = [value for value, count in Counter(tracking_numbers).items() if value and count > 1]
            if duplicates:
                contradictions.append("Duplicate tracking_number values detected in sibling shipments.")
        return contradictions

    def _validate_ocean_invoice(self, payload: JsonObject) -> list[str]:
        contradictions: list[str] = []
        etd = payload.get("etd")
        eta = payload.get("eta")
        if isinstance(etd, str) and isinstance(eta, str) and etd > eta:
            contradictions.append("ETD occurs after ETA.")
        line_items = payload.get("line_items", [])
        if not isinstance(line_items, list):
            return contradictions
        amounts: list[float] = [
            float(value)
            for item in line_items
            if isinstance(item, dict)
            for value in [item.get("amount")]
            if isinstance(value, (int, float))
        ]
        total_amount = payload.get("total_amount")
        if isinstance(total_amount, (int, float)) and amounts and abs(sum(amounts) - float(total_amount)) > 0.01:
            contradictions.append("Arithmetic mismatch between ocean line_items and total_amount.")
        return contradictions

    def _validate_customs_entry(self, payload: JsonObject) -> list[str]:
        contradictions: list[str] = []
        line_items = payload.get("line_items", [])
        if not isinstance(line_items, list):
            return contradictions
        line_numbers = [item.get("line_number") for item in line_items if isinstance(item, dict)]
        duplicates = [value for value, count in Counter(line_numbers).items() if value and count > 1]
        if duplicates:
            contradictions.append("Duplicate line_number values detected in customs line_items.")
        return contradictions

    def _validate_supplier_workbook(self, payload: JsonObject) -> list[str]:
        # Workbook totals are validated at the category rollup level rather than
        # re-summing every individual line item.
        contradictions: list[str] = []
        start = payload.get("period_start")
        end = payload.get("period_end")
        if isinstance(start, str) and isinstance(end, str) and start > end:
            contradictions.append("period_start occurs after period_end.")

        categories = payload.get("categories", [])
        if not isinstance(categories, list):
            return contradictions
        subtotals: list[float] = [
            float(value)
            for category in categories
            if isinstance(category, dict)
            for value in [category.get("subtotal")]
            if isinstance(value, (int, float))
        ]
        total_amount = payload.get("total_amount")
        if isinstance(total_amount, (int, float)) and subtotals and abs(sum(subtotals) - float(total_amount)) > 0.01:
            contradictions.append("Arithmetic mismatch between category subtotals and total_amount.")
        return contradictions
