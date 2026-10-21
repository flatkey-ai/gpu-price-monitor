"""Anonymous hourly configuration quotes for UCloud's CompShare product line.

The public website bundle discovers configurations, never supplies returned
prices. Each price is freshly requested from GetCompShareInstancePrice. Only
the original published ZoneId is used, with a documented exact mapping and the
live anonymous UCloud country/region/zone directory. Unknown IDs are excluded.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import json
import re
from threading import Lock
import time

from bs4 import BeautifulSoup

from ..settings import Settings
from ..transport import FetchError, fetch_text, request_json
from . import ucloud_public

SOURCE_URL = "https://www.compshare.cn/price-list"
API_URL = "https://api.compshare.cn/"
SOURCE_TYPE = "official_public_api"
ACTION = "GetCompShareInstancePrice"
DOCUMENTATION_URL = "https://www.compshare.cn/docs/gpus/instance/getcompshareinstanceprice"
ZONE_SOURCE_URL = "https://www.compshare.cn/docs/gpus/instance/describecompsharesupportzone"
BILLING_SOURCE_URL = "https://www.compshare.cn/docs/operation/charge/billdescribe"
PRODUCT_LINE = "UCloud · CompShare（优云智算）"
# Exact IDs from the official support-zone table, verified 2026-10-21. The
# website's unknown 10033/10049 IDs must not inherit another zone's identity.
_ZONES = {
    10027: ("cn-wlcb", "cn-wlcb-01", "华北二A"),
    8200: ("cn-sh2", "cn-sh2-02", "上海二B"),
    5001: ("cn-bj2", "cn-bj2-03", "华北一C"),
    8100: ("cn-sh2", "cn-sh2-01", "上海二A"),
    8300: ("cn-sh2", "cn-sh2-03", "上海二C"),
}
_GPU_CARDS = {
    "4090": ("rtx4090", "RTX 4090"),
    "4090_48G": ("rtx4090-48g", "RTX 4090"),
    "5090": ("rtx5090", "RTX 5090"),
    "3080Ti": ("rtx3080ti", "RTX 3080 TI"),
    "3090": ("rtx3090", "RTX 3090"),
    "2080": ("rtx2080", "RTX 2080"),
    "2080Ti": ("rtx2080ti", "RTX 2080 TI"),
    "A800": ("a800", "A800"), "H20": ("h20", "H20"),
    "P40": ("p40", "P40"), "V100S": ("v100s", "V100S"),
    "A100": ("a100", "A100"),
}
_ASSET = re.compile(r"/_next/static/chunks/app/price-list/page-[a-zA-Z0-9-]+\.js\Z")
_PRICE_COMPONENTS = ("Instance", "SystemDisks", "Disks", "CompShareImage")
MAX_TARGETS = 250
MIN_REQUEST_INTERVAL_SECONDS = 0.2


def _invalid() -> ValueError:
    return ValueError("The CompShare public configuration or hourly quote structure changed.")


def _integer(value, maximum=10_000_000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise _invalid()
    return value


def _amount(value) -> Decimal:
    if type(value) not in (int, Decimal):
        raise _invalid()
    result = Decimal(value)
    if not result.is_finite() or not 0 <= result < Decimal("1e12"):
        raise _invalid()
    return result


def _money(value: Decimal) -> str:
    return format(value, "f")


def discover_asset(content: str) -> str:
    """Select one same-origin price-page bundle, without executing JavaScript."""
    soup = BeautifulSoup(content, "html.parser")
    candidates = [tag.get("src") for tag in soup.select("script[src]")
                  if _ASSET.fullmatch(tag.get("src", ""))]
    if len(candidates) != 1:
        raise _invalid()
    return "https://www.compshare.cn" + candidates[0]


def discover_targets(content: str, script: str) -> tuple[list[dict], list[dict]]:
    """Read config identities only; every embedded monetary field is discarded."""
    if not isinstance(content, str) or not isinstance(script, str):
        raise _invalid()
    matches = re.findall(r"JSON\.parse\('(\{\"MachineTypePrices\":.*?)'\)", script, re.DOTALL)
    if len(matches) != 1 or len(matches[0]) > 2 * 1024 * 1024:
        raise _invalid()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _invalid()
            result[key] = value
        return result

    try:
        payload = json.loads(matches[0], object_pairs_hook=unique)
    except (ValueError, RecursionError):
        raise _invalid() from None
    groups = payload.get("MachineTypePrices") if isinstance(payload, dict) else None
    if not isinstance(groups, list) or not 1 <= len(groups) <= 100:
        raise _invalid()
    soup = BeautifulSoup(content, "html.parser")
    targets, excluded, seen = [], [], set()
    for group in groups:
        if not isinstance(group, dict) or group.get("MachineType") not in _GPU_CARDS:
            raise _invalid()
        gpu = group["MachineType"]
        zone_id = _integer(group.get("ZoneId"))
        rows = group.get("Configs")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise _invalid()
        if zone_id not in _ZONES:
            excluded.append({"gpu_type": gpu, "zone_id": zone_id,
                             "reason": "unverified_zone_id"})
            continue
        card_id, model = _GPU_CARDS[gpu]
        cards = soup.select(f".pl-table-card[id='{card_id}']")
        if len(cards) != 1:
            raise _invalid()
        specs = cards[0].select(".pl-table-spec")
        names = cards[0].select(".pl-table-name")
        memory = re.fullmatch(r"([1-9]\d{0,3})G", specs[0].get_text(strip=True)) if len(specs) == 1 else None
        if not memory or len(names) != 1:
            raise _invalid()
        region, zone, zone_name = _ZONES[zone_id]
        for row in rows:
            if not isinstance(row, dict):
                raise _invalid()
            if row.get("ChargeType") not in {"Postpay", "Day", "Month", "Spot"}:
                raise _invalid()
            if row["ChargeType"] != "Postpay":
                continue
            count, cpu, ram, disk = (_integer(row.get(key)) for key in ("Gpu", "Cpu", "Memory", "DiskSize"))
            if ram % 1024 or row.get("DiskType") not in {"CLOUD_SSD", "CLOUD_RSSD"}:
                raise _invalid()
            request = {"Action": ACTION, "Region": region, "Zone": zone,
                       "GpuType": gpu, "Gpu": count, "Cpu": cpu, "Memory": ram,
                       "ChargeType": "Postpay", "Quantity": 1,
                       "Disks": [{"IsBoot": True, "Type": row["DiskType"], "Size": disk}]}
            identity = json.dumps(request, sort_keys=True, separators=(",", ":"))
            if identity in seen:
                continue
            seen.add(identity)
            targets.append({"request": request, "gpu_model": model,
                            "raw_name": names[0].get_text(" ", strip=True),
                            "vram_gb": int(memory[1]), "zone_id": zone_id,
                            "zone_name": zone_name})
            if len(targets) > MAX_TARGETS:
                raise _invalid()
    if not targets:
        raise _invalid()
    return targets, excluded


def _price_row(payload: dict, field: str) -> tuple[dict, Decimal]:
    rows = payload.get(field)
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or rows[0].get("ChargeType") != "Postpay" or "Instance" not in rows[0]
            or set(rows[0]) - {*_PRICE_COMPONENTS, "ChargeType", "InstanceDiscountType"}):
        raise _invalid()
    row = rows[0]
    if "InstanceDiscountType" in row and row["InstanceDiscountType"] not in (0, 1, 2):
        raise _invalid()
    components = {name: _amount(row[name]) for name in _PRICE_COMPONENTS if name in row}
    total = sum(components.values(), Decimal(0))
    if total <= 0:
        raise _invalid()
    return {name: _money(value) for name, value in components.items()}, total


def parse_quote(payload: dict, *, target: dict, location: dict, observed_at: str,
                catalog_url: str) -> dict:
    """Return the API's original tariff; anonymous discounts remain unqualified."""
    if (not isinstance(payload, dict) or type(payload.get("RetCode")) is not int
            or payload["RetCode"] != 0 or payload.get("Action") != ACTION + "Response"):
        raise _invalid()
    original_components, original = _price_row(payload, "OriginalPriceDetails")
    discounted_components, discounted = _price_row(payload, "PriceDetails")
    listing = _price_row(payload, "ListPriceDetails") if "ListPriceDetails" in payload else None
    request = target["request"]
    if location.get("region") != request["Region"] or location.get("zone") != request["Zone"]:
        raise _invalid()
    count = request["Gpu"]
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        allocated = (original / count).quantize(Decimal("0.000000000001"))
    return {
        "provider": "ucloud", "product_line": PRODUCT_LINE, "product_line_code": "compshare",
        "pricing_product_scope": "ucloud_compshare",
        "product_type": "gpu_instance", "gpu_model": target["gpu_model"],
        "gpu_variant": request["GpuType"], "raw_name": target["raw_name"],
        "raw_sku": f"compshare:{request['Zone']}:{request['GpuType']}:{count}:{request['Cpu']}:{request['Memory']}:{request['Disks'][0]['Type']}:{request['Disks'][0]['Size']}",
        "vram_gb": target["vram_gb"], "gpu_count": count,
        "amount": _money(allocated).rstrip("0").rstrip(".") or "0",
        "currency": "CNY", "unit": "gpu_hour", "billing_mode": "on_demand",
        "pricing_tier": "ordinary", "membership_required": False,
        "price_basis": "instance_total_allocated", "quote_status": "quoted",
        "regions": [request["Region"]], "zones": [request["Zone"]],
        "compute_countries": [location["country_code"]],
        "geographic_scope": "requested_zone", "location": dict(location),
        "location_source": {**ucloud_public.location_source(price_location_basis="requested_region_and_zone"),
                            "zone_id_mapping_url": ZONE_SOURCE_URL, "zone_id_verified_on": "2026-10-21",
                            "catalog_zone_id": target["zone_id"], "response_echoes_location": False},
        "account_scope": "anonymous_public_quote", "tax_scope": "unspecified",
        "availability": "unknown", "observed_at": observed_at,
        "effective_from": None, "effective_until": None,
        "source_url": SOURCE_URL, "source_type": SOURCE_TYPE,
        "api_url": API_URL, "api_action": ACTION, "api_documentation_url": DOCUMENTATION_URL,
        "catalog_discovery": {"type": "website_configuration_catalog", "page_url": SOURCE_URL,
                              "asset_url": catalog_url, "prices_taken_from_catalog": False},
        "price_field": "OriginalPriceDetails", "requested_configuration": request,
        "instance_price": {"amount": _money(original), "currency": "CNY", "unit": "instance_hour",
                           "components": original_components},
        "current_discounted_quote": {"amount": _money(discounted), "currency": "CNY", "unit": "instance_hour",
                               "components": discounted_components, "price_field": "PriceDetails",
                               "eligibility_verified": False, "membership_verified": False},
        "list_price": None if listing is None else {"amount": _money(listing[1]), "currency": "CNY", "unit": "instance_hour"},
        "normalization": {"formula": "sum(OriginalPriceDetails hourly components) / gpu_count",
                          "decimal_places": 12, "rounding": "ROUND_HALF_UP"},
        "resources": {"vcpu_count": request["Cpu"], "memory_mb": request["Memory"],
                      "system_disk_gb": request["Disks"][0]["Size"], "system_disk_type": request["Disks"][0]["Type"]},
        "conditions": ["UCloud · CompShare（优云智算）产品线；普通原价，非 UHost 活动月包。",
                       "比较金额采用 API OriginalPriceDetails；PriceDetails 折后金额仅作审计证据。",
                       "整实例小时费用按 GPU 数分摊，包含返回的 CPU、内存、GPU 及磁盘分项。",
                       "未请求的网络、共享存储、付费镜像和其他附加服务不包含在此报价。",
                       "API 折后价资格未核实，未当作会员价或比较价格。",
                       "地区为官方目录核验的请求上下文，价格响应未回显地区；库存与可购买性未验证。"],
        "notes": ["Hourly postpay billing is documented at " + BILLING_SOURCE_URL,
                  "All returned price amounts come from the fresh anonymous quote API, not the website bundle.",
                  "The source publishes no price-effective timestamp; observed_at is the collection time."],
    }


def collect_result(*, settings: Settings, observed_at: str, regions=None, zones=None) -> dict:
    """Collect exact published configs with bounded concurrency and diagnostics."""
    content = fetch_text(SOURCE_URL, settings)
    asset_url = discover_asset(content)
    targets, excluded = discover_targets(content, fetch_text(asset_url, settings))
    discovered = len(targets)
    targets = [target for target in targets
               if (not regions or target["request"]["Region"] in regions)
               and (not zones or target["request"]["Zone"] in zones)]
    catalog = ucloud_public.load_location_catalog(settings=settings) if targets else {}
    request_lock = Lock()
    last_request_at = [0.0]

    def collect_one(target):
        request = target["request"]
        identity = {key: request[key] for key in ("Region", "Zone", "GpuType", "Gpu", "Cpu", "Memory",
                                                 "ChargeType", "Quantity", "Disks")}
        try:
            location = ucloud_public.resolve_location(catalog, region=request["Region"], zone=request["Zone"])
            # Three in-flight requests maximum; start no more than five per
            # second. Transport retries remain bounded by caller Settings.
            with request_lock:
                remaining = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_at[0])
                if remaining > 0:
                    time.sleep(remaining)
                last_request_at[0] = time.monotonic()
            payload = request_json(API_URL, settings, method="POST",
                                   headers={"Content-Type": "application/json"},
                                   data=json.dumps(request, separators=(",", ":")).encode("utf-8"),
                                   authenticated=False)
            if type(payload.get("RetCode")) is int and payload["RetCode"] != 0:
                code = "authentication_required" if payload["RetCode"] == 170 else "quote_rejected"
                raise FetchError(code, "The anonymous CompShare quote API did not accept this configuration.")
            return parse_quote(payload, target=target, location=location, observed_at=observed_at,
                               catalog_url=asset_url), None
        except FetchError as exc:
            return None, {"code": exc.code, "message": str(exc), "retryable": exc.retryable, "target": identity}
        except (ValueError, TypeError, KeyError):
            return None, {"code": "invalid_quote", "message": "The CompShare hourly quote could not be verified.",
                          "retryable": False, "target": identity}

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect_one, targets))
    prices = [quote for quote, _ in results if quote is not None]
    errors = [error for _, error in results if error is not None]
    return {"prices": prices, "errors": errors,
            "status": "partial" if prices and errors else "failed" if errors else "ok",
            "discovery": {"page_url": SOURCE_URL, "asset_url": asset_url,
                          "type": "website_configuration_catalog", "discovered_target_count": discovered,
                          "requested_target_count": len(targets), "succeeded_target_count": len(prices),
                          "failed_target_count": len(errors), "excluded_unverified_zones": excluded}}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Simple adapter: fail visibly if any target failed; use collect_result for partials."""
    result = collect_result(settings=settings, observed_at=observed_at)
    if result["errors"]:
        raise FetchError("partial_collection" if result["prices"] else "quote_failed",
                         "Some CompShare hourly quote requests failed; inspect collect_result diagnostics.")
    return result["prices"]
