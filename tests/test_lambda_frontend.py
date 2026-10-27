"""Synthetic frontend/version tests; no user login, local state or network."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gpu_price_monitor import lambda_frontend as frontend
from gpu_price_monitor import lambda_session
from gpu_price_monitor.providers import lambda_console, lambda_locations
from gpu_price_monitor.transport import FetchError


SCRIPT = "/* synthetic reviewed bundle */ export const price = 616;"
DIGEST = hashlib.sha256(SCRIPT.encode("utf-8")).hexdigest()
ENTRY_PATH = "/static/cloud-app/assets/main-SyntheticReviewed.js"
ENTRY_URL = "https://cloud.lambda.ai" + ENTRY_PATH
HTML = '<!doctype html><script type="module" src="' + ENTRY_PATH + '"></script>'
SECRET = "synthetic-private-cookie"


class LambdaFrontendTests(unittest.TestCase):
    def test_current_fingerprint_matches_reviewed_shared_sku_flow_record(self):
        review = json.loads((Path(__file__).parent / "fixtures" /
                             "lambda-console-frontend-review-20261027.json").read_text())
        self.assertEqual(frontend.REVIEWED_SOURCE_URL, review["source_url"])
        self.assertEqual(frontend.REVIEWED_SHA256, review["source_sha256"])
        self.assertEqual(lambda_console.FRONTEND_SOURCE_URL, review["source_url"])
        self.assertEqual(lambda_locations.FRONTEND_SOURCE_URL, review["source_url"])
        self.assertEqual(lambda_locations.FRONTEND_SOURCE_SHA256, review["source_sha256"])
        self.assertEqual(lambda_locations.VERIFIED_ON, review["verified_on"])
        self.assertEqual(review["reviewed_scope"], "currently_selectable_standard_regions")
        self.assertFalse(review["independent_region_quotes"])
        self.assertFalse(review["final_checkout_verified"])
        fragments = review["reviewed_fragments"]
        # The reviewed region callbacks only change selected configuration state.
        # They contain no new catalog/price request or SKU-price mutation.
        for name in ("instance_region_selection", "cluster_region_selection"):
            self.assertIn("region=e", fragments[name])
            self.assertNotIn("price_cents", fragments[name])
            self.assertNotIn("getInstanceTypes", fragments[name])
            self.assertNotIn("getReservedClusterTypes", fragments[name])

    def setUp(self):
        self.session = Mock(spec=["get_console_html"])
        self.session.get_console_html.return_value = HTML
        self.settings = SimpleNamespace(timeout_seconds=1, max_retries=0)

    def verify(self):
        with patch.object(frontend, "REVIEWED_SHA256", DIGEST):
            return frontend.verify_frontend_version(self.session, self.settings)

    def assert_private(self, result):
        serialized = json.dumps(result)
        for private in (SECRET, "/private/synthetic-session.json", "private-response-body"):
            self.assertNotIn(private, serialized)

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_matching_reviewed_hash_verifies_one_observed_public_script_without_cookies(self, request):
        request.return_value = SCRIPT
        result = self.verify()
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source_url"], ENTRY_URL)
        self.assertEqual(result["sha256"], DIGEST)
        self.assertEqual(result["reviewed_sha256"], DIGEST)
        self.session.get_console_html.assert_called_once_with()
        request.assert_called_once_with(
            ENTRY_URL, self.settings, method="GET",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/javascript,*/*;q=0.1"},
            authenticated=True,
        )
        headers = request.call_args.kwargs["headers"]
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_changed_bundle_does_not_reuse_previous_review(self, request):
        request.return_value = SCRIPT + "export const changed = true;"
        result = self.verify()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "frontend_version_changed")
        self.assertNotEqual(result["sha256"], DIGEST)
        self.assertEqual(result["source_url"], ENTRY_URL)

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_exact_origin_and_canonical_entry_path_only(self, request):
        sources = (
            "https://evil.example" + ENTRY_PATH,
            "https://cloud.lambda.ai.evil.example" + ENTRY_PATH,
            "https://evil@cloud.lambda.ai" + ENTRY_PATH,
            "https://cloud.lambda.ai:443" + ENTRY_PATH,
            "http://cloud.lambda.ai" + ENTRY_PATH,
            "https://CLOUD.LAMBDA.AI" + ENTRY_PATH,
            ENTRY_PATH + "?cookie=" + SECRET,
            ENTRY_PATH + "?",
            ENTRY_PATH + "#" + SECRET,
            ENTRY_PATH + "#",
            "/static/cloud-app/assets/main-%2f.js",
            "/static/cloud-app/assets/main-../fake.js",
            "/static/cloud-app/assets/chunk-Synthetic.js",
            "/another/assets/main-Synthetic.js",
            " " + ENTRY_PATH,
            ENTRY_PATH + "\t",
            "https:\\cloud.lambda.ai" + ENTRY_PATH,
        )
        for source in sources:
            with self.subTest(source=source):
                self.session.get_console_html.return_value = '<script src="' + source + '"></script>'
                result = self.verify()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["reason_code"], "frontend_entry_unrecognized")
                self.assertNotIn("source_url", result)
                self.assert_private(result)
        request.assert_not_called()

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_absolute_and_origin_relative_observed_scripts_are_supported(self, request):
        request.return_value = SCRIPT
        for source in (ENTRY_PATH, ENTRY_URL, "//cloud.lambda.ai" + ENTRY_PATH):
            with self.subTest(source=source):
                self.session.get_console_html.return_value = '<script src="' + source + '"></script>'
                self.assertEqual(self.verify()["status"], "verified")
        self.assertEqual(request.call_count, 3)

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_missing_or_ambiguous_entry_or_document_base_never_fetches_guessed_url(self, request):
        for html in ("", "<html>Please sign in</html>", None, {}, HTML + HTML,
                     HTML + '<script src="/static/cloud-app/assets/main-Other.js"></script>',
                     '<base href="https://evil.example/">' + HTML):
            with self.subTest(html=html):
                self.session.get_console_html.return_value = html
                result = self.verify()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["reason_code"], "frontend_entry_unrecognized")
        request.assert_not_called()

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_shell_failure_is_static_and_never_fetches_script(self, request):
        for code in ("authentication_error", "redirect_rejected", "network_error"):
            with self.subTest(code=code):
                self.session.get_console_html.side_effect = FetchError(code, SECRET + " private-response-body")
                result = self.verify()
                self.assertEqual(result["reason_code"], "frontend_shell_unavailable")
                self.assert_private(result)
        request.assert_not_called()

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_static_script_403_redirect_and_network_errors_fail_closed_without_details(self, request):
        for code in ("authentication_error", "redirect_rejected", "network_error", "http_error"):
            with self.subTest(code=code):
                request.side_effect = FetchError(code, SECRET + " private-response-body")
                result = self.verify()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["reason_code"], "frontend_script_unavailable")
                self.assert_private(result)
        self.assertEqual(request.call_count, 4)

    @patch("gpu_price_monitor.lambda_frontend.transport._request_text")
    def test_invalid_script_payload_is_not_verified(self, request):
        for script in (None, {}, b"bytes", "unpaired-surrogate-\ud800"):
            with self.subTest(script=script):
                request.return_value = script
                result = self.verify()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["reason_code"], "frontend_script_invalid")

    @patch("gpu_price_monitor.lambda_session._request_text")
    def test_fixed_html_get_uses_only_applicable_exported_secure_cookies(self, request):
        instant = datetime(2026, 10, 22, tzinfo=timezone.utc)
        with TemporaryDirectory(prefix="synthetic-frontend-state-") as directory:
            path = Path(directory) / "synthetic-state.json"
            cookies = [{"name": "session", "value": SECRET, "domain": "cloud.lambda.ai",
                        "path": "/", "expires": instant.timestamp() + 3600,
                        "httpOnly": True, "secure": True, "sameSite": "Lax"},
                       {"name": "api_only", "value": "api-path-secret", "domain": "cloud.lambda.ai",
                        "path": "/api/", "expires": instant.timestamp() + 3600,
                        "httpOnly": True, "secure": True, "sameSite": "Lax"}]
            path.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
            settings = SimpleNamespace(lambda_storage_state_path=path)
            client = lambda_session.LambdaConsoleSession(settings, now=instant)
            request.return_value = HTML
            self.assertEqual(client.get_console_html(), HTML)
            request.assert_called_once_with(
                lambda_session.CONSOLE_HTML_URL, settings, method="GET",
                headers={"Cookie": "session=" + SECRET, "User-Agent": "Mozilla/5.0", "Accept": "text/html"},
                authenticated=True,
            )
            self.assertNotIn(SECRET, repr(request.call_args))
            with self.assertRaises(FetchError) as error:
                client.get_json(lambda_session.CONSOLE_HTML_URL)
            self.assertEqual(error.exception.code, "lambda_session_url_rejected")
            self.assertEqual(len(lambda_session.ALLOWED_URLS), 3)
            self.assertEqual(lambda_session.COOKIE_ALLOWED_URLS,
                             lambda_session.ALLOWED_URLS | {lambda_session.CONSOLE_HTML_URL})

    @patch("gpu_price_monitor.lambda_session._request_text")
    def test_html_missing_session_and_redirect_propagate_without_fallback(self, request):
        client = lambda_session.LambdaConsoleSession(SimpleNamespace())
        with self.assertRaises(FetchError) as error:
            client.get_console_html()
        self.assertEqual(error.exception.code, "lambda_session_missing")
        request.assert_not_called()
        with patch.object(lambda_session, "load_session_cookie_header", return_value="session=" + SECRET):
            client = lambda_session.LambdaConsoleSession(SimpleNamespace(), storage_state_path="/private/synthetic-session.json")
            request.side_effect = FetchError("redirect_rejected", "Authenticated requests do not follow redirects.")
            with self.assertRaises(FetchError) as error:
                client.get_console_html()
            self.assertEqual(error.exception.code, "redirect_rejected")
            request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
