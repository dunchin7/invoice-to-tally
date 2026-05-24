"""GSTR-2B JSON parser.

Handles both legacy ('idt', 'nt_num', 'nt_dt') and current ('dt', 'ntnum')
field-name variants from the GSTN portal.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconciliation.types import PurchaseRecord, RecordSource


class GSTR2BParseError(ValueError):
    """Raised when the GSTR-2B JSON cannot be parsed."""


def parse_gstr2b(json_path: str | Path) -> list[PurchaseRecord]:
    """Parse a GSTR-2B JSON file from the GSTN portal into PurchaseRecord list.

    Includes B2B invoices, B2B amendments, and credit/debit notes. Skips
    ISD/imports/ecom for the first cut (different ledger semantics).
    """
    path = Path(json_path)
    if not path.exists():
        raise GSTR2BParseError(f"GSTR-2B file not found: {json_path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GSTR2BParseError(f"GSTR-2B file is not valid JSON: {exc}") from exc

    data = payload.get("data") or payload  # tolerate envelope-less payloads
    docdata = data.get("docdata") or {}

    records: list[PurchaseRecord] = []
    for supplier_block in docdata.get("b2b") or []:
        records.extend(_parse_b2b_block(supplier_block, doc_type="invoice"))
    for supplier_block in docdata.get("b2ba") or []:
        records.extend(_parse_b2b_block(supplier_block, doc_type="invoice"))
    for supplier_block in docdata.get("cdnr") or []:
        records.extend(_parse_cdnr_block(supplier_block))
    for supplier_block in docdata.get("cdnra") or []:
        records.extend(_parse_cdnr_block(supplier_block))

    return records


def _parse_b2b_block(supplier_block: dict[str, Any], doc_type: str) -> list[PurchaseRecord]:
    supplier_gstin = (supplier_block.get("ctin") or "").strip().upper()
    supplier_name = supplier_block.get("trdnm")
    out: list[PurchaseRecord] = []
    for inv in supplier_block.get("inv") or []:
        invoice_number = (inv.get("inum") or "").strip()
        date_raw = inv.get("dt") or inv.get("idt")
        invoice_date = _to_iso_date(date_raw)
        amounts = _sum_item_amounts(inv.get("itms") or [])
        total = _to_decimal(inv.get("val"))
        out.append(
            PurchaseRecord(
                source=RecordSource.GSTR2B,
                supplier_gstin=supplier_gstin,
                supplier_name=supplier_name,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                document_type=doc_type,
                taxable_value=amounts["taxable"],
                cgst=amounts["cgst"],
                sgst=amounts["sgst"],
                igst=amounts["igst"],
                cess=amounts["cess"],
                total=total,
                itc_available=_to_bool(inv.get("itcavl")),
                place_of_supply=inv.get("pos"),
                raw=inv,
            )
        )
    return out


def _parse_cdnr_block(supplier_block: dict[str, Any]) -> list[PurchaseRecord]:
    supplier_gstin = (supplier_block.get("ctin") or "").strip().upper()
    supplier_name = supplier_block.get("trdnm")
    out: list[PurchaseRecord] = []
    for note in supplier_block.get("nt") or []:
        ntty = (note.get("ntty") or "").strip().upper()
        doc_type = "credit_note" if ntty == "C" else "debit_note" if ntty == "D" else "credit_note"
        note_number = (note.get("ntnum") or note.get("nt_num") or "").strip()
        date_raw = note.get("dt") or note.get("nt_dt")
        invoice_date = _to_iso_date(date_raw)
        amounts = _sum_item_amounts(note.get("itms") or [])
        total = _to_decimal(note.get("val"))
        out.append(
            PurchaseRecord(
                source=RecordSource.GSTR2B,
                supplier_gstin=supplier_gstin,
                supplier_name=supplier_name,
                invoice_number=note_number,
                invoice_date=invoice_date,
                document_type=doc_type,
                taxable_value=amounts["taxable"],
                cgst=amounts["cgst"],
                sgst=amounts["sgst"],
                igst=amounts["igst"],
                cess=amounts["cess"],
                total=total,
                itc_available=_to_bool(note.get("itcavl")),
                place_of_supply=note.get("pos"),
                raw=note,
            )
        )
    return out


def _sum_item_amounts(items: list[dict[str, Any]]) -> dict[str, Decimal]:
    taxable = cgst = sgst = igst = cess = Decimal("0")
    for item in items:
        detail = item.get("itm_det") or item
        taxable += _to_decimal(detail.get("txval"))
        cgst += _to_decimal(detail.get("camt"))
        sgst += _to_decimal(detail.get("samt"))
        igst += _to_decimal(detail.get("iamt"))
        cess += _to_decimal(detail.get("csamt"))
    return {"taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst, "cess": cess}


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return Decimal("0")


def _to_iso_date(raw: Any) -> str:
    """Accept DD-MM-YYYY (GSTN canonical), YYYY-MM-DD, DD/MM/YYYY. Return ISO."""
    if not raw:
        return ""
    if isinstance(raw, str):
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return str(raw)


def _to_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().upper()
    if s in ("Y", "YES", "TRUE", "1"):
        return True
    if s in ("N", "NO", "FALSE", "0"):
        return False
    return None
