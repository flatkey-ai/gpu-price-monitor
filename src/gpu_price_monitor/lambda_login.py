"""Save a dedicated Lambda session after the user signs in manually.

This optional local-browser helper never reads an existing browser profile,
enters credentials, adds payment details, or creates cloud resources. Only
cookies applicable to the fixed Lambda console origin are saved; local storage
and unrelated origins are excluded.
"""

from __future__ import annotations

from contextlib import suppress
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

from .settings import ConfigurationError
from .transport import FetchError


ORIGIN = "https://cloud.lambda.ai/"
PROBE_URL = "https://cloud.lambda.ai/api/internal/dashboard/v1/instance-types"
_COOKIE_DOMAINS = {"cloud.lambda.ai", ".cloud.lambda.ai", ".lambda.ai"}
_COOKIE_KEYS = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
_MAX_STATE_BYTES = 256 * 1024


def _destination(path: str | Path) -> Path:
    try:
        destination = Path(path)
        if os.path.lexists(destination):
            exists = True
        else:
            exists = False
    except (OSError, TypeError, ValueError):
        raise ConfigurationError("Session destination must be a valid new file.") from None
    if exists:
        raise ConfigurationError("Session destination already exists. Choose a new file or move the existing file first.")
    try:
        if not destination.name:
            raise OSError
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not destination.parent.is_dir():
            raise OSError
    except OSError:
        raise ConfigurationError("The Lambda session directory could not be prepared.") from None
    return destination


def _session_state(cookies: object) -> dict:
    if not isinstance(cookies, list) or not cookies or len(cookies) > 1000:
        raise FetchError("session_save_failed", "No valid Lambda console cookies were available to save.")
    saved = []
    for cookie in cookies:
        if (not isinstance(cookie, dict) or cookie.keys() - _COOKIE_KEYS
                or not {"name", "value", "domain", "path"} <= cookie.keys()
                or not isinstance(cookie["domain"], str) or cookie["domain"] not in _COOKIE_DOMAINS
                or not isinstance(cookie["name"], str) or not cookie["name"]
                or not isinstance(cookie["value"], str)
                or not isinstance(cookie["path"], str) or not cookie["path"].startswith("/")):
            raise FetchError("session_save_failed", "The Lambda console cookies could not be safely scoped.")
        if any(key in cookie and type(cookie[key]) is not bool for key in ("httpOnly", "secure")):
            raise FetchError("session_save_failed", "The Lambda console cookie structure was not recognized.")
        if "sameSite" in cookie and (not isinstance(cookie["sameSite"], str)
                                    or cookie["sameSite"] not in {"Strict", "Lax", "None"}):
            raise FetchError("session_save_failed", "The Lambda console cookie structure was not recognized.")
        if "expires" in cookie and (type(cookie["expires"]) not in {int, float}
                                     or type(cookie["expires"]) is float and not math.isfinite(cookie["expires"])):
            raise FetchError("session_save_failed", "The Lambda console cookie structure was not recognized.")
        saved.append(dict(cookie))
    return {"cookies": saved, "origins": []}


def _write_session(path: str | Path, cookies: list[dict]) -> None:
    """Publish a complete private file atomically without replacing any path."""
    destination = _destination(path)
    state = _session_state(cookies)
    try:
        encoded = json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > _MAX_STATE_BYTES:
            raise FetchError("session_save_failed", "The Lambda session exceeds the supported file size.")
    except (TypeError, ValueError, UnicodeError):
        raise FetchError("session_save_failed", "The Lambda session could not be safely serialized.") from None
    temporary, descriptor = None, None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".lambda-session-", dir=destination.parent)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # link() is atomic and fails if the destination appeared while the
        # user was signing in. rename()/replace() could overwrite that file.
        os.link(temporary, destination)
    except FileExistsError:
        raise ConfigurationError("Session destination already exists. Choose a new file or move the existing file first.") from None
    except OSError:
        raise FetchError("session_save_failed", "The Lambda session could not be securely saved.") from None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


def save_lambda_session(path: str | Path, *, timeout_seconds: float = 300) -> None:
    """Open a fresh browser and save scoped cookies after a read-only check.

    The caller chooses a new file. Its parent directory is prepared if needed.
    Nothing is saved
    unless the fixed console instance-catalog GET returns HTTP 200 and a JSON
    data object. The function never executes the login flow on the user's behalf.
    """
    if (type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 300
            or not math.isfinite(timeout_seconds)):
        raise ConfigurationError("Lambda login timeout must be finite and in (0, 300] seconds.")
    destination = _destination(path)
    try:
        from playwright.sync_api import Error as BrowserError
        from playwright.sync_api import TimeoutError as BrowserTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError("browser_dependency_missing", "Lambda login needs the optional browser extra and a local Playwright Chromium installation.") from None

    print("Lambda login: manually sign in using the new dedicated browser window. "
          "Do not add a payment method or create or reserve resources. "
          "Waiting for a read-only catalog check; no existing browser profile is used.", file=sys.stderr)
    deadline = time.monotonic() + timeout_seconds

    def remaining_ms() -> int:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout", "Lambda login was not verified within the allowed time.")
        return max(1, int(remaining * 1000))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False, timeout=remaining_ms())
            try:
                context = browser.new_context(accept_downloads=False)
                page = context.new_page()
                page.goto(ORIGIN, wait_until="domcontentloaded", timeout=remaining_ms())
                while True:
                    remaining_ms()
                    if page.is_closed():
                        raise FetchError("browser_error", "The dedicated login browser was closed before verification.")
                    response = None
                    verified = False
                    try:
                        response = context.request.get(PROBE_URL, fail_on_status_code=False, max_redirects=0,
                                                       timeout=min(5000, remaining_ms()))
                        if response.status == 200:
                            payload = response.json()
                            verified = isinstance(payload, dict) and isinstance(payload.get("data"), dict)
                    except (BrowserError, ValueError):
                        # Login redirects, incomplete authentication and a
                        # transient read failure are not a reason to save state.
                        pass
                    finally:
                        if response is not None:
                            with suppress(BrowserError):
                                response.dispose()
                    if verified:
                        _write_session(destination, context.cookies([ORIGIN]))
                        print("Lambda login verified. A new private session file was saved.", file=sys.stderr)
                        return
                    page.wait_for_timeout(min(1000, remaining_ms()))
            finally:
                with suppress(BrowserError):
                    browser.close()
    except BrowserTimeout:
        raise FetchError("timeout", "Lambda login was not verified within the allowed time.") from None
    except BrowserError as exc:
        if "Executable doesn't exist" in str(exc):
            raise FetchError("browser_not_installed", "Install the optional local Chromium browser with python -m playwright install chromium.") from None
        raise FetchError("browser_error", "The dedicated Lambda login browser could not complete verification.") from None
    except (ConfigurationError, FetchError):
        raise
    except Exception:
        raise FetchError("browser_error", "The dedicated Lambda login browser could not complete verification.") from None
