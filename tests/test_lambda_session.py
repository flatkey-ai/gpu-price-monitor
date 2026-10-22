"""Synthetic exported-session tests; no browser, user profile or live login."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gpu_price_monitor import lambda_session as session
from gpu_price_monitor.transport import FetchError


NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)
SECRET = "synthetic-secret-session-value"


def cookie(**changes):
    return {"name": "session", "value": SECRET, "domain": "cloud.lambda.ai", "path": "/",
            "expires": NOW.timestamp() + 3600, "httpOnly": True, "secure": True,
            "sameSite": "Lax", **changes}


class LambdaSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="synthetic-lambda-session-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "synthetic-private-session.json"
        self.settings = SimpleNamespace(lambda_storage_state_path=str(self.path))
        self.write([cookie()])

    def write(self, cookies, **extra):
        self.path.write_text(json.dumps({"cookies": cookies, **extra}), encoding="utf-8")

    def load(self, *, url=session.INSTANCE_TYPES_URL, now=NOW):
        return session.load_session_cookie_header(self.path, url, now)

    def assert_safe_error(self, operation, code=None):
        with self.assertRaises(FetchError) as raised:
            operation()
        if code:
            self.assertEqual(raised.exception.code, code)
        for secret in (SECRET, str(self.path), "private-local-storage", "synthetic-foreign-origin"):
            self.assertNotIn(secret, str(raised.exception))
            self.assertNotIn(secret, repr(raised.exception))
        return raised.exception

    def test_secure_exported_cookies_only_and_repr_is_redacted(self):
        self.write([cookie(), cookie(name="csrf", value="encoded%3Dvalue", domain=".lambda.ai")])
        header = self.load()
        self.assertIsInstance(header, str)
        self.assertEqual(header, "session=" + SECRET + "; csrf=encoded%3Dvalue")
        self.assertNotIn(SECRET, repr(header))
        self.assertNotIn(SECRET, repr({"Cookie": header}))

    def test_origins_and_local_storage_are_never_credentials(self):
        self.write([cookie()], origins=[{"origin": "https://synthetic-foreign-origin.example",
                                        "localStorage": [{"name": "access_token", "value": "private-local-storage"}]}])
        self.assertEqual(self.load(), "session=" + SECRET)
        self.write([], origins=[{"origin": "https://cloud.lambda.ai",
                                 "localStorage": [{"name": "access_token", "value": SECRET}]}])
        self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_only_exact_cloud_domain_and_explicit_parent_domain_cookies(self):
        for domain in ("cloud.lambda.ai", ".cloud.lambda.ai", ".lambda.ai", "CLOUD.LAMBDA.AI"):
            with self.subTest(domain=domain):
                self.write([cookie(domain=domain)])
                self.assertEqual(self.load(), "session=" + SECRET)
        for domain in ("lambda.ai", "evil.lambda.ai", ".evil.lambda.ai", "cloud.lambda.ai.evil.example",
                       "lambda.ai.example", "evilcloud.lambda.ai", "https://cloud.lambda.ai", "cloud.lambda.ai."):
            with self.subTest(domain=domain):
                self.write([cookie(domain=domain)])
                self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_expiry_and_secure_flag_are_enforced_and_session_cookie_is_supported(self):
        self.write([cookie(name="expired", expires=NOW.timestamp()), cookie(name="insecure", secure=False),
                    cookie(expires=-1)])
        self.assertEqual(self.load(now=NOW.timestamp()), "session=" + SECRET)
        for changes in ({"expires": NOW.timestamp() - 1}, {"secure": False}, {"expires": 0}):
            with self.subTest(changes=changes):
                self.write([cookie(**changes)])
                self.assert_safe_error(self.load, "lambda_session_cookie_unavailable")

    def test_cookie_paths_use_slash_boundaries_and_longer_paths_first(self):
        self.write([cookie(name="root"), cookie(name="api", path="/api/internal"),
                    cookie(name="endpoint", path="/api/internal/dashboard/v1/instance-types"),
                    cookie(name="wrong", path="/api/internal/dash"), cookie(name="other", path="/elsewhere")])
        self.assertEqual(self.load(), "; ".join(name + "=" + SECRET for name in ("endpoint", "api", "root")))
        self.assertEqual(self.load(url=session.REGIONS_URL), "; ".join(name + "=" + SECRET for name in ("api", "root")))

    def test_foreign_and_noncanonical_urls_rejected_before_reading_any_file(self):
        for url in ("https://example.org/", session.BASE_URL + "/instance-types?region=secret",
                    session.INSTANCE_TYPES_URL + "#fragment", session.INSTANCE_TYPES_URL + "/",
                    session.INSTANCE_TYPES_URL.replace("https:", "http:"),
                    session.INSTANCE_TYPES_URL.replace("cloud.lambda.ai", "cloud.lambda.ai:443"),
                    session.INSTANCE_TYPES_URL.replace("cloud.lambda.ai", "user@cloud.lambda.ai"),
                    session.INSTANCE_TYPES_URL.replace("cloud.lambda.ai", "cloud.lambda.ai.evil.example"),
                    session.BASE_URL + "/instances/launch", None):
            with self.subTest(url=url), patch.object(session, "_read_state") as read:
                self.assert_safe_error(lambda: self.load(url=url), "lambda_session_url_rejected")
                read.assert_not_called()

    def test_malformed_cookie_fields_and_header_injection_are_rejected_without_secrets(self):
        cases = ({"name": "bad\r\nCookie"}, {"value": SECRET + "\r\nX: bad"},
                 {"value": SECRET + "; other=bad"}, {"value": "quoted\"cookie"}, {"value": "nonascii-\u2603"},
                 {"path": "/api\nprivate"}, {"secure": 1}, {"httpOnly": "yes"},
                 {"sameSite": "invalid"}, {"sameSite": []}, {"expires": True}, {"expires": -2}, {"expires": "tomorrow"},
                 {"domain": "cloud.lambda.ai\r\n"})
        for changes in cases:
            with self.subTest(changes=changes):
                self.write([cookie(**changes)])
                self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_cookie_prefix_guarantees_and_duplicate_names(self):
        self.write([cookie(name="__Host-session")])
        self.assertEqual(self.load(), "__Host-session=" + SECRET)
        for cookies in ([cookie(name="__Host-session", domain=".lambda.ai")],
                        [cookie(name="__Host-session", path="/api")],
                        [cookie(name="__Secure-session", secure=False)],
                        [cookie(), cookie(domain=".lambda.ai", value="other")],
                        [cookie(), deepcopy(cookie())]):
            with self.subTest(cookies=cookies):
                self.write(cookies)
                self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_bad_files_json_duplicate_keys_nonfinite_and_oversize_are_private(self):
        for raw in (SECRET, '{"cookies":[],"cookies":[]}', '{"cookies":NaN}', '[]', '{}',
                    '{"cookies":[{"value":Infinity}]}', '{"cookies":null}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                self.assert_safe_error(self.load, "lambda_session_invalid")
        self.path.write_bytes(b"x" * (session.MAX_SESSION_BYTES + 1))
        self.assert_safe_error(self.load, "lambda_session_invalid")
        self.path.write_bytes(b"\xff\xfe" + SECRET.encode())
        self.assert_safe_error(self.load, "lambda_session_invalid")
        self.path.unlink()
        self.assert_safe_error(self.load, "lambda_session_unavailable")
        self.path.mkdir()
        self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_size_cookie_count_and_header_limits(self):
        self.write([cookie(name="n" + str(i)) for i in range(session.MAX_COOKIE_COUNT + 1)])
        self.assert_safe_error(self.load, "lambda_session_invalid")
        self.write([cookie(value="x" * session.MAX_COOKIE_HEADER_BYTES)])
        self.assert_safe_error(self.load, "lambda_session_invalid")

    def test_aware_clock_required_and_nonfinite_expiry_rejected(self):
        for now in (datetime(2026, 10, 22), True, float("inf"), float("nan"), "tomorrow"):
            with self.subTest(now=now):
                self.assert_safe_error(lambda: self.load(now=now), "lambda_session_invalid")
        for expiry in (float("inf"), float("nan")):
            self.write([cookie(expires=expiry)])
            self.assert_safe_error(self.load, "lambda_session_invalid")

    @patch("gpu_price_monitor.lambda_session.request_json")
    def test_client_can_only_make_three_authenticated_gets_and_ignores_other_credentials(self, request):
        request.return_value = {"data": []}
        self.settings.lambda_api_key = "unused-api-key"
        client = session.LambdaConsoleSession(self.settings, now=NOW)
        for method, url in ((client.get_instance_types, session.INSTANCE_TYPES_URL),
                            (client.get_reserved_cluster_types, session.RESERVED_CLUSTER_TYPES_URL),
                            (client.get_regions, session.REGIONS_URL)):
            self.assertEqual(method(), {"data": []})
            request.assert_called_with(url, self.settings, method="GET", headers={"Cookie": "session=" + SECRET}, authenticated=True)
        self.assertEqual(request.call_count, 3)
        self.assertNotIn(SECRET, repr(client))
        self.assertNotIn(SECRET, repr(request.call_args))
        self.assert_safe_error(lambda: client.get_json(session.BASE_URL + "/launch"), "lambda_session_url_rejected")
        self.assertEqual(request.call_count, 3)

    @patch("gpu_price_monitor.lambda_session.request_json")
    def test_explicit_path_overrides_settings_and_missing_file_never_sends_http(self, request):
        request.return_value = {}
        client = session.LambdaConsoleSession(SimpleNamespace(), storage_state_path=self.path, now=NOW)
        self.assertEqual(client.get_regions(), {})
        request.reset_mock()
        self.assert_safe_error(lambda: session.LambdaConsoleSession(SimpleNamespace()).get_regions(), "lambda_session_missing")
        self.path.unlink()
        self.assert_safe_error(client.get_regions, "lambda_session_unavailable")
        request.assert_not_called()

    @patch("gpu_price_monitor.lambda_session.request_json")
    def test_login_expiry_and_redirect_errors_propagate_once_without_fallback(self, request):
        client = session.LambdaConsoleSession(self.settings, now=NOW)
        for code in ("authentication_error", "redirect_rejected", "invalid_json"):
            with self.subTest(code=code):
                request.reset_mock()
                request.side_effect = FetchError(code, "Lambda console session rejected.")
                self.assert_safe_error(client.get_instance_types, code)
                request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
