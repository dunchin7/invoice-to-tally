import unittest
from unittest.mock import Mock, patch

import requests

from tally.client import TallyClient, TallyClientConfig, parse_tally_response


class TallyClientTests(unittest.TestCase):
    def test_parse_success_acknowledgement(self):
        xml = """
        <ENVELOPE><BODY><DATA><IMPORTRESULT>
        <CREATED>1</CREATED><ALTERED>0</ALTERED><IGNORED>0</IGNORED><ERRORS>0</ERRORS>
        </IMPORTRESULT></DATA></BODY></ENVELOPE>
        """
        status = parse_tally_response(xml, endpoint="http://localhost:9000")
        self.assertTrue(status.ok)
        self.assertEqual(status.created, 1)

    def test_parse_failure_acknowledgement(self):
        xml = """
        <ENVELOPE><BODY><DATA><IMPORTRESULT>
        <CREATED>0</CREATED><ALTERED>0</ALTERED><IGNORED>1</IGNORED><ERRORS>1</ERRORS>
        <LINEERROR>Ledger not found</LINEERROR>
        </IMPORTRESULT></DATA></BODY></ENVELOPE>
        """
        status = parse_tally_response(xml, endpoint="http://localhost:9000")
        self.assertFalse(status.ok)
        self.assertIn("Ledger not found", status.line_errors)

    @patch("tally.client.time.sleep")
    @patch("tally.client.requests.post")
    def test_retries_transient_network_failures(self, post_mock: Mock, _sleep_mock: Mock):
        response = Mock()
        response.text = "<ENVELOPE><CREATED>1</CREATED><ERRORS>0</ERRORS></ENVELOPE>"
        response.raise_for_status.return_value = None
        post_mock.side_effect = [requests.ConnectionError("down"), response]

        client = TallyClient(TallyClientConfig(max_retries=2, retry_backoff_seconds=0.01))
        status = client.upload_xml("<xml/>")

        self.assertTrue(status.ok)
        self.assertEqual(post_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
