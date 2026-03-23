from __future__ import annotations

import re
from pathlib import Path

from src.domain.models import BillTo, CarrierCharge, CarrierInvoice, CarrierShipment
from src.extractors.base import BaseExtractor
from src.parsers.text_utils import all_lines, find_date_by_labels, find_label_value, find_money_by_labels, parse_float
from src.routing.probe import ProbeResult


class GenericCarrierInvoiceExtractor(BaseExtractor):
    key = "generic.carrier_invoice"
    family = "carrier_invoice"

    def extract(self, input_path: Path, probe: ProbeResult) -> CarrierInvoice:
        text = probe.full_text or probe.first_page_text
        invoice = CarrierInvoice(
            invoice_number=find_label_value(text, ["Invoice Number", "Invoice No", "Invoice #"]),
            invoice_date=find_date_by_labels(text, ["Invoice Date", "Date"]),
            customer_number=find_label_value(text, ["Customer Number", "Account Number"]),
            due_date=find_date_by_labels(text, ["Due Date", "Payment Due"]),
            total_amount_usd=find_money_by_labels(text, ["Total Amount Due USD", "Total Amount", "Net Amount Due"]),
            bill_to=BillTo(
                name=find_label_value(text, ["Bill To", "Customer Name"]),
                address=find_label_value(text, ["Bill To Address", "Customer Address"]),
            ),
            extras=self.build_extras("Generic carrier invoice extractor executed."),
        )

        invoice.shipments = self._parse_shipments(text, invoice.total_amount_usd)
        return invoice

    def _parse_shipments(self, text: str, total_amount: float | None) -> list[CarrierShipment]:
        lines = all_lines(text)
        tracking_indexes = [index for index, line in enumerate(lines) if re.match(r"tracking (id|number)", line, re.IGNORECASE)]

        if not tracking_indexes:
            return []

        shipments: list[CarrierShipment] = []
        for position, start_index in enumerate(tracking_indexes):
            end_index = tracking_indexes[position + 1] if position + 1 < len(tracking_indexes) else len(lines)
            block_lines = lines[start_index:end_index]
            block = "\n".join(block_lines)
            shipment = CarrierShipment(
                tracking_number=find_label_value(block, ["Tracking ID", "Tracking Number"]),
                ship_date=find_date_by_labels(block, ["Ship Date", "Shipment Date"]),
                service_type=find_label_value(block, ["Service Type", "Service"]),
                subtotal_usd=find_money_by_labels(block, ["Net Charge", "Shipment Total", "Subtotal"]),
                reference=find_label_value(block, ["Reference", "Reference Number"]),
                actual_weight_kg=parse_float(find_label_value(block, ["Actual Weight KG", "Actual Weight"])),
                billed_weight_kg=parse_float(find_label_value(block, ["Billed Weight KG", "Billed Weight"])),
            )

            charge_patterns = [
                r"(?P<label>Transportation Charge)\s*[:#-]?\s*(?P<amount>-?\d+(?:\.\d+)?)",
                r"(?P<label>Fuel Surcharge)\s*[:#-]?\s*(?P<amount>-?\d+(?:\.\d+)?)",
                r"(?P<label>Delivery Surcharge)\s*[:#-]?\s*(?P<amount>-?\d+(?:\.\d+)?)",
                r"(?P<label>Other Charge)\s*[:#-]?\s*(?P<amount>-?\d+(?:\.\d+)?)",
            ]
            for pattern in charge_patterns:
                for match in re.finditer(pattern, block, re.IGNORECASE):
                    shipment.charges.append(
                        CarrierCharge(description=match.group("label"), amount_usd=parse_float(match.group("amount")))
                    )

            if shipment.subtotal_usd is None and len(tracking_indexes) == 1:
                shipment.subtotal_usd = total_amount
            shipments.append(shipment)

        return shipments
