import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict

from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import Image
import pytesseract

from settings import SETTINGS


_tesseract_runtime_validated = False
_pdf_runtime_validated = False


class OCRLimitExceededError(RuntimeError):
    """Raised when OCR execution exceeds configured operational limits."""

    def __init__(self, message: str, *, code: str, context: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.context = context or {}


@dataclass(frozen=True)
class OCRExecutionLimits:
    timeout_seconds: float
    max_pages: int


def _resolve_command(binary_name: str, configured_path: str | None) -> str | None:
    """Resolve a command from explicit config or system PATH."""
    if configured_path:
        return configured_path if os.path.isfile(configured_path) else None
    return shutil.which(binary_name)


def _ensure_tesseract_available() -> None:
    """Validate Tesseract only (used for image and PDF OCR text recognition)."""
    global _tesseract_runtime_validated
    if _tesseract_runtime_validated:
        return

    tesseract_cmd = _resolve_command("tesseract", SETTINGS.tesseract_cmd)
    if not tesseract_cmd:
        source = (
            f"configured TESSERACT_CMD='{SETTINGS.tesseract_cmd}'"
            if SETTINGS.tesseract_cmd
            else "system PATH"
        )
        raise RuntimeError(
            "OCR runtime validation failed. Missing dependencies:\n"
            f"- Tesseract binary not found via {source}.\n\n"
            "Tesseract is required to perform OCR text extraction. "
            "Install it and/or set TESSERACT_CMD."
        )

    if SETTINGS.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = SETTINGS.tesseract_cmd

    _tesseract_runtime_validated = True


def _ensure_pdf_runtime_available() -> None:
    """Validate PDF conversion requirements (Poppler) only for PDF inputs."""
    global _pdf_runtime_validated
    if _pdf_runtime_validated:
        return

    if SETTINGS.poppler_path:
        if not os.path.isdir(SETTINGS.poppler_path):
            raise RuntimeError(
                "OCR runtime validation failed. Missing dependencies:\n"
                f"- Poppler directory not found at POPPLER_PATH='{SETTINGS.poppler_path}'.\n\n"
                "Poppler's pdftoppm is required for PDF-to-image conversion. "
                "Fix POPPLER_PATH or install Poppler into PATH."
            )
    elif shutil.which("pdftoppm") is None:
        raise RuntimeError(
            "OCR runtime validation failed. Missing dependencies:\n"
            "- Poppler utility 'pdftoppm' not found in system PATH.\n\n"
            "Poppler is required only for PDF inputs. Install it or set POPPLER_PATH."
        )

    _pdf_runtime_validated = True


def _load_limits() -> OCRExecutionLimits:
    timeout_raw = os.getenv("OCR_TIMEOUT_SECONDS")
    max_pages_raw = os.getenv("OCR_MAX_PAGES")

    try:
        timeout_seconds = float(timeout_raw) if timeout_raw is not None else float(SETTINGS.ocr_timeout_seconds)
    except ValueError:
        timeout_seconds = float(SETTINGS.ocr_timeout_seconds)

    try:
        max_pages = int(max_pages_raw) if max_pages_raw is not None else int(SETTINGS.ocr_max_pages)
    except ValueError:
        max_pages = int(SETTINGS.ocr_max_pages)

    timeout_seconds = max(timeout_seconds, 0.0)
    max_pages = max(max_pages, 1)
    return OCRExecutionLimits(timeout_seconds=timeout_seconds, max_pages=max_pages)


def _check_timeout(*, started_at: float, timeout_seconds: float, processed_pages: int) -> None:
    if timeout_seconds <= 0:
        return
    elapsed = time.monotonic() - started_at
    if elapsed > timeout_seconds:
        raise OCRLimitExceededError(
            "OCR processing timed out before completion.",
            code="OCR_TIMEOUT",
            context={
                "ocr_timeout_seconds": timeout_seconds,
                "elapsed_seconds": round(elapsed, 3),
                "processed_pages": processed_pages,
            },
        )


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from an image file using Tesseract OCR.
    """
    _ensure_tesseract_available()
    limits = _load_limits()
    started_at = time.monotonic()

    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)

    _check_timeout(started_at=started_at, timeout_seconds=limits.timeout_seconds, processed_pages=1)
    return text


def extract_text_from_pdf(pdf_path: str, config: OCRConfig | None = None) -> tuple[str, Dict[str, Any]]:
    """
    Convert PDF pages to images and extract text from each page.
    Uses optional Poppler path when configured.
    """
    _ensure_tesseract_available()
    _ensure_pdf_runtime_available()

    limits = _load_limits()
    started_at = time.monotonic()

    convert_kwargs: Dict[str, str] = {}
    if SETTINGS.poppler_path:
        convert_kwargs["poppler_path"] = SETTINGS.poppler_path

    page_info = pdfinfo_from_path(pdf_path, **convert_kwargs)
    total_pages = int(page_info.get("Pages", 0))
    if total_pages > limits.max_pages:
        raise OCRLimitExceededError(
            "Input PDF exceeds configured page limit for OCR.",
            code="OCR_PAGE_LIMIT_EXCEEDED",
            context={
                "ocr_max_pages": limits.max_pages,
                "detected_pages": total_pages,
            },
        )

    text_parts: list[str] = []
    for page_number in range(1, total_pages + 1):
        _check_timeout(
            started_at=started_at,
            timeout_seconds=limits.timeout_seconds,
            processed_pages=page_number - 1,
        )

        page_image = convert_from_path(
            pdf_path,
            first_page=page_number,
            last_page=page_number,
            **convert_kwargs,
        )[0]
        text_parts.append(pytesseract.image_to_string(page_image))

    _check_timeout(
        started_at=started_at,
        timeout_seconds=limits.timeout_seconds,
        processed_pages=total_pages,
    )
    return "\n".join(text_parts)


def extract_text(file_path: str) -> str:
    """
    Detect file type and route to appropriate OCR method.
    """
    ext = os.path.splitext(file_path)[1].lower()
    config = resolve_ocr_config(tenant_id=tenant_id)

    if ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        return extract_text_from_image(file_path, config=config)

    if ext == ".pdf":
        return extract_text_from_pdf(file_path, config=config)

    raise ValueError(f"Unsupported file type: {ext}")


def extract_text(file_path: str, tenant_id: str = "default") -> str:
    """
    Detect file type and route to appropriate OCR method.
    """
    text, _ = extract_text_with_diagnostics(file_path, tenant_id=tenant_id)
    return text
