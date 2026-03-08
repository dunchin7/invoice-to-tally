import argparse
import json

from service.orchestrator import InvoiceOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoice OCR → LLM → Validation → Orchestrated Tally posting"
    )
    parser.add_argument("--input", required=True, help="Path to invoice PDF/image/document")
    parser.add_argument(
        "--orchestration-output",
        default="outputs/orchestration",
        help="Directory used by the orchestration service for job state and artifacts",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        default=0.8,
        type=float,
        help="Invoices below this extraction confidence are routed to manual review",
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
        "--operator",
        default="system",
        help="Operator identifier for audit logs when manually invoking this command",
    )

    args = parser.parse_args()

    orchestrator = InvoiceOrchestrator(
        output_dir=args.orchestration_output,
        low_confidence_threshold=args.low_confidence_threshold,
    )

    result = orchestrator.process_invoice(
        input_path=args.input,
        operator=args.operator,
        allow_accounting_override=args.allow_accounting_override,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
