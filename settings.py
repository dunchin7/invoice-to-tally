import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    tesseract_cmd: Optional[str] = None
    poppler_path: Optional[str] = None



def load_settings() -> Settings:
    """Load runtime configuration from environment variables."""
    return Settings(
        tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
        poppler_path=os.getenv("POPPLER_PATH") or None,
    )


SETTINGS = load_settings()
