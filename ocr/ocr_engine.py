import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from pdf2image import convert_from_path
from PIL import Image
import os


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
    """
    pages = convert_from_path(pdf_path)
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