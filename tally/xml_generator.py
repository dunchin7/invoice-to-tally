from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable
from xml.etree.ElementTree import Element, ElementTree, SubElement, tostring

TWOPLACES = Decimal("0.01")
DEFAULT_LEDGER_NAMES = {
    "sales": "Sales",
    "purchase": "Purchase",
    "cgst": "CGST",
    "sgst": "SGST",
    "igst": "IGST",
    "input_cgst": "Input CGST",
    "input_sgst": "Input SGST",
    "input_igst": "Input IGST",
    "round_off": "Round Off",
    "receivables": None,
    "payables": None,
}
DEFAULT_VOUCHER_TYPES = {
    "tax_invoice": "Sales",
    "credit_note": "Credit Note",
    "debit_note": "Debit Note",
    "proforma_invoice": "Sales",
    "receipt": "Receipt",
    None: "Sales",
}
DEFAULT_PURCHASE_VOUCHER_TYPES = {
    "tax_invoice": "Purchase",
    "credit_note": "Debit Note",
    "debit_note": "Credit Note",
    "proforma_invoice": "Purchase",
    "receipt": "Payment",
    None: "Purchase",
}


@dataclass(frozen=True)
class VoucherLedgerEntry:
    ledger_name: str
    amount: Decimal
    entry_type: str


@dataclass(frozen=True)
class VoucherMapping:
    date: str
    voucher_number: str
    voucher_type: str
    party_ledger_name: str
    narration: str
    entries: list[VoucherLedgerEntry]


LedgerResolver = Callable[[str, dict[str, Any]], str]


class VoucherBalanceError(ValueError):
    pass


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(TWOPLACES)


def _party_ledger_name(party: Any) -> str:
    if isinstance(party, dict):
        return party.get("name") or "Unknown Party"
    if party:
        return str(party)
    return "Unknown Party"


def _normalize_tally_date(invoice_date: str) -> str:
    if isinstance(invoice_date, datetime):
        return invoice_date.strftime("%Y%m%d")

    date_text = str(invoice_date).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            parsed = datetime.strptime(date_text, fmt)
            return parsed.strftime("%Y%m%d")
        except ValueError:
            continue

    raise ValueError(f"Unsupported invoice_date format: {invoice_date}")


def _resolve_direction(invoice: dict[str, Any], config: dict[str, Any]) -> str:
    """Return 'sales' or 'purchase' for voucher polarity. Defaults to sales."""
    explicit = config.get("direction") or invoice.get("direction")
    if explicit in ("sales", "purchase"):
        return explicit
    return "sales"


def _resolve_voucher_type(invoice: dict[str, Any], config: dict[str, Any], direction: str) -> str:
    configured = config.get("voucher_type")
    if configured:
        return str(configured)

    if direction == "purchase":
        mapping = {**DEFAULT_PURCHASE_VOUCHER_TYPES, **config.get("voucher_type_map", {})}
        return mapping.get(invoice.get("invoice_type"), "Purchase")

    mapping = {**DEFAULT_VOUCHER_TYPES, **config.get("voucher_type_map", {})}
    return mapping.get(invoice.get("invoice_type"), "Sales")


def _build_ledger_resolver(config: dict[str, Any]) -> LedgerResolver:
    explicit_resolver = config.get("ledger_resolver")
    if explicit_resolver:
        return explicit_resolver

    configured_ledgers = {**DEFAULT_LEDGER_NAMES, **config.get("ledger_names", {})}

    def _resolve(role: str, invoice: dict[str, Any]) -> str:
        if role == "receivables":
            return configured_ledgers.get(role) or _party_ledger_name(invoice.get("buyer"))
        if role == "payables":
            return configured_ledgers.get(role) or _party_ledger_name(invoice.get("seller"))
        return configured_ledgers[role]

    return _resolve


def _collect_amounts(invoice: dict[str, Any]) -> dict[str, Decimal]:
    line_items = invoice.get("line_items", [])

    taxable = Decimal("0")
    cgst = Decimal("0")
    sgst = Decimal("0")
    igst = Decimal("0")

    for item in invoice.get("line_items", []):
        item_total = _to_decimal(item.get("total_price"))
        item_tax = _to_decimal(item.get("tax_amount"))
        item_taxable = _to_decimal(item.get("taxable_value"), default="-1")

        if item_taxable < 0:
            item_taxable = item_total - item_tax

        taxable += item_taxable
        cgst += _to_decimal(item.get("cgst_amount"))
        sgst += _to_decimal(item.get("sgst_amount"))
        igst += _to_decimal(item.get("igst_amount"))

    if not any([cgst, sgst, igst]):
        # Fallback: when item-level split tax is not present.
        igst = _to_decimal(invoice.get("tax"))

    total = _to_decimal(invoice.get("total"))
    computed_credit = taxable + cgst + sgst + igst
    round_off = total - computed_credit

    return {
        "taxable": _quantize(taxable),
        "cgst": _quantize(cgst),
        "sgst": _quantize(sgst),
        "igst": _quantize(igst),
        "round_off": _quantize(round_off),
        "total": _quantize(total),
    }


def _validate_balancing(entries: list[VoucherLedgerEntry]) -> None:
    debit = _quantize(sum((entry.amount for entry in entries if entry.entry_type == "debit"), Decimal("0")))
    credit = _quantize(sum((entry.amount for entry in entries if entry.entry_type == "credit"), Decimal("0")))

    if debit != credit:
        raise VoucherBalanceError(f"Unbalanced voucher entries: debit={debit} credit={credit}")


def map_invoice_to_voucher(invoice: dict[str, Any], config: dict[str, Any] | None = None) -> VoucherMapping:
    config = config or {}
    ledger_resolver = _build_ledger_resolver(config)
    direction = _resolve_direction(invoice, config)
    is_purchase = direction == "purchase"

    amounts = _collect_amounts(invoice)

    # Sales: buyer is Dr (receivable); Sales/Output GST are Cr.
    # Purchase: seller is Cr (payable); Purchase/Input GST are Dr.
    if is_purchase:
        party_ledger = ledger_resolver("payables", invoice)
        party_entry_type = "credit"
        line_entry_type = "debit"
        line_ledger_role = "purchase"
        tax_role_map = {"cgst": "input_cgst", "sgst": "input_sgst", "igst": "input_igst"}
    else:
        party_ledger = ledger_resolver("receivables", invoice)
        party_entry_type = "debit"
        line_entry_type = "credit"
        line_ledger_role = "sales"
        tax_role_map = {"cgst": "cgst", "sgst": "sgst", "igst": "igst"}

    entries: list[VoucherLedgerEntry] = [
        VoucherLedgerEntry(ledger_name=party_ledger, amount=amounts["total"], entry_type=party_entry_type),
        VoucherLedgerEntry(
            ledger_name=ledger_resolver(line_ledger_role, invoice),
            amount=amounts["taxable"],
            entry_type=line_entry_type,
        ),
    ]

    for tax_role in ("cgst", "sgst", "igst"):
        amount = amounts[tax_role]
        if amount > 0:
            entries.append(
                VoucherLedgerEntry(
                    ledger_name=ledger_resolver(tax_role_map[tax_role], invoice),
                    amount=amount,
                    entry_type=line_entry_type,
                )
            )

    max_round_off = _to_decimal(config.get("max_round_off", "1.00"))
    if abs(amounts["round_off"]) > max_round_off:
        raise VoucherBalanceError(f"Round-off {amounts['round_off']} exceeds configured threshold {max_round_off}")

    if amounts["round_off"] != 0:
        # On sales the "natural" credit side is taxable+taxes summing to less than total → round_off as Cr balances the Dr party.
        # On purchase the polarity flips: the Dr side is short → round_off goes on Dr (i.e. line side).
        round_off_amount = abs(amounts["round_off"])
        if amounts["round_off"] > 0:
            round_off_type = "credit" if not is_purchase else "debit"
        else:
            round_off_type = "debit" if not is_purchase else "credit"
        entries.append(VoucherLedgerEntry(ledger_name=ledger_resolver("round_off", invoice), amount=round_off_amount, entry_type=round_off_type))

    _validate_balancing(entries)

    return VoucherMapping(
        date=_normalize_tally_date(invoice["invoice_date"]),
        voucher_number=str(invoice["invoice_number"]),
        voucher_type=_resolve_voucher_type(invoice, config, direction),
        party_ledger_name=party_ledger,
        narration=config.get("narration") or "Imported from Invoice AI",
        entries=entries,
    )


def _build_xml_tree(voucher_mapping: VoucherMapping, *, company: str | None = None, voucher_action: str = "Create") -> Element:
    envelope = Element("ENVELOPE")
    header = SubElement(envelope, "HEADER")
    SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = SubElement(envelope, "BODY")
    importdata = SubElement(body, "IMPORTDATA")

    requestdesc = SubElement(importdata, "REQUESTDESC")
    SubElement(requestdesc, "REPORTNAME").text = "Vouchers"

    if company:
        staticvariables = SubElement(requestdesc, "STATICVARIABLES")
        SubElement(staticvariables, "SVCURRENTCOMPANY").text = company

    requestdata = SubElement(importdata, "REQUESTDATA")
    tallymessage = SubElement(requestdata, "TALLYMESSAGE")
    voucher = SubElement(tallymessage, "VOUCHER", VCHTYPE=voucher_mapping.voucher_type, ACTION=voucher_action)

    SubElement(voucher, "DATE").text = voucher_mapping.date
    SubElement(voucher, "VOUCHERNUMBER").text = voucher_mapping.voucher_number
    SubElement(voucher, "PARTYLEDGERNAME").text = voucher_mapping.party_ledger_name
    SubElement(voucher, "NARRATION").text = voucher_mapping.narration

    for entry in voucher_mapping.entries:
        ledger_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        SubElement(ledger_entry, "LEDGERNAME").text = entry.ledger_name
        SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes" if entry.entry_type == "debit" else "No"
        SubElement(ledger_entry, "AMOUNT").text = str(entry.amount)

    return envelope


def build_tally_xml(
    invoice: dict[str, Any],
    *,
    company: str | None = None,
    voucher_type: str | None = None,
    voucher_action: str = "Create",
) -> str:
    voucher_mapping = map_invoice_to_voucher(invoice, config={"voucher_type": voucher_type})
    root = _build_xml_tree(voucher_mapping, company=company, voucher_action=voucher_action)
    return tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def generate_tally_xml(
    invoice: dict[str, Any],
    output_path: str,
    *,
    company: str | None = None,
    voucher_type: str | None = None,
    voucher_action: str = "Create",
    config: dict[str, Any] | None = None,
) -> None:
    config = config or {}
    if voucher_type is not None:
        config = {**config, "voucher_type": voucher_type}
    voucher_mapping = map_invoice_to_voucher(invoice, config=config)
    root = _build_xml_tree(voucher_mapping, company=company, voucher_action=voucher_action)
    tree = ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
