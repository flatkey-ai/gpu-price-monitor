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


def prices_to_csv(result: dict, *, bilingual_headers: bool = True) -> str:
    """Return UTF-8-BOM CSV text with one row per returned quote and CRLF rows.

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
    English/Chinese ``CSV_HEADERS`` are used by default. Set
    ``bilingual_headers=False`` for the unchanged English ``CSV_COLUMNS``
    machine headers; this option never changes the data rows.
    """
    if type(bilingual_headers) is not bool:
        raise ValueError("bilingual_headers must be boolean")
    if not isinstance(result, dict) or not isinstance(result.get("prices"), list):
        raise ValueError("CSV input must be a collection result with a prices list")
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS if bilingual_headers else CSV_COLUMNS)
    for quote in result["prices"]:
        if not isinstance(quote, dict):
            raise ValueError("CSV price records must be objects")
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
