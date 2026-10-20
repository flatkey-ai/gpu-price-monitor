"""Optional local browser renderer for AutoDL's public homepage.

Always uses a fresh context. Saved sessions, API tokens and paid services are
not used. Nothing is purchased or launched on a cloud provider.
"""

from __future__ import annotations

from contextlib import suppress
import re
import time
from urllib.parse import urlsplit

from .settings import Settings
from .transport import FetchError, MAX_RESPONSE_BYTES

AUTODL_PUBLIC_URL = "https://www.autodl.com/home"


def _render_autodl(settings: Settings) -> list[str]:
    try:
        from playwright.sync_api import Error as BrowserError
        from playwright.sync_api import TimeoutError as BrowserTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError(
            "browser_dependency_missing",
            "AutoDL needs the free local browser extra: install 'flatkey-gpu-price-monitor[browser]' and run python -m playwright install chromium.",
        ) from None

    deadline = time.monotonic() + settings.timeout_seconds

    def remaining_ms() -> int:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout", "The AutoDL public page timed out.", True)
        return max(1, int(remaining * 1000))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=remaining_ms())
            try:
                context = browser.new_context(accept_downloads=False, service_workers="block")
                # Price text does not require images, videos or webfonts.
                context.route("**/*", lambda route: route.abort() if route.request.resource_type in
                              {"image", "media", "font"} else route.continue_())
                page = context.new_page()
                response = page.goto(AUTODL_PUBLIC_URL, wait_until="domcontentloaded", timeout=remaining_ms())
                if response is not None and response.status >= 400:
                    raise FetchError(
                        "rate_limited" if response.status == 429 else "http_error",
                        f"The AutoDL public page returned HTTP {response.status}.",
                        response.status == 429 or response.status >= 500,
                    )
                location = urlsplit(page.url)
                if (location.scheme != "https" or location.hostname not in {"www.autodl.com", "autodl.com"}
                        or location.path.rstrip("/") not in {"", "/home"}):
                    raise FetchError("unexpected_page", "AutoDL did not return its public pricing homepage.")
                section = page.locator(".display-module").filter(
                    has=page.locator(".header .title", has_text=re.compile(r"^\s*炼丹会员及租用价格\s*$")),
                )
                section.wait_for(state="visible", timeout=remaining_ms())
                pages = []
                for label in ("普通用户", "炼丹会员"):
                    tab = section.locator(".level-tab").get_by_text(label, exact=True)
                    tab.click(timeout=remaining_ms())
                    active = section.locator(".level-tab .active")
                    active.wait_for(state="visible", timeout=remaining_ms())
                    if active.inner_text(timeout=remaining_ms()).strip() != label:
                        raise FetchError("page_structure_changed", "AutoDL's selected public pricing tier could not be verified.")
                    section.locator(".member-gpu-price .gpu-item .price .text").first.wait_for(
                        state="visible", timeout=remaining_ms(),
                    )
                    content = section.evaluate("element => element.outerHTML", timeout=remaining_ms())
                    if len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
                        raise FetchError("response_too_large", "The rendered pricing section exceeds the size limit.")
                    pages.append(content)
                return pages
            finally:
                with suppress(BrowserError):
                    browser.close()
    except BrowserTimeout:
        raise FetchError("timeout", "The AutoDL public page timed out.", True) from None
    except BrowserError as exc:
        if "Executable doesn't exist" in str(exc):
            raise FetchError("browser_not_installed", "Install the free local Chromium browser with python -m playwright install chromium.") from None
        if "net::ERR" in str(exc):
            raise FetchError("network_error", "The AutoDL public page could not be reached by the local browser.", True) from None
        raise FetchError("browser_error", "The local browser could not read AutoDL's public price page.") from None


def fetch_autodl_pages(settings: Settings) -> list[str]:
    """Read normal-user and membership tariffs without any account session."""
    for attempt in range(settings.max_retries + 1):
        try:
            return _render_autodl(settings)
        except FetchError as exc:
            if not exc.retryable or attempt == settings.max_retries:
                raise
            time.sleep(min(2 ** attempt, 8))
    raise FetchError("browser_error", "The local browser could not read AutoDL's public price page.")
