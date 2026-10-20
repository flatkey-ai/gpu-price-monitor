"""Browser lifecycle and credential isolation without launching a browser."""

import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from gpu_price_monitor.browser import AUTODL_PUBLIC_URL, fetch_autodl_pages
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


class BrowserFailure(Exception):
    pass


class BrowserDeadline(BrowserFailure):
    pass


class PublicBrowserTests(unittest.TestCase):
    def setUp(self):
        sync_api = ModuleType("playwright.sync_api")
        sync_api.Error = BrowserFailure
        sync_api.TimeoutError = BrowserDeadline
        manager = MagicMock()
        sync_api.sync_playwright = MagicMock(return_value=manager)
        self.driver = manager.__enter__.return_value
        self.browser = self.driver.chromium.launch.return_value
        self.context = self.browser.new_context.return_value
        self.page = self.context.new_page.return_value
        self.page.url = AUTODL_PUBLIC_URL
        self.page.goto.return_value.status = 200
        self.section = self.page.locator.return_value.filter.return_value
        self.active = MagicMock()
        self.active.inner_text.side_effect = ["普通用户", "炼丹会员"]
        self.section.locator.side_effect = lambda selector: self.active if selector == ".level-tab .active" else MagicMock()
        self.section.evaluate.side_effect = ["<ordinary />", "<member />"]
        modules = patch.dict(sys.modules, {"playwright": ModuleType("playwright"), "playwright.sync_api": sync_api})
        modules.start()
        self.addCleanup(modules.stop)
        clock = patch("gpu_price_monitor.browser.time.monotonic", return_value=0)
        clock.start()
        self.addCleanup(clock.stop)

    def test_fresh_context_ignores_tokens_and_storage_state_and_closes_browser(self):
        settings = Settings(max_retries=0, autodl_token="synthetic-secret-token",
                            autodl_storage_state_path="/nonexistent/synthetic-secret-session.json")
        pages = fetch_autodl_pages(settings)
        self.assertEqual(pages, ["<ordinary />", "<member />"])
        self.browser.new_context.assert_called_once_with(accept_downloads=False, service_workers="block")
        self.assertNotIn("storage_state", self.browser.new_context.call_args.kwargs)
        self.assertNotIn("synthetic-secret", str(self.driver.mock_calls))
        self.assertEqual(self.page.goto.call_args.args, (AUTODL_PUBLIC_URL,))
        self.browser.close.assert_called_once()

    def test_timeout_closes_browser_and_returns_static_retryable_error(self):
        self.page.goto.side_effect = BrowserDeadline("synthetic-secret-session and page content")
        with self.assertRaises(FetchError) as captured:
            fetch_autodl_pages(Settings(max_retries=0))
        self.assertEqual(captured.exception.code, "timeout")
        self.assertTrue(captured.exception.retryable)
        self.assertNotIn("synthetic-secret", str(captured.exception))
        self.browser.close.assert_called_once()

    def test_context_failure_closes_browser_and_hides_engine_error_details(self):
        self.browser.new_context.side_effect = BrowserFailure("synthetic-secret-engine-path")
        with self.assertRaises(FetchError) as captured:
            fetch_autodl_pages(Settings(max_retries=0))
        self.assertEqual(captured.exception.code, "browser_error")
        self.assertNotIn("synthetic-secret", str(captured.exception))
        self.browser.close.assert_called_once()

    def test_unexpected_origin_is_rejected_and_browser_is_closed(self):
        self.page.url = "https://example.invalid/private/synthetic-secret"
        with self.assertRaises(FetchError) as captured:
            fetch_autodl_pages(Settings(max_retries=0))
        self.assertEqual(captured.exception.code, "unexpected_page")
        self.assertNotIn("synthetic-secret", str(captured.exception))
        self.section.evaluate.assert_not_called()
        self.browser.close.assert_called_once()

    def test_missing_chromium_is_a_static_non_retryable_installation_error(self):
        self.driver.chromium.launch.side_effect = BrowserFailure("Executable doesn't exist at synthetic-secret-path")
        with self.assertRaises(FetchError) as captured:
            fetch_autodl_pages(Settings(max_retries=2))
        self.assertEqual(captured.exception.code, "browser_not_installed")
        self.assertFalse(captured.exception.retryable)
        self.assertNotIn("synthetic-secret", str(captured.exception))
        self.assertEqual(self.driver.chromium.launch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
