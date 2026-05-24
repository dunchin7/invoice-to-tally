from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from reconciliation.books_loader import load_books_from_json, load_books_from_outputs
from reconciliation.types import RecordSource


def _purchase_invoice(invoice_number: str = "INV-1", invoice_date: str = "2025-04-15") -> dict:
    return {
        "schema_version": "2.0",
        "invoice_number": invoice_number,
        "invoice_type": "tax_invoice",
        "invoice_date": invoice_date,
        "direction": "purchase",
        "seller": {"name": "Vendor X", "gstin": "27AAAPL1234C1Z5",
                   "address": {"line1": None, "line2": None, "city": None,
                               "state": "Maharashtra", "postal_code": None, "country": "India"}},
        "buyer": {"name": "Our Co", "gstin": "29AAAAA0000A1Z5",
                  "address": {"line1": None, "line2": None, "city": None,
                              "state": "Karnataka", "postal_code": None, "country": "India"}},
        "currency": "INR",
        "line_items": [
            {"description": "Item", "quantity": 1, "unit_price": 10000,
             "taxable_value": 10000, "cgst_amount": 900, "sgst_amount": 900,
             "igst_amount": 0, "cess_amount": 0, "tax_amount": 1800, "total_price": 11800},
        ],
        "subtotal": 10000, "tax": 1800, "total": 11800,
        "place_of_supply": "Maharashtra",
    }


def _write_job_record(root: Path, invoice: dict, job_id: str = "job-1") -> None:
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "normalized_invoice.json").write_text(json.dumps(invoice), encoding="utf-8")


def test_load_from_outputs_returns_purchase_records(tmp_path):
    _write_job_record(tmp_path, _purchase_invoice("PUR-1", "2025-04-15"), job_id="job-1")

    records = load_books_from_outputs(tmp_path)
    assert len(records) == 1
    r = records[0]
    assert r.source == RecordSource.BOOKS
    assert r.supplier_gstin == "27AAAPL1234C1Z5"
    assert r.invoice_number == "PUR-1"
    assert r.total == Decimal("11800")
    assert r.cgst == Decimal("900")
    assert r.sgst == Decimal("900")


def test_load_from_outputs_skips_sales_invoices(tmp_path):
    sales = _purchase_invoice("SAL-1", "2025-04-15")
    sales["direction"] = "sales"
    _write_job_record(tmp_path, sales, job_id="job-sales")
    _write_job_record(tmp_path, _purchase_invoice("PUR-1", "2025-04-15"), job_id="job-purchase")

    records = load_books_from_outputs(tmp_path)
    assert len(records) == 1
    assert records[0].invoice_number == "PUR-1"


def test_load_from_outputs_filters_by_period(tmp_path):
    _write_job_record(tmp_path, _purchase_invoice("PUR-1", "2025-04-15"), job_id="job-apr")
    _write_job_record(tmp_path, _purchase_invoice("PUR-2", "2025-05-10"), job_id="job-may")

    records = load_books_from_outputs(tmp_path, period_yyyy_mm="2025-04")
    assert {r.invoice_number for r in records} == {"PUR-1"}


def test_load_from_outputs_filters_by_own_gstins(tmp_path):
    own = _purchase_invoice("PUR-1", "2025-04-15")
    other = _purchase_invoice("PUR-2", "2025-04-15")
    other["buyer"]["gstin"] = "07OTHER0000X1Z9"

    _write_job_record(tmp_path, own, job_id="job-own")
    _write_job_record(tmp_path, other, job_id="job-other")

    records = load_books_from_outputs(tmp_path, own_gstins=["29AAAAA0000A1Z5"])
    assert len(records) == 1
    assert records[0].invoice_number == "PUR-1"


def test_load_from_json_flat_list(tmp_path):
    payload = [_purchase_invoice("PUR-1", "2025-04-15")]
    path = tmp_path / "books.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = load_books_from_json(path)
    assert len(records) == 1
    assert records[0].invoice_number == "PUR-1"


def test_load_from_json_with_envelope(tmp_path):
    payload = {"invoices": [_purchase_invoice("PUR-1", "2025-04-15")]}
    path = tmp_path / "books.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = load_books_from_json(path)
    assert len(records) == 1


def test_load_from_outputs_empty_dir_returns_empty_list(tmp_path):
    records = load_books_from_outputs(tmp_path)
    assert records == []
