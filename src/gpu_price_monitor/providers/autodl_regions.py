"""Opt-in country evidence for exact AutoDL market-region records.

The public region API does not provide a country field. Eleven reviewed region
identities explicitly name Beijing, Inner Mongolia, Chongqing or Foshan and
match the official data-center appendix. Only those exact triples can receive
CN here. ``west*``, ``nm-*`` and ``shanghai*`` prefixes are never geocoded.

This module performs no HTTP, browser, authentication or file operations. It
does not change a price, price scope, source region, tier or availability.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re

REGIONS_URL = "https://www.autodl.com/api/v1/region/list"
DOCUMENTATION_URL = "https://www.autodl.com/docs/esd_api_doc/"
DOCUMENTATION_VERIFIED_ON = "2026-10-22"
MARKET_URL = "https://www.autodl.com/market/list"
MARKET_API_URL = "https://www.autodl.com/api/v1/user/machine/list"

# Exact public-API identities cross-checked with the official DC appendix.
# These are country-evidence rules, not a price/SKU list or a claim that other
# AutoDL regions are outside China. The source spelling "内蒙" is preserved.
_VERIFIED_IDENTITIES = {
    "beijing-A": ("北京A区", "beijingDC1"),
    "beijing-B": ("北京A区", "beijingDC1"),
    "beijing-D": ("北京A区", "beijingDC1"),
    "beijing-E": ("北京A区", "beijingDC1"),
    "bj-B1": ("北京B区", "beijingDC2"),
    "bj-B2": ("北京B区", "beijingDC2"),
    "bj-B3": ("北京B区", "beijingDC2"),
    "nm-B1": ("内蒙B区", "neimengDC3"),
    "nm-B2": ("内蒙B区", "neimengDC3"),
    "cq-A1": ("重庆A区", "chongqingDC1"),
    "foshan-A": ("佛山区", "foshanDC1"),
}
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_COUNTRY_FIELDS = ("country_code", "country_name", "country_name_zh", "country_source")


def _invalid() -> ValueError:
    return ValueError("The public AutoDL region directory or exact market-location identity changed.")


def _timestamp(value: str) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise _invalid()
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise _invalid()
    except (ValueError, OverflowError):
        raise _invalid() from None
    return value


def parse_region_directory(payload: dict, *, observed_at: str) -> dict[str, dict]:
    """Project the actual public directory without trusting extra country data.

    New regions are retained for audit; their codes do not create new country
    rules automatically. Request IDs and unrelated metadata are not returned.
    """
    observed_at = _timestamp(observed_at)
    if (not isinstance(payload, dict) or payload.get("code") != "Success"
            or not isinstance(payload.get("data"), list) or not 1 <= len(payload["data"]) <= 1000):
        raise _invalid()
    result = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            raise _invalid()
        code, name, center = (item.get(key) for key in ("region_sign", "region_name", "data_center"))
        if (not isinstance(code, str) or not _CODE.fullmatch(code) or code in result
                or not isinstance(center, str) or not _CODE.fullmatch(center)
                or not isinstance(name, str) or not name or name != name.strip() or len(name) > 120
                or any(ord(char) < 32 for char in name)):
            raise _invalid()
        result[code] = {"region_sign": code, "region_name": name, "data_center": center,
                        "source_url": REGIONS_URL, "observed_at": observed_at}
    return result


def enrich_market_quote(quote: dict, *, region_directory: dict[str, dict]) -> dict:
    """Attach country evidence to one exact located market quote, copying it.

    Callers must opt in with a current public directory. Anonymous homepage
    rates, multi-region records and caller-invented locations are not accepted
    as market-region evidence. Failure to match keeps country information empty
    and explains the gap; it never turns a rate into a nationwide price.
    """
    if (not isinstance(quote, dict) or quote.get("provider") != "autodl"
            or quote.get("product_type") != "gpu_container"
            or quote.get("source_url") not in {MARKET_URL, MARKET_API_URL}
            or quote.get("source_type") not in {"authorized_browser", "official_internal_api", "official_api"}
            or quote.get("unit") != "gpu_hour" or quote.get("geographic_scope") != "regions"
            or not isinstance(quote.get("regions"), list) or len(quote["regions"]) != 1
            or not isinstance(quote.get("location"), dict) or not isinstance(region_directory, dict)):
        raise _invalid()
    code = quote["regions"][0]
    location = quote["location"]
    if (not isinstance(code, str) or not _CODE.fullmatch(code) or location.get("region") != code
            or not isinstance(location.get("region_name"), str) or not location["region_name"]):
        raise _invalid()
    result = deepcopy(quote)
    result["compute_countries"] = []
    for key in _COUNTRY_FIELDS:
        result["location"].pop(key, None)
    evidence = {"url": REGIONS_URL, "documentation_url": DOCUMENTATION_URL,
                "documentation_verified_on": DOCUMENTATION_VERIFIED_ON,
                "source_type": "official_region_directory",
                "country_field_provided_by_api": False,
                "country_basis": "unverified_country", "country_status": "not_verified"}
    directory_row = region_directory.get(code)
    expected = _VERIFIED_IDENTITIES.get(code)
    if directory_row is None:
        evidence["reason"] = "The quoted region is absent from the supplied current public directory."
    elif (not isinstance(directory_row, dict) or directory_row.get("region_sign") != code
          or directory_row.get("source_url") != REGIONS_URL):
        raise _invalid()
    elif expected is None:
        evidence["reason"] = "No reviewed explicit country evidence exists for this region; code/DC prefixes and old zone names are not geocoded."
    elif (directory_row.get("region_name"), directory_row.get("data_center")) != expected:
        evidence["reason"] = "The current region name/data center no longer matches the reviewed official place-name mapping."
    elif location["region_name"] != directory_row["region_name"]:
        evidence["reason"] = "The market quote and current directory disagree on the region name."
    else:
        _timestamp(directory_row.get("observed_at"))
        result["compute_countries"] = ["CN"]
        result["location"].update(country_code="CN", country_name="China", country_name_zh="中国")
        evidence.update(country_basis="official_named_place_and_data_center_crossreference",
                        country_status="verified", region_sign=code,
                        region_name=directory_row["region_name"], data_center=directory_row["data_center"],
                        directory_observed_at=directory_row["observed_at"],
                        explanation="The current API code/name/DC triple matches the reviewed official appendix for an explicit Chinese place; the API itself has no country field.")
    result["location_source"] = evidence
    return result


def enrich_market_quotes(quotes: list[dict], *, region_directory: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Return located quotes and explicit country gaps, without adding rows."""
    if not isinstance(quotes, list):
        raise _invalid()
    result, gaps = [], []
    for supplied in quotes:
        quote = enrich_market_quote(supplied, region_directory=region_directory)
        result.append(quote)
        evidence = quote["location_source"]
        if evidence["country_status"] != "verified":
            gaps.append({"scope": "market_region_country", "region": quote["regions"][0],
                         "status": "country_not_verified", "reason": evidence["reason"],
                         "source_url": REGIONS_URL, "documentation_url": DOCUMENTATION_URL})
    return result, gaps
