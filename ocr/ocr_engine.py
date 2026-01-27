import os
from pdf2image import convert_from_path
from PIL import Image
import pytesseract

# ---- HARD-WIRED PATHS FOR WINDOWS ----
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from an image file using Tesseract OCR.
    """
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)
    return text


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Convert PDF pages to images and extract text from each page.
    Uses explicit Poppler path for Windows reliability.
    """
    pages = convert_from_path(
        pdf_path,
        poppler_path=POPPLER_PATH
    )

    full_text = []

    for page in pages:
        text = pytesseract.image_to_string(page)
        full_text.append(text)

    return "\n".join(full_text)


def extract_text(file_path: str) -> str:
    """
    Detect file type and route to appropriate OCR method.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        return extract_text_from_image(file_path)

    elif ext == ".pdf":
        return extract_text_from_pdf(file_path)

    else:
        raise ValueError(f"Unsupported file type: {ext}")
