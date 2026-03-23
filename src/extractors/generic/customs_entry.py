from __future__ import annotations

import re
from pathlib import Path

from src.extractors.base import BaseExtractor
from src.io.json_codec import JsonObject
from src.parsers.text_utils import all_lines, find_date_by_labels, find_label_value, find_money_by_labels, parse_currency, parse_float
from src.routing.probe import ProbeResult


class GenericCustomsEntryExtractor(BaseExtractor):
    key = "generic.customs_entry"
    family = "customs_entry"

    LINE_ITEM_CODE = re.compile(r"\d{4}\.\d{2}\.\d{4}")
    SUBCODE_CODE = re.compile(r"\d{4}\.\d{2}\.\d{2,4}")

    def extract(self, input_path: Path, probe: ProbeResult) -> dict[str, object]:
        text = probe.full_text or probe.first_page_text
        lines = all_lines(text)
        return {
            "entry_number": find_label_value(text, ["Entry Number", "Customs Entry Number", "ENTRY NO.", "ENT. NO"]),
            "entry_date": find_date_by_labels(text, ["Entry Date", "Release Date", "ENTRY DT.", "ENT. DT."]),
            "importer_name": find_label_value(text, ["Importer Name", "Importer", "IMP. OF RECORD (Name & Addr.)"]),
            "total_customs_value": find_money_by_labels(text, ["Total Entered Value", "Total Customs Value", "Customs Value"]),
            "total_taxes": find_money_by_labels(text, ["TOTAL TAXES, DUTIES & FEES", "Total Taxes", "Duty and Tax Total"]),
            "currency": parse_currency(find_label_value(text, ["Currency"]) or text) or "USD",
            "broker_name": find_label_value(text, ["Broker Name", "Broker", "CUST. BROKER"]),
            "bill_of_lading": self._value_after_label(lines, ["B/L OR AWB NO.", "Bill of Lading"]),
            "mpf_amount": self._money_after_label(lines, ["Merch. Processing Fee (MPF)", "MPF Amount"]),
            "hmf_amount": self._money_after_label(lines, ["Harbor Maintenance Fee (HMF)", "HMF Amount"]),
            "line_items": self._parse_line_items(lines),
            "extras": {
                "raw_labels": [],
                "unmapped_fields": {},
                "notes": [],
            },
        }

    def _value_after_label(self, lines: list[str], labels: list[str]) -> str | None:
        for index, line in enumerate(lines):
            normalized = line.lower().strip()
            for label in labels:
                if normalized.startswith(label.lower()):
                    for lookahead in range(index + 1, min(len(lines), index + 4)):
                        candidate = lines[lookahead].strip()
                        if candidate:
                            return candidate
        return None

    def _money_after_label(self, lines: list[str], labels: list[str]) -> float | None:
        for index, line in enumerate(lines):
            normalized = line.lower().strip()
            for label in labels:
                if normalized.startswith(label.lower()):
                    inline = parse_float(line)
                    if inline is not None:
                        return inline
                    for lookahead in range(index + 1, min(len(lines), index + 4)):
                        parsed = parse_float(lines[lookahead])
                        if parsed is not None:
                            return parsed
        return None

    def _parse_line_items(self, lines: list[str]) -> list[JsonObject]:
        start_index = next(
            (index for index, line in enumerate(lines) if "block 27 - line item data" in line.lower()),
            None,
        )
        end_index = next(
            (index for index, line in enumerate(lines) if "block 39 - totals" in line.lower()),
            None,
        )
        if start_index is None or end_index is None or end_index <= start_index:
            return []

        items: list[JsonObject] = []
        index = start_index + 1
        while index < end_index:
            line = lines[index]
            if not line.isdigit() or index + 8 >= end_index:
                index += 1
                continue
            if not self.LINE_ITEM_CODE.fullmatch(lines[index + 1]):
                index += 1
                continue

            duty_rate_raw = lines[index + 5]
            item: JsonObject = {
                "line_number": line,
                "hts_code": lines[index + 1],
                "description": lines[index + 2],
                "customs_value": parse_float(lines[index + 4]),
                "duty_rate_percent": self._parse_duty_rate(duty_rate_raw),
                "duty_amount": parse_float(lines[index + 6]),
                "mpf_amount": parse_float(lines[index + 7]),
                "hmf_amount": parse_float(lines[index + 8]),
                "total_tax_amount": parse_float(lines[index + 9]),
                "subcodes": [],
            }
            index += 10

            subcodes: list[JsonObject] = []
            while index < end_index:
                candidate = lines[index]
                if candidate.isdigit() and index + 1 < end_index and self.LINE_ITEM_CODE.fullmatch(lines[index + 1]):
                    break
                if not self.SUBCODE_CODE.fullmatch(candidate):
                    index += 1
                    continue

                subcode: JsonObject = {
                    "code": candidate,
                    "description": lines[index + 1] if index + 1 < end_index else None,
                    "rate_percent": None,
                    "amount": None,
                }
                lookahead = index + 2
                if lookahead < end_index and self._looks_like_rate(lines[lookahead]):
                    subcode["rate_percent"] = self._parse_duty_rate(lines[lookahead])
                    lookahead += 1
                if lookahead < end_index and lines[lookahead].startswith("$"):
                    subcode["amount"] = parse_float(lines[lookahead])
                    lookahead += 1
                subcodes.append(subcode)
                index = lookahead

            item["subcodes"] = subcodes
            items.append(item)
        return items

    def _looks_like_rate(self, value: str) -> bool:
        return "%" in value or "FREE" in value.upper() or "AD VAL" in value.upper() or bool(re.fullmatch(r"0\.\d+", value))

    def _parse_duty_rate(self, value: str | None) -> float | None:
        if not value:
            return None
        if "FREE" in value.upper():
            return 0.0
        parsed = parse_float(value)
        if parsed is None:
            return None
        if "%" not in value and parsed <= 1:
            return parsed * 100
        return parsed
