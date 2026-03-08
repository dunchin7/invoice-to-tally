import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    tesseract_cmd: Optional[str] = None
    poppler_path: Optional[str] = None
    tally_host: str = "localhost"
    tally_port: int = 9000
    tally_company: Optional[str] = None
    tally_voucher_type: str = "Sales"
    tally_voucher_action: str = "Create"
    tally_timeout_seconds: float = 15.0
    tally_max_retries: int = 3
    tally_retry_backoff_seconds: float = 1.0


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


def load_settings() -> Settings:
    """Load runtime configuration from environment variables."""
    return Settings(
        tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
        poppler_path=os.getenv("POPPLER_PATH") or None,
        tally_host=os.getenv("TALLY_HOST", "localhost"),
        tally_port=_parse_int("TALLY_PORT", 9000),
        tally_company=os.getenv("TALLY_COMPANY") or None,
        tally_voucher_type=os.getenv("TALLY_VOUCHER_TYPE", "Sales"),
        tally_voucher_action=os.getenv("TALLY_VOUCHER_ACTION", "Create"),
        tally_timeout_seconds=_parse_float("TALLY_TIMEOUT_SECONDS", 15.0),
        tally_max_retries=_parse_int("TALLY_MAX_RETRIES", 3),
        tally_retry_backoff_seconds=_parse_float("TALLY_RETRY_BACKOFF_SECONDS", 1.0),
    )


SETTINGS = load_settings()
