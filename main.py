import argparse
import json
import os

from ocr.ocr_engine import extract_text
from llm.extractor import extract_structured_invoice
from validation.normalizer import validate_invoice
from tally.xml_generator import generate_tally_xml
from validation.pipeline import run_normalization_pipeline, to_mutable_invoice


def main():
    parser = argparse.ArgumentParser(description="Invoice OCR → LLM → Structured JSON → Tally XML")
    parser.add_argument("--input", required=True, help="Path to invoice PDF or image")
    parser.add_argument(
        "--output",
        default="outputs/invoice_structured.json",
        help="Path to save structured invoice JSON",
    )
    parser.add_argument(
        "--tally-output",
        default="outputs/tally_invoice.xml",
        help="Path to save Tally XML file",
    )
    parser.add_argument(
        "--report-output",
        default="outputs/validation_report.json",
        help="Path to save validation report JSON",
    )
    parser.add_argument(
        "--allow-accounting-override",
        action="store_true",
        help=(
            "Allow output generation even when critical accounting mismatches are detected "
            "(subtotal/tax/total or line-item rollup mismatches)."
        ),
    )

    args = parser.parse_args()

    os.makedirs("outputs", exist_ok=True)

    print("[*] Ingesting invoice and extracting text...")
    try:
        raw_text = route_extraction(args.input)
    except IngestionError as exc:
        raise SystemExit(f"[!] Ingestion failed: {exc}")

    print("[*] Sending text to Gemini for field extraction...")
    extraction_result = extract_structured_invoice(raw_text)

    if extraction_result.get("status") != "success":
        diagnostics = extraction_result.get("diagnostics", {})
        raise RuntimeError(
            f"Invoice extraction failed: {extraction_result.get('error', {}).get('message', 'Unknown error')} | diagnostics={diagnostics}"
        )

    print("[*] Validating extracted invoice...")
    validated = validate_invoice(extraction_result["data"])
    extraction_result["data"] = validated

    # ---- SAVE JSON ----
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(extraction_result, f, indent=2)

    print(f"[+] Structured invoice saved to: {args.output}")
    print(f"[*] Extraction confidence: {extraction_result.get('confidence', {}).get('overall', 0)}")

    # ---- GENERATE TALLY XML ----
    generate_tally_xml(normalized_payload, args.tally_output)

    print(f"[+] Tally XML saved to: {args.tally_output}")


if __name__ == "__main__":
    main()
