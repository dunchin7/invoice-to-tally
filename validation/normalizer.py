import re
from datetime import datetime

from jsonschema import ValidationError, validate

from schema.invoice_schema import invoice_schema
from validation.errors import SchemaValidationError


DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


NUMERIC_KEYS = {
    "quantity",
    "unit_price",
    "discount_rate",
    "discount_amount",
    "taxable_value",
    "cgst_rate",
    "sgst_rate",
    "igst_rate",
    "cess_rate",
    "cgst_amount",
    "sgst_amount",
    "igst_amount",
    "cess_amount",
    "tax_amount",
    "total_price",
}


def _clean_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value).strip() or None


def _to_number(value):
    """Converts numeric/currency strings like "₹1,200.00" to float."""
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = value.replace(",", "")
        cleaned = re.sub(r"[^\d.\-]", "", cleaned)
        if cleaned in {"", "-", ".", "-."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    return None


def _to_iso_date(value):
    value = _clean_text(value)
    if not value:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value

    return None


def _to_bool_or_none(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value

    val = str(value).strip().lower()
    if val in {"yes", "y", "true", "1", "applicable"}:
        return True
    if val in {"no", "n", "false", "0", "not applicable", "na"}:
        return False
    return None


def _normalize_address(address):
    if isinstance(address, dict):
        return {
            "line1": _clean_text(address.get("line1") or address.get("street") or address.get("address_line_1")),
            "line2": _clean_text(address.get("line2") or address.get("address_line_2")),
            "city": _clean_text(address.get("city")),
            "state": _clean_text(address.get("state")),
            "postal_code": _clean_text(address.get("postal_code") or address.get("pincode") or address.get("zip")),
            "country": _clean_text(address.get("country")),
        }

    raw = _clean_text(address)
    return {
        "line1": raw,
        "line2": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None,
    }


def _normalize_party(party):
    if isinstance(party, str):
        return {
            "name": _clean_text(party) or "Unknown",
            "gstin": None,
            "pan": None,
            "address": _normalize_address(None),
        }

    if not isinstance(party, dict):
        party = {}

    name = _clean_text(party.get("name")) or "Unknown"
    gstin = _clean_text(party.get("gstin") or party.get("gst_number") or party.get("gst"))
    pan = _clean_text(party.get("pan"))
    address = _normalize_address(party.get("address"))

    if not address["line1"]:
        address = _normalize_address(party.get("address_line") or party.get("addr"))

    return {
        "name": name,
        "gstin": gstin,
        "pan": pan,
        "address": address,
    }


def _normalize_transport(data):
    transport = data.get("transport") if isinstance(data.get("transport"), dict) else {}
    return {
        "transport_mode": _clean_text(transport.get("transport_mode") or data.get("transport_mode")),
        "transporter_name": _clean_text(transport.get("transporter_name") or data.get("transporter_name")),
        "vehicle_number": _clean_text(transport.get("vehicle_number") or data.get("vehicle_number")),
        "lr_number": _clean_text(transport.get("lr_number") or data.get("lr_number")),
        "eway_bill_number": _clean_text(transport.get("eway_bill_number") or data.get("eway_bill_number")),
    }


def _normalize_line_item(item):
    normalized = {
        "description": _clean_text(item.get("description")) or "Item",
        "hsn_sac": _clean_text(item.get("hsn_sac") or item.get("hsn") or item.get("sac")),
        "quantity": _to_number(item.get("quantity")),
        "unit": _clean_text(item.get("unit")),
        "uom": _clean_text(item.get("uom") or item.get("unit_of_measure")),
        "unit_price": _to_number(item.get("unit_price") or item.get("rate")),
        "discount_rate": _to_number(item.get("discount_rate") or item.get("discount_percent")),
        "discount_amount": _to_number(item.get("discount_amount") or item.get("discount")),
        "taxable_value": _to_number(item.get("taxable_value") or item.get("assessable_value")),
        "cgst_rate": _to_number(item.get("cgst_rate")),
        "sgst_rate": _to_number(item.get("sgst_rate")),
        "igst_rate": _to_number(item.get("igst_rate")),
        "cess_rate": _to_number(item.get("cess_rate")),
        "cgst_amount": _to_number(item.get("cgst_amount")),
        "sgst_amount": _to_number(item.get("sgst_amount")),
        "igst_amount": _to_number(item.get("igst_amount")),
        "cess_amount": _to_number(item.get("cess_amount")),
        "tax_amount": _to_number(item.get("tax_amount") or item.get("tax")),
        "total_price": _to_number(item.get("total_price") or item.get("amount")),
    }

    if normalized["tax_amount"] is None:
        tax_parts = [
            normalized["cgst_amount"] or 0,
            normalized["sgst_amount"] or 0,
            normalized["igst_amount"] or 0,
            normalized["cess_amount"] or 0,
        ]
        if any(tax_parts):
            normalized["tax_amount"] = float(sum(tax_parts))

    if normalized["total_price"] is None and normalized["quantity"] is not None and normalized["unit_price"] is not None:
        normalized["total_price"] = normalized["quantity"] * normalized["unit_price"]

    return normalized


def _normalize_legacy(data: dict) -> dict:
    """Backward compatibility mapper for pre-v2 payloads."""
    if "tax" not in data and "taxes" in data:
        data["tax"] = data.get("taxes")

    line_items = data.get("line_items") or []
    normalized_items = []
    for item in line_items:
        if isinstance(item, dict):
            normalized_items.append(_normalize_line_item(item))

    normalized = {
        "schema_version": "2.0",
        "invoice_number": _clean_text(data.get("invoice_number")) or "UNKNOWN",
        "invoice_type": _clean_text(data.get("invoice_type")),
        "invoice_date": _to_iso_date(data.get("invoice_date")) or "1970-01-01",
        "due_date": _to_iso_date(data.get("due_date")),
        "po_number": _clean_text(data.get("po_number") or data.get("purchase_order_number")),
        "place_of_supply": _clean_text(data.get("place_of_supply")),
        "reverse_charge": _to_bool_or_none(data.get("reverse_charge")),
        "transport": _normalize_transport(data),
        "seller": _normalize_party(data.get("seller")),
        "buyer": _normalize_party(data.get("buyer")),
        "currency": _clean_text(data.get("currency")) or "INR",
        "line_items": normalized_items or [
            {
                "description": "Item",
                "hsn_sac": None,
                "quantity": 1.0,
                "unit": None,
                "uom": None,
                "unit_price": 0.0,
                "discount_rate": None,
                "discount_amount": None,
                "taxable_value": None,
                "cgst_rate": None,
                "sgst_rate": None,
                "igst_rate": None,
                "cess_rate": None,
                "cgst_amount": None,
                "sgst_amount": None,
                "igst_amount": None,
                "cess_amount": None,
                "tax_amount": None,
                "total_price": 0.0,
            }
        ],
        "subtotal": _to_number(data.get("subtotal")),
        "tax": _to_number(data.get("tax")),
        "total": _to_number(data.get("total")),
    }

    # Compute fallback totals where feasible.
    if normalized["subtotal"] is None:
        normalized["subtotal"] = sum(item.get("total_price") or 0 for item in normalized["line_items"])
    if normalized["tax"] is None:
        normalized["tax"] = sum(item.get("tax_amount") or 0 for item in normalized["line_items"])
    if normalized["total"] is None and normalized["subtotal"] is not None:
        normalized["total"] = (normalized["subtotal"] or 0) + (normalized["tax"] or 0)

    return normalized


def validate_invoice(data: dict) -> dict:
    normalized = _normalize_legacy(data)

    try:
        validate(instance=normalized, schema=invoice_schema)
    except ValidationError as exc:
        field = ".".join(str(part) for part in exc.absolute_path) or "invoice"
        raise SchemaValidationError(
            f"Invoice JSON validation failed: {exc.message}",
            context={"field": field, "expected": exc.validator_value, "actual": exc.instance},
        ) from exc

    return normalized
