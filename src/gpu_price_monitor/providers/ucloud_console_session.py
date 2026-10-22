"""Explicit local UCloud session, restricted to read-only catalog/quote actions.

Only a caller-exported minimal JSON file is read. This module never accesses
browser profiles or evaluates copied shell commands. Requests use the reviewed
console protocol and never forward cookies through redirects.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlencode

from ..settings import Settings
from ..transport import FetchError, request_json

API_URL = "https://api.ucloud.cn"
CONSOLE_ORIGIN = "https://console.ucloud.cn"
PRICING_PAGE = CONSOLE_ORIGIN + "/uhost/uhost/gpu_create"
EXPORT_FORMAT = "ucloud-console-visible-cookie-v1"
MAX_SESSION_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
ALLOWED_ACTIONS = frozenset({
    "GetDataForConsoleVersion", "ListRegions", "ListZones",
    "DescribeAvailableInstanceTypes", "DescribeAvailableGpuTypeConfigs",
    "DescribeUHostMachineTypeAvailableZones", "DescribeImage",
    "GetUHostInstancePrice",
})
_COOKIE_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*\Z")
_HEADER_VALUE = re.compile(r"[\x21-\x7e]+\Z")
_PARAMETER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]*\Z")


def _invalid_session() -> FetchError:
    return FetchError("session_invalid", "UCLOUD_SESSION_PATH must identify a private, minimal UCloud console session JSON file.")


def _cookie_pairs(header: object) -> list[tuple[str, str]]:
    if (not isinstance(header, str) or not header or len(header) > 65536
            or not re.fullmatch(r"[\x20-\x7e]+", header)):
        raise _invalid_session()
    pairs = []
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if not separator or not _COOKIE_NAME.fullmatch(name) or not _COOKIE_VALUE.fullmatch(value):
            raise _invalid_session()
        pairs.append((name, value))
    if len(pairs) > 1000:
        raise _invalid_session()
    return pairs


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid_session()
        result[key] = value
    return result


def _load_cookie(path: str | Path | None) -> str:
    if path is None or path == "":
        raise FetchError("login_required", "Export a UCloud console session and configure UCLOUD_SESSION_PATH.")
    descriptor = None
    try:
        session_path = Path(path).expanduser()
        if session_path.is_symlink():
            raise _invalid_session()
        descriptor = os.open(session_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SESSION_BYTES or info.st_nlink != 1:
            raise _invalid_session()
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise _invalid_session()
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(MAX_SESSION_BYTES + 1)
        if len(raw) > MAX_SESSION_BYTES:
            raise _invalid_session()
        state = json.loads(raw, object_pairs_hook=_unique_fields)
        if (not isinstance(state, dict) or set(state) != {"format", "origin", "cookie"}
                or state["format"] != EXPORT_FORMAT or state["origin"] != CONSOLE_ORIGIN):
            raise _invalid_session()
        _cookie_pairs(state["cookie"])
        return state["cookie"]
    except FetchError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise _invalid_session() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _csrf_headers(cookie: str, *, bootstrap: bool = False) -> dict[str, str]:
    # The published services.js takes the first cookie and decodeURIComponent.
    # The bootstrap instead builds a last-wins map from split('=')[1]. Preserve
    # these distinct behaviors; blank channel_key is an optional empty header.
    values = {}
    for name, value in _cookie_pairs(cookie):
        if name not in {"CSRF_TOKEN", "U_CSRF_TOKEN", "channel_key"}:
            continue
        try:
            if bootstrap:
                values[name] = value.split("=", 1)[0]
            elif name not in values:
                if re.search(r"%(?![0-9A-Fa-f]{2})", value):
                    raise ValueError
                values[name] = unquote(value, errors="strict")
        except (ValueError, UnicodeError):
            raise FetchError("session_invalid", "The UCloud session contains an invalid CSRF value.") from None
    result = {}
    for name, target in (("CSRF_TOKEN", "CSRF-Token"), ("U_CSRF_TOKEN", "U-CSRF-Token"), ("channel_key", "channel-key")):
        value = values.get(name)
        if not value:
            continue
        if len(value) > 8192 or not _HEADER_VALUE.fullmatch(value):
            raise FetchError("session_invalid", "The UCloud session contains an invalid CSRF value.")
        result[target] = value
    if not {"CSRF-Token", "U-CSRF-Token"} & result.keys():
        raise FetchError("login_required", "The exported UCloud session has no CSRF authorization; export the logged-in console request again.")
    return result


def _request_body(action: str, parameters: Mapping | None) -> bytes:
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise FetchError("action_not_allowed", "Only reviewed UCloud catalog and quote actions are allowed.")
    if parameters is not None and not isinstance(parameters, Mapping):
        raise FetchError("invalid_request", "UCloud request parameters must be a mapping of scalar values.")
    params = dict(parameters or {})
    if len(params) > 256:
        raise FetchError("invalid_request", "UCloud request parameters exceed the supported limit.")
    for name, value in params.items():
        if isinstance(name, str) and name.lower() == "action":
            raise FetchError("action_not_allowed", "The selected UCloud action cannot be overridden.")
        if not isinstance(name, str) or len(name) > 128 or not _PARAMETER_NAME.fullmatch(name):
            raise FetchError("invalid_request", "UCloud request parameters contain an invalid name.")
        if (type(value) not in (str, int, bool, float, Decimal)
                or isinstance(value, str) and len(value) > 16384
                or isinstance(value, float) and not math.isfinite(value)
                or isinstance(value, Decimal) and not value.is_finite()):
            raise FetchError("invalid_request", "UCloud request parameters must contain bounded scalar values.")
    params["Action"] = action
    try:
        body = urlencode(params).encode("ascii")
    except (ValueError, UnicodeError, TypeError):
        raise FetchError("invalid_request", "UCloud request parameters could not be encoded.") from None
    if len(body) > MAX_SESSION_BYTES:
        raise FetchError("invalid_request", "UCloud request parameters exceed the supported limit.")
    return body


class UCloudConsoleSession:
    """A minimal credential held in memory for one catalog collection."""

    __slots__ = ("_cookie",)

    def __init__(self, cookie: str):
        _cookie_pairs(cookie)
        self._cookie = cookie

    def __repr__(self) -> str:
        return "UCloudConsoleSession(<redacted>)"

    @classmethod
    def from_settings(cls, settings: Settings) -> UCloudConsoleSession:
        return cls(_load_cookie(settings.ucloud_session_path))

    def request(self, action: str, parameters: Mapping | None = None, *, settings: Settings) -> dict:
        """POST one allowlisted action; no arbitrary URLs or redirects."""
        data = _request_body(action, parameters)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": CONSOLE_ORIGIN, "Referer": PRICING_PAGE,
            "Cookie": self._cookie,
            **_csrf_headers(self._cookie, bootstrap=action == "GetDataForConsoleVersion"),
        }
        payload = request_json(API_URL + "?Action=" + action, settings, method="POST",
                               headers=headers, data=data, authenticated=True,
                               max_response_bytes=MAX_RESPONSE_BYTES)
        if not isinstance(payload, dict) or type(payload.get("RetCode")) is not int:
            raise FetchError("invalid_response", "UCloud returned an unexpected response structure.")
        code = payload["RetCode"]
        if code in {170, 172, 174}:
            raise FetchError("authentication_error", "UCloud rejected the exported session; sign in and export it again.")
        if code != 0:
            # Provider messages may contain session or account data; do not echo.
            raise FetchError("provider_rejected", "UCloud rejected the catalog or price request.")
        return payload


def request(action: str, parameters: Mapping | None = None, *, settings: Settings) -> dict:
    """Single-request convenience; reuse UCloudConsoleSession for a catalog."""
    return UCloudConsoleSession.from_settings(settings).request(action, parameters, settings=settings)
