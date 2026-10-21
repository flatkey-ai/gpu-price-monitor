"""Anonymous UCloud GPU promotion catalog, with native monthly price units.

The official GPU product page publicly loads these read-only website APIs.
Its observed monthly activities cover the general GPU sale (10204), RTX 4090
(10216), and RTX 4090 48G / RTX 5090 (10248). The page's public product-gpu.js
requests those exact activity IDs; other account-specific campaigns are excluded.
These packages are not standard on-demand/account quotes, and listing a price
does not mean it can be purchased. No API keys, cookies or credentials are used.
"""

from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import json
import re
from urllib.parse import urlencode

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://www.ucloud.cn/site/product/gpu.html"
API_URL = "https://api.ucloud.cn/"
ACTIVITY_IDS = ("10204", "10216", "10248")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_WHOLE_GPUS = {"K80", "P40", "V100", "V100S", "T4", "T4A", "T4S", "2080", "2080Ti",
               "2080TiS", "2080TiPro", "1080Ti", "MI100", "3080Ti", "3090", "4090",
               "4090Pro", "4090_48G", "A100", "A800", "H20", "5090"}


def _invalid() -> ValueError:
    return ValueError("The UCloud public GPU promotion catalog has an unsupported structure.")


def _label(value) -> str:
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        raise _invalid()
    return value


def _text(value) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise _invalid()
    return value


def _integer(value, *, zero=False) -> int:
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) < 10:
        value = int(value)
    if type(value) is not int or not (0 if zero else 1) <= value <= 10_000_000:
        raise _invalid()
    return value


def _cents(value) -> Decimal:
    if type(value) not in (int, Decimal):
        raise _invalid()
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0 or amount >= Decimal("1e15") or amount != amount.to_integral_value():
        raise _invalid()
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        return amount / Decimal(100)


def _rows(payload, action: str, key="Data") -> list[dict]:
    if not isinstance(payload, dict) or type(payload.get("RetCode")) is not int:
        raise _invalid()
    if payload["RetCode"] != 0:
        raise FetchError("public_api_error", "UCloud's public catalog request failed; no account credentials were used.")
    rows = payload.get(key)
    if payload.get("Action") != action + "Response" or not isinstance(rows, list) or len(rows) > 5000:
        raise _invalid()
    if any(not isinstance(row, dict) for row in rows):
        raise _invalid()
    if "TotalCount" in payload and (type(payload["TotalCount"]) is not int or payload["TotalCount"] != len(rows)):
        raise _invalid()
    return rows


def _decode_details(raw) -> dict:
    if not isinstance(raw, str) or len(raw) > 8192:
        raise _invalid()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _invalid()
            result[key] = value
        return result
    try:
        details = json.loads(raw, object_pairs_hook=unique)
    except RecursionError:
        raise _invalid() from None
    if not isinstance(details, dict) or details.get("MachineType") != "G":
        raise _invalid()
    gpu = details.get("gpu_type")
    if not isinstance(gpu, str) or gpu not in _WHOLE_GPUS:
        raise _invalid()
    for name in ("Cpu", "Mem", "Gpu", "Disk", "Bandwidth"):
        _integer(details.get(name))
    if _integer(details["Mem"]) % 1024:
        raise _invalid()
    for name in ("DiskType", "CpuPlatform"):
        _label(details.get(name))
    if details.get("UHostFamily", ""):
        _label(details["UHostFamily"])
    if details.get("NetEnhancedV2", "") not in ("", "0", "1", "2", "3", 0, 1, 2, 3):
        raise _invalid()
    return details


def parse_location_catalog(regions_payload: dict, zones_payload: dict) -> dict[str, dict]:
    """Bind zones to countries using the provider's explicit region directory.

    CountryCode is retained exactly as published, including the provider's
    classification of territories. Region prefixes and translated names are
    never used to infer a country. Only the location whitelist is returned.
    """
    regions = {}
    for row in _rows(regions_payload, "ListAllRegions", "Regions"):
        name, country = _label(row.get("Region")), row.get("CountryCode")
        if name in regions or not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country):
            raise _invalid()
        regions[name] = {"country_code": country, "region_name": _text(row.get("LocalName"))}
    zones = {}
    for row in _rows(zones_payload, "ListAllZones", "Zones"):
        zone, region = _label(row.get("Zone")), _label(row.get("Region"))
        if zone in zones or region not in regions:
            raise _invalid()
        zones[zone] = {"region": region, "zone_name": _text(row.get("LocalName")), **regions[region]}
    if not zones or not regions:
        raise _invalid()
    return zones


def resolve_location(location_catalog: dict, *, region: str, zone: str) -> dict:
    """Resolve one exact region/zone pair; never borrow another zone's country."""
    if not isinstance(location_catalog, dict):
        raise _invalid()
    location = location_catalog.get(zone)
    if not isinstance(location, dict) or location.get("region") != region:
        raise FetchError(
            "unverifiable_geography",
            "The requested UCloud region/zone pair could not be verified in the official location directory.",
        )
    country = location.get("country_code")
    if not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country):
        raise _invalid()
    return {"region": _label(region), "zone": _label(zone), "country_code": country,
            "region_name": _text(location.get("region_name")),
            "zone_name": _text(location.get("zone_name"))}


def location_source(*, price_location_basis: str) -> dict:
    """Describe the public mapping separately from a price's request context."""
    return {"api_url": API_URL, "source_type": "official_public_api",
            "region_action": "ListAllRegions", "zone_action": "ListAllZones",
            "country_field": "CountryCode", "price_location_basis": price_location_basis}


def _offline_zones(payload) -> set[str]:
    result = set()
    for row in _rows(payload, "GetActivityFlags"):
        if row.get("FlagType") != "Zone" or row.get("Value") != "offline":
            # Do not pretend a new flag format proves that a package is available.
            raise _invalid()
        flags = row.get("FlagList")
        if not isinstance(flags, list) or len(flags) != 1 or not isinstance(flags[0], dict):
            raise _invalid()
        if flags[0].get("FlagKey") != "Zone":
            raise _invalid()
        result.add(_label(flags[0].get("FlagVal")))
    return result


def parse_catalog(*, activities, regions, zones, packages: dict, flags: dict, observed_at: str) -> list[dict]:
    """Parse complete source responses. Unknown structures fail closed."""
    location_map = parse_location_catalog(regions, zones)
    metadata = {}
    for row in _rows(activities, "ListActivity"):
        if row.get("ActivityId") in ACTIVITY_IDS:
            activity_id = row["ActivityId"]
            if activity_id in metadata:
                raise _invalid()
            metadata[activity_id] = row
    if set(metadata) != set(ACTIVITY_IDS) or set(packages) != set(ACTIVITY_IDS) or set(flags) != set(ACTIVITY_IDS):
        raise _invalid()
    now = datetime.fromisoformat(observed_at)
    if now.tzinfo is None:
        raise _invalid()
    result = []
    for activity_id in ACTIVITY_IDS:
        activity = metadata[activity_id]
        if type(activity.get("OnlyNewUser")) is not bool or type(activity.get("Quota")) is not int or activity["Quota"] < 0:
            raise _invalid()
        if any(type(activity.get(key)) is not int or not 0 <= activity[key] <= 253402300799
               for key in ("BeginTime", "EndTime")):
            raise _invalid()
        begin, end = (datetime.fromtimestamp(activity[key], timezone.utc) for key in ("BeginTime", "EndTime"))
        if begin >= end:
            raise _invalid()
        state = _text(activity.get("State"))
        status = "ended" if now >= end else "upcoming" if now < begin else "published" if state == "published" else "offline"
        offline = _offline_zones(flags[activity_id])
        seen = set()
        package_rows = _rows(packages[activity_id], "ListPackage")
        if not package_rows:
            raise _invalid()
        for package in package_rows:
            if package.get("ActivityId") != activity_id or package.get("PackageType") != "uhost":
                raise _invalid()
            if package.get("DurationUnit") != "month" or package.get("Durations") != [1] or type(package["Durations"][0]) is not int:
                raise _invalid()
            package_id = _label(package.get("PackageId"))
            if package_id in seen:
                raise _invalid()
            seen.add(package_id)
            details = _decode_details(package.get("PackageDetails"))
            quantity = _integer(details["Gpu"])
            price, original = _cents(package.get("CurPrice")), _cents(package.get("OriginalPrice"))
            with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
                allocated = (price / quantity).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            amount = format(allocated, "f").rstrip("0").rstrip(".") or "0"
            package_zones = package.get("Zones")
            if (not isinstance(package_zones, list) or not package_zones
                    or any(not isinstance(zone, str) for zone in package_zones)
                    or len(set(package_zones)) != len(package_zones)):
                raise _invalid()
            renew = package.get("DiscountAllowRenew")
            if type(renew) is not int or renew not in (0, 1):
                raise _invalid()
            for zone in package_zones:
                if zone not in location_map:
                    raise _invalid()
                location = location_map[zone]
                availability = status if status in {"ended", "upcoming", "offline"} else "offline" if zone in offline else "unknown"
                result.append({
                    "provider": "ucloud", "product_type": "gpu_instance",
                    "gpu_model": details["gpu_type"].upper(), "gpu_variant": details["gpu_type"],
                    "raw_name": f"UHost G {details['gpu_type']}", "raw_sku": package_id,
                    "vram_gb": None, "gpu_count": quantity, "amount": amount,
                    "currency": "CNY", "unit": "gpu_month", "billing_mode": "monthly",
                    "price_basis": "instance_total_allocated", "quote_status": "quoted",
                    "regions": [location["region"]], "zones": [zone],
                    "compute_countries": [location["country_code"]],
                    "location": dict(location, zone=zone), "geographic_scope": "zone",
                    "location_source": location_source(price_location_basis="package_zones"),
                    "account_scope": "public_promotion", "tax_scope": "unspecified",
                    "observed_at": observed_at, "effective_from": None, "effective_until": None,
                    "source_url": SOURCE_URL, "source_type": "official_public_api",
                    "availability": availability,
                    "instance_price": {"amount": format(price, "f"), "original_amount": format(original, "f"), "currency": "CNY", "unit": "instance_month"},
                    "normalization": {"formula": "CurPrice / 100 / gpu_count", "decimal_places": 12, "rounding": "ROUND_HALF_UP"},
                    "resources": {"vcpu_count": _integer(details["Cpu"]), "memory_mb": _integer(details["Mem"]),
                                  "disk_gb": _integer(details["Disk"]), "disk_type": details["DiskType"],
                                  "bandwidth_mbps": _integer(details["Bandwidth"]), "cpu_platform": details["CpuPlatform"],
                                  "machine_type": "G", "uhost_family": details.get("UHostFamily", ""),
                                  "network_enhancement": details.get("NetEnhancedV2", "")},
                    "promotion": {"activity_id": activity_id, "title": _text(activity.get("Title")),
                                  "only_new_users": activity["OnlyNewUser"], "purchase_limit": activity["Quota"],
                                  "user_types": _text(activity.get("UserType")), "activity_state": state,
                                  "activity_status": status, "duration": 1, "duration_unit": "month",
                                  "activity_begin_at": begin.isoformat(), "activity_end_at": end.isoformat(),
                                  "discount_allow_renew": bool(renew), "eligibility_verified": False},
                    "notes": [
                        "Published promotional package price, not a standard on-demand or account-specific quote.",
                        "Current and original prices are published in cents per instance-month; the per-GPU amount allocates the entire CPU/RAM/disk/bandwidth package.",
                        "No hourly equivalent was calculated; a one-month commitment applies.",
                        "Activity dates describe the promotion window, not a guarantee that this price remains fixed throughout that window.",
                        "Published activity metadata and website eligibility text may differ; purchase eligibility must be checked with UCloud and was not verified.",
                        "An offline flag marks this zone's activity as unavailable; absence of a flag does not prove stock or orderability.",
                    ],
                })
    return result


def _query(action: str, settings: Settings, **parameters) -> dict:
    return request_json(API_URL, settings, method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data=urlencode({"Action": action, **parameters}).encode("ascii"),
                        authenticated=False)


def load_location_catalog(*, settings: Settings) -> dict[str, dict]:
    """Read only the two anonymous location directories, with no API keys."""
    regions = _query("ListAllRegions", settings)
    zones = _query("ListAllZones", settings)
    return parse_location_catalog(regions, zones)


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Collect public packages without reading or transmitting credentials."""
    activities = _query("ListActivity", settings)
    regions = _query("ListAllRegions", settings)
    zones = _query("ListAllZones", settings)
    packages, flags = {}, {}
    for activity in ACTIVITY_IDS:
        packages[activity] = _query("ListPackage", settings, ActivityId=activity)
        flags[activity] = _query("GetActivityFlags", settings, ActivityId=activity, PackageType="uhost")
    return parse_catalog(activities=activities, regions=regions, zones=zones,
                         packages=packages, flags=flags, observed_at=observed_at)
