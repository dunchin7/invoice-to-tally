from __future__ import annotations

import json

from llm.extractor import extract_structured_invoice
from llm.providers.base import LLMProvider


class _Provider(LLMProvider):
    def __init__(self, extract_payload: str, repaired_payload: str | None = None):
        self._extract_payload = extract_payload
        self._repaired_payload = repaired_payload

    @property
    def name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "fake"

    def extract_structured_invoice(self, raw_text: str) -> str:
        return self._extract_payload

    def repair_json(self, raw_text: str, broken_json: str, parse_error: str) -> str:
        if self._repaired_payload is None:
            raise RuntimeError("repair not configured")
        return self._repaired_payload


def _valid_invoice(*, total: float = 118.0) -> dict:
    return {
        "schema_version": "2.0",
        "invoice_number": "INV-1",
        "invoice_type": "tax_invoice",
        "invoice_date": "2024-01-01",
        "due_date": None,
        "po_number": None,
        "place_of_supply": None,
        "reverse_charge": None,
        "transport": None,
        "seller": {
            "name": "Seller Pvt Ltd",
            "gstin": None,
            "pan": None,
            "address": {
                "line1": None,
                "line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
            },
        },
        "buyer": {
            "name": "Buyer Pvt Ltd",
            "gstin": None,
            "pan": None,
            "address": {
                "line1": None,
                "line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
            },
        },
        "currency": "INR",
        "line_items": [
            {
                "description": "Service",
                "hsn_sac": None,
                "quantity": 1,
                "unit": None,
                "uom": None,
                "unit_price": 100.0,
                "discount_rate": None,
                "discount_amount": None,
                "taxable_value": None,
                "cgst_rate": None,
                "sgst_rate": None,
                "igst_rate": None,
                "cess_rate": None,
                "cgst_amount": None,
                "sgst_amount": None,
                "igst_amount": None,
                "cess_amount": None,
                "tax_amount": None,
                "total_price": total,
            }
        ],
        "subtotal": 100.0,
        "tax": 18.0,
        "total": total,
    }


def test_accounting_consistency_impacts_confidence():
    consistent_provider = _Provider(json.dumps(_valid_invoice(total=118.0)))
    inconsistent_provider = _Provider(json.dumps(_valid_invoice(total=119.0)))

    consistent = extract_structured_invoice("raw", provider=consistent_provider)
    inconsistent = extract_structured_invoice("raw", provider=inconsistent_provider)

    assert consistent["status"] == "success"
    assert inconsistent["status"] == "success"

    assert consistent["confidence"]["accounting_consistency_score"] == 1.0
    assert inconsistent["confidence"]["accounting_consistency_score"] == 0.0
    assert consistent["confidence"]["overall"] > inconsistent["confidence"]["overall"]


def test_repair_metadata_is_exposed():
    repaired_payload = json.dumps(_valid_invoice())
    provider = _Provider("{bad-json", repaired_payload)

    result = extract_structured_invoice("raw", provider=provider)

    assert result["status"] == "success"
    assert result["confidence"]["repair_attempted"] is True
    assert result["confidence"]["repair_succeeded"] is True


def test_legacy_confidence_overall_is_still_present():
    provider = _Provider(json.dumps(_valid_invoice()))

    result = extract_structured_invoice("raw", provider=provider)

    assert result["status"] == "success"
    assert "overall" in result["confidence"]
    assert isinstance(result["confidence"]["overall"], float)
