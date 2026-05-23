from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from service.orchestrator import InvoiceOrchestrator


def parse_args() -> argparse.Namespace:
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
    parser.add_argument("--reconciliation-approved", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ocr-timeout-seconds", type=float, default=None)
    parser.add_argument("--ocr-max-pages", type=int, default=None)
    return parser.parse_args()


def _validate_config() -> None:
    """Fail fast with clear error messages for missing required configuration."""
    provider = os.getenv("LLM_PROVIDER", "azure_openai").lower()
    errors: list[str] = []

    if provider in ("azure_openai", ""):
        if not os.getenv("AZURE_OPENAI_API_KEY"):
            errors.append("AZURE_OPENAI_API_KEY is not set (set LLM_PROVIDER=gemini to use Google Gemini instead)")
        if not os.getenv("AZURE_OPENAI_ENDPOINT"):
            errors.append("AZURE_OPENAI_ENDPOINT is not set (e.g. https://yourinstance.openai.azure.com)")
        if not (os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")):
            errors.append("AZURE_OPENAI_DEPLOYMENT_NAME (or AZURE_OPENAI_DEPLOYMENT) is not set (e.g. gpt-4o)")
    elif provider == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            errors.append("GEMINI_API_KEY is not set")

    if errors:
        print("ERROR: Missing required configuration. Copy .env.example to .env and fill in the values.", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    args = parse_args()
    _validate_config()
    if args.ocr_timeout_seconds is not None:
        os.environ["OCR_TIMEOUT_SECONDS"] = str(args.ocr_timeout_seconds)
    if args.ocr_max_pages is not None:
        os.environ["OCR_MAX_PAGES"] = str(args.ocr_max_pages)

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
        reconciliation_approved=args.reconciliation_approved,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
