from __future__ import annotations

import re
from pathlib import Path

from src.extractors.base import BaseExtractor
from src.parsers.text_utils import (
    all_lines,
    find_date_by_labels,
    find_label_value,
    find_money_by_labels,
    parse_currency,
    parse_float,
)
from src.routing.probe import ProbeResult


class GenericOceanInvoiceExtractor(BaseExtractor):
    key = "generic.ocean_invoice"
    family = "ocean_invoice"

    def extract(self, input_path: Path, probe: ProbeResult) -> dict[str, object]:
        text = probe.full_text or probe.first_page_text
        lines = all_lines(text)
        line_items = self._parse_line_items(text)
        total_amount = find_money_by_labels(text, ["Total Amount", "Amount Due", "Invoice Total", "TOTAL"])
        if total_amount is None and line_items:
            total_amount = round(
                sum(float(amount) for item in line_items for amount in [item.get("amount")] if isinstance(amount, (int, float))),
                2,
            )
        return {
            "invoice_number": self._clean_invoice_number(find_label_value(text, ["Invoice Number", "Invoice No", "Invoice #", "No"])),
            "invoice_date": find_date_by_labels(text, ["Invoice Date", "Date"]),
            "currency": parse_currency(find_label_value(text, ["Currency", "Invoice Currency"]) or text) or "USD",
            "total_amount": total_amount,
            "forwarder_name": self._find_forwarder_name(lines),
            "client_name": find_label_value(text, ["Client Name", "Bill To", "Customer"]),
            "shipment_id": find_label_value(text, ["Shipment ID", "Shipment Reference", "Job Ref", "Booking Ref"]),
            "vessel_voyage": find_label_value(text, ["Vessel Voyage", "Vessel/Voyage", "VSL/VOY", "Voyage"]),
            "port_of_loading": self._port_code(find_label_value(text, ["Port of Loading", "POL"])),
            "port_of_discharge": self._port_code(find_label_value(text, ["Port of Discharge", "POD"])),
            "etd": find_date_by_labels(text, ["ETD", "Departure Date"]),
            "eta": find_date_by_labels(text, ["ETA", "Arrival Date"]),
            "container_info": {
                "container_number": find_label_value(text, ["Container Number", "CNTR No."]),
                "container_type": find_label_value(text, ["Container Type", "CNTR Type"]),
            },
            "line_items": line_items,
            "extras": {
                "raw_labels": [],
                "unmapped_fields": {},
                "notes": [],
            },
        }

    def _clean_invoice_number(self, value: str | None) -> str | None:
        if value is None:
            return None
        return re.sub(r"^(?:no|invoice)\s*[:#-]?\s*", "", value, flags=re.IGNORECASE).strip() or None

    def _find_forwarder_name(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):
            if "invoice" not in line.lower():
                continue
            for candidate in reversed(lines[max(0, index - 4) : index]):
                normalized = candidate.strip()
                if not normalized:
                    continue
                if normalized.lower().startswith(("copy", "original", "confirmed", "ref#")):
                    continue
                return normalized
        return find_label_value("\n".join(lines), ["Forwarder Name", "Forwarder", "Carrier"])

    def _port_code(self, value: str | None) -> str | None:
        if value is None:
            return None
        match = re.match(r"([A-Z]{5})", value.strip())
        return match.group(1) if match else value.strip()

    def _parse_line_items(self, text: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        lines = all_lines(text)
        in_charges = False
        index = 0
        while index < len(lines):
            line = lines[index]
            lowered = line.lower()
            if lowered == "charges":
                in_charges = True
                index += 1
                continue
            if not in_charges:
                index += 1
                continue
            if lowered.startswith("subtotal") or lowered == "payment terms":
                break
            if not line.isdigit() or index + 1 >= len(lines):
                index += 1
                continue

            description = lines[index + 1].strip()
            amount = None
            quantity = None
            currency = "USD"
            for lookahead in range(index + 2, min(len(lines), index + 6)):
                candidate = lines[lookahead]
                if candidate.isdigit() and lookahead > index + 2:
                    break
                if re.fullmatch(r"[A-Z]{3}", candidate):
                    currency = candidate
                    continue
                if quantity is None and re.fullmatch(r"\d+\s*x\s+\S+|\d+", candidate, re.IGNORECASE):
                    quantity = candidate
                    continue
                parsed = parse_float(candidate)
                if parsed is not None:
                    amount = parsed
            if description and amount is not None:
                items.append(
                    {
                        "description": description,
                        "quantity": quantity,
                        "amount": amount,
                        "currency": currency,
                    }
                )
            next_index = index + 2
            while next_index < len(lines):
                candidate = lines[next_index]
                if candidate.isdigit() and next_index > index + 2:
                    break
                if candidate.lower().startswith("subtotal"):
                    break
                next_index += 1
            index = next_index
        return items
