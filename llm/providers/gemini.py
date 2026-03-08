from __future__ import annotations

import os

from google import genai

from llm.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not found in environment variables")

        self._model_name = model_name or os.getenv("GEMINI_MODEL_NAME", "models/gemini-flash-latest")
        self._client = genai.Client(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract_structured_invoice(self, raw_text: str) -> str:
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=self._build_extraction_prompt(raw_text),
        )
        return self._response_text(response)

    def repair_json(self, raw_text: str, broken_json: str, parse_error: str) -> str:
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=self._build_repair_prompt(raw_text, broken_json, parse_error),
        )
        return self._response_text(response)

    @staticmethod
    def _response_text(response: object) -> str:
        try:
            return response.text.strip()
        except Exception as exc:  # no text available from model
            raise RuntimeError("Gemini response had no text content") from exc

    @staticmethod
    def _build_extraction_prompt(raw_text: str) -> str:
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

    @staticmethod
    def _build_repair_prompt(raw_text: str, broken_json: str, parse_error: str) -> str:
        return f"""
You are a strict JSON repair assistant for invoice extraction.

The following extracted JSON is invalid and failed parsing:
Parse error: {parse_error}

Invalid JSON candidate:
----------------
{broken_json}
----------------

Original invoice text (for grounding):
----------------
{raw_text}
----------------

Task:
- Repair the JSON so it is strictly valid JSON.
- Preserve values from the candidate when possible.
- Conform exactly to this schema:
{{
  "invoice_number": "",
  "invoice_date": "",
  "seller": {{"name": "", "address": "", "gst_number": ""}},
  "buyer": {{"name": "", "address": "", "gst_number": ""}},
  "line_items": [{{"description": "", "quantity": "", "unit_price": "", "total_price": ""}}],
  "subtotal": "",
  "taxes": "",
  "total": "",
  "currency": ""
}}

Rules:
- Return ONLY valid JSON.
- Do not include markdown fences or explanation text.
"""
