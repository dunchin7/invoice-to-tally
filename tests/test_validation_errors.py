from __future__ import annotations

import pytest

from validation.errors import AccountingValidationError, FieldNormalizationError, SchemaValidationError
from validation.pipeline import run_normalization_pipeline


def test_field_normalization_error_for_non_object_payload():
    with pytest.raises(FieldNormalizationError) as exc_info:
        run_normalization_pipeline(["not", "an", "object"])

    assert exc_info.value.code == "FIELD_NORMALIZATION_ERROR"
    assert exc_info.value.context["field"] == "invoice"
    assert exc_info.value.context["expected"] == "object"


def test_schema_validation_error_contains_context():
    payload = {
        "invoice_number": "INV-001",
        "invoice_date": "2024-01-01",
        "seller": "Seller",
        "buyer": "Buyer",
        "currency": "INR",
        "subtotal": 10.0,
        "tax": 1.0,
        "total": 11.0,
        "line_items": [{"description": "Item", "quantity": 1, "unit_price": 10, "total_price": 10}],
    }

    payload.pop("invoice_number")

    with pytest.raises(SchemaValidationError) as exc_info:
        run_normalization_pipeline(payload)

    assert exc_info.value.code == "SCHEMA_VALIDATION_ERROR"
    assert exc_info.value.context["field"] == "invoice"


def test_accounting_validation_error_contains_mismatch_details(monkeypatch):
    payload = {
        "invoice_number": "INV-001",
        "invoice_date": "2024-01-01",
        "seller": "Seller",
        "buyer": "Buyer",
        "currency": "INR",
        "subtotal": 10.0,
        "tax": 1.0,
        "total": 30.0,
        "line_items": [{"description": "Item", "quantity": 1, "unit_price": 10, "total_price": 10}],
    }

    monkeypatch.setattr("validation.pipeline.validate", lambda **_kwargs: None)

    with pytest.raises(AccountingValidationError) as exc_info:
        run_normalization_pipeline(payload)

    assert exc_info.value.code == "ACCOUNTING_VALIDATION_ERROR"
    assert exc_info.value.context["field"] == "totals"
    assert exc_info.value.context["actual"]
