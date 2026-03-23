from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeGuard

from src.io.json_codec import JsonObject

from src.domain.enums import DocumentFamily


@dataclass
class Extras:
    raw_labels: list[str] = field(default_factory=list)
    unmapped_fields: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class BillTo:
    name: str | None = None
    address: str | None = None


@dataclass
class CarrierCharge:
    description: str | None = None
    amount_usd: float | None = None


@dataclass
class CarrierShipment:
    tracking_number: str | None = None
    ship_date: str | None = None
    service_type: str | None = None
    subtotal_usd: float | None = None
    charges: list[CarrierCharge] = field(default_factory=list)
    dimensions_cm: list[float] = field(default_factory=list)
    reference: str | None = None
    actual_weight_kg: float | None = None
    billed_weight_kg: float | None = None


@dataclass
class CarrierInvoice:
    family: str = DocumentFamily.CARRIER_INVOICE.value
    invoice_number: str | None = None
    invoice_date: str | None = None
    customer_number: str | None = None
    due_date: str | None = None
    total_amount_usd: float | None = None
    bill_to: BillTo = field(default_factory=BillTo)
    shipments: list[CarrierShipment] = field(default_factory=list)
    extras: Extras = field(default_factory=Extras)


@dataclass
class OceanLineItem:
    description: str | None = None
    amount: float | None = None


@dataclass
class OceanInvoice:
    family: str = DocumentFamily.OCEAN_INVOICE.value
    invoice_number: str | None = None
    invoice_date: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    forwarder_name: str | None = None
    client_name: str | None = None
    shipment_id: str | None = None
    vessel_voyage: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    etd: str | None = None
    eta: str | None = None
    container_info: list[str] = field(default_factory=list)
    line_items: list[OceanLineItem] = field(default_factory=list)
    extras: Extras = field(default_factory=Extras)


@dataclass
class CustomsSubcode:
    code: str | None = None


@dataclass
class CustomsLineItem:
    line_number: str | None = None
    hts_code: str | None = None
    customs_value: float | None = None
    total_tax_amount: float | None = None
    duty_rate_percent: float | None = None
    duty_amount: float | None = None
    subcodes: list[CustomsSubcode] = field(default_factory=list)


@dataclass
class CustomsEntry:
    family: str = DocumentFamily.CUSTOMS_ENTRY.value
    entry_number: str | None = None
    entry_date: str | None = None
    importer_name: str | None = None
    total_customs_value: float | None = None
    total_taxes: float | None = None
    currency: str | None = None
    broker_name: str | None = None
    bill_of_lading: str | None = None
    mpf_amount: float | None = None
    hmf_amount: float | None = None
    line_items: list[CustomsLineItem] = field(default_factory=list)
    extras: Extras = field(default_factory=Extras)


@dataclass
class WorkbookLineItem:
    description: str | None = None
    amount: float | None = None
    date: str | None = None
    quantity: float | None = None
    unit_rate: float | None = None
    reference: str | None = None


@dataclass
class WorkbookCategory:
    category: str | None = None
    subtotal: float | None = None
    line_items: list[WorkbookLineItem] = field(default_factory=list)


@dataclass
class SupplierWorkbook:
    family: str = DocumentFamily.SUPPLIER_WORKBOOK.value
    batch_number: str | None = None
    invoice_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    supplier_name: str | None = None
    client_name: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    categories: list[WorkbookCategory] = field(default_factory=list)
    extras: Extras = field(default_factory=Extras)


DocumentModel = CarrierInvoice | OceanInvoice | CustomsEntry | SupplierWorkbook
ExtractionPayload = DocumentModel | JsonObject


def is_document_model(value: object) -> TypeGuard[DocumentModel]:
    return isinstance(value, (CarrierInvoice, OceanInvoice, CustomsEntry, SupplierWorkbook))


def is_extraction_payload(value: object) -> TypeGuard[ExtractionPayload]:
    return is_document_model(value) or isinstance(value, dict)


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _as_string_list(value: object) -> list[str]:
    return [item for item in _as_list(value) if isinstance(item, str)]


def _as_float_list(value: object) -> list[float]:
    return [float(item) for item in _as_list(value) if isinstance(item, (int, float))]


def _as_dict(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def build_document_model(family: str, payload: JsonObject) -> DocumentModel:
    extras_payload = _as_dict(payload.get("extras"))
    extras = Extras(
        raw_labels=_as_string_list(extras_payload.get("raw_labels", [])),
        unmapped_fields=dict(_as_dict(extras_payload.get("unmapped_fields", {}))),
        notes=_as_string_list(extras_payload.get("notes", [])),
    )

    if family == DocumentFamily.CARRIER_INVOICE.value:
        shipments = []
        for shipment in _as_list(payload.get("shipments", [])):
            if not isinstance(shipment, dict):
                continue
            charges = [
                CarrierCharge(description=_as_string(charge.get("description")), amount_usd=_as_number(charge.get("amount_usd")))
                for charge in _as_list(shipment.get("charges", []))
                if isinstance(charge, dict)
            ]
            shipments.append(
                CarrierShipment(
                    tracking_number=_as_string(shipment.get("tracking_number")),
                    ship_date=_as_string(shipment.get("ship_date")),
                    service_type=_as_string(shipment.get("service_type")),
                    subtotal_usd=_as_number(shipment.get("subtotal_usd")),
                    charges=charges,
                    dimensions_cm=_as_float_list(shipment.get("dimensions_cm", [])),
                    reference=_as_string(shipment.get("reference")),
                    actual_weight_kg=_as_number(shipment.get("actual_weight_kg")),
                    billed_weight_kg=_as_number(shipment.get("billed_weight_kg")),
                )
            )
        bill_to_payload = _as_dict(payload.get("bill_to"))
        return CarrierInvoice(
            invoice_number=_as_string(payload.get("invoice_number")),
            invoice_date=_as_string(payload.get("invoice_date")),
            customer_number=_as_string(payload.get("customer_number")),
            due_date=_as_string(payload.get("due_date")),
            total_amount_usd=_as_number(payload.get("total_amount_usd")),
            bill_to=BillTo(name=_as_string(bill_to_payload.get("name")), address=_as_string(bill_to_payload.get("address"))),
            shipments=shipments,
            extras=extras,
        )

    if family == DocumentFamily.OCEAN_INVOICE.value:
        line_items = [
            OceanLineItem(description=_as_string(item.get("description")), amount=_as_number(item.get("amount")))
            for item in _as_list(payload.get("line_items", []))
            if isinstance(item, dict)
        ]
        return OceanInvoice(
            invoice_number=_as_string(payload.get("invoice_number")),
            invoice_date=_as_string(payload.get("invoice_date")),
            currency=_as_string(payload.get("currency")),
            total_amount=_as_number(payload.get("total_amount")),
            forwarder_name=_as_string(payload.get("forwarder_name")),
            client_name=_as_string(payload.get("client_name")),
            shipment_id=_as_string(payload.get("shipment_id")),
            vessel_voyage=_as_string(payload.get("vessel_voyage")),
            port_of_loading=_as_string(payload.get("port_of_loading")),
            port_of_discharge=_as_string(payload.get("port_of_discharge")),
            etd=_as_string(payload.get("etd")),
            eta=_as_string(payload.get("eta")),
            container_info=_as_string_list(payload.get("container_info", [])),
            line_items=line_items,
            extras=extras,
        )

    if family == DocumentFamily.CUSTOMS_ENTRY.value:
        customs_line_items: list[CustomsLineItem] = []
        for item in _as_list(payload.get("line_items", [])):
            if not isinstance(item, dict):
                continue
            subcodes = [
                CustomsSubcode(code=_as_string(subcode.get("code")))
                for subcode in _as_list(item.get("subcodes", []))
                if isinstance(subcode, dict)
            ]
            customs_line_items.append(
                CustomsLineItem(
                    line_number=_as_string(item.get("line_number")),
                    hts_code=_as_string(item.get("hts_code")),
                    customs_value=_as_number(item.get("customs_value")),
                    total_tax_amount=_as_number(item.get("total_tax_amount")),
                    duty_rate_percent=_as_number(item.get("duty_rate_percent")),
                    duty_amount=_as_number(item.get("duty_amount")),
                    subcodes=subcodes,
                )
            )
        return CustomsEntry(
            entry_number=_as_string(payload.get("entry_number")),
            entry_date=_as_string(payload.get("entry_date")),
            importer_name=_as_string(payload.get("importer_name")),
            total_customs_value=_as_number(payload.get("total_customs_value")),
            total_taxes=_as_number(payload.get("total_taxes")),
            currency=_as_string(payload.get("currency")),
            broker_name=_as_string(payload.get("broker_name")),
            bill_of_lading=_as_string(payload.get("bill_of_lading")),
            mpf_amount=_as_number(payload.get("mpf_amount")),
            hmf_amount=_as_number(payload.get("hmf_amount")),
            line_items=customs_line_items,
            extras=extras,
        )

    categories: list[WorkbookCategory] = []
    for category in _as_list(payload.get("categories", [])):
        if not isinstance(category, dict):
            continue
        workbook_line_items = [
            WorkbookLineItem(
                description=_as_string(item.get("description")),
                amount=_as_number(item.get("amount")),
                date=_as_string(item.get("date")),
                quantity=_as_number(item.get("quantity")),
                unit_rate=_as_number(item.get("unit_rate")),
                reference=_as_string(item.get("reference")),
            )
            for item in _as_list(category.get("line_items", []))
            if isinstance(item, dict)
        ]
        categories.append(
            WorkbookCategory(
                category=_as_string(category.get("category")),
                subtotal=_as_number(category.get("subtotal")),
                line_items=workbook_line_items,
            )
        )
    return SupplierWorkbook(
        batch_number=_as_string(payload.get("batch_number")),
        invoice_date=_as_string(payload.get("invoice_date")),
        period_start=_as_string(payload.get("period_start")),
        period_end=_as_string(payload.get("period_end")),
        supplier_name=_as_string(payload.get("supplier_name")),
        client_name=_as_string(payload.get("client_name")),
        total_amount=_as_number(payload.get("total_amount")),
        currency=_as_string(payload.get("currency")),
        categories=categories,
        extras=extras,
    )
