import tempfile
import unittest
from xml.etree import ElementTree

from tally.xml_generator import VoucherBalanceError, generate_tally_xml, map_invoice_to_voucher


class TallyXMLGeneratorTests(unittest.TestCase):
    def _base_invoice(self):
        return {
            "schema_version": "2.0",
            "invoice_number": "INV-1001",
            "invoice_type": "tax_invoice",
            "invoice_date": "2025-01-31",
            "seller": {"name": "ABC Pvt Ltd"},
            "buyer": {"name": "XYZ Traders"},
            "currency": "INR",
            "line_items": [],
            "subtotal": 0,
            "tax": 0,
            "total": 0,
        }

    def test_intrastate_mixed_tax_rates_maps_cgst_and_sgst(self):
        invoice = self._base_invoice()
        invoice["line_items"] = [
            {"description": "Item A", "taxable_value": 1000, "cgst_amount": 90, "sgst_amount": 90, "igst_amount": 0, "tax_amount": 180, "total_price": 1180},
            {"description": "Item B", "taxable_value": 500, "cgst_amount": 30, "sgst_amount": 30, "igst_amount": 0, "tax_amount": 60, "total_price": 560},
        ]
        invoice["subtotal"] = 1500
        invoice["tax"] = 240
        invoice["total"] = 1740

        mapping = map_invoice_to_voucher(invoice)

        self.assertEqual(mapping.date, "20250131")
        self.assertEqual(mapping.voucher_type, "Sales")
        ledger_amounts = {(e.ledger_name, e.entry_type): float(e.amount) for e in mapping.entries}
        self.assertEqual(ledger_amounts[("Sales", "credit")], 1500.0)
        self.assertEqual(ledger_amounts[("CGST", "credit")], 120.0)
        self.assertEqual(ledger_amounts[("SGST", "credit")], 120.0)
        self.assertEqual(ledger_amounts[("XYZ Traders", "debit")], 1740.0)

    def test_interstate_uses_igst_ledger_and_custom_ledger_names(self):
        invoice = self._base_invoice()
        invoice["line_items"] = [
            {"description": "Item C", "taxable_value": 1000, "igst_amount": 180, "tax_amount": 180, "total_price": 1180}
        ]
        invoice["subtotal"] = 1000
        invoice["tax"] = 180
        invoice["total"] = 1180

        config = {
            "ledger_names": {
                "sales": "Sales @18%",
                "igst": "Output IGST 18%",
                "receivables": "Sundry Debtors",
            }
        }

        mapping = map_invoice_to_voucher(invoice, config=config)

        ledger_amounts = {(e.ledger_name, e.entry_type): float(e.amount) for e in mapping.entries}
        self.assertEqual(ledger_amounts[("Sales @18%", "credit")], 1000.0)
        self.assertEqual(ledger_amounts[("Output IGST 18%", "credit")], 180.0)
        self.assertEqual(ledger_amounts[("Sundry Debtors", "debit")], 1180.0)

    def test_round_off_and_voucher_type_override_and_xml_serialization(self):
        invoice = self._base_invoice()
        invoice["invoice_type"] = "receipt"
        invoice["line_items"] = [
            {"description": "Item D", "taxable_value": 1000, "igst_amount": 180, "tax_amount": 180, "total_price": 1180}
        ]
        invoice["subtotal"] = 1000
        invoice["tax"] = 180
        invoice["total"] = 1180.25

        with tempfile.NamedTemporaryFile(suffix=".xml") as handle:
            generate_tally_xml(
                invoice,
                handle.name,
                config={"voucher_type": "Receipt", "ledger_names": {"round_off": "Round Off Adj"}},
            )
            xml_root = ElementTree.parse(handle.name).getroot()

        voucher = xml_root.find("./BODY/IMPORTDATA/REQUESTDATA/TALLYMESSAGE/VOUCHER")
        self.assertIsNotNone(voucher)
        self.assertEqual(voucher.attrib["VCHTYPE"], "Receipt")
        self.assertEqual(voucher.findtext("DATE"), "20250131")

        ledgers = [
            (
                node.findtext("LEDGERNAME"),
                node.findtext("ISDEEMEDPOSITIVE"),
                node.findtext("AMOUNT"),
            )
            for node in voucher.findall("ALLLEDGERENTRIES.LIST")
        ]
        self.assertIn(("Round Off Adj", "No", "0.25"), ledgers)

    def test_purchase_invoice_flips_polarity_with_input_gst_ledgers(self):
        invoice = self._base_invoice()
        invoice["seller"] = {"name": "ACME Suppliers Pvt Ltd", "gstin": "27AAAPL1234C1Z5"}
        invoice["buyer"] = {"name": "Our Trading Co", "gstin": "29AABCS1429B1ZS"}
        invoice["line_items"] = [
            {"description": "Raw Material", "taxable_value": 10000, "cgst_amount": 900, "sgst_amount": 900, "igst_amount": 0, "tax_amount": 1800, "total_price": 11800},
        ]
        invoice["subtotal"] = 10000
        invoice["tax"] = 1800
        invoice["total"] = 11800
        invoice["direction"] = "purchase"

        mapping = map_invoice_to_voucher(invoice)

        self.assertEqual(mapping.voucher_type, "Purchase")
        ledger_amounts = {(e.ledger_name, e.entry_type): float(e.amount) for e in mapping.entries}
        # Vendor (seller) is credited (payable)
        self.assertEqual(ledger_amounts[("ACME Suppliers Pvt Ltd", "credit")], 11800.0)
        # Purchase ledger is debited (expense)
        self.assertEqual(ledger_amounts[("Purchase", "debit")], 10000.0)
        # Input GST is debited (ITC asset)
        self.assertEqual(ledger_amounts[("Input CGST", "debit")], 900.0)
        self.assertEqual(ledger_amounts[("Input SGST", "debit")], 900.0)

    def test_purchase_interstate_uses_input_igst(self):
        invoice = self._base_invoice()
        invoice["seller"] = {"name": "Karnataka Vendor"}
        invoice["buyer"] = {"name": "TN Customer"}
        invoice["line_items"] = [
            {"description": "Services", "taxable_value": 50000, "igst_amount": 9000, "tax_amount": 9000, "total_price": 59000},
        ]
        invoice["subtotal"] = 50000
        invoice["tax"] = 9000
        invoice["total"] = 59000

        mapping = map_invoice_to_voucher(invoice, config={"direction": "purchase"})

        ledger_amounts = {(e.ledger_name, e.entry_type): float(e.amount) for e in mapping.entries}
        self.assertEqual(ledger_amounts[("Karnataka Vendor", "credit")], 59000.0)
        self.assertEqual(ledger_amounts[("Purchase", "debit")], 50000.0)
        self.assertEqual(ledger_amounts[("Input IGST", "debit")], 9000.0)
        # No output GST entries
        self.assertNotIn(("CGST", "credit"), ledger_amounts)
        self.assertNotIn(("IGST", "credit"), ledger_amounts)

    def test_purchase_credit_note_becomes_debit_note_voucher(self):
        invoice = self._base_invoice()
        invoice["invoice_type"] = "credit_note"
        invoice["seller"] = {"name": "Vendor X"}
        invoice["buyer"] = {"name": "Our Co"}
        invoice["line_items"] = [
            {"description": "Returned item", "taxable_value": 1000, "cgst_amount": 90, "sgst_amount": 90, "tax_amount": 180, "total_price": 1180},
        ]
        invoice["subtotal"] = 1000
        invoice["tax"] = 180
        invoice["total"] = 1180

        mapping = map_invoice_to_voucher(invoice, config={"direction": "purchase"})

        # Vendor-side credit note (refund from vendor) should post as a Debit Note in our books
        self.assertEqual(mapping.voucher_type, "Debit Note")

    def test_unbalanced_invoice_raises_error(self):
        invoice = self._base_invoice()
        invoice["line_items"] = [
            {"description": "Item E", "taxable_value": 1000, "cgst_amount": 90, "sgst_amount": 90, "tax_amount": 180, "total_price": 1180}
        ]
        invoice["subtotal"] = 1000
        invoice["tax"] = 180
        invoice["total"] = 1000

        with self.assertRaises(VoucherBalanceError):
            map_invoice_to_voucher(invoice)


if __name__ == "__main__":
    unittest.main()
