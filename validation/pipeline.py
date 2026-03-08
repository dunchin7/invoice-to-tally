from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping

from jsonschema import ValidationError, validate

from schema.invoice_schema import invoice_schema

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)

CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "₹": "INR",
    "€": "EUR",
    "£": "GBP",
    "A$": "AUD",
    "C$": "CAD",
}

TAX_KEY_CANDIDATES = (
    "tax",
    "taxes",
    "tax_amount",
    "gst",
    "gst_amount",
    "vat",
    "vat_amount",
)


@dataclass(frozen=True)
class ValidationReport:
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    confidence_flags: Dict[str, bool] = field(default_factory=dict)
    critical_failure: bool = False


@dataclass(frozen=True)
class NormalizationResult:
    normalized: Dict[str, Any]
    report: ValidationReport


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        cleaned = re.sub(r"[^\d.\-]", "", cleaned)
        if cleaned in {"", ".", "-", "-."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    return None


def _normalize_entity(entity: Any) -> str:
    if isinstance(entity, str):
        return entity.strip()

    if isinstance(entity, Mapping):
        parts = [
            str(entity.get("name", "")).strip(),
            str(entity.get("address", "")).strip(),
            str(entity.get("gst_number", "")).strip(),
        ]
        return " | ".join(part for part in parts if part)

    return ""


def _normalize_currency(value: Any) -> tuple[str, List[str], bool]:
    warnings: List[str] = []

    if value is None:
        return "", ["Currency missing; left blank."], False

    raw = str(value).strip()
    if raw == "":
        return "", ["Currency missing; left blank."], False

    if raw in CURRENCY_SYMBOL_MAP:
        return CURRENCY_SYMBOL_MAP[raw], warnings, True

    direct_symbol = next((code for symbol, code in CURRENCY_SYMBOL_MAP.items() if raw.startswith(symbol)), None)
    if direct_symbol:
        warnings.append(f"Currency '{raw}' normalized to '{direct_symbol}'.")
        return direct_symbol, warnings, True

    upper = raw.upper()
    if re.fullmatch(r"[A-Z]{3}", upper):
        return upper, warnings, True

    warnings.append(f"Unrecognized currency '{raw}'; retained upper-case literal.")
    return upper, warnings, False


def _normalize_date(value: Any) -> tuple[str, List[str], bool]:
    warnings: List[str] = []

    if value is None:
        return "", ["Invoice date missing; left blank."], False

    raw = str(value).strip()
    if raw == "":
        return "", ["Invoice date missing; left blank."], False

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d"), warnings, True
        except ValueError:
            continue

    warnings.append(f"Could not confidently parse invoice_date '{raw}'; retained original text.")
    return raw, warnings, False


def _normalize_tax(data: Dict[str, Any], warnings: List[str]) -> float | None:
    chosen = None
    for key in TAX_KEY_CANDIDATES:
        if key in data:
            chosen = key
            break

    if chosen is None:
        warnings.append("No tax/GST field found; defaulting tax to 0.0.")
        return 0.0

    tax_value = _to_number(data.get(chosen))
    if tax_value is None:
        warnings.append(f"Tax field '{chosen}' was not numeric; defaulting tax to 0.0.")
        return 0.0

    if chosen != "tax":
        warnings.append(f"Mapped '{chosen}' to canonical 'tax'.")

    return tax_value


def _normalize_line_items(line_items: Any, warnings: List[str], confidence_flags: Dict[str, bool]) -> List[Dict[str, Any]]:
    if not isinstance(line_items, list):
        warnings.append("line_items was not a list; replaced with empty list.")
        confidence_flags["line_items_present"] = False
        return []

    normalized_items: List[Dict[str, Any]] = []
    quantity_confident = True
    price_confident = True

    for idx, item in enumerate(line_items, start=1):
        if not isinstance(item, Mapping):
            warnings.append(f"line_items[{idx}] is not an object; skipped.")
            continue

        quantity = _to_number(item.get("quantity"))
        unit_price = _to_number(item.get("unit_price"))
        total_price = _to_number(item.get("total_price"))

        if quantity is None:
            quantity_confident = False
            quantity = 0.0
            warnings.append(f"line_items[{idx}].quantity was not numeric; defaulted to 0.0.")
        if unit_price is None:
            price_confident = False
            unit_price = 0.0
            warnings.append(f"line_items[{idx}].unit_price was not numeric; defaulted to 0.0.")
        if total_price is None:
            price_confident = False
            total_price = round(quantity * unit_price, 2)
            warnings.append(
                f"line_items[{idx}].total_price was not numeric; backfilled from quantity * unit_price = {total_price:.2f}."
            )

        normalized_items.append(
            {
                "description": str(item.get("description", "")).strip(),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
            }
        )

    confidence_flags["line_item_quantity_confident"] = quantity_confident
    confidence_flags["line_item_pricing_confident"] = price_confident
    confidence_flags["line_items_present"] = len(normalized_items) > 0
    return normalized_items


def _cross_field_checks(data: Dict[str, Any], report_errors: List[str], confidence_flags: Dict[str, bool], tolerance: float = 0.05) -> None:
    subtotal = data.get("subtotal", 0.0) or 0.0
    tax = data.get("tax", 0.0) or 0.0
    total = data.get("total", 0.0) or 0.0

    header_delta = abs((subtotal + tax) - total)
    header_ok = header_delta <= tolerance
    confidence_flags["header_totals_consistent"] = header_ok

    if not header_ok:
        report_errors.append(
            f"Critical mismatch: subtotal + tax ({subtotal + tax:.2f}) does not match total ({total:.2f}); delta={header_delta:.2f}."
        )

    line_sum = round(sum((item.get("total_price", 0.0) or 0.0) for item in data.get("line_items", [])), 2)
    line_delta = abs(line_sum - subtotal)
    lines_ok = line_delta <= tolerance
    confidence_flags["line_totals_consistent"] = lines_ok

    if not lines_ok:
        report_errors.append(
            f"Critical mismatch: line item total ({line_sum:.2f}) does not match subtotal ({subtotal:.2f}); delta={line_delta:.2f}."
        )


def run_normalization_pipeline(raw_data: Dict[str, Any], allow_critical_override: bool = False) -> NormalizationResult:
    data = copy.deepcopy(raw_data) if raw_data is not None else {}

    warnings: List[str] = []
    errors: List[str] = []
    confidence_flags: Dict[str, bool] = {}

    normalized: Dict[str, Any] = {
        "invoice_number": str(data.get("invoice_number", "")).strip(),
        "seller": _normalize_entity(data.get("seller")),
        "buyer": _normalize_entity(data.get("buyer")),
    }

    normalized_date, date_warnings, date_ok = _normalize_date(data.get("invoice_date"))
    warnings.extend(date_warnings)
    normalized["invoice_date"] = normalized_date
    confidence_flags["invoice_date_confident"] = date_ok

    normalized_currency, currency_warnings, currency_ok = _normalize_currency(data.get("currency"))
    warnings.extend(currency_warnings)
    normalized["currency"] = normalized_currency
    confidence_flags["currency_confident"] = currency_ok

    normalized["subtotal"] = _to_number(data.get("subtotal"))
    if normalized["subtotal"] is None:
        normalized["subtotal"] = 0.0
        warnings.append("subtotal was not numeric; defaulted to 0.0.")

    normalized["tax"] = _normalize_tax(data, warnings)

    normalized["total"] = _to_number(data.get("total"))
    if normalized["total"] is None:
        normalized["total"] = 0.0
        warnings.append("total was not numeric; defaulted to 0.0.")

    normalized["line_items"] = _normalize_line_items(data.get("line_items", []), warnings, confidence_flags)

    try:
        validate(instance=normalized, schema=invoice_schema)
        confidence_flags["schema_valid"] = True
    except ValidationError as exc:
        errors.append(f"Schema validation failed: {exc.message}")
        confidence_flags["schema_valid"] = False

    _cross_field_checks(normalized, errors, confidence_flags)

    critical_failure = bool(errors)
    report = ValidationReport(
        warnings=warnings,
        errors=errors,
        confidence_flags=confidence_flags,
        critical_failure=critical_failure,
    )

    if critical_failure and not allow_critical_override:
        raise ValueError(
            "Validation failed with critical accounting mismatches. "
            "Re-run with allow_critical_override=True (or --allow-accounting-override) to continue. "
            f"Errors: {' | '.join(errors)}"
        )

    return NormalizationResult(normalized=normalized, report=report)
