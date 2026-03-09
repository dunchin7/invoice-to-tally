import os
import shutil
from dataclasses import dataclass
from typing import Any, Dict

from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageOps
import pytesseract

from settings import SETTINGS


_tesseract_runtime_validated = False
_pdf_runtime_validated = False


@dataclass(frozen=True)
class OCRConfig:
    preprocess_deskew: bool = False
    preprocess_binarization: bool = False
    preprocess_contrast_enhancement: bool = False
    language: str | None = None


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


def resolve_ocr_config(tenant_id: str = "default") -> OCRConfig:
    tenant_overrides = SETTINGS.ocr_tenant_language_overrides or {}
    language = tenant_overrides.get(tenant_id) or SETTINGS.ocr_language
    return OCRConfig(
        preprocess_deskew=SETTINGS.ocr_preprocess_deskew,
        preprocess_binarization=SETTINGS.ocr_preprocess_binarization,
        preprocess_contrast_enhancement=SETTINGS.ocr_preprocess_contrast_enhancement,
        language=language,
    )


def _deskew_image(image: Image.Image) -> Image.Image:
    # Lightweight deterministic deskew approximation using nearest 90° orientation.
    return ImageOps.exif_transpose(image)


def _binarize_image(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda px: 255 if px > 128 else 0, mode="1")


def _enhance_contrast(image: Image.Image) -> Image.Image:
    return ImageEnhance.Contrast(image).enhance(1.5)


def _apply_preprocessing(image: Image.Image, config: OCRConfig) -> tuple[Image.Image, list[str]]:
    processed = image
    applied_steps: list[str] = []

    if config.preprocess_deskew:
        processed = _deskew_image(processed)
        applied_steps.append("deskew")

    if config.preprocess_binarization:
        processed = _binarize_image(processed)
        applied_steps.append("binarization")

    if config.preprocess_contrast_enhancement:
        processed = _enhance_contrast(processed)
        applied_steps.append("contrast_enhancement")

    return processed, applied_steps


def _ocr_image(image: Image.Image, config: OCRConfig) -> tuple[str, Dict[str, Any]]:
    processed_image, applied_steps = _apply_preprocessing(image, config)
    if config.language:
        text = pytesseract.image_to_string(processed_image, lang=config.language)
    else:
        text = pytesseract.image_to_string(processed_image)

    return text, {
        "preprocessing_steps": applied_steps,
        "language": config.language,
    }


def extract_text_from_image(image_path: str, config: OCRConfig | None = None) -> tuple[str, Dict[str, Any]]:
    """
    Extract text from an image file using Tesseract OCR.
    """
    _ensure_tesseract_available()
    image = Image.open(image_path)
    effective_config = config or resolve_ocr_config()
    text, diagnostics = _ocr_image(image, effective_config)
    diagnostics.update({"source": "image", "page_count": 1})
    return text, diagnostics


def extract_text_from_pdf(pdf_path: str, config: OCRConfig | None = None) -> tuple[str, Dict[str, Any]]:
    """
    Convert PDF pages to images and extract text from each page.
    Uses optional Poppler path when configured.
    """
    _ensure_tesseract_available()
    _ensure_pdf_runtime_available()

    convert_kwargs: Dict[str, str] = {}
    if SETTINGS.poppler_path:
        convert_kwargs["poppler_path"] = SETTINGS.poppler_path

    pages = convert_from_path(pdf_path, **convert_kwargs)
    effective_config = config or resolve_ocr_config()

    page_texts: list[str] = []
    applied_steps: list[str] = []
    for idx, page in enumerate(pages):
        text, page_diag = _ocr_image(page, effective_config)
        page_texts.append(text)
        if idx == 0:
            applied_steps = page_diag["preprocessing_steps"]

    return "\n".join(page_texts), {
        "source": "pdf",
        "page_count": len(pages),
        "preprocessing_steps": applied_steps,
        "language": effective_config.language,
    }


def extract_text_with_diagnostics(file_path: str, tenant_id: str = "default") -> tuple[str, Dict[str, Any]]:
    """Detect file type, run OCR, and return extracted text with OCR diagnostics."""
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
