import argparse
import json
import os

from llm.extractor import extract_invoice_fields
from ocr.ocr_engine import extract_text
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

    print("[*] Extracting text from invoice...")
    raw_text = extract_text(args.input)

    print("[*] Sending text to Gemini for field extraction...")
    invoice_data = extract_invoice_fields(raw_text)

    print("[*] Running normalization + validation pipeline...")
    result = run_normalization_pipeline(
        invoice_data,
        allow_critical_override=args.allow_accounting_override,
    )

    normalized_payload = to_mutable_invoice(result.normalized)

    # ---- SAVE JSON ----
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(normalized_payload, f, indent=2)

    with open(args.report_output, "w", encoding="utf-8") as f:
        json.dump(
            {
                "warnings": result.report.warnings,
                "errors": result.report.errors,
                "confidence_flags": result.report.confidence_flags,
                "critical_failure": result.report.critical_failure,
            },
            f,
            indent=2,
        )

    print(f"[+] Structured invoice saved to: {args.output}")
    print(f"[+] Validation report saved to: {args.report_output}")

    # ---- GENERATE TALLY XML ----
    generate_tally_xml(normalized_payload, args.tally_output)

    print(f"[+] Tally XML saved to: {args.tally_output}")


if __name__ == "__main__":
    main()
