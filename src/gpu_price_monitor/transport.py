"""Bounded, read-only HTTP transport; errors never echo response bodies."""

from __future__ import annotations

import socket
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .settings import Settings

MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class FetchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def fetch_text(url: str, settings: Settings) -> str:
    request = Request(url, headers={
        "User-Agent": "gpu-price-monitor/0.1 (+https://github.com/flatkey-ai/gpu-price-monitor)",
        "Accept": "text/markdown,text/html,text/plain;q=0.9",
    })
    for attempt in range(settings.max_retries + 1):
        try:
            with urlopen(request, timeout=settings.timeout_seconds) as response:
                expected_length = None
                length_header = response.headers.get("Content-Length")
                if length_header is not None and not response.headers.get("Transfer-Encoding"):
                    if (not length_header.isascii() or not length_header.isdigit()
                            or len(length_header) > 12):
                        raise FetchError("invalid_response", "The pricing response has an invalid length header.")
                    expected_length = int(length_header)
                    if expected_length > MAX_RESPONSE_BYTES:
                        raise FetchError("response_too_large", "The pricing response exceeds the size limit.")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
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
            error = FetchError("http_error", f"The pricing source returned HTTP {status}.", status == 429 or status >= 500)
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
