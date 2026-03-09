from __future__ import annotations

import time
import logging
import re
from dataclasses import dataclass
from typing import List
from uuid import uuid4
from xml.etree import ElementTree

import requests


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TallyClientConfig:
    host: str = "localhost"
    port: int = 9000
    company: str | None = None
    voucher_type: str = "Sales"
    voucher_action: str = "Create"
    timeout_seconds: float = 15.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class TallyUploadStatus:
    ok: bool
    endpoint: str
    created: int = 0
    altered: int = 0
    ignored: int = 0
    errors: int = 0
    line_errors: tuple[str, ...] = ()
    raw_response: str = ""
    message: str = ""
    request_id: str = ""


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in {408, 425, 429, 500, 502, 503, 504}
    return False


def _extract_int(root: ElementTree.Element, tag: str) -> int:
    node = root.find(f".//{tag}")
    if node is None or node.text is None:
        return 0
    try:
        return int(node.text.strip())
    except ValueError:
        return 0


def parse_tally_response(xml_body: str, endpoint: str) -> TallyUploadStatus:
    try:
        root = ElementTree.fromstring(xml_body)
    except ElementTree.ParseError as exc:
        return TallyUploadStatus(
            ok=False,
            endpoint=endpoint,
            raw_response=xml_body,
            message=f"Unable to parse Tally response XML: {exc}",
        )

    created = _extract_int(root, "CREATED")
    altered = _extract_int(root, "ALTERED")
    ignored = _extract_int(root, "IGNORED")
    errors = _extract_int(root, "ERRORS")
    line_errors: List[str] = []

    for line_error in root.findall(".//LINEERROR"):
        if line_error.text and line_error.text.strip():
            line_errors.append(line_error.text.strip())

    ok = errors == 0 and len(line_errors) == 0
    message = (
        f"Imported successfully (created={created}, altered={altered}, ignored={ignored})."
        if ok
        else ("Import failed. " + "; ".join(line_errors) if line_errors else "Import failed with Tally errors.")
    )

    return TallyUploadStatus(
        ok=ok,
        endpoint=endpoint,
        created=created,
        altered=altered,
        ignored=ignored,
        errors=errors,
        line_errors=tuple(line_errors),
        raw_response=xml_body,
        message=message,
    )


class TallyClient:
    def __init__(self, config: TallyClientConfig):
        self._config = config

    @property
    def endpoint(self) -> str:
        return self._config.endpoint

    @staticmethod
    def _redact_xml_payload(xml_body: str) -> str:
        redacted = re.sub(r">([^<]+)<", r">***<", xml_body)
        return redacted[:300]

    def upload_xml(self, xml_body: str, idempotency_key: str, request_id: str | None = None) -> TallyUploadStatus:
        endpoint = self._config.endpoint
        last_error: Exception | None = None
        request_id = request_id or str(uuid4())
        redacted_payload_preview = self._redact_xml_payload(xml_body)

        for attempt in range(self._config.max_retries + 1):
            started_at = time.monotonic()
            try:
                response = requests.post(
                    endpoint,
                    data=xml_body.encode("utf-8"),
                    headers={"Content-Type": "application/xml; charset=utf-8"},
                    timeout=self._config.timeout_seconds,
                )
                response.raise_for_status()
                parsed = parse_tally_response(response.text, endpoint=endpoint)
                parsed_status = "ok" if parsed.ok else "tally_error"
                LOGGER.info(
                    "tally_upload_attempt",
                    extra={
                        "request_id": request_id,
                        "idempotency_key": idempotency_key,
                        "attempt_number": attempt + 1,
                        "endpoint": endpoint,
                        "latency_ms": round((time.monotonic() - started_at) * 1000, 3),
                        "parsed_status": parsed_status,
                        "error_class": None if parsed.ok else "tally_response_error",
                        "payload_preview": redacted_payload_preview,
                    },
                )
                return TallyUploadStatus(**{**parsed.__dict__, "request_id": request_id})
            except Exception as exc:
                last_error = exc
                error_class = exc.__class__.__name__
                LOGGER.info(
                    "tally_upload_attempt",
                    extra={
                        "request_id": request_id,
                        "idempotency_key": idempotency_key,
                        "attempt_number": attempt + 1,
                        "endpoint": endpoint,
                        "latency_ms": round((time.monotonic() - started_at) * 1000, 3),
                        "parsed_status": "transport_error",
                        "error_class": error_class,
                        "payload_preview": redacted_payload_preview,
                    },
                )
                if attempt >= self._config.max_retries or not _is_transient(exc):
                    break
                time.sleep(self._config.retry_backoff_seconds * (2**attempt))

        return TallyUploadStatus(
            ok=False,
            endpoint=endpoint,
            raw_response="",
            message=f"Failed to upload to Tally endpoint after retries: {last_error}",
            request_id=request_id,
        )
