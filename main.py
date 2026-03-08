import argparse
import json
import os

from ingestion.router import IngestionError, route_extraction
from llm.extractor import extract_invoice_fields
from validation.normalizer import validate_invoice
from tally.xml_generator import generate_tally_xml


def main():
    parser = argparse.ArgumentParser(description="Invoice OCR → LLM → Structured JSON → Tally XML")
    parser.add_argument("--input", required=True, help="Path to invoice PDF or image")
    parser.add_argument(
        "--output",
        default="outputs/invoice_structured.json",
        help="Path to save structured invoice JSON"
    )
    parser.add_argument(
        "--tally-output",
        default="outputs/tally_invoice.xml",
        help="Path to save Tally XML file"
    )

    args = parser.parse_args()

    os.makedirs("outputs", exist_ok=True)

    print("[*] Ingesting invoice and extracting text...")
    try:
        raw_text = route_extraction(args.input)
    except IngestionError as exc:
        raise SystemExit(f"[!] Ingestion failed: {exc}")

    print("[*] Sending text to Gemini for field extraction...")
    invoice_data = extract_invoice_fields(raw_text)

    print("[*] Validating extracted invoice...")
    validated = validate_invoice(invoice_data)

    # ---- SAVE JSON ----
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)

    print(f"[+] Structured invoice saved to: {args.output}")

    # ---- GENERATE TALLY XML ----
    generate_tally_xml(validated, args.tally_output)

    print(f"[+] Tally XML saved to: {args.tally_output}")


if __name__ == "__main__":
    main()
