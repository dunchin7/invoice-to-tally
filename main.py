from __future__ import annotations

import argparse
import json
import os

from service.orchestrator import InvoiceOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoice OCR → LLM → Validation → Tally orchestration")
    parser.add_argument("--input", required=True, help="Path to invoice PDF/image/document")
    parser.add_argument("--orchestration-output", default="outputs/orchestration")
    parser.add_argument("--low-confidence-threshold", type=float, default=0.8)
    parser.add_argument("--allow-accounting-override", action="store_true")
    parser.add_argument("--operator", default="system")

    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--master-data-file", default="")
    parser.add_argument("--tally-base-url", default="http://localhost:9000")
    parser.add_argument("--mapping-rules-file", default="validation/config/mapping_rules.json")
    parser.add_argument("--mapping-rules-db", default="")
    parser.add_argument("--party-fallback", choices=["auto_create", "reject", "manual_review"], default="manual_review")
    parser.add_argument("--ledger-fallback", choices=["auto_create", "reject", "manual_review"], default="reject")
    parser.add_argument("--stock-fallback", choices=["auto_create", "reject", "manual_review"], default="manual_review")
from ingestion.router import IngestionError, route_extraction
from llm.extractor import extract_structured_invoice
from settings import SETTINGS
from tally.client import TallyClient, TallyClientConfig
from tally.xml_generator import build_tally_xml, generate_tally_xml
from validation.normalizer import validate_invoice
from validation.pipeline import run_normalization_pipeline, to_mutable_invoice


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Invoice OCR → LLM → Validation → Tally XML")
    parser.add_argument("--input", required=True, help="Path to invoice PDF/image/document")
    parser.add_argument("--output", default="outputs/invoice_structured.json", help="Path for structured invoice JSON")
    parser.add_argument("--report-output", default="outputs/validation_report.json", help="Path for validation report JSON")
    parser.add_argument("--tally-output", default="outputs/tally_invoice.xml", help="Path for generated Tally XML")
    parser.add_argument("--allow-accounting-override", action="store_true", help="Allow generation even with critical mismatch")

    parser.add_argument("--upload-to-tally", action="store_true", help="Upload generated XML to Tally HTTP endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Prepare XML and print upload destination without posting")
    parser.add_argument("--tally-host", default=SETTINGS.tally_host, help="Tally host")
    parser.add_argument("--tally-port", default=SETTINGS.tally_port, type=int, help="Tally port")
    parser.add_argument("--tally-company", default=SETTINGS.tally_company, help="Tally company name")
    parser.add_argument("--tally-voucher-type", default=SETTINGS.tally_voucher_type, help="Tally voucher type")
    parser.add_argument("--tally-voucher-action", default=SETTINGS.tally_voucher_action, help="Tally voucher action")
    return parser.parse_args()

    orchestrator = InvoiceOrchestrator(
        output_dir=args.orchestration_output,
        low_confidence_threshold=args.low_confidence_threshold,
    )
    result = orchestrator.process_invoice(
        input_path=args.input,
        operator=args.operator,
        allow_accounting_override=args.allow_accounting_override,
        tenant_id=args.tenant_id,
        master_data_file=args.master_data_file,
        tally_base_url=args.tally_base_url,
        mapping_rules_file=args.mapping_rules_file,
        mapping_rules_db=args.mapping_rules_db,
        fallback_policy={
            "party": args.party_fallback,
            "ledger": args.ledger_fallback,
            "stock_item": args.stock_fallback,
        },

def main() -> None:
    args = parse_args()
    os.makedirs("outputs", exist_ok=True)

    try:
        raw_text = route_extraction(args.input)
    except IngestionError as exc:
        raise SystemExit(f"[!] Ingestion failed: {exc}")

    extraction_result = extract_structured_invoice(raw_text)
    if extraction_result.get("status") != "success":
        raise SystemExit(f"[!] Invoice extraction failed: {extraction_result.get('error', {}).get('message', 'Unknown error')}")

    validated = validate_invoice(extraction_result["data"])
    normalization = run_normalization_pipeline(validated, allow_critical_override=args.allow_accounting_override)
    normalized_payload = to_mutable_invoice(normalization.normalized)

    extraction_result["data"] = normalized_payload
    with open(args.output, "w", encoding="utf-8") as out_json:
        json.dump(extraction_result, out_json, indent=2)

    report_payload = {
        "warnings": list(normalization.report.warnings),
        "errors": list(normalization.report.errors),
        "confidence_flags": dict(normalization.report.confidence_flags),
        "critical_failure": normalization.report.critical_failure,
    }
    with open(args.report_output, "w", encoding="utf-8") as out_report:
        json.dump(report_payload, out_report, indent=2)

    generate_tally_xml(
        normalized_payload,
        args.tally_output,
        company=args.tally_company,
        voucher_type=args.tally_voucher_type,
        voucher_action=args.tally_voucher_action,
    )

    if not args.upload_to_tally:
        return

    xml_payload = build_tally_xml(
        normalized_payload,
        company=args.tally_company,
        voucher_type=args.tally_voucher_type,
        voucher_action=args.tally_voucher_action,
    )
    client = TallyClient(
        TallyClientConfig(
            host=args.tally_host,
            port=args.tally_port,
            company=args.tally_company,
            voucher_type=args.tally_voucher_type,
            voucher_action=args.tally_voucher_action,
            timeout_seconds=SETTINGS.tally_timeout_seconds,
            max_retries=SETTINGS.tally_max_retries,
            retry_backoff_seconds=SETTINGS.tally_retry_backoff_seconds,
        )
    )

    if args.dry_run:
        print(f"[i] Dry run enabled. XML prepared for upload to {client.endpoint}")
        return

    status = client.upload_xml(xml_payload)
    if status.ok:
        print(f"[+] {status.message}")
    else:
        raise SystemExit(f"[!] {status.message}")


if __name__ == "__main__":
    main()
