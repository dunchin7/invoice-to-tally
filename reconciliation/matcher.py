from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable

from reconciliation.types import (
    MatchPair,
    MatchStatus,
    PurchaseRecord,
    ReconciliationReport,
    ReconciliationSummary,
)


AMOUNT_TOLERANCE = Decimal("1.00")          # ≤ ₹1 difference counts as matched
DATE_WINDOW_DAYS = 3                         # accept date drift of ±3 days


def reconcile(
    books: Iterable[PurchaseRecord],
    gstr2b: Iterable[PurchaseRecord],
    period: str,
    own_gstin: str,
    amount_tolerance: Decimal = AMOUNT_TOLERANCE,
    date_window_days: int = DATE_WINDOW_DAYS,
) -> ReconciliationReport:
    """Match books against GSTR-2B records.

    Matching strategy:
      1. Group records by supplier GSTIN — invoices from a wrong-GSTIN supplier
         can never match. (Typos in GSTIN are surfaced as unmatched on both sides;
         the human reviewer must fix the source.)
      2. Within a supplier group, try exact match on normalized invoice number
         AND date within window.
      3. For matched pairs, compute value differences. If any GST component differs
         by more than amount_tolerance → VALUE_MISMATCH, else MATCHED.
      4. Records unmatched after step 2 become BOOKS_ONLY or GSTR2B_ONLY.
    """
    books_list = list(books)
    gstr2b_list = list(gstr2b)

    books_by_supplier: dict[str, list[PurchaseRecord]] = defaultdict(list)
    gstr2b_by_supplier: dict[str, list[PurchaseRecord]] = defaultdict(list)
    for record in books_list:
        books_by_supplier[record.supplier_gstin].append(record)
    for record in gstr2b_list:
        gstr2b_by_supplier[record.supplier_gstin].append(record)

    pairs: list[MatchPair] = []
    matched_books_ids: set[int] = set()
    matched_gstr2b_ids: set[int] = set()

    all_suppliers = set(books_by_supplier.keys()) | set(gstr2b_by_supplier.keys())
    for supplier in all_suppliers:
        supplier_books = books_by_supplier.get(supplier, [])
        supplier_gstr2b = gstr2b_by_supplier.get(supplier, [])

        # Index GSTR-2B records by normalized invoice number for fast lookup
        gstr2b_by_invnum: dict[str, list[PurchaseRecord]] = defaultdict(list)
        for record in supplier_gstr2b:
            gstr2b_by_invnum[record.normalized_invoice_number].append(record)

        for books_record in supplier_books:
            candidates = gstr2b_by_invnum.get(books_record.normalized_invoice_number, [])
            best_match = _best_date_match(books_record, candidates, matched_gstr2b_ids, date_window_days)
            if best_match is None:
                continue

            matched_books_ids.add(id(books_record))
            matched_gstr2b_ids.add(id(best_match))

            differences = _compute_differences(books_record, best_match, amount_tolerance)
            status = MatchStatus.VALUE_MISMATCH if differences else MatchStatus.MATCHED
            pairs.append(MatchPair(status=status, books=books_record, gstr2b=best_match, differences=differences))

    # Anything still unmatched → one-sided
    for record in books_list:
        if id(record) not in matched_books_ids:
            pairs.append(MatchPair(status=MatchStatus.BOOKS_ONLY, books=record))
    for record in gstr2b_list:
        if id(record) not in matched_gstr2b_ids:
            pairs.append(MatchPair(status=MatchStatus.GSTR2B_ONLY, gstr2b=record))

    pairs.sort(key=_pair_sort_key)
    summary = _summarize(pairs, books_list, gstr2b_list)
    return ReconciliationReport(period=period, own_gstin=own_gstin, summary=summary, pairs=pairs)


def _best_date_match(
    books_record: PurchaseRecord,
    candidates: list[PurchaseRecord],
    already_matched: set[int],
    window_days: int,
) -> PurchaseRecord | None:
    """Pick the GSTR-2B candidate with the smallest date drift within the window."""
    books_date = _parse_iso(books_record.invoice_date)
    best: tuple[int, PurchaseRecord] | None = None
    for candidate in candidates:
        if id(candidate) in already_matched:
            continue
        candidate_date = _parse_iso(candidate.invoice_date)
        if books_date is None or candidate_date is None:
            # If either date is unparseable accept the match on invoice number alone
            drift = 0
        else:
            drift = abs((books_date - candidate_date).days)
            if drift > window_days:
                continue
        if best is None or drift < best[0]:
            best = (drift, candidate)
    return best[1] if best else None


def _compute_differences(
    books: PurchaseRecord, gstr2b: PurchaseRecord, tolerance: Decimal
) -> dict[str, tuple[Decimal, Decimal]]:
    diff: dict[str, tuple[Decimal, Decimal]] = {}
    for field in ("taxable_value", "cgst", "sgst", "igst", "cess", "total"):
        books_val = getattr(books, field)
        gstr2b_val = getattr(gstr2b, field)
        if abs(books_val - gstr2b_val) > tolerance:
            diff[field] = (books_val, gstr2b_val)
    if books.invoice_date != gstr2b.invoice_date:
        diff["invoice_date"] = (books.invoice_date, gstr2b.invoice_date)
    return diff


def _summarize(
    pairs: list[MatchPair],
    books_list: list[PurchaseRecord],
    gstr2b_list: list[PurchaseRecord],
) -> ReconciliationSummary:
    summary = ReconciliationSummary(total_books=len(books_list), total_gstr2b=len(gstr2b_list))
    for pair in pairs:
        if pair.status == MatchStatus.MATCHED:
            summary.matched += 1
        elif pair.status == MatchStatus.VALUE_MISMATCH:
            summary.value_mismatch += 1
        elif pair.status == MatchStatus.BOOKS_ONLY:
            summary.books_only += 1
            if pair.books:
                summary.itc_at_risk += pair.books.cgst + pair.books.sgst + pair.books.igst + pair.books.cess
        elif pair.status == MatchStatus.GSTR2B_ONLY:
            summary.gstr2b_only += 1
            if pair.gstr2b:
                summary.itc_unclaimed += pair.gstr2b.cgst + pair.gstr2b.sgst + pair.gstr2b.igst + pair.gstr2b.cess
    return summary


def _parse_iso(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


_STATUS_ORDER = {
    MatchStatus.BOOKS_ONLY: 0,           # most urgent — supplier defaulting
    MatchStatus.GSTR2B_ONLY: 1,          # urgent — you've missed entering
    MatchStatus.VALUE_MISMATCH: 2,       # important — fix before filing
    MatchStatus.MATCHED: 3,
}


def _pair_sort_key(pair: MatchPair) -> tuple[int, str, str]:
    record = pair.books or pair.gstr2b
    return (
        _STATUS_ORDER.get(pair.status, 99),
        record.supplier_gstin if record else "",
        record.invoice_date if record else "",
    )
