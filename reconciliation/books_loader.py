"""Books-side loader: reads purchase invoices already processed by the pipeline."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconciliation.types import PurchaseRecord, RecordSource


def load_books_from_outputs(
    outputs_dir: str | Path,
    period_yyyy_mm: str | None = None,
    own_gstins: list[str] | tuple[str, ...] | None = None,
) -> list[PurchaseRecord]:
    """Scan an orchestration output directory for normalized purchase invoices.

    Each job directory contains a `normalized_invoice.json`. We filter to:
      - direction == "purchase" (skip sales invoices in the same store)
      - invoice_date falls within period_yyyy_mm (e.g. "2025-04") if provided
      - buyer.gstin matches one of own_gstins if provided
    """
    root = Path(outputs_dir)
    if not root.is_dir():
        return []

    own_set = {g.strip().upper() for g in (own_gstins or []) if g}
    records: list[PurchaseRecord] = []

    for normalized_path in root.rglob("normalized_invoice.json"):
        try:
            data = json.loads(normalized_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("direction") != "purchase":
            continue

        invoice_date = data.get("invoice_date") or ""
        if period_yyyy_mm and not invoice_date.startswith(period_yyyy_mm):
            continue

        buyer_gstin = ((data.get("buyer") or {}).get("gstin") or "").strip().upper()
        if own_set and buyer_gstin not in own_set:
            continue

        records.append(_normalized_to_record(data))

    return records


def load_books_from_json(
    json_path: str | Path,
    period_yyyy_mm: str | None = None,
) -> list[PurchaseRecord]:
    """Load books from a flat JSON file: either a list of normalized invoices, or
    {"invoices": [...]} envelope. Useful for ingesting data exported from Tally
    or another system without re-running our pipeline.
    """
    path = Path(json_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    invoices = payload if isinstance(payload, list) else payload.get("invoices") or []

    records: list[PurchaseRecord] = []
    for entry in invoices:
        invoice_date = entry.get("invoice_date") or ""
        if period_yyyy_mm and not invoice_date.startswith(period_yyyy_mm):
            continue
        records.append(_normalized_to_record(entry))
    return records


def _normalized_to_record(data: dict[str, Any]) -> PurchaseRecord:
    seller = data.get("seller") or {}
    seller_gstin = (seller.get("gstin") or "").strip().upper()
    line_items = data.get("line_items") or []
    cgst = _sum(line_items, "cgst_amount")
    sgst = _sum(line_items, "sgst_amount")
    igst = _sum(line_items, "igst_amount")
    cess = _sum(line_items, "cess_amount")
    taxable = _sum(line_items, "taxable_value") or _to_decimal(data.get("subtotal"))

    doc_type_map = {
        "credit_note": "credit_note",
        "debit_note": "debit_note",
    }
    document_type = doc_type_map.get(data.get("invoice_type") or "", "invoice")

    return PurchaseRecord(
        source=RecordSource.BOOKS,
        supplier_gstin=seller_gstin,
        supplier_name=seller.get("name"),
        invoice_number=(data.get("invoice_number") or "").strip(),
        invoice_date=data.get("invoice_date") or "",
        document_type=document_type,
        taxable_value=taxable,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        total=_to_decimal(data.get("total")),
        place_of_supply=data.get("place_of_supply"),
        raw=data,
    )


def _sum(items: list[dict[str, Any]], field: str) -> Decimal:
    total = Decimal("0")
    for item in items:
        total += _to_decimal(item.get(field))
    return total


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return Decimal("0")
