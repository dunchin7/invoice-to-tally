"""Render a ReconciliationReport as console text or CSV."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from reconciliation.types import MatchPair, MatchStatus, PurchaseRecord, ReconciliationReport


def render_console(report: ReconciliationReport) -> str:
    s = report.summary
    lines = [
        "=" * 80,
        f"GSTR-2B Reconciliation — Period {report.period}   Recipient GSTIN: {report.own_gstin}",
        "=" * 80,
        f"Books:   {s.total_books:>4} invoices    GSTR-2B: {s.total_gstr2b:>4} invoices",
        "",
        f"  Matched              : {s.matched:>4}  (amounts within tolerance)",
        f"  Value mismatch       : {s.value_mismatch:>4}  (review before filing)",
        f"  Books only           : {s.books_only:>4}  (supplier has NOT filed — ITC at risk)",
        f"  GSTR-2B only         : {s.gstr2b_only:>4}  (you have NOT entered — unclaimed ITC)",
        "",
        f"  ITC at risk (your books, supplier missing)  : Rs. {s.itc_at_risk:>12,.2f}",
        f"  ITC unclaimed (in 2B, missing from books)   : Rs. {s.itc_unclaimed:>12,.2f}",
        "",
    ]
    if s.books_only or s.gstr2b_only or s.value_mismatch:
        lines.append("-" * 80)
        lines.append("ACTION REQUIRED BEFORE FILING GSTR-3B")
        lines.append("-" * 80)
        lines.extend(_render_action_section(report.pairs))
    else:
        lines.append("All invoices reconcile cleanly. Safe to proceed with GSTR-3B filing.")
    return "\n".join(lines)


def _render_action_section(pairs: list[MatchPair]) -> list[str]:
    out: list[str] = []
    books_only = [p for p in pairs if p.status == MatchStatus.BOOKS_ONLY]
    gstr2b_only = [p for p in pairs if p.status == MatchStatus.GSTR2B_ONLY]
    mismatches = [p for p in pairs if p.status == MatchStatus.VALUE_MISMATCH]

    if books_only:
        out.append("")
        out.append(f"Books-only ({len(books_only)}) — chase these suppliers to file:")
        for pair in books_only:
            r = pair.books
            out.append(f"  {r.supplier_gstin}  {r.invoice_number:<15} {r.invoice_date}   Rs. {r.total:>12,.2f}   {r.supplier_name or ''}")

    if gstr2b_only:
        out.append("")
        out.append(f"GSTR-2B-only ({len(gstr2b_only)}) — get these invoices from suppliers and enter them:")
        for pair in gstr2b_only:
            r = pair.gstr2b
            out.append(f"  {r.supplier_gstin}  {r.invoice_number:<15} {r.invoice_date}   Rs. {r.total:>12,.2f}   {r.supplier_name or ''}")

    if mismatches:
        out.append("")
        out.append(f"Value mismatches ({len(mismatches)}) — verify before filing:")
        for pair in mismatches:
            r = pair.books
            out.append(f"  {r.supplier_gstin}  {r.invoice_number:<15} {r.invoice_date}")
            for field, (book_val, gstr_val) in pair.differences.items():
                out.append(f"      {field:<14}  books: {book_val}   gstr2b: {gstr_val}")
    return out


CSV_HEADERS = [
    "status", "supplier_gstin", "supplier_name", "invoice_number", "invoice_date",
    "document_type",
    "books_taxable", "books_cgst", "books_sgst", "books_igst", "books_cess", "books_total",
    "gstr2b_taxable", "gstr2b_cgst", "gstr2b_sgst", "gstr2b_igst", "gstr2b_cess", "gstr2b_total",
    "differences",
]


def render_csv(report: ReconciliationReport) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADERS)
    for pair in report.pairs:
        writer.writerow(_csv_row(pair))
    return buffer.getvalue()


def _csv_row(pair: MatchPair) -> list[str]:
    ref = pair.books or pair.gstr2b
    diffs = "; ".join(f"{k}: {v[0]} vs {v[1]}" for k, v in pair.differences.items())
    return [
        pair.status.value,
        ref.supplier_gstin if ref else "",
        ref.supplier_name or "" if ref else "",
        ref.invoice_number if ref else "",
        ref.invoice_date if ref else "",
        ref.document_type if ref else "",
        *_record_amount_cells(pair.books),
        *_record_amount_cells(pair.gstr2b),
        diffs,
    ]


def _record_amount_cells(record: PurchaseRecord | None) -> list[str]:
    if record is None:
        return ["", "", "", "", "", ""]
    return [str(record.taxable_value), str(record.cgst), str(record.sgst), str(record.igst), str(record.cess), str(record.total)]


def write_report_files(report: ReconciliationReport, output_dir: str | Path) -> dict[str, str]:
    """Write JSON + CSV + console-text artifacts and return the written paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "reconciliation_report.json"
    json_path.write_text(_json_dump(report.as_dict()), encoding="utf-8")

    csv_path = out / "reconciliation_report.csv"
    csv_path.write_text(render_csv(report), encoding="utf-8")

    txt_path = out / "reconciliation_report.txt"
    txt_path.write_text(render_console(report), encoding="utf-8")

    return {"json": str(json_path), "csv": str(csv_path), "text": str(txt_path)}


def _json_dump(payload: dict) -> str:
    import json
    return json.dumps(payload, indent=2, default=str)
