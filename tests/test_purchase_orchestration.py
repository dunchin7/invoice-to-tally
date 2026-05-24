from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator
from tally.client import TallyUploadStatus
from tally.master_data import TallyMasterData


def _purchase_invoice() -> dict:
    return {
        "schema_version": "2.0",
        "invoice_number": "VENDOR-INV-9001",
        "invoice_type": "tax_invoice",
        "invoice_date": "2025-04-15",
        "due_date": None,
        "po_number": None,
        "place_of_supply": "Maharashtra",
        "reverse_charge": False,
        "transport": None,
        "seller": {
            "name": "ACME Suppliers Pvt Ltd",
            "gstin": "27AAAPL1234C1Z5",
            "pan": "AAAPL1234C",
            "address": {
                "line1": "12 Industrial Estate", "line2": None,
                "city": "Mumbai", "state": "Maharashtra",
                "postal_code": "400001", "country": "India",
            },
        },
        "buyer": {
            "name": "Our Trading Co",
            "gstin": "27ABCDE5678F1Z3",
            "pan": "ABCDE5678F",
            "address": {
                "line1": "Plot 42", "line2": None,
                "city": "Pune", "state": "Maharashtra",
                "postal_code": "411001", "country": "India",
            },
        },
        "currency": "INR",
        "line_items": [
            {
                "description": "Steel sheets",
                "hsn_sac": "7208", "quantity": 100.0, "unit": "KG", "uom": None,
                "unit_price": 100.0, "discount_rate": None, "discount_amount": None,
                "taxable_value": 10000.0,
                "cgst_rate": 9.0, "cgst_amount": 900.0,
                "sgst_rate": 9.0, "sgst_amount": 900.0,
                "igst_rate": 0.0, "igst_amount": 0.0,
                "cess_rate": None, "cess_amount": None,
                "tax_amount": 1800.0, "total_price": 11800.0,
            }
        ],
        "subtotal": 10000.0, "tax": 1800.0, "total": 11800.0,
    }


class _Report:
    warnings = ()
    errors = ()
    confidence_flags = {}
    critical_failure = False


class _Normalization:
    def __init__(self, payload):
        self.normalized = payload
        self.report = _Report()


def test_orchestrator_detects_purchase_from_own_gstins_and_emits_input_gst_xml(tmp_path, monkeypatch):
    invoice = _purchase_invoice()

    monkeypatch.setattr("service.orchestrator.route_extraction_with_diagnostics",
                        lambda path, tenant_id="default": ("raw ocr", {"source": "test"}))
    monkeypatch.setattr("service.orchestrator.extract_structured_invoice",
                        lambda _raw: {"status": "success", "data": invoice, "confidence": {"overall": 0.95}})
    monkeypatch.setattr("service.orchestrator.run_normalization_pipeline",
                        lambda payload, **_kw: _Normalization(payload))
    monkeypatch.setattr("service.orchestrator.to_mutable_invoice", lambda p: dict(p))
    monkeypatch.setattr("service.orchestrator.TallyMasterDataClient",
                        lambda base_url: type("M", (), {
                            "get_master_data": lambda self, force_refresh=False: TallyMasterData(
                                parties=(), ledgers=(), stock_items=(),
                                fetched_at_epoch=0.0, source="mock_empty",
                            )
                        })())

    sample_path = tmp_path / "vendor_bill.pdf"
    sample_path.write_bytes(b"%PDF-1.4")

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path / "out"))
    result = orchestrator.process_invoice(
        input_path=str(sample_path),
        master_data_file="",
        fallback_policy={"party": "auto_create", "ledger": "auto_create", "stock_item": "auto_create"},
        reconciliation_approved=True,
        dry_run=True,
        own_gstins=("27ABCDE5678F1Z3",),
    )

    assert result["state"] == InvoiceJobState.DRY_RUN.value
    assert result["direction"] == "purchase"

    xml_path = result["artifacts"]["generated_xml"]
    root = ElementTree.parse(xml_path).getroot()
    voucher = root.find(".//VOUCHER")
    assert voucher.attrib["VCHTYPE"] == "Purchase"

    entries = {
        node.findtext("LEDGERNAME"): (node.findtext("ISDEEMEDPOSITIVE"), node.findtext("AMOUNT"))
        for node in voucher.findall("ALLLEDGERENTRIES.LIST")
    }
    # Vendor is credited (payable) — "No" means it's a credit entry
    assert entries["ACME Suppliers Pvt Ltd"] == ("No", "11800.00")
    # Purchase ledger is debited
    assert entries["Purchase"] == ("Yes", "10000.00")
    # Input GST is debited
    assert entries["Input CGST"] == ("Yes", "900.00")
    assert entries["Input SGST"] == ("Yes", "900.00")


def test_orchestrator_explicit_sales_direction_overrides_gstin_match(tmp_path, monkeypatch):
    invoice = _purchase_invoice()  # buyer GSTIN matches own_gstins → would auto-detect as purchase

    monkeypatch.setattr("service.orchestrator.route_extraction_with_diagnostics",
                        lambda path, tenant_id="default": ("raw ocr", {"source": "test"}))
    monkeypatch.setattr("service.orchestrator.extract_structured_invoice",
                        lambda _raw: {"status": "success", "data": invoice, "confidence": {"overall": 0.95}})
    monkeypatch.setattr("service.orchestrator.run_normalization_pipeline",
                        lambda payload, **_kw: _Normalization(payload))
    monkeypatch.setattr("service.orchestrator.to_mutable_invoice", lambda p: dict(p))
    monkeypatch.setattr("service.orchestrator.TallyMasterDataClient",
                        lambda base_url: type("M", (), {
                            "get_master_data": lambda self, force_refresh=False: TallyMasterData(
                                parties=(), ledgers=(), stock_items=(),
                                fetched_at_epoch=0.0, source="mock_empty",
                            )
                        })())

    sample_path = tmp_path / "force_sales.pdf"
    sample_path.write_bytes(b"%PDF-1.4")

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path / "out"))
    result = orchestrator.process_invoice(
        input_path=str(sample_path),
        master_data_file="",
        fallback_policy={"party": "auto_create", "ledger": "auto_create", "stock_item": "auto_create"},
        reconciliation_approved=True,
        dry_run=True,
        own_gstins=("27ABCDE5678F1Z3",),
        invoice_direction="sales",
    )

    # Explicit override wins over GSTIN match
    assert result["direction"] == "sales"
    root = ElementTree.parse(result["artifacts"]["generated_xml"]).getroot()
    voucher = root.find(".//VOUCHER")
    assert voucher.attrib["VCHTYPE"] == "Sales"
