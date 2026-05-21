"""OCR entrypoints for image/PDF extraction.

Canonical API surface:
- ``extract_text_with_diagnostics(file_path, tenant_id=...)`` for callers needing
  both OCR text and metadata (source, language, preprocessing steps).
- ``extract_text(file_path, tenant_id=...)`` as an alias returning the same
  tuple contract used by ingestion routing.
- ``extract_text_from_image`` / ``extract_text_from_pdf`` for low-level text-only
  OCR operations.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class OCRConfig:
    language: str | None
    preprocess_deskew: bool = False
    preprocess_binarization: bool = False
    preprocess_contrast_enhancement: bool = False


def resolve_ocr_config(tenant_id: str = "default") -> OCRConfig:
    overrides = SETTINGS.ocr_tenant_language_overrides or {}
    language = overrides.get(tenant_id) or SETTINGS.ocr_language
    return OCRConfig(
        language=language,
        preprocess_deskew=bool(getattr(SETTINGS, "ocr_preprocess_deskew", False)),
        preprocess_binarization=bool(getattr(SETTINGS, "ocr_preprocess_binarization", False)),
        preprocess_contrast_enhancement=bool(getattr(SETTINGS, "ocr_preprocess_contrast_enhancement", False)),
    )


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
        timeout_seconds = float(timeout_raw) if timeout_raw is not None else float(getattr(SETTINGS, "ocr_timeout_seconds", 30.0))
    except ValueError:
        timeout_seconds = float(getattr(SETTINGS, "ocr_timeout_seconds", 30.0))

    try:
        max_pages = int(max_pages_raw) if max_pages_raw is not None else int(getattr(SETTINGS, "ocr_max_pages", 20))
    except ValueError:
        max_pages = int(getattr(SETTINGS, "ocr_max_pages", 20))

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


def _deskew_image(image: Image.Image) -> Image.Image:
    """Detect and correct skew angle by maximising row-projection variance."""
    try:
        import numpy as np
    except ImportError:
        return image

    gray = image.convert("L")
    arr = np.array(gray, dtype=np.float32)
    # Invert so text pixels are bright
    if arr.mean() > 128:
        arr = 255.0 - arr
    threshold = arr.mean()
    binary = (arr > threshold).astype(np.float32) * 255.0
    binary_img = Image.fromarray(binary.astype(np.uint8))

    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-5.0, 5.1, 0.5):
        rotated = np.array(binary_img.rotate(float(angle), expand=False, fillcolor=0), dtype=np.float32)
        score = float(np.var(rotated.sum(axis=1)))
        if score > best_score:
            best_score = score
            best_angle = float(angle)

    if abs(best_angle) > 0.3:
        return image.rotate(best_angle, expand=True, fillcolor=255)
    return image


def _binarize_image(image: Image.Image) -> Image.Image:
    """Apply Otsu's thresholding to improve contrast for OCR."""
    try:
        import numpy as np
    except ImportError:
        from PIL import ImageOps
        return ImageOps.autocontrast(image.convert("L")).convert("RGB")

    gray = image.convert("L")
    arr = np.array(gray, dtype=np.int32)
    hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
    total = arr.size
    sum_total = float(np.dot(np.arange(256, dtype=np.float64), hist.astype(np.float64)))
    sum_b, weight_b, max_var, threshold = 0.0, 0, 0.0, 128
    for t in range(256):
        weight_b += int(hist[t])
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += float(t * int(hist[t]))
        mean_b = sum_b / weight_b
        mean_f = (sum_total - sum_b) / weight_f
        var = float(weight_b) * float(weight_f) * (mean_b - mean_f) ** 2
        if var > max_var:
            max_var = var
            threshold = t
    binary = gray.point(lambda x: 255 if x > threshold else 0)
    return binary.convert("RGB")


def _enhance_contrast(image: Image.Image) -> Image.Image:
    """Boost image contrast to improve OCR on faded or low-contrast scans."""
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(image).enhance(2.0)


def _prepare_image(image: Image.Image, config: OCRConfig) -> tuple[Image.Image, list[str]]:
    processed = image
    steps: list[str] = []

    if config.preprocess_deskew:
        processed = _deskew_image(processed)
        steps.append("deskew")
    if config.preprocess_binarization:
        processed = _binarize_image(processed)
        steps.append("binarization")
    if config.preprocess_contrast_enhancement:
        processed = _enhance_contrast(processed)
        steps.append("contrast_enhancement")

    return processed, steps


def _ocr_image(image: Image.Image, config: OCRConfig) -> tuple[str, list[str]]:
    prepared_image, steps = _prepare_image(image, config)
    ocr_kwargs: dict[str, str] = {}
    if config.language:
        ocr_kwargs["lang"] = config.language
    return pytesseract.image_to_string(prepared_image, **ocr_kwargs), steps


def extract_text_from_image(image_path: str, config: OCRConfig | None = None) -> str:
    """Extract text from an image file using Tesseract OCR."""
    _ensure_tesseract_available()
    limits = _load_limits()
    started_at = time.monotonic()
    resolved_config = config or resolve_ocr_config()

    image = Image.open(image_path)
    text, _steps = _ocr_image(image, resolved_config)

    _check_timeout(started_at=started_at, timeout_seconds=limits.timeout_seconds, processed_pages=1)
    return text


def extract_text_from_pdf(pdf_path: str, config: OCRConfig | None = None) -> str:
    """Convert PDF pages to images and extract text from each page."""
    _ensure_tesseract_available()
    _ensure_pdf_runtime_available()

    limits = _load_limits()
    started_at = time.monotonic()
    resolved_config = config or resolve_ocr_config()

    convert_kwargs: dict[str, str] = {}
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
        page_text, _steps = _ocr_image(page_image, resolved_config)
        text_parts.append(page_text)

    _check_timeout(
        started_at=started_at,
        timeout_seconds=limits.timeout_seconds,
        processed_pages=total_pages,
    )
    return "\n".join(text_parts)


def extract_text_with_diagnostics(file_path: str, tenant_id: str = "default") -> tuple[str, dict[str, Any]]:
    """Detect file type, execute OCR, and return text plus OCR diagnostics."""
    ext = os.path.splitext(file_path)[1].lower()
    config = resolve_ocr_config(tenant_id=tenant_id)

    diagnostics: dict[str, Any] = {
        "source": None,
        "preprocessing_steps": [],
        "language": config.language,
    }

    if ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        diagnostics["source"] = "ocr_image"
        if config.preprocess_deskew:
            diagnostics["preprocessing_steps"].append("deskew")
        if config.preprocess_binarization:
            diagnostics["preprocessing_steps"].append("binarization")
        if config.preprocess_contrast_enhancement:
            diagnostics["preprocessing_steps"].append("contrast_enhancement")
        return extract_text_from_image(file_path, config=config), diagnostics

    if ext == ".pdf":
        diagnostics["source"] = "ocr_pdf"
        if config.preprocess_deskew:
            diagnostics["preprocessing_steps"].append("deskew")
        if config.preprocess_binarization:
            diagnostics["preprocessing_steps"].append("binarization")
        if config.preprocess_contrast_enhancement:
            diagnostics["preprocessing_steps"].append("contrast_enhancement")
        return extract_text_from_pdf(file_path, config=config), diagnostics

    raise ValueError(f"Unsupported file type: {ext}")


def extract_text(file_path: str, tenant_id: str = "default") -> tuple[str, dict[str, Any]]:
    """Compatibility entrypoint expected by ingestion.router."""
    return extract_text_with_diagnostics(file_path, tenant_id=tenant_id)
