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


def _compact_gpu(quote: dict) -> str:
    parts = [str(quote.get("gpu_model") or "型号未说明")]
    for field, suffix in (("gpu_variant", ""), ("vram_gb", "GB/卡"), ("gpu_count", "卡")):
        value = quote.get(field)
        if value is not None and value != "":
            parts.append(f"{value}{suffix}")
    if quote.get("raw_sku"):
        parts.append("SKU=" + str(quote["raw_sku"]))
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
        for field in ("region_name", "zone_name"):
            if location.get(field):
                parts.append(str(location[field]))
    prefix = "请求配置询价地区：" if quote["price_scope"].startswith("requested_") else "价格地区："
    return prefix + " / ".join(parts)


def _compact_conditions(quote: dict, *, collection_status: object) -> str:
    parts = []
    labels = (
        ("billing_mode", {"on_demand": "按需", "spot": "Spot（可中断）", "reserved": "预留",
                          "monthly": "月包", "yearly": "年包"}, "计费"),
        ("pricing_tier", {"ordinary": "普通用户", "member": "会员", "authenticated_market": "认证市场"}, "档位"),
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
                parts.append(label + "=" + " ".join(
                    [amount] + [str(instance[key]) for key in ("currency", "unit") if instance.get(key) is not None]
                ))
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


def prices_to_csv(result: dict, *, bilingual_headers: bool = True, profile: str = "compact") -> str:
    """Return UTF-8-BOM CSV text with one row per returned quote and CRLF rows.

    The default compact profile has ten readable columns and includes only
    actual per-GPU hourly quotes with verified country and region evidence.
    Unlocated, platform-coverage, component-only, starting-price, contact-sales,
    monthly and explicitly unavailable listings are excluded. GPU configuration and
    pricing conditions are grouped without inventing an instance total,
    country price or currency conversion. ``profile="full"`` retains all
    source records, the original 51-column schema and all metadata.

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
    ``COMPACT_CSV_COLUMNS`` and ``COMPACT_CSV_HEADERS`` describe the default.
    """
    if type(bilingual_headers) is not bool:
        raise ValueError("bilingual_headers must be boolean")
    if not isinstance(profile, str) or profile not in {"compact", "full"}:
        raise ValueError("profile must be compact or full")
    if not isinstance(result, dict) or not isinstance(result.get("prices"), list):
        raise ValueError("CSV input must be a collection result with a prices list")
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    columns = COMPACT_CSV_COLUMNS if profile == "compact" else CSV_COLUMNS
    headers = COMPACT_CSV_HEADERS if profile == "compact" else CSV_HEADERS
    writer.writerow(headers if bilingual_headers else columns)
    for quote in result["prices"]:
        if not isinstance(quote, dict):
            raise ValueError("CSV price records must be objects")
        if profile == "compact":
            if not publishable_quote(quote):
                continue
            row = {
                "gpu_model": _compact_gpu(quote), "provider": quote.get("provider"),
                "location": _compact_location(quote),
                "amount": None if quote.get("quote_status") == "contact_sales" else quote.get("amount"),
                "currency": quote.get("currency"), "unit": quote.get("unit"),
                "pricing_conditions": _compact_conditions(quote, collection_status=result.get("status")),
                "availability": quote.get("availability"), "source_url": quote.get("source_url"),
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
