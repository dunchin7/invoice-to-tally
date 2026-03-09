from __future__ import annotations

import json

from llm.extractor import _compute_confidence, extract_structured_invoice
from llm.providers.base import LLMProvider


class _Provider(LLMProvider):
    @property
    def name(self) -> str:
        return "test"

    @property
    def model_name(self) -> str:
        return "fake"

    def extract_structured_invoice(self, _raw_text: str) -> str:
        return json.dumps(
            {
                "invoice_number": "INV-1001",
                "invoice_date": "2024-01-01",
                "subtotal": 100,
                "tax": 10,
                "total": 110,
                "currency": "INR",
                "seller": {"name": "Seller Co"},
                "buyer": {"name": "Buyer Co"},
                "line_items": [{"description": "A", "total_price": 110}],
            }
        )

    def repair_json(self, _raw_text: str, _broken_json: str, _parse_error: str) -> str:
        raise AssertionError("repair_json should not be called")


def test_compute_confidence_counts_numeric_only_accounting_values_as_present():
    payload = {
        "invoice_number": "INV-1",
        "invoice_date": "2024-01-01",
        "subtotal": 100.0,
        "tax": 18,
        "total": 118,
        "currency": "INR",
        "seller": {"name": "Acme"},
        "buyer": {"name": "Beta"},
        "line_items": [{"description": "line", "total_price": 118}],
    }

    confidence = _compute_confidence(payload)

    assert confidence["fields_present"] == confidence["fields_total"]
    assert confidence["inputs"]["subtotal"] is True
    assert confidence["inputs"]["tax"] is True
    assert confidence["inputs"]["total"] is True
    assert confidence["inputs"]["line_item_totals"] is True


def test_compute_confidence_handles_mixed_string_and_numeric_payloads():
    payload = {
        "invoice_number": "INV-2",
        "invoice_date": "2024-01-01",
        "subtotal": "250.50",
        "taxes": "45.09",
        "total": 295.59,
        "currency": "USD",
        "seller": {"name": "Seller"},
        "buyer": {"name": "Buyer"},
        "line_items": [{"description": "item", "taxable_value": "250.50", "tax_amount": 45.09}],
    }

    confidence = _compute_confidence(payload)

    assert confidence["inputs"]["subtotal"] is True
    assert confidence["inputs"]["tax"] is True
    assert confidence["inputs"]["line_item_totals"] is True


def test_compute_confidence_nested_object_presence_and_missing_empty_structures():
    payload = {
        "invoice_number": "INV-3",
        "invoice_date": "2024-01-01",
        "subtotal": 10,
        "tax": 1,
        "total": 11,
        "currency": "INR",
        "seller": {},
        "buyer": {"address": {"line1": "Street 1"}},
        "line_items": [],
    }

    confidence = _compute_confidence(payload)

    assert confidence["inputs"]["seller"] is False
    assert confidence["inputs"]["buyer"] is True
    assert confidence["inputs"]["line_items"] is False
    assert confidence["inputs"]["line_item_totals"] is False


def test_extract_structured_invoice_reports_confidence_inputs_in_diagnostics():
    result = extract_structured_invoice("raw", provider=_Provider())

    assert result["status"] == "success"
    assert result["diagnostics"]["confidence_inputs"] == result["confidence"]["inputs"]
    assert result["diagnostics"]["confidence_inputs"]["subtotal"] is True
