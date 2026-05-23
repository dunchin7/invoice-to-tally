from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Tuple

from jsonschema import ValidationError, validate

from schema.invoice_schema import invoice_schema
from validation.errors import AccountingValidationError, FieldNormalizationError, SchemaValidationError
from validation.normalizer import _normalize_legacy as _normalize_to_v2_schema

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
    warnings: Tuple[str, ...]
    errors: Tuple[str, ...]
    confidence_flags: Mapping[str, bool]
    critical_failure: bool


@dataclass(frozen=True)
class NormalizationResult:
    normalized: Mapping[str, Any]
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


def _normalize_tax(data: Dict[str, Any], warnings: List[str], confidence_flags: Dict[str, bool]) -> float:
    chosen = None
    for key in TAX_KEY_CANDIDATES:
        if key in data:
            chosen = key
            break

    if chosen is None:
        warnings.append("No tax/GST field found; defaulting tax to 0.0.")
        confidence_flags["tax_confident"] = False
        return 0.0

    tax_value = _to_number(data.get(chosen))
    if tax_value is None:
        warnings.append(f"Tax field '{chosen}' was not numeric; defaulting tax to 0.0.")
        confidence_flags["tax_confident"] = False
        return 0.0

    if chosen != "tax":
        warnings.append(f"Mapped '{chosen}' to canonical 'tax'.")

    confidence_flags["tax_confident"] = True
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


def _cross_field_checks(data: Dict[str, Any], report_errors: List[str], confidence_flags: Dict[str, bool], tolerance: float = 1.0) -> None:
    subtotal = data.get("subtotal", 0.0) or 0.0
    tax = data.get("tax", 0.0) or 0.0
    total = data.get("total", 0.0) or 0.0
    line_items = data.get("line_items") or []

    header_delta = abs((subtotal + tax) - total)
    header_ok = header_delta <= tolerance
    confidence_flags["header_totals_consistent"] = header_ok

    if not header_ok:
        report_errors.append(
            f"Critical mismatch: subtotal + tax ({subtotal + tax:.2f}) does not match total ({total:.2f}); delta={header_delta:.2f}."
        )

    # For v2.0 invoices: sum(line.total_price) == total (line.total_price includes tax)
    # Fallback: sum(line.taxable_value) == subtotal (pre-tax sum)
    line_total_sum = round(sum((item.get("total_price") or 0.0) for item in line_items), 2)
    line_taxable_sum = round(sum((item.get("taxable_value") or 0.0) for item in line_items), 2)

    total_match_delta = abs(line_total_sum - total)
    taxable_match_delta = abs(line_taxable_sum - subtotal)
    # Also accept legacy invoices where line.total_price was pre-tax (matches subtotal)
    legacy_match_delta = abs(line_total_sum - subtotal)

    lines_ok = (
        total_match_delta <= tolerance
        or taxable_match_delta <= tolerance
        or legacy_match_delta <= tolerance
    )
    confidence_flags["line_totals_consistent"] = lines_ok

    if not lines_ok:
        report_errors.append(
            f"Critical mismatch: line items do not reconcile with header totals — "
            f"sum(total_price)={line_total_sum:.2f}, sum(taxable_value)={line_taxable_sum:.2f}, "
            f"subtotal={subtotal:.2f}, total={total:.2f}."
        )


def _freeze_normalized(data: Dict[str, Any]) -> Mapping[str, Any]:
    frozen_items = tuple(MappingProxyType(dict(item)) for item in data.get("line_items", []))
    frozen = dict(data)
    frozen["line_items"] = frozen_items
    return MappingProxyType(frozen)


def run_normalization_pipeline(raw_data: Dict[str, Any], allow_critical_override: bool = False) -> NormalizationResult:
    if raw_data is not None and not isinstance(raw_data, Mapping):
        raise FieldNormalizationError(
            "Invoice payload must be a JSON object for normalization.",
            context={"field": "invoice", "expected": "object", "actual": type(raw_data).__name__},
        )

    data = copy.deepcopy(raw_data) if raw_data is not None else {}

    warnings: List[str] = []
    errors: List[str] = []
    confidence_flags: Dict[str, bool] = {}

    # Normalize to v2.0 schema (preserves seller/buyer as dicts, GST fields, schema_version)
    normalized: Dict[str, Any] = _normalize_to_v2_schema(data)

    # Coerce any None totals to 0.0 so schema validation passes (schema allows null but
    # downstream Tally XML expects numbers)
    if normalized.get("subtotal") is None:
        normalized["subtotal"] = 0.0
        warnings.append("subtotal was not numeric; defaulted to 0.0.")
        confidence_flags["subtotal_confident"] = False
    else:
        confidence_flags["subtotal_confident"] = True

    if normalized.get("tax") is None:
        normalized["tax"] = 0.0
        warnings.append("tax was not numeric; defaulted to 0.0.")
        confidence_flags["tax_confident"] = False
    else:
        confidence_flags["tax_confident"] = True

    if normalized.get("total") is None:
        normalized["total"] = 0.0
        warnings.append("total was not numeric; defaulted to 0.0.")
        confidence_flags["total_confident"] = False
    else:
        confidence_flags["total_confident"] = True

    # Date confidence: normalizer falls back to "1970-01-01" when unparseable
    date_value = normalized.get("invoice_date")
    confidence_flags["invoice_date_confident"] = bool(date_value) and date_value != "1970-01-01"

    # Currency confidence: normalizer defaults to "INR" only when source had no currency
    confidence_flags["currency_confident"] = bool(normalized.get("currency"))

    # Line item presence
    confidence_flags["line_items_present"] = bool(normalized.get("line_items"))
    confidence_flags["line_item_quantity_confident"] = all(
        item.get("quantity") is not None for item in normalized.get("line_items", [])
    )
    confidence_flags["line_item_pricing_confident"] = all(
        item.get("unit_price") is not None and item.get("total_price") is not None
        for item in normalized.get("line_items", [])
    )

    try:
        validate(instance=normalized, schema=invoice_schema)
        confidence_flags["schema_valid"] = True
    except ValidationError as exc:
        confidence_flags["schema_valid"] = False
        field = ".".join(str(part) for part in exc.absolute_path) or "invoice"
        raise SchemaValidationError(
            f"Schema validation failed: {exc.message}",
            context={
                "field": field,
                "expected": exc.validator_value,
                "actual": exc.instance,
            },
        ) from exc

    _cross_field_checks(normalized, errors, confidence_flags)

    critical_failure = bool(errors)
    report = ValidationReport(
        warnings=tuple(warnings),
        errors=tuple(errors),
        confidence_flags=MappingProxyType(dict(confidence_flags)),
        critical_failure=critical_failure,
    )

    if critical_failure and not allow_critical_override:
        raise AccountingValidationError(
            "Validation failed with critical accounting mismatches.",
            context={
                "field": "totals",
                "expected": "subtotal + tax == total and line totals == subtotal",
                "actual": list(errors),
            },
        )

    return NormalizationResult(normalized=_freeze_normalized(normalized), report=report)


def to_mutable_invoice(normalized: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert immutable normalized payload back to plain dict/list for downstream consumers."""
    line_items = [dict(item) for item in normalized.get("line_items", ())]
    mutable = dict(normalized)
    mutable["line_items"] = line_items
    return mutable
