from __future__ import annotations

from decimal import Decimal

from reconciliation.matcher import reconcile
from reconciliation.types import MatchStatus, PurchaseRecord, RecordSource


def _record(
    *,
    source: RecordSource,
    supplier_gstin: str = "27AAAPL1234C1Z5",
    supplier_name: str = "ACME Suppliers",
    invoice_number: str,
    invoice_date: str,
    taxable: float = 10000.0,
    cgst: float = 900.0,
    sgst: float = 900.0,
    igst: float = 0.0,
    cess: float = 0.0,
    total: float = 11800.0,
    itc_available: bool | None = None,
) -> PurchaseRecord:
    return PurchaseRecord(
        source=source,
        supplier_gstin=supplier_gstin,
        supplier_name=supplier_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        document_type="invoice",
        taxable_value=Decimal(str(taxable)),
        cgst=Decimal(str(cgst)),
        sgst=Decimal(str(sgst)),
        igst=Decimal(str(igst)),
        cess=Decimal(str(cess)),
        total=Decimal(str(total)),
        itc_available=itc_available,
    )


def test_exact_match_amounts_within_tolerance_is_matched():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15")]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15")]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.matched == 1
    assert report.summary.value_mismatch == 0
    assert report.summary.books_only == 0
    assert report.summary.gstr2b_only == 0
    assert report.pairs[0].status == MatchStatus.MATCHED


def test_invoice_number_normalization_handles_separators():
    books = [_record(source=RecordSource.BOOKS, invoice_number="inv 001", invoice_date="2025-04-15")]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15")]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.matched == 1


def test_date_drift_within_window_still_matches():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15")]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-17")]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5", date_window_days=3)

    assert report.summary.matched == 0
    assert report.summary.value_mismatch == 1
    assert report.pairs[0].differences.get("invoice_date") == ("2025-04-15", "2025-04-17")


def test_date_drift_beyond_window_is_treated_as_unmatched():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15")]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-25")]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5", date_window_days=3)

    assert report.summary.books_only == 1
    assert report.summary.gstr2b_only == 1


def test_amount_mismatch_flagged_as_value_mismatch():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15",
                     cgst=850.0, sgst=850.0, total=11700.0)]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15",
                      cgst=900.0, sgst=900.0, total=11800.0)]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.value_mismatch == 1
    pair = report.pairs[0]
    assert pair.status == MatchStatus.VALUE_MISMATCH
    assert "cgst" in pair.differences
    assert "sgst" in pair.differences
    assert "total" in pair.differences


def test_paise_level_difference_within_tolerance_still_matches():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15",
                     total=11800.50)]
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15",
                      total=11800.00)]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5",
                       amount_tolerance=Decimal("1.00"))

    assert report.summary.matched == 1


def test_books_only_invoice_supplier_hasnt_filed():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15",
                     cgst=900.0, sgst=900.0)]
    gstr2b = []

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.books_only == 1
    assert report.summary.itc_at_risk == Decimal("1800.0")
    assert report.pairs[0].status == MatchStatus.BOOKS_ONLY


def test_gstr2b_only_invoice_not_entered_yet():
    books = []
    gstr2b = [_record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15",
                      cgst=0.0, sgst=0.0, igst=1800.0)]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.gstr2b_only == 1
    assert report.summary.itc_unclaimed == Decimal("1800.0")


def test_different_suppliers_dont_cross_match():
    books = [_record(source=RecordSource.BOOKS, supplier_gstin="27AAA1", invoice_number="INV-001", invoice_date="2025-04-15")]
    gstr2b = [_record(source=RecordSource.GSTR2B, supplier_gstin="27BBB2", invoice_number="INV-001", invoice_date="2025-04-15")]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.matched == 0
    assert report.summary.books_only == 1
    assert report.summary.gstr2b_only == 1


def test_multiple_invoices_match_independently():
    books = [
        _record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15"),
        _record(source=RecordSource.BOOKS, invoice_number="INV-002", invoice_date="2025-04-16"),
        _record(source=RecordSource.BOOKS, invoice_number="INV-003", invoice_date="2025-04-17"),
    ]
    gstr2b = [
        _record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15"),
        _record(source=RecordSource.GSTR2B, invoice_number="INV-003", invoice_date="2025-04-17"),
        _record(source=RecordSource.GSTR2B, invoice_number="INV-099", invoice_date="2025-04-20"),
    ]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    assert report.summary.matched == 2
    assert report.summary.books_only == 1     # INV-002 missing from GSTR-2B
    assert report.summary.gstr2b_only == 1     # INV-099 missing from books


def test_pairs_sorted_with_most_urgent_first():
    books = [_record(source=RecordSource.BOOKS, invoice_number="INV-001", invoice_date="2025-04-15")]
    gstr2b = [
        _record(source=RecordSource.GSTR2B, invoice_number="INV-001", invoice_date="2025-04-15"),
        _record(source=RecordSource.GSTR2B, supplier_gstin="27BBB1", invoice_number="INV-099", invoice_date="2025-04-20"),
    ]

    report = reconcile(books, gstr2b, period="04-2025", own_gstin="29AAAAA0000A1Z5")

    # books_only sorts first, gstr2b_only next, matched last
    statuses = [p.status for p in report.pairs]
    assert statuses.index(MatchStatus.GSTR2B_ONLY) < statuses.index(MatchStatus.MATCHED)
