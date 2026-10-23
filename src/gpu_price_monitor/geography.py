"""Describe the location evidence without expanding catalog rates into regions."""

from collections import Counter

from .providers.nebius_regions import REGION_COUNTRIES, REGIONS_URL, VERIFIED_ON


def describe_geography(quote: dict) -> None:
    """Separate price locations from documented coverage and live capacity."""
    countries = quote.get("compute_countries", [])
    if not isinstance(countries, list) or any(
        not isinstance(code, str) or len(code) != 2 or not code.isascii()
        or not code.isalpha() or code != code.upper() for code in countries
    ):
        raise ValueError("Invalid source country metadata")
    quote["compute_countries"] = list(dict.fromkeys(countries))
    scope = quote.get("geographic_scope", "unspecified")
    if quote["provider"] == "nebius" and quote.get("source_type") in {
        "official_pricing_document", "public_documentation", "public_page",
    }:
        coverage = quote.get("coverage_regions", quote.get("regions", []))
        if (not isinstance(coverage, list)
                or any(not isinstance(region, str) or not region for region in coverage)):
            raise ValueError("Invalid source platform coverage")
        quote["coverage_regions"] = list(dict.fromkeys(coverage))
        quote["coverage_countries"] = sorted({REGION_COUNTRIES[r] for r in coverage if r in REGION_COUNTRIES})
        quote["coverage_location_source"] = {
            "regions_url": REGIONS_URL, "pricing_url": quote.get("source_url"),
            "verified_on": VERIFIED_ON,
            "basis": "documented_platform_availability_not_independent_region_quote",
            "country_mapping": {r: REGION_COUNTRIES[r] for r in coverage if r in REGION_COUNTRIES},
        }
        # Even a single-region platform restriction is coverage evidence. It
        # must not be silently expanded into an independently obtained quote.
        quote["regions"] = []
        quote["zones"] = []
        quote["geographic_scope"] = "platform_coverage" if coverage else "unspecified"
        price_scope = "platform_coverage" if coverage else "unlocated_catalog"
    elif scope == "requested_zone":
        price_scope = "requested_zone_quote"
    elif scope == "requested_region":
        price_scope = "requested_region_quote"
    elif quote.get("zones"):
        price_scope = "zone_quote"
    elif quote.get("regions"):
        price_scope = "regional_quote"
    elif (quote["provider"] == "vast" and scope == "offer_country"
          and quote.get("source_type") == "official_public_api"
          and quote.get("source_url") == "https://console.vast.ai/api/v0/bundles"
          and quote.get("location_source", {}).get("basis") == "offer_geolocation"
          and quote["compute_countries"] == [quote.get("location_source", {}).get("country_code")]):
        # A concrete offer's country remains evidence even if no subdivision is
        # published. It still cannot pass the strict regional comparison gate.
        price_scope = "country_quote"
    else:
        price_scope = "unlocated_catalog"
    quote["price_scope"] = price_scope
    quote["region_price_verified"] = price_scope in {
        "zone_quote", "regional_quote", "requested_zone_quote", "requested_region_quote",
    }
    if not quote["region_price_verified"] and price_scope != "country_quote":
        # Catalog or hardware coverage cannot establish a country price.
        quote["compute_countries"] = []


def geography_summary(quotes: list[dict]) -> dict:
    """Report only the coverage of this returned batch, never market completeness."""
    scopes = Counter(quote["price_scope"] for quote in quotes)
    return {
        "scope": "returned_quotes",
        "price_scope_counts": dict(sorted(scopes.items())),
        "country_codes": sorted({code for quote in quotes for code in quote["compute_countries"]}),
        "country_bound_quote_count": sum(bool(quote["compute_countries"]) for quote in quotes),
        "region_bound_quote_count": sum(quote["region_price_verified"] for quote in quotes),
        "unlocated_quote_count": scopes["unlocated_catalog"],
        "platform_coverage_quote_count": scopes["platform_coverage"],
        "coverage_region_codes": sorted({r for q in quotes for r in q.get("coverage_regions", [])}),
        "coverage_country_codes": sorted({c for q in quotes for c in q.get("coverage_countries", [])}),
    }
