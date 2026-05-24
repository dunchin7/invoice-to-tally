"""GSTR-2B reconciliation engine.

Parses GSTR-2B JSON from the GSTN portal and matches it against purchase
invoices already imported into the system, flagging mismatches and
missing-on-either-side records before GSTR-3B filing.

Public API:
    parse_gstr2b(json_path) -> list[PurchaseRecord]
    load_books_from_outputs(outputs_dir, period_yyyy_mm) -> list[PurchaseRecord]
    reconcile(books, gstr2b) -> ReconciliationReport
"""
from reconciliation.matcher import reconcile
from reconciliation.parser import parse_gstr2b
from reconciliation.books_loader import load_books_from_outputs, load_books_from_json
from reconciliation.types import (
    MatchPair,
    MatchStatus,
    PurchaseRecord,
    ReconciliationReport,
    ReconciliationSummary,
)

__all__ = [
    "MatchPair",
    "MatchStatus",
    "PurchaseRecord",
    "ReconciliationReport",
    "ReconciliationSummary",
    "parse_gstr2b",
    "load_books_from_outputs",
    "load_books_from_json",
    "reconcile",
]
