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
