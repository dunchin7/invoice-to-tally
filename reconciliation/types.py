from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class MatchStatus(str, Enum):
    MATCHED = "matched"                      # exact match, all values within tolerance
    VALUE_MISMATCH = "value_mismatch"        # matched on id but amounts differ
    BOOKS_ONLY = "books_only"                # in your books, missing from GSTR-2B (supplier hasn't filed)
    GSTR2B_ONLY = "gstr2b_only"              # in GSTR-2B, missing from your books (you haven't entered it)


class RecordSource(str, Enum):
    BOOKS = "books"
    GSTR2B = "gstr2b"


@dataclass
class PurchaseRecord:
    """A single purchase invoice or credit/debit note from either books or GSTR-2B."""
    source: RecordSource
    supplier_gstin: str
    supplier_name: str | None
    invoice_number: str
    invoice_date: str                      # ISO YYYY-MM-DD
    document_type: str                      # "invoice" | "credit_note" | "debit_note"
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total: Decimal
    itc_available: bool | None = None       # only from GSTR-2B
    place_of_supply: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_invoice_number(self) -> str:
        return _normalize_invoice_number(self.invoice_number)


def _normalize_invoice_number(value: str) -> str:
    """Normalize for matching: uppercase, strip whitespace and common separators."""
    if not value:
        return ""
    cleaned = value.strip().upper()
    # Collapse internal whitespace and remove non-alphanumeric separators
    cleaned = "".join(ch for ch in cleaned if ch.isalnum())
    return cleaned


@dataclass
class MatchPair:
    """Represents one reconciliation outcome — either matched pair or unmatched record."""
    status: MatchStatus
    books: PurchaseRecord | None = None
    gstr2b: PurchaseRecord | None = None
    differences: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def key(self) -> str:
        rec = self.books or self.gstr2b
        if rec is None:
            return ""
        return f"{rec.supplier_gstin}|{rec.normalized_invoice_number}|{rec.invoice_date}"


@dataclass
class ReconciliationSummary:
    matched: int = 0
    value_mismatch: int = 0
    books_only: int = 0
    gstr2b_only: int = 0
    total_books: int = 0
    total_gstr2b: int = 0
    itc_at_risk: Decimal = Decimal("0")     # input GST in books-only records (supplier hasn't filed)
    itc_unclaimed: Decimal = Decimal("0")    # input GST in gstr2b-only records (we haven't entered)


@dataclass
class ReconciliationReport:
    period: str                              # e.g. "04-2025" or "April 2025"
    own_gstin: str
    summary: ReconciliationSummary
    pairs: list[MatchPair]

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "own_gstin": self.own_gstin,
            "summary": {
                "matched": self.summary.matched,
                "value_mismatch": self.summary.value_mismatch,
                "books_only": self.summary.books_only,
                "gstr2b_only": self.summary.gstr2b_only,
                "total_books": self.summary.total_books,
                "total_gstr2b": self.summary.total_gstr2b,
                "itc_at_risk": str(self.summary.itc_at_risk),
                "itc_unclaimed": str(self.summary.itc_unclaimed),
            },
            "pairs": [_pair_to_dict(p) for p in self.pairs],
        }


def _pair_to_dict(pair: MatchPair) -> dict[str, Any]:
    return {
        "status": pair.status.value,
        "books": _record_to_dict(pair.books),
        "gstr2b": _record_to_dict(pair.gstr2b),
        "differences": {k: [_serialize(v[0]), _serialize(v[1])] for k, v in pair.differences.items()},
    }


def _record_to_dict(record: PurchaseRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "source": record.source.value,
        "supplier_gstin": record.supplier_gstin,
        "supplier_name": record.supplier_name,
        "invoice_number": record.invoice_number,
        "invoice_date": record.invoice_date,
        "document_type": record.document_type,
        "taxable_value": str(record.taxable_value),
        "cgst": str(record.cgst),
        "sgst": str(record.sgst),
        "igst": str(record.igst),
        "cess": str(record.cess),
        "total": str(record.total),
        "itc_available": record.itc_available,
        "place_of_supply": record.place_of_supply,
    }


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
