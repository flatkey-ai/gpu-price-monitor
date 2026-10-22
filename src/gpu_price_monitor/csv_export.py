"""Serialize collection results as native-price CSV without changing quotes."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import json
import re


CSV_COLUMNS = (
    "provider", "product_type", "gpu_vendor", "gpu_model", "gpu_variant",
    "vram_gb", "gpu_count", "raw_name", "raw_sku", "amount", "currency", "unit",
    "billing_mode", "price_basis", "quote_status", "pricing_tier",
    "membership_required", "membership_discount", "cloud_tier", "availability",
    "account_scope", "tax_scope", "compute_countries", "regions", "zones",
    "price_scope", "region_price_verified", "geographic_scope", "location_json",
    "location_source_json", "instance_amount", "instance_currency", "instance_unit",
    "instance_original_amount", "resources_json", "conditions_json", "promotion_json",
    "minimum_commitment_json", "selected_configuration_json", "components_json",
    "normalization_json", "notes_json", "source_url", "source_type", "observed_at",
    "effective_from", "effective_until", "source_last_verified", "extra_metadata_json",
    "collected_at", "collection_status",
)

_COLUMN_TRANSLATIONS = {
    "provider": "平台", "product_type": "产品类型", "gpu_vendor": "GPU厂商",
    "gpu_model": "GPU型号", "gpu_variant": "GPU规格", "vram_gb": "单GPU显存GB",
    "gpu_count": "实例GPU数量", "raw_name": "来源名称", "raw_sku": "来源SKU",
    "amount": "原币单GPU价格", "currency": "原币币种", "unit": "计费单位",
    "billing_mode": "计费模式", "price_basis": "价格口径", "quote_status": "报价状态",
    "pricing_tier": "价格档位", "membership_required": "是否要求会员",
    "membership_discount": "会员折扣", "cloud_tier": "云类型", "availability": "可用状态",
    "account_scope": "账户适用范围", "tax_scope": "税费口径",
    "compute_countries": "计算资源国家", "regions": "地区", "zones": "可用区",
    "price_scope": "价格地域范围", "region_price_verified": "地区价格是否核实",
    "geographic_scope": "来源地域口径", "location_json": "位置详情JSON",
    "location_source_json": "地域证据JSON", "instance_amount": "实例原币价格",
    "instance_currency": "实例币种", "instance_unit": "实例计费单位",
    "instance_original_amount": "实例原价", "resources_json": "资源配置JSON",
    "conditions_json": "报价条件JSON", "promotion_json": "促销条件JSON",
    "minimum_commitment_json": "最低承诺条件JSON", "selected_configuration_json": "选定配置JSON",
    "components_json": "价格组成JSON", "normalization_json": "单GPU折算规则JSON",
    "notes_json": "来源说明JSON", "source_url": "官方来源链接", "source_type": "来源类型",
    "observed_at": "报价采集时间", "effective_from": "生效时间", "effective_until": "失效时间",
    "source_last_verified": "来源最近核查日期", "extra_metadata_json": "补充元数据JSON",
    "collected_at": "本批采集时间", "collection_status": "本批采集状态",
}
CSV_HEADERS = tuple(f"{column}（{_COLUMN_TRANSLATIONS[column]}）" for column in CSV_COLUMNS)

COMPACT_CSV_COLUMNS = (
    "gpu_model", "provider", "location", "amount", "currency", "unit",
    "pricing_conditions", "availability", "source_url", "observed_at",
)
_COMPACT_TRANSLATIONS = {
    "gpu_model": "GPU型号及配置", "provider": "平台", "location": "价格国家与地区",
    "amount": "原币单GPU价格", "currency": "原币币种", "unit": "计费单位",
    "pricing_conditions": "价格与资格条件", "availability": "可用状态",
    "source_url": "官方来源链接", "observed_at": "报价采集时间",
}
COMPACT_CSV_HEADERS = tuple(
    f"{column}（{_COMPACT_TRANSLATIONS[column]}）" for column in COMPACT_CSV_COLUMNS
)
MARKET_CSV_COLUMNS = COMPACT_CSV_COLUMNS
MARKET_CSV_HEADERS = tuple(
    f"{column}（{'报价适用范围' if column == 'location' else _COMPACT_TRANSLATIONS[column]}）"
    for column in MARKET_CSV_COLUMNS
)
CATALOG_CSV_COLUMNS = MARKET_CSV_COLUMNS
CATALOG_CSV_HEADERS = MARKET_CSV_HEADERS

_JSON_FIELDS = {
    "compute_countries": "compute_countries", "regions": "regions", "zones": "zones",
    "location_json": "location", "location_source_json": "location_source",
    "resources_json": "resources", "conditions_json": "conditions",
    "promotion_json": "promotion", "minimum_commitment_json": "minimum_commitment",
    "selected_configuration_json": "selected_configuration", "components_json": "components",
    "normalization_json": "normalization", "notes_json": "notes",
}
_INSTANCE_FIELDS = {
    "instance_amount": "amount", "instance_currency": "currency",
    "instance_unit": "unit", "instance_original_amount": "original_amount",
}
_SPECIAL_COLUMNS = {*_JSON_FIELDS, *_INSTANCE_FIELDS, "extra_metadata_json", "collected_at", "collection_status"}
_SCALAR_FIELDS = tuple(column for column in CSV_COLUMNS if column not in _SPECIAL_COLUMNS)
_CONSUMED_FIELDS = {*_SCALAR_FIELDS, *_JSON_FIELDS.values(), "instance_price"}
_MONETARY_COLUMNS = {"amount", "instance_amount", "instance_original_amount"}
_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_FORMULA = re.compile(r"^[\s\ufeff]*[=+\-@]")
_REGIONAL_PRICE_SCOPES = {
    "regional_quote", "zone_quote", "requested_region_quote", "requested_zone_quote",
}


def _json_cell(value: object) -> str:
    if value is None or value == [] or value == {}:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _text_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    # Keep the quote's text, including leading whitespace, while making it a
    # spreadsheet literal. Decimal price columns bypass this text conversion.
    if _FORMULA.match(text) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _amount_cell(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("CSV monetary amounts must be finite nonnegative decimal strings or null")
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError("CSV monetary amounts must be finite nonnegative decimal strings or null")
    except InvalidOperation:
        raise ValueError("CSV monetary amounts must be finite nonnegative decimal strings or null") from None
    # No float, arithmetic, quantization, FX conversion or spreadsheet prefix.
    return value


def publishable_quote(quote: object) -> bool:
    """Whether a quote has an actual hourly rate and verified country/region.

    This checks the collector's explicit location evidence, never provider
    coverage, capacity, currency or a guessed global price. The full CSV
    profile remains available for inspecting excluded source records.
    """
    if not isinstance(quote, dict):
        return False
    if (quote.get("unit") != "gpu_hour" or quote.get("quote_status") != "quoted"
            or quote.get("price_basis") in ("starting_price", "gpu_component")
            or quote.get("region_price_verified") is not True
            or not isinstance(quote.get("price_scope"), str)
            or quote["price_scope"] not in _REGIONAL_PRICE_SCOPES
            or quote.get("availability") in ("offline", "ended", "upcoming", "unavailable")):
        return False
    countries = quote.get("compute_countries")
    regions = quote.get("regions")
    if not isinstance(countries, list) or not countries or any(
        not isinstance(code, str) or len(code) != 2 or not code.isascii()
        or not code.isalpha() or not code.isupper() for code in countries
    ):
        return False
    if not isinstance(regions, list) or not regions or any(
        not isinstance(region, str) or not region.strip() for region in regions
    ):
        return False
    if quote.get("amount") is None:
        return False
    try:
        _amount_cell(quote["amount"])
    except ValueError:
        return False
    return True


def _hourly_catalog_price(quote: object) -> bool:
    """Validate the rental rate independently of its displayable geography."""
    if not isinstance(quote, dict):
        return False
    if (quote.get("product_type") not in ("gpu_instance", "gpu_container", "gpu_cluster")
            or not isinstance(quote.get("gpu_model"), str) or not quote["gpu_model"].strip()
            or quote.get("unit") != "gpu_hour" or quote.get("quote_status") != "quoted"
            or quote.get("price_basis") not in ("advertised_per_gpu", "instance_total_allocated")
            or quote.get("billing_mode") not in ("on_demand", "spot", "reserved")
            or quote.get("availability") in ("offline", "ended", "upcoming", "unavailable")
            or not isinstance(quote.get("currency"), str)
            or not re.fullmatch(r"[A-Z]{3}", quote["currency"])
            or quote.get("amount") is None):
        return False
    try:
        _amount_cell(quote["amount"])
    except ValueError:
        return False
    return True


def _lambda_console_applicability_record(quote: dict) -> bool:
    return (quote.get("provider") == "lambda"
            and quote.get("source_type") == "official_internal_api"
            and "price_applicability" in quote)


def _lambda_shared_catalog_locations(quote: dict) -> list[dict] | None:
    # One helper supplies the adapter, filtering and export contract. Capacity
    # alone does not supply applicability, a country or a uniform price claim.
    from .providers.lambda_locations import validated_applicability_locations
    return validated_applicability_locations(quote)


def market_eligible_quote(quote: object) -> bool:
    """Whether a record supplies an actual per-GPU hourly rental price.

    The Lambda console's explicit shared-catalog applicability needs complete
    country and region metadata and at least one selectable standard location.
    Other catalogs retain their existing, separately labeled geographic scope.
    Floors, GPU-only components, monthly packages and explicitly unavailable
    listings remain audit records in the full profile.
    """
    if not _hourly_catalog_price(quote):
        return False
    if _lambda_console_applicability_record(quote):
        return bool(_lambda_shared_catalog_locations(quote))
    return True


def catalog_eligible_record(quote: object) -> bool:
    """Keep hourly GPU catalog entries, including explicit sales-only gaps.

    This is a catalog export, not a list of purchasable prices. Component-only
    rates remain in the full audit export; a sales-only entry never gains a
    numeric amount, and a From rate remains explicitly labeled as a floor.
    """
    if market_eligible_quote(quote):
        return True
    if not isinstance(quote, dict):
        return False
    # An unavailable or unlocated Lambda SKU is still a genuine catalog rate.
    # Preserve it here without relaxing numeric, period or status validation.
    if _lambda_console_applicability_record(quote) and _hourly_catalog_price(quote):
        return True
    if (quote.get("product_type") not in {"gpu_instance", "gpu_container", "gpu_cluster"}
            or not isinstance(quote.get("gpu_model"), str) or not quote["gpu_model"].strip()
            or quote.get("unit") != "gpu_hour"
            or quote.get("quote_status") not in {"contact_sales", "starting_at"}):
        return False
    if quote["quote_status"] == "contact_sales":
        return True
    try:
        return quote.get("amount") is not None and bool(_amount_cell(quote["amount"]))
    except ValueError:
        return False


def _compact_gpu(quote: dict) -> str:
    parts = [str(quote.get("gpu_model") or "型号未说明")]
    for field, suffix in (("gpu_variant", ""), ("vram_gb", "GB/卡"), ("gpu_count", "卡")):
        value = quote.get(field)
        if value is not None and value != "":
            parts.append(f"{value}{suffix}")
    if quote.get("raw_sku"):
        parts.append("SKU=" + str(quote["raw_sku"]))
    configuration = quote.get("selected_configuration")
    if quote.get("product_type") == "gpu_cluster" and isinstance(configuration, dict):
        count = configuration.get("cluster_gpu_count")
        if type(count) is int and count > 0:
            prefix = "至少" if configuration.get("cluster_gpu_count_relation") == "minimum" else ""
            parts.append(f"集群共{prefix}{count}卡")
    resources = quote.get("resources")
    if isinstance(resources, dict):
        # Keep each published unit: MB, GB and GiB are not interchangeable.
        for fields in (
            (("vcpus", "vCPU"), ("vcpu_count", "vCPU"), ("cpu_count", "CPU")),
            (("memory_gib", "GiB RAM"), ("memory_mb", "MB RAM"), ("ram_gb", "GB RAM")),
            (("storage_gib", "GiB 存储"), ("disk_gb", "GB 磁盘")),
        ):
            for field, suffix in fields:
                if resources.get(field) is not None:
                    parts.append(f"{resources[field]} {suffix}")
                    break
        if quote.get("provider") == "ucloud" and quote.get("source_type") == "official_internal_api":
            if resources.get("cpu_platform"):
                parts.append(str(resources["cpu_platform"]) + " CPU")
            if resources.get("net_capability"):
                parts.append("网络=" + str(resources["net_capability"]))
            for disk in resources.get("disks", []):
                if isinstance(disk, dict):
                    label = "系统盘" if disk.get("IsBoot") in (True, "True") else "数据盘"
                    parts.append(f"{disk.get('Size')} GB {disk.get('Type')} {label}")
        storage = resources.get("storage")
        if isinstance(storage, dict) and storage.get("amount") is not None:
            parts.append(" ".join(str(storage[key]) for key in ("amount", "unit", "type") if storage.get(key) is not None))
        if resources.get("cpu_cores_per_gpu") is not None:
            parts.append(f"{resources['cpu_cores_per_gpu']} CPU核/卡")
        per_gpu_memory = resources.get("memory_per_gpu")
        if isinstance(per_gpu_memory, dict) and per_gpu_memory.get("amount") is not None:
            parts.append(" ".join(str(per_gpu_memory[key]) for key in ("amount", "unit") if per_gpu_memory.get(key) is not None) + " RAM/卡")
    return " / ".join(parts)


def _location_values(value: object) -> list[str]:
    return [str(item) for item in value if item is not None and item != ""] if isinstance(value, list) else []


def _compact_location(quote: dict) -> str:
    # The compact writer calls this only after publishable_quote has checked
    # explicit country and regional-price evidence. Coverage is never rendered.
    parts = ["国家=" + ",".join(quote["compute_countries"])]
    for field, label in (("regions", "地区"), ("zones", "可用区")):
        values = _location_values(quote.get(field))
        if values:
            parts.append(label + "=" + ",".join(values))
    location = quote.get("location")
    if isinstance(location, dict):
        if (len(quote["compute_countries"]) == 1
                and location.get("country_code") == quote["compute_countries"][0]
                and location.get("country_name_zh")):
            parts[0] += "（" + str(location["country_name_zh"]) + "）"
        for field in ("region_name", "zone_name"):
            value = location.get(field + "_zh") or location.get(field)
            if value and value != location.get("country_name_zh"):
                parts.append(str(value))
    prefix = "请求配置询价地区：" if quote["price_scope"].startswith("requested_") else "价格地区："
    return prefix + " / ".join(parts)


def _market_location(quote: dict) -> str:
    if _lambda_console_applicability_record(quote):
        locations = _lambda_shared_catalog_locations(quote)
        if locations:
            return "统一目录价｜" + "、".join(
                location["country_name_zh"] + "·" + location["region_name_zh"]
                + "（" + location["region"] + "）" for location in locations)
        if locations == []:
            applicability = quote["price_applicability"]
            if applicability.get("excluded_dedicated_locations"):
                return "统一目录价；当前无可选标准地区（私有地区价格待核实）"
            return "统一目录价；当前无可选地区（无库存）"
        return "账号目录报价；可选地区的国家与价格适用信息待核实"
    # Only an explicit price-region binding can put a location in this cell.
    # Full location evidence remains available in JSON and the full CSV.
    regions = quote.get("regions")
    scope = quote.get("price_scope")
    if (quote.get("region_price_verified") is True
            and isinstance(scope, str) and scope in _REGIONAL_PRICE_SCOPES
            and isinstance(regions, list) and regions
            and all(isinstance(region, str) and region.strip() for region in regions)):
        countries = quote.get("compute_countries")
        has_countries = (isinstance(countries, list) and bool(countries)
                         and all(isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code)
                                 for code in countries))
        if has_countries:
            return _compact_location(quote)
        parts = ["国家未核实", "地区=" + ",".join(regions)]
        zones = _location_values(quote.get("zones"))
        if zones:
            parts.append("可用区=" + ",".join(zones))
        prefix = "请求配置询价地区：" if quote["price_scope"].startswith("requested_") else "价格地区："
        return prefix + " / ".join(parts)
    account_scope = quote.get("account_scope")
    label = {"public_catalog": "公开目录报价", "public_promotion": "公开促销报价",
             "authenticated_catalog": "账号目录报价", "account_quote": "账号配置询价",
             "account_contract_quote": "账号合同报价"}.get(
                 account_scope if isinstance(account_scope, str) else None, "目录报价")
    return label + "；适用地区未标明（不代表全球统一价）"


def _separate_configuration_costs(quote: dict) -> list[str]:
    """Keep separately estimated storage out of the main per-GPU rate."""
    parts = []
    for field, label in (("storage_quote", "另计磁盘小时费"),
                         ("full_configuration_price", "计算资源加磁盘每实例小时合计")):
        value = quote.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError("CSV supplemental prices must be objects or null")
        if value.get("amount") is None:
            continue
        amount = _amount_cell(value["amount"])
        parts.append(label + "=" + " ".join(
            [amount] + [str(value[key]) for key in ("currency", "unit") if value.get(key) is not None]
        ))
    return parts


def _ucloud_console_conditions(quote: dict, *, collection_status: object) -> str:
    """Short display of the console adapter's verified baseline and account terms.

    Exact hardware/disk/network values already appear in the GPU configuration
    cell. Source notes and normalization metadata remain in the audit profiles.
    """
    parts = [{"on_demand": "按需小时", "spot": "Spot（可中断）", "reserved": "预留"}.get(
        quote.get("billing_mode"), str(quote.get("billing_mode") or "计费方式未说明"))]
    tier = {"account": "账号报价", "ordinary": "普通用户", "member": "会员价"}.get(quote.get("pricing_tier"))
    if tier:
        parts.append(tier)
    account = {"account_quote": "当前账号询价",
               "account_contract_quote": "账号合同价",
               "authenticated_catalog": "认证账号目录价",
               "public_catalog": "公开目录价"}.get(quote.get("account_scope"))
    parts.append(account or "账号适用范围待确认")
    parts.append({"excluded": "未含税", "included": "含税"}.get(quote.get("tax_scope"), "税费未说明"))
    if quote.get("price_basis") == "instance_total_allocated":
        parts.append("整机价按卡分摊")
    if quote.get("membership_required") is not None:
        parts.append("需会员" if quote["membership_required"] else "无需会员")
    if quote.get("membership_discount") is not None:
        parts.append("会员折扣=" + str(quote["membership_discount"]))
    instance = quote.get("instance_price")
    if instance is not None and not isinstance(instance, dict):
        raise ValueError("CSV instance prices must be objects or null")
    if instance:
        amount = _amount_cell(instance.get("amount"))
        original = _amount_cell(instance.get("original_amount"))
        unit = {"instance_hour": "/小时"}.get(instance.get("unit"), " " + str(instance.get("unit") or ""))
        suffix = " " + str(instance.get("currency") or quote.get("currency") or "") + unit
        if amount:
            parts.append("整机总价=" + amount + suffix)
        if original and (not amount or Decimal(original) != Decimal(amount)):
            parts.append("整机原价=" + original + suffix)
    parts.extend(("含GPU、CPU、内存及系统盘", "不含额外数据盘、公网IP及带宽"))
    image = quote.get("image_selection")
    if isinstance(image, dict) and image.get("image_license_price_verified") is True:
        parts.append("镜像费用已核实为0")
    if collection_status == "partial":
        parts.append("本批采集不完整（已保留核实报价）")
    elif collection_status not in (None, "success"):
        parts.append("本批采集失败" if collection_status == "failed" else "采集状态=" + str(collection_status))
    return "；".join(parts)


def _compact_conditions(quote: dict, *, collection_status: object) -> str:
    parts = []
    derivation = quote.get("rate_derivation")
    if isinstance(derivation, dict) and derivation.get("independent_provider_quote") is False:
        parts.append("官方费率与规格计算；非新增独立报价；只含计算资源，磁盘与网络另计")
    labels = (
        ("billing_mode", {"on_demand": "按需", "spot": "Spot（可中断）", "reserved": "预留",
                          "monthly": "月包", "yearly": "年包"}, "计费"),
        ("pricing_tier", {"ordinary": "普通用户", "member": "会员", "account": "账号报价", "authenticated_market": "认证市场"}, "档位"),
        ("price_basis", {"advertised_per_gpu": "公开每GPU价", "starting_price": "最低起步价",
                         "gpu_component": "GPU组件价（CPU/RAM另计）", "instance_total_allocated": "整机价按卡分摊"}, "口径"),
        ("account_scope", {"public_catalog": "公开目录", "public_promotion": "公开促销",
                           "authenticated_catalog": "认证账号目录", "account_quote": "账号配置询价",
                           "account_contract_quote": "账号合同价"}, "账户适用"),
        ("tax_scope", {"excluded": "未含税", "included": "含税", "unspecified": "税费未说明"}, "税费"),
    )
    for field, mapping, label in labels:
        value = quote.get(field)
        if value is not None and value != "":
            parts.append(label + "=" + mapping.get(value, str(value)))
    status = quote.get("quote_status")
    if status == "starting_at":
        parts.append("起步价，实际报价可能更高")
    elif status == "contact_sales":
        parts.append("联系销售（未提供数值报价）")
    elif status not in (None, "", "quoted"):
        parts.append("报价状态=" + str(status))
    if quote.get("membership_required") is not None:
        parts.append("需会员" if quote["membership_required"] else "无需会员")
    for field, label in (("membership_discount", "会员折扣"), ("cloud_tier", "云档位")):
        if quote.get(field) is not None:
            parts.append(label + "=" + str(quote[field]))
    if quote.get("ordinary_price_amount") is not None and status != "contact_sales":
        parts.append("普通用户每GPU原币金额=" + _amount_cell(quote["ordinary_price_amount"]))

    instance = quote.get("instance_price")
    if instance is not None and not isinstance(instance, dict):
        raise ValueError("CSV instance prices must be objects or null")
    if status != "contact_sales" and instance:
        for field, label in (("amount", "整实例总价"), ("original_amount", "整实例原价")):
            if instance.get(field) is not None:
                amount = _amount_cell(instance[field])
                if field == "amount" and str(instance.get("scope", "")).startswith("compute_resources_only"):
                    label = "实例计算资源小时费"
                parts.append(label + "=" + " ".join(
                    [amount] + [str(instance[key]) for key in ("currency", "unit") if instance.get(key) is not None]
                ))
        parts.extend(_separate_configuration_costs(quote))
    for field, label in (
        ("conditions", "报价条件"), ("promotion", "促销资格"), ("minimum_commitment", "最低承诺"),
        ("source_conditions", "来源条件"), ("components", "组件费用"), ("normalization", "分摊规则"),
        ("selected_configuration", "选定配置"),
    ):
        value = _json_cell(quote.get(field))
        if value:
            parts.append(label + "=" + value)
    for field, label in (("effective_from", "生效"), ("effective_until", "失效")):
        if quote.get(field) is not None:
            parts.append(label + "=" + str(quote[field]))
    # Source prose can carry account jurisdictions (for example Israel),
    # separately billed resources or eligibility terms absent from the schema.
    notes = quote.get("notes")
    if isinstance(notes, list) and notes:
        parts.append("来源说明：" + "；".join(str(note) for note in notes))
    if collection_status not in (None, "success"):
        parts.append("采集状态=" + str(collection_status))
    return "；".join(parts)


def _market_note_conditions(quote: dict) -> list[str]:
    """Keep billing restrictions, omitting collection and verification prose."""
    notes = quote.get("notes")
    if not isinstance(notes, list):
        return []
    parts = []
    # These summaries follow the adapters' explicit source statements. A
    # currency never supplies a customer jurisdiction or a compute country.
    summaries = (
        ("usd billing applies except to companies from israel, where ils billing applies",
         "以色列公司按ILS计费，其余客户按USD计费（客户所在地限制）"),
        ("usd prices apply to customers except companies from israel",
         "USD价不适用于以色列公司"),
        ("ils prices apply to companies from israel",
         "ILS价适用于以色列公司（客户所在地限制）"),
        ("as often as every 15 minutes", "Spot价格可每15分钟变动"),
        ("private-region footnote", "私有地区需访问资格"),
        ("storage is charged separately", "存储另计"),
        ("additional outbound transfer can incur charges", "额外出站流量可能收费"),
        ("prices may change daily", "Spot公测，价格可每日变动"),
        ("managed disks, networking and other services are not included", "托管磁盘、网络及其他服务另计"),
        ("bandwidth, traffic and other services not included", "带宽、流量及请求外服务可能另计"),
        ("tax, network traffic, services outside this request", "网络流量及请求外服务费用未核实"),
        ("separately billed storage or networking", "存储与网络可能另计"),
    )
    substantive = re.compile(
        r"billed separately|charged separately|"
        r"\bminimum\b.*\b(?:rental|payment|commitment|billing)\b|"
        r"\b(?:requires?|must)\b.*\b(?:payment|membership|commitment|contract)\b|"
        r"\b(?:additional|outbound|egress)\b.*\b(?:charge\w*|cost\w*|fee\w*)\b|"
        r"\b(?:only|except)\b.*\b(?:customers?|compan\w*|accounts?)\b|"
        r"\b(?:contract|membership)\b.*\b(?:required|eligibility|minimum)\b|"
        r"\b(?:excludes?|includes?|exempt from|subject to)\b.*\b(?:tax(?:es)?|vat|gst)\b|"
        r"\b(?:tax(?:es)?|vat|gst)\b.*\b(?:excluded|included|exempt|applies|apply)\b|"
        r"另计|另收费|最低租用|最低承诺|合同资格",
        re.IGNORECASE,
    )
    for note in notes:
        if not isinstance(note, str):
            continue
        matched = [summary for fragment, summary in summaries if fragment in note.casefold()]
        if matched:
            parts.extend(matched)
        else:
            for sentence in re.split(r"(?<=[.!?。])\s+", note):
                # Membership and contract requirements are already carried by
                # explicit fields; keep otherwise unrepresented restrictions.
                if ("membership eligibility" in sentence.casefold() and quote.get("membership_required")):
                    continue
                if ("contract pricing was explicitly requested" in sentence.casefold()
                        and quote.get("account_scope") == "account_contract_quote"):
                    continue
                if (quote.get("tax_scope") in {"included", "excluded"}
                        and re.search(r"\b(?:tax(?:es)?|vat|gst)\b", sentence, re.IGNORECASE)):
                    continue
                if substantive.search(sentence):
                    parts.append(sentence.strip())
    return list(dict.fromkeys(parts))


def _market_conditions(quote: dict, *, collection_status: object) -> str:
    parts = []
    discovery = quote.get("catalog_discovery")
    discovered_compute = (isinstance(discovery, dict)
                          and discovery.get("method") == "authenticated_tenant_project_platform_list"
                          and isinstance(quote.get("instance_price"), dict)
                          and quote["instance_price"].get("scope") == "compute_resources_only")
    shared_locations = (_lambda_shared_catalog_locations(quote)
                        if _lambda_console_applicability_record(quote) else None)
    if shared_locations is not None:
        parts.append("同规格在所列可选地区共享目录价；非逐地区独立询价；不保证税费、合同与最终购买价")
    status = quote.get("quote_status")
    if status == "contact_sales":
        parts.append("需销售报价（官网无数值）")
    elif status == "starting_at":
        parts.append("起步价（不是完整配置报价）")
    derivation = quote.get("rate_derivation")
    if isinstance(derivation, dict) and derivation.get("independent_provider_quote") is False:
        if derivation.get("rate_source") == "current_regional_spot_api":
            parts.append("地区Spot接口价；实例费用按官方规格计算（非新增独立报价）")
        else:
            parts.append("官方费率×规格计算（非账号独立询价）")
        parts.append("只含计算资源，磁盘与网络另计")
    for field, mapping, label in (
        ("billing_mode", {"on_demand": "按需", "spot": "Spot（可中断）", "reserved": "预留"}, "计费"),
        ("pricing_tier", {"ordinary": "普通用户", "member": "会员", "account": "账号报价", "authenticated_market": "认证市场"}, "档位"),
        ("price_basis", {"advertised_per_gpu": "每GPU价", "instance_total_allocated": "整机价按卡分摊"}, "口径"),
        ("tax_scope", {"excluded": "未含税", "included": "含税", "unspecified": "税费未说明"}, "税费"),
    ):
        value = quote.get(field)
        if value is not None and value != "":
            parts.append(label + "=" + mapping.get(value, str(value)))
    account = {"public_promotion": "公开促销", "authenticated_catalog": "认证账号目录",
               "authenticated_console_catalog": "登录账号可见目录（非合同价）",
               "account_quote": "账号配置询价", "account_contract_quote": "账号合同价"}.get(quote.get("account_scope"))
    if account:
        parts.append("账户适用=" + account)
    if quote.get("membership_required") is not None:
        parts.append("需会员" if quote["membership_required"] else "无需会员")
    for field, label in (("membership_discount", "会员折扣"), ("cloud_tier", "云档位"),
                         ("product_line", "产品线")):
        if quote.get(field) is not None:
            parts.append(label + "=" + str(quote[field]))
    if quote.get("ordinary_price_amount") is not None:
        parts.append("普通用户每GPU原币金额=" + _amount_cell(quote["ordinary_price_amount"]))
    instance = quote.get("instance_price")
    if instance is not None and not isinstance(instance, dict):
        raise ValueError("CSV instance prices must be objects or null")
    for field, label in (("amount", "整实例总价"), ("original_amount", "整实例原价")):
        if instance and instance.get(field) is not None:
            if field == "amount" and str(instance.get("scope", "")).startswith("compute_resources_only"):
                label = "实例计算资源小时费"
            parts.append(label + "=" + " ".join(
                [_amount_cell(instance[field])] + [str(instance[key]) for key in ("currency", "unit") if instance.get(key) is not None]
            ))
    if status != "contact_sales":
        parts.extend(_separate_configuration_costs(quote))
    conditions = quote.get("conditions")
    if discovered_compute and isinstance(conditions, list):
        # The amounts and hardware already have dedicated human-readable cells.
        # Preserve other restrictions; request DTOs remain in the full audit CSV.
        conditions = [text for text in conditions if not isinstance(text, str) or not (
            text.startswith(("普通报价仅含VM计算费", "盘费来自同批独立CreateDiskRequest", "项目API已核实部署地区"))
            or re.match(r"\d+ GiB SSD额外", text))]
        parts.append("含GPU/CPU/RAM计算费；磁盘与网络另计")
    if isinstance(conditions, list) and isinstance(derivation, dict):
        # These adapter-generated explanations are summarized above and in the
        # location/currency labels. Preserve any other eligibility restriction.
        conditions = [text for text in conditions if not isinstance(text, str) or not text.startswith((
            "按官方每小时费率与明确 preset", "只含计算资源；", "USD适用于以色列公司以外客户；"))]
        if quote.get("currency") == "ILS":
            parts.append("ILS价适用于以色列公司（客户所在地限制）")
        elif quote.get("currency") == "USD":
            parts.append("USD价不适用于以色列公司")
    if isinstance(conditions, dict):
        if conditions.get("product_scope") == "base_vm_without_windows_license":
            parts.append("基础VM，不含Windows许可")
        conditions = {key: value for key, value in conditions.items()
                      if key not in {"capacity_type", "cloud_type", "rate_type", "product_scope", "purchase_option"}
                      and not key.endswith("_url")}
    if conditions:
        parts.append("报价条件=" + ("、".join(map(str, conditions)) if isinstance(conditions, list) else _json_cell(conditions)))
    source_conditions = quote.get("source_conditions")
    cluster_summary = False
    if isinstance(source_conditions, dict):
        offers = source_conditions.get("offer_types")
        if offers:
            parts.append("价格方案=" + ",".join(map(str, offers)))
        if quote.get("product_type") == "gpu_cluster":
            if source_conditions.get("duration_unverified") or source_conditions.get("pricing_terms_unverified"):
                parts.append("预留期限与最终购买条件待确认")
            if source_conditions.get("billing_increment") == "week":
                parts.append("按周结算；价格单位仍为每GPU小时")
            if source_conditions.get("sales_contact_required") is True:
                parts.append("需联系销售确认容量与合同")
            term = source_conditions.get("reservation_term")
            if isinstance(term, dict):
                units = {"week": "周", "month": "月", "year": "年"}
                def duration(value):
                    if (isinstance(value, dict) and type(value.get("amount")) is int
                            and value["amount"] > 0 and value.get("unit") in units):
                        return str(value["amount"]) + units[value["unit"]]
                    return None
                minimum, maximum = duration(term.get("minimum")), duration(term.get("maximum"))
                if minimum and (maximum or term.get("maximum") is None):
                    parts.append("最低承诺=" + minimum)
                    parts.append("最长期限=" + maximum if maximum else "期限无上限（需销售确认）")
                    cluster_summary = True
        handled = {"offer_types", "aggregation_unit"}
        if cluster_summary:
            handled.add("reservation_term")
        if quote.get("product_type") == "gpu_cluster":
            handled.update({"duration_unverified", "pricing_terms_unverified"})
            if source_conditions.get("reservation_term") is None:
                handled.add("reservation_term")
            if source_conditions.get("billing_increment") == "week":
                handled.add("billing_increment")
            if source_conditions.get("sales_contact_required") is True:
                handled.add("sales_contact_required")
        remaining = {key: value for key, value in source_conditions.items()
                     if key not in handled and not key.endswith("_url")}
        if remaining:
            parts.append("来源条件=" + _json_cell(remaining))
    for field, label in (("minimum_commitment", "最低承诺"), ("selected_configuration", "选定配置"),
                         ("requested_configuration", "询价配置")):
        if discovered_compute and field == "requested_configuration":
            continue
        if discovered_compute and field == "selected_configuration":
            configuration = quote.get(field)
            if isinstance(configuration, dict):
                if configuration.get("preset"):
                    parts.append("规格=" + str(configuration["preset"]))
                if configuration.get("boot_disk_gib") is not None:
                    parts.append("另配SSD=" + str(configuration["boot_disk_gib"]) + " GiB")
            continue
        if field == "minimum_commitment" and cluster_summary:
            continue
        if field == "selected_configuration":
            if quote.get("product_type") == "gpu_cluster":
                continue  # Whole-cluster count is already in the GPU label.
            if isinstance(derivation, dict):
                configuration = quote.get(field)
                if isinstance(configuration, dict) and configuration.get("preset"):
                    parts.append("规格=" + str(configuration["preset"]))
                continue  # Coverage belongs in JSON, never the price location.
        value = _json_cell(quote.get(field))
        if value:
            parts.append(label + "=" + value)
    promotion = quote.get("promotion")
    if isinstance(promotion, dict):
        if promotion.get("only_new_users") is True:
            parts.append("仅新用户")
        for field, label in (("purchase_limit", "限购数量"), ("user_types", "适用用户"),
                             ("activity_begin_at", "促销开始"), ("activity_end_at", "促销截止")):
            if promotion.get(field) is not None:
                parts.append(label + "=" + str(promotion[field]))
    for field, label in (("effective_from", "生效"), ("effective_until", "失效")):
        if quote.get(field) is not None:
            parts.append(label + "=" + str(quote[field]))
    parts.extend(_market_note_conditions(quote))
    if quote.get("price_scope") == "platform_coverage" or quote.get("coverage_regions"):
        parts.append("平台覆盖（非地区报价）")
    if quote.get("capacity_regions") and shared_locations is None:
        locations = quote.get("capacity_locations")
        if isinstance(locations, list) and locations:
            parts.append("可选容量地区=" + "、".join(
                str(location.get("description", "")) + " [" + str(location.get("name", "")) + "]"
                for location in locations if isinstance(location, dict)) + "（非独立地区报价）")
        else:
            parts.append("可用容量地区（非地区报价）")
    if quote.get("source_field_conflict"):
        parts.append("原始金额字段有冲突；采用官方前端每GPU显示价，其余仅供审计")
    source_type = quote.get("source_type")
    if source_type:
        source = {"official_api": "官方接口", "official_public_api": "官方公开接口",
                  "official_internal_api": "官方控制台内部接口",
                  "official_website_json": "官网结构化数据（非云API）",
                  "official_quote_api": "官方询价接口", "public_documentation": "官方文档",
                  "official_pricing_document": "官方价目文档", "public_page": "官网价目页",
                  "official_pricing_page": "官网价目页", "authorized_browser": "授权市场页"}.get(source_type, "其他来源")
        parts.append("来源=" + source)
    if collection_status not in (None, "success"):
        parts.append("采集状态=" + str(collection_status))
    return "；".join(parts)


def prices_to_csv(result: dict, *, bilingual_headers: bool = True, profile: str = "market") -> str:
    """Return UTF-8-BOM CSV text with one row per returned quote and CRLF rows.

    The default market profile has ten readable columns and includes actual
    per-GPU hourly catalog and regional quotes. Catalog applicability is labeled
    explicitly, without inferring countries or a global price. Lambda console
    records with shared-catalog metadata require complete selectable standard
    locations; empty or unverified applicability stays in catalog/full output.
    Component-only,
    starting-price, contact-sales, monthly and explicitly unavailable listings
    are excluded. ``profile="compact"`` retains the stricter requirement for
    verified country and region evidence. ``profile="full"`` retains every
    source record, the original 51-column schema and all metadata.
    ``profile="catalog"`` uses the same ten columns but also keeps explicitly
    labeled starting-price and contact-sales entries, with sales amounts blank.

    Input order, native decimal strings, billing periods and source geography
    are retained. No currencies or month/hour units are converted. Null and
    empty arrays/objects become blank cells; explicit ``unknown``, ``false``
    and zero remain distinct values. Complex fields use compact JSON. Further
    quote fields, including API/hardware evidence, are preserved as JSON in
    ``extra_metadata_json``. The original result is never changed.

    Partial/failed envelopes keep their status on every existing quote row.
    Empty results contain only the header, with no synthetic quote or price.
    Text cells that could become spreadsheet formulas are prefixed with an
    apostrophe; validated numeric decimal price strings remain unchanged.
    English/Chinese headers are used by default. Set ``bilingual_headers=False``
    for the profile's stable English column IDs; this option never changes
    the data rows. ``CSV_COLUMNS`` and ``CSV_HEADERS`` describe the full profile;
    ``MARKET_CSV_COLUMNS`` and ``MARKET_CSV_HEADERS`` describe the default;
    ``COMPACT_CSV_COLUMNS`` and ``COMPACT_CSV_HEADERS`` describe regional output.
    """
    if type(bilingual_headers) is not bool:
        raise ValueError("bilingual_headers must be boolean")
    if not isinstance(profile, str) or profile not in {"market", "compact", "full", "catalog"}:
        raise ValueError("profile must be market, compact or full; catalog is also supported")
    if not isinstance(result, dict) or not isinstance(result.get("prices"), list):
        raise ValueError("CSV input must be a collection result with a prices list")
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    columns = CSV_COLUMNS if profile == "full" else MARKET_CSV_COLUMNS
    headers = (CSV_HEADERS if profile == "full" else
               COMPACT_CSV_HEADERS if profile == "compact" else MARKET_CSV_HEADERS)
    writer.writerow(headers if bilingual_headers else columns)
    for quote in result["prices"]:
        if not isinstance(quote, dict):
            raise ValueError("CSV price records must be objects")
        if profile in {"market", "compact", "catalog"}:
            eligible = (publishable_quote if profile == "compact" else
                        catalog_eligible_record if profile == "catalog" else market_eligible_quote)
            if not eligible(quote):
                continue
            conditions_writer = _compact_conditions if profile == "compact" else _market_conditions
            if (profile in {"compact", "market"} and quote.get("provider") == "ucloud"
                    and quote.get("source_type") == "official_internal_api"):
                conditions_writer = _ucloud_console_conditions
            row = {
                "gpu_model": _compact_gpu(quote), "provider": quote.get("provider"),
                "location": _compact_location(quote) if profile == "compact" else _market_location(quote),
                "amount": None if quote.get("quote_status") == "contact_sales" else quote.get("amount"),
                "currency": quote.get("currency"), "unit": quote.get("unit"),
                "pricing_conditions": conditions_writer(quote, collection_status=result.get("status")),
                "availability": quote.get("availability"), "source_url": quote.get("pricing_page_url") or quote.get("source_url"),
                "observed_at": quote.get("observed_at"),
            }
            writer.writerow([
                _amount_cell(row[column]) if column == "amount" else _text_cell(row[column])
                for column in columns
            ])
            continue
        row = {column: quote.get(column) for column in _SCALAR_FIELDS}
        for column, field in _JSON_FIELDS.items():
            row[column] = _json_cell(quote.get(field))
        instance = quote.get("instance_price")
        if instance is not None and not isinstance(instance, dict):
            raise ValueError("CSV instance prices must be objects or null")
        for column, field in _INSTANCE_FIELDS.items():
            row[column] = (instance or {}).get(field)
        extra = {key: value for key, value in quote.items() if key not in _CONSUMED_FIELDS}
        instance_extra = {key: value for key, value in (instance or {}).items() if key not in _INSTANCE_FIELDS.values()}
        if instance_extra:
            extra["instance_price_metadata"] = instance_extra
        row["extra_metadata_json"] = _json_cell(extra)
        row["collected_at"] = result.get("collected_at")
        row["collection_status"] = result.get("status")
        if quote.get("quote_status") == "contact_sales":
            for column in _MONETARY_COLUMNS:
                row[column] = None
        writer.writerow([
            _amount_cell(row.get(column)) if column in _MONETARY_COLUMNS
            else _text_cell(row.get(column)) for column in CSV_COLUMNS
        ])
    return output.getvalue()
