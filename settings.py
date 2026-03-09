import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    tesseract_cmd: Optional[str] = None
    poppler_path: Optional[str] = None
    ocr_language: Optional[str] = None
    ocr_tenant_language_overrides: dict[str, str] | None = None
    ocr_preprocess_deskew: bool = False
    ocr_preprocess_binarization: bool = False
    ocr_preprocess_contrast_enhancement: bool = False
    tally_host: str = "localhost"
    tally_port: int = 9000
    tally_company: Optional[str] = None
    tally_voucher_type: str = "Sales"
    tally_voucher_action: str = "Create"
    tally_timeout_seconds: float = 15.0
    tally_max_retries: int = 3
    tally_retry_backoff_seconds: float = 1.0
    ocr_timeout_seconds: float = 30.0
    ocr_max_pages: int = 20


def _parse_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_json_mapping(name: str) -> dict[str, str]:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items() if value}


def load_settings() -> Settings:
    """Load runtime configuration from environment variables."""
    return Settings(
        tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
        poppler_path=os.getenv("POPPLER_PATH") or None,
        ocr_language=os.getenv("OCR_LANGUAGE") or None,
        ocr_tenant_language_overrides=_parse_json_mapping("OCR_TENANT_LANGUAGE_OVERRIDES"),
        ocr_preprocess_deskew=_parse_bool("OCR_PREPROCESS_DESKEW"),
        ocr_preprocess_binarization=_parse_bool("OCR_PREPROCESS_BINARIZATION"),
        ocr_preprocess_contrast_enhancement=_parse_bool("OCR_PREPROCESS_CONTRAST_ENHANCEMENT"),
        tally_host=os.getenv("TALLY_HOST", "localhost"),
        tally_port=_parse_int("TALLY_PORT", 9000),
        tally_company=os.getenv("TALLY_COMPANY") or None,
        tally_voucher_type=os.getenv("TALLY_VOUCHER_TYPE", "Sales"),
        tally_voucher_action=os.getenv("TALLY_VOUCHER_ACTION", "Create"),
        tally_timeout_seconds=_parse_float("TALLY_TIMEOUT_SECONDS", 15.0),
        tally_max_retries=_parse_int("TALLY_MAX_RETRIES", 3),
        tally_retry_backoff_seconds=_parse_float("TALLY_RETRY_BACKOFF_SECONDS", 1.0),
        ocr_timeout_seconds=_parse_float("OCR_TIMEOUT_SECONDS", 30.0),
        ocr_max_pages=_parse_int("OCR_MAX_PAGES", 20),
    )


SETTINGS = load_settings()
