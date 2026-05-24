from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from reconciliation.matcher import reconcile
from reconciliation.reporter import render_console, render_csv, write_report_files
from reconciliation.types import PurchaseRecord, RecordSource


def _record(source: RecordSource, invoice_number: str, invoice_date: str = "2025-04-15", total: float = 11800.0,
            cgst: float = 900.0, sgst: float = 900.0) -> PurchaseRecord:
    return PurchaseRecord(
        source=source,
        supplier_gstin="27AAAPL1234C1Z5",
        supplier_name="ACME Suppliers",
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        document_type="invoice",
        taxable_value=Decimal("10000"),
        cgst=Decimal(str(cgst)), sgst=Decimal(str(sgst)),
        igst=Decimal("0"), cess=Decimal("0"),
        total=Decimal(str(total)),
    )


def test_console_summary_lists_action_items_for_unmatched():
    books = [_record(RecordSource.BOOKS, "INV-1")]
    gstr2b = [_record(RecordSource.GSTR2B, "INV-2")]

    report = reconcile(books, gstr2b, period="2025-04", own_gstin="29AAAAA0000A1Z5")
    text = render_console(report)

    assert "Books only" in text
    assert "GSTR-2B only" in text
    assert "INV-1" in text
    assert "INV-2" in text
    assert "ITC at risk" in text


def test_console_says_safe_to_file_when_clean():
    books = [_record(RecordSource.BOOKS, "INV-1")]
    gstr2b = [_record(RecordSource.GSTR2B, "INV-1")]

    report = reconcile(books, gstr2b, period="2025-04", own_gstin="29AAAAA0000A1Z5")
    text = render_console(report)
    assert "Safe to proceed" in text


def test_csv_contains_one_row_per_pair_with_diffs(tmp_path):
    books = [_record(RecordSource.BOOKS, "INV-1", cgst=850.0, total=11700.0)]
    gstr2b = [_record(RecordSource.GSTR2B, "INV-1", cgst=900.0, total=11800.0)]

    report = reconcile(books, gstr2b, period="2025-04", own_gstin="29AAAAA0000A1Z5")
    csv_text = render_csv(report)

    rows = list(csv.reader(csv_text.splitlines()))
    assert rows[0][0] == "status"
    assert rows[1][0] == "value_mismatch"
    # The differences column lists field diffs
    diffs_col = rows[1][-1]
    assert "cgst" in diffs_col
    assert "total" in diffs_col


def test_write_report_files_emits_all_three_artifacts(tmp_path):
    books = [_record(RecordSource.BOOKS, "INV-1")]
    gstr2b = [_record(RecordSource.GSTR2B, "INV-1")]

    report = reconcile(books, gstr2b, period="2025-04", own_gstin="29AAAAA0000A1Z5")
    paths = write_report_files(report, tmp_path)

    assert Path(paths["json"]).exists()
    assert Path(paths["csv"]).exists()
    assert Path(paths["text"]).exists()

    payload = json.loads(Path(paths["json"]).read_text())
    assert payload["period"] == "2025-04"
    assert payload["summary"]["matched"] == 1
