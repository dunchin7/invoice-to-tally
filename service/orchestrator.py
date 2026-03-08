from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from ingestion.router import IngestionError, route_extraction
from llm.extractor import extract_structured_invoice
from tally.xml_generator import generate_tally_xml
from validation.pipeline import run_normalization_pipeline, to_mutable_invoice


class InvoiceJobState(str, Enum):
    INGESTED = "ingested"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    REVIEW_REQUIRED = "review_required"
    POSTED = "posted"
    FAILED = "failed"


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str
    actor: str
    action: str
    state: str
    details: Dict[str, Any]


class InvoiceOrchestrator:
    def __init__(
        self,
        output_dir: str = "outputs/orchestration",
        low_confidence_threshold: float = 0.8,
    ):
        self.base_path = Path(output_dir)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.low_confidence_threshold = low_confidence_threshold
        self.idempotency_store_path = self.base_path / "idempotency_store.json"
        self.review_queue_path = self.base_path / "manual_review_queue.jsonl"

    def process_invoice(
        self,
        input_path: str,
        operator: str = "system",
        allow_accounting_override: bool = False,
    ) -> Dict[str, Any]:
        job_id = str(uuid4())
        job_path = self.base_path / job_id
        job_path.mkdir(parents=True, exist_ok=True)

        audit_log: list[AuditEvent] = []
        record: Dict[str, Any] = {
            "job_id": job_id,
            "input_path": str(input_path),
            "state": None,
            "idempotency_key": None,
            "artifacts": {},
            "audit_log": [],
        }

        def transition(state: InvoiceJobState, action: str, details: Dict[str, Any] | None = None) -> None:
            payload = details or {}
            record["state"] = state.value
            event = AuditEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                actor=operator if action.startswith("operator:") else "system",
                action=action,
                state=state.value,
                details=payload,
            )
            audit_log.append(event)
            record["audit_log"] = [asdict(item) for item in audit_log]
            self._write_json(job_path / "job_record.json", record)

        try:
            raw_text = route_extraction(input_path)
            raw_text_path = job_path / "raw_ocr_text.txt"
            raw_text_path.write_text(raw_text, encoding="utf-8")
            record["artifacts"]["raw_ocr_text"] = str(raw_text_path)
            transition(InvoiceJobState.INGESTED, "system:invoice_ingested")

            extraction_result = extract_structured_invoice(raw_text)
            if extraction_result.get("status") != "success":
                raise RuntimeError(extraction_result.get("error", {}).get("message", "Extraction failed"))

            extracted_json_path = job_path / "extracted_invoice.json"
            self._write_json(extracted_json_path, extraction_result)
            record["artifacts"]["extracted_json"] = str(extracted_json_path)
            transition(
                InvoiceJobState.EXTRACTED,
                "system:invoice_extracted",
                {"confidence": extraction_result.get("confidence", {}).get("overall", 0.0)},
            )

            normalization = run_normalization_pipeline(
                extraction_result["data"], allow_critical_override=allow_accounting_override
            )
            normalized_payload = to_mutable_invoice(normalization.normalized)
            normalized_json_path = job_path / "normalized_invoice.json"
            self._write_json(normalized_json_path, normalized_payload)
            record["artifacts"]["normalized_json"] = str(normalized_json_path)

            validation_report_path = job_path / "validation_report.json"
            report_payload = {
                "warnings": list(normalization.report.warnings),
                "errors": list(normalization.report.errors),
                "confidence_flags": dict(normalization.report.confidence_flags),
                "critical_failure": normalization.report.critical_failure,
            }
            self._write_json(validation_report_path, report_payload)
            record["artifacts"]["validation_report"] = str(validation_report_path)
            transition(InvoiceJobState.VALIDATED, "system:invoice_validated", report_payload)

            extraction_confidence = extraction_result.get("confidence", {}).get("overall", 0.0)
            if extraction_confidence < self.low_confidence_threshold or normalization.report.critical_failure:
                queue_payload = {
                    "job_id": job_id,
                    "invoice_number": normalized_payload.get("invoice_number"),
                    "confidence": extraction_confidence,
                    "critical_failure": normalization.report.critical_failure,
                    "reason": "low_confidence" if extraction_confidence < self.low_confidence_threshold else "validation_failed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._append_jsonl(self.review_queue_path, queue_payload)
                record["review_queue_entry"] = queue_payload
                transition(InvoiceJobState.REVIEW_REQUIRED, "system:routed_to_manual_review", queue_payload)
                return record

            idempotency_key = self._build_idempotency_key(normalized_payload)
            record["idempotency_key"] = idempotency_key
            idempotency_store = self._read_json(self.idempotency_store_path, default={})

            if idempotency_key in idempotency_store:
                response = {
                    "status": "duplicate",
                    "message": "Invoice already posted to Tally. Reusing prior response.",
                    "posted_at": idempotency_store[idempotency_key].get("posted_at"),
                    "response": idempotency_store[idempotency_key].get("response", {}),
                }
                upload_response_path = job_path / "upload_response.json"
                self._write_json(upload_response_path, response)
                record["artifacts"]["upload_response"] = str(upload_response_path)
                transition(InvoiceJobState.POSTED, "system:duplicate_post_prevented", response)
                return record

            xml_path = job_path / "tally_invoice.xml"
            generate_tally_xml(normalized_payload, str(xml_path))
            record["artifacts"]["generated_xml"] = str(xml_path)

            upload_response = {
                "status": "success",
                "voucher_number": normalized_payload.get("invoice_number"),
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "idempotency_key": idempotency_key,
            }
            upload_response_path = job_path / "upload_response.json"
            self._write_json(upload_response_path, upload_response)
            record["artifacts"]["upload_response"] = str(upload_response_path)

            idempotency_store[idempotency_key] = {
                "job_id": job_id,
                "posted_at": upload_response["posted_at"],
                "response": upload_response,
            }
            self._write_json(self.idempotency_store_path, idempotency_store)

            transition(InvoiceJobState.POSTED, "system:posted_to_tally", upload_response)
            return record

        except (IngestionError, RuntimeError, ValueError) as exc:
            transition(InvoiceJobState.FAILED, "system:processing_failed", {"error": str(exc)})
            record["error"] = str(exc)
            return record

    @staticmethod
    def _build_idempotency_key(invoice: Dict[str, Any]) -> str:
        seed = "|".join(
            [
                str(invoice.get("invoice_number", "")).strip(),
                str(invoice.get("invoice_date", "")).strip(),
                str(invoice.get("total", "")).strip(),
                str(invoice.get("seller", "")).strip(),
                str(invoice.get("buyer", "")).strip(),
            ]
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
