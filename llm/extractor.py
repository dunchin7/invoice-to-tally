import os
import json
import re
from dotenv import load_dotenv
from google import genai

# Load .env variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not found in environment variables")

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "models/gemini-flash-latest"


def _build_prompt(raw_text: str) -> str:
    return f"""
You are an expert system that extracts structured invoice data.

Given the following invoice text, extract these fields and return ONLY valid JSON.

Required JSON format:

{{
  "invoice_number": "",
  "invoice_date": "",
  "seller": {{
    "name": "",
    "address": "",
    "gst_number": ""
  }},
  "buyer": {{
    "name": "",
    "address": "",
    "gst_number": ""
  }},
  "line_items": [
    {{
      "description": "",
      "quantity": "",
      "unit_price": "",
      "total_price": ""
    }}
  ],
  "subtotal": "",
  "taxes": "",
  "total": "",
  "currency": ""
}}

Rules:
- Return ONLY JSON.
- Do NOT wrap in ```json or code blocks.
- Do NOT add explanations.
- If a field is missing, leave it as an empty string.
- Ensure the output is strictly valid JSON.

Invoice text:
----------------
{raw_text}
----------------
"""


def _clean_gemini_output(text: str) -> str:
    """
    Removes markdown code fences and extracts raw JSON.
    """
    text = text.strip()

    # Remove ```json or ``` fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
        text = re.sub(r"```$", "", text.strip())

    # Trim again
    text = text.strip()

    return text


def extract_invoice_fields(raw_text: str) -> dict:
    prompt = _build_prompt(raw_text)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    try:
        response_text = response.text.strip()
    except Exception:
        raise RuntimeError("Gemini response had no text content")

    # Clean Gemini markdown garbage
    cleaned = _clean_gemini_output(response_text)

    # Try parsing JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print("[-] Gemini returned invalid JSON:")
        print(cleaned)
        raise RuntimeError("Failed to parse Gemini JSON output") from e

    return data
