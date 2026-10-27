"""Anonymous Azure retail rates for explicitly documented whole-GPU VM sizes.

Only base VM Consumption products are collected. Windows-license products,
Low Priority, reservations, Dev/Test and savings-plan nested rates are outside
this scope. A regional retail meter is not a current capacity assertion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://prices.azure.com/api/retail/prices"
SOURCE_TYPE = "official_public_api"
DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices"
API_VERSION = "2023-01-01-preview"
REGIONS_DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/azure/reliability/regions-list"
GOVERNMENT_REGIONS_DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/azure/azure-government/documentation-government-welcome"
SENTINEL_GEOGRAPHY_DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/azure/sentinel/geographical-availability-data-residency"
REGION_NAMES_DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/azure/defender-for-cloud/concept-data-security-posture-prepare"
PIPELINES_GEOGRAPHY_DOCUMENTATION_URL = "https://learn.microsoft.com/en-us/azure/devops/pipelines/agents/hosted?view=azure-devops-2022"
# The MEC documentation was archived in 2024. Pin the Microsoft-owned source to
# its last commit before archival so the exact Edge Zone ID remains reviewable.
MEC_REGIONS_DOCUMENTATION_URL = "https://github.com/MicrosoftDocs/azure-docs/blob/b18b0e4c79b722bb6da2d86c654376dd45eba817/articles/public-multi-access-edge-compute-mec/key-concepts.md"
MEC_LOCATIONS_DOCUMENTATION_URL = "https://azure.microsoft.com/en-us/blog/microsoft-and-att-are-accelerating-the-enterprise-customer-s-journey-to-the-edge-with-5g/"
# Explicit programmatic-name rows verified against the official region directory
# on 2026-10-21; broad labels such as Europe/Asia Pacific use its physical location.
# Additional directories below bind named government, Jio and MEC locations to
# their exact identifiers. Any region without this evidence stays unknown.
_REGION_COUNTRIES = {
    'attatlanta1': 'US',
    'attdallas1': 'US',
    'australiacentral': 'AU',
    'australiacentral2': 'AU',
    'australiaeast': 'AU',
    'australiasoutheast': 'AU',
    'austriaeast': 'AT',
    'belgiumcentral': 'BE',
    'brazilsouth': 'BR',
    'brazilsoutheast': 'BR',
    'canadacentral': 'CA',
    'canadaeast': 'CA',
    'centralindia': 'IN',
    'centralus': 'US',
    'chilecentral': 'CL',
    'denmarkeast': 'DK',
    'eastasia': 'HK',
    'eastus': 'US',
    'eastus2': 'US',
    'eastus3': 'US',
    'francecentral': 'FR',
    'francesouth': 'FR',
    'germanynorth': 'DE',
    'germanywestcentral': 'DE',
    'indiasouthcentral': 'IN',
    'indonesiacentral': 'ID',
    'israelcentral': 'IL',
    'italynorth': 'IT',
    'japaneast': 'JP',
    'japanwest': 'JP',
    'jioindiacentral': 'IN',
    'jioindiawest': 'IN',
    'koreacentral': 'KR',
    'koreasouth': 'KR',
    'malaysiawest': 'MY',
    'mexicocentral': 'MX',
    'newzealandnorth': 'NZ',
    'northcentralus': 'US',
    'northeurope': 'IE',
    'norwayeast': 'NO',
    'norwaywest': 'NO',
    'polandcentral': 'PL',
    'qatarcentral': 'QA',
    'southafricanorth': 'ZA',
    'southafricawest': 'ZA',
    'southcentralus': 'US',
    'southeastasia': 'SG',
    'southindia': 'IN',
    'spaincentral': 'ES',
    'swedencentral': 'SE',
    'switzerlandnorth': 'CH',
    'switzerlandwest': 'CH',
    'taiwannorth': 'TW',
    'uaecentral': 'AE',
    'uaenorth': 'AE',
    'uksouth': 'GB',
    'ukwest': 'GB',
    'usgovarizona': 'US',
    'usgovvirginia': 'US',
    'westcentralus': 'US',
    'westeurope': 'NL',
    'westindia': 'IN',
    'westus': 'US',
    'westus2': 'US',
    'westus3': 'US',
}
_REGION_COUNTRY_SOURCES = {
    region: {"url": REGIONS_DOCUMENTATION_URL, "source_type": "official_region_directory",
             "verified_on": "2026-10-21", "region_field": "Programmatic name",
             "country_basis": "explicit_region_geography_or_physical_location"}
    for region in _REGION_COUNTRIES
}
_REGION_COUNTRY_SOURCES["eastus3"] = {
    "url": PIPELINES_GEOGRAPHY_DOCUMENTATION_URL, "source_type": "official_geography_document",
    "verified_on": "2026-10-27", "region_field": "USGeographyRegions",
    "country_basis": "explicit_programmatic_region_in_united_states_geography",
}
for _region in ("usgovarizona", "usgovvirginia"):
    _REGION_COUNTRY_SOURCES[_region] = {
        "url": GOVERNMENT_REGIONS_DOCUMENTATION_URL, "source_type": "official_region_directory",
        "verified_on": "2026-10-21", "region_field": "Programmatic name",
        "country_basis": "explicit_government_region_and_us_only_datacenters",
    }
for _region in ("jioindiacentral", "jioindiawest"):
    _REGION_COUNTRY_SOURCES[_region] = {
        "url": SENTINEL_GEOGRAPHY_DOCUMENTATION_URL, "source_type": "official_geography_document",
        "verified_on": "2026-10-21", "region_field": "SIEM supported region",
        "country_basis": "explicit_region_country_table",
        "region_name_source_url": REGION_NAMES_DOCUMENTATION_URL,
    }
for _region in ("attatlanta1", "attdallas1"):
    _REGION_COUNTRY_SOURCES[_region] = {
        "url": MEC_REGIONS_DOCUMENTATION_URL, "source_type": "official_region_directory",
        "verified_on": "2026-10-21", "region_field": "Edge Zone ID",
        "country_basis": "explicit_edge_zone_id_and_documented_physical_city",
        "physical_location_source_url": MEC_LOCATIONS_DOCUMENTATION_URL,
        "archived": True,
    }
del _region


def _location_source(region: str) -> dict:
    """Return country evidence only for an explicitly verified region identifier."""
    source = _REGION_COUNTRY_SOURCES.get(region)
    if source is None:
        return {"url": None, "source_type": "unknown", "verified_on": None,
                "region_field": "armRegionName", "country_basis": "unverified_region"}
    return dict(source)


MAX_PAGES_PER_SKU = 5
MAX_ITEMS_PER_PAGE = 1000
_SPECS = {
    "Standard_NC4as_T4_v3": {
        "gpu_model": "T4", "gpu_count": 1, "vram_gb": 16, "vcpus": 4, "memory_gib": 28,
        "product": "Virtual Machines NCasT4 v3 Series", "meter": "NC4as T4 v3",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series",
    },
    "Standard_ND128isr_NDR_GB200_v6": {
        "gpu_model": "GB200", "gpu_count": 4, "vram_gb": 192, "vcpus": 128, "memory_gib": 900,
        "product": "Virtual Machines NDsrGB200NDRv6 Series", "meter": "ND128isrNDRGB200v6",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-gb200-v6-series",
    },
    "Standard_NC40ads_H100_v5": {
        "gpu_model": "H100", "gpu_variant": "NVL", "gpu_count": 1, "vram_gb": 94,
        "vcpus": 40, "memory_gib": 320,
        "product": "Virtual Machines NCadsH100v5 Series", "meter": "NC40adsH100v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/ncads-h100-v5",
    },
    "Standard_NC24ads_A100_v4": {
        "gpu_model": "A100", "gpu_variant": "PCIe", "gpu_count": 1, "vram_gb": 80,
        "vcpus": 24, "memory_gib": 220,
        "product": "NCads A100 v4 Series Linux", "meter": "NC24ads_A100_v4",
        "sku": "Standard_NC24ads_A100_v4",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nca100v4-series",
    },
    "Standard_NC8as_T4_v3": {
        "gpu_model": "T4", "gpu_count": 1, "vram_gb": 16, "vcpus": 8, "memory_gib": 56,
        "product": "Virtual Machines NCasT4 v3 Series", "meter": "NC8as T4 v3",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series",
    },
    "Standard_NC16as_T4_v3": {
        "gpu_model": "T4", "gpu_count": 1, "vram_gb": 16, "vcpus": 16, "memory_gib": 110,
        "product": "Virtual Machines NCasT4 v3 Series", "meter": "NC16asT4 v3",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series",
    },
    "Standard_NC64as_T4_v3": {
        "gpu_model": "T4", "gpu_count": 4, "vram_gb": 16, "vcpus": 64, "memory_gib": 440,
        "product": "Virtual Machines NCasT4 v3 Series", "meter": "NC64asT4 v3",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series",
    },
    "Standard_NC48ads_A100_v4": {
        "gpu_model": "A100", "gpu_variant": "PCIe", "gpu_count": 2, "vram_gb": 80,
        "vcpus": 48, "memory_gib": 440,
        "product": "NCads A100 v4 Series Linux", "meter": "NC48ads_A100_v4",
        "sku": "Standard_NC48ads_A100_v4",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nca100v4-series",
    },
    "Standard_NC96ads_A100_v4": {
        "gpu_model": "A100", "gpu_variant": "PCIe", "gpu_count": 4, "vram_gb": 80,
        "vcpus": 96, "memory_gib": 880,
        "product": "NCads A100 v4 Series Linux", "meter": "NC96ads_A100_v4",
        "sku": "Standard_NC96ads_A100_v4",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nca100v4-series",
    },
    "Standard_NC80adis_H100_v5": {
        "gpu_model": "H100", "gpu_variant": "NVL", "gpu_count": 2, "vram_gb": 94,
        "vcpus": 80, "memory_gib": 640,
        "product": "Virtual Machines NCadsH100v5 Series", "meter": "NC80adisH100v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncadsh100v5-series",
    },
    "Standard_ND96asr_v4": {
        "gpu_model": "A100", "gpu_count": 8, "vram_gb": 40, "vcpus": 96, "memory_gib": 900,
        "product": "Virtual Machines NDasr A100 v4 Series", "meter": "ND96asr_A100_v4",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndasra100v4-series",
    },
    "Standard_ND96amsr_A100_v4": {
        "gpu_model": "A100", "gpu_count": 8, "vram_gb": 80, "vcpus": 96, "memory_gib": 1900,
        "product": "Virtual Machines NDamsr A100 v4 Series Linux", "meter": "ND96amsr A100 v4",
        "sku": "Standard_ND96amsr_A100_v4",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndma100v4-series",
    },
    "Standard_ND96isr_H100_v5": {
        "gpu_model": "H100", "gpu_count": 8, "vram_gb": 80, "vcpus": 96, "memory_gib": 1900,
        "product": "Virtual Machines NDsr H100 v5 Series", "meter": "ND96isrH100v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndh100v5-series",
    },
    "Standard_ND96isr_MI300X_v5": {
        "gpu_model": "MI300X", "gpu_vendor": "AMD", "gpu_count": 8, "vram_gb": 192,
        "vcpus": 96, "memory_gib": 1850,
        "product": "Virtual Machines NDMI300Xv5 Srs", "meter": "ND96isrMI300Xv5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndmi300xv5-series",
    },
    "Standard_NV36ads_A10_v5": {
        "gpu_model": "A10", "gpu_count": 1, "vram_gb": 24, "vcpus": 36, "memory_gib": 440,
        "product": "Virtual Machines NVadsA10v5 Series", "meter": "NV36ads A10 v5",
        "sku": "Standard_NV36ads_A10_v5", "included_license": "NVIDIA GRID",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsa10v5-series",
    },
    "Standard_NV36adms_A10_v5": {
        "gpu_model": "A10", "gpu_count": 1, "vram_gb": 24, "vcpus": 36, "memory_gib": 880,
        "product": "Virtual Machines NVadsA10v5 Series", "meter": "NV36adms A10 v5",
        "sku": "Standard_NV36adms_A10_v5", "included_license": "NVIDIA GRID",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsa10v5-series",
    },
    "Standard_NV72ads_A10_v5": {
        "gpu_model": "A10", "gpu_count": 2, "vram_gb": 24, "vcpus": 72, "memory_gib": 880,
        "product": "Virtual Machines NVadsA10v5 Series", "meter": "NV72ads A10 v5",
        "sku": "Standard_NV72ads_A10_v5", "included_license": "NVIDIA GRID",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsa10v5-series",
    },
    "Standard_ND96isr_H200_v5": {
        "gpu_model": "H200", "gpu_count": 8, "vram_gb": 141,
        "vcpus": 96, "memory_gib": 1850,
        "product": "Virtual Machines NDsrH200v5 Series", "meter": "ND96isrH200v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-h200-v5-series",
    },
    "Standard_NCC40ads_H100_v5": {
        "gpu_model": "H100", "gpu_variant": "NVL", "gpu_count": 1, "vram_gb": 94,
        "vcpus": 40, "memory_gib": 320, "confidential_vm": True,
        "product": "Virtual Machines NCCadsv5 Srs", "meter": "NCC40adsH100v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nccadsh100v5-series",
    },
    "Standard_ND40rs_v2": {
        "gpu_model": "V100", "gpu_variant": "NVLink", "gpu_count": 8, "vram_gb": 32,
        "vcpus": 40, "memory_gib": 672,
        "product": "Virtual Machines NDrSv2 Series", "meter": "ND40rs v2",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndv2-series",
    },
    "Standard_NC144ds_xl_RTXPRO6000BSE_v6": {
        "gpu_model": "RTX PRO 6000", "gpu_variant": "Blackwell Server Edition",
        "gpu_count": 1, "vram_gb": 96, "vcpus": 144, "memory_gib": 516,
        "product": "Virtual Machines NCdsxlRTX6kv6", "meter": "NC144dsxlRTX6kv6",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-rtxpro6000-bse-v6-series",
    },
    "Standard_NC288ds_xl_RTXPRO6000BSE_v6": {
        "gpu_model": "RTX PRO 6000", "gpu_variant": "Blackwell Server Edition",
        "gpu_count": 2, "vram_gb": 96, "vcpus": 288, "memory_gib": 1032,
        "product": "Virtual Machines NCdsxlRTX6kv6", "meter": "NC288dsxlRTX6kv6",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-rtxpro6000-bse-v6-series",
    },
    "Standard_NC144lds_xl_RTXPRO6000BSE_v6": {
        "gpu_model": "RTX PRO 6000", "gpu_variant": "Blackwell Server Edition",
        "gpu_count": 1, "vram_gb": 96, "vcpus": 144, "memory_gib": 264,
        "product": "Virtual Machines NCldsxlRTX6kv6", "meter": "NC144ldsxlRTX6kv6",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-rtxpro6000-bse-v6-series",
    },
    "Standard_NC288lds_xl_RTXPRO6000BSE_v6": {
        "gpu_model": "RTX PRO 6000", "gpu_variant": "Blackwell Server Edition",
        "gpu_count": 2, "vram_gb": 96, "vcpus": 288, "memory_gib": 516,
        "product": "Virtual Machines NCldsxlRTX6kv6", "meter": "NC288ldsxlRTX6kv6",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-rtxpro6000-bse-v6-series",
    },
    "Standard_NV24ads_V710_v5": {
        "gpu_model": "RADEON PRO V710", "gpu_vendor": "AMD", "gpu_count": 1, "vram_gb": 24,
        "vcpus": 24, "memory_gib": 128,
        "product": "Virtual Machines NVadsV710v5 Series", "meter": "NV24adsV710v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsv710-v5-series",
    },
    "Standard_NV28adms_V710_v5": {
        "gpu_model": "RADEON PRO V710", "gpu_vendor": "AMD", "gpu_count": 1, "vram_gb": 24,
        "vcpus": 28, "memory_gib": 160,
        "product": "Virtual Machines NVadsV710v5 Series", "meter": "NV28admsV710v5",
        "source": "https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsv710-v5-series",
    },
}


def _invalid() -> ValueError:
    return ValueError("The Azure regional retail meter, unit, scope or effective date was not recognized.")


def _parameters(arm_sku: str) -> dict[str, str]:
    spec = _SPECS[arm_sku]
    return {
        "api-version": API_VERSION, "currencyCode": "USD", "meterRegion": "'primary'",
        "$filter": ("serviceName eq 'Virtual Machines' and armSkuName eq '" + arm_sku
                    + "' and priceType eq 'Consumption' and productName eq '" + spec["product"] + "'"),
    }


def query_url(arm_sku: str, *, skip: int = 0) -> str:
    """Build only fixed public retail queries, never arbitrary user filters."""
    parameters = _parameters(arm_sku)
    if skip:
        parameters["$skip"] = str(skip)
    return SOURCE_URL + "?" + urlencode(parameters)


def _next_skip(value: object, arm_sku: str, previous_skip: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise FetchError("invalid_pagination", "Azure returned an invalid retail-price continuation link.")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname != "prices.azure.com"
                or parsed.port not in (None, 443) or parsed.username is not None or parsed.password is not None
                or parsed.path != "/api/retail/prices" or parsed.fragment):
            raise ValueError
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        expected = _parameters(arm_sku)
        if (set(query) - set(expected) - {"$skip"} or any(len(values) != 1 for values in query.values())
                or query.get("$filter") != [expected["$filter"]]
                or any(query[key] != [value] for key, value in expected.items() if key in query)):
            raise ValueError
        offset = query.get("$skip", [""])[0]
        if not re.fullmatch(r"[1-9]\d{0,5}", offset):
            raise ValueError
        skip = int(offset)
        if skip <= previous_skip or skip > MAX_PAGES_PER_SKU * MAX_ITEMS_PER_PAGE:
            raise ValueError
    except (ValueError, TypeError):
        raise FetchError("invalid_pagination", "Azure returned an invalid retail-price continuation link.") from None
    return skip


def _text(value: object, *, limit: int = 200) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(ord(char) < 32 for char in value)):
        raise _invalid()
    return value


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or "T" not in value:
        raise _invalid()
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise _invalid() from None


def _number(value: object, *, positive: bool) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid()
    amount = Decimal(value)
    if (not amount.is_finite() or amount < 0 or (positive and amount == 0)
            or (amount and (amount.adjusted() > 12 or amount.as_tuple().exponent < -50))):
        raise _invalid()
    return amount


def parse_items(items: list[dict], *, arm_sku: str, observed_at: str) -> list[dict]:
    """Return the latest already-effective base VM rate per region and mode."""
    if arm_sku not in _SPECS or not isinstance(items, list) or len(items) > MAX_PAGES_PER_SKU * MAX_ITEMS_PER_PAGE:
        raise _invalid()
    spec, observed = _SPECS[arm_sku], _instant(observed_at)
    selected, seen = {}, set()
    for row in items:
        if not isinstance(row, dict):
            raise _invalid()
        if (row.get("armSkuName") != arm_sku or row.get("serviceName") != "Virtual Machines"
                or row.get("serviceFamily") != "Compute" or row.get("type") != "Consumption"
                or row.get("productName") != spec["product"] or row.get("currencyCode") != "USD"
                or row.get("isPrimaryMeterRegion") is not True):
            raise _invalid()
        meter = row.get("meterName")
        sku_name = row.get("skuName")
        expected_sku = spec.get("sku", spec["meter"])
        if (not isinstance(meter, str) or not meter.startswith(spec["meter"])
                or sku_name != expected_sku + meter[len(spec["meter"]):]):
            raise _invalid()
        if meter == spec["meter"] + " Low Priority":
            # This legacy purchasing option is neither ordinary nor Spot.
            continue
        if meter == spec["meter"]:
            mode = "on_demand"
        elif meter == spec["meter"] + " Spot":
            mode = "spot"
        else:
            raise _invalid()
        if (row.get("unitOfMeasure") != "1 Hour" or row.get("reservationTerm")
                or _number(row.get("tierMinimumUnits"), positive=False) != 0):
            raise _invalid()
        total = _number(row.get("retailPrice"), positive=True)
        if total != _number(row.get("unitPrice"), positive=True):
            raise _invalid()
        region = _text(row.get("armRegionName"), limit=80)
        if not re.fullmatch(r"[a-z][a-z0-9]{0,79}", region):
            raise _invalid()
        location = _text(row.get("location"))
        meter_id, sku_id, product_id = (_text(row.get(field)) for field in ("meterId", "skuId", "productId"))
        effective = _instant(row.get("effectiveStartDate"))
        revision = (meter_id, effective)
        if revision in seen:
            raise _invalid()
        seen.add(revision)
        if effective > observed:
            continue
        identity = (region, mode)
        if identity in selected:
            previous_effective, _ = selected[identity]
            if previous_effective == effective:
                raise _invalid()
            if previous_effective > effective:
                continue
        with localcontext(Context(prec=max(80, len(total.as_tuple().digits) + 10))):
            amount = total / spec["gpu_count"]
        notes = [
            "Anonymous Microsoft retail rate for the explicitly named base VM product in the returned ARM region; Windows-license products are excluded.",
            "The instance hourly retail total is allocated across the GPU count documented for this exact VM size; managed disks, networking and other services are not included.",
            "Only already-effective Consumption primary meters are returned; Low Priority, Dev/Test, reservations and nested savings-plan rates are excluded.",
            "Regional retail listings do not verify quota, capacity, subscription access, availability zones, tax or orderability.",
        ]
        if mode == "spot":
            notes.append("Spot has separate interruption and capacity conditions; its published retail rate is not a guaranteed future price or available offer.")
        if spec.get("included_license"):
            notes.append("This NVadsA10 v5 instance includes a NVIDIA GRID license according to its hardware specification; fractional GPU sizes are excluded.")
        if spec["gpu_model"] == "MI300X":
            notes.append("192 GB is the documented nominal memory per MI300X accelerator; the specification lists 1,535 GB at VM level, not eight independently allocated memory amounts.")
        quote = {
            "provider": "azure", "product_type": "gpu_instance", "gpu_model": spec["gpu_model"],
            "gpu_vendor": spec.get("gpu_vendor", "NVIDIA"),
            "gpu_variant": spec.get("gpu_variant"), "raw_name": meter, "raw_sku": arm_sku,
            "vram_gb": spec["vram_gb"], "gpu_count": spec["gpu_count"],
            "amount": format(amount, "f"), "currency": "USD", "unit": "gpu_hour",
            "billing_mode": mode, "price_basis": "instance_total_allocated", "quote_status": "quoted",
            "instance_price": {"amount": format(total, "f"), "currency": "USD", "unit": "instance_hour"},
            "resources": {"vcpus": spec["vcpus"], "memory_gib": spec["memory_gib"]},
            "conditions": {"product_scope": "base_vm_without_windows_license", "purchase_option": mode},
            "regions": [region], "zones": [], "geographic_scope": "regions",
            "location": {"region": region, "region_name": location},
            "compute_countries": [_REGION_COUNTRIES[region]] if region in _REGION_COUNTRIES else [],
            "location_source": _location_source(region),
            "account_scope": "public_catalog", "tax_scope": "unspecified", "availability": "unknown",
            "observed_at": observed_at, "effective_from": effective.isoformat(), "effective_until": None,
            "source_url": query_url(arm_sku), "source_type": SOURCE_TYPE,
            "api_documentation_url": DOCUMENTATION_URL, "hardware_source_url": spec["source"],
            "azure_meter": {"meter_id": meter_id, "product_id": product_id, "sku_id": sku_id,
                            "product_name": spec["product"], "meter_name": meter,
                            "is_primary_meter_region": True, "tier_minimum_units": "0"},
            "normalization": {"formula": "instance_price.amount / gpu_count", "rounding": "exact"},
            "notes": notes,
        }
        if spec.get("included_license"):
            quote["conditions"]["included_license"] = spec["included_license"]
        if spec.get("confidential_vm"):
            quote["conditions"]["confidential_vm"] = True
        selected[identity] = (effective, quote)
    return [selected[key][1] for key in sorted(selected)]


def _fetch_items(arm_sku: str, settings: Settings) -> list[dict]:
    items, skip = [], 0
    for page in range(MAX_PAGES_PER_SKU):
        # Rebuild every URL from fixed scope and a validated monotonic offset.
        # No URL supplied by the response is ever requested directly.
        payload = request_json(query_url(arm_sku, skip=skip), settings, authenticated=False)
        if (payload.get("BillingCurrency") != "USD" or payload.get("CustomerEntityType") != "Retail"
                or not isinstance(payload.get("Items"), list) or type(payload.get("Count")) is not int
                or payload["Count"] != len(payload["Items"]) or payload["Count"] > MAX_ITEMS_PER_PAGE
                or "NextPageLink" not in payload):
            raise FetchError("invalid_public_catalog", "Azure returned an incomplete or unexpected retail-price page.")
        items.extend(payload["Items"])
        next_skip = _next_skip(payload["NextPageLink"], arm_sku, skip)
        if next_skip is None:
            return items
        if next_skip != skip + payload["Count"]:
            raise FetchError("invalid_pagination", "Azure returned a noncontiguous retail-price continuation.")
        if not payload["Items"] or page + 1 == MAX_PAGES_PER_SKU:
            raise FetchError("pagination_limit", "Azure retail-price pagination did not complete within the collection limit.")
        skip = next_skip
    raise FetchError("pagination_limit", "Azure retail-price pagination did not complete within the collection limit.")


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Read fixed GPU sizes without credentials or resource operations."""
    quotes = []
    for arm_sku in _SPECS:
        prices = parse_items(_fetch_items(arm_sku, settings), arm_sku=arm_sku, observed_at=observed_at)
        if not prices:
            raise FetchError("empty_public_catalog", "Azure returned no already-effective rates for a configured GPU size.")
        quotes.extend(prices)
    return quotes
