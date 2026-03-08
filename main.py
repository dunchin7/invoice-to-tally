import argparse
import json
import os

from ingestion.router import IngestionError, route_extraction
from llm.extractor import extract_structured_invoice
from settings import SETTINGS
from tally.client import TallyClient, TallyClientConfig
from tally.xml_generator import build_tally_xml, generate_tally_xml
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
        "--allow-accounting-override",
        action="store_true",
        help=(
            "Allow output generation even when critical accounting mismatches are detected "
            "(subtotal/tax/total or line-item rollup mismatches)."
        ),
    )
    parser.add_argument(
        "--upload-to-tally",
        action="store_true",
        help="Upload the generated Tally XML to the configured Tally endpoint.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only prepare upload and print destination; do not send HTTP request.",
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

    print("[*] Normalizing and validating extracted invoice...")
    normalization_result = run_normalization_pipeline(
        extraction_result["data"],
        allow_critical_override=args.allow_accounting_override,
    )
    normalized_payload = to_mutable_invoice(normalization_result.normalized)

    extraction_result["data"] = normalized_payload
    extraction_result["validation_report"] = {
        "warnings": list(normalization_result.report.warnings),
        "errors": list(normalization_result.report.errors),
        "confidence_flags": dict(normalization_result.report.confidence_flags),
        "critical_failure": normalization_result.report.critical_failure,
    }

    with open(args.output, "w", encoding="utf-8") as output_json:
        json.dump(extraction_result, output_json, indent=2)

    print(f"[+] Structured invoice saved to: {args.output}")

    generate_tally_xml(
        normalized_payload,
        args.tally_output,
        company=SETTINGS.tally_company,
        voucher_type=SETTINGS.tally_voucher_type,
        voucher_action=SETTINGS.tally_voucher_action,
    )

    print(f"[+] Tally XML saved to: {args.tally_output}")

    if args.upload_to_tally:
        xml_payload = build_tally_xml(
            normalized_payload,
            company=SETTINGS.tally_company,
            voucher_type=SETTINGS.tally_voucher_type,
            voucher_action=SETTINGS.tally_voucher_action,
        )
        client = TallyClient(
            TallyClientConfig(
                host=SETTINGS.tally_host,
                port=SETTINGS.tally_port,
                company=SETTINGS.tally_company,
                timeout_seconds=SETTINGS.tally_timeout_seconds,
                max_retries=SETTINGS.tally_max_retries,
                retry_backoff_seconds=SETTINGS.tally_retry_backoff_seconds,
            )
        )

        if args.dry_run:
            print(f"[i] Dry run enabled. XML prepared for upload to {client.endpoint}")
            return

        print(f"[*] Uploading XML to Tally at {client.endpoint}...")
        status = client.upload_xml(xml_payload)
        if status.ok:
            print(f"[+] {status.message}")
        else:
            raise SystemExit(f"[!] {status.message}")


if __name__ == "__main__":
    main()
