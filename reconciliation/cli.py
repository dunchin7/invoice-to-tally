"""Stand-alone CLI for GSTR-2B reconciliation.

Usage:
    python -m reconciliation.cli \\
        --gstr2b path/to/gstr2b.json \\
        --books-dir outputs/orchestration \\
        --period 2025-04 \\
        --own-gstin 27ABCDE5678F1Z3 \\
        --output-dir outputs/reconciliation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reconciliation.books_loader import load_books_from_json, load_books_from_outputs
from reconciliation.matcher import reconcile
from reconciliation.parser import GSTR2BParseError, parse_gstr2b
from reconciliation.reporter import render_console, write_report_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GSTR-2B reconciliation engine")
    parser.add_argument("--gstr2b", required=True, help="Path to GSTR-2B JSON downloaded from GSTN portal")
    parser.add_argument("--books-dir", default=None, help="Orchestration output directory to scan for purchase invoices")
    parser.add_argument("--books-file", default=None, help="Alternative: flat JSON file with a list of normalized invoices")
    parser.add_argument("--period", default=None, help="Filter books by period prefix, e.g. 2025-04 (matches invoice_date YYYY-MM-*)")
    parser.add_argument("--own-gstin", required=True, help="The recipient GSTIN that owns the GSTR-2B file")
    parser.add_argument("--output-dir", default="outputs/reconciliation", help="Where to write the report artifacts")
    parser.add_argument("--amount-tolerance", type=float, default=1.0, help="INR difference treated as a match (default 1.00)")
    parser.add_argument("--date-window-days", type=int, default=3, help="Allowed date drift in days (default 3)")
    parser.add_argument("--quiet", action="store_true", help="Skip console summary output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.books_dir and not args.books_file:
        print("ERROR: provide either --books-dir or --books-file to source the books side.", file=sys.stderr)
        return 1

    try:
        gstr2b_records = parse_gstr2b(args.gstr2b)
    except GSTR2BParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.books_dir:
        books_records = load_books_from_outputs(args.books_dir, period_yyyy_mm=args.period, own_gstins=[args.own_gstin])
    else:
        books_records = load_books_from_json(args.books_file, period_yyyy_mm=args.period)

    from decimal import Decimal
    report = reconcile(
        books=books_records,
        gstr2b=gstr2b_records,
        period=args.period or "unspecified",
        own_gstin=args.own_gstin,
        amount_tolerance=Decimal(str(args.amount_tolerance)),
        date_window_days=args.date_window_days,
    )

    artifact_paths = write_report_files(report, args.output_dir)
    if not args.quiet:
        print(render_console(report))
        print("")
        print(f"Reports written to:")
        for kind, path in artifact_paths.items():
            print(f"  {kind:<6} {path}")

    # Exit non-zero when there are filing-blocking issues
    if report.summary.books_only or report.summary.gstr2b_only or report.summary.value_mismatch:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
