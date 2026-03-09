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
from tally.master_data import TallyMasterDataClient, load_master_data_from_file
from tally.xml_generator import generate_tally_xml
from validation.errors import (
    AccountingValidationError,
    FieldNormalizationError,
    SchemaValidationError,
    ValidationFlowError,
)
from validation.pipeline import run_normalization_pipeline, to_mutable_invoice
from validation.pre_import import MappingRuleStore, PreImportResolver


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
        tenant_id: str = "default",
        master_data_file: str = "",
        tally_base_url: str = "http://localhost:9000",
        mapping_rules_file: str = "validation/config/mapping_rules.json",
        mapping_rules_db: str = "",
        fallback_policy: dict[str, str] | None = None,
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
            transition(InvoiceJobState.INGESTED, "operator:submitted_invoice", {"input_path": str(input_path)})
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

            if master_data_file:
                master_data = load_master_data_from_file(master_data_file)
            else:
                master_client = TallyMasterDataClient(base_url=tally_base_url)
                master_data = master_client.get_master_data()

            resolver = PreImportResolver(
                master_data=master_data,
                rule_store=MappingRuleStore(json_path=mapping_rules_file, sqlite_path=mapping_rules_db or None),
                fallback_policy=fallback_policy,
            )
            preimport_report = resolver.resolve_invoice(normalized_payload, tenant_id=tenant_id)
            resolved_payload = preimport_report.invoice

            normalized_json_path = job_path / "normalized_invoice.json"
            self._write_json(normalized_json_path, resolved_payload)
            record["artifacts"]["normalized_json"] = str(normalized_json_path)

            reconciliation_payload = {
                "blocking": preimport_report.blocking,
                "resolutions": [resolution.__dict__ for resolution in preimport_report.resolutions],
                "issues": [issue.__dict__ for issue in preimport_report.issues],
            }

            validation_report_path = job_path / "validation_report.json"
            report_payload = {
                "warnings": list(normalization.report.warnings),
                "errors": list(normalization.report.errors),
                "confidence_flags": dict(normalization.report.confidence_flags),
                "critical_failure": normalization.report.critical_failure,
                "master_data_source": master_data.source,
                "reconciliation": reconciliation_payload,
            }
            self._write_json(validation_report_path, report_payload)
            record["artifacts"]["validation_report"] = str(validation_report_path)
            transition(InvoiceJobState.VALIDATED, "system:invoice_validated", report_payload)

            manual_review_reasons = [issue.__dict__ for issue in preimport_report.issues if issue.action == "manual_review"]
            extraction_confidence = extraction_result.get("confidence", {}).get("overall", 0.0)

            if preimport_report.blocking:
                queue_payload = {
                    "job_id": job_id,
                    "invoice_number": resolved_payload.get("invoice_number"),
                    "confidence": extraction_confidence,
                    "critical_failure": normalization.report.critical_failure,
                    "reason": "validation_failed",
                    "reconciliation_issues": [issue.__dict__ for issue in preimport_report.issues],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._append_jsonl(self.review_queue_path, queue_payload)
                record["review_queue_entry"] = queue_payload
                transition(InvoiceJobState.REVIEW_REQUIRED, "system:routed_to_manual_review", queue_payload)
                return record

            if (
                extraction_confidence < self.low_confidence_threshold
                or normalization.report.critical_failure
                or manual_review_reasons
            ):
                queue_payload = {
                    "job_id": job_id,
                    "invoice_number": resolved_payload.get("invoice_number"),
                    "confidence": extraction_confidence,
                    "critical_failure": normalization.report.critical_failure,
                    "reason": "manual_review_required"
                    if manual_review_reasons
                    else (
                        "low_confidence"
                        if extraction_confidence < self.low_confidence_threshold
                        else "validation_failed"
                    ),
                    "reconciliation_issues": manual_review_reasons,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._append_jsonl(self.review_queue_path, queue_payload)
                record["review_queue_entry"] = queue_payload
                transition(InvoiceJobState.REVIEW_REQUIRED, "system:routed_to_manual_review", queue_payload)
                return record

            idempotency_key = self._build_idempotency_key(resolved_payload)
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
            generate_tally_xml(resolved_payload, str(xml_path))
            record["artifacts"]["generated_xml"] = str(xml_path)

            upload_response = {
                "status": "success",
                "voucher_number": resolved_payload.get("invoice_number"),
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

        except (SchemaValidationError, FieldNormalizationError) as exc:
            details = {"error": str(exc), "error_code": exc.code, "error_context": exc.context}
            transition(InvoiceJobState.FAILED, "system:validation_schema_failed", details)
            record["error"] = str(exc)
            record["error_code"] = exc.code
            record["error_context"] = exc.context
            return record
        except AccountingValidationError as exc:
            queue_payload = {
                "job_id": job_id,
                "invoice_number": None,
                "confidence": None,
                "critical_failure": True,
                "reason": "validation_failed",
                "error_code": exc.code,
                "error_context": exc.context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._append_jsonl(self.review_queue_path, queue_payload)
            record["review_queue_entry"] = queue_payload
            transition(InvoiceJobState.REVIEW_REQUIRED, "system:accounting_validation_failed", queue_payload)
            record["error"] = str(exc)
            record["error_code"] = exc.code
            record["error_context"] = exc.context
            return record
        except ValidationFlowError as exc:
            details = {"error": str(exc), "error_code": exc.code, "error_context": exc.context}
            transition(InvoiceJobState.FAILED, "system:validation_failed", details)
            record["error"] = str(exc)
            record["error_code"] = exc.code
            record["error_context"] = exc.context
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
