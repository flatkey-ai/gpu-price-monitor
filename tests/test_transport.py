import unittest
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from gpu_price_monitor import Settings
from gpu_price_monitor.transport import FetchError, fetch_text


class TransportTests(unittest.TestCase):
    def response(self, body=b"public pricing"):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        response.headers = Message()
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    def test_transient_http_error_retries_and_preserves_decoding(self):
        error = HTTPError("https://example.com", 503, "private body", {}, None)
        with patch("gpu_price_monitor.transport.urlopen", side_effect=[error, self.response()]) as opener:
            with patch("gpu_price_monitor.transport.time.sleep"):
                self.assertEqual(fetch_text("https://example.com", Settings(max_retries=1)), "public pricing")
        self.assertEqual(opener.call_count, 2)

    def test_unauthorized_does_not_retry_or_leak_upstream_message(self):
        with patch("gpu_price_monitor.transport.urlopen", side_effect=HTTPError("https://example.com", 403, "private value", {}, None)) as opener:
            with self.assertRaises(FetchError) as raised:
                fetch_text("https://example.com", Settings(max_retries=2))
        self.assertFalse(raised.exception.retryable)
        self.assertNotIn("private value", str(raised.exception))
        self.assertEqual(opener.call_count, 1)

    def test_incomplete_http_response_returns_safe_network_error(self):
        response = self.response()
        response.read.side_effect = IncompleteRead(b"private partial body")
        with patch("gpu_price_monitor.transport.urlopen", return_value=response):
            with self.assertRaises(FetchError) as raised:
                fetch_text("https://example.com", Settings(max_retries=0))
        self.assertEqual(raised.exception.code, "network_error")
        self.assertNotIn("private", str(raised.exception))

    def test_response_size_is_bounded(self):
        with patch("gpu_price_monitor.transport.MAX_RESPONSE_BYTES", 2):
            with patch("gpu_price_monitor.transport.urlopen", return_value=self.response(b"123")):
                with self.assertRaises(FetchError) as raised:
                    fetch_text("https://example.com", Settings(max_retries=0))
        self.assertEqual(raised.exception.code, "response_too_large")

    def test_declared_length_detects_truncation_and_retries(self):
        short = self.response(b"incomplete")
        short.headers["Content-Length"] = "100"
        complete = self.response(b"ok")
        complete.headers["Content-Length"] = "2"
        with patch("gpu_price_monitor.transport.urlopen", side_effect=[short, complete]) as opener:
            with patch("gpu_price_monitor.transport.time.sleep"):
                self.assertEqual(fetch_text("https://example.com", Settings(max_retries=1)), "ok")
        self.assertEqual(opener.call_count, 2)

    def test_declared_length_failure_never_reaches_parser(self):
        short = self.response(b"incomplete")
        short.headers["Content-Length"] = "100"
        with patch("gpu_price_monitor.transport.urlopen", return_value=short):
            with self.assertRaises(FetchError) as raised:
                fetch_text("https://example.com", Settings(max_retries=0))
        self.assertEqual(raised.exception.code, "response_incomplete")


if __name__ == "__main__":
    unittest.main()
