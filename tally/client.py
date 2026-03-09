from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List
from xml.etree import ElementTree

import requests


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

    def upload_xml(self, xml_body: str) -> TallyUploadStatus:
        endpoint = self._config.endpoint
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    data=xml_body.encode("utf-8"),
                    headers={"Content-Type": "application/xml; charset=utf-8"},
                    timeout=self._config.timeout_seconds,
                )
                response.raise_for_status()
                return parse_tally_response(response.text, endpoint=endpoint)
            except Exception as exc:
                last_error = exc
                if attempt >= self._config.max_retries or not _is_transient(exc):
                    break
                time.sleep(self._config.retry_backoff_seconds * (2**attempt))

        return TallyUploadStatus(
            ok=False,
            endpoint=endpoint,
            raw_response="",
            message=f"Failed to upload to Tally endpoint after retries: {last_error}",
        )
