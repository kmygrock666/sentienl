
import unittest
from unittest.mock import MagicMock, patch
from sentinel.intraday.fetcher import MISFetcher

class TestMISFetcher(unittest.TestCase):
    def setUp(self):
        self.fetcher = MISFetcher()
        self.fetcher._initialized = True # Skip session initialization

    @patch("requests.Session.get")
    def test_fetch_batch_success_with_json_content_type(self, mock_get):
        # Mock valid JSON with application/json header
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json;charset=UTF-8"}
        mock_response.json.return_value = {"msgArray": [{"c": "2330", "z": "100.0"}]}
        mock_get.return_value = mock_response

        results = self.fetcher.fetch_batch(["2330"], ["TWSE"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["c"], "2330")

    @patch("requests.Session.get")
    def test_fetch_batch_success_with_html_content_type(self, mock_get):
        # Mock valid JSON with text/html header (the problematic case)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html;charset=UTF-8"}
        mock_response.json.return_value = {"msgArray": [{"c": "2330", "z": "100.0"}]}
        mock_get.return_value = mock_response

        results = self.fetcher.fetch_batch(["2330"], ["TWSE"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["c"], "2330")

    @patch("requests.Session.get")
    def test_fetch_batch_failure_with_real_html(self, mock_get):
        # Mock real HTML content (JSON parsing should fail)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html;charset=UTF-8"}
        mock_response.text = "<html><body>Maintenance</body></html>"
        mock_response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        mock_get.return_value = mock_response

        results = self.fetcher.fetch_batch(["2330"], ["TWSE"], max_retries=1)
        self.assertEqual(results, [])

    @patch("requests.Session.get")
    def test_fetch_batch_unexpected_content_type(self, mock_get):
        # Mock unexpected content type (e.g., image/png)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/png"}
        mock_get.return_value = mock_response

        results = self.fetcher.fetch_batch(["2330"], ["TWSE"], max_retries=1)
        self.assertEqual(results, [])

if __name__ == "__main__":
    unittest.main()
