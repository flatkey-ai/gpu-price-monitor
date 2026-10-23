"""Read the anonymous RunPod GPU Pods catalog, without provisioning resources.

The catalog's cloud-enable flags matter: a disabled cloud can still carry a
placeholder amount. These are per-GPU catalog rates, not complete-instance
quotes or a promise that any datacenter currently has stock.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from decimal import Decimal

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://www.runpod.io/pricing"
SOURCE_TYPE = "official_public_api"
API_URL = "https://api.runpod.io/graphql"
DOCUMENTATION_URL = "https://graphql-spec.runpod.io/"
PRICE_BASIS_URL = "https://www.runpod.io/articles/comparison/runpod-vs-replicate"

# Only GPU Pods on-demand prices. No mutations, account queries, serverless,
# spot, reserved plans, or datacenter inventory fields are requested.
GPU_TYPES_QUERY = """query PublicGpuPodPrices {
  gpuTypes {
    id displayName memoryInGb
    secureCloud communityCloud securePrice communityPrice
  }
}"""
_TIERS = (("secure", "secureCloud", "securePrice"),
          ("community", "communityCloud", "communityPrice"))
_VARIANT = re.compile(r"\b(?:SXM\d*|PCIe|NVL)\b", re.IGNORECASE)
_PARTITION = re.compile(r"\b(?:MIG|vGPU)\b", re.IGNORECASE)
_MAX_GPU_TYPES = 1000
DATACENTERS_SOURCE_URL = "https://github.com/runpod/runpodctl/blob/dd55bcff14ef1faadeb27c8f08edfeb8795e026f/internal/api/gpu.go"
DATACENTERS_QUERY = "query PublicDataCenters { dataCenters { id name location } }"
REGION_PRICES_QUERY = """query PublicGpuPodRegionPrices($secure: GpuLowestPriceInput!, $community: GpuLowestPriceInput!) {
  gpuTypes {
    id
    secure: lowestPrice(input: $secure) { uninterruptablePrice countryCode stockStatus minMemory minVcpu }
    community: lowestPrice(input: $community) { uninterruptablePrice countryCode stockStatus minMemory minVcpu }
  }
}"""
# Match the API's explicit country names, never infer a country from a DC code.
_LOCATION_COUNTRIES = {"India": "IN", "Japan": "JP", "Canada": "CA", "France": "FR",
                       "Australia": "AU", "United States": "US", "Germany": "DE",
                       "Netherlands": "NL", "Sweden": "SE", "Norway": "NO",
                       "Iceland": "IS", "Romania": "RO", "Czech Republic": "CZ",
                       "Czechia": "CZ", "Denmark": "DK", "Singapore": "SG",
                       "United Kingdom": "GB"}
_MAX_DATA_CENTERS = 64
_REGIONAL_BUDGET_SECONDS = 180


def _request(query: str, settings: Settings, variables: dict | None = None) -> dict:
    body = {"query": query}
    if variables is not None:
        body["variables"] = variables
    payload = request_json(API_URL, settings, method="POST", authenticated=False,
                           headers={"Content-Type": "application/json"},
                           data=json.dumps(body, separators=(",", ":")).encode("utf-8"))
    if payload.get("errors"):
        raise FetchError("public_api_error", "RunPod rejected the public pricing query.")
    return payload


def parse_data_centers(payload: dict) -> tuple[list[dict], list[dict]]:
    if isinstance(payload, dict) and payload.get("errors"):
        raise ValueError("RunPod data center query contains errors")
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("dataCenters") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not 0 < len(rows) <= _MAX_DATA_CENTERS:
        raise ValueError("RunPod data center catalog is invalid or exceeds the request limit")
    centers, exclusions, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("RunPod data center row is invalid")
        code, name, location = (_name(row.get(key)) for key in ("id", "name", "location"))
        if not re.fullmatch(r"[A-Z0-9-]{2,40}", code) or code in seen:
            raise ValueError("RunPod data center identity is invalid")
        seen.add(code)
        country = _LOCATION_COUNTRIES.get(location)
        if country is None:
            exclusions.append({"data_center_id": code, "location": location, "code": "country_not_explicit"})
        else:
            centers.append({"id": code, "name": name, "location": location, "country_code": country})
    return centers, exclusions


def parse_region_prices(payload: dict, *, center: dict, catalog: list[dict],
                        expected_ids: set[str], observed_at: str) -> tuple[list[dict], int]:
    if isinstance(payload, dict) and payload.get("errors"):
        raise ValueError("RunPod regional query contains errors")
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("gpuTypes") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise ValueError("RunPod regional GPU catalog is incomplete")
    base = {(q["raw_sku"], q["cloud_tier"]): q for q in catalog}
    quotes, missing, seen = [], 0, set()
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in expected_ids or row["id"] in seen:
            raise ValueError("RunPod regional GPU identity changed")
        seen.add(row["id"])
        for tier in ("secure", "community"):
            template = base.get((row["id"], tier))
            if template is None:
                continue
            if tier not in row:
                raise ValueError("RunPod regional cloud tier is missing")
            value = row.get(tier)
            if value is None:
                missing += 1
                continue
            if not isinstance(value, dict) or "uninterruptablePrice" not in value:
                raise ValueError("RunPod regional price structure changed")
            amount = _price(value["uninterruptablePrice"])
            if amount is None or amount == 0:
                missing += 1
                continue
            if value.get("countryCode") not in (None, center["country_code"]):
                raise ValueError("RunPod regional price country contradicts the data center")
            for key in ("minMemory", "minVcpu"):
                if value.get(key) is not None and (type(value[key]) is not int or value[key] <= 0):
                    raise ValueError("RunPod regional minimum resources are invalid")
            stock = value.get("stockStatus")
            if stock not in (None, "Low", "Medium", "High", "None"):
                raise ValueError("RunPod regional stock status changed")
            request = {"dataCenterId": center["id"], "gpuCount": 1, "secureCloud": tier == "secure"}
            quotes.append({**template, "gpu_count": 1, "amount": format(amount, "f"),
                           "quote_status": "starting_at", "price_basis": "starting_price",
                           "regions": [center["id"]], "zones": [center["id"]],
                           "geographic_scope": "requested_zone", "price_scope": "requested_zone_quote",
                           "region_price_verified": True, "compute_countries": [center["country_code"]],
                           "observed_at": observed_at,
                           "availability": "available" if stock in ("Low", "Medium", "High") else "unknown",
                           "conditions": {"cloud_type": f"{tier}_cloud", "rate_type": "lowest_available",
                                          "quote_request": request, "minimum_ram_gb": value.get("minMemory"),
                                          "minimum_vcpus": value.get("minVcpu"), "stock_status": stock},
                           "location_source": {"source_url": API_URL, "documentation_url": DATACENTERS_SOURCE_URL,
                                               "basis": "explicit_data_center_location_and_price_request",
                                               "data_center_id": center["id"], "location": center["location"],
                                               "country_code": center["country_code"]},
                           "notes": ["Lowest currently quoted one-GPU on-demand price for the requested data center and cloud tier; storage excluded.",
                                     "Minimum CPU/RAM are aggregate resource minima, not a complete selected machine specification.",
                                     "This is a starting price; no resource was created and checkout orderability was not tested."]})
    return quotes, missing


def _name(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or not value.isascii() or any(ord(char) < 32 for char in value)):
        raise ValueError("RunPod GPU catalog name is invalid")
    return " ".join(value.split())


def _gpu_fields(display_name: str, raw_sku: str) -> tuple[str, str | None]:
    name = re.sub(r"^(?:NVIDIA|AMD|Tesla)\s+", "", display_name, flags=re.IGNORECASE)
    # Display names can repeat the separate memory field (A100 SXM 40GB).
    name = re.sub(r"\s+\d+\s*GB$", "", name, flags=re.IGNORECASE)
    variants = _VARIANT.findall(name)
    if len(variants) > 1:
        raise ValueError("RunPod GPU variant is ambiguous")
    model = " ".join(_VARIANT.sub("", name).split()).upper()
    if not model or not re.fullmatch(r"[A-Z0-9][A-Z0-9 .-]*", model):
        raise ValueError("RunPod GPU model is invalid")
    variant = variants[0] if variants else None
    # The V100 PCIe display name omits the variant retained in its catalog id.
    if variant is None:
        raw_variants = _VARIANT.findall(raw_sku)
        if len(raw_variants) == 1:
            variant = raw_variants[0]
    if variant and variant.casefold() == "pcie":
        variant = "PCIe"
    elif variant:
        variant = variant.upper()
    return model, variant


def _price(value: object) -> Decimal | None:
    # JSON floats are decoded as Decimal by the shared transport. Strings and
    # binary floats are deliberately rejected, rather than silently rounded.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("RunPod GPU catalog price is not an exact JSON number")
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError("RunPod GPU catalog price is invalid")
    if amount and (amount.adjusted() > 12 or amount.as_tuple().exponent < -50):
        raise ValueError("RunPod GPU catalog price magnitude or precision is invalid")
    return amount


def _catalog_entries(payload: dict, *, observed_at: str) -> list[tuple[dict, Decimal | None]]:
    """Keep enabled full-GPU identity separate from optional catalog amounts.

    An absent catalog rate does not invalidate a separately requested regional
    rate. Metadata templates never contain a fabricated or fallback amount.
    """
    if not isinstance(payload, dict):
        raise ValueError("RunPod GPU catalog response is invalid")
    if payload.get("errors"):
        raise FetchError("public_api_error", "RunPod rejected the public GPU catalog query.")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("gpuTypes"), list):
        raise ValueError("RunPod GPU catalog response structure changed")
    rows = data["gpuTypes"]
    if not rows or len(rows) > _MAX_GPU_TYPES:
        raise ValueError("RunPod GPU catalog size is invalid")
    entries, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("RunPod GPU catalog row is invalid")
        raw_sku, raw_name = _name(row.get("id")), _name(row.get("displayName"))
        if raw_sku in seen:
            raise ValueError("RunPod GPU catalog contains duplicate identifiers")
        seen.add(raw_sku)
        if any(type(row.get(flag)) is not bool for _, flag, _ in _TIERS):
            raise ValueError("RunPod GPU cloud eligibility is invalid")
        # Unavailable/inactive sentinels can have memory=0 and placeholder prices.
        if not row["secureCloud"] and not row["communityCloud"]:
            continue
        if _PARTITION.search(raw_sku) or _PARTITION.search(raw_name):
            continue
        memory = row.get("memoryInGb")
        if type(memory) is not int or not 0 < memory <= 10000:
            raise ValueError("RunPod GPU catalog memory is invalid")
        model, variant = _gpu_fields(raw_name, raw_sku)
        for tier, flag, price_key in _TIERS:
            if not row[flag]:
                continue
            if price_key not in row:
                raise ValueError("RunPod GPU catalog price field is missing")
            amount = _price(row[price_key])
            entries.append(({
                "provider": "runpod",
                "product_type": "gpu_instance",
                "gpu_model": model,
                "raw_name": raw_name,
                "raw_sku": raw_sku,
                "gpu_variant": variant,
                "vram_gb": memory,
                "gpu_count": None,
                "currency": "USD",
                "unit": "gpu_hour",
                "billing_mode": "on_demand",
                "cloud_tier": tier,
                "conditions": {"cloud_type": f"{tier}_cloud", "rate_type": "catalog"},
                "regions": [],
                "zones": [],
                "geographic_scope": "unspecified",
                "account_scope": "public_catalog",
                "tax_scope": "unspecified",
                "observed_at": observed_at,
                "effective_from": None,
                "effective_until": None,
                "source_url": SOURCE_URL,
                "source_type": SOURCE_TYPE,
                "api_source_url": API_URL,
                "price_basis_source_url": PRICE_BASIS_URL,
                "availability": "unknown",
                "notes": [
                    "Public GPU Pods on-demand catalog rate in USD per GPU-hour for the named cloud tier; storage is charged separately.",
                    "The catalog does not identify an instance GPU count, CPU/RAM allocation, datacenter or availability zone for this rate.",
                    "Cloud eligibility is not current stock; availability, orderability and account-specific checkout totals were not verified.",
                    "Only enabled cloud tiers with positive public rates are returned; unquoted entries, inactive entries and MIG/vGPU partitions are excluded.",
                ],
            }, amount))
    if not entries:
        raise ValueError("RunPod GPU catalog contains no enabled full-GPU types")
    return entries


def _catalog_prices(entries: list[tuple[dict, Decimal | None]], *, allow_empty: bool = False) -> list[dict]:
    quotes = [{**metadata, "amount": format(amount, "f"), "price_basis": "advertised_per_gpu",
               "quote_status": "quoted"}
              for metadata, amount in entries if amount is not None and amount > 0]
    if not quotes and not allow_empty:
        raise ValueError("RunPod GPU catalog contains no priced full-GPU types")
    return quotes


def parse_catalog(payload: dict, *, observed_at: str) -> list[dict]:
    """Return only positive catalog rates, excluding inactive/MIG/vGPU entries."""
    return _catalog_prices(_catalog_entries(payload, observed_at=observed_at))


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Make one anonymous, read-only query; credentials are never consulted."""
    if settings.catalog_scope == "complete":
        result = collect_result(settings=settings, observed_at=observed_at)
        if result["errors"]:
            raise FetchError("incomplete_catalog", "RunPod regional collection was incomplete; use collect_result to inspect partial results.")
        return result["prices"]
    payload = request_json(
        API_URL, settings, method="POST", authenticated=False,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"query": GPU_TYPES_QUERY}, separators=(",", ":")).encode("utf-8"),
    )
    return parse_catalog(payload, observed_at=observed_at)


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Add bounded one-GPU regional starting prices in complete mode only."""
    bounded = replace(settings, timeout_seconds=min(settings.timeout_seconds, 20), max_retries=0)
    deadline = time.monotonic() + _REGIONAL_BUDGET_SECONDS
    if settings.catalog_scope == "complete":
        payload = _request(GPU_TYPES_QUERY, bounded)
        entries = _catalog_entries(payload, observed_at=observed_at)
        catalog = _catalog_prices(entries, allow_empty=True)
        regional_metadata = [metadata for metadata, _amount in entries]
    else:
        catalog = collect_quotes(settings=settings, observed_at=observed_at)
    prices, errors, exclusions = list(catalog), [], []
    coverage = {"scope": "enabled_full_gpu_pods_catalog", "catalog_quote_count": len(catalog),
                "regional_quote_count": 0, "regional_gpu_count": 1, "data_center_count": 0,
                "country_verified_data_center_count": 0, "queried_data_center_count": 0,
                "unquoted_region_tier_count": 0}
    if settings.catalog_scope == "complete":
        coverage["scope"] = "catalog_and_country_verified_data_centers_one_gpu_lowest_available"
        try:
            centers, exclusions = parse_data_centers(_request(DATACENTERS_QUERY, bounded))
            coverage["data_center_count"] = len(centers) + len(exclusions)
            coverage["country_verified_data_center_count"] = len(centers)
            expected_ids = {row["id"] for row in payload["data"]["gpuTypes"]}
            for center in centers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append({"code": "collection_budget_exceeded", "message": "RunPod regional collection reached its time limit.", "retryable": True})
                    break
                request = {"dataCenterId": center["id"], "gpuCount": 1}
                variables = {"secure": {**request, "secureCloud": True},
                             "community": {**request, "secureCloud": False}}
                try:
                    regional = _request(REGION_PRICES_QUERY, replace(bounded, timeout_seconds=min(remaining, 20)), variables)
                    rows, missing = parse_region_prices(regional, center=center, catalog=regional_metadata,
                                                        expected_ids=expected_ids, observed_at=observed_at)
                    prices.extend(rows)
                    coverage["queried_data_center_count"] += 1
                    coverage["unquoted_region_tier_count"] += missing
                except (FetchError, ValueError) as exc:
                    errors.append({"data_center_id": center["id"], "code": getattr(exc, "code", "parse_failed"),
                                   "message": "RunPod data center pricing could not be verified.",
                                   "retryable": getattr(exc, "retryable", False)})
                    if isinstance(exc, FetchError) and exc.code == "rate_limited":
                        break
        except (FetchError, ValueError) as exc:
            errors.append({"code": getattr(exc, "code", "parse_failed"),
                           "message": "RunPod data center discovery could not be verified.",
                           "retryable": getattr(exc, "retryable", False)})
    coverage["regional_quote_count"] = len(prices) - len(catalog)
    coverage["country_unverified_data_centers"] = exclusions
    return {"prices": prices, "status": "partial" if errors else "ok", "errors": errors,
            "coverage": coverage, "catalog_coverage": coverage,
            "pricing_limitations": ["Regional collection requests one GPU and reports lowest available starting prices, not all machine configurations.",
                                    "Data centers whose location only identifies a continent are excluded until country evidence is available.",
                                    "Cloud tiers are not membership discounts; Spot, prepaid plans, clusters and Serverless are outside this source."],
            "source_type": SOURCE_TYPE, "source_url": SOURCE_URL,
            "authentication_method": "anonymous"}
