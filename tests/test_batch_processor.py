from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.batch_processor import BatchProcessor, discover_invoices
from service.orchestrator import InvoiceJobState, InvoiceOrchestrator


def _make_fake_invoice(path: Path, content: str = "%PDF-1.4 fake") -> Path:
    path.write_bytes(content.encode("utf-8"))
    return path


def test_discover_invoices_finds_supported_extensions(tmp_path):
    _make_fake_invoice(tmp_path / "a.pdf")
    _make_fake_invoice(tmp_path / "b.PNG")
    _make_fake_invoice(tmp_path / "c.jpeg")
    _make_fake_invoice(tmp_path / "ignore.txt")
    _make_fake_invoice(tmp_path / "skip.zip")

    files = discover_invoices(str(tmp_path))
    names = [f.name for f in files]

    assert "a.pdf" in names
    assert "b.PNG" in names
    assert "c.jpeg" in names
    assert "ignore.txt" not in names
    assert "skip.zip" not in names


def test_discover_invoices_recursive(tmp_path):
    sub = tmp_path / "nested"
    sub.mkdir()
    _make_fake_invoice(tmp_path / "top.pdf")
    _make_fake_invoice(sub / "deep.pdf")

    flat = discover_invoices(str(tmp_path), recursive=False)
    deep = discover_invoices(str(tmp_path), recursive=True)

    assert {f.name for f in flat} == {"top.pdf"}
    assert {f.name for f in deep} == {"top.pdf", "deep.pdf"}


def test_discover_invoices_rejects_non_directory(tmp_path):
    file_path = _make_fake_invoice(tmp_path / "single.pdf")
    with pytest.raises(ValueError):
        discover_invoices(str(file_path))


def test_batch_processor_aggregates_mixed_results(tmp_path):
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    file_ok = _make_fake_invoice(invoices_dir / "ok.pdf")
    file_review = _make_fake_invoice(invoices_dir / "review.pdf")
    file_fail = _make_fake_invoice(invoices_dir / "fail.pdf")

    output_dir = tmp_path / "outputs"

    class _StubOrchestrator(InvoiceOrchestrator):
        def process_invoice(self, *, input_path, **_kwargs):
            name = Path(input_path).name
            if name == "ok.pdf":
                return {
                    "job_id": "job-ok",
                    "state": InvoiceJobState.DRY_RUN.value,
                    "artifacts": {},
                    "error": None,
                }
            if name == "review.pdf":
                return {
                    "job_id": "job-review",
                    "state": InvoiceJobState.REVIEW_REQUIRED.value,
                    "artifacts": {},
                    "error": None,
                }
            raise RuntimeError("simulated crash")

    orchestrator = _StubOrchestrator(output_dir=str(output_dir))
    processor = BatchProcessor(orchestrator, max_workers=2, progress_stream=None)

    batch_result = processor.process_directory(str(invoices_dir))

    assert batch_result.total_files == 3
    assert batch_result.summary.dry_run == 1
    assert batch_result.summary.review_required == 1
    assert batch_result.summary.failed == 1

    by_file = {Path(r.file).name: r for r in batch_result.results}
    assert by_file["ok.pdf"].state == InvoiceJobState.DRY_RUN.value
    assert by_file["review.pdf"].state == InvoiceJobState.REVIEW_REQUIRED.value
    assert by_file["fail.pdf"].state == InvoiceJobState.FAILED.value
    assert "simulated crash" in (by_file["fail.pdf"].error or "")

    batch_dir = output_dir / f"batch_{batch_result.batch_id}"
    manifest = json.loads((batch_dir / "batch_manifest.json").read_text())
    assert manifest["summary"]["failed"] == 1
    assert manifest["total_files"] == 3
    assert (batch_dir / "batch_summary.txt").exists()


def test_batch_processor_handles_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path / "out"))
    processor = BatchProcessor(orchestrator, progress_stream=None)

    batch_result = processor.process_directory(str(empty))

    assert batch_result.total_files == 0
    assert batch_result.summary.posted == 0
    assert batch_result.results == []
