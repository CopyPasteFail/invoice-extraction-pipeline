from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from src.extractors.base import BaseExtractor
from src.parsers.text_utils import all_lines, parse_date, parse_float
from src.routing.probe import ProbeResult


class FedExCarrierInvoiceExtractor(BaseExtractor):
    key = "dedicated.fedex_carrier_invoice"
    family = "carrier_invoice"
    TAXABLE_CHARGE_TYPES = {
        "AHS Freight",
        "Demand Surcharge",
        "Direct Signature",
        "Out of Delivery Area",
        "Oversize",
        "Reshumon Fee",
        "Third Party Billing",
    }

    TRACKING_PATTERN = re.compile(r"^(?:trk#|tracking#|awb#?|awb )\s*#?\s*(\d{12})", re.IGNORECASE)
    MONEY_PATTERN = re.compile(r"^[+\-−–—]?\d[\d,]*(?:\.\d+)?$")
    HEADER_VALUE_STOP_PATTERN = re.compile(
        r"^(?:cust#|inv(?:\.|\s)?no|inv(?:\.|\s)?date|due[:\s]|trk#|tracking#|awb#?|pg\s+\d+)",
        re.IGNORECASE,
    )
    DETAIL_FIELD_PATTERN = re.compile(r"(pcs:|wt\(kg\):|bld\.?wt:|dim:|ref:)", re.IGNORECASE)

    def extract(self, input_path: Path, probe: ProbeResult) -> dict[str, object]:
        text = probe.full_text or probe.first_page_text
        lines = all_lines(text)
        header_lines = self._header_lines(lines)
        invoice_date = self._extract_invoice_date(header_lines)
        exchange_rate = self._extract_exchange_rate(lines)

        return {
            "invoice_number": self._extract_invoice_number(header_lines),
            "invoice_date": invoice_date,
            "customer_number": self._extract_customer_number(header_lines),
            "due_date": self._extract_due_date(header_lines),
            "total_amount_usd": self._extract_total_amount_usd(lines),
            "total_amount_ils": self._extract_total_amount_ils(lines, exchange_rate),
            "bill_to": self._extract_bill_to(header_lines),
            "vat_summary": self._extract_vat_summary(lines),
            "shipments": [self._parse_shipment(block, invoice_date, exchange_rate) for block in self._split_shipments(lines)],
            "extras": {
                "raw_labels": [],
                "unmapped_fields": {},
                "notes": [],
            },
        }

    def _header_lines(self, lines: list[str]) -> list[str]:
        for index, line in enumerate(lines):
            if self.TRACKING_PATTERN.match(line):
                return lines[:index]
        return lines

    def _extract_invoice_number(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):
            if not re.search(r"\binv(?:\.|\s)?no\b", line, re.IGNORECASE):
                continue
            match = re.search(r"(\d{9})", line)
            if match:
                return match.group(1)
            value = self._next_header_value(lines, index)
            if value:
                digits = re.sub(r"\D", "", value)
                if len(digits) >= 9:
                    return digits[:9]
        return None

    def _extract_invoice_date(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):
            match = re.search(r"inv(?:\.|\s)?date[:\s]*([0-9A-Za-z./-]+)", line, re.IGNORECASE)
            if match:
                return self._parse_fedex_date(match.group(1))
            if re.search(r"\binv(?:\.|\s)?date\b", line, re.IGNORECASE):
                value = self._next_header_value(lines, index)
                if value:
                    return self._parse_fedex_date(value)
        return None

    def _extract_due_date(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):
            match = re.search(r"\bdue[:\s]*([0-9A-Za-z./-]+)", line, re.IGNORECASE)
            if match:
                return self._parse_fedex_date(match.group(1))
            if re.match(r"^due\b", line, re.IGNORECASE):
                value = self._next_header_value(lines, index)
                if value:
                    return self._parse_fedex_date(value)
        return None

    def _extract_customer_number(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):
            match = re.search(r"cust#\s*(\d+)", line, re.IGNORECASE)
            if match:
                return match.group(1)
            if re.match(r"^cust#", line, re.IGNORECASE):
                value = self._next_header_value(lines, index)
                if value:
                    digits = re.sub(r"\D", "", value)
                    if digits:
                        return digits
        return None

    def _next_header_value(self, lines: list[str], index: int) -> str | None:
        for lookahead in range(index + 1, min(len(lines), index + 4)):
            candidate = lines[lookahead].strip()
            if not candidate or self.HEADER_VALUE_STOP_PATTERN.match(candidate):
                continue
            return candidate
        return None

    def _extract_total_amount_usd(self, lines: list[str]) -> float | None:
        for line in reversed(lines):
            match = re.search(r"totaldue:usd\s*([\d,]+\.\d+)", line.replace(" ", ""), re.IGNORECASE)
            if match:
                return parse_float(match.group(1))
        return None

    def _extract_total_amount_ils(self, lines: list[str], exchange_rate: float | None) -> float | None:
        ils_indexes = [index for index, line in enumerate(lines) if line.strip().upper() == "ILS"]
        for index in reversed(ils_indexes):
            for lookahead in range(index + 1, min(len(lines), index + 4)):
                amount = self._parse_money_token(lines[lookahead])
                if amount is not None:
                    return amount

        total_usd = self._extract_total_amount_usd(lines)
        if total_usd is not None and exchange_rate is not None:
            return round(total_usd * exchange_rate, 2)
        return None

    def _extract_exchange_rate(self, lines: list[str]) -> float | None:
        for line in reversed(lines):
            match = re.search(r"1\s*USD\s*=\s*([\d.]+)\s*ILS", line, re.IGNORECASE)
            if match:
                return parse_float(match.group(1))
        return None

    def _extract_bill_to(self, lines: list[str]) -> dict[str, object]:
        for index, line in enumerate(lines):
            if "bill to" not in line.lower():
                continue

            candidates: list[str] = []
            for lookahead in range(index + 1, len(lines)):
                candidate = lines[lookahead].strip()
                lowered = candidate.lower()
                if self.HEADER_VALUE_STOP_PATTERN.match(candidate) or self.TRACKING_PATTERN.match(candidate):
                    break
                if lowered.startswith(("payment to", "fedex", "bank leumi")):
                    continue
                if "herzliya" in lowered and "abba" in lowered:
                    continue
                candidates.append(candidate)
                if len(candidates) >= 2:
                    break

            return {
                "name": candidates[0] if candidates else None,
                "address": candidates[1] if len(candidates) > 1 else None,
            }

        return {"name": None, "address": None}

    def _extract_vat_summary(self, lines: list[str]) -> list[dict[str, object]]:
        vat_rows: list[dict[str, object]] = []
        for index, line in enumerate(lines):
            if not line.endswith("%"):
                continue
            rate = parse_float(line.rstrip("%"))
            if rate is None:
                continue
            amounts = [parse_float(lines[index + offset]) for offset in range(1, 5) if index + offset < len(lines)]
            if len(amounts) != 4 or any(amount is None for amount in amounts):
                continue
            vat_rows.append(
                {
                    "rate_percent": rate,
                    "charges_usd": amounts[0],
                    "net_usd": amounts[1],
                    "vat_usd": amounts[2],
                    "total_usd": amounts[3],
                }
            )
        return vat_rows[:2]

    def _split_shipments(self, lines: list[str]) -> list[list[str]]:
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if self.TRACKING_PATTERN.match(line):
                if current:
                    blocks.append(current)
                current = [line]
                continue
            if not current:
                continue
            if line.lower().startswith(("fedex express israel ltd", "tax invoice", "taxinvoice", "pg ", "invoice summary")):
                continue
            current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _parse_shipment(
        self,
        block: list[str],
        invoice_date: str | None,
        exchange_rate: float | None,
    ) -> dict[str, object]:
        block_text = "\n".join(block)
        tracking_match = self.TRACKING_PATTERN.match(block[0])
        tracking_number = tracking_match.group(1) if tracking_match else None
        ship_date = self._extract_shipment_date(block, invoice_date)
        service_type = self._extract_service_type(block)
        charge_start = self._find_charge_start(block)

        route_lines: list[str] = []
        detail_lines: list[str] = []
        for index, line in enumerate(block[1:], start=1):
            lowered = line.lower()
            if index >= charge_start or lowered.startswith("taxable:"):
                continue
            if re.match(r"^(orig:|dest:)", lowered) or "->" in line:
                route_lines.append(line)
                continue
            if re.search(r"^(dt:|svc:|sve:|sve:|svc|sve)\b", lowered):
                continue
            detail_lines.append(line)

        shipper, consignee = self._parse_route(route_lines)
        detail_text = self._normalize_detail_text(" ".join(detail_lines))
        charges, subtotal_usd = self._parse_amounts(block[charge_start:], exchange_rate)
        taxable_usd, non_taxable_usd = self._extract_tax_breakdown(block_text)
        taxable_usd, non_taxable_usd = self._recover_tax_breakdown(charges, subtotal_usd, taxable_usd, non_taxable_usd)

        return {
            "tracking_number": tracking_number,
            "ship_date": ship_date,
            "service_type": service_type,
            "pieces": self._parse_int(detail_text, r"pcs:\s*(\d+)"),
            "actual_weight_kg": self._parse_float(detail_text, r"wt\(kg\):\s*([\d.]+)"),
            "billed_weight_kg": self._parse_float(detail_text, r"bld\.?wt:\s*([\d.]+)"),
            "dimensions_cm": self._parse_dimension(detail_text),
            "reference": self._parse_reference(detail_text),
            "shipper": shipper,
            "consignee": consignee,
            "charges": charges,
            "taxable_usd": taxable_usd,
            "non_taxable_usd": non_taxable_usd,
            "subtotal_usd": subtotal_usd,
        }

    def _extract_shipment_date(self, block: list[str], invoice_date: str | None) -> str | None:
        for line in block[1:5]:
            match = re.search(r"\bdt:\s*([0-9A-Za-z./-]+)", line, re.IGNORECASE)
            if match:
                return self._parse_fedex_date(match.group(1), invoice_date)
        return None

    def _extract_service_type(self, block: list[str]) -> str | None:
        for line in block[1:6]:
            match = re.search(r"\bsv[a-z]?:\s*(.+)$", line, re.IGNORECASE)
            if match:
                return self._normalize_service(match.group(1))
        return None

    def _find_charge_start(self, block: list[str]) -> int:
        for index, line in enumerate(block[1:], start=1):
            if self._looks_like_amount_table_header(line) or self._normalize_charge_label(line) or self._is_subtotal_label(line):
                return index
            if self._parse_money_token(line) is None:
                continue
            lookahead = block[index + 1 : index + 4]
            if any(self._normalize_charge_label(candidate) or self._is_subtotal_label(candidate) for candidate in lookahead):
                return index
        return len(block)

    def _looks_like_amount_table_header(self, line: str) -> bool:
        lowered = line.lower()
        return lowered in {
            "charge",
            "charges",
            "chrg type",
            "description",
            "item",
            "amounts",
            "usd",
            "ils",
            "amt(usd)",
            "amt(ils)",
            "amount(usd)",
            "amount(ils)",
        }

    def _extract_tax_breakdown(self, block_text: str) -> tuple[float | None, float | None]:
        match = re.search(
            r"taxable:\s*([\d,]+\.\d+)\s+non-tax:\s*([\d,]+\.\d+)",
            block_text,
            re.IGNORECASE,
        )
        if not match:
            return None, None
        return parse_float(match.group(1)), parse_float(match.group(2))

    def _recover_tax_breakdown(
        self,
        charges: list[dict[str, object]],
        subtotal_usd: float | None,
        taxable_usd: float | None,
        non_taxable_usd: float | None,
    ) -> tuple[float | None, float | None]:
        if taxable_usd is not None or non_taxable_usd is not None:
            return taxable_usd, non_taxable_usd
        if subtotal_usd is None or not charges:
            return taxable_usd, non_taxable_usd

        total_from_charges = 0.0
        recovered_taxable = 0.0
        for charge in charges:
            amount_usd = charge.get("amount_usd")
            description = charge.get("description")
            if not isinstance(amount_usd, (int, float)) or not isinstance(description, str):
                return taxable_usd, non_taxable_usd
            total_from_charges += float(amount_usd)
            if description in self.TAXABLE_CHARGE_TYPES:
                recovered_taxable += float(amount_usd)

        if abs(round(total_from_charges, 2) - subtotal_usd) > 0.01:
            return taxable_usd, non_taxable_usd

        recovered_taxable = round(recovered_taxable, 2)
        recovered_non_taxable = round(subtotal_usd - recovered_taxable, 2)
        return recovered_taxable, recovered_non_taxable

    def _normalize_detail_text(self, detail_text: str) -> str:
        normalized = detail_text.replace("I ", " ").replace(" 1 ", " ")
        normalized = re.sub(r"(?<=[0-9A-Za-z])(?=(?:Pcs:|Wt\(kg\):|Bld\.?Wt:|Dim:|Ref:))", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _parse_route(self, route_lines: list[str]) -> tuple[dict[str, object], dict[str, object]]:
        if len(route_lines) >= 2 and route_lines[0].lower().startswith("orig:") and route_lines[1].lower().startswith("dest:"):
            return self._parse_side(route_lines[0].split(":", maxsplit=1)[1]), self._parse_side(route_lines[1].split(":", maxsplit=1)[1])

        if route_lines:
            line = route_lines[0]
            arrow = "-->" if "-->" in line else "->"
            left, right = [part.strip() for part in line.split(arrow, maxsplit=1)]
            parenthetical = re.search(r"\(([^)]+)\)", line)
            if parenthetical and "/" in parenthetical.group(1):
                shipper_name, consignee_name = [part.strip() for part in parenthetical.group(1).split("/", maxsplit=1)]
                shipper = self._parse_city_country(left)
                consignee = self._parse_city_country(right.split("(", maxsplit=1)[0].strip())
                shipper["name"] = shipper_name
                consignee["name"] = consignee_name
                return shipper, consignee
            return self._parse_side(left), self._parse_side(right)

        return self._empty_party(), self._empty_party()

    def _parse_side(self, value: str) -> dict[str, object]:
        cleaned = value.strip()
        match = re.match(r"(?P<name>.+?),\s*(?P<city>.+?)\s*\(?(?P<country>[A-Z]{2})\)?$", cleaned)
        if match:
            return {
                "name": match.group("name").strip(),
                "city": match.group("city").strip(),
                "country": match.group("country").strip(),
            }
        city_country = self._parse_city_country(cleaned)
        if city_country["city"] is not None:
            return city_country
        return {"name": cleaned or None, "city": None, "country": None}

    def _parse_city_country(self, value: str) -> dict[str, object]:
        cleaned = value.strip().strip("()")
        match = re.match(r"(?P<city>.+?)[/,]\s*(?P<country>[A-Z]{2})$", cleaned)
        if not match:
            match = re.match(r"(?P<city>.+?)\s+\(?(?P<country>[A-Z]{2})\)?$", cleaned)
        if match:
            return {
                "name": None,
                "city": match.group("city").strip().rstrip(","),
                "country": match.group("country").strip(),
            }
        return self._empty_party()

    def _empty_party(self) -> dict[str, object]:
        return {"name": None, "city": None, "country": None}

    def _parse_amounts(self, lines: list[str], exchange_rate: float | None) -> tuple[list[dict[str, object]], float | None]:
        tokens = self._charge_tokens(lines)
        used_amount_indexes: set[int] = set()
        charges: list[dict[str, object]] = []
        subtotal_usd: float | None = None

        for index, token in enumerate(tokens):
            if token["kind"] not in {"label", "subtotal"}:
                continue

            previous_label_index = max(
                (candidate for candidate in range(index - 1, -1, -1) if tokens[candidate]["kind"] in {"label", "subtotal"}),
                default=-1,
            )
            next_label_index = next(
                (candidate for candidate in range(index + 1, len(tokens)) if tokens[candidate]["kind"] in {"label", "subtotal"}),
                len(tokens),
            )
            prev_amounts = [
                candidate
                for candidate in range(previous_label_index + 1, index)
                if tokens[candidate]["kind"] == "amount" and candidate not in used_amount_indexes
            ]
            next_amounts = [
                candidate
                for candidate in range(index + 1, next_label_index)
                if tokens[candidate]["kind"] == "amount" and candidate not in used_amount_indexes
            ]

            selected = self._select_amount_pair(tokens, prev_amounts, next_amounts, exchange_rate)
            if selected is None:
                continue

            usd_index, ils_index = selected
            used_amount_indexes.update({usd_index, ils_index})

            usd_amount, ils_amount = self._normalize_amount_pair(
                label=str(token["value"]),
                usd_raw=str(tokens[usd_index]["raw"]),
                ils_raw=str(tokens[ils_index]["raw"]),
                exchange_rate=exchange_rate,
            )
            if usd_amount is None or ils_amount is None:
                continue

            if token["kind"] == "subtotal":
                subtotal_usd = usd_amount
                continue

            charges.append(
                {
                    "description": str(token["value"]),
                    "amount_usd": usd_amount,
                    "amount_ils": ils_amount,
                }
            )

        return charges, subtotal_usd

    def _charge_tokens(self, lines: list[str]) -> list[dict[str, object]]:
        tokens: list[dict[str, object]] = []
        for line in lines:
            stripped = line.strip()
            lowered = stripped.lower()
            if not stripped:
                continue
            if lowered.startswith("taxable:") or lowered.startswith(("fedex express israel ltd", "tax invoice", "taxinvoice", "pg ")):
                break
            if self._looks_like_amount_table_header(stripped):
                continue

            label = self._normalize_charge_label(stripped)
            if label:
                tokens.append({"kind": "label", "value": label, "raw": stripped})
                continue
            if self._is_subtotal_label(stripped):
                tokens.append({"kind": "subtotal", "value": "subtotal", "raw": stripped})
                continue

            amount = self._parse_money_token(stripped)
            if amount is not None:
                tokens.append({"kind": "amount", "value": amount, "raw": stripped})
                continue

            tokens.append({"kind": "other", "value": stripped, "raw": stripped})
        return tokens

    def _select_amount_pair(
        self,
        tokens: list[dict[str, object]],
        prev_amounts: list[int],
        next_amounts: list[int],
        exchange_rate: float | None,
    ) -> tuple[int, int] | None:
        candidates: list[tuple[float, tuple[int, int]]] = []
        if len(next_amounts) >= 2:
            candidates.append((self._pair_score(tokens, next_amounts[0], next_amounts[1], exchange_rate, 0.02), (next_amounts[0], next_amounts[1])))
        if prev_amounts and next_amounts:
            candidates.append((self._pair_score(tokens, prev_amounts[-1], next_amounts[0], exchange_rate, 0.0), (prev_amounts[-1], next_amounts[0])))
        if len(prev_amounts) >= 2:
            candidates.append((self._pair_score(tokens, prev_amounts[-2], prev_amounts[-1], exchange_rate, 0.05), (prev_amounts[-2], prev_amounts[-1])))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _pair_score(
        self,
        tokens: list[dict[str, object]],
        usd_index: int,
        ils_index: int,
        exchange_rate: float | None,
        order_penalty: float,
    ) -> float:
        usd_value = self._parse_money_token(str(tokens[usd_index]["raw"]))
        ils_value = self._parse_money_token(str(tokens[ils_index]["raw"]))
        if usd_value is None or ils_value is None or abs(usd_value) < 0.0001:
            return 999999.0

        score = order_penalty
        if exchange_rate is not None:
            score += abs((abs(ils_value) / abs(usd_value)) - exchange_rate)
        if "." not in str(tokens[usd_index]["raw"]):
            score += 0.15
        if "." not in str(tokens[ils_index]["raw"]):
            score += 0.15
        return score

    def _normalize_amount_pair(
        self,
        label: str,
        usd_raw: str,
        ils_raw: str,
        exchange_rate: float | None,
    ) -> tuple[float | None, float | None]:
        usd_amount = self._parse_money_token(usd_raw)
        ils_amount = self._parse_money_token(ils_raw)
        if usd_amount is None or ils_amount is None:
            return None, None

        if exchange_rate is not None:
            inferred_usd = round(abs(ils_amount) / exchange_rate, 2)
            if self._is_obviously_garbled_amount(usd_raw, usd_amount, inferred_usd):
                usd_amount = inferred_usd

            inferred_ils = round(abs(usd_amount) * exchange_rate, 2)
            if self._is_obviously_garbled_amount(ils_raw, ils_amount, inferred_ils):
                ils_amount = inferred_ils

        if self._is_negative_charge(label):
            usd_amount = -abs(usd_amount)
            ils_amount = -abs(ils_amount)

        return round(usd_amount, 2), round(ils_amount, 2)

    def _is_obviously_garbled_amount(self, raw_value: str, parsed_value: float, inferred_value: float) -> bool:
        cleaned = self._clean_money_token(raw_value)
        if "." in cleaned:
            return False
        if inferred_value <= 0:
            return False
        return abs(parsed_value) > max(100.0, inferred_value * 5)

    def _parse_money_token(self, value: str) -> float | None:
        cleaned = self._clean_money_token(value)
        if not self.MONEY_PATTERN.fullmatch(cleaned):
            return None
        return parse_float(cleaned)

    def _clean_money_token(self, value: str) -> str:
        return (
            value.strip()
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace(" ", "")
        )

    def _normalize_charge_label(self, value: str) -> str | None:
        lowered = value.lower().replace(".", "").replace("-", "").replace(" ", "").replace("/", "")
        if lowered in {"trans", "transport", "transp", "trnsp", "trnsp", "freightchrg", "freightcharge"}:
            return "Transportation"
        if lowered in {"disc", "discount", "dscnt", "adjdisc"}:
            return "Discount"
        if lowered in {"fuel", "fuelsc", "fuelsurcharge", "fsurcharge", "fsc", "fuelsur"}:
            return "Fuel Surcharge"
        if lowered in {"dirsig", "dsr", "directsig", "dsignature", "dsign", "directsignature"}:
            return "Direct Signature"
        if lowered in {"oda", "outdelarea", "outofarea", "outofdeliveryarea", "outdelarea"}:
            return "Out of Delivery Area"
        if lowered in {"demsur", "demand", "demandsc", "demsrchg", "demandsurcharge", "demsurchg"}:
            return "Demand Surcharge"
        if lowered in {"ahs", "ahsfrt", "addlhandling"}:
            return "AHS Freight"
        if lowered in {"tpb", "thirdpty", "3rdpty", "3pbilling", "thirdpartybilling"}:
            return "Third Party Billing"
        if lowered in {"resh", "reshfee", "customsfee"}:
            return "Reshumon Fee"
        if lowered in {"oversize", "oversz", "ovrsz", "os", "s0", "so", "oversz", "oversz", "oversz"}:
            return "Oversize"
        return None

    def _is_subtotal_label(self, value: str) -> bool:
        lowered = value.lower().replace(" ", "").replace(".", "")
        return lowered in {"sub", "subtotal", "sub-total", "total"}

    def _is_negative_charge(self, label: str) -> bool:
        return label in {"Discount"}

    def _normalize_service(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        if normalized in {"INTPF", "IPE", "INTLPRIFRT"}:
            return "International Priority Freight"
        if normalized in {"IEF", "INTEF", "INTLECOFRT"}:
            return "International Economy Freight"
        if "ECO" in normalized and ("FRT" in normalized or normalized in {"IEF", "INTEF", "INTEFRT"}):
            return "International Economy Freight"
        if "PRI" in normalized and ("FRT" in normalized or normalized in {"INTPF", "IPE"}):
            return "International Priority Freight"
        if normalized in {"IF", "INT1"} or "FIRST" in normalized or normalized.endswith(("1ST", "LST", "IST")):
            return "International First"
        if "ECO" in normalized or normalized in {"IE", "INTLECO"}:
            return "International Economy"
        if "PRI" in normalized or normalized in {"INTP", "INTLPRI", "INTLPRIORITY"}:
            return "International Priority"
        return value.strip()

    def _parse_reference(self, detail_text: str) -> str | None:
        match = re.search(r"ref:\s*([A-Z0-9-]+)", detail_text, re.IGNORECASE)
        return match.group(1) if match else None

    def _parse_dimension(self, detail_text: str) -> str | None:
        match = re.search(r"dim:?\s*([0-9x]+)", detail_text, re.IGNORECASE)
        return match.group(1) if match else None

    def _parse_int(self, text: str, pattern: str) -> int | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _parse_float(self, text: str, pattern: str) -> float | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return parse_float(match.group(1)) if match else None

    def _parse_fedex_date(self, value: str | None, reference_date: str | None = None) -> str | None:
        if not value:
            return None

        candidate = value.strip()
        if re.search(r"[A-Za-z]", candidate) or candidate.startswith("20"):
            return parse_date(candidate)

        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", candidate):
            day, month, year = [int(part) for part in candidate.split(".")]
            year = 2000 + year if year < 100 else year
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                return None

        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", candidate):
            return parse_date(candidate)

        first, second, year = [int(part) for part in candidate.split("/")]
        year = 2000 + year if year < 100 else year
        options: list[date] = []
        for month, day in ((first, second), (second, first)):
            try:
                options.append(date(year, month, day))
            except ValueError:
                continue
        if not options:
            return None
        if len(options) == 1:
            return options[0].isoformat()

        reference = self._date_from_iso(reference_date)
        if reference is None:
            return options[0].isoformat()

        options.sort(key=lambda item: (0 if item <= reference else 1, abs((reference - item).days)))
        return options[0].isoformat()

    def _date_from_iso(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
