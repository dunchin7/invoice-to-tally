import os
import shutil
from typing import Dict

from pdf2image import convert_from_path
from PIL import Image
import pytesseract

from settings import SETTINGS


_tesseract_runtime_validated = False
_pdf_runtime_validated = False


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


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from an image file using Tesseract OCR.
    """
    _ensure_tesseract_available()
    image = Image.open(image_path)
    return pytesseract.image_to_string(image)


def extract_text_from_pdf(pdf_path: str) -> str:
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
    return "\n".join(pytesseract.image_to_string(page) for page in pages)


def extract_text(file_path: str) -> str:
    """
    Detect file type and route to appropriate OCR method.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        return extract_text_from_image(file_path)

    if ext == ".pdf":
        return extract_text_from_pdf(file_path)

    raise ValueError(f"Unsupported file type: {ext}")
