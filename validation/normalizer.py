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

    normalized = _reconcile_header_with_lines(normalized)
    return _apply_gst_consistency(normalized)


def _reconcile_header_with_lines(normalized: dict, tolerance: float = 1.0) -> dict:
    """Override header totals when line items reconcile internally but header disagrees.

    LLM/OCR extraction sometimes misreads single digits in the header summary while
    line item values remain correct. If sum(taxable_value)+sum(tax) reconciles to
    sum(total_price) internally, treat that as the truth and overwrite the header.
    """
    line_items = normalized.get("line_items") or []
    if not line_items:
        return normalized

    line_taxable = sum(item.get("taxable_value") or 0.0 for item in line_items)
    line_tax = sum(item.get("tax_amount") or 0.0 for item in line_items)
    line_total = sum(item.get("total_price") or 0.0 for item in line_items)

    # Only trust line items if they reconcile internally
    if line_taxable <= 0 or line_total <= 0:
        return normalized
    if abs((line_taxable + line_tax) - line_total) > tolerance:
        return normalized

    header_subtotal = normalized.get("subtotal") or 0.0
    header_tax = normalized.get("tax") or 0.0
    header_total = normalized.get("total") or 0.0

    # If header already matches line items, no adjustment needed
    if (
        abs(header_subtotal - line_taxable) <= tolerance
        and abs(header_tax - line_tax) <= tolerance
        and abs(header_total - line_total) <= tolerance
    ):
        return normalized

    # Header diverges from internally-consistent line items — overwrite with line sums
    normalized["subtotal"] = round(line_taxable, 2)
    normalized["tax"] = round(line_tax, 2)
    normalized["total"] = round(line_total, 2)
    return normalized


def _apply_gst_consistency(normalized: dict) -> dict:
    """Correct CGST/SGST vs IGST split based on seller and buyer state."""
    seller_state = ((normalized.get("seller") or {}).get("address") or {}).get("state") or ""
    buyer_state = ((normalized.get("buyer") or {}).get("address") or {}).get("state") or ""

    if not seller_state or not buyer_state:
        return normalized

    def _norm(s: str) -> str:
        return s.strip().lower().replace(" ", "").replace("-", "")

    is_intra_state = _norm(seller_state) == _norm(buyer_state)

    for item in normalized.get("line_items") or []:
        cgst_amount = item.get("cgst_amount") or 0.0
        sgst_amount = item.get("sgst_amount") or 0.0
        igst_amount = item.get("igst_amount") or 0.0
        cgst_rate = item.get("cgst_rate") or 0.0
        sgst_rate = item.get("sgst_rate") or 0.0
        igst_rate = item.get("igst_rate") or 0.0

        has_cgst_sgst = cgst_amount > 0 or sgst_amount > 0
        has_igst = igst_amount > 0

        if is_intra_state and has_igst and not has_cgst_sgst:
            # Inter-state amounts provided but transaction is intra-state — split IGST
            half_rate = round(igst_rate / 2, 4)
            half_amount = round(igst_amount / 2, 2)
            item["cgst_rate"] = half_rate
            item["cgst_amount"] = half_amount
            item["sgst_rate"] = half_rate
            item["sgst_amount"] = half_amount
            item["igst_rate"] = 0.0
            item["igst_amount"] = 0.0
        elif not is_intra_state and has_cgst_sgst and not has_igst:
            # Intra-state amounts provided but transaction is inter-state — combine to IGST
            item["igst_rate"] = round(cgst_rate + sgst_rate, 4)
            item["igst_amount"] = round(cgst_amount + sgst_amount, 2)
            item["cgst_rate"] = 0.0
            item["cgst_amount"] = 0.0
            item["sgst_rate"] = 0.0
            item["sgst_amount"] = 0.0

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
