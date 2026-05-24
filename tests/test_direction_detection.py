from __future__ import annotations

from validation.normalizer import detect_direction


def _invoice(seller_gstin: str | None, buyer_gstin: str | None) -> dict:
    return {
        "seller": {"name": "Seller Co", "gstin": seller_gstin},
        "buyer": {"name": "Buyer Co", "gstin": buyer_gstin},
    }


def test_seller_gstin_match_returns_sales():
    invoice = _invoice("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    own = ("27AAAPL1234C1Z5",)
    assert detect_direction(invoice, own) == "sales"


def test_buyer_gstin_match_returns_purchase():
    invoice = _invoice("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    own = ("29AABCS1429B1ZS",)
    assert detect_direction(invoice, own) == "purchase"


def test_no_match_returns_none():
    invoice = _invoice("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    own = ("07AABCS9999X1Z9",)
    assert detect_direction(invoice, own) is None


def test_both_match_returns_none_ambiguous():
    invoice = _invoice("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    own = ("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    assert detect_direction(invoice, own) is None


def test_empty_own_gstins_returns_none():
    invoice = _invoice("27AAAPL1234C1Z5", "29AABCS1429B1ZS")
    assert detect_direction(invoice, ()) is None


def test_case_insensitive_match():
    invoice = _invoice("27aaapl1234c1z5", "29AABCS1429B1ZS")
    own = ("27AAAPL1234C1Z5",)
    assert detect_direction(invoice, own) == "sales"


def test_whitespace_in_gstin_is_trimmed():
    invoice = _invoice("  27AAAPL1234C1Z5  ", None)
    own = ("27AAAPL1234C1Z5",)
    assert detect_direction(invoice, own) == "sales"


def test_missing_gstins_returns_none():
    invoice = _invoice(None, None)
    own = ("27AAAPL1234C1Z5",)
    assert detect_direction(invoice, own) is None
