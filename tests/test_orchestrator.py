from __future__ import annotations

import json

from service.orchestrator import InvoiceJobState, InvoiceOrchestrator


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

    monkeypatch.setattr("service.orchestrator.generate_tally_xml", _generate_xml)

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
