"""AutoDL's read-only market JSON, using an explicitly exported local token.

The reviewed official market frontend selects the `payg` SKU and displays
current_price / 1000 (ordinary) or level_config.discounted_price / 1000
(member), rounded to two CNY decimals. Exact milli-CNY values are retained.
No browser, LLM, account profile, wallet, instance or order endpoint is used.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
import stat
import time

from ..settings import Settings
from ..transport import FetchError, request_json
from . import autodl_market as market, autodl_regions

SOURCE_URL = "https://www.autodl.com/api/v1/user/machine/list"
SOURCE_TYPE = "official_internal_api"
PRICING_PAGE = market.SOURCE_URL
FRONTEND_URL = "https://www.autodl.com/assets/index.ec54d3c7.js"
VERIFIED_ON = "2026-10-22"
BULK_PAGE_SIZE = 5000


def _invalid():
    return ValueError("AutoDL's hourly SKU, pricing levels, configuration or inventory changed.")


def _token(path: str | None) -> str:
    if not path:
        raise FetchError("login_required", "Export an AutoDL market session and configure AUTODL_STORAGE_STATE_PATH.")
    descriptor = None
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        state = json.loads(raw, object_pairs_hook=unique)
        token = state["origins"][0]["localStorage"][0]["value"]
        if (not isinstance(token, str) or not 0 < len(token) <= 65536
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)
                or state != {"cookies": [], "origins": [{"origin": "https://www.autodl.com",
                              "localStorage": [{"name": "token", "value": token}]}]}):
            raise ValueError
        return token
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise FetchError("storage_state_invalid", "The explicitly supplied AutoDL session must be a minimal token-only JSON file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _int(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise _invalid()
    return value


def _money(value):
    exact = Decimal(_int(value, positive=True)) / 1000
    displayed = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if displayed <= 0:
        raise _invalid()
    return format(displayed, ".2f"), format(exact, "f")


def parse_listing(item: dict, *, identity: dict, observed_at: str) -> list[dict]:
    """Project only explicit hourly tariffs, retaining both published tiers."""
    if identity["chip_corp"] in {"cpu", "huawei", "cambricon"}:
        return []
    if identity["chip_corp"] not in {"nvidia", "amd", "mthreads"}:
        raise _invalid()
    if item.get("payg") is False:
        return []
    if item.get("payg") is not True:
        raise _invalid()
    skus = item.get("machine_sku_info")
    if not isinstance(skus, list) or not skus or not isinstance(skus[0], dict) or skus[0].get("type") != "payg":
        raise _invalid()
    sku = skus[0]
    levels = sku.get("level_config")
    if not isinstance(levels, list) or not levels or any(not isinstance(x, dict) for x in levels):
        raise _invalid()
    by_level = {}
    for level in levels:
        name = level.get("level_name")
        if not isinstance(name, str) or name in by_level:
            raise _invalid()
        by_level[name] = level
    if "normal_user" not in by_level or "member_user" not in by_level:
        raise _invalid()
    ordinary = by_level["normal_user"]
    member = by_level["member_user"]
    if (_int(ordinary.get("discount"), positive=True) != 100
            or ordinary.get("discounted_price") != sku.get("current_price")
            or not 0 < _int(member.get("discount"), positive=True) <= 100
            or _int(member.get("discounted_price"), positive=True) > _int(sku.get("current_price"), positive=True)):
        raise _invalid()
    memory = _int(identity["gpu_memory"], positive=True)
    if memory % (2**30):
        raise _invalid()
    raw_name = identity["gpu_name"] + " / " + str(memory // 2**30) + " GB"
    model, vram = market._gpu_fields(raw_name)
    cpu = item.get("cpu_per_gpu")
    if type(cpu) not in {int, Decimal} or cpu <= 0:
        raise _invalid()
    ram = Decimal(_int(item.get("mem_per_gpu"), positive=True)) / (2**30)
    online = _int(item.get("on_line"))
    # The official market can report a negative native idle counter. Its
    # frontend still displays the hourly tariff and disables rent for <= 0;
    # that inventory anomaly must not discard an otherwise verified price.
    idle = item.get("gpu_idle_num")
    if type(idle) is not int:
        raise _invalid()
    maximum = _int(item.get("max_instance_num"))
    bound = _int(item.get("binding_instance_num"))
    available = online not in {3, 4, 5, 6} and idle > 0 and maximum > bound
    result = []
    for tier, level in (("ordinary", ordinary), ("member", member)):
        amount, exact = _money(level["discounted_price"])
        quote = {
            "provider": "autodl", "product_type": "gpu_container", "gpu_model": model,
            "gpu_variant": None, "vram_gb": vram, "gpu_count": None,
            "raw_name": raw_name, "raw_sku": identity["machine_id"],
            "amount": amount, "currency": "CNY", "unit": "gpu_hour", "billing_mode": "on_demand",
            "price_basis": "advertised_per_gpu", "quote_status": "quoted", "pricing_tier": tier,
            "membership_required": tier == "member", "exact_api_hourly_amount": exact,
            "regions": [identity["region_sign"]], "zones": [], "geographic_scope": "regions",
            "location": {"region": identity["region_sign"], "region_name": identity["region_name"]},
            "resources": {"allocation_scope": "per_gpu", "cpu_cores_per_gpu": format(Decimal(cpu), "f"),
                          "memory_per_gpu": {"amount": format(ram, "f"), "unit": "GB"}},
            "availability": "available" if available else "out_of_stock",
            "available_gpu_count": idle if available else 0, "vendor_online_status": online,
            "inventory_label": f"{idle}卡可租" if available else "已租完",
            "account_scope": "authenticated_catalog", "tax_scope": "unspecified",
            "conditions": ["Requires AutoDL member eligibility."] if tier == "member" else [],
            "price_source": {"field": "machine_sku_info[0].level_config[" + level["level_name"] + "].discounted_price",
                             "native_amount_milli_cny": level["discounted_price"], "native_currency": "CNY",
                             "conversion": "milli-CNY / 1000, then official frontend two-decimal half-up display"},
            "pricing_protocol": {"source_url": FRONTEND_URL, "verified_on": VERIFIED_ON,
                                 "hourly_sku_type": "payg", "ordinary_field": "current_price"},
            "observed_at": observed_at, "effective_from": None, "effective_until": None,
            "source_url": SOURCE_URL, "pricing_page_url": PRICING_PAGE, "source_type": SOURCE_TYPE,
            "notes": ["Direct read-only official market JSON; no browser or LLM runs during collection.",
                      "Only explicitly hourly payg SKUs are included; daily, weekly and monthly prices are never divided into hours.",
                      "Amount matches the official two-decimal display; exact_api_hourly_amount preserves the finer API precision.",
                      "Out of stock means the official UI displays 已租完; it does not establish product discontinuation.",
                      "Prices refer to the advertised accelerator slot; composite or virtual GPU model names are preserved."],
        }
        if tier == "member":
            quote["membership_discount_badge"] = format(Decimal(level["discount"]) / 10, "f") + "折"
        result.append(quote)
    return result


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    token = _token(settings.autodl_storage_state_path)
    headers = {"Authorization": token, "Content-Type": "application/json",
               "Origin": "https://www.autodl.com", "Referer": PRICING_PAGE}
    quotes, gaps, seen = [], [], set()
    total = None
    pages = 0
    excluded_non_gpu = excluded_non_hourly = 0
    deadline = time.monotonic() + settings.timeout_seconds
    for index in range(1, market.MAX_PAGES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout", "AutoDL market API pagination timed out.", True)
        query = market.market_query(index, page_size=BULK_PAGE_SIZE)
        payload = request_json(SOURCE_URL, replace(settings, timeout_seconds=min(30, remaining)),
                               method="POST", headers=headers, data=json.dumps(query).encode(), authenticated=True,
                               max_response_bytes=32 * 1024 * 1024)
        metadata = market.project_market_response(payload, query)
        if total is None:
            total = metadata["result_total"]
        if metadata["result_total"] != total:
            raise FetchError("market_changed", "AutoDL's market changed during pagination; retry the complete read.", True)
        for item, identity in zip(payload["data"]["list"], metadata["rows"]):
            if identity["machine_id"] in seen:
                raise FetchError("market_changed", "AutoDL returned overlapping market pages; retry the complete read.", True)
            seen.add(identity["machine_id"])
            if identity["chip_corp"] in {"cpu", "huawei", "cambricon"}:
                excluded_non_gpu += 1
                continue
            if item.get("payg") is False:
                excluded_non_hourly += 1
                continue
            try:
                quotes.extend(parse_listing(item, identity=identity, observed_at=observed_at))
            except (ValueError, TypeError, KeyError):
                gaps.append({"scope": "market_hourly_tariff", "status": "pricing_not_verified",
                             "machine_id": identity["machine_id"], "region": identity["region_sign"],
                             "gpu_model": identity["gpu_name"], "reason": "The explicit hourly SKU/configuration did not match the reviewed pricing protocol."})
        pages += 1
        if len(seen) == total:
            break
        time.sleep(0.1)
    if total is None or len(seen) != total:
        raise FetchError("pagination_incomplete", "AutoDL market API pagination did not cover the source count.")
    errors, directory = [], {}
    try:
        directory = autodl_regions.parse_region_directory(request_json(autodl_regions.REGIONS_URL, settings), observed_at=observed_at)
    except (FetchError, ValueError, TypeError, KeyError):
        errors.append({"source": "region_country_directory", "code": "region_directory_unavailable",
                       "message": "Public country evidence was unavailable; no country was guessed.", "retryable": True})
    quotes, country_gaps = autodl_regions.enrich_market_quotes(quotes, region_directory=directory)
    gaps.extend({(g["region"], g["reason"]): g for g in country_gaps}.values())
    summary = {"market_listing_count": total, "observed_unique_listing_count": len(seen), "pages": pages,
               "gpu_listing_count": len({q["raw_sku"] for q in quotes}), "returned_price_count": len(quotes),
               "excluded_non_gpu_listing_count": excluded_non_gpu, "excluded_non_hourly_listing_count": excluded_non_hourly,
               "country_verified_price_count": sum(bool(q["compute_countries"]) for q in quotes),
               "country_codes": sorted({c for q in quotes for c in q["compute_countries"]}),
               "region_codes": sorted({r for q in quotes for r in q["regions"]}),
               "unverified_hourly_listing_count": sum(g["scope"] == "market_hourly_tariff" for g in gaps),
               "hourly_market_pages_complete": True, "all_billing_periods_included": False}
    return {"status": "partial" if errors or gaps else "ok", "prices": quotes, "errors": errors, "gaps": gaps,
            "coverage": summary, "catalog_coverage": {"summary": summary},
            "authentication_method": "caller_exported_token_only_session",
            "source_contexts": [{"source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "status": "ok", "quote_count": len(quotes)}]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    return collect_result(settings=settings, observed_at=observed_at)["prices"]
