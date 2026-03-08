from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from dotenv import load_dotenv

from llm.providers import GeminiProvider, LLMProvider

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
    transient_markers = [
        "timeout",
        "timed out",
        "rate limit",
        "too many requests",
        "service unavailable",
        "temporarily unavailable",
        "connection",
        "503",
        "429",
    ]
    return any(marker in message for marker in transient_markers)


def _run_with_retry(action: Callable[[], str], action_name: str) -> tuple[str, int, list[str]]:
    errors: list[str] = []

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return action(), attempt, errors
        except Exception as exc:
            err = f"{action_name} attempt {attempt} failed: {exc}"
            errors.append(err)
            if attempt >= RETRY_ATTEMPTS or not _is_transient_error(exc):
                raise
            sleep_seconds = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)

    raise RuntimeError(f"Retry loop exhausted for {action_name}")


def _parse_json_strict(payload: str) -> dict[str, Any]:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Top-level JSON value must be an object", payload, 0)
    return parsed


def _compute_confidence(data: dict[str, Any]) -> dict[str, Any]:
    checks = [
        data.get("invoice_number"),
        data.get("invoice_date"),
        data.get("subtotal"),
        data.get("taxes"),
        data.get("total"),
        data.get("currency"),
        data.get("seller", {}).get("name") if isinstance(data.get("seller"), dict) else "",
        data.get("buyer", {}).get("name") if isinstance(data.get("buyer"), dict) else "",
    ]
    present = sum(1 for item in checks if isinstance(item, str) and item.strip())
    total = len(checks)
    line_items = data.get("line_items")
    if isinstance(line_items, list) and line_items:
        present += 1
    total += 1

    overall = round(present / total, 3) if total else 0.0
    return {
        "overall": overall,
        "method": "heuristic_completeness",
        "fields_present": present,
        "fields_total": total,
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
            diagnostics["parse_strategy"] = "strict_json"
            return {
                "status": "success",
                "data": data,
                "confidence": confidence,
                "diagnostics": {
                    **diagnostics,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            }
        except json.JSONDecodeError as strict_error:
            diagnostics["errors"].append(f"strict_parse_failed: {strict_error}")
            diagnostics["parse_strategy"] = "repair_pass"

            repaired_response, repair_attempts, repair_errors = _run_with_retry(
                lambda: selected_provider.repair_json(raw_text, cleaned, str(strict_error)),
                "repair",
            )
            diagnostics["attempts"]["repair"] = repair_attempts
            diagnostics["errors"].extend(repair_errors)

            repaired_cleaned = _clean_model_output(repaired_response)
            try:
                repaired_data = _parse_json_strict(repaired_cleaned)
                confidence = _compute_confidence(repaired_data)
                diagnostics["parse_strategy"] = "repaired_json"
                return {
                    "status": "success",
                    "data": repaired_data,
                    "confidence": confidence,
                    "diagnostics": {
                        **diagnostics,
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                }
            except json.JSONDecodeError as repaired_error:
                diagnostics["errors"].append(f"repair_parse_failed: {repaired_error}")
                diagnostics["parse_strategy"] = "failed"
                return {
                    "status": "error",
                    "error": {
                        "code": "JSON_REPAIR_FAILED",
                        "message": "Failed to parse model output as JSON after repair pass",
                        "raw_response_excerpt": repaired_cleaned[:500],
                    },
                    "data": None,
                    "confidence": {
                        "overall": 0.0,
                        "method": "heuristic_completeness",
                        "fields_present": 0,
                        "fields_total": 0,
                    },
                    "diagnostics": {
                        **diagnostics,
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                }

    except Exception as exc:
        diagnostics["errors"].append(f"provider_failure: {exc}")
        diagnostics["parse_strategy"] = "failed"
        return {
            "status": "error",
            "error": {
                "code": "PROVIDER_FAILURE",
                "message": str(exc),
            },
            "data": None,
            "confidence": {
                "overall": 0.0,
                "method": "heuristic_completeness",
                "fields_present": 0,
                "fields_total": 0,
            },
            "diagnostics": {
                **diagnostics,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        }


def extract_invoice_fields(raw_text: str) -> dict[str, Any]:
    """Backward-compatible helper for callers expecting only extracted data."""
    result = extract_structured_invoice(raw_text)
    if result.get("status") != "success":
        message = result.get("error", {}).get("message", "Unknown extraction error")
        raise RuntimeError(message)
    return result["data"]
