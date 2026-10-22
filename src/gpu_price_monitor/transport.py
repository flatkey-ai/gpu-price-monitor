"""Bounded, read-only HTTP transport; errors never echo response bodies."""

from __future__ import annotations

import socket
import time
import json
from decimal import Decimal
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .settings import Settings

MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class FetchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class _NoRedirect(HTTPRedirectHandler):
    """Never forward credentials or signed requests through a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request_text(url: str, settings: Settings, *, method: str = "GET", headers: dict | None = None,
                  data: bytes | None = None, authenticated: bool = False,
                  max_response_bytes: int | None = None) -> str:
    if max_response_bytes is None:
        max_response_bytes = MAX_RESPONSE_BYTES
    if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 32 * 1024 * 1024:
        raise FetchError("invalid_request", "The response size limit must be an integer within 32 MiB.")
    request_headers = {
        "User-Agent": "gpu-price-monitor/0.2 (+https://github.com/flatkey-ai/gpu-price-monitor)",
        "Accept": "text/markdown,text/html,text/plain;q=0.9",
    }
    request_headers.update(headers or {})
    if authenticated and not url.startswith("https://"):
        raise FetchError("invalid_request", "Authenticated requests require HTTPS.")
    if any(not isinstance(k, str) or not isinstance(v, str) or "\r" in k + v or "\n" in k + v
           for k, v in request_headers.items()):
        raise FetchError("invalid_request", "The request contains an invalid header.")
    request = Request(url, headers=request_headers, data=data, method=method)
    open_request = build_opener(_NoRedirect()).open if authenticated else urlopen
    for attempt in range(settings.max_retries + 1):
        try:
            with open_request(request, timeout=settings.timeout_seconds) as response:
                expected_length = None
                length_header = response.headers.get("Content-Length")
                if length_header is not None and not response.headers.get("Transfer-Encoding"):
                    if (not length_header.isascii() or not length_header.isdigit()
                            or len(length_header) > 12):
                        raise FetchError("invalid_response", "The pricing response has an invalid length header.")
                    expected_length = int(length_header)
                    if expected_length > max_response_bytes:
                        raise FetchError("response_too_large", "The pricing response exceeds the size limit.")
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise FetchError("response_too_large", "The pricing response exceeds the size limit.")
                if expected_length is not None and len(body) != expected_length:
                    raise FetchError("response_incomplete", "The pricing response ended before its declared length.", True)
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    return body.decode(charset)
                except (UnicodeError, LookupError):
                    raise FetchError("invalid_encoding", "The pricing response could not be decoded.") from None
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if authenticated and status in (401, 403):
                error = FetchError("authentication_error", "The provider rejected the configured credentials or permissions.")
            elif authenticated and 300 <= status < 400:
                error = FetchError("redirect_rejected", "Authenticated requests do not follow redirects.")
            else:
                error = FetchError("rate_limited" if status == 429 else "http_error", f"The pricing source returned HTTP {status}.", status == 429 or status >= 500)
        except FetchError as exc:
            error = exc
        except (TimeoutError, socket.timeout):
            error = FetchError("timeout", "The pricing source timed out.", True)
        except (URLError, OSError, HTTPException):
            error = FetchError("network_error", "The pricing source could not be reached.", True)
        if not error.retryable or attempt == settings.max_retries:
            raise error
        time.sleep(min(2 ** attempt, 8))
    raise FetchError("network_error", "The pricing source could not be reached.", True)


def fetch_text(url: str, settings: Settings) -> str:
    return _request_text(url, settings)


def request_json(url: str, settings: Settings, *, method: str = "GET", headers: dict | None = None,
                 data: bytes | None = None, authenticated: bool = False,
                 max_response_bytes: int | None = None) -> dict:
    """Read an API response without leaking headers, body or signed query data.

    Floats are decoded as Decimal to preserve the provider's monetary value.
    Authenticated requests reject every redirect, including same-origin ones.
    """
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    limits = {} if max_response_bytes is None else {"max_response_bytes": max_response_bytes}
    content = _request_text(url, settings, method=method, headers=request_headers, data=data, authenticated=authenticated, **limits)
    def reject_constant(value):
        raise ValueError("Non-finite JSON constant")
    try:
        payload = json.loads(content, parse_float=Decimal, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise FetchError("invalid_json", "The provider did not return valid JSON.") from None
    if not isinstance(payload, dict):
        raise FetchError("invalid_json", "The provider returned an unexpected JSON structure.")
    return payload
