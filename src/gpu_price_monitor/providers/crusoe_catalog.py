"""Collect Crusoe's public price and deployed-VM catalogs independently.

The VM table binds exact configurations to deployment zones. It does not bind
the separate marketing prices to those zones. Both facts are returned without
turning documented deployment locations into regional price quotations.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re

from bs4 import BeautifulSoup

from ..settings import Settings
from ..transport import FetchError, fetch_text
from . import crusoe

SOURCE_URL = crusoe.SOURCE_URL
SOURCE_TYPE = "official_public_sources"
VM_CATALOG_URL = "https://docs.crusoecloud.com/compute/virtual-machines/overview/"
VM_TYPES_URL = VM_CATALOG_URL
LOCATIONS_URL = "https://docs.crusoecloud.com/locations/"
OPENAPI_URL = "https://api.crusoecloud.com/v1/openapi.json"
LOGIN_URL = "https://console.crusoecloud.com/"
_ZONE = re.compile(r"[a-z][a-z0-9-]*[0-9]-[a-z]\Z")
_GPU = re.compile(r"([1-9][0-9]*)x (NVIDIA|AMD) ([A-Za-z0-9 ]+?) ([1-9][0-9]*)GB (.+)", re.IGNORECASE)
_VM_COLUMNS = ("Type", "vCPU", "GPU", "Memory", "Ephemeral Disk", "VPC Network",
               "InfiniBand Network", "Block Storage Network", "Zones")
_LOCATION_COLUMNS = ("Location", "ID", "Energy profile")
# Normalize explicit city/state/country labels from the official location
# directory. A new label needs review; no country is guessed from an ID prefix.
_PLACE_NAMES = {
    "Houston, TX": ("US", "United States", "美国", "休斯敦（得克萨斯州）"),
    "Iceland": ("IS", "Iceland", "冰岛", "冰岛"),
    "Norway": ("NO", "Norway", "挪威", "挪威"),
    "Ohio": ("US", "United States", "美国", "俄亥俄州"),
    "Sparks, NV": ("US", "United States", "美国", "斯帕克斯（内华达州）"),
    "Virginia": ("US", "United States", "美国", "弗吉尼亚州"),
}


def _invalid() -> ValueError:
    return ValueError("The Crusoe public VM or location catalog structure changed.")


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).replace("\u200b", "").split())


def _table(content: str, heading: str, columns: tuple[str, ...]) -> list[list[str]]:
    soup = BeautifulSoup(content, "html.parser")
    headings = [node for node in soup.find_all(re.compile(r"^h[1-6]$")) if _text(node) == heading]
    if len(headings) != 1:
        raise _invalid()
    table = None
    for element in headings[0].find_all_next(["h1", "h2", "h3", "h4", "table"]):
        if element.name != "table":
            break
        table = element
        break
    if table is None:
        raise _invalid()
    rows = [[_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            for row in table.find_all("tr")]
    if (not rows or tuple(rows[0]) != columns or len(rows) < 2
            or any(len(row) != len(columns) for row in rows[1:])):
        raise _invalid()
    return rows[1:]


def parse_locations(content: str) -> dict[str, dict]:
    """Parse all documented locations, including explicit country evidence."""
    locations = {}
    for name, code, energy in _table(content, "Data centers", _LOCATION_COLUMNS):
        if name not in _PLACE_NAMES or not _ZONE.fullmatch(code) or code in locations or not energy:
            raise _invalid()
        country, english, chinese, region_name = _PLACE_NAMES[name]
        locations[code] = {
            "zone": code, "region": code.rsplit("-", 1)[0], "name": name,
            "country_code": country, "country_name": english, "country_name_zh": chinese,
            "region_name_zh": region_name, "energy_profile": energy,
            "source_url": LOCATIONS_URL,
            "country_basis": "normalized_explicit_place_label_not_region_prefix",
        }
    return locations


def parse_vm_catalog(content: str, locations: dict[str, dict]) -> list[dict]:
    """Parse exact deployed GPU VM specifications; these are not price rows."""
    if not isinstance(locations, dict) or not locations:
        raise _invalid()
    catalog, seen = [], set()
    for row in _table(content, "GPU-enabled VMs", _VM_COLUMNS):
        sku, cpu, gpu, memory, disk, vpc, infiniband, block, zone_text = row
        gpu_match = _GPU.fullmatch(gpu)
        cpu_match = re.fullmatch(r"([1-9][0-9]*) vCPUs (.+)", cpu)
        memory_match = re.fullmatch(r"([1-9][0-9]*)GB", memory)
        zones = zone_text.split(", ")
        if (not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,127}", sku) or sku in seen
                or not gpu_match or not cpu_match or not memory_match or not zones
                or len(zones) != len(set(zones)) or any(zone not in locations for zone in zones)
                or not all((disk, vpc, infiniband, block))):
            raise _invalid()
        seen.add(sku)
        catalog.append({
            "provider": "crusoe", "record_type": "documented_vm_availability", "raw_sku": sku,
            "gpu_model": gpu_match[3].upper(), "gpu_vendor": gpu_match[2].upper(),
            "gpu_count": int(gpu_match[1]), "vram_gb": int(gpu_match[4]),
            "gpu_variant": gpu_match[5], "gpu_description": gpu,
            "vcpus": int(cpu_match[1]), "cpu_description": cpu_match[2],
            "memory_gb": int(memory_match[1]), "ephemeral_disk_description": disk,
            "vpc_network_description": vpc, "infiniband_network_description": infiniband,
            "block_storage_network_description": block,
            "coverage_zones": zones, "coverage_regions": list(dict.fromkeys(locations[z]["region"] for z in zones)),
            "coverage_countries": sorted({locations[z]["country_code"] for z in zones}),
            "coverage_locations": [deepcopy(locations[zone]) for zone in zones],
            "source_url": VM_CATALOG_URL, "location_source_url": LOCATIONS_URL,
            "stock_verified": False, "orderability_verified": False,
            "independent_provider_quote": False, "price_applicability_verified": False,
            "notes": ["Documented deployment zones are not current stock or independently verified regional prices.",
                      "Some documented VM types may require account access or sales approval."],
        })
    return catalog


def _variant_group(value: str | None) -> str:
    value = (value or "").upper()
    if value in {"HGX", "SXM", "SXM4", "SXM5", "SXM6"}:
        return "SXM"
    if value == "PCIE":
        return "PCIE"
    return value


def annotate_prices(prices: list[dict], vm_catalog: list[dict], locations: dict[str, dict]) -> list[dict]:
    """Attach deployment evidence without asserting a price's geographic scope."""
    result = []
    for original in prices:
        quote = deepcopy(original)
        candidates = [vm for vm in vm_catalog
                      if vm["gpu_model"] == quote["gpu_model"] and vm["vram_gb"] == quote["vram_gb"]
                      and (not quote["gpu_variant"] or _variant_group(vm["gpu_variant"]) == _variant_group(quote["gpu_variant"]))]
        zones = sorted({zone for vm in candidates for zone in vm["coverage_zones"]})
        quote.update(
            regions=[], zones=[], compute_countries=[], geographic_scope="unspecified",
            price_scope="unlocated_catalog", region_price_verified=False,
            documented_vm_configurations=deepcopy(candidates),
            coverage_zones=zones,
            coverage_regions=list(dict.fromkeys(locations[zone]["region"] for zone in zones)),
            coverage_countries=sorted({locations[zone]["country_code"] for zone in zones}),
            coverage_locations=[deepcopy(locations[zone]) for zone in zones],
            coverage_location_source={"url": LOCATIONS_URL, "types_url": VM_CATALOG_URL,
                                      "basis": "documented_vm_deployment_not_price_applicability"},
            price_applicability={
                "status": "unverified", "uniform_price_verified": False,
                "independent_regional_quote_count": 0,
                "reason": "Public price table does not bind its rates to documented deployment zones or declare a uniform geographic tariff.",
            },
        )
        quote.setdefault("notes", []).append(
            "Matched documented VM deployment locations are returned separately; the public rate is not copied into regional prices or labeled globally uniform.")
        result.append(quote)
    return result


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Read three public sources, preserving prices when a metadata source fails."""
    errors, contexts, prices, locations, catalog = [], [], [], {}, []
    as_of = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).date()

    def read(url: str, parser, label: str):
        try:
            value = parser(fetch_text(url, settings))
            contexts.append({"source_url": url, "source_type": "official_pricing_page" if url == SOURCE_URL else "official_documentation",
                             "collection_method": "http_html", "status": "ok", "scope": label,
                             "observed_at": observed_at})
            return value
        except FetchError as exc:
            error = {"source_url": url, "source": label, "code": exc.code, "message": str(exc), "retryable": exc.retryable}
        except (ValueError, KeyError, TypeError, ArithmeticError):
            error = {"source_url": url, "source": label, "code": "parse_failed",
                     "message": "The Crusoe public catalog source could not be verified.", "retryable": False}
        errors.append(error)
        contexts.append({"source_url": url, "source_type": "official_pricing_page" if url == SOURCE_URL else "official_documentation",
                         "collection_method": "http_html", "status": "failed", "scope": label,
                         "observed_at": observed_at})
        return None

    prices = read(SOURCE_URL, lambda content: crusoe.parse_prices(content, observed_at=observed_at, as_of=as_of),
                  "public_gpu_price_table") or []
    locations = read(LOCATIONS_URL, parse_locations, "documented_location_directory") or {}
    if locations:
        catalog = read(VM_CATALOG_URL, lambda content: parse_vm_catalog(content, locations),
                       "documented_gpu_vm_catalog") or []
    else:
        errors.append({"source_url": VM_CATALOG_URL, "source": "documented_gpu_vm_catalog", "code": "dependency_failed",
                       "message": "The VM catalog cannot verify countries without the official location directory.", "retryable": False})
    prices = annotate_prices(prices, catalog, locations)
    summary = {"public_price_cell_count": len(prices),
               "numeric_price_count": sum(q["amount"] is not None for q in prices),
               "contact_sales_count": sum(q["quote_status"] == "contact_sales" for q in prices),
               "documented_vm_configuration_count": len(catalog),
               "documented_location_count": len(locations),
               "documented_country_count": len({location["country_code"] for location in locations.values()}),
               "independent_regional_quote_count": 0, "uniform_price_verified": False}
    return {
        "status": ("partial" if prices else "failed") if errors else "ok",
        "prices": prices, "errors": errors, "source_contexts": contexts, "uses_llm": False,
        "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "coverage": summary,
        "catalog_coverage": {"summary": summary, "availability_catalog": catalog,
                             "location_catalog": locations, "pricing_source_url": SOURCE_URL,
                             "types_source_url": VM_CATALOG_URL, "locations_source_url": LOCATIONS_URL},
        "gaps": [{"scope": "regional_and_uniform_gpu_rental_prices", "status": "not_verified",
                  "source_url": SOURCE_URL, "login_url": LOGIN_URL,
                  "reason": "No geographic price binding or universal uniform-price statement is supplied by the public table; documented deployment locations are metadata only."},
                 {"scope": "gpu_rental_price_api", "status": "not_found_in_current_public_schema",
                  "source_url": OPENAPI_URL, "login_url": LOGIN_URL,
                  "reason": "VM types lack prices; existing-account bills, reservation contracts and model deployment rates are different data scopes."}],
    }


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    outcome = collect_result(settings=settings, observed_at=observed_at)
    if outcome["errors"]:
        raise FetchError("partial_collection", "One independent Crusoe public source failed; inspect collect_result diagnostics.")
    return outcome["prices"]
