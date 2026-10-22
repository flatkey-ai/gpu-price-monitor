"""Manual Lambda login and private session persistence use mocked browsers only."""

from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from gpu_price_monitor import ConfigurationError
from gpu_price_monitor import lambda_login
from gpu_price_monitor.transport import FetchError


LOGIN_URL = "https://cloud.lambda.ai/"
CHECK_URL = "https://cloud.lambda.ai/api/internal/dashboard/v1/instance-types"
PRIVATE = "synthetic-private-cookie-value"


def cookie(domain="cloud.lambda.ai", name="session"):
    return {"name": name, "value": PRIVATE, "domain": domain, "path": "/", "expires": -1,
            "httpOnly": True, "secure": True, "sameSite": "Lax"}


class LambdaLoginTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "private-lambda-session.json"
        self.stderr = io.StringIO()
        self.stack.enter_context(redirect_stderr(self.stderr))
        self.transport = self.stack.enter_context(patch(
            "gpu_price_monitor.transport._request_text",
            side_effect=AssertionError("Login tests must not issue real HTTP"),
        ))
        self.socket = self.stack.enter_context(patch(
            "socket.create_connection", side_effect=AssertionError("Login tests must not open sockets"),
        ))
        self.playwright = MagicMock(name="playwright")
        self.browser = self.playwright.chromium.launch.return_value
        self.context = self.browser.new_context.return_value
        self.page = self.context.new_page.return_value
        self.page.is_closed.return_value = False
        self.response = self.context.request.get.return_value
        self.response.status = 200
        self.response.json.return_value = {"data": {}}
        self.context.cookies.return_value = [cookie()]
        self.factory = MagicMock(name="sync_playwright")
        self.factory.return_value.__enter__.return_value = self.playwright
        package = types.ModuleType("playwright")
        package.__path__ = []
        sync = types.ModuleType("playwright.sync_api")
        sync.sync_playwright = self.factory
        sync.TimeoutError = type("MockPlaywrightTimeoutError", (Exception,), {})
        sync.Error = type("MockPlaywrightError", (Exception,), {})
        self.stack.enter_context(patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": sync}))
        self.clock = {"now": 0.0}
        self.stack.enter_context(patch("gpu_price_monitor.lambda_login.time.monotonic",
                                       side_effect=lambda: self.clock["now"]))
        self.page.wait_for_timeout.side_effect = lambda milliseconds: self.advance_clock(milliseconds / 1000)

    def advance_clock(self, seconds):
        self.clock["now"] += max(float(seconds), 0.1)

    def tearDown(self):
        self.transport.assert_not_called()
        self.socket.assert_not_called()

    def assert_private_output(self, exception=None):
        text = self.stderr.getvalue() + (str(exception) if exception is not None else "")
        self.assertNotIn(str(self.path), text)
        self.assertNotIn(PRIVATE, text)

    def test_manual_login_uses_a_new_browser_and_only_the_fixed_read_only_probe(self):
        lambda_login.save_lambda_session(self.path)
        self.playwright.chromium.launch.assert_called_once()
        launch_options = self.playwright.chromium.launch.call_args.kwargs
        self.assertIs(launch_options["headless"], False)
        self.assertGreater(launch_options["timeout"], 0)
        self.assertLessEqual(launch_options["timeout"], 300000)
        self.playwright.chromium.launch_persistent_context.assert_not_called()
        self.browser.new_context.assert_called_once_with(accept_downloads=False)
        self.assertEqual(self.page.goto.call_args.args[0], LOGIN_URL)
        self.assertTrue(self.context.request.get.called)
        self.assertTrue(all(call.args[0] == CHECK_URL for call in self.context.request.get.call_args_list))
        for request in self.context.request.get.call_args_list:
            self.assertIs(request.kwargs["fail_on_status_code"], False)
            self.assertEqual(request.kwargs["max_redirects"], 0)
            self.assertGreater(request.kwargs["timeout"], 0)
            self.assertLessEqual(request.kwargs["timeout"], 5000)
        self.context.request.post.assert_not_called()
        self.context.request.put.assert_not_called()
        self.context.request.delete.assert_not_called()
        self.page.click.assert_not_called()
        self.page.fill.assert_not_called()
        self.context.cookies.assert_called_once_with([LOGIN_URL])
        self.context.storage_state.assert_not_called()
        self.page.evaluate.assert_not_called()
        self.browser.close.assert_called_once()
        self.assert_private_output()

    def test_success_saves_only_scoped_cookies_with_empty_origins_and_private_permissions(self):
        expected = [cookie(domain, f"session-{index}") for index, domain in enumerate(
            ("cloud.lambda.ai", ".cloud.lambda.ai", ".lambda.ai"))]
        self.context.cookies.return_value = expected
        lambda_login.save_lambda_session(self.path, timeout_seconds=10)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"cookies": expected, "origins": []})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])
        self.assert_private_output()

    def test_cookie_export_rejects_foreign_domains_without_saving_them(self):
        for domain in ("evil.invalid", "lambda.ai", "cloud.lambda.ai.evil.invalid"):
            self.context.cookies.return_value = [cookie(), cookie(domain, "other")]
            with self.subTest(domain=domain), self.assertRaises(FetchError) as raised:
                lambda_login.save_lambda_session(self.path, timeout_seconds=1)
            self.assertEqual(raised.exception.code, "session_save_failed")
            self.assertFalse(self.path.exists())
            self.assert_private_output(raised.exception)

    def test_login_instructions_explain_manual_sign_in_without_account_mutations(self):
        lambda_login.save_lambda_session(self.path)
        text = " ".join(self.stderr.getvalue().lower().split())
        self.assertRegex(text, r"manual|手动")
        self.assertRegex(text, r"payment|付款|支付")
        self.assertRegex(text, r"resource|资源")
        self.assert_private_output()

    def test_existing_destination_is_rejected_before_launching_or_overwriting(self):
        self.path.write_text("existing-private-session", encoding="utf-8")
        with self.assertRaises(ConfigurationError) as raised:
            lambda_login.save_lambda_session(self.path)
        self.assertEqual(self.path.read_text(), "existing-private-session")
        self.factory.assert_not_called()
        self.assert_private_output(raised.exception)

    def test_invalid_timeout_is_rejected_without_opening_a_browser(self):
        for value in (None, True, False, 0, -1, 301, float("inf"), float("nan"), "300"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as raised:
                lambda_login.save_lambda_session(self.path, timeout_seconds=value)
            self.assert_private_output(raised.exception)
        self.factory.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_probe_retries_until_a_200_data_object_is_available(self):
        unauthenticated = MagicMock(status=401)
        wrong_schema = MagicMock(status=200)
        wrong_schema.json.return_value = {"data": []}
        valid = MagicMock(status=200)
        valid.json.return_value = {"data": {"synthetic-sku": {}}}
        self.context.request.get.side_effect = [unauthenticated, wrong_schema, valid]
        lambda_login.save_lambda_session(self.path, timeout_seconds=10)
        self.assertEqual(self.context.request.get.call_count, 3)
        self.assertTrue(self.path.exists())
        self.assert_private_output()

    def test_probe_timeout_never_saves_a_session_or_exposes_response_content(self):
        self.response.status = 401
        self.response.json.return_value = {"error": {"message": PRIVATE}}
        with self.assertRaises(FetchError) as raised:
            lambda_login.save_lambda_session(self.path, timeout_seconds=1)
        self.assertEqual(raised.exception.code, "timeout")
        self.assertFalse(self.path.exists())
        self.context.cookies.assert_not_called()
        self.browser.close.assert_called_once()
        self.assert_private_output(raised.exception)

    def test_malformed_json_does_not_count_as_success(self):
        self.response.json.side_effect = ValueError(PRIVATE)
        with self.assertRaises(FetchError) as raised:
            lambda_login.save_lambda_session(self.path, timeout_seconds=1)
        self.assertEqual(raised.exception.code, "timeout")
        self.assertFalse(self.path.exists())
        self.assert_private_output(raised.exception)

    def test_browser_launch_errors_are_redacted(self):
        self.playwright.chromium.launch.side_effect = RuntimeError(PRIVATE + str(self.path))
        with self.assertRaises(FetchError) as raised:
            lambda_login.save_lambda_session(self.path, timeout_seconds=1)
        self.assertIn(raised.exception.code, {"browser_error", "browser_not_installed"})
        self.assertFalse(self.path.exists())
        self.assert_private_output(raised.exception)

    def test_missing_optional_playwright_dependency_is_reported_without_installing(self):
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(FetchError) as raised:
                lambda_login.save_lambda_session(self.path)
        self.assertEqual(raised.exception.code, "browser_dependency_missing")
        self.assertFalse(self.path.exists())
        self.assert_private_output(raised.exception)

    def test_writer_creates_a_private_file_without_browser_or_storage_access(self):
        cookies = [cookie()]
        before = deepcopy(cookies)
        lambda_login._write_session(self.path, cookies)
        self.assertEqual(json.loads(self.path.read_text()), {"cookies": cookies, "origins": []})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(cookies, before)
        self.factory.assert_not_called()

    def test_writer_does_not_overwrite_an_existing_file(self):
        self.path.write_text("existing-private-session", encoding="utf-8")
        with self.assertRaises((ConfigurationError, FetchError)) as raised:
            lambda_login._write_session(self.path, [cookie()])
        self.assertEqual(self.path.read_text(), "existing-private-session")
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])
        self.assert_private_output(raised.exception)

    def test_writer_creates_a_missing_parent_with_private_directory_permissions(self):
        destination = Path(self.directory.name) / "new-private-directory" / "session.json"
        lambda_login._write_session(destination, [cookie()])
        self.assertEqual(stat.S_IMODE(destination.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(json.loads(destination.read_text())["origins"], [])

    def test_writer_preserves_an_existing_parent_directory_permissions(self):
        parent = Path(self.directory.name) / "existing-directory"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        lambda_login._write_session(parent / "session.json", [cookie()])
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)

    def test_writer_cannot_overwrite_a_destination_created_during_publication(self):
        def race(source, destination, **kwargs):
            Path(destination).write_text("concurrent-private-session", encoding="utf-8")
            raise FileExistsError(PRIVATE)

        with patch("gpu_price_monitor.lambda_login.os.link", side_effect=race):
            with self.assertRaises((ConfigurationError, FetchError)) as raised:
                lambda_login._write_session(self.path, [cookie()])
        self.assertEqual(self.path.read_text(), "concurrent-private-session")
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])
        self.assert_private_output(raised.exception)

    def test_writer_failure_removes_temporary_files_and_redacts_os_errors(self):
        for operation in ("fsync", "link"):
            with self.subTest(operation=operation), patch(
                f"gpu_price_monitor.lambda_login.os.{operation}",
                side_effect=OSError(PRIVATE + str(self.path)),
            ):
                with self.assertRaises(FetchError) as raised:
                    lambda_login._write_session(self.path, [cookie()])
                self.assertEqual(raised.exception.code, "session_save_failed")
                self.assertEqual(list(Path(self.directory.name).iterdir()), [])
                self.assert_private_output(raised.exception)


if __name__ == "__main__":
    unittest.main()
