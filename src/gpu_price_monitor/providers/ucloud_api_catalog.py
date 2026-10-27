"""Rediscover and price UHost GPU configurations with official signed APIs.

No browser, Cookie, saved login session, cloud resource creation or cached
configuration catalog is used. Country labels come from the anonymous official
directory, joined only to exact region/zone pairs returned by GetRegion.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
import re
import threading
from urllib.parse import urlencode

from ..settings import Settings
from ..transport import FetchError, request_json
from . import ucloud, ucloud_console, ucloud_public
from .ucloud_console_session import UCloudAPIError

SOURCE_URL = "https://api.ucloud.cn/"
API_URL = SOURCE_URL
SOURCE_TYPE = "official_quote_api"
REGIONS_DOCUMENTATION_URL = "https://docs.ucloud.cn/api/uaccount-api/get_region"
CATALOG_DOCUMENTATION_URL = "https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types"
IMAGE_DOCUMENTATION_URL = "https://docs.ucloud.cn/api/uhost-api/describe_image"
AUTHENTICATION_METHOD = "ucloud_public_private_key_signature"
MAX_REGIONS = 100
MAX_IMAGES = 10_000
IMAGE_PAGE_SIZE = 100
_ACTIONS = frozenset({"GetRegion", "DescribeAvailableInstanceTypes", "DescribeImage", "GetUHostInstancePrice"})
_PARAMETER = re.compile(r"[A-Za-z][A-Za-z0-9_.]*\Z")


class SignedAPIError(UCloudAPIError):
    """Keep only public protocol diagnostics, never a provider Message."""
    def __init__(self, action: str, retcode: int):
        if action not in _ACTIONS or type(retcode) is not int or not -(2 ** 31) <= retcode < 2 ** 31 or retcode == 0:
            raise ValueError("Invalid UCloud signed API diagnostics.")
        code = ("authentication_error" if retcode in {170, 171, 172, 174} else
                "permission_denied" if retcode in {291, 293, 294, 295, 299} else
                "rate_limited" if retcode == 153 else "provider_rejected")
        FetchError.__init__(self, code, "UCloud rejected the signed read-only API request; verify the API key, project and action permissions.",
                            retryable=retcode in {110, 130, 150, 153})
        self.provider_action, self.provider_retcode = action, retcode


@dataclass(repr=False)
class SignedCatalogReader:
    settings: Settings = field(repr=False)
    gaps: list[dict] = field(default_factory=list)
    request_counts: Counter = field(default_factory=Counter)
    region_attempts: list[str] = field(default_factory=list)
    region_successes: list[str] = field(default_factory=list)
    _regions: dict | None = None
    _zones: dict | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        for value in (self.settings.ucloud_public_key, self.settings.ucloud_private_key):
            if (not isinstance(value, str) or not value or value != value.strip() or len(value) > 16384
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise FetchError("missing_credentials", "Configure UCLOUD_PUBLIC_KEY and UCLOUD_PRIVATE_KEY for signed catalog collection; no browser session is needed.")
        if self.settings.ucloud_project_id is not None and not ucloud._label(self.settings.ucloud_project_id):
            raise FetchError("invalid_project", "UCLOUD_PROJECT_ID must identify the authorized quotation project.")

    def _signed(self, action: str, params: dict, settings: Settings) -> dict:
        if action not in _ACTIONS or not isinstance(params, dict) or len(params) > 256:
            raise FetchError("unsupported_action", "Only documented UCloud catalog, image and price reads are allowed.")
        if any(not isinstance(key, str) or not _PARAMETER.fullmatch(key) or key in {"Action", "PublicKey", "Signature"}
               or type(value) not in {str, int, bool} for key, value in params.items()):
            raise FetchError("invalid_api_parameters", "Invalid UCloud read-only API parameters.")
        parameters = dict(params, Action=action, PublicKey=self.settings.ucloud_public_key)
        parameters["Signature"] = ucloud.sign_parameters(parameters, self.settings.ucloud_private_key)
        body = urlencode({key: ucloud._wire_value(value) for key, value in parameters.items()}).encode("ascii")
        with self._lock:
            self.request_counts[action] += 1
        payload = request_json(API_URL, settings, method="POST", authenticated=True,
                               headers={"Content-Type": "application/x-www-form-urlencoded"}, data=body)
        if not isinstance(payload, dict) or type(payload.get("RetCode")) is not int:
            raise FetchError("invalid_api_response", "The signed UCloud API response structure changed.")
        if payload["RetCode"] != 0:
            raise SignedAPIError(action, payload["RetCode"])
        if payload.get("Action") != action + "Response":
            raise FetchError("invalid_api_response", "The signed UCloud API response structure changed.")
        return payload

    def _geography(self, settings: Settings):
        if self._regions is not None:
            return
        payload = self._signed("GetRegion", {}, settings)
        rows = payload.get("Regions")
        if not isinstance(rows, list) or not rows or len(rows) > 1000:
            raise FetchError("invalid_region_directory", "GetRegion did not return a bounded account region/zone directory.")
        directory = ucloud_public.load_location_catalog(settings=settings)
        regions, zones = {}, {}
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not ucloud._label(row.get("Region")) or not ucloud._label(row.get("Zone")):
                raise FetchError("invalid_region_directory", "GetRegion returned an invalid region/zone pair.")
            region, zone = row["Region"], row["Zone"]
            if (region, zone) in seen:
                raise FetchError("invalid_region_directory", "GetRegion returned duplicate region/zone pairs.")
            seen.add((region, zone))
            if zone in zones and zones[zone]["Region"] != region:
                raise FetchError("invalid_region_directory", "GetRegion returned a zone bound to conflicting regions.")
            location = directory.get(zone)
            if not isinstance(location, dict) or location.get("region") != region:
                self.gaps.append({"scope": "region_country_binding", "region": region, "zone": zone,
                                  "status": "country_not_verified", "retryable": False})
                regions.setdefault(region, {"Region": region, "CountryCode": None, "LocalName": None})
                zones[zone] = {"Region": region, "Zone": zone, "LocalName": None, "CountryCodeVerified": False}
                continue
            verified = ucloud_public.resolve_location(directory, region=region, zone=zone)
            regions[region] = {"Region": region, "CountryCode": verified["country_code"], "LocalName": verified["region_name"]}
            zones[zone] = {"Region": region, "Zone": zone, "LocalName": verified["zone_name"]}
        if not regions or len(regions) > MAX_REGIONS:
            raise FetchError("invalid_region_directory", "No bounded account region/zone directory was returned.")
        self._regions = {"RetCode": 0, "Regions": list(regions.values())}
        self._zones = {"RetCode": 0, "Zones": list(zones.values())}

    def _instances(self, params: dict, settings: Settings) -> dict:
        self._geography(settings)
        regions = sorted(row["Region"] for row in self._regions["Regions"])
        zone_regions = {row["Zone"]: row["Region"] for row in self._zones["Zones"]}
        self.region_attempts = regions
        def read_region(region):
            try:
                request = {"Region": region}
                if self.settings.ucloud_project_id:
                    request["ProjectId"] = self.settings.ucloud_project_id
                payload = self._signed("DescribeAvailableInstanceTypes", request, settings)
                rows = payload.get("AvailableInstanceTypes")
                if not isinstance(rows, list) or len(rows) > 100_000 or any(not isinstance(row, dict) for row in rows):
                    raise FetchError("invalid_catalog_response", "Invalid UCloud configuration directory.")
                if any(row.get("ParentType") == "G" and row.get("Zone") in zone_regions
                       and zone_regions[row["Zone"]] != region for row in rows):
                    raise FetchError("region_catalog_mismatch", "A returned GPU configuration belongs to a different request region.")
                return region, rows, None
            except (FetchError, ValueError, TypeError, KeyError) as exc:
                gap = {"scope": "regional_configuration_catalog", "region": region,
                       "status": getattr(exc, "code", "parse_failed"), "retryable": bool(getattr(exc, "retryable", False))}
                if isinstance(exc, SignedAPIError):
                    gap.update(exc.diagnostics)
                return region, [], gap
        all_rows = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            for region, rows, gap in pool.map(read_region, regions):
                if gap:
                    self.gaps.append(gap)
                else:
                    self.region_successes.append(region)
                    all_rows.extend(rows)
        return {"RetCode": 0, "AvailableInstanceTypes": all_rows}

    def _images(self, params: dict, settings: Settings) -> dict:
        request = {key: value for key, value in params.items() if key not in {"Limit", "Offset"}}
        request.setdefault("ImageType", "Base")
        request.setdefault("OsType", "Linux")
        request["PriceSet"] = 1
        rows, seen, total = [], set(), None
        while True:
            payload = self._signed("DescribeImage", {**request, "Limit": IMAGE_PAGE_SIZE, "Offset": len(rows)}, settings)
            page, page_total = payload.get("ImageSet"), payload.get("TotalCount")
            if (not isinstance(page, list) or len(page) > IMAGE_PAGE_SIZE
                    or type(page_total) is not int or not 0 <= page_total <= MAX_IMAGES
                    or (total is not None and page_total != total)):
                raise FetchError("invalid_image_pagination", "UCloud image pagination changed; no incomplete image catalog is substituted.")
            total = page_total
            for row in page:
                identity = row.get("ImageId") if isinstance(row, dict) else None
                if not ucloud._label(identity) or identity in seen:
                    raise FetchError("invalid_image_pagination", "UCloud image pages contain invalid or duplicate identities.")
                seen.add(identity)
                rows.append(row)
            if len(rows) == total:
                return {"RetCode": 0, "TotalCount": total, "ImageSet": rows}
            if not page or len(rows) > total:
                raise FetchError("incomplete_image_catalog", "UCloud image pagination ended before the declared total.")

    def request(self, action: str, params=None, *, settings: Settings):
        params = dict(params or {})
        if action in {"ListRegions", "ListZones"}:
            self._geography(settings)
            return deepcopy(self._regions if action == "ListRegions" else self._zones)
        if action == "DescribeAvailableInstanceTypes":
            return self._instances(params, settings)
        if action == "DescribeImage":
            return self._images(params, settings)
        return self._signed(action, params, settings)


def collect_result(*, settings: Settings, observed_at: str, regions=None, zones=None, gpu_models=None) -> dict:
    reader = SignedCatalogReader(settings)
    result = ucloud_console.collect_catalog(reader, settings=settings, observed_at=observed_at,
                                           regions=regions, zones=zones, gpu_models=gpu_models)
    result["source_url"], result["source_type"] = SOURCE_URL, SOURCE_TYPE
    result["authentication_method"] = AUTHENTICATION_METHOD
    result["coverage"].update(scope="account_readable_signed_api_uhost_on_demand_configurations_with_baseline_boot_disk",
                              discovery_regions_attempted=reader.region_attempts,
                              discovery_regions_succeeded=reader.region_successes,
                              signed_request_counts=dict(reader.request_counts),
                              configuration_catalog_refreshed_at=observed_at, uses_cached_catalog=False)
    result["coverage"]["account_scope_exclusions"] = result["coverage"].pop("console_scope_exclusions")
    result["gaps"].extend(reader.gaps)
    if reader.gaps:
        result["status"] = "partial" if result["prices"] else "failed"
        result["errors"].append({"source_url": SOURCE_URL, "code": "incomplete_catalog",
                                 "message": "Some account regions could not be discovered or geographically verified.",
                                 "retryable": any(gap.get("retryable", False) for gap in reader.gaps)})
    for quote in result["prices"]:
        quote["source_url"], quote["source_type"], quote["api_source_url"] = ucloud.DOCUMENTATION_URL, SOURCE_TYPE, API_URL
        quote["location_source"] = {"regions_url": REGIONS_DOCUMENTATION_URL,
                                    **({"country_mapping": ucloud_public.location_source(price_location_basis="signed_GetRegion_exact_pair")}
                                       if quote["compute_countries"] else {"country_status": "not_verified"}),
                                    "basis": "signed_account_directory_exact_requested_region_zone"}
        quote["catalog_discovery"] = {"source_url": CATALOG_DOCUMENTATION_URL, "authentication_method": AUTHENTICATION_METHOD,
                                      "refreshed_at": observed_at, "uses_cached_catalog": False}
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    outcome = collect_result(settings=settings, observed_at=observed_at)
    if outcome["status"] != "ok":
        raise FetchError("incomplete_catalog", "Inspect UCloud signed catalog diagnostics for unpriced configurations or unreadable regions.")
    return outcome["prices"]
