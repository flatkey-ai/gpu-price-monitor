"""Describe Lambda console catalog applicability without inventing region quotes.

The console uses one SKU price when choosing a currently available standard
region. That is a catalog applicability statement, not a country-wide tariff or
an independently requested quote for every location. Country names come from
the provider's explicit descriptions, never from a region-code prefix.
"""

from __future__ import annotations

from copy import deepcopy


FRONTEND_SOURCE_URL = "https://cloud.lambda.ai/static/cloud-app/assets/main-BYA5g9wz.js"
FRONTEND_SOURCE_SHA256 = "e659ac4a2ead7c4002292657204d7f1341be99762c9157df3527fb2ef2e85a4f"
VERIFIED_ON = "2026-10-22"
_CONSOLE_CATALOG_URLS = (
    "https://cloud.lambda.ai/api/internal/dashboard/v1/instance-types",
    "https://cloud.lambda.ai/api/internal/dashboard/v1/cluster-types/reserved",
)

# These are translations of the live /regions response descriptions. Matching
# descriptions instead of region codes avoids retaining an obsolete Tokyo /
# Osaka association when the provider changes a region's displayed location.
_DESCRIPTION_LOCATIONS = {
    "Ohio, USA": ("US", "美国", "俄亥俄州"),
    "Germany": ("DE", "德国", "德国（官方未细分城市）"),
    "California, USA": ("US", "美国", "加利福尼亚州"),
    "Texas, USA": ("US", "美国", "得克萨斯州"),
    "Osaka, Japan": ("JP", "日本", "大阪"),
    "Georgia, USA": ("US", "美国", "佐治亚州"),
    "Arizona, USA": ("US", "美国", "亚利桑那州"),
    "Sydney, Australia": ("AU", "澳大利亚", "悉尼"),
    "India": ("IN", "印度", "印度（官方未细分城市）"),
    "North Texas, USA": ("US", "美国", "得克萨斯州北部"),
    "Central Texas, USA": ("US", "美国", "得克萨斯州中部"),
    "Tokyo, Japan": ("JP", "日本", "东京"),
    "Washington DC, USA": ("US", "美国", "华盛顿特区"),
    "Virginia, USA": ("US", "美国", "弗吉尼亚州"),
    "Utah, USA": ("US", "美国", "犹他州"),
    "Illinois, USA": ("US", "美国", "伊利诺伊州"),
    "Israel": ("IL", "以色列", "以色列（官方未细分城市）"),
}


def describe_location(location: dict) -> dict:
    """Translate an explicit provider location, retaining unknown descriptions.

    An unfamiliar description intentionally has no country association. A known
    region-code prefix does not override conflicting or new source text.
    """
    if not isinstance(location, dict):
        raise ValueError("Invalid Lambda location metadata")
    region, description = location.get("name"), location.get("description")
    if (not isinstance(region, str) or not region.strip()
            or not isinstance(description, str) or not description.strip()
            or any(ord(c) < 32 for c in region + description)):
        raise ValueError("Invalid Lambda location metadata")
    mapping = _DESCRIPTION_LOCATIONS.get(description)
    return {
        "region": region,
        "description": description,
        "country_code": mapping[0] if mapping else None,
        "country_name_zh": mapping[1] if mapping else None,
        "region_name_zh": mapping[2] if mapping else description,
    }


def enrich_price_applicability(quote: dict) -> dict:
    """Return a copy with only this SKU's available standard-region scope.

    ``capacity_locations`` and independently verified price geography remain
    unchanged. Dedicated locations are excluded because the audited standard
    console price display does not establish their dedicated price. An empty
    capacity list never becomes a platform-wide list of countries or regions.
    """
    if (not isinstance(quote, dict) or quote.get("provider") != "lambda"
            or quote.get("source_type") != "official_internal_api"):
        raise ValueError("Expected a Lambda console quote")
    locations = quote.get("capacity_locations", [])
    if not isinstance(locations, list):
        raise ValueError("Invalid Lambda location metadata")
    applicable, excluded, seen = [], [], set()
    for location in locations:
        item = describe_location(location)
        if item["region"] in seen:
            raise ValueError("Duplicate Lambda location metadata")
        seen.add(item["region"])
        if "dedicated" in location and type(location["dedicated"]) is not bool:
            raise ValueError("Invalid Lambda location metadata")
        if location.get("dedicated") is True:
            excluded.append(item)
        else:
            applicable.append(item)

    product = quote.get("product_type")
    display_basis = (
        "The cluster frontend VF selects price_cents_per_gpu_hour; region selection only updates selected-region state."
        if product == "gpu_cluster" else
        "The standard instance frontend $U displays the SKU price loaded by aW; Me changes the selected region without requesting a new regional price."
    )
    result = deepcopy(quote)
    result["price_applicability"] = {
        "basis": "official_console_shared_sku_catalog",
        "scope": "currently_selectable_standard_regions",
        "label_zh": "所列可选地区统一目录价",
        "verification_status": "reviewed_snapshot",
        "locations": applicable,
        "independent_region_quotes": False,
        "final_checkout_verified": False,
        "location_status": "currently_selectable" if applicable else "no_currently_selectable_standard_regions",
        "excluded_dedicated_locations": excluded,
        "evidence": {
            "source_url": FRONTEND_SOURCE_URL,
            "source_sha256": FRONTEND_SOURCE_SHA256,
            "verified_on": VERIFIED_ON,
            "price_display_basis": display_basis,
            "dedicated_exclusion_basis": "The standard instance frontend hides prices when dedicated_region is selected.",
            "location_basis": "Only capacity locations returned for this exact catalog SKU or cluster configuration are included.",
            "country_mapping_basis": "Exact official location description; no region-prefix inference.",
            "does_not_establish": ["nationwide_uniform_price", "worldwide_uniform_price", "final_checkout_price"],
        },
    }
    result["applicable_regions"] = [item["region"] for item in applicable]
    result["applicable_countries"] = sorted({
        item["country_code"] for item in applicable if item["country_code"] is not None
    })
    return result


def validated_applicability_locations(quote: dict, *, require_country: bool = True) -> list[dict] | None:
    """Return validated shared-catalog locations, or ``None`` for other evidence.

    ``[]`` is a valid catalog record with no currently selectable standard
    location. By default every location needs an explicitly recognized country
    for a complete country / region table. Region filters may pass
    ``require_country=False`` to retain an explicit but untranslated new location
    without assigning it a country.
    """
    if (not isinstance(quote, dict) or quote.get("provider") != "lambda"
            or quote.get("source_type") != "official_internal_api"
            or quote.get("source_url") not in _CONSOLE_CATALOG_URLS
            or quote.get("account_scope") != "authenticated_console_catalog"
            or quote.get("product_type") not in ("gpu_instance", "gpu_cluster")
            or quote.get("regions") != [] or quote.get("compute_countries") != []
            or quote.get("region_price_verified") is not False):
        return None
    metadata = quote.get("price_applicability")
    if (not isinstance(metadata, dict)
            or metadata.get("basis") != "official_console_shared_sku_catalog"
            or metadata.get("scope") != "currently_selectable_standard_regions"
            or metadata.get("label_zh") != "所列可选地区统一目录价"
            or metadata.get("verification_status") not in ("reviewed_snapshot", "verified_current_frontend")
            or metadata.get("independent_region_quotes") is not False
            or metadata.get("final_checkout_verified") is not False):
        return None
    evidence = metadata.get("evidence")
    if (not isinstance(evidence, dict) or evidence.get("source_url") != FRONTEND_SOURCE_URL
            or evidence.get("source_sha256") != FRONTEND_SOURCE_SHA256
            or evidence.get("verified_on") != VERIFIED_ON
            or not isinstance(evidence.get("price_display_basis"), str)
            or not evidence["price_display_basis"].strip()):
        return None
    locations, raw = metadata.get("locations"), quote.get("capacity_locations")
    if not isinstance(locations, list) or not isinstance(raw, list):
        return None
    expected, seen = [], set()
    try:
        for source in raw:
            item = describe_location(source)
            if item["region"] in seen:
                return None
            seen.add(item["region"])
            if "dedicated" in source and type(source["dedicated"]) is not bool:
                return None
            if source.get("dedicated") is not True:
                expected.append(item)
    except ValueError:
        return None
    if locations != expected:
        return None
    if require_country and any(item["country_code"] is None for item in locations):
        return None
    countries = sorted({item["country_code"] for item in expected if item["country_code"] is not None})
    if (quote.get("applicable_regions") != [item["region"] for item in expected]
            or quote.get("applicable_countries") != countries):
        return None
    return deepcopy(locations)
