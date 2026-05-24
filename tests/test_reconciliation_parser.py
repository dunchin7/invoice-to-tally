from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from reconciliation.parser import GSTR2BParseError, parse_gstr2b
from reconciliation.types import RecordSource


def _write_gstr2b(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "gstr2b.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parses_b2b_invoice_with_current_field_names(tmp_path):
    payload = {
        "data": {
            "rtnprd": "042025",
            "gstin": "29AAAAA0000A1Z5",
            "docdata": {
                "b2b": [
                    {
                        "ctin": "27AAAPL1234C1Z5",
                        "trdnm": "ACME Suppliers Pvt Ltd",
                        "inv": [
                            {
                                "inum": "INV-9001",
                                "dt": "15-04-2025",
                                "val": 11800,
                                "pos": "27",
                                "itcavl": "Y",
                                "itms": [
                                    {"num": 1, "itm_det": {"txval": 10000, "rt": 18, "iamt": 0, "camt": 900, "samt": 900, "csamt": 0}}
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    }
    path = _write_gstr2b(tmp_path, payload)
    records = parse_gstr2b(path)

    assert len(records) == 1
    r = records[0]
    assert r.source == RecordSource.GSTR2B
    assert r.supplier_gstin == "27AAAPL1234C1Z5"
    assert r.supplier_name == "ACME Suppliers Pvt Ltd"
    assert r.invoice_number == "INV-9001"
    assert r.invoice_date == "2025-04-15"
    assert r.taxable_value == Decimal("10000")
    assert r.cgst == Decimal("900")
    assert r.sgst == Decimal("900")
    assert r.igst == Decimal("0")
    assert r.total == Decimal("11800")
    assert r.itc_available is True
    assert r.document_type == "invoice"


def test_parses_b2b_with_legacy_idt_field(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "b2b": [
                    {
                        "ctin": "27AAAPL1234C1Z5",
                        "inv": [
                            {
                                "inum": "OLD-001",
                                "idt": "01-04-2025",  # legacy field name
                                "val": 1180,
                                "itms": [{"num": 1, "itm_det": {"txval": 1000, "iamt": 180, "camt": 0, "samt": 0, "csamt": 0}}],
                            }
                        ],
                    }
                ]
            }
        }
    }
    path = _write_gstr2b(tmp_path, payload)
    records = parse_gstr2b(path)

    assert len(records) == 1
    assert records[0].invoice_date == "2025-04-01"
    assert records[0].igst == Decimal("180")


def test_parses_credit_note_with_current_field_names(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "cdnr": [
                    {
                        "ctin": "27AAAPL1234C1Z5",
                        "trdnm": "ACME",
                        "nt": [
                            {
                                "ntty": "C",
                                "ntnum": "CN-001",
                                "dt": "20-04-2025",
                                "val": 1180,
                                "itms": [{"num": 1, "itm_det": {"txval": 1000, "camt": 90, "samt": 90, "iamt": 0, "csamt": 0}}],
                            }
                        ],
                    }
                ]
            }
        }
    }
    path = _write_gstr2b(tmp_path, payload)
    records = parse_gstr2b(path)

    assert len(records) == 1
    r = records[0]
    assert r.document_type == "credit_note"
    assert r.invoice_number == "CN-001"
    assert r.invoice_date == "2025-04-20"


def test_parses_credit_note_with_legacy_nt_num_nt_dt(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "cdnr": [
                    {
                        "ctin": "27AAAPL1234C1Z5",
                        "nt": [
                            {
                                "ntty": "D",
                                "nt_num": "DN-001",
                                "nt_dt": "25-04-2025",
                                "val": 590,
                                "itms": [{"num": 1, "itm_det": {"txval": 500, "iamt": 90, "camt": 0, "samt": 0, "csamt": 0}}],
                            }
                        ],
                    }
                ]
            }
        }
    }
    path = _write_gstr2b(tmp_path, payload)
    records = parse_gstr2b(path)

    assert records[0].document_type == "debit_note"
    assert records[0].invoice_number == "DN-001"
    assert records[0].invoice_date == "2025-04-25"


def test_handles_amendments_b2ba_as_invoices(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "b2ba": [
                    {
                        "ctin": "27AAAPL1234C1Z5",
                        "inv": [{"inum": "AMD-001", "dt": "10-04-2025", "val": 1180,
                                 "itms": [{"num": 1, "itm_det": {"txval": 1000, "iamt": 180}}]}]
                    }
                ]
            }
        }
    }
    records = parse_gstr2b(_write_gstr2b(tmp_path, payload))
    assert len(records) == 1
    assert records[0].invoice_number == "AMD-001"


def test_ignores_isd_and_imports_blocks(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "b2b": [],
                "isd": [{"ctin": "X", "inv": [{"inum": "ISD-1", "dt": "01-04-2025", "val": 100, "itms": []}]}],
                "impg": [{"boe": [{"benum": "BOE-1"}]}],
            }
        }
    }
    records = parse_gstr2b(_write_gstr2b(tmp_path, payload))
    assert records == []


def test_handles_envelope_less_payload(tmp_path):
    # Some downstream tools strip the outer "data" wrapper
    payload = {
        "docdata": {
            "b2b": [
                {"ctin": "27X", "inv": [{"inum": "I-1", "dt": "01-04-2025", "val": 100,
                                         "itms": [{"num": 1, "itm_det": {"txval": 90, "iamt": 10}}]}]}
            ]
        }
    }
    records = parse_gstr2b(_write_gstr2b(tmp_path, payload))
    assert len(records) == 1
    assert records[0].invoice_number == "I-1"


def test_raises_on_missing_file(tmp_path):
    with pytest.raises(GSTR2BParseError, match="not found"):
        parse_gstr2b(tmp_path / "does_not_exist.json")


def test_raises_on_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(GSTR2BParseError, match="not valid JSON"):
        parse_gstr2b(path)


def test_supplier_gstin_uppercased_and_stripped(tmp_path):
    payload = {
        "data": {
            "docdata": {
                "b2b": [
                    {"ctin": "  27aaapl1234c1z5  ", "inv": [{"inum": "I", "dt": "01-04-2025", "val": 100, "itms": []}]}
                ]
            }
        }
    }
    records = parse_gstr2b(_write_gstr2b(tmp_path, payload))
    assert records[0].supplier_gstin == "27AAAPL1234C1Z5"
