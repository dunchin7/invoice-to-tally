from __future__ import annotations

import json
from pathlib import Path

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator
from tally.master_data import TallyMasterData, TallyMasterRecord
from validation.errors import AccountingValidationError


class _FakeMasterDataClient:
    """Deterministic stand-in for live Tally master-data HTTP calls."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def get_master_data(self, force_refresh: bool = False) -> TallyMasterData:
        return TallyMasterData(
            parties=(
                TallyMasterRecord(
                    name="Test Business | 123 Somewhere St Melbourne, VIC 3000",
                    code="P001",
                ),
            ),
            ledgers=(
                TallyMasterRecord(
                    name="DEMO - Sliced Invoices | Suite 5A-1204 123 Somewhere Street Your City AZ 12345",
                    code="L001",
                ),
            ),
            stock_items=(
                TallyMasterRecord(name="Web Design - This is a sample description...", code="S001"),
            ),
            fetched_at_epoch=123.0,
            source="mock_http",
        )


class _Normalization:
    def __init__(self, normalized, report):
        self.normalized = normalized
        self.report = report


class _Report:
    def __init__(self):
        self.warnings = ()
        self.errors = ()
        self.confidence_flags = {}
        self.critical_failure = False


def _ground_truth_invoice() -> dict:
    payload = json.loads(Path("datasets/ground_truth/sample_invoice.json").read_text(encoding="utf-8"))
    payload["schema_version"] = "1.0"
    payload["invoice_date"] = "2016-01-25"
    return payload


def test_smoke_orchestrator_end_to_end_with_sample_fixture(tmp_path, monkeypatch):
    sample_invoice_path = Path("samples/sample_invoice.pdf")
    assert sample_invoice_path.exists(), "Sample fixture required for smoke test."

    monkeypatch.setattr("service.orchestrator.route_extraction", lambda path: f"OCR for {Path(path).name}")
    monkeypatch.setattr(
        "service.orchestrator.extract_structured_invoice",
        lambda _raw_text: {"status": "success", "data": _ground_truth_invoice(), "confidence": {"overall": 0.97}},
    )
    monkeypatch.setattr("service.orchestrator.TallyMasterDataClient", _FakeMasterDataClient)
    monkeypatch.setattr(
        "service.orchestrator.run_normalization_pipeline",
        lambda payload, **_kwargs: _Normalization(payload, _Report()),
    )
    monkeypatch.setattr("service.orchestrator.to_mutable_invoice", lambda payload: dict(payload))

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path), low_confidence_threshold=0.8)
    result = orchestrator.process_invoice(input_path=str(sample_invoice_path), master_data_file="")

    assert result["state"] == InvoiceJobState.POSTED.value
    assert Path(result["artifacts"]["raw_ocr_text"]).exists()
    assert Path(result["artifacts"]["extracted_json"]).exists()
    assert Path(result["artifacts"]["validation_report"]).exists()
    assert Path(result["artifacts"]["generated_xml"]).exists()

    with open(result["artifacts"]["upload_response"], "r", encoding="utf-8") as handle:
        upload_response = json.load(handle)
    assert upload_response["status"] == "success"

    with open(result["artifacts"]["validation_report"], "r", encoding="utf-8") as handle:
        validation_report = json.load(handle)
    assert validation_report["master_data_source"] == "mock_http"
    assert validation_report["reconciliation"]["blocking"] is False


def test_smoke_orchestrator_error_classification_is_structured(tmp_path, monkeypatch):
    sample_invoice_path = Path("samples/sample_invoice.pdf")
    assert sample_invoice_path.exists(), "Sample fixture required for smoke test."

    monkeypatch.setattr("service.orchestrator.route_extraction", lambda _path: "raw ocr")
    monkeypatch.setattr(
        "service.orchestrator.extract_structured_invoice",
        lambda _raw_text: {"status": "success", "data": _ground_truth_invoice(), "confidence": {"overall": 0.97}},
    )
    monkeypatch.setattr(
        "service.orchestrator.run_normalization_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AccountingValidationError(
                "totals mismatch",
                context={"field": "totals", "actual": ["delta=2.5"]},
            )
        ),
    )

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path=str(sample_invoice_path), master_data_file="")

    assert result["state"] == InvoiceJobState.REVIEW_REQUIRED.value
    assert result["error_code"] == "ACCOUNTING_VALIDATION_ERROR"
    assert result["review_queue_entry"]["reason"] == "validation_failed"
    assert result["review_queue_entry"]["error_context"]["field"] == "totals"
