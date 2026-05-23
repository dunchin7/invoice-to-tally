from __future__ import annotations

import os

from openai import AzureOpenAI

from llm.providers.base import LLMProvider


_EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert invoice data extraction system specializing in Indian GST invoices. "
    "Extract all invoice data from the provided text and return it as a valid JSON object "
    "matching the required schema exactly. Return ONLY the JSON object."
)

_EXTRACTION_USER_TEMPLATE = """\
Extract all invoice data from the following invoice text and return it as a JSON object.

REQUIRED JSON SCHEMA (return this exact structure, all keys must be present):
{{
  "schema_version": "2.0",
  "invoice_number": "string — invoice/bill number (required, use UNKNOWN if missing)",
  "invoice_date": "YYYY-MM-DD — invoice date (required)",
  "invoice_type": "one of: tax_invoice, credit_note, debit_note, proforma_invoice, receipt — or null",
  "place_of_supply": "state name string or null",
  "due_date": "YYYY-MM-DD or null",
  "po_number": "purchase order number or null",
  "reverse_charge": true or false or null,
  "seller": {{
    "name": "company/supplier name (required)",
    "gstin": "15-char GST number like 29ABCDE1234F1Z5, or empty string if not found",
    "pan": "10-char PAN like ABCDE1234F, or empty string if not found",
    "address": {{
      "line1": "street address line 1 or null",
      "line2": "area/locality line 2 or null",
      "city": "city name or null",
      "state": "full state name like Maharashtra, Delhi, Karnataka or null",
      "postal_code": "PIN code or null",
      "country": "country — default India"
    }}
  }},
  "buyer": {{
    "name": "customer/buyer name (required)",
    "gstin": "15-char GST number or empty string if not found",
    "pan": "10-char PAN or empty string if not found",
    "address": {{
      "line1": "street address line 1 or null",
      "line2": "area/locality line 2 or null",
      "city": "city name or null",
      "state": "full state name or null",
      "postal_code": "PIN code or null",
      "country": "country or null"
    }}
  }},
  "currency": "INR (or actual currency code if different)",
  "line_items": [
    {{
      "description": "item/service description (required, non-empty string)",
      "hsn_sac": "4-8 digit HSN or SAC code or null",
      "quantity": 1.0,
      "unit": "UOM like PCS, KG, NOS, MONTHS or null",
      "uom": null,
      "unit_price": 100.00,
      "taxable_value": 100.00,
      "discount_rate": null,
      "discount_amount": null,
      "cgst_rate": 9.0,
      "cgst_amount": 9.00,
      "sgst_rate": 9.0,
      "sgst_amount": 9.00,
      "igst_rate": 0.0,
      "igst_amount": 0.00,
      "cess_rate": null,
      "cess_amount": null,
      "tax_amount": 18.00,
      "total_price": 118.00
    }}
  ],
  "subtotal": 100.00,
  "tax": 18.00,
  "total": 118.00,
  "transport": {{
    "transport_mode": null,
    "transporter_name": null,
    "vehicle_number": null,
    "lr_number": null,
    "eway_bill_number": null
  }}
}}

EXTRACTION RULES:
1. schema_version must always be exactly the string "2.0"
2. invoice_date must be in YYYY-MM-DD format regardless of how it appears on the invoice
3. ALL monetary amounts must be numbers (not strings): subtotal, tax, total, unit_price, total_price, taxable_value, cgst_amount, sgst_amount, igst_amount, tax_amount
4. quantity must be a number (not a string)
5. GST rules — determine intra-state vs inter-state from seller and buyer state:
   - If buyer state == seller state (INTRA-STATE): populate cgst_rate + sgst_rate (each = half the GST rate), set igst_rate=0, igst_amount=0
   - If buyer state != seller state (INTER-STATE): populate igst_rate = full GST rate, set cgst_rate=0, cgst_amount=0, sgst_rate=0, sgst_amount=0
   - Common GST rates: 0%, 5%, 12%, 18%, 28%
   - cgst_rate should equal sgst_rate for intra-state
6. gstin: 15-character format — 2-digit state code + 5-char PAN base + 4 digits + 1 char + Z + 1 char (e.g. 29ABCDE1234F1Z5)
7. pan: 10-character format — 5 uppercase letters + 4 digits + 1 uppercase letter (e.g. ABCDE1234F)
8. Use null (not empty string) for optional fields that are absent, EXCEPT gstin and pan which should be empty string "" when absent
9. transport: use null values for each sub-field if transport details are not on the invoice
10. taxable_value per line item = total_price minus tax_amount (before GST)
11. subtotal = sum of all line item taxable_values (before tax)
12. tax = sum of all GST amounts (cgst + sgst or igst)
13. total = subtotal + tax

INVOICE TEXT:
----------------
{raw_text}
----------------"""

_REPAIR_SYSTEM_PROMPT = (
    "You are a JSON repair assistant. Fix the provided invalid JSON to exactly match "
    "the required invoice schema. Return ONLY the corrected JSON object."
)

_REPAIR_USER_TEMPLATE = """\
The following JSON extracted from an invoice is invalid and must be repaired.

Parse error: {parse_error}

Invalid JSON candidate:
----------------
{broken_json}
----------------

Original invoice text (for grounding):
----------------
{raw_text}
----------------

Return ONLY a corrected valid JSON object matching this schema exactly:
{{
  "schema_version": "2.0",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "invoice_type": "tax_invoice|credit_note|debit_note|proforma_invoice|receipt or null",
  "place_of_supply": "string or null",
  "due_date": "YYYY-MM-DD or null",
  "po_number": "string or null",
  "reverse_charge": true/false/null,
  "seller": {{"name": "string", "gstin": "", "pan": "", "address": {{"line1": null, "line2": null, "city": null, "state": null, "postal_code": null, "country": null}}}},
  "buyer": {{"name": "string", "gstin": "", "pan": "", "address": {{"line1": null, "line2": null, "city": null, "state": null, "postal_code": null, "country": null}}}},
  "currency": "INR",
  "line_items": [{{"description": "string", "hsn_sac": null, "quantity": 1.0, "unit": null, "uom": null, "unit_price": 0.0, "taxable_value": null, "discount_rate": null, "discount_amount": null, "cgst_rate": null, "cgst_amount": null, "sgst_rate": null, "sgst_amount": null, "igst_rate": null, "igst_amount": null, "cess_rate": null, "cess_amount": null, "tax_amount": null, "total_price": 0.0}}],
  "subtotal": 0.0,
  "tax": 0.0,
  "total": 0.0,
  "transport": {{"transport_mode": null, "transporter_name": null, "vehicle_number": null, "lr_number": null, "eway_bill_number": null}}
}}

Fix ALL invalid JSON syntax. Preserve values from the candidate where possible.
Ensure all monetary amounts are numbers, not strings."""


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider for invoice field extraction."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment_name: str | None = None,
        api_version: str | None = None,
    ):
        resolved_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        resolved_endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        resolved_deployment = (
            deployment_name
            or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
            or os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or "gpt-4o"
        )
        resolved_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

        if not resolved_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY not found in environment variables")
        if not resolved_endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT not found in environment variables")

        self._deployment = resolved_deployment
        self._client = AzureOpenAI(
            api_key=resolved_key,
            azure_endpoint=resolved_endpoint,
            api_version=resolved_version,
        )

    @property
    def name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return self._deployment

    def extract_structured_invoice(self, raw_text: str) -> str:
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": _EXTRACTION_USER_TEMPLATE.format(raw_text=raw_text)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("Azure OpenAI response returned no content")
        return content

    def repair_json(self, raw_text: str, broken_json: str, parse_error: str) -> str:
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": _REPAIR_USER_TEMPLATE.format(
                    raw_text=raw_text,
                    broken_json=broken_json,
                    parse_error=parse_error,
                )},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("Azure OpenAI repair response returned no content")
        return content
