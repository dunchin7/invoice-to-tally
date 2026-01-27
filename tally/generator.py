from xml.etree.ElementTree import Element, SubElement, ElementTree


def generate_tally_xml(invoice: dict, output_path: str):
    envelope = Element("ENVELOPE")

    header = SubElement(envelope, "HEADER")
    tallyrequest = SubElement(header, "TALLYREQUEST")
    tallyrequest.text = "Import Data"

    body = SubElement(envelope, "BODY")
    importdata = SubElement(body, "IMPORTDATA")

    requestdesc = SubElement(importdata, "REQUESTDESC")
    reportname = SubElement(requestdesc, "REPORTNAME")
    reportname.text = "Vouchers"

    requestdata = SubElement(importdata, "REQUESTDATA")
    tallymessage = SubElement(requestdata, "TALLYMESSAGE")

    voucher = SubElement(tallymessage, "VOUCHER", VCHTYPE="Sales", ACTION="Create")

    # Basic fields
    SubElement(voucher, "DATE").text = invoice["invoice_date"]
    SubElement(voucher, "VOUCHERNUMBER").text = invoice["invoice_number"]
    SubElement(voucher, "PARTYLEDGERNAME").text = invoice["buyer"]
    SubElement(voucher, "NARRATION").text = "Imported from Invoice AI"

    # Ledger Entries (Sales)
    for item in invoice["line_items"]:
        ledger_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        SubElement(ledger_entry, "LEDGERNAME").text = "Sales"
        SubElement(ledger_entry, "ISDEEMEDPOSITIVE").text = "No"
        SubElement(ledger_entry, "AMOUNT").text = str(item["total_price"])

    # Tax Entry
    if invoice.get("tax", 0) > 0:
        tax_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

        SubElement(tax_entry, "LEDGERNAME").text = "Tax"
        SubElement(tax_entry, "ISDEEMEDPOSITIVE").text = "No"
        SubElement(tax_entry, "AMOUNT").text = str(invoice["tax"])

    # Party Ledger Entry (Receivable)
    party_entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")

    SubElement(party_entry, "LEDGERNAME").text = invoice["buyer"]
    SubElement(party_entry, "ISDEEMEDPOSITIVE").text = "Yes"
    SubElement(party_entry, "AMOUNT").text = str(invoice["total"])

    tree = ElementTree(envelope)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
