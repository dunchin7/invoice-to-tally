from __future__ import annotations

import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS: tuple[str, ...] = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".doc", ".docx")


@dataclass
class InvoiceResult:
    file: str
    job_id: str | None
    state: str
    invoice_number: str | None
    invoice_date: str | None
    total: float | None
    confidence: float | None
    elapsed_seconds: float
    error: str | None
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class BatchSummary:
    posted: int = 0
    dry_run: int = 0
    review_required: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class BatchResult:
    batch_id: str
    input_dir: str
    started_at: str
    completed_at: str
    elapsed_seconds: float
    total_files: int
    summary: BatchSummary
    results: list[InvoiceResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "input_dir": self.input_dir,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "total_files": self.total_files,
            "summary": asdict(self.summary),
            "results": [asdict(r) for r in self.results],
        }


def discover_invoices(input_dir: str, recursive: bool = False) -> list[Path]:
    root = Path(input_dir)
    if not root.is_dir():
        raise ValueError(f"input_dir is not a directory: {input_dir}")

    iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    files = [
        p for p in iterator
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    files.sort()
    return files


class BatchProcessor:
    def __init__(
        self,
        orchestrator: InvoiceOrchestrator,
        max_workers: int = 4,
        progress_stream=sys.stderr,
    ):
        self.orchestrator = orchestrator
        self.max_workers = max(1, max_workers)
        self.progress_stream = progress_stream
        self._progress_lock = threading.Lock()

    def _emit_progress(self, message: str) -> None:
        if self.progress_stream is None:
            return
        with self._progress_lock:
            print(message, file=self.progress_stream, flush=True)

    def _process_one(
        self,
        file_path: Path,
        process_kwargs: dict[str, Any],
        index: int,
        total: int,
    ) -> InvoiceResult:
        started = time.monotonic()
        try:
            result = self.orchestrator.process_invoice(input_path=str(file_path), **process_kwargs)
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._emit_progress(f"[{index}/{total}] FAIL {file_path.name}: {exc}")
            return InvoiceResult(
                file=str(file_path),
                job_id=None,
                state=InvoiceJobState.FAILED.value,
                invoice_number=None,
                invoice_date=None,
                total=None,
                confidence=None,
                elapsed_seconds=round(elapsed, 2),
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed = time.monotonic() - started
        state = result.get("state", "unknown")
        normalized_path = result.get("artifacts", {}).get("normalized_json")
        invoice_number, invoice_date, total = _summarize_invoice(normalized_path)
        extracted_path = result.get("artifacts", {}).get("extracted_json")
        confidence = _read_confidence(extracted_path)

        self._emit_progress(f"[{index}/{total}] {state.upper()} {file_path.name} ({elapsed:.1f}s)")

        return InvoiceResult(
            file=str(file_path),
            job_id=result.get("job_id"),
            state=state,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            total=total,
            confidence=confidence,
            elapsed_seconds=round(elapsed, 2),
            error=result.get("error"),
            artifacts=result.get("artifacts", {}),
        )

    def process_directory(
        self,
        input_dir: str,
        recursive: bool = False,
        process_kwargs: dict[str, Any] | None = None,
    ) -> BatchResult:
        process_kwargs = process_kwargs or {}
        files = discover_invoices(input_dir, recursive=recursive)
        total = len(files)
        batch_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        started_monotonic = time.monotonic()

        self._emit_progress(f"[batch:{batch_id[:8]}] discovered {total} files in {input_dir} (workers={self.max_workers})")

        results: list[InvoiceResult] = []
        if total == 0:
            self._emit_progress(f"[batch:{batch_id[:8]}] no supported files found")
        else:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._process_one, file_path, process_kwargs, i + 1, total): file_path
                    for i, file_path in enumerate(files)
                }
                for future in as_completed(futures):
                    results.append(future.result())

        results.sort(key=lambda r: r.file)
        completed_at = datetime.now(timezone.utc).isoformat()
        elapsed = time.monotonic() - started_monotonic

        summary = _build_summary(results)
        batch_result = BatchResult(
            batch_id=batch_id,
            input_dir=str(Path(input_dir).resolve()),
            started_at=started_at,
            completed_at=completed_at,
            elapsed_seconds=elapsed,
            total_files=total,
            summary=summary,
            results=results,
        )

        self._write_manifest(batch_result)
        self._emit_summary(batch_result)
        return batch_result

    def _write_manifest(self, batch_result: BatchResult) -> None:
        batch_dir = self.orchestrator.base_path / f"batch_{batch_result.batch_id}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(json.dumps(batch_result.to_dict(), indent=2))

        summary_path = batch_dir / "batch_summary.txt"
        summary_path.write_text(_format_text_summary(batch_result))

    def _emit_summary(self, batch_result: BatchResult) -> None:
        self._emit_progress("")
        self._emit_progress("=" * 72)
        for line in _format_text_summary(batch_result).splitlines():
            self._emit_progress(line)


def _summarize_invoice(normalized_path: str | None) -> tuple[str | None, str | None, float | None]:
    if not normalized_path:
        return None, None, None
    try:
        data = json.loads(Path(normalized_path).read_text())
    except (OSError, json.JSONDecodeError):
        return None, None, None
    return (
        data.get("invoice_number"),
        data.get("invoice_date"),
        data.get("total"),
    )


def _read_confidence(extracted_path: str | None) -> float | None:
    if not extracted_path:
        return None
    try:
        data = json.loads(Path(extracted_path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    confidence = data.get("confidence")
    if isinstance(confidence, dict):
        return confidence.get("overall")
    return None


def _build_summary(results: list[InvoiceResult]) -> BatchSummary:
    summary = BatchSummary()
    for r in results:
        if r.state == InvoiceJobState.POSTED.value:
            summary.posted += 1
        elif r.state == InvoiceJobState.DRY_RUN.value:
            summary.dry_run += 1
        elif r.state == InvoiceJobState.REVIEW_REQUIRED.value:
            summary.review_required += 1
        elif r.state == InvoiceJobState.FAILED.value:
            summary.failed += 1
        else:
            summary.skipped += 1
    return summary


def _format_text_summary(batch_result: BatchResult) -> str:
    s = batch_result.summary
    lines = [
        f"Batch: {batch_result.batch_id}",
        f"Input: {batch_result.input_dir}",
        f"Files: {batch_result.total_files}   Elapsed: {batch_result.elapsed_seconds:.1f}s",
        f"  posted={s.posted}  dry_run={s.dry_run}  review_required={s.review_required}  failed={s.failed}  skipped={s.skipped}",
        "",
        f"{'File':<40} {'State':<16} {'Invoice#':<14} {'Total':>12}  {'Time':>6}",
        "-" * 96,
    ]
    for r in batch_result.results:
        name = Path(r.file).name
        if len(name) > 38:
            name = name[:35] + "..."
        total_str = f"{r.total:,.2f}" if r.total is not None else "-"
        inv = (r.invoice_number or "-")[:14]
        lines.append(f"{name:<40} {r.state:<16} {inv:<14} {total_str:>12}  {r.elapsed_seconds:>5.1f}s")
        if r.error:
            err = r.error if len(r.error) < 90 else r.error[:87] + "..."
            lines.append(f"  └─ {err}")
    return "\n".join(lines)
