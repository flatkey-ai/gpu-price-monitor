"""Read Nebius's public on-demand catalog from its website JSON data endpoint.

The HTML bootstrap supplies only Next.js routing metadata. All catalog rows,
units, amounts, and currency evidence come from the subsequent JSON response.
This endpoint is website infrastructure, not a documented cloud price API.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from ..settings import Settings
from ..transport import FetchError, fetch_text, request_json

SOURCE_URL = "https://nebius.com/prices"
SOURCE_TYPE = "official_website_json"
_ENDPOINT = re.compile(r"https://nebius\.com/_next/data/[A-Za-z0-9_-]{1,128}/en/prices\.json")
_COLUMNS = ("Item", "vCPUs", "RAM, GB", "Preemptible, GPU-hour *", "On-demand, GPU-hour")
_MODEL = re.compile(r"NVIDIA (?:(HGX) )?(GB\d{3}|B\d{3}|H\d{3}|RTX PRO \d{4}|L40S)(?: (NVL\d+|with Intel CPU|with AMD CPU))?")
_PRICE = re.compile(r"(?:(from) )?\$(\d{1,8}(?:\.\d{1,12})?)", re.IGNORECASE)


def _invalid() -> ValueError:
    return ValueError("The public Nebius website catalog structure, currency or unit changed.")


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise _invalid()
    return " ".join(value.split())


def data_url(bootstrap_html: str) -> str:
    """Construct one fixed-origin JSON URL, without reading HTML price rows."""
    soup = BeautifulSoup(bootstrap_html, "html.parser")
    scripts = soup.find_all("script", id="__NEXT_DATA__", type="application/json")
    if len(scripts) != 1:
        raise _invalid()
    payload = json.loads(scripts[0].get_text())
    if (not isinstance(payload, dict) or payload.get("page") != "/[[...slug]]"
            or payload.get("locale") != "en" or payload.get("gssp") is not True):
        raise _invalid()
    build = payload.get("buildId")
    if not isinstance(build, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", build):
        raise _invalid()
    return f"https://nebius.com/_next/data/{build}/en/prices.json"


def _resource(value: str, name: str) -> dict:
    if not re.fullmatch(r"[1-9]\d{0,5}(?:-[1-9]\d{0,5})?", value):
        raise _invalid()
    bounds = list(map(int, value.split("-")))
    if len(bounds) == 2:
        if bounds[0] >= bounds[1]:
            raise _invalid()
        return {name + "_range": bounds}
    return {name: bounds[0]}


def parse_prices(payload: dict, *, observed_at: str, api_endpoint: str) -> list[dict]:
    """Parse the published GPU row catalog; do not infer regions or GPU count."""
    if not isinstance(api_endpoint, str) or not _ENDPOINT.fullmatch(api_endpoint):
        raise _invalid()
    if not isinstance(payload, dict) or payload.get("__N_SSP") is not True:
        raise _invalid()
    props = payload.get("pageProps")
    state = props.get("__APOLLO_STATE__") if isinstance(props, dict) else None
    if not isinstance(state, dict):
        raise _invalid()
    pages = [item for item in state.values() if isinstance(item, dict)
             and item.get("__typename") == "pages" and item.get("name") == "prices"
             and item.get("website") == "nebius.com"]
    if len(pages) != 1 or not isinstance(pages[0].get("content"), str) or len(pages[0]["content"]) > 512 * 1024:
        raise _invalid()
    content = json.loads(pages[0]["content"])
    blocks = content.get("blocks") if isinstance(content, dict) else None
    if not isinstance(blocks, list) or len(blocks) > 100:
        raise _invalid()
    tables = [block for block in blocks if isinstance(block, dict)
              and block.get("type") == "highlight-table-block"
              and block.get("title") == "NVIDIA GPU Instances"]
    if len(tables) != 1 or not isinstance(tables[0].get("table"), dict):
        raise _invalid()
    rows = tables[0]["table"].get("content")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 51:
        raise _invalid()
    if not isinstance(rows[0], list) or tuple(map(_text, rows[0])) != _COLUMNS:
        raise _invalid()
    currency_evidence = any(
        isinstance(item, dict) and _text(item.get("title", "")).casefold() == "what currency do you accept?"
        and _text(item.get("text", "")).casefold() == "we accept usd."
        for block in blocks if isinstance(block, dict) and block.get("type") == "questions-block"
        for item in (block.get("items") if isinstance(block.get("items"), list) else [])
    )
    if not currency_evidence:
        raise _invalid()
    tax_evidence = any(
        isinstance(block, dict) and isinstance(block.get("textContent"), dict)
        and isinstance(block["textContent"].get("additionalInfo"), str)
        and "All prices are shown without any applicable taxes" in block["textContent"]["additionalInfo"]
        for block in blocks
    )
    quotes, seen = [], set()
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != len(_COLUMNS):
            raise _invalid()
        name, cpu, ram, _spot, price = map(_text, row)
        model = _MODEL.fullmatch(name)
        if not model or name in seen:
            raise _invalid()
        seen.add(name)
        resources = {**_resource(cpu, "vcpus"), **_resource(ram, "ram_gb")}
        if price == "[Contact us](#ai-contact-form)":
            amount, status, basis = None, "contact_sales", "advertised_per_gpu"
        else:
            match = _PRICE.fullmatch(price)
            if not match or Decimal(match[2]) <= 0:
                raise _invalid()
            amount = match[2]
            status, basis = ("starting_at", "starting_price") if match[1] else ("quoted", "advertised_per_gpu")
        variant = " ".join(part for part in (model[1], model[3]) if part) or None
        notes = [
            "Public website JSON catalog on-demand rate, not an authenticated account estimate or regional price API.",
            "The row lists vCPUs and RAM in GB but does not declare GPU count, GPU memory or a price-bound deployment region.",
            "The advertised GPU-hour rate does not include separately billed storage or guarantee capacity or purchase eligibility.",
        ]
        if status == "starting_at":
            notes.append("The source publishes a starting price across a configuration range, not one exact configuration quote.")
        quotes.append({
            "provider": "nebius", "product_type": "gpu_instance", "gpu_model": model[2],
            "gpu_variant": variant, "raw_name": name, "raw_sku": None,
            "gpu_count": None, "vram_gb": None, "resources": resources,
            "amount": amount, "currency": "USD", "unit": "gpu_hour", "billing_mode": "on_demand",
            "price_basis": basis, "quote_status": status, "regions": [], "zones": [],
            "compute_countries": [], "geographic_scope": "unspecified", "price_scope": "unlocated_catalog",
            "region_price_verified": False, "account_scope": "public_catalog",
            "tax_scope": "excluded" if tax_evidence else "unspecified", "availability": "unknown",
            "observed_at": observed_at, "effective_from": None, "effective_until": None,
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "api_endpoint": api_endpoint,
            "conditions": {"currency_basis": "official_website_payment_currency_USD",
                           "resource_scope": "published_row_unspecified_gpu_count"},
            "notes": notes,
        })
    if not any(quote["quote_status"] == "quoted" for quote in quotes):
        raise _invalid()
    return quotes


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Fetch routing metadata, then anonymous website JSON; never use a cache."""
    try:
        endpoint = data_url(fetch_text(SOURCE_URL, settings))
        payload = request_json(endpoint, settings, authenticated=False)
        return parse_prices(payload, observed_at=observed_at, api_endpoint=endpoint)
    except (ValueError, TypeError, RecursionError):
        raise FetchError("parse_failed", "The public Nebius website pricing structure changed.") from None
