import unittest
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from gpu_price_monitor import Settings
from gpu_price_monitor.transport import FetchError, _NoRedirect, fetch_text, request_json
from decimal import Decimal


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

    def test_explicit_bulk_limit_remains_bounded_and_rejects_invalid_limits_before_io(self):
        with patch("gpu_price_monitor.transport.urlopen", return_value=self.response(b'{"ok":1}')):
            with self.assertRaises(FetchError) as raised:
                request_json("https://example.com", Settings(max_retries=0), max_response_bytes=7)
        self.assertEqual(raised.exception.code, "response_too_large")
        for limit in (0, True, 32 * 1024 * 1024 + 1):
            with self.subTest(limit=limit), patch("gpu_price_monitor.transport.urlopen") as opener:
                with self.assertRaises(FetchError):
                    request_json("https://example.com", Settings(max_retries=0), max_response_bytes=limit)
                opener.assert_not_called()

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

    def test_authenticated_redirect_is_rejected_without_exposing_credentials(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError("https://example.com", 302, "secret-message", {}, None)
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            with self.assertRaises(FetchError) as raised:
                request_json("https://example.com", Settings(max_retries=0), headers={"Authorization": "Bearer secret-key"}, authenticated=True)
        self.assertEqual(raised.exception.code, "redirect_rejected")
        self.assertNotIn("secret", str(raised.exception))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))
        self.assertEqual(opener.open.call_count, 1)

    def test_authenticated_unauthorized_becomes_safe_authentication_error(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError("https://example.com", 401, "secret", {}, None)
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            with self.assertRaises(FetchError) as raised:
                request_json("https://example.com", Settings(max_retries=0), authenticated=True)
        self.assertEqual(raised.exception.code, "authentication_error")

    def test_json_money_remains_decimal_and_invalid_json_is_safe(self):
        with patch("gpu_price_monitor.transport.urlopen", return_value=self.response(b'{"Price":0.42}')):
            payload = request_json("https://example.com", Settings(max_retries=0))
        self.assertEqual(payload["Price"], Decimal("0.42"))
        for body in (b'secret-upstream-body', b'[]', b'{"Price":NaN}'):
            with self.subTest(body=body):
                with patch("gpu_price_monitor.transport.urlopen", return_value=self.response(body)):
                    with self.assertRaises(FetchError) as raised:
                        request_json("https://example.com", Settings(max_retries=0))
                self.assertEqual(raised.exception.code, "invalid_json")
                self.assertNotIn("secret", str(raised.exception))

    def test_authenticated_plain_http_and_header_injection_never_send_request(self):
        with patch("gpu_price_monitor.transport.build_opener") as opener:
            with self.assertRaises(FetchError):
                request_json("http://example.com", Settings(), authenticated=True)
            with self.assertRaises(FetchError):
                request_json("https://example.com", Settings(), authenticated=True, headers={"Authorization": "secret\r\ninjection"})
        opener.assert_not_called()

    def test_excessively_deep_json_is_a_safe_structured_error(self):
        with patch("gpu_price_monitor.transport._request_text", return_value="{}"):
            with patch("gpu_price_monitor.transport.json.loads", side_effect=RecursionError("private response")):
                with self.assertRaises(FetchError) as raised:
                    request_json("https://example.com", Settings(max_retries=0))
        self.assertEqual(raised.exception.code, "invalid_json")
        self.assertNotIn("private response", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
