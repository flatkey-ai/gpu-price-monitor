"""Describe the location evidence without expanding catalog rates into regions."""

from collections import Counter


def describe_geography(quote: dict) -> None:
    """Add explicit price scope while keeping the source location arrays intact."""
    countries = quote.get("compute_countries", [])
    if not isinstance(countries, list) or any(
        not isinstance(code, str) or len(code) != 2 or not code.isascii()
        or not code.isalpha() or code != code.upper() for code in countries
    ):
        raise ValueError("Invalid source country metadata")
    quote["compute_countries"] = list(dict.fromkeys(countries))
    scope = quote.get("geographic_scope", "unspecified")
    if quote["provider"] == "nebius" and quote.get("source_type") != "official_quote_api":
        price_scope = "platform_coverage" if quote.get("regions") else "unlocated_catalog"
    elif scope == "requested_zone":
        price_scope = "requested_zone_quote"
    elif scope == "requested_region":
        price_scope = "requested_region_quote"
    elif quote.get("zones"):
        price_scope = "zone_quote"
    elif quote.get("regions"):
        price_scope = "regional_quote"
    else:
        price_scope = "unlocated_catalog"
    quote["price_scope"] = price_scope
    quote["region_price_verified"] = price_scope in {
        "zone_quote", "regional_quote", "requested_zone_quote", "requested_region_quote",
    }
    if not quote["region_price_verified"]:
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
    }
