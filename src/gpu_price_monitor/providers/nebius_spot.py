"""Anonymous, region-specific current Nebius preemptible GPU spot prices.

This public API returns the current price, not the published minimum or an
aggregated history point. A price listing does not assert available capacity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from urllib.parse import urlencode

from ..settings import Settings
from ..transport import FetchError, request_json
from .nebius_regions import REGION_COUNTRIES, REGIONS_URL, VERIFIED_ON

SOURCE_URL = "https://api.nebius.cloud/billing/v1alpha1/spot-price"
SOURCE_TYPE = "official_public_api"
PUBLIC_URL = "https://nebius.com/spot-prices"
DOCUMENTATION_URL = "https://docs.nebius.com/signup-billing/spot-prices"
POLICY_URL = "https://docs.nebius.com/signup-billing/pricing-policy"
PRICING_URL = "https://docs.nebius.com/compute/resources/pricing"
MAX_PAGES = 5
PAGE_SIZE = 100
MAX_SNAPSHOT_AGE = timedelta(minutes=15)
MAX_CLOCK_SKEW = timedelta(minutes=5)
_PLATFORMS = {
    "gpu-b300-sxm": ("B300", "NVLink"),
    "gpu-b200-sxm": ("B200", "NVLink"),
    "gpu-b200-sxm-a": ("B200", "NVLink"),
    "gpu-h200-sxm": ("H200", "NVLink"),
    "gpu-h100-sxm": ("H100", "NVLink"),
    "gpu-rtx6000": ("RTX PRO 6000", None),
    "gpu-rtx6000-a": ("RTX PRO 6000", None),
}


def _invalid() -> ValueError:
    return ValueError("The public Nebius spot-price structure, scope, unit or time was not recognized.")


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or "T" not in value:
        raise _invalid()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise _invalid() from None


def query_url(page_token: str | None = None) -> str:
    """Keep pagination on the fixed anonymous endpoint; tokens are query values."""
    query = {"pageSize": str(PAGE_SIZE)}
    if page_token is not None:
        query["pageToken"] = page_token
    return SOURCE_URL + "?" + urlencode(query)


def parse_prices(payload: dict, *, observed_at: str) -> list[dict]:
    """Parse one complete current-price page, retaining exact decimal strings."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise _invalid()
    items = payload["items"]
    if len(items) > PAGE_SIZE:
        raise _invalid()
    observed, snapshot = _instant(observed_at), _instant(payload.get("snapshotTime"))
    # The collector timestamps the request before I/O, so a response snapshot
    # can follow observed_at slightly. Reject stale caches and implausible clocks.
    if not observed - MAX_SNAPSHOT_AGE <= snapshot <= observed + MAX_CLOCK_SKEW:
        raise _invalid()
    quotes, seen = [], set()
    for row in items:
        if not isinstance(row, dict) or not isinstance(row.get("computeInstance"), dict):
            raise _invalid()
        platform = row["computeInstance"].get("platform")
        if not isinstance(platform, str) or platform not in _PLATFORMS:
            raise _invalid()
        model, variant = _PLATFORMS[platform]
        expected_title = "Preemptible NVIDIA® " + model + (" " + variant if variant else "")
        sku, region = row.get("skuId"), row.get("region")
        if (row.get("productTitle") != expected_title or not isinstance(sku, str)
                or not re.fullmatch(r"sku-[a-z0-9]{1,80}", sku)
                or not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}-[a-z]+[1-9][0-9]*", region)):
            raise _invalid()
        identity = (region, platform)
        if sku in seen or identity in seen:
            raise _invalid()
        seen.update((sku, identity))
        price = row.get("price")
        if not isinstance(price, dict):
            raise _invalid()
        value, currency = price.get("value"), price.get("currency")
        if (not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,20})?", value)
                or Decimal(value) <= 0 or currency not in ("usd", "ils")
                or price.get("unitTitle") != "GPU hour"):
            raise _invalid()
        effective = _instant(row.get("effectiveTime"))
        # snapshotTime is the earliest per-SKU sampling time, not an upper
        # bound for every event in this response (the public API documents it).
        if effective > observed + MAX_CLOCK_SKEW:
            raise _invalid()
        countries = [REGION_COUNTRIES[region]] if region in REGION_COUNTRIES else []
        location = {"region": region}
        if countries:
            location["country_code"] = countries[0]
        quotes.append({
            "provider": "nebius", "product_type": "gpu_instance", "gpu_model": model,
            "gpu_variant": variant, "raw_name": expected_title, "raw_sku": platform,
            "provider_sku_id": sku, "gpu_count": None, "vram_gb": None,
            "amount": value, "currency": currency.upper(), "unit": "gpu_hour",
            "billing_mode": "spot", "price_basis": "advertised_per_gpu", "quote_status": "quoted",
            "regions": [region], "zones": [], "geographic_scope": "regions",
            "location": location, "compute_countries": countries,
            "price_scope": "regional_quote", "region_price_verified": True,
            "location_source": {
                "url": REGIONS_URL if countries else None,
                "source_type": "official_region_directory" if countries else "unknown",
                "verified_on": VERIFIED_ON if countries else None,
                "country_basis": "explicit_region_country_table" if countries else "unverified_region",
            },
            "account_scope": "public_catalog", "tax_scope": "excluded", "availability": "unknown",
            "observed_at": observed_at, "effective_from": effective.isoformat(), "effective_until": None,
            "source_snapshot_at": snapshot.isoformat(),
            "source_snapshot_basis": "earliest_per_sku_snapshot",
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "public_url": PUBLIC_URL,
            "api_documentation_url": DOCUMENTATION_URL,
            "conditions": {"capacity_type": "preemptible", "pricing_policy_url": POLICY_URL},
            "notes": [
                "Current anonymous API spot price for one GPU hour on this exact platform in this region; this is not the published minimum or an averaged history point.",
                "Preemptible prices can change as often as every 15 minutes before and during use; interruption conditions apply and capacity is not verified.",
                "The API supplies the currency. USD billing applies except to companies from Israel, where ILS billing applies; customer billing jurisdiction is separate from compute location.",
                "Prices exclude applicable taxes; GPU quantity and VM configuration are not specified by this per-GPU price listing.",
            ],
            "tax_source_url": PRICING_URL,
        })
    return quotes


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Fetch every bounded page using anonymous GET requests only."""
    quotes, seen_tokens, seen_skus, seen_platforms = [], set(), set(), set()
    token = None
    for _ in range(MAX_PAGES):
        payload = request_json(query_url(token), settings, authenticated=False)
        page = parse_prices(payload, observed_at=observed_at)
        for quote in page:
            sku, identity = quote["provider_sku_id"], (quote["regions"][0], quote["raw_sku"])
            if sku in seen_skus or identity in seen_platforms:
                raise FetchError("invalid_public_catalog", "Nebius returned duplicate current spot-price entries.")
            seen_skus.add(sku)
            seen_platforms.add(identity)
        quotes.extend(page)
        token = payload.get("nextPageToken")
        if token in (None, ""):
            if not quotes:
                raise FetchError("empty_public_catalog", "Nebius returned no current public spot prices.")
            return quotes
        if (not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 32 for c in token)
                or token in seen_tokens or not page):
            raise FetchError("invalid_pagination", "Nebius returned an invalid spot-price continuation token.")
        seen_tokens.add(token)
    raise FetchError("pagination_limit", "Nebius spot-price pagination exceeded its safety limit.")
