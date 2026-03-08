import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_KEY_FIELDS = [
    "invoice_number",
    "invoice_date",
    "seller",
    "buyer",
    "currency",
    "subtotal",
    "tax",
    "total",
]
DEFAULT_CRITICAL_FIELDS = ["invoice_number", "invoice_date", "total"]


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().lower()


def values_match(field: str, gt: Any, pred: Any, numeric_tolerance: float) -> bool:
    if gt is None and pred is None:
        return True
    if gt is None or pred is None:
        return False

    numeric_fields = {"subtotal", "tax", "total", "quantity", "unit_price", "total_price"}
    if field in numeric_fields:
        gt_num = _to_float(gt)
        pred_num = _to_float(pred)
        if gt_num is None or pred_num is None:
            return False
        return math.isclose(gt_num, pred_num, abs_tol=numeric_tolerance)

    return _normalize_text(gt) == _normalize_text(pred)


def canonical_line_item(item: Dict[str, Any], numeric_tolerance: float) -> Tuple[str, str, str, str]:
    def n(field: str) -> str:
        value = _to_float(item.get(field))
        if value is None:
            return ""
        rounded = round(value / numeric_tolerance) * numeric_tolerance if numeric_tolerance > 0 else value
        return f"{rounded:.6f}"

    description = _normalize_text(item.get("description")) or ""
    return (
        description,
        n("quantity"),
        n("unit_price"),
        n("total_price"),
    )


def evaluate_line_items(gt_items: List[Dict[str, Any]], pred_items: List[Dict[str, Any]], numeric_tolerance: float) -> PRF:
    gt_pool = [canonical_line_item(item, numeric_tolerance) for item in gt_items]
    pred_pool = [canonical_line_item(item, numeric_tolerance) for item in pred_items]

    matched_gt = [False] * len(gt_pool)
    metrics = PRF()

    for pred in pred_pool:
        match_index = next((idx for idx, gt in enumerate(gt_pool) if not matched_gt[idx] and gt == pred), None)
        if match_index is not None:
            matched_gt[match_index] = True
            metrics.tp += 1
        else:
            metrics.fp += 1

    metrics.fn += matched_gt.count(False)
    return metrics


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_documents(
    ground_truth_dir: Path,
    predictions_dir: Path,
    key_fields: List[str],
    critical_fields: List[str],
    numeric_tolerance: float,
) -> Dict[str, Any]:
    field_metrics = {field: PRF() for field in key_fields}
    line_item_metrics = PRF()
    document_rows = []

    gt_files = sorted(ground_truth_dir.glob("*.json"))
    if not gt_files:
        raise ValueError(f"No ground truth JSON files found in {ground_truth_dir}")

    for gt_file in gt_files:
        doc_id = gt_file.stem
        pred_file = predictions_dir / f"{doc_id}.json"

        gt_doc = load_json(gt_file)
        pred_doc = load_json(pred_file) if pred_file.exists() else {}

        field_matches = {}
        critical_pass = True

        for field in key_fields:
            gt_val = gt_doc.get(field)
            pred_val = pred_doc.get(field)
            match = values_match(field, gt_val, pred_val, numeric_tolerance)
            field_matches[field] = match

            if gt_val is not None and pred_val is not None:
                if match:
                    field_metrics[field].tp += 1
                else:
                    field_metrics[field].fp += 1
                    field_metrics[field].fn += 1
            elif gt_val is None and pred_val is not None:
                field_metrics[field].fp += 1
            elif gt_val is not None and pred_val is None:
                field_metrics[field].fn += 1
            else:
                pass

            if field in critical_fields and not match:
                critical_pass = False

        line_metrics = evaluate_line_items(
            gt_doc.get("line_items", []),
            pred_doc.get("line_items", []),
            numeric_tolerance=numeric_tolerance,
        )
        line_item_metrics.tp += line_metrics.tp
        line_item_metrics.fp += line_metrics.fp
        line_item_metrics.fn += line_metrics.fn

        doc_exact_match = all(field_matches.values()) and line_metrics.fp == 0 and line_metrics.fn == 0

        document_rows.append(
            {
                "doc_id": doc_id,
                "prediction_found": pred_file.exists(),
                "doc_exact_match": doc_exact_match,
                "critical_fields_pass": critical_pass,
                "line_items_precision": line_metrics.precision,
                "line_items_recall": line_metrics.recall,
                "line_items_f1": line_metrics.f1,
            }
        )

    overall_docs = len(document_rows)
    doc_exact_match_rate = sum(1 for row in document_rows if row["doc_exact_match"]) / overall_docs
    critical_doc_pass_rate = sum(1 for row in document_rows if row["critical_fields_pass"]) / overall_docs

    field_summary = {
        field: {
            "tp": metric.tp,
            "fp": metric.fp,
            "fn": metric.fn,
            "precision": metric.precision,
            "recall": metric.recall,
            "f1": metric.f1,
        }
        for field, metric in field_metrics.items()
    }

    micro_field = PRF(
        tp=sum(metric.tp for metric in field_metrics.values()),
        fp=sum(metric.fp for metric in field_metrics.values()),
        fn=sum(metric.fn for metric in field_metrics.values()),
    )

    return {
        "documents": document_rows,
        "field_metrics": field_summary,
        "line_item_metrics": {
            "tp": line_item_metrics.tp,
            "fp": line_item_metrics.fp,
            "fn": line_item_metrics.fn,
            "precision": line_item_metrics.precision,
            "recall": line_item_metrics.recall,
            "f1": line_item_metrics.f1,
        },
        "overall": {
            "documents_total": overall_docs,
            "document_exact_match_rate": doc_exact_match_rate,
            "critical_document_pass_rate": critical_doc_pass_rate,
            "field_micro_precision": micro_field.precision,
            "field_micro_recall": micro_field.recall,
            "field_micro_f1": micro_field.f1,
        },
    }


def write_reports(summary: Dict[str, Any], report_dir: Path) -> Tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "evaluation_summary.json"
    csv_path = report_dir / "evaluation_fields.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["field", "tp", "fp", "fn", "precision", "recall", "f1"],
        )
        writer.writeheader()
        for field, metrics in summary["field_metrics"].items():
            writer.writerow({"field": field, **metrics})
        writer.writerow({"field": "line_items", **summary["line_item_metrics"]})

    return json_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate extraction quality against benchmark JSON labels")
    parser.add_argument("--ground-truth-dir", default="datasets/ground_truth", help="Folder of labeled JSON files")
    parser.add_argument("--predictions-dir", default="outputs", help="Folder of predicted JSON files")
    parser.add_argument("--report-dir", default="evaluation/reports", help="Folder for CSV/JSON evaluation output")
    parser.add_argument("--key-fields", nargs="+", default=DEFAULT_KEY_FIELDS, help="Fields evaluated with precision/recall/F1")
    parser.add_argument(
        "--critical-fields",
        nargs="+",
        default=DEFAULT_CRITICAL_FIELDS,
        help="Fields required to pass release gate",
    )
    parser.add_argument("--numeric-tolerance", type=float, default=0.01, help="Absolute tolerance for numeric comparison")
    parser.add_argument("--critical-f1-threshold", type=float, default=0.95, help="Minimum F1 per critical field")
    parser.add_argument("--critical-doc-pass-threshold", type=float, default=0.9, help="Minimum doc-level critical pass rate")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    summary = evaluate_documents(
        ground_truth_dir=Path(args.ground_truth_dir),
        predictions_dir=Path(args.predictions_dir),
        key_fields=args.key_fields,
        critical_fields=args.critical_fields,
        numeric_tolerance=args.numeric_tolerance,
    )

    json_path, csv_path = write_reports(summary, Path(args.report_dir))

    critical_field_results = {
        field: summary["field_metrics"][field]["f1"] >= args.critical_f1_threshold
        for field in args.critical_fields
        if field in summary["field_metrics"]
    }
    docs_gate = summary["overall"]["critical_document_pass_rate"] >= args.critical_doc_pass_threshold
    release_ready = docs_gate and all(critical_field_results.values())

    gate_summary = {
        "critical_f1_threshold": args.critical_f1_threshold,
        "critical_doc_pass_threshold": args.critical_doc_pass_threshold,
        "critical_field_results": critical_field_results,
        "critical_document_pass_rate": summary["overall"]["critical_document_pass_rate"],
        "release_ready": release_ready,
    }
    summary["release_gate"] = gate_summary

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"[+] Evaluation JSON report: {json_path}")
    print(f"[+] Evaluation CSV report:  {csv_path}")
    print(f"[+] Release gate: {'PASS' if release_ready else 'FAIL'}")

    if not release_ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
