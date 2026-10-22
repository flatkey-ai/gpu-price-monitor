"""Use an explicitly exported Lambda session for three read-only price routes.

Only Playwright's cookies array is used. Browser profiles, localStorage and
saved origins are never used as credentials. A cookie-bearing request never
follows redirects and cannot be sent outside the fixed Lambda URL allowlist.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .transport import FetchError, request_json


BASE_URL = "https://cloud.lambda.ai/api/internal/dashboard/v1"
INSTANCE_TYPES_URL = BASE_URL + "/instance-types"
RESERVED_CLUSTER_TYPES_URL = BASE_URL + "/cluster-types/reserved"
REGIONS_URL = BASE_URL + "/regions"
ALLOWED_URLS = frozenset({INSTANCE_TYPES_URL, RESERVED_CLUSTER_TYPES_URL, REGIONS_URL})
MAX_SESSION_BYTES = 1024 * 1024
MAX_COOKIE_COUNT = 512
MAX_COOKIE_HEADER_BYTES = 32 * 1024
# The leading dot in a Playwright domain identifies a domain cookie. A bare
# lambda.ai cookie is host-only and is not applicable to cloud.lambda.ai.
_COOKIE_DOMAINS = frozenset({"cloud.lambda.ai", ".cloud.lambda.ai", ".lambda.ai"})
_COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,256}\Z")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*\Z")


class _CookieHeader(str):
    """Avoid accidental disclosure in a request-options repr or traceback."""

    def __repr__(self) -> str:
        return "<redacted Lambda session cookies>"


def _invalid() -> FetchError:
    return FetchError("lambda_session_invalid", "The exported Lambda session has an invalid cookie structure.")


def _validate_url(url: str) -> str:
    # Exact comparison also rejects usernames, ports, queries, fragments,
    # alternate hosts, encoded paths and prefix/suffix lookalikes.
    if not isinstance(url, str) or url not in ALLOWED_URLS:
        raise FetchError("lambda_session_url_rejected", "Only the three fixed Lambda console pricing GET URLs are allowed.")
    return urlsplit(url).path


def _timestamp(now: datetime | int | float | None) -> float:
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise _invalid()
        try:
            result = now.timestamp()
        except (OverflowError, OSError, ValueError):
            raise _invalid() from None
    elif type(now) in (int, float):
        try:
            result = float(now)
        except (OverflowError, ValueError):
            raise _invalid() from None
    else:
        raise _invalid()
    if not math.isfinite(result):
        raise _invalid()
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _reject_constant(value: str):
    raise _invalid()


def _read_state(path: str | os.PathLike) -> dict:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        # Check the opened descriptor, rather than trusting a prior path stat.
        # NONBLOCK avoids blocking on a pipe substituted for an exported file.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(resolved, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SESSION_BYTES:
                raise _invalid()
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None  # The file object now owns the descriptor.
                raw = stream.read(MAX_SESSION_BYTES + 1)
        finally:
            if descriptor is not None:
                os.close(descriptor)
    except FetchError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise FetchError("lambda_session_unavailable", "The explicitly configured Lambda session file is unavailable.") from None
    if len(raw) > MAX_SESSION_BYTES:
        raise _invalid()
    try:
        state = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except FetchError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise _invalid() from None
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise _invalid()
    return state


def _path_matches(cookie_path: str, request_path: str) -> bool:
    return (cookie_path == request_path or (request_path.startswith(cookie_path)
            and (cookie_path.endswith("/") or request_path[len(cookie_path):].startswith("/"))))


def load_session_cookie_header(path: str | os.PathLike, url: str,
                               now: datetime | int | float | None = None) -> str:
    """Read only applicable Secure cookies from the caller's exported file.

    The returned value is a secret request header, not result metadata. Expired,
    non-Secure and nonmatching-path cookies are not sent. Foreign cookie domains
    and malformed cookie fields reject the file without exposing its contents.
    Session cookies (expires=-1) require the server to validate the login.
    """
    request_path, instant = _validate_url(url), _timestamp(now)
    cookies = _read_state(path)["cookies"]
    if not cookies or len(cookies) > MAX_COOKIE_COUNT:
        raise _invalid()
    selected, names = [], set()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise _invalid()
        name, value, domain, cookie_path = (cookie.get(key) for key in ("name", "value", "domain", "path"))
        expiry, secure = cookie.get("expires"), cookie.get("secure")
        if (not isinstance(name, str) or not _COOKIE_NAME.fullmatch(name)
                or not isinstance(value, str) or not _COOKIE_VALUE.fullmatch(value)
                or not isinstance(domain, str) or domain.lower() not in _COOKIE_DOMAINS
                or not isinstance(cookie_path, str) or not cookie_path.startswith("/")
                or any(ord(char) < 32 or ord(char) == 127 for char in cookie_path)
                or type(secure) is not bool or type(cookie.get("httpOnly")) is not bool
                or not isinstance(cookie.get("sameSite"), str)
                or cookie.get("sameSite") not in {"Strict", "Lax", "None"}
                or type(expiry) not in (int, float)):
            raise _invalid()
        try:
            expiry = float(expiry)
        except (OverflowError, ValueError):
            raise _invalid() from None
        if not math.isfinite(expiry) or (expiry < 0 and expiry != -1):
            raise _invalid()
        if name.startswith("__Host-") and (domain.lower() != "cloud.lambda.ai" or cookie_path != "/" or not secure):
            raise _invalid()
        if name.startswith("__Secure-") and not secure:
            raise _invalid()
        if not secure or (expiry != -1 and expiry <= instant) or not _path_matches(cookie_path, request_path):
            continue
        # Sending the same name from overlapping scopes can make which login
        # is selected server-dependent. Require the user to export one session.
        if name in names:
            raise _invalid()
        names.add(name)
        selected.append((cookie_path, name + "=" + value))
    if not selected:
        raise FetchError("lambda_session_cookie_unavailable", "No unexpired Secure cookie applies to this Lambda console endpoint; export a current session.")
    selected.sort(key=lambda item: -len(item[0]))
    header = "; ".join(value for _, value in selected)
    if len(header) > MAX_COOKIE_HEADER_BYTES:
        raise _invalid()
    return _CookieHeader(header)


class LambdaConsoleSession:
    """GET-only client; it never logs in, launches instances or requests quotes."""

    def __init__(self, settings, *, storage_state_path: str | os.PathLike | None = None,
                 now: datetime | int | float | None = None):
        self._settings = settings
        self._state_path = (storage_state_path if storage_state_path is not None
                            else getattr(settings, "lambda_storage_state_path", None))
        self._now = now

    def get_json(self, url: str) -> dict:
        _validate_url(url)
        if not self._state_path:
            raise FetchError("lambda_session_missing", "Lambda console collection requires an explicitly exported session file.")
        cookie = load_session_cookie_header(self._state_path, url, self._now)
        # Authenticated transport rejects redirects, including redirects to the
        # login page. HTTP authentication failures propagate without fallback.
        return request_json(url, self._settings, method="GET", headers={"Cookie": cookie}, authenticated=True)

    def get_instance_types(self) -> dict:
        return self.get_json(INSTANCE_TYPES_URL)

    def get_reserved_cluster_types(self) -> dict:
        return self.get_json(RESERVED_CLUSTER_TYPES_URL)

    def get_regions(self) -> dict:
        return self.get_json(REGIONS_URL)
