from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from dotenv import load_dotenv
from jsonschema import ValidationError, validate

from llm.providers import GeminiProvider, LLMProvider
from schema.invoice_schema import invoice_schema

load_dotenv()

RETRY_ATTEMPTS = int(os.getenv("EXTRACT_RETRY_ATTEMPTS", "3"))
RETRY_BASE_DELAY_SECONDS = float(os.getenv("EXTRACT_RETRY_BASE_DELAY_SECONDS", "1.0"))


def _clean_model_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
        text = re.sub(r"```$", "", text.strip())
    return text.strip()


def _is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "timeout",
            "timed out",
            "rate limit",
            "too many requests",
            "service unavailable",
            "temporarily unavailable",
            "connection",
            "503",
            "429",
        )
    )


def _run_with_retry(action: Callable[[], str], action_name: str) -> tuple[str, int, list[str]]:
    errors: list[str] = []
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return action(), attempt, errors
        except Exception as exc:
            errors.append(f"{action_name} attempt {attempt} failed: {exc}")
            if attempt >= RETRY_ATTEMPTS or not _is_transient_error(exc):
                raise
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    raise RuntimeError(f"Retry loop exhausted for {action_name}")


def _parse_json_strict(payload: str) -> dict[str, Any]:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Top-level JSON value must be an object", payload, 0)
    return parsed


def _compute_completeness_score(data: dict[str, Any]) -> tuple[float, int, int, dict[str, bool]]:
    def _is_numeric_string(value: str) -> bool:
        return bool(re.fullmatch(r"[+-]?(?:\d+\.?\d*|\d*\.\d+)", value.strip()))

    def _is_present(
        value: Any,
        *,
        allow_numeric: bool = False,
        allow_collection: bool = False,
        allow_numeric_string: bool = False,
    ) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return False
            return _is_numeric_string(cleaned) if allow_numeric_string else True
        if isinstance(value, (int, float)):
            return allow_numeric
        if allow_collection and isinstance(value, (dict, list, tuple)):
            return bool(value)
        return False

    line_items = data.get("line_items")
    has_line_items = _is_present(line_items, allow_collection=True)
    has_line_item_totals = isinstance(line_items, list) and any(
        _is_present(item.get("total_price") if isinstance(item, dict) else None, allow_numeric=True, allow_numeric_string=True)
        or _is_present(item.get("taxable_value") if isinstance(item, dict) else None, allow_numeric=True, allow_numeric_string=True)
        or _is_present(item.get("tax_amount") if isinstance(item, dict) else None, allow_numeric=True, allow_numeric_string=True)
        for item in line_items
    )

    inputs = {
        "invoice_number": _is_present(data.get("invoice_number")),
        "invoice_date": _is_present(data.get("invoice_date")),
        "subtotal": _is_present(data.get("subtotal"), allow_numeric=True, allow_numeric_string=True),
        "tax": _is_present(data.get("tax"), allow_numeric=True, allow_numeric_string=True)
        or _is_present(data.get("taxes"), allow_numeric=True, allow_numeric_string=True),
        "total": _is_present(data.get("total"), allow_numeric=True, allow_numeric_string=True),
        "currency": _is_present(data.get("currency")),
        "seller": _is_present(data.get("seller"), allow_collection=True),
        "buyer": _is_present(data.get("buyer"), allow_collection=True),
        "line_items": has_line_items,
        "line_item_totals": has_line_item_totals,
    }

    present = sum(1 for ok in inputs.values() if ok)
    total = len(inputs)
    return (round(present / total, 3) if total else 0.0), present, total, inputs


def _compute_schema_valid_score(data: dict[str, Any]) -> tuple[float, bool]:
    try:
        validate(instance=data, schema=invoice_schema)
        return 1.0, True
    except ValidationError:
        return 0.0, False


def _compute_accounting_consistency_score(data: dict[str, Any], tolerance: float = 0.05) -> float:
    subtotal = data.get("subtotal")
    tax = data.get("tax")
    total = data.get("total")
    if not all(isinstance(value, (int, float)) for value in (subtotal, tax, total)):
        return 0.0
    return 1.0 if abs((float(subtotal) + float(tax)) - float(total)) <= tolerance else 0.0


def _compute_confidence(
    data: dict[str, Any],
    *,
    repair_attempted: bool = False,
    repair_succeeded: bool = False,
) -> dict[str, Any]:
    completeness_score, fields_present, fields_total, inputs = _compute_completeness_score(data)
    schema_valid_score, schema_valid = _compute_schema_valid_score(data)
    accounting_consistency_score = _compute_accounting_consistency_score(data)
    overall = round((0.5 * completeness_score) + (0.25 * schema_valid_score) + (0.25 * accounting_consistency_score), 3)
    return {
        "overall": overall,
        "method": "weighted_components_v2",
        "fields_present": fields_present,
        "fields_total": fields_total,
        "completeness_score": completeness_score,
        "schema_valid_score": schema_valid_score,
        "schema_valid": schema_valid,
        "accounting_consistency_score": accounting_consistency_score,
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
        "inputs": inputs,
    }


def extract_structured_invoice(raw_text: str, provider: LLMProvider | None = None) -> dict[str, Any]:
    selected_provider = provider or GeminiProvider()
    diagnostics: dict[str, Any] = {
        "provider": selected_provider.name,
        "model": selected_provider.model_name,
        "attempts": {"extract": 0, "repair": 0},
        "parse_strategy": "strict_json",
        "errors": [],
    }
    started_at = time.perf_counter()

    try:
        raw_response, extract_attempts, extract_errors = _run_with_retry(
            lambda: selected_provider.extract_structured_invoice(raw_text),
            "extract",
        )
        diagnostics["attempts"]["extract"] = extract_attempts
        diagnostics["errors"].extend(extract_errors)
        cleaned = _clean_model_output(raw_response)

        try:
            data = _parse_json_strict(cleaned)
            confidence = _compute_confidence(data)
            return {
                "status": "success",
                "data": data,
                "confidence": confidence,
                "diagnostics": {**diagnostics, "confidence_inputs": confidence["inputs"], "latency_ms": round((time.perf_counter() - started_at) * 1000, 2)},
            }
        except json.JSONDecodeError as strict_error:
            diagnostics["errors"].append(f"strict_parse_failed: {strict_error}")
            repaired_response, repair_attempts, repair_errors = _run_with_retry(
                lambda: selected_provider.repair_json(raw_text, cleaned, str(strict_error)),
                "repair",
            )
            diagnostics["attempts"]["repair"] = repair_attempts
            diagnostics["errors"].extend(repair_errors)
            repaired_cleaned = _clean_model_output(repaired_response)
            repaired_data = _parse_json_strict(repaired_cleaned)
            confidence = _compute_confidence(repaired_data, repair_attempted=True, repair_succeeded=True)
            return {
                "status": "success",
                "data": repaired_data,
                "confidence": confidence,
                "diagnostics": {**diagnostics, "parse_strategy": "repaired_json", "confidence_inputs": confidence["inputs"], "latency_ms": round((time.perf_counter() - started_at) * 1000, 2)},
            }
    except Exception as exc:
        diagnostics["errors"].append(f"provider_failure: {exc}")
        return {
            "status": "error",
            "error": {"code": "PROVIDER_FAILURE", "message": str(exc)},
            "data": None,
            "confidence": {
                "overall": 0.0,
                "method": "weighted_components_v2",
                "fields_present": 0,
                "fields_total": 0,
                "completeness_score": 0.0,
                "schema_valid_score": 0.0,
                "schema_valid": False,
                "accounting_consistency_score": 0.0,
                "repair_attempted": diagnostics["attempts"]["repair"] > 0,
                "repair_succeeded": False,
                "inputs": {},
            },
            "diagnostics": {**diagnostics, "parse_strategy": "failed", "latency_ms": round((time.perf_counter() - started_at) * 1000, 2)},
        }
