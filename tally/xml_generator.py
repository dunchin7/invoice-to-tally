from xml.etree.ElementTree import Element, ElementTree, SubElement, tostring


def _party_ledger_name(party):
    if isinstance(party, dict):
        return party.get("name") or "Unknown Party"
    return str(party)


def build_tally_xml(
    invoice: dict,
    *,
    company: str | None = None,
    voucher_type: str = "Sales",
    voucher_action: str = "Create",
) -> str:
    envelope = Element("ENVELOPE")

    header = SubElement(envelope, "HEADER")
    tallyrequest = SubElement(header, "TALLYREQUEST")
    tallyrequest.text = "Import Data"

    body = SubElement(envelope, "BODY")
    importdata = SubElement(body, "IMPORTDATA")

    requestdesc = SubElement(importdata, "REQUESTDESC")
    reportname = SubElement(requestdesc, "REPORTNAME")
    reportname.text = "Vouchers"

    if company:
        staticvariables = SubElement(requestdesc, "STATICVARIABLES")
        SubElement(staticvariables, "SVCURRENTCOMPANY").text = company

    requestdata = SubElement(importdata, "REQUESTDATA")
    tallymessage = SubElement(requestdata, "TALLYMESSAGE")

    voucher = SubElement(tallymessage, "VOUCHER", VCHTYPE=voucher_type, ACTION=voucher_action)

    SubElement(voucher, "DATE").text = invoice["invoice_date"]
    SubElement(voucher, "VOUCHERNUMBER").text = invoice["invoice_number"]
    buyer_ledger = _party_ledger_name(invoice.get("buyer"))
    SubElement(voucher, "PARTYLEDGERNAME").text = buyer_ledger
    SubElement(voucher, "NARRATION").text = "Imported from Invoice AI"

    for item in invoice["line_items"]:
        ledger_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        SubElement(ledger_entry, "LEDGERNAME").text = "Sales"
        SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "No"
        SubElement(ledger_entry, "AMOUNT").text = str(item["total_price"])

    if invoice.get("tax", 0) > 0:
        tax_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        SubElement(tax_entry, "LEDGERNAME").text = "Tax"
        SubElement(tax_entry, "ISDEEMEDPOSITIVE").text = "No"
        SubElement(tax_entry, "AMOUNT").text = str(invoice["tax"])

    party_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

    SubElement(party_entry, "LEDGERNAME").text = buyer_ledger
    SubElement(party_entry, "ISDEEMEDPOSITIVE").text = "Yes"
    SubElement(party_entry, "AMOUNT").text = str(invoice["total"])

    return tostring(envelope, encoding="utf-8", xml_declaration=True).decode("utf-8")


def generate_tally_xml(
    invoice: dict,
    output_path: str,
    *,
    company: str | None = None,
    voucher_type: str = "Sales",
    voucher_action: str = "Create",
):
    xml_content = build_tally_xml(
        invoice,
        company=company,
        voucher_type=voucher_type,
        voucher_action=voucher_action,
    )
    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(xml_content)
