"""Anonymous current Spot API quotes with a freshly verified country directory.

This adapter never derives region prices from platform coverage. One returned
price is one current API (platform, region) record; country metadata is refreshed
independently from the official directory. Failed metadata cannot use a static
fallback country in publishable results.
"""

from __future__ import annotations

from copy import deepcopy

from ..settings import Settings
from ..transport import FetchError, fetch_text
from . import nebius_regions, nebius_spot

SOURCE_URL = nebius_spot.SOURCE_URL
SOURCE_TYPE = nebius_spot.SOURCE_TYPE
REGIONS_URL = nebius_regions.REGIONS_URL + ".md"


def _error(source: str, exc) -> dict:
    return {"source": source, "code": exc.code if isinstance(exc, FetchError) else "parse_failed",
            "message": ("Current regional Nebius Spot API quotes could not be verified." if source == "regional_spot_api"
                        else "The current official region-country directory could not be verified; no fallback country was used."),
            "retryable": exc.retryable if isinstance(exc, FetchError) else False}


def _without_countries(prices: list[dict]) -> list[dict]:
    result = deepcopy(prices)
    for quote in result:
        quote["compute_countries"] = []
        quote["location"] = {"region": quote["regions"][0]}
        quote["location_source"] = {"url": nebius_regions.REGIONS_URL, "source_type": "unknown",
                                     "country_basis": "live_directory_not_verified"}
    return result


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    errors, gaps, contexts, prices, directory = [], [], [], [], {}
    try:
        prices = nebius_spot.collect_quotes(settings=settings, observed_at=observed_at)
        contexts.append({"source": "regional_spot_api", "source_url": SOURCE_URL,
                         "source_type": SOURCE_TYPE, "status": "ok", "quote_count": len(prices)})
    except (FetchError, ValueError, TypeError, KeyError) as exc:
        errors.append(_error("regional_spot_api", exc))
        contexts.append({"source": "regional_spot_api", "source_url": SOURCE_URL,
                         "source_type": SOURCE_TYPE, "status": "failed", "quote_count": 0})
    try:
        content = fetch_text(REGIONS_URL, settings)
        directory = nebius_regions.parse_directory(content, observed_at=observed_at)
        prices, country_gaps = nebius_regions.attach_spot_locations(prices, directory)
        gaps.extend(country_gaps)
        contexts.append({"source": "region_country_directory", "source_url": nebius_regions.REGIONS_URL,
                         "source_type": "official_region_directory", "status": "ok",
                         "region_count": len(directory)})
    except (FetchError, ValueError, TypeError, KeyError) as exc:
        prices = _without_countries(prices)
        errors.append(_error("region_country_directory", exc))
        gaps.append({"scope": "spot_country_metadata", "status": "live_directory_unverified",
                     "reason": "Amounts and region codes remain actual API data; countries were cleared."})
        contexts.append({"source": "region_country_directory", "source_url": nebius_regions.REGIONS_URL,
                         "source_type": "official_region_directory", "status": "failed"})
    coverage = {"reported_spot_api_quote_count": len(prices),
                "country_verified_spot_api_quote_count": sum(bool(q["compute_countries"]) for q in prices),
                "region_codes": sorted({r for q in prices for r in q["regions"]}),
                "country_codes": sorted({c for q in prices for c in q["compute_countries"]}),
                "derived_preset_row_count": 0, "all_platform_prices_complete": False}
    return {"prices": prices, "errors": errors, "gaps": gaps, "source_contexts": contexts,
            "status": ("partial" if prices else "failed") if errors or gaps or not prices else "ok",
            "coverage": coverage,
            "catalog_coverage": {"summary": coverage, "regions": directory,
                                 "source_urls": [SOURCE_URL, nebius_regions.REGIONS_URL]},
            "authentication_method": "anonymous",
            "pricing_limitations": ["Current preemptible Spot prices only; no on-demand or private contract prices are inferred.",
                                     "Regional price listings do not guarantee available capacity or orderability."]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    result = collect_result(settings=settings, observed_at=observed_at)
    if result["status"] != "ok":
        raise FetchError("partial_collection", "Inspect Nebius Spot result diagnostics for API/country metadata gaps.")
    return result["prices"]
