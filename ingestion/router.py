import mimetypes
import os
from pathlib import Path
from typing import Any

from ocr.ocr_engine import extract_text, extract_text_with_diagnostics


class IngestionError(ValueError):
    """Raised when a file cannot be ingested using a supported strategy."""


_SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff"}
_SUPPORTED_WORD_EXTENSIONS = {".doc", ".docx"}


def _detect_file_type(file_path: str) -> tuple[str | None, str]:
    ext = Path(file_path).suffix.lower()
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type, ext


def _extract_pdf_text_layer(file_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise IngestionError(
            "Digital PDF text extraction requires the optional 'pypdf' package. "
            "Install dependencies from requirements.txt and retry."
        ) from exc

    reader = PdfReader(file_path)
    text_parts = []

    for page in reader.pages:
        text_parts.append(page.extract_text() or "")

    return "\n".join(text_parts).strip()


def _extract_docx_text(file_path: str) -> str:
    try:
        from docx import Document
    except ModuleNotFoundError as exc:
        raise IngestionError(
            "DOCX parsing requires the optional 'python-docx' package. "
            "Install dependencies from requirements.txt and retry."
        ) from exc

    doc = Document(file_path)
    lines = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
    return "\n".join(lines).strip()


def _extract_doc_text(file_path: str) -> str:
    try:
        import textract
    except ModuleNotFoundError as exc:
        raise IngestionError(
            "DOC parsing requires the optional 'textract' package. "
            "Install textract and antiword, or convert .doc files to .docx before running this command."
        ) from exc

    parsed = textract.process(file_path)
    text = parsed.decode("utf-8", errors="ignore").strip()

    if not text:
        raise IngestionError(
            "DOC file appears empty after parsing. "
            "Try converting the file to .docx or exporting as PDF and rerun the command."
        )

    return text


def route_extraction_with_diagnostics(file_path: str, tenant_id: str = "default") -> tuple[str, dict[str, Any]]:
    if not os.path.exists(file_path):
        raise IngestionError(
            f"Input file not found: {file_path}. "
            "Check the path and re-run with --input <path-to-invoice>."
        )

    mime_type, ext = _detect_file_type(file_path)

    if ext == ".pdf" or mime_type == "application/pdf":
        text_layer = _extract_pdf_text_layer(file_path)

        if text_layer.strip():
            print("[i] Detected digital PDF: using embedded text layer extraction.")
            return text_layer, {"source": "pdf_text_layer", "preprocessing_steps": [], "language": None}

        print("[i] Detected scanned PDF: no text layer found, running OCR pipeline.")
        return extract_text_with_diagnostics(file_path, tenant_id=tenant_id)

    if ext in _SUPPORTED_IMAGE_EXTENSIONS or (mime_type and mime_type.startswith("image/")):
        print("[i] Detected image invoice: routing to OCR pipeline.")
        return extract_text_with_diagnostics(file_path, tenant_id=tenant_id)

    if ext in _SUPPORTED_WORD_EXTENSIONS:
        print("[i] Detected Word document: extracting text with parser before LLM pipeline.")

        if ext == ".docx":
            extracted = _extract_docx_text(file_path)
        else:
            extracted = _extract_doc_text(file_path)

        if not extracted:
            raise IngestionError(
                "No text content could be extracted from the Word document. "
                "Open the file and ensure it contains selectable text, then try again."
            )

        return extracted, {"source": "word_parser", "preprocessing_steps": [], "language": None}

    hint = (
        "Supported formats are PDF, PNG, JPG, JPEG, TIFF, DOC, and DOCX. "
        "If your invoice is in another format, export it to PDF or DOCX and retry."
    )
    readable_type = mime_type or ext or "unknown"
    raise IngestionError(f"Unsupported input format: {readable_type}. {hint}")


def route_extraction(file_path: str, tenant_id: str = "default") -> str:
    text, _ = route_extraction_with_diagnostics(file_path, tenant_id=tenant_id)
    return text
