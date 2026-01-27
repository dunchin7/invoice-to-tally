import re
from jsonschema import validate
from schema.invoice_schema import invoice_schema

def _to_number(value):
    """
    Converts currency strings like "$85.00" or "85.00" to float.
    Returns None if conversion fails.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value)
        try:
            return float(cleaned)
        except ValueError:
            return None

    return None


def validate_invoice(data: dict) -> dict:
    # ---- FIELD NORMALIZATION ----

    # Map "taxes" → "tax"
    if "tax" not in data and "taxes" in data:
        data["tax"] = data.pop("taxes")

    # Flatten seller & buyer into strings (schema expects string)
    if isinstance(data.get("seller"), dict):
        seller = data["seller"]
        parts = [seller.get("name", ""), seller.get("address", ""), seller.get("gst_number", "")]
        data["seller"] = " | ".join(p for p in parts if p)

    if isinstance(data.get("buyer"), dict):
        buyer = data["buyer"]
        parts = [buyer.get("name", ""), buyer.get("address", ""), buyer.get("gst_number", "")]
        data["buyer"] = " | ".join(p for p in parts if p)

    # Convert numeric fields
    data["subtotal"] = _to_number(data.get("subtotal"))
    data["tax"] = _to_number(data.get("tax"))
    data["total"] = _to_number(data.get("total"))

    # Normalize line item numbers
    for item in data.get("line_items", []):
        item["quantity"] = _to_number(item.get("quantity"))
        item["unit_price"] = _to_number(item.get("unit_price"))
        item["total_price"] = _to_number(item.get("total_price"))

    # ---- VALIDATION ----
    try:
        validate(instance=data, schema=invoice_schema)
    except Exception as e:
        raise ValueError(f"Invoice JSON validation failed: {e.message}") from e

    return data
