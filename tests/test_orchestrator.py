from __future__ import annotations

import json
from pathlib import Path

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator
from tally.client import TallyUploadStatus
from validation.errors import AccountingValidationError, FieldNormalizationError


class _Normalization:
    def __init__(self, normalized, report):
        self.normalized = normalized
        self.report = report


class _Report:
    def __init__(self, critical_failure=False):
        self.warnings = ()
        self.errors = ()
        self.confidence_flags = {}
        self.critical_failure = critical_failure


class _MasterData:
    source = "test"


class _PreImportReport:
    def __init__(self, invoice, blocking=False, issues=None, learned_rules=None):
        self.invoice = invoice
        self.blocking = blocking
        self.resolutions = []
        self.issues = issues or []
        self.learned_rules = learned_rules or []


class _Issue:
    def __init__(self, action="reject"):
        self.action = action
        self.field = "seller"
        self.entity_type = "ledger"
        self.extracted_value = "unknown"
        self.message = "missing mapping"
        self.suggestions = []
        self.suggestion_codes = []


class _Resolver:
    def __init__(self, report):
        self._report = report

    def resolve_invoice(self, *_args, **_kwargs):
        return self._report


def _patch_pipeline(monkeypatch, *, confidence=0.95, blocking=False):
    normalized = {
        "invoice_number": "INV-1",
        "invoice_date": "2024-01-01",
        "total": 100,
        "seller": "SELLER",
        "buyer": "BUYER",
        "line_items": [],
    }

    monkeypatch.setattr("service.orchestrator.route_extraction", lambda _p: "raw text")
    monkeypatch.setattr(
        "service.orchestrator.extract_structured_invoice",
        lambda _t: {"status": "success", "data": normalized, "confidence": {"overall": confidence}},
    )
    monkeypatch.setattr(
        "service.orchestrator.run_normalization_pipeline",
        lambda *_args, **_kwargs: _Normalization(normalized, _Report(False)),
    )
    monkeypatch.setattr("service.orchestrator.to_mutable_invoice", lambda payload: payload)
    monkeypatch.setattr("service.orchestrator.load_master_data_from_file", lambda _p: _MasterData())
    monkeypatch.setattr(
        "service.orchestrator.PreImportResolver",
        lambda **_kwargs: _Resolver(_PreImportReport(normalized, blocking=blocking, issues=[_Issue()] if blocking else [])),
    )
    monkeypatch.setattr(
        "service.orchestrator.generate_tally_xml",
        lambda _invoice, path: Path(path).write_text("<ENVELOPE/>", encoding="utf-8"),
    )


def test_blocking_validation_routes_to_manual_review(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=True)

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.REVIEW_REQUIRED.value
    assert result["review_queue_entry"]["reason"] == "validation_failed"
    assert "generated_xml" not in result["artifacts"]


def test_idempotency_prevents_duplicate_posting(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    generated = []

    def _generate_xml(_invoice, path):
        generated.append(path)
        Path(path).write_text("<ENVELOPE/>", encoding="utf-8")

    class _Client:
        endpoint = "http://localhost:9000"

        def upload_xml(self, _xml_body):
            return TallyUploadStatus(ok=True, endpoint=self.endpoint, created=1, raw_response="<ok/>", message="ok")

    monkeypatch.setattr("service.orchestrator.generate_tally_xml", _generate_xml)
    monkeypatch.setattr("service.orchestrator.InvoiceOrchestrator._build_tally_client", lambda *_a, **_k: _Client())

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    first = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")
    second = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert first["state"] == InvoiceJobState.POSTED.value
    assert second["state"] == InvoiceJobState.POSTED.value
    assert len(generated) == 1

    response_path = second["artifacts"]["upload_response"]
    with open(response_path, "r", encoding="utf-8") as handle:
        response = json.load(handle)

    assert response["status"] == "duplicate"



def test_reconciliation_payload_includes_rule_learning_summary(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    learned = [{"learned": True, "stored_in": "sqlite", "entity_type": "ledger"}]
    normalized = {
        "invoice_number": "INV-1",
        "invoice_date": "2024-01-01",
        "total": 100,
        "seller": "SELLER",
        "buyer": "BUYER",
        "line_items": [],
    }
    monkeypatch.setattr(
        "service.orchestrator.PreImportResolver",
        lambda **_kwargs: _Resolver(_PreImportReport(normalized, blocking=False, issues=[], learned_rules=learned)),
    )
    monkeypatch.setattr(
        "service.orchestrator.InvoiceOrchestrator._build_tally_client",
        lambda *_a, **_k: type("Client", (), {"endpoint": "http://localhost:9000", "upload_xml": lambda self, _xml: TallyUploadStatus(ok=True, endpoint=self.endpoint, created=1, raw_response="<ok/>", message="ok")})(),
    )

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(
        input_path="invoice.pdf",
        master_data_file="master.json",
        reconciliation_approved=True,
    )

    validation_path = result["artifacts"]["validation_report"]
    with open(validation_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)

    learning = report["reconciliation"]["rule_learning"]
    assert learning["enabled"] is True
    assert learning["learned"] is True
    assert learning["stored_in"] == ["sqlite"]


def test_dry_run_generates_xml_and_skips_remote_post(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    class _Client:
        endpoint = "http://localhost:9000"

        def upload_xml(self, _xml_body):
            raise AssertionError("upload_xml should not be called for dry run")

    monkeypatch.setattr("service.orchestrator.InvoiceOrchestrator._build_tally_client", lambda *_a, **_k: _Client())

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json", dry_run=True)

    assert result["state"] == InvoiceJobState.DRY_RUN.value
    assert "upload_request" not in result["artifacts"]
    with open(result["artifacts"]["upload_response"], "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["status"] == "dry_run"


def test_tally_success_transitions_to_posted(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    class _Client:
        endpoint = "http://localhost:9000"

        def upload_xml(self, _xml_body):
            return TallyUploadStatus(ok=True, endpoint=self.endpoint, created=1, raw_response="<ok/>", message="ok")

    monkeypatch.setattr("service.orchestrator.InvoiceOrchestrator._build_tally_client", lambda *_a, **_k: _Client())

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.POSTED.value
    assert "upload_request" in result["artifacts"]


def test_tally_retryable_error_transitions_to_retry_pending(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    class _Client:
        endpoint = "http://localhost:9000"

        def upload_xml(self, _xml_body):
            return TallyUploadStatus(ok=False, endpoint=self.endpoint, raw_response="", message="connection failed")

    monkeypatch.setattr("service.orchestrator.InvoiceOrchestrator._build_tally_client", lambda *_a, **_k: _Client())

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.RETRY_PENDING.value


def test_tally_hard_failure_routes_to_manual_review(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)

    class _Client:
        endpoint = "http://localhost:9000"

        def upload_xml(self, _xml_body):
            return TallyUploadStatus(
                ok=False,
                endpoint=self.endpoint,
                errors=1,
                line_errors=("Voucher type invalid",),
                raw_response="<error/>",
                message="Import failed",
            )

    monkeypatch.setattr("service.orchestrator.InvoiceOrchestrator._build_tally_client", lambda *_a, **_k: _Client())

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.REVIEW_REQUIRED.value
    assert result["review_queue_entry"]["reason"] == "tally_rejected"


def test_schema_or_normalization_error_sets_structured_failure(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)
    monkeypatch.setattr(
        "service.orchestrator.run_normalization_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FieldNormalizationError(
                "bad payload",
                context={"field": "invoice", "expected": "object", "actual": "list"},
            )
        ),
    )

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.FAILED.value
    assert result["error_code"] == "FIELD_NORMALIZATION_ERROR"
    assert result["error_context"]["field"] == "invoice"


def test_accounting_error_routes_review_with_structured_context(tmp_path, monkeypatch):
    _patch_pipeline(monkeypatch, blocking=False)
    monkeypatch.setattr(
        "service.orchestrator.run_normalization_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AccountingValidationError(
                "totals mismatch",
                context={"field": "totals", "expected": "subtotal + tax == total", "actual": ["delta=10"]},
            )
        ),
    )

    orchestrator = InvoiceOrchestrator(output_dir=str(tmp_path))
    result = orchestrator.process_invoice(input_path="invoice.pdf", master_data_file="master.json")

    assert result["state"] == InvoiceJobState.REVIEW_REQUIRED.value
    assert result["error_code"] == "ACCOUNTING_VALIDATION_ERROR"
    assert result["review_queue_entry"]["error_code"] == "ACCOUNTING_VALIDATION_ERROR"
