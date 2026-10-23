"""Discover UHost configurations and request account-scoped hourly prices.

The comparison baseline is a compatible official Linux image with no image
fee and its minimum boot disk. No resources are created. GPU/CPU/RAM combinations are
enumerated, while arbitrary images, disk sizes, networking, spot and contracts
are outside this catalog. Every amount belongs to its exact requested zone.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from ..settings import Settings
from ..transport import FetchError
from . import ucloud
from .ucloud_console_catalog import build_catalog_targets
from .ucloud_console_image import select_image_and_disk
from .ucloud_console_session import UCloudAPIError, UCloudConsoleSession, PRICING_PAGE

SOURCE_URL = "https://api.ucloud.cn?Action=GetUHostInstancePrice"
SOURCE_TYPE = "official_internal_api"
MAX_TARGETS = 5000
MAX_WORKERS = 8


def _scope(target):
    return {key: target.request[key] for key in
            ("Region", "Zone", "GpuType", "GPU", "CPU", "Memory", "CpuPlatform", "NetCapability")}


def _wire(parameters):
    result = {}
    for key, value in parameters.items():
        if key == "Disks":
            for index, disk in enumerate(value):
                for name, field in disk.items():
                    result[f"Disks.{index}.{name}"] = str(field).lower() if type(field) is bool else field
        else:
            result[key] = str(value).lower() if type(value) is bool else value
    return result


def _availability_request(target):
    return {key: target.request[key] for key in ("MachineType", "GpuType", "GPU", "CPU", "Memory", "ChargeType")} | {
        "MinimalCpuPlatform": target.request["CpuPlatform"] + "/Auto",
    }


def _identity(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def availability_status(payload, target):
    rows = payload.get("AvailableZones") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Unrecognized UCloud availability directory.")
    matches = [row for row in rows if row.get("Region") == target.request["Region"]
               and row.get("Zone") == target.request["Zone"]]
    if len(matches) != 1 or matches[0].get("Status") not in {"Available", "Soldout"}:
        raise ValueError("The exact UCloud configuration has no verified available/soldout zone.")
    return "available" if matches[0]["Status"] == "Available" else "sold_out"


def parse_console_quote(payload, target, selected, *, availability, observed_at):
    request = deepcopy(target.request) | deepcopy(selected.request)
    quote = ucloud.parse_quote(payload, request, observed_at=observed_at)
    raw = payload["PriceSet"][0]
    # Zero/unknown compute prices are not a free GPU offer. Preserve known
    # components and reject unexpected charge types or inconsistent totals.
    details = raw.get("PriceDetail")
    if not isinstance(details, dict) or ucloud._amount(details.get("UHost")) <= 0:
        raise ValueError("No positive UHost compute price was returned.")
    known = {"UHost", "UDisk", "Snapshot", "Volume", "UMkt", "UImage"}
    if any(ucloud._amount(details.get(key, 0)) != 0 for key in ("Snapshot", "Volume", "UMkt", "UImage")):
        raise ValueError("Unexpected paid image or extra service in the baseline quote.")
    if any(ucloud._amount(value) != 0 for key, value in details.items() if key not in known):
        raise ValueError("Unknown nonzero UCloud price component.")
    total = sum((ucloud._amount(value) for value in details.values()), Decimal(0))
    if total != ucloud._amount(raw["Price"]):
        raise ValueError("UCloud price components do not sum to the instance total.")
    quote["instance_price"]["details"] = {key: format(ucloud._amount(value), "f") for key, value in details.items() if key in known}
    if ucloud._amount(raw["Price"]) <= 0:
        raise ValueError("No positive UCloud price was returned.")
    quote.update({
        "gpu_model": target.gpu_model, "vram_gb": target.gpu_memory_gb,
        "raw_name": "UHost " + target.request["GpuType"],
        "raw_sku": None,
        "configuration_id": hashlib.sha256(_identity(request).encode()).hexdigest()[:20],
        "compute_countries": [target.country_code], "location": target.location,
        "location_source": {"regions_url": "https://api.ucloud.cn?Action=ListRegions",
                            "zones_url": "https://api.ucloud.cn?Action=ListZones",
                            "basis": "official_directory_exact_requested_region_zone"},
        "source_url": SOURCE_URL, "pricing_page_url": PRICING_PAGE,
        "source_type": SOURCE_TYPE, "availability": availability,
        "availability_scope": "gpu_cpu_memory_vendor_zone" if availability != "unknown" else "unknown",
        "pricing_tier": "account", "membership_required": None,
        "catalog_status": target.catalog_status,
        "cpu_platform_options": target.cpu_platform_options,
        "network_selection": {
            "mode": target.metadata["network_mode"],
            "catalog_options": deepcopy(target.metadata["network_mode_options"]),
            "required_image_features": list(target.metadata["network_mode_required_image_features"]),
            "selection_basis": target.metadata["network_mode_selection_basis"],
        },
        "image_selection": deepcopy(selected.metadata) | {"image_license_price_verified": True},
        "price_scope": "requested_zone_quote", "region_price_verified": True,
        "notes": [
            "Account-scoped UHost Dynamic hourly quote for the exact catalog GPU/CPU/RAM/vendor/network/region/zone configuration.",
            "Per-GPU price is the configured instance total divided by its GPU count; CPU, RAM and the requested boot disk are included.",
            "Baseline uses a compatible official Linux image with no image charge and a minimum boot disk; it excludes extra data disks, EIP/bandwidth, paid images and snapshots.",
            "Country and zone are joined through the official directories; each zone is separately quoted, never copied from another region.",
            ("Availability was checked for this GPU/CPU/RAM/vendor/zone combination; network/image orderability and quota were not checked. Sold out does not mean discontinued." if availability != "unknown" else
             "Current stock was not verified; the official catalog validates this configuration, not immediate orderability."),
            "Catalog coverage excludes spot, monthly/yearly packages, custom storage/images and unpublished contracts.",
        ],
    })
    quote["resources"]["cpu_platform"] = request["CpuPlatform"]
    quote["resources"]["net_capability"] = request["NetCapability"]
    quote["resources"]["ram_gb"] = target.memory_gb
    return quote


def collect_result(*, settings: Settings, observed_at: str, regions=None, zones=None, gpu_models=None):
    session = UCloudConsoleSession.from_settings(settings)
    if settings.ucloud_project_id is not None and not ucloud._label(settings.ucloud_project_id):
        raise FetchError("invalid_project", "UCLOUD_PROJECT_ID must be a valid project identifier.")
    def read(action, params=None):
        params = dict(params or {})
        if settings.ucloud_project_id and action not in {"ListRegions", "ListZones"}:
            params["ProjectId"] = settings.ucloud_project_id
        return session.request(action, params, settings=settings)
    region_data = read("ListRegions")
    zone_data = read("ListZones")
    instance_data = read("DescribeAvailableInstanceTypes", {"InstanceType": "all"})
    catalog = build_catalog_targets(region_data, zone_data, instance_data)
    targets = [target for target in catalog.targets
               if (not regions or target.request["Region"] in regions)
               and (not zones or target.request["Zone"] in zones)
               and (not gpu_models or target.gpu_model.casefold() in {model.casefold() for model in gpu_models})]
    if len(targets) > MAX_TARGETS:
        raise FetchError("catalog_limit", "UHost configuration catalog exceeded the bounded collection limit.")
    gaps = deepcopy(catalog.gaps)
    prices, errors = [], []
    def safe_read(job):
        action, params = job
        try:
            payload = read(action, params)
            # Capture receipt in the worker. Ordered map iteration can wait
            # behind a slower earlier request after this response has arrived.
            completed_at = datetime.now(timezone.utc).isoformat()
            return payload, None, completed_at
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            code = exc.code if isinstance(exc, FetchError) else "parse_failed"
            error = {"code": code, "message": "UCloud catalog/quote request did not produce verified data.",
                     "retryable": getattr(exc, "retryable", False)}
            if isinstance(exc, UCloudAPIError):
                error["diagnostics"] = exc.diagnostics
            return None, error, None
    region_names = sorted({target.request["Region"] for target in targets})
    configs = {_identity(_availability_request(target)): _availability_request(target) for target in targets}
    # Bounded concurrency; each worker has an independent urllib request. The
    # session is immutable, and identical configuration availability is reused.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        image_results = dict(zip(region_names, pool.map(safe_read, [("DescribeImage", {"Region": region, "Limit": 9999}) for region in region_names])))
        availability_results = (dict(zip(configs, pool.map(safe_read, [("DescribeUHostMachineTypeAvailableZones", config) for config in configs.values()])))
                                if settings.ucloud_check_availability else {})
        prepared = []
        market_images = {}
        for target in targets:
            image_payload, image_error, _ = image_results[target.request["Region"]]
            if image_error:
                gaps.append({**_scope(target), "status": image_error["code"], "retryable": bool(image_error.get("retryable")),
                             **image_error.get("diagnostics", {})})
                continue
            availability = "unknown"
            if settings.ucloud_check_availability:
                available_payload, available_error, _ = availability_results[_identity(_availability_request(target))]
                try:
                    if available_error:
                        raise ValueError("Stock query failed.")
                    availability = availability_status(available_payload, target)
                except (ValueError, KeyError, TypeError):
                    gaps.append({**_scope(target), "status": "availability_not_verified",
                                 "retryable": bool(available_error and available_error.get("retryable")),
                                 "reason": "Stock could not be verified; a valid catalog configuration may still be quoted.",
                                 **((available_error or {}).get("diagnostics", {}))})
            configuration_error = None
            try:
                try:
                    selected = select_image_and_disk(target, image_payload)
                except ValueError:
                    region = target.request["Region"]
                    if region not in market_images:
                        market_images[region] = safe_read(("DescribeImage", {"Region": region, "ImageType": "Business", "FuncType": "gpu", "Limit": 9999}))
                    market_payload, market_error, _ = market_images[region]
                    if market_error:
                        configuration_error = market_error
                        raise ValueError("GPU image directory failed.")
                    selected = select_image_and_disk(target, market_payload, gpu_market=True)
                prepared.append((target, selected, availability))
            except (ValueError, KeyError, TypeError):
                gaps.append({**_scope(target), "status": "configuration_not_verified",
                             "retryable": bool(configuration_error and configuration_error.get("retryable")),
                             "reason": "Compatible image/disk could not be verified.",
                             **((configuration_error or {}).get("diagnostics", {}))})
        jobs = [("GetUHostInstancePrice", _wire(target.request | selected.request)) for target, selected, _ in prepared]
        for (target, selected, availability), (payload, error, completed_at) in zip(prepared, pool.map(safe_read, jobs)):
            if error:
                gaps.append({**_scope(target), "status": error["code"], "retryable": bool(error.get("retryable")),
                             **error.get("diagnostics", {})})
                continue
            try:
                quote = parse_console_quote(payload, target, selected, availability=availability,
                                            observed_at=completed_at)
                quote["account_project_scope"] = "configured_project" if settings.ucloud_project_id else "api_default_project"
                prices.append(quote)
            except (ValueError, KeyError, TypeError):
                gaps.append({**_scope(target), "status": "invalid_hourly_price"})
    if gaps:
        errors.append({"source_url": SOURCE_URL, "code": "incomplete_catalog",
                       "message": "Some UHost catalog entries could not be verified or priced; inspect gaps.",
                       "retryable": any(gap.get("retryable", False) for gap in gaps)})
    return {
        "status": ("partial" if prices else "failed") if gaps else "ok",
        "prices": prices, "errors": errors, "gaps": gaps,
        "authentication_method": "local_console_session",
        "coverage": {**catalog.counts, "scope": "account_visible_uhost_on_demand_configurations_with_baseline_boot_disk",
                     "availability_check_requested": settings.ucloud_check_availability,
                     "account_project_scope": "configured_project" if settings.ucloud_project_id else "api_default_project",
                     "selected_targets": len(targets), "prepared_price_requests": len(prepared),
                     "priced_targets": len(prices), "quote_gap_count": len(targets) - len(prices),
                     "filters": {"regions": list(regions or []), "zones": list(zones or []), "gpu_models": list(gpu_models or [])},
                     "countries": sorted({country for q in prices for country in q["compute_countries"]}),
                     "regions": sorted({region for q in prices for region in q["regions"]}),
                     "gpu_models": sorted({q["gpu_model"] for q in prices})},
        "pricing_limitations": ["Account-scoped CNY prices; not a promise of universal public tariffs.",
                                "One official Linux/minimum boot-disk baseline with no image fee per catalog configuration, not all custom images/disks.",
                                "Spot, monthly/yearly, EIP, bandwidth and unpublished contract prices are outside this scope."],
    }
