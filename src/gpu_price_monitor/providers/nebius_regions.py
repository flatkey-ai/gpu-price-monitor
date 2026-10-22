"""Official Nebius locations, separate from regional price evidence.

The constants support the small anonymous API adapter offline. Full-catalog
collection refreshes the directory on every run and binds countries to the
explicit country names in that document, never to a region-code prefix.
"""

from copy import deepcopy
from hashlib import sha256
from html import unescape
import re

REGIONS_URL = "https://docs.nebius.com/overview/regions"
VERIFIED_ON = "2026-10-21"
REGION_COUNTRIES = {
    "eu-north1": "FI", "eu-north2": "IS", "eu-south1": "ES",
    "eu-west1": "FR", "eu-west2": "FR", "uk-south1": "GB", "uk-south2": "GB",
    "us-central1": "US", "us-north1": "US", "me-west1": "IL",
}

_COUNTRIES = {
    "Finland": ("FI", "芬兰"), "Spain": ("ES", "西班牙"),
    "France": ("FR", "法国"), "Israel": ("IL", "以色列"),
    "US": ("US", "美国"), "United States": ("US", "美国"),
    "United Kingdom": ("GB", "英国"), "Iceland": ("IS", "冰岛"),
}
_PLACES = {
    "Finland": "芬兰", "Madrid, Spain": "马德里", "France": "法国",
    "Israel": "以色列", "Kansas City, Missouri, US": "密苏里州堪萨斯城",
    "Woodbury, Minnesota, US": "明尼苏达州伍德伯里", "United Kingdom": "英国",
    "Iceland": "冰岛",
}


def parse_directory(content: str, *, observed_at: str | None = None) -> dict[str, dict]:
    """Parse the current public/private directory, retaining explicit evidence.

    A new country is preserved by name with a null ISO code until it can be
    identified reliably. A new region in an existing country needs no code
    release. Unknown regions are not assigned countries from their prefix.
    """
    if not isinstance(content, str) or len(content) > 512 * 1024:
        raise ValueError("Nebius region directory structure changed.")
    result = {}
    for title, private in (("Public regions", False), ("Private regions", True)):
        section = re.search(r"^## " + title + r"\s*\n(.*?)(?=^## |\Z)", content,
                            re.MULTILINE | re.DOTALL)
        if section is None:
            raise ValueError("Nebius region directory structure changed.")
        for code, label in re.findall(r"^\* `([a-z]{2}-[a-z]+[1-9][0-9]*)`: ([^\n]+)",
                                      section[1], re.MULTILINE):
            name = " ".join(unescape(label).split())
            if code in result or not name or len(name) > 200 or re.search(r"[<>\[\]`\\]", name):
                raise ValueError("Nebius region directory structure changed.")
            # The final comma-delimited component is an explicit country name,
            # not a guess based on the code or the requested billing currency.
            country_name = name.rsplit(", ", 1)[-1]
            country = _COUNTRIES.get(country_name)
            result[code] = {
                "region": code, "country_code": country[0] if country else None,
                "country_name": country_name, "country_name_zh": country[1] if country else country_name,
                "region_name": name, "region_name_zh": _PLACES.get(name, name),
                "country_description": name, "private_region": private,
                "source_url": REGIONS_URL, "source_type": "official_region_directory",
                "country_basis": "explicit_official_region_country_list",
                "observed_at": observed_at,
                "directory_sha256": sha256(content.encode("utf-8")).hexdigest(),
            }
    if not result:
        raise ValueError("Nebius region directory is empty.")
    return result


def attach_spot_locations(quotes: list[dict], directory: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Enrich actual region-bound Spot quotes; do not create or duplicate rows."""
    result, gaps = [], []
    for supplied in quotes:
        quote = deepcopy(supplied)
        codes = quote.get("regions")
        if (quote.get("provider") != "nebius" or quote.get("billing_mode") != "spot"
                or quote.get("source_type") != "official_public_api"
                or not isinstance(codes, list) or len(codes) != 1):
            raise ValueError("Expected one actual Nebius Spot API region per quote.")
        location = directory.get(codes[0])
        if location is None or location.get("country_code") is None:
            # Remove a historical constant's country if fresh evidence cannot
            # verify it, while preserving the real price and source region.
            quote["compute_countries"] = []
            quote["location"] = {"region": codes[0]}
            quote["location_source"] = {"url": REGIONS_URL, "country_basis": "not_in_verified_live_directory"}
            gaps.append({"region": codes[0], "status": "country_not_verified",
                         "scope": "spot_region_country", "source_url": REGIONS_URL})
        else:
            quote["compute_countries"] = [location["country_code"]]
            quote["location"] = {key: deepcopy(location[key]) for key in
                                 ("region", "region_name", "region_name_zh", "country_code", "country_name", "country_name_zh")}
            quote["location_source"] = {"url": REGIONS_URL,
                                        "source_type": "official_region_directory",
                                        "country_basis": location["country_basis"],
                                        "observed_at": location["observed_at"],
                                        "directory_sha256": location["directory_sha256"]}
            quote["region_access"] = "existing_deployments_only" if location["private_region"] else "public"
        result.append(quote)
    return result, gaps
