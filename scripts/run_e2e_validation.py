"""Run the full pipeline on all three test invoices and report a summary.

Usage:
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=... \
    AZURE_OPENAI_DEPLOYMENT=... python scripts/run_e2e_validation.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from dotenv import load_dotenv

load_dotenv()

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator


INVOICES = [
    {
        "path": "datasets/source_docs/invoice_1_intrastate_maharashtra.pdf",
        "label": "Invoice 1: Intra-state (Maharashtra → Maharashtra)",
        "expected_gst_type": "intra",
        "expected_total": Decimal("139830.00"),
    },
    {
        "path": "datasets/source_docs/invoice_2_interstate_karnataka_tamilnadu.pdf",
        "label": "Invoice 2: Inter-state (Karnataka → Tamil Nadu)",
        "expected_gst_type": "inter",
        "expected_total": Decimal("602980.00"),
    },
    {
        "path": "datasets/source_docs/invoice_3_service_delhi_mumbai.pdf",
        "label": "Invoice 3: Service Invoice (Delhi → Mumbai, SAC codes)",
        "expected_gst_type": "inter",
        "expected_total": Decimal("649000.00"),
    },
]


def _analyze_xml(xml_path: str) -> dict:
    tree = ET.parse(xml_path)
    voucher = tree.getroot().find(".//VOUCHER")
    entries = []
    debits = credits = Decimal("0")
    has_cgst = has_sgst = has_igst = False
    for entry in voucher.findall("ALLLEDGERENTRIES.LIST"):
        name = entry.findtext("LEDGERNAME") or ""
        amt = Decimal(entry.findtext("AMOUNT") or "0")
        pos = entry.findtext("ISDEEMEDPOSITIVE") == "Yes"
        entries.append({"name": name, "amount": amt, "side": "Dr" if pos else "Cr"})
        if pos:
            debits += amt
        else:
            credits += amt
        n = name.lower()
        if "cgst" in n:
            has_cgst = True
        elif "sgst" in n:
            has_sgst = True
        elif "igst" in n:
            has_igst = True
    return {
        "voucher_type": voucher.attrib.get("VCHTYPE"),
        "voucher_number": voucher.findtext("VOUCHERNUMBER"),
        "date": voucher.findtext("DATE"),
        "party": voucher.findtext("PARTYLEDGERNAME"),
        "entries": entries,
        "debits": debits,
        "credits": credits,
        "balanced": debits == credits,
        "has_cgst_sgst": has_cgst and has_sgst,
        "has_igst": has_igst,
    }


def _run_one(invoice: dict, output_root: Path) -> dict:
    job_dir = output_root / Path(invoice["path"]).stem
    if job_dir.exists():
        shutil.rmtree(job_dir)
    orchestrator = InvoiceOrchestrator(output_dir=str(job_dir), low_confidence_threshold=0.5)
    result = orchestrator.process_invoice(
        input_path=invoice["path"],
        master_data_file="",
        fallback_policy={"party": "auto_create", "ledger": "auto_create", "stock_item": "auto_create"},
        reconciliation_approved=True,
        dry_run=True,
    )
    return result


def main() -> int:
    if not os.getenv("AZURE_OPENAI_API_KEY"):
        print("ERROR: AZURE_OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    output_root = Path("outputs/e2e_validation")
    output_root.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("INVOICE-TO-TALLY: END-TO-END VALIDATION")
    print("=" * 80)

    overall_ok = True
    for invoice in INVOICES:
        print(f"\n{invoice['label']}")
        print("-" * 80)
        result = _run_one(invoice, output_root)
        state = result.get("state")
        print(f"  Pipeline state: {state}")

        if state != InvoiceJobState.DRY_RUN.value:
            print(f"  FAIL: Did not reach DRY_RUN. error={result.get('error')}")
            overall_ok = False
            continue

        xml_path = result["artifacts"].get("generated_xml")
        if not xml_path or not Path(xml_path).exists():
            print(f"  FAIL: No XML generated")
            overall_ok = False
            continue

        xml_info = _analyze_xml(xml_path)
        norm = json.loads(Path(result["artifacts"]["normalized_json"]).read_text())
        extracted = json.loads(Path(result["artifacts"]["extracted_json"]).read_text())
        confidence = extracted.get("confidence", {}).get("overall", 0.0)

        # Compute checks
        expected = invoice["expected_total"]
        actual = xml_info["debits"]
        total_ok = abs(actual - expected) < Decimal("1.00")
        gst_type_ok = (
            (invoice["expected_gst_type"] == "intra" and xml_info["has_cgst_sgst"] and not xml_info["has_igst"])
            or (invoice["expected_gst_type"] == "inter" and xml_info["has_igst"] and not xml_info["has_cgst_sgst"])
        )

        print(f"  Voucher: {xml_info['voucher_type']} #{xml_info['voucher_number']} on {xml_info['date']}")
        print(f"  Party (Dr): {xml_info['party']}")
        print(f"  LLM confidence: {confidence:.2f}")
        print(f"  Seller: {norm['seller']['name']} ({norm['seller']['gstin']}) — {norm['seller']['address']['state']}")
        print(f"  Buyer:  {norm['buyer']['name']} ({norm['buyer']['gstin']}) — {norm['buyer']['address']['state']}")
        print(f"  Line items: {len(norm['line_items'])}")
        print(f"  Ledger entries:")
        for entry in xml_info["entries"]:
            print(f"    {entry['side']}  {entry['name']:32s}  Rs.{entry['amount']:>14,.2f}")
        print(f"  Balance check: Dr={xml_info['debits']:,.2f}  Cr={xml_info['credits']:,.2f}  Balanced={xml_info['balanced']}")
        print(f"  Total match: expected Rs.{expected:,.2f}  got Rs.{actual:,.2f}  ok={total_ok}")
        print(f"  GST type: expected {invoice['expected_gst_type']}-state  CGST/SGST={xml_info['has_cgst_sgst']}  IGST={xml_info['has_igst']}  ok={gst_type_ok}")

        passed = xml_info["balanced"] and total_ok and gst_type_ok
        print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
        if not passed:
            overall_ok = False

    print("\n" + "=" * 80)
    print(f"OVERALL: {'ALL THREE INVOICES PASSED' if overall_ok else 'FAILURES DETECTED'}")
    print("=" * 80)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
