"""Fail-closed version evidence for Lambda's reviewed console price semantics.

The current console shell identifies one public JavaScript entry point. Its
digest must match the version manually reviewed in this project before callers
can rely on that version's region/price selection behavior. No price is parsed
here, and a changed or unavailable bundle never silently reuses old evidence.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import transport
from .lambda_session import CONSOLE_HTML_URL


REVIEWED_SOURCE_URL = "https://cloud.lambda.ai/static/cloud-app/assets/main-Bqe423_X.js"
REVIEWED_SHA256 = "dcdf86c8907b3ff9bd862b5070f80fdb295125e9a34d5649fb569fba9f26acb9"
_MAIN_PATH = re.compile(r"/static/cloud-app/assets/main-[A-Za-z0-9_-]+\.js\Z")


def _entry_source(html: str) -> str | None:
    """Return exactly one observed canonical main bundle, never a guessed URL."""
    if not isinstance(html, str):
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Relative entry URLs must not be resolved differently by a document base.
    if soup.find("base", href=True) is not None:
        return None
    candidates = []
    for script in soup.find_all("script", src=True):
        source = script.get("src")
        if not isinstance(source, str) or not source or not source.isascii():
            continue
        # Reject URL normalization surprises instead of trimming or decoding.
        if (any(ord(char) <= 32 or ord(char) == 127 for char in source)
                or any(char in source for char in ("\\", "?", "#"))):
            continue
        try:
            resolved = urljoin(CONSOLE_HTML_URL, source)
            parsed = urlsplit(resolved)
        except ValueError:
            continue
        if (parsed.scheme != "https" or parsed.netloc != "cloud.lambda.ai"
                or parsed.query or parsed.fragment or not _MAIN_PATH.fullmatch(parsed.path)
                or resolved != "https://cloud.lambda.ai" + parsed.path):
            continue
        candidates.append(resolved)
    # Even repeated identical entry scripts are unexpected and fail closed.
    return candidates[0] if len(candidates) == 1 else None


def verify_frontend_version(session, settings) -> dict:
    """Return safe evidence; unavailable or changed versions return ``failed``.

    Only the HTML request uses the caller's authorized session. The one public
    script URL observed in that HTML is fetched without Cookie or authorization
    headers. ``authenticated=True`` merely selects transport's no-redirect mode
    for this public request, so redirects cannot expand the source allowlist.
    """
    baseline = {"reviewed_source_url": REVIEWED_SOURCE_URL,
                "reviewed_sha256": REVIEWED_SHA256}
    try:
        html = session.get_console_html()
    except transport.FetchError:
        return {"status": "failed", "reason_code": "frontend_shell_unavailable", **baseline}
    source = _entry_source(html)
    if source is None:
        return {"status": "failed", "reason_code": "frontend_entry_unrecognized", **baseline}
    evidence = {"source_url": source, **baseline}
    try:
        script = transport._request_text(
            source, settings, method="GET",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/javascript,*/*;q=0.1"},
            authenticated=True,
        )
    except transport.FetchError:
        return {"status": "failed", "reason_code": "frontend_script_unavailable", **evidence}
    if not isinstance(script, str):
        return {"status": "failed", "reason_code": "frontend_script_invalid", **evidence}
    try:
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    except UnicodeError:
        return {"status": "failed", "reason_code": "frontend_script_invalid", **evidence}
    if digest != REVIEWED_SHA256:
        return {"status": "failed", "reason_code": "frontend_version_changed",
                "sha256": digest, **evidence}
    return {"status": "verified", "sha256": digest, **evidence}
