from __future__ import annotations

import pytest

from ocr.ocr_engine import OCRExecutionLimits, OCRLimitExceededError, extract_text_from_pdf


class _Page:
    pass


def test_pdf_page_limit_breach_raises_structured_failure(monkeypatch):
    monkeypatch.setattr("ocr.ocr_engine._ensure_tesseract_available", lambda: None)
    monkeypatch.setattr("ocr.ocr_engine._ensure_pdf_runtime_available", lambda: None)
    monkeypatch.setattr("ocr.ocr_engine._load_limits", lambda: OCRExecutionLimits(timeout_seconds=30, max_pages=2))
    monkeypatch.setattr("ocr.ocr_engine.pdfinfo_from_path", lambda *_a, **_k: {"Pages": 3})

    with pytest.raises(OCRLimitExceededError) as exc:
        extract_text_from_pdf("invoice.pdf")

    assert exc.value.code == "OCR_PAGE_LIMIT_EXCEEDED"
    assert exc.value.context["detected_pages"] == 3
    assert exc.value.context["ocr_max_pages"] == 2


def test_pdf_timeout_returns_processed_page_count(monkeypatch):
    monkeypatch.setattr("ocr.ocr_engine._ensure_tesseract_available", lambda: None)
    monkeypatch.setattr("ocr.ocr_engine._ensure_pdf_runtime_available", lambda: None)
    monkeypatch.setattr("ocr.ocr_engine._load_limits", lambda: OCRExecutionLimits(timeout_seconds=1.0, max_pages=5))
    monkeypatch.setattr("ocr.ocr_engine.pdfinfo_from_path", lambda *_a, **_k: {"Pages": 3})
    monkeypatch.setattr("ocr.ocr_engine.convert_from_path", lambda *_a, **_k: [_Page()])
    monkeypatch.setattr("ocr.ocr_engine.pytesseract.image_to_string", lambda _img: "page-text")

    ticks = iter([0.0, 0.2, 1.2])
    monkeypatch.setattr("ocr.ocr_engine.time.monotonic", lambda: next(ticks))

    with pytest.raises(OCRLimitExceededError) as exc:
        extract_text_from_pdf("invoice.pdf")

    assert exc.value.code == "OCR_TIMEOUT"
    assert exc.value.context["processed_pages"] == 1


def test_router_maps_ocr_timeout_to_ingestion_error(monkeypatch):
    from ingestion.router import IngestionError, route_extraction

    monkeypatch.setattr("ingestion.router.os.path.exists", lambda _p: True)
    monkeypatch.setattr("ingestion.router._detect_file_type", lambda _p: ("application/pdf", ".pdf"))
    monkeypatch.setattr("ingestion.router._extract_pdf_text_layer", lambda _p: "")

    def _raise(_p):
        raise OCRLimitExceededError(
            "timed out",
            code="OCR_TIMEOUT",
            context={"processed_pages": 2, "ocr_timeout_seconds": 1.0},
        )

    monkeypatch.setattr("ingestion.router.extract_text", _raise)

    with pytest.raises(IngestionError) as exc:
        route_extraction("invoice.pdf")

    assert exc.value.code == "OCR_TIMEOUT"
    assert exc.value.context["processed_pages"] == 2
