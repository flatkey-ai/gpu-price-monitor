"""Small, provider-specific hourly CSV views; collection JSON remains the audit record.

No files are written and no currency/period conversion or instance-total inference
is performed. Only quotes with verified price geography enter these tables.
"""

from __future__ import annotations

from collections import Counter
import csv
import io
import re

from .csv_export import (
    _amount_cell, _hourly_catalog_price, _json_cell, _market_note_conditions,
    _text_cell, publishable_quote,
)
from .member_prices import prefer_member_quotes
from .providers.lambda_locations import validated_applicability_locations


_COMMON = (
    "provider", "gpu_model", "gpu_count", "country", "region", "zone",
    "gpu_hour_amount", "instance_hour_amount", "currency", "billing_mode",
    "pricing_conditions", "availability", "source_url", "observed_at",
)
_EXTRA = {
    "nebius": ("platform", "preset", "resource_config"),
    "lambda": ("instance_sku", "cpu", "memory", "storage"),
    "crusoe": ("instance_sku", "resource_config"),
    "autodl": ("machine_id", "data_center", "membership", "resource_config"),
    "ucloud": ("instance_sku", "cpu_memory", "boot_disk", "image_network"),
    "runpod": ("instance_sku", "cloud_tier", "resource_config"),
    "azure": ("instance_sku", "cpu", "memory", "billing_meter"),
    "digitalocean": ("instance_sku", "cpu", "memory", "storage"),
    "verda": ("instance_sku", "resource_config"),
    "vast": ("offer_id", "cpu_memory", "storage", "extra_costs"),
}
_TRANSLATIONS = {
    "provider": "平台", "gpu_model": "GPU型号及规格", "gpu_count": "实例或集群GPU数量",
    "country": "国家代码", "region": "报价地区", "zone": "可用区",
    "gpu_hour_amount": "原币单GPU每小时价格", "instance_hour_amount": "原币实例每小时价格",
    "currency": "原币币种", "billing_mode": "计费方式", "pricing_conditions": "价格适用条件",
    "availability": "库存状态", "source_url": "官方来源", "observed_at": "采集时间",
    "platform": "硬件平台", "preset": "实例预设", "resource_config": "资源配置",
    "instance_sku": "实例规格", "cpu": "CPU", "memory": "内存", "storage": "存储",
    "machine_id": "机器编号", "data_center": "机房", "membership": "会员档位",
    "cpu_memory": "CPU与内存", "boot_disk": "启动磁盘", "image_network": "镜像与网络模式",
    "cloud_tier": "云类型", "billing_meter": "计费项目", "offer_id": "报价编号",
    "extra_costs": "另计费用",
}
PROVIDER_CSV_COLUMNS = {provider: _COMMON + extra for provider, extra in _EXTRA.items()}
PROVIDER_CSV_HEADERS = {
    provider: tuple(f"{key}（{_TRANSLATIONS[key]}）" for key in columns)
    for provider, columns in PROVIDER_CSV_COLUMNS.items()
}
_DEFAULT_COLUMNS = _COMMON + ("instance_sku", "resource_config")
_BILLING = {"on_demand": "on_demand（按需小时）", "spot": "spot（可中断）", "reserved": "reserved（预留）"}


def _object(value):
    return value if isinstance(value, dict) else {}


def _join(values):
    return " / ".join(str(value) for value in values if value is not None and value != "")


def _native_instance_amount(quote):
    value = _object(quote.get("instance_price"))
    if value.get("amount") is None:
        return None
    # The common currency column must describe both monetary columns exactly.
    if value.get("unit") != "instance_hour" or value.get("currency") != quote["currency"]:
        return None
    return _amount_cell(value["amount"])


def _resource_cells(quote):
    worker = quote.get("product_type") == "gpu_cluster"
    resources = _object(quote.get("worker_resources")) if worker else _object(quote.get("resources"))
    scope = "每节点 " if worker else ""
    cpu = next((f"{resources[key]} {unit}" for key, unit in (
        ("vcpus", "vCPU"), ("vcpu_count", "vCPU"), ("cpu_count", "CPU"),
        ("cpu", "CPU"), ("cpu_cores_per_gpu", "CPU核/卡"),
    ) if resources.get(key) is not None), "")
    memory = next((f"{resources[key]} {unit}" for key, unit in (
        ("memory_gib", "GiB"), ("memory_mb", "MB"), ("ram_gb", "GB"), ("memory_gb", "GB"),
    ) if resources.get(key) is not None), "")
    per_gpu = _object(resources.get("memory_per_gpu"))
    if not memory and per_gpu.get("amount") is not None:
        memory = _join((per_gpu["amount"], per_gpu.get("unit"))) + "/卡"
    storage = next((f"{resources[key]} {unit}" for key, unit in (
        ("storage_gib", "GiB"), ("storage_gb", "GB"), ("disk_gb", "GB"), ("disk_space", "GB"),
    ) if resources.get(key) is not None), "")
    conditions = _object(quote.get("conditions"))
    if (quote.get("provider") == "vast" and resources.get("storage_gb") is not None
            and conditions.get("storage_unit") == "GB_as_documented_by_API"):
        storage = f"{resources['storage_gb']} GB（API文档；CLI称GiB，未换算）"
    native_storage = _object(resources.get("storage"))
    if not storage and native_storage.get("amount") is not None:
        storage = _join((native_storage["amount"], native_storage.get("unit"), native_storage.get("type")))
    return tuple(scope + value if value else "" for value in (cpu, memory, storage))


def _conditions(quote, *, shared, status):
    parts = []
    if shared:
        parts.append("所列可选地区统一目录价；非逐地区独立询价；最终购买价未核实")
    elif str(quote.get("price_scope", "")).startswith("requested_"):
        parts.append("指定地区配置询价")
    if quote.get("price_basis") == "instance_total_allocated":
        parts.append("整机价按GPU数量分摊")
    if quote.get("membership_required") is True:
        parts.append("需会员资格；资格未核实")
    parts.append({"included": "含税", "excluded": "未含税"}.get(quote.get("tax_scope"), "税费未说明"))
    account = {"authenticated_catalog": "登录账号目录价", "authenticated_console_catalog": "登录账号目录价",
               "account_quote": "当前账号报价", "account_contract_quote": "账号合同价"}.get(quote.get("account_scope"))
    if account:
        parts.append(account)
    for field, label in (("minimum_commitment", "最低承诺"), ("promotion", "促销限制")):
        if quote.get(field):
            parts.append(label + "=" + _json_cell(quote[field]))
    conditions = quote.get("conditions")
    if isinstance(conditions, list):
        parts.extend(value for value in conditions if isinstance(value, str) and value)
    elif isinstance(conditions, dict):
        for key in ("product_scope", "purchase_option", "rate_type"):
            if conditions.get(key):
                parts.append(key + "=" + str(conditions[key]))
    source = _object(quote.get("source_conditions"))
    if quote.get("duration_unverified") or source.get("duration_unverified"):
        parts.append("预留期限未核实")
    if quote.get("pricing_terms_unverified") or source.get("pricing_terms_unverified"):
        parts.append("最终购买条件未核实")
    for key, label in (("billing_increment", "结算周期"), ("reservation_term", "预留期限")):
        if source.get(key):
            parts.append(label + "=" + (_json_cell(source[key]) if isinstance(source[key], dict) else str(source[key])))
    if quote.get("product_type") == "gpu_cluster":
        parts.append("卡数为集群总量；CPU/内存/存储按单节点列示；实例小时价不虚算集群总价")
    instance = _object(quote.get("instance_price"))
    if str(instance.get("scope", "")).startswith("compute_resources_only"):
        parts.append("仅计算资源；磁盘和网络另计")
    if quote.get("provider") == "ucloud" and quote.get("source_type") == "official_internal_api":
        parts.append("含所选启动盘；不含额外数据盘、外网IP、带宽与付费镜像")
    parts.extend(_market_note_conditions(quote))
    if status not in (None, "success"):
        parts.append("本批采集状态=" + str(status))
    return "；".join(dict.fromkeys(parts))


def _locations(quote):
    shared = validated_applicability_locations(quote)
    if shared:
        return [(item["country_code"], item["region"], "", True) for item in shared]
    if not publishable_quote(quote):
        return []
    if any(region.strip().casefold() in {"global", "global listings", "unknown", "unspecified", "not published"}
           for region in quote["regions"]):
        return []
    # An opaque multi-country list has no country-to-region join. Do not invent
    # its cross product. Current regional adapters supply one country per quote.
    countries = quote["compute_countries"]
    if len(set(countries)) != 1 or countries[0] == "EU":
        return []
    return [(countries[0], " | ".join(quote["regions"]), " | ".join(quote.get("zones") or []), False)]


def _provider_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
        raise ValueError("Provider CSV records require a valid provider identifier")
    return value


def _prepare(result, prefer_member):
    if type(prefer_member) is not bool:
        raise ValueError("prefer_member must be boolean")
    if not isinstance(result, dict) or not isinstance(result.get("prices"), list):
        raise ValueError("Provider CSV input must have a prices list")
    providers, original = {}, Counter()
    for quote in result["prices"]:
        if not isinstance(quote, dict):
            raise ValueError("Provider CSV price records must be objects")
        name = _provider_name(quote.get("provider"))
        providers.setdefault(name, [])
        original[name] += 1
    sources = result.get("provider_results", [])
    if not isinstance(sources, list):
        raise ValueError("provider_results must be a list")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Provider results must be objects")
        providers.setdefault(_provider_name(source.get("provider")), [])
    quotes = prefer_member_quotes(result["prices"]) if prefer_member else result["prices"]
    for quote in quotes:
        providers[quote["provider"]].append(quote)
    return providers, original


def _eligible_rows(quote):
    if not _hourly_catalog_price(quote):
        return [], "not_exact_hourly_rental"
    locations = _locations(quote)
    return locations, None if locations else "country_region_not_verified"


def provider_csv_coverage(result: dict, *, prefer_member: bool = True) -> dict[str, dict]:
    """Safe counts explaining empty tables, exclusions and shared-location rows.

    ``exported_quote_count`` counts observations; ``row_count`` includes Lambda
    location expansions and must not be described as independent price queries.
    """
    providers, original = _prepare(result, prefer_member)
    output = {}
    for provider, quotes in providers.items():
        reasons, count, rows, shared = Counter(), 0, 0, 0
        for quote in quotes:
            locations, reason = _eligible_rows(quote)
            if reason:
                reasons[reason] += 1
            else:
                count += 1
                rows += len(locations)
                shared += int(locations[0][3])
        output[provider] = {"source_quote_count": original[provider], "exported_quote_count": count,
                            "row_count": rows, "shared_catalog_quote_count": shared,
                            "ordinary_member_pairs_hidden": original[provider] - len(quotes),
                            "excluded_quote_count": sum(reasons.values()), "excluded_reasons": dict(reasons)}
    return output


def _row(quote, location, status):
    country, region, zone, shared = location
    resources, config = _object(quote.get("resources")), _object(quote.get("selected_configuration"))
    cpu, memory, storage = _resource_cells(quote)
    location_data, image = _object(quote.get("location")), _object(quote.get("image_selection"))
    disks = resources.get("disks") if isinstance(resources.get("disks"), list) else []
    boot = [_join((str(disk["Size"]) + " GB" if disk.get("Size") is not None else "", disk.get("Type")))
            for disk in disks if isinstance(disk, dict)
            and (disk.get("IsBoot") is True or disk.get("IsBoot") == "True")]
    gpu_count = quote.get("gpu_count")
    if quote.get("product_type") == "gpu_cluster" and config.get("cluster_gpu_count_relation") == "exact":
        gpu_count = config.get("cluster_gpu_count")
    extra_costs = _market_note_conditions(quote)
    if quote["provider"] == "vast":
        if _object(quote.get("conditions")).get("bandwidth_included") is False:
            extra_costs.append("带宽另计")
        extra_costs.append({"included": "含税", "excluded": "未含税"}.get(quote.get("tax_scope"), "税费未说明"))
    return {
        "provider": quote["provider"],
        "gpu_model": _join((quote.get("gpu_model"), quote.get("gpu_variant"),
                            f"{quote['vram_gb']} GB/卡" if quote.get("vram_gb") is not None else "")),
        "gpu_count": gpu_count, "country": country, "region": region, "zone": zone,
        "gpu_hour_amount": quote["amount"], "instance_hour_amount": _native_instance_amount(quote),
        "currency": quote["currency"], "billing_mode": _BILLING[quote["billing_mode"]],
        "pricing_conditions": _conditions(quote, shared=shared, status=status),
        "availability": quote.get("availability"), "source_url": quote.get("pricing_page_url") or quote.get("source_url"), "observed_at": quote.get("observed_at"),
        "platform": resources.get("platform") or quote.get("raw_sku"), "preset": resources.get("preset"),
        "resource_config": _join((cpu, memory, storage)), "instance_sku": quote.get("raw_sku") or quote.get("raw_name"),
        "cpu": cpu, "memory": memory, "storage": storage, "machine_id": quote.get("raw_sku"),
        "data_center": location_data.get("data_center") or location_data.get("region_name_zh") or location_data.get("region_name"),
        "membership": {"member": "member（会员价；需会员资格）", "ordinary": "ordinary（普通价）"}.get(quote.get("pricing_tier"), quote.get("pricing_tier")),
        "cpu_memory": _join((cpu, memory, resources.get("cpu_platform"))), "boot_disk": " | ".join(boot),
        "image_network": _join((image.get("image_name") or image.get("image_id"), resources.get("net_capability") or _object(quote.get("network_selection")).get("mode"))),
        "cloud_tier": quote.get("cloud_tier"), "billing_meter": _object(quote.get("azure_meter")).get("meter_name") or quote.get("billing_meter"),
        "offer_id": quote.get("raw_sku"), "extra_costs": "；".join(dict.fromkeys(extra_costs)),
    }


def prices_to_provider_csvs(result: dict, *, bilingual_headers: bool = True,
                           prefer_member: bool = True) -> dict[str, str]:
    """Return one 16–18-column native-price CSV per observed/requested provider.

    Columns differ by provider. Empty/failed/unlocated providers still receive
    headers when present in ``provider_results``; see ``provider_csv_coverage``
    for exclusion counts. Lambda's validated shared catalog is explicitly labeled
    and split by its listed country/region. Missing location is never called global.

    Verified matching AutoDL member prices are preferred by default; eligibility
    remains explicit. Set ``prefer_member=False`` to retain both tariffs. UTF-8
    BOM, bilingual headers and spreadsheet formula protection match other exports.
    Input is unchanged. Amounts remain original decimal strings; no FX or implied
    per-instance/cluster multiplication is applied, and unknown quantities are blank.
    """
    if type(bilingual_headers) is not bool:
        raise ValueError("bilingual_headers must be boolean")
    providers, _ = _prepare(result, prefer_member)
    output = {}
    for provider, quotes in providers.items():
        columns = PROVIDER_CSV_COLUMNS.get(provider, _DEFAULT_COLUMNS)
        buffer = io.StringIO(newline="")
        buffer.write("\ufeff")
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow([f"{key}（{_TRANSLATIONS[key]}）" for key in columns] if bilingual_headers else columns)
        for quote in quotes:
            locations, _ = _eligible_rows(quote)
            for location in locations:
                row = _row(quote, location, result.get("status"))
                writer.writerow([_amount_cell(row[key]) if key in {"gpu_hour_amount", "instance_hour_amount"}
                                 else _text_cell(row[key]) for key in columns])
        output[provider] = buffer.getvalue()
    return output
