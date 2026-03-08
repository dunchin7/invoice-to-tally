from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable
from xml.etree.ElementTree import Element, ElementTree, SubElement


TWOPLACES = Decimal("0.01")
DEFAULT_LEDGER_NAMES = {
    "sales": "Sales",
    "cgst": "CGST",
    "sgst": "SGST",
    "igst": "IGST",
    "round_off": "Round Off",
    "receivables": None,
}
DEFAULT_VOUCHER_TYPES = {
    "tax_invoice": "Sales",
    "credit_note": "Credit Note",
    "debit_note": "Debit Note",
    "proforma_invoice": "Sales",
    "receipt": "Receipt",
    None: "Sales",
}


@dataclass(frozen=True)
class VoucherLedgerEntry:
    ledger_name: str
    amount: Decimal
    entry_type: str  # "debit" or "credit"


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
    parsed = datetime.strptime(invoice_date, "%Y-%m-%d")
    return parsed.strftime("%Y%m%d")


def _resolve_voucher_type(invoice: dict[str, Any], config: dict[str, Any]) -> str:
    configured = config.get("voucher_type")
    if configured:
        return str(configured)

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
        return configured_ledgers[role]

    return _resolve


def _collect_amounts(invoice: dict[str, Any]) -> dict[str, Decimal]:
    line_items = invoice.get("line_items", [])

    taxable = Decimal("0")
    cgst = Decimal("0")
    sgst = Decimal("0")
    igst = Decimal("0")

    for item in line_items:
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
        tax_total = _to_decimal(invoice.get("tax"))
        # Fallback: when only total tax is known, treat as IGST.
        igst = tax_total

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
    debit = sum((entry.amount for entry in entries if entry.entry_type == "debit"), Decimal("0"))
    credit = sum((entry.amount for entry in entries if entry.entry_type == "credit"), Decimal("0"))

    debit = _quantize(debit)
    credit = _quantize(credit)

    if debit != credit:
        raise VoucherBalanceError(f"Unbalanced voucher entries: debit={debit} credit={credit}")


def map_invoice_to_voucher(invoice: dict[str, Any], config: dict[str, Any] | None = None) -> VoucherMapping:
    config = config or {}
    ledger_resolver = _build_ledger_resolver(config)

    amounts = _collect_amounts(invoice)
    receivables_ledger = ledger_resolver("receivables", invoice)

    entries: list[VoucherLedgerEntry] = [
        VoucherLedgerEntry(ledger_name=receivables_ledger, amount=amounts["total"], entry_type="debit"),
        VoucherLedgerEntry(ledger_name=ledger_resolver("sales", invoice), amount=amounts["taxable"], entry_type="credit"),
    ]

    for tax_role in ("cgst", "sgst", "igst"):
        amount = amounts[tax_role]
        if amount > 0:
            entries.append(
                VoucherLedgerEntry(
                    ledger_name=ledger_resolver(tax_role, invoice),
                    amount=amount,
                    entry_type="credit",
                )
            )

    max_round_off = _to_decimal(config.get("max_round_off", "1.00"))
    if abs(amounts["round_off"]) > max_round_off:
        raise VoucherBalanceError(
            f"Round-off {amounts['round_off']} exceeds configured threshold {max_round_off}"
        )

    if amounts["round_off"] != 0:
        round_off_amount = abs(amounts["round_off"])
        round_off_type = "credit" if amounts["round_off"] > 0 else "debit"
        entries.append(
            VoucherLedgerEntry(
                ledger_name=ledger_resolver("round_off", invoice),
                amount=round_off_amount,
                entry_type=round_off_type,
            )
        )

    _validate_balancing(entries)

    return VoucherMapping(
        date=_normalize_tally_date(invoice["invoice_date"]),
        voucher_number=str(invoice["invoice_number"]),
        voucher_type=_resolve_voucher_type(invoice, config),
        party_ledger_name=receivables_ledger,
        narration=config.get("narration") or "Imported from Invoice AI",
        entries=entries,
    )


def serialize_voucher_mapping(voucher_mapping: VoucherMapping, output_path: str) -> None:
    envelope = Element("ENVELOPE")

    header = SubElement(envelope, "HEADER")
    SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = SubElement(envelope, "BODY")
    importdata = SubElement(body, "IMPORTDATA")

    requestdesc = SubElement(importdata, "REQUESTDESC")
    SubElement(requestdesc, "REPORTNAME").text = "Vouchers"

    requestdata = SubElement(importdata, "REQUESTDATA")
    tallymessage = SubElement(requestdata, "TALLYMESSAGE")

    voucher = SubElement(tallymessage, "VOUCHER", VCHTYPE=voucher_mapping.voucher_type, ACTION="Create")

    SubElement(voucher, "DATE").text = voucher_mapping.date
    SubElement(voucher, "VOUCHERNUMBER").text = voucher_mapping.voucher_number
    SubElement(voucher, "PARTYLEDGERNAME").text = voucher_mapping.party_ledger_name
    SubElement(voucher, "NARRATION").text = voucher_mapping.narration

    for entry in voucher_mapping.entries:
        ledger_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        SubElement(ledger_entry, "LEDGERNAME").text = entry.ledger_name
        SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "Yes" if entry.entry_type == "debit" else "No"
        SubElement(ledger_entry, "AMOUNT").text = f"{entry.amount:.2f}"

    tree = ElementTree(envelope)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def generate_tally_xml(invoice: dict[str, Any], output_path: str, config: dict[str, Any] | None = None) -> None:
    voucher_mapping = map_invoice_to_voucher(invoice, config=config)
    serialize_voucher_mapping(voucher_mapping, output_path)
