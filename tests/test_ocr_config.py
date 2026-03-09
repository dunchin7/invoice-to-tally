from types import SimpleNamespace

from PIL import Image

from ocr import ocr_engine


def test_preprocessing_steps_are_disabled_by_default(monkeypatch, tmp_path):
    image_path = tmp_path / "invoice.png"
    Image.new("RGB", (8, 8), color="white").save(image_path)

    monkeypatch.setattr(
        ocr_engine,
        "SETTINGS",
        SimpleNamespace(
            tesseract_cmd=None,
            poppler_path=None,
            ocr_language=None,
            ocr_tenant_language_overrides={},
            ocr_preprocess_deskew=False,
            ocr_preprocess_binarization=False,
            ocr_preprocess_contrast_enhancement=False,
        ),
    )
    monkeypatch.setattr(ocr_engine, "_ensure_tesseract_available", lambda: None)

    calls = {"deskew": 0, "binarization": 0, "contrast": 0}
    monkeypatch.setattr(ocr_engine, "_deskew_image", lambda image: calls.__setitem__("deskew", calls["deskew"] + 1) or image)
    monkeypatch.setattr(ocr_engine, "_binarize_image", lambda image: calls.__setitem__("binarization", calls["binarization"] + 1) or image)
    monkeypatch.setattr(ocr_engine, "_enhance_contrast", lambda image: calls.__setitem__("contrast", calls["contrast"] + 1) or image)
    monkeypatch.setattr(ocr_engine.pytesseract, "image_to_string", lambda _img, **_kwargs: "parsed")

    _text, diagnostics = ocr_engine.extract_text_with_diagnostics(str(image_path))

    assert calls == {"deskew": 0, "binarization": 0, "contrast": 0}
    assert diagnostics["preprocessing_steps"] == []


def test_preprocessing_toggles_and_language_override(monkeypatch, tmp_path):
    image_path = tmp_path / "invoice.png"
    Image.new("RGB", (8, 8), color="white").save(image_path)

    monkeypatch.setattr(
        ocr_engine,
        "SETTINGS",
        SimpleNamespace(
            tesseract_cmd=None,
            poppler_path=None,
            ocr_language="eng",
            ocr_tenant_language_overrides={"tenant-a": "deu"},
            ocr_preprocess_deskew=True,
            ocr_preprocess_binarization=True,
            ocr_preprocess_contrast_enhancement=True,
        ),
    )
    monkeypatch.setattr(ocr_engine, "_ensure_tesseract_available", lambda: None)

    order = []
    monkeypatch.setattr(ocr_engine, "_deskew_image", lambda image: order.append("deskew") or image)
    monkeypatch.setattr(ocr_engine, "_binarize_image", lambda image: order.append("binarization") or image)
    monkeypatch.setattr(ocr_engine, "_enhance_contrast", lambda image: order.append("contrast_enhancement") or image)

    seen_lang = {}

    def _fake_ocr(_img, **kwargs):
        seen_lang["lang"] = kwargs.get("lang")
        return "parsed"

    monkeypatch.setattr(ocr_engine.pytesseract, "image_to_string", _fake_ocr)

    _text, diagnostics = ocr_engine.extract_text_with_diagnostics(str(image_path), tenant_id="tenant-a")

    assert order == ["deskew", "binarization", "contrast_enhancement"]
    assert seen_lang["lang"] == "deu"
    assert diagnostics["preprocessing_steps"] == ["deskew", "binarization", "contrast_enhancement"]
    assert diagnostics["language"] == "deu"


def test_global_language_used_without_tenant_override(monkeypatch):
    monkeypatch.setattr(
        ocr_engine,
        "SETTINGS",
        SimpleNamespace(
            ocr_language="eng",
            ocr_tenant_language_overrides={"tenant-a": "deu"},
            ocr_preprocess_deskew=False,
            ocr_preprocess_binarization=False,
            ocr_preprocess_contrast_enhancement=False,
        ),
    )

    config = ocr_engine.resolve_ocr_config(tenant_id="tenant-b")

    assert config.language == "eng"
