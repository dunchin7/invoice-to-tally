"""Real end-to-end tests that exercise actual external dependencies.

These tests are SKIPPED automatically when the required environment variables
are not set, so they never fail in CI unless explicitly opted in.

To run:
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_DEPLOYMENT_NAME=... \
    pytest tests/test_real_invoice_e2e.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from xml.etree import ElementTree

import pytest

# Skip the entire module if Azure OpenAI creds are absent
pytestmark = pytest.mark.skipif(
    not (
        os.getenv("AZURE_OPENAI_API_KEY")
        and os.getenv("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    ),
    reason="Azure OpenAI credentials not set — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME to run",
)


def _sample_invoice_text() -> str:
    """Return OCR text extracted from the sample invoice fixture, or a synthetic fallback."""
    sample_path = Path("samples/sample_invoice.pdf")
    if not sample_path.exists():
        return _synthetic_invoice_text()

    try:
        import pytesseract
        from pdf2image import convert_from_path
        pages = convert_from_path(str(sample_path), first_page=1, last_page=1)
        return pytesseract.image_to_string(pages[0])
    except Exception:
        return _synthetic_invoice_text()


def _synthetic_invoice_text() -> str:
    return """\
TAX INVOICE

Invoice No: INV-2024-001
Date: 15-03-2024

SELLER:
ABC Traders Pvt Ltd
GSTIN: 27AABCT1234F1Z5
123, MG Road, Andheri East
Mumbai, Maharashtra - 400069

BUYER:
XYZ Solutions Pvt Ltd
GSTIN: 27AABCX5678G1Z3
456, Bandra Kurla Complex
Mumbai, Maharashtra - 400051

Place of Supply: Maharashtra

Items:
--------------------------------------------------
Description         HSN    Qty  Rate      Amount
Web Development     9983   10   5000.00   50000.00
CGST @ 9%                                 4500.00
SGST @ 9%                                 4500.00
--------------------------------------------------
Taxable Value:                           50000.00
CGST (9%):                                4500.00
SGST (9%):                                4500.00
Total Tax:                                9000.00
Grand Total:                             59000.00

Payment Terms: Net 30 days
"""


def test_azure_openai_extracts_invoice_fields():
    """LLM extraction returns a valid dict with required fields."""
    from llm.extractor import extract_structured_invoice
    from llm.providers.azure_openai import AzureOpenAIProvider

    provider = AzureOpenAIProvider()
    raw_text = _synthetic_invoice_text()
    result = extract_structured_invoice(raw_text, provider=provider)

    assert result["status"] == "success", f"Extraction failed: {result.get('error')}"

    data = result["data"]
    assert data.get("invoice_number"), "invoice_number must be non-empty"
    assert data.get("invoice_date"), "invoice_date must be present"
    assert data.get("seller", {}).get("name"), "seller.name must be present"
    assert data.get("buyer", {}).get("name"), "buyer.name must be present"
    assert isinstance(data.get("line_items"), list), "line_items must be a list"
    assert len(data["line_items"]) >= 1, "at least one line item required"

    confidence = result["confidence"]
    assert confidence["overall"] >= 0.5, f"Confidence too low: {confidence['overall']}"


def test_azure_openai_returns_correct_schema_version():
    """Extracted invoice always has schema_version 2.0."""
    from llm.extractor import extract_structured_invoice
    from llm.providers.azure_openai import AzureOpenAIProvider

    provider = AzureOpenAIProvider()
    result = extract_structured_invoice(_synthetic_invoice_text(), provider=provider)
    assert result["status"] == "success"
    assert result["data"].get("schema_version") == "2.0"


def test_extraction_passes_schema_validation():
    """Extracted and normalized invoice passes JSON schema validation."""
    from llm.extractor import extract_structured_invoice
    from llm.providers.azure_openai import AzureOpenAIProvider
    from validation.normalizer import validate_invoice

    provider = AzureOpenAIProvider()
    result = extract_structured_invoice(_synthetic_invoice_text(), provider=provider)
    assert result["status"] == "success"

    # validate_invoice runs normalization + schema validation
    normalized = validate_invoice(result["data"])
    assert normalized["schema_version"] == "2.0"
    assert normalized["invoice_number"]
    assert isinstance(normalized["subtotal"], float)
    assert isinstance(normalized["tax"], float)
    assert isinstance(normalized["total"], float)


def test_extraction_gst_type_is_consistent():
    """For intra-state invoice, CGST+SGST should be populated and IGST should be zero."""
    from llm.extractor import extract_structured_invoice
    from llm.providers.azure_openai import AzureOpenAIProvider
    from validation.normalizer import _apply_gst_consistency, _normalize_legacy

    provider = AzureOpenAIProvider()
    result = extract_structured_invoice(_synthetic_invoice_text(), provider=provider)
    assert result["status"] == "success"

    normalized = _normalize_legacy(result["data"])
    seller_state = (normalized.get("seller") or {}).get("address", {}).get("state") or ""
    buyer_state = (normalized.get("buyer") or {}).get("address", {}).get("state") or ""

    if seller_state and buyer_state and seller_state.lower() == buyer_state.lower():
        for item in normalized["line_items"]:
            igst = item.get("igst_amount") or 0
            assert igst == 0, f"IGST should be 0 for intra-state; got {igst}"


def test_full_pipeline_dry_run(tmp_path):
    """Full orchestrator pipeline runs end-to-end in dry-run mode without errors."""
    # This test does NOT mock anything — it uses real Azure OpenAI but skips Tally upload
    from service.orchestrator import InvoiceJobState, InvoiceOrchestrator

    sample_path = Path("samples/sample_invoice.pdf")
    if not sample_path.exists():
        pytest.skip("samples/sample_invoice.pdf not present")

    # Check OCR binaries are available
    import shutil
    if not shutil.which("tesseract"):
        pytest.skip("tesseract not in PATH")
    if not shutil.which("pdftoppm"):
        pytest.skip("pdftoppm (poppler) not in PATH")

    orchestrator = InvoiceOrchestrator(
        output_dir=str(tmp_path),
        low_confidence_threshold=0.5,
    )
    result = orchestrator.process_invoice(
        input_path=str(sample_path),
        dry_run=True,
        master_data_file="",
        fallback_policy={"party": "manual_review", "ledger": "manual_review", "stock_item": "manual_review"},
        reconciliation_approved=True,
    )

    # Should reach DRY_RUN or REVIEW_REQUIRED (never FAILED unless there's a real error)
    assert result["state"] in (
        InvoiceJobState.DRY_RUN.value,
        InvoiceJobState.REVIEW_REQUIRED.value,
    ), f"Unexpected state {result['state']}: {result.get('error')}"

    assert Path(result["artifacts"]["raw_ocr_text"]).exists()
    assert Path(result["artifacts"]["extracted_json"]).exists()

    # Validate the extracted JSON has actual content
    with open(result["artifacts"]["extracted_json"], encoding="utf-8") as f:
        extracted = json.load(f)
    assert extracted.get("status") == "success", "Extraction should succeed"
    assert extracted["data"].get("invoice_number"), "invoice_number should be extracted"


def test_tally_xml_is_well_formed(tmp_path):
    """Generated Tally XML is well-formed and contains expected elements."""
    from llm.extractor import extract_structured_invoice
    from llm.providers.azure_openai import AzureOpenAIProvider
    from tally.xml_generator import generate_tally_xml
    from validation.normalizer import validate_invoice

    provider = AzureOpenAIProvider()
    result = extract_structured_invoice(_synthetic_invoice_text(), provider=provider)
    assert result["status"] == "success"

    normalized = validate_invoice(result["data"])
    xml_path = tmp_path / "invoice.xml"
    generate_tally_xml(normalized, str(xml_path))

    assert xml_path.exists()
    tree = ElementTree.parse(str(xml_path))
    root = tree.getroot()
    assert root.tag == "ENVELOPE"

    voucher = root.find(".//VOUCHER")
    assert voucher is not None, "VOUCHER element must exist"
    assert voucher.find("DATE") is not None
    assert voucher.find("VOUCHERNUMBER") is not None

    entries = voucher.findall("ALLLEDGERENTRIES.LIST")
    assert len(entries) >= 2, "Must have at least debit + credit ledger entries"

    # Validate balance: sum of debit amounts == sum of credit amounts
    from decimal import Decimal
    debits = Decimal("0")
    credits = Decimal("0")
    for entry in entries:
        amount = Decimal(entry.find("AMOUNT").text or "0")
        is_positive = (entry.find("ISDEEMEDPOSITIVE").text or "No") == "Yes"
        if is_positive:
            debits += amount
        else:
            credits += amount
    assert debits == credits, f"Voucher unbalanced: debits={debits} credits={credits}"
