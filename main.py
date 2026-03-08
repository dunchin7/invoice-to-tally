import argparse
import json
import os

from ingestion.router import IngestionError, route_extraction
from llm.extractor import extract_structured_invoice
from tally.master_data import TallyMasterDataClient, load_master_data_from_file
from tally.xml_generator import generate_tally_xml
from validation.normalizer import validate_invoice
from validation.pipeline import run_normalization_pipeline, to_mutable_invoice
from validation.pre_import import MappingRuleStore, PreImportResolver


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
        "--preimport-report-output",
        default="outputs/preimport_report.json",
        help="Path to save pre-import master-data reconciliation report",
    )
    parser.add_argument("--tenant-id", default="default", help="Tenant ID used for mapping rule lookups")
    parser.add_argument(
        "--master-data-file",
        default="",
        help="Optional static JSON path for master data. If omitted, pulls from Tally and caches locally.",
    )
    parser.add_argument(
        "--tally-base-url",
        default="http://localhost:9000",
        help="Tally HTTP endpoint for master-data export",
    )
    parser.add_argument(
        "--mapping-rules-file",
        default="validation/config/mapping_rules.json",
        help="Tenant mapping rules JSON file",
    )
    parser.add_argument(
        "--mapping-rules-db",
        default="",
        help="Optional SQLite DB for mapping rules (table: mapping_rules)",
    )
    parser.add_argument(
        "--party-fallback",
        choices=["auto_create", "reject", "manual_review"],
        default="manual_review",
        help="Fallback policy for unresolved party mappings",
    )
    parser.add_argument(
        "--stock-fallback",
        choices=["auto_create", "reject", "manual_review"],
        default="manual_review",
        help="Fallback policy for unresolved stock-item mappings",
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

    normalization_result = run_normalization_pipeline(
        validated,
        allow_critical_override=args.allow_accounting_override,
    )
    normalized_payload = to_mutable_invoice(normalization_result.normalized)

    if args.master_data_file:
        master_data = load_master_data_from_file(args.master_data_file)
    else:
        master_client = TallyMasterDataClient(base_url=args.tally_base_url)
        master_data = master_client.get_master_data()

    resolver = PreImportResolver(
        master_data=master_data,
        rule_store=MappingRuleStore(json_path=args.mapping_rules_file, sqlite_path=args.mapping_rules_db or None),
        fallback_policy={"party": args.party_fallback, "stock_item": args.stock_fallback},
    )
    preimport_report = resolver.resolve_invoice(normalized_payload, tenant_id=args.tenant_id)

    extraction_result["data"] = preimport_report.invoice

    output_report = {
        "warnings": list(normalization_result.report.warnings),
        "errors": list(normalization_result.report.errors),
        "confidence_flags": dict(normalization_result.report.confidence_flags),
        "critical_failure": normalization_result.report.critical_failure,
        "master_data_source": master_data.source,
        "reconciliation": {
            "blocking": preimport_report.blocking,
            "resolutions": [resolution.__dict__ for resolution in preimport_report.resolutions],
            "issues": [issue.__dict__ for issue in preimport_report.issues],
        },
    }

    if preimport_report.blocking:
        actionable = " | ".join(
            f"{issue.field}: {issue.message} suggestions={list(issue.suggestions)}"
            for issue in preimport_report.issues
            if issue.action == "reject"
        )
        raise RuntimeError(f"Pre-import reconciliation failed. {actionable}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(extraction_result, f, indent=2)

    with open(args.report_output, "w", encoding="utf-8") as f:
        json.dump(output_report, f, indent=2)

    with open(args.preimport_report_output, "w", encoding="utf-8") as f:
        json.dump(output_report["reconciliation"], f, indent=2)

    print(f"[+] Structured invoice saved to: {args.output}")
    print(f"[+] Validation report saved to: {args.report_output}")
    print(f"[+] Pre-import reconciliation report saved to: {args.preimport_report_output}")

    generate_tally_xml(preimport_report.invoice, args.tally_output)
    print(f"[+] Tally XML saved to: {args.tally_output}")


if __name__ == "__main__":
    main()
