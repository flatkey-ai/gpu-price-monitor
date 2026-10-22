"""Calculate documented Nebius GPU presets and expand live regional Spot rates.

Public tariff calculations are explicitly distinct from account estimates and
regional prices. No monthly-to-hourly conversion or minimum Spot price is used.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from html import unescape
import re

from ..settings import Settings
from ..transport import FetchError, fetch_text
from . import nebius, nebius_catalog, nebius_regions, nebius_spot

SOURCE_URL = "https://docs.nebius.com/compute/resources/pricing.md"
PUBLIC_URL = "https://docs.nebius.com/compute/resources/pricing"
TYPES_URL = "https://docs.nebius.com/compute/virtual-machines/types.md"
REGIONS_URL = "https://docs.nebius.com/overview/regions.md"
ACCOUNT_API_URL = "https://api.nebius.cloud/billing/v1/calculator/estimate-batch"
ACCOUNT_DOCUMENTATION_URL = "https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch"
SOURCE_TYPE = "official_pricing_document"
_PRESET = re.compile(r"([1-9]\d*)gpu-([1-9]\d*)vcpu-([1-9]\d*)gb\Z")
_REGION = re.compile(r"`([a-z]{2}-[a-z]+\d+)`")
_PLATFORM = re.compile(r"\b(gpu-[a-z0-9-]+)\b")


def _invalid() -> ValueError:
    return ValueError("The Nebius published GPU presets, prices or geography structure changed.")


def _plain(text):
    return " ".join(nebius._plain(unescape(text)).replace("`", "").split())


def _section(content, heading, end):
    match = re.search(heading + r"\n(.*?)(?=" + end + r"|\Z)", content, re.MULTILINE | re.DOTALL)
    if not match:
        raise _invalid()
    return match[1]


def _table(content, expected):
    lines = [line.strip() for line in content.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        raise _invalid()
    rows = [[_plain(cell) for cell in line.strip("|").split("|")] for line in lines]
    if tuple(rows[0]) != expected or any(len(row) != len(expected) for row in rows):
        raise _invalid()
    if not all(re.fullmatch(r"[-: ]+", cell) for cell in rows[1]):
        raise _invalid()
    return rows[2:]


def parse_regions(content: str, *, observed_at: str | None = None) -> dict[str, dict]:
    """Read explicit official country names; never infer a country from a code."""
    result = nebius_regions.parse_directory(content, observed_at=observed_at)
    if any(location["country_code"] is None for location in result.values()):
        raise _invalid()
    return result


def parse_platforms(content: str, regions: dict) -> dict[str, dict]:
    """Parse every public GPU platform, memory type and exact resource preset."""
    first = content.split("## GPU types", 1)[0]
    platforms = {}
    for name, identity, cpu, region_text in _table(first, ("Platform name", "Platform ID", "CPU", "Regions")):
        if not identity.startswith("gpu-"):
            continue
        # _table removes Markdown code ticks; parse only exact region labels.
        codes = re.findall(r"\b[a-z]{2}-[a-z]+\d+\b", region_text)
        if identity in platforms or not codes or any(code not in regions for code in codes):
            raise _invalid()
        platforms[identity] = {"platform_id": identity, "platform_name": name, "cpu_model": cpu,
                               "coverage_regions": list(dict.fromkeys(codes)), "presets": []}
    gpu_body = _section(content, r"^## GPU types", r"^## ")
    gpu_columns = ("GPU", "Architecture", "Form factor", "GPU memory", "Memory bandwidth",
                   "InfiniBand interconnect", "Network adapter", "Platform", "CPU")
    for row in _table(gpu_body, gpu_columns):
        gpu, architecture, form, memory, *_ = row
        model = re.sub(r"^NVIDIA\s+", "", gpu).removesuffix(" Server Edition")
        match = re.fullmatch(r"([1-9]\d*) GB(?: (.*))?", memory)
        ids = _PLATFORM.findall(row[7])
        if not match or not ids:
            raise _invalid()
        for identity in ids:
            if identity not in platforms or "gpu_model" in platforms[identity]:
                raise _invalid()
            platforms[identity].update(gpu_model=model, vram_gb=int(match[1]),
                                       gpu_memory_description=memory, architecture=architecture,
                                       form_factor=form)
    presets_body = _section(content, r"^## Presets for GPU platforms", r"^### Presets compatible|^## ")
    groups = re.findall(r"^\* ([^\n]+)\n(.*?)(?=^\* |\Z)", presets_body, re.MULTILINE | re.DOTALL)
    seen = set()
    for label, body in groups:
        ids = _PLATFORM.findall(label)
        lines = [line.strip() for line in body.splitlines() if line.strip().startswith("|")]
        if not lines:
            raise _invalid()
        header = tuple(_plain(cell) for cell in lines[0].strip("|").split("|"))
        expected = ("Preset name", "Number of GPUs", "Number of vCPUs", "RAM, GiB")
        if header not in (expected, expected + ("Regions",)) or not ids:
            raise _invalid()
        for row in _table(body, header):
            match = _PRESET.fullmatch(row[0])
            if not match or tuple(map(int, match.groups())) != tuple(map(int, row[1:4])):
                raise _invalid()
            count, cpus, ram = map(int, match.groups())
            for identity in ids:
                if identity not in platforms or (identity, row[0]) in seen:
                    raise _invalid()
                coverage = platforms[identity]["coverage_regions"]
                if len(row) == 5:
                    coverage = re.findall(r"\b[a-z]{2}-[a-z]+\d+\b", row[4])
                    if not coverage or not set(coverage) <= set(platforms[identity]["coverage_regions"]):
                        raise _invalid()
                seen.add((identity, row[0]))
                platforms[identity]["presets"].append({"preset": row[0], "gpu_count": count,
                                                       "vcpus": cpus, "memory_gib": ram,
                                                       "coverage_regions": list(coverage)})
    if not platforms or any(not item["presets"] or "gpu_model" not in item for item in platforms.values()):
        raise _invalid()
    return platforms


def _price_platform(title: str, platforms: dict) -> str:
    explicit = _PLATFORM.findall(title)
    if explicit:
        if len(explicit) != 1 or explicit[0] not in platforms:
            raise _invalid()
        return explicit[0]
    label = _plain(title).replace("®", "").replace("™", "")
    candidates = [identity for identity, item in platforms.items()
                  if item["gpu_model"] in label and (
                      item["gpu_model"] != "L40S" or
                      ("Intel" in label and "Intel" in item["cpu_model"]) or
                      ("AMD" in label and "AMD" in item["cpu_model"]))]
    if len(candidates) != 1:
        raise _invalid()
    return candidates[0]


def _rates(content: str, platforms: dict, as_of: date) -> tuple[list[dict], list[dict]]:
    body = _section(content, r"^### Virtual machines[^\n]*", r"^### ")
    sections = re.findall(r"^#### (NVIDIA[^\n]+)\n(.*?)(?=^#### |\Z)", body, re.MULTILINE | re.DOTALL)
    if not sections:
        raise _invalid()
    rates, minimums, seen = [], [], set()
    for title, section in sections:
        platform = _price_platform(title, platforms)
        preamble, tables = nebius._currency_tables(section)
        price_coverage = _REGION.findall(preamble)
        if set(price_coverage) != set(platforms[platform]["coverage_regions"]):
            raise _invalid()
        for currency, table in tables:
            rows = nebius._table_rows(table, currency, as_of)
            for mode in ("on_demand", "spot"):
                selected = [row for row in rows if row["billing_mode"] == mode]
                gpu_rows = [row for row in selected if row["unit"] == "1 GPU hour"]
                if len(gpu_rows) != 1 or (platform, currency, mode) in seen:
                    raise _invalid()
                seen.add((platform, currency, mode))
                if any(row["starting"] for row in selected):
                    minimums.append({"platform": platform, "currency": currency, "billing_mode": mode,
                                     "minimum_gpu_hour": gpu_rows[0]["amount"], "status": "starting_at",
                                     "source_url": PUBLIC_URL})
                    continue
                component_units = [row["unit"] for row in selected]
                if component_units not in (["1 GPU hour"], ["1 GPU hour", "1 CPU hour", "1 GiB hour"]):
                    raise _invalid()
                rates.append({"platform": platform, "currency": currency, "billing_mode": mode,
                              "rows": selected, "effective_from": gpu_rows[0]["effective_from"],
                              "effective_until": gpu_rows[0]["effective_until"]})
    if {item["platform"] for item in rates if item["billing_mode"] == "on_demand"} != set(platforms):
        raise _invalid()
    return rates, minimums


def _value(value: Decimal) -> str:
    return format(value, "f")


def calculate_catalog(pricing: str, types: str, regions: str, *, observed_at: str, as_of: date | None = None) -> dict:
    """Return exact compute-only preset calculations, with coverage kept separate."""
    as_of = as_of or datetime.fromisoformat(observed_at.replace("Z", "+00:00")).date()
    countries = parse_regions(regions, observed_at=observed_at)
    platforms = parse_platforms(types, countries)
    rates, minimums = _rates(pricing, platforms, as_of)
    if "Prices in US dollars (USD" not in pricing or "companies from Israel" not in pricing:
        raise _invalid()
    tax_scope = "excluded" if "All prices are shown without any applicable taxes" in pricing else "unspecified"
    prices = []
    for rate in rates:
        platform = platforms[rate["platform"]]
        for preset in platform["presets"]:
            quantities = {"1 GPU hour": ("gpu", "gpu_hour", preset["gpu_count"]),
                          "1 CPU hour": ("vcpu", "cpu_hour", preset["vcpus"]),
                          "1 GiB hour": ("memory", "gib_hour", preset["memory_gib"])}
            components = []
            with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
                for row in rate["rows"]:
                    resource, unit, quantity = quantities[row["unit"]]
                    component = Decimal(row["amount"]) * quantity
                    components.append({"resource": resource, "unit_price": row["amount"], "unit": unit,
                                       "quantity": quantity, "amount": _value(component), "currency": rate["currency"]})
                total = sum((Decimal(row["amount"]) for row in components), Decimal(0))
                amount = (total / preset["gpu_count"]).quantize(Decimal("0.000000000001"))
            coverage = preset["coverage_regions"]
            conditions = ["按官方每小时费率与明确 preset 数量计算；不是账号实时报价或地区独立询价。",
                          "只含计算资源；磁盘、共享文件系统、网络及其他附加服务另计。",
                          "USD适用于以色列公司以外客户；以色列公司使用ILS，与计算资源国家无关。"]
            if any(countries[region]["private_region"] for region in coverage):
                conditions.append("覆盖列表含私有地区，仅已有部署用户有访问资格。")
            prices.append({
                "provider": "nebius", "product_type": "gpu_instance", "gpu_model": platform["gpu_model"],
                "gpu_variant": platform["form_factor"], "vram_gb": platform["vram_gb"],
                "gpu_count": preset["gpu_count"], "raw_name": platform["platform_name"], "raw_sku": platform["platform_id"],
                "amount": _value(amount).rstrip("0").rstrip(".") or "0", "currency": rate["currency"],
                "unit": "gpu_hour", "billing_mode": rate["billing_mode"], "pricing_tier": "ordinary",
                "membership_required": False, "price_basis": "instance_total_allocated", "quote_status": "quoted",
                "quote_origin": "published_tariff_preset_calculation", "regions": [], "zones": [],
                "compute_countries": [], "geographic_scope": "platform_coverage", "price_scope": "platform_coverage",
                "region_price_verified": False, "coverage_regions": coverage,
                "coverage_countries": sorted({countries[region]["country_code"] for region in coverage}),
                "coverage_locations": [deepcopy(countries[region]) for region in coverage],
                "coverage_location_source": {"url": REGIONS_URL.removesuffix(".md"), "types_url": TYPES_URL.removesuffix(".md"),
                                             "basis": "platform_availability_not_region_price"},
                "selected_configuration": {"platform": platform["platform_id"], **deepcopy(preset)},
                "resources": {"vcpus": preset["vcpus"], "memory_gib": preset["memory_gib"]},
                "components": components,
                "instance_price": {"amount": _value(total), "currency": rate["currency"], "unit": "instance_hour",
                                   "scope": "compute_resources_only"},
                "normalization": {"formula": "sum(published hourly component rate * preset quantity) / gpu_count",
                                  "decimal_places": 12, "rounding": "ROUND_HALF_UP"},
                "rate_derivation": {"method": "computed_from_official_tariff",
                                    "rate_source": "published_resource_tariff", "independent_provider_quote": False,
                                    "source_rates": deepcopy(components),
                                    "equation": " + ".join(f"{c['quantity']} * {c['unit_price']}" for c in components)
                                                + f" = {_value(total)} {rate['currency']}/instance_hour; "
                                                + f"{_value(total)} / {preset['gpu_count']} = {_value(amount)} {rate['currency']}/gpu_hour"},
                "account_scope": "public_catalog", "tax_scope": tax_scope, "availability": "unknown",
                "observed_at": observed_at, "effective_from": rate["effective_from"], "effective_until": rate["effective_until"],
                "source_url": PUBLIC_URL, "source_type": SOURCE_TYPE, "configuration_source_url": TYPES_URL.removesuffix(".md"),
                "conditions": conditions,
                "notes": ["GPU-hour prices are preset compute-cost calculations, not a monthly price divided by hours.",
                          "Documented platform coverage is not an independently verified price in each region.",
                          "Storage and networking are charged separately; project eligibility, capacity and account discounts were not verified."],
            })
    return {"prices": prices, "platforms": platforms, "regions": countries,
            "source_rate_groups": deepcopy(rates), "published_minimums": minimums}


def expand_spot(spot_prices: list[dict], catalog: dict) -> tuple[list[dict], list[dict]]:
    """Apply a live SKU's GPU-hour price only to its own region/platform presets."""
    result, excluded = [], []
    if catalog["regions"]:
        spot_prices, country_gaps = nebius_regions.attach_spot_locations(spot_prices, catalog["regions"])
        excluded.extend({**gap, "reason": "spot_country_not_in_verified_live_directory"} for gap in country_gaps)
    for supplied in spot_prices:
        platform = catalog["platforms"].get(supplied.get("raw_sku"))
        actual_regions = supplied.get("regions")
        if not isinstance(actual_regions, list) or len(actual_regions) != 1:
            raise _invalid()
        region = actual_regions[0]
        if (supplied.get("unit") != "gpu_hour" or supplied.get("quote_status") != "quoted"
                or supplied.get("billing_mode") != "spot" or supplied.get("source_type") != "official_public_api"):
            raise _invalid()
        matching = ([preset for preset in platform["presets"] if region in preset["coverage_regions"]]
                    if platform else [])
        if not matching:
            excluded.append({"platform": supplied["raw_sku"], "region": region,
                             "reason": ("preset_region_not_in_documented_platform_catalog" if platform
                                        else "platform_not_in_documented_preset_catalog")})
            unexpanded = deepcopy(supplied)
            unexpanded["quote_origin"] = "reported_regional_spot_rate"
            unexpanded.setdefault("notes", []).append(
                "No VM preset was assumed because the public preset catalog does not yet bind this platform to the API's region.")
            result.append(unexpanded)
            continue
        for preset in matching:
            quote = deepcopy(supplied)
            quote.update(gpu_count=preset["gpu_count"], vram_gb=platform["vram_gb"],
                         gpu_variant=platform["form_factor"], quote_origin="regional_spot_preset_calculation",
                         price_basis="instance_total_allocated", selected_configuration={"platform": platform["platform_id"], **deepcopy(preset)},
                         resources={"vcpus": preset["vcpus"], "memory_gib": preset["memory_gib"]},
                         configuration_source_url=TYPES_URL.removesuffix(".md"))
            with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
                total = Decimal(quote["amount"]) * preset["gpu_count"]
            quote["components"] = [{"resource": "gpu", "unit_price": quote["amount"], "unit": "gpu_hour",
                                    "quantity": preset["gpu_count"], "amount": _value(total), "currency": quote["currency"]}]
            quote["instance_price"] = {"amount": _value(total), "currency": quote["currency"], "unit": "instance_hour",
                                       "scope": "compute_resources_only_at_current_spot_rate"}
            quote["normalization"] = {"formula": "current API GPU-hour price * preset GPU count / preset GPU count"}
            quote["rate_derivation"] = {"method": "computed_from_official_tariff", "rate_source": "current_regional_spot_api",
                                        "independent_provider_quote": False, "source_api_quote_count": 1,
                                        "source_api_region": region, "source_api_platform": supplied["raw_sku"],
                                        "source_rates": deepcopy(quote["components"]),
                                        "equation": f"{preset['gpu_count']} * {quote['amount']} = {_value(total)} {quote['currency']}/instance_hour; "
                                                    + f"{_value(total)} / {preset['gpu_count']} = {quote['amount']} {quote['currency']}/gpu_hour"}
            country = catalog["regions"].get(region)
            if country:
                quote["compute_countries"] = [country["country_code"]]
                # Keep the fresh country names, location provenance and private
                # access restriction attached before preset expansion.
                quote["location"].update(region=region, country_code=country["country_code"])
            quote["notes"] = [note for note in quote.get("notes", []) if "GPU quantity and VM configuration are not specified" not in note]
            quote["notes"].extend([
                "The API supplies a current regional GPU-hour SKU rate; the explicit preset and instance compute total are calculated using the official preset catalog.",
                "Storage and networking are charged separately; this is not a checkout quote or a capacity guarantee.",
            ])
            result.append(quote)
    return result, excluded


def collect_result(*, settings: Settings, observed_at: str, include_spot: bool = True,
                   website_quotes: list[dict] | None = None) -> dict:
    """Return full public preset calculations plus independent live Spot prices."""
    if type(include_spot) is not bool:
        raise _invalid()
    errors, excluded_spot, source_spot_count, raw_spot = [], [], 0, []
    catalog = {"prices": [], "platforms": {}, "regions": {}, "source_rate_groups": [], "published_minimums": []}
    try:
        catalog = calculate_catalog(fetch_text(SOURCE_URL, settings), fetch_text(TYPES_URL, settings),
                                    fetch_text(REGIONS_URL, settings), observed_at=observed_at)
    except FetchError as exc:
        errors.append({"source": "public_preset_catalog", "code": exc.code, "message": str(exc), "retryable": exc.retryable})
    except (ValueError, KeyError, TypeError):
        errors.append({"source": "public_preset_catalog", "code": "parse_failed",
                       "message": "Published preset/resource-tariff calculations could not be verified.", "retryable": False})
    prices = catalog["prices"]
    if include_spot:
        try:
            spot = nebius_spot.collect_quotes(settings=settings, observed_at=observed_at)
            source_spot_count = len(spot)
            raw_spot = (nebius_regions.attach_spot_locations(spot, catalog["regions"])[0]
                        if catalog["regions"] else deepcopy(spot))
            expanded, excluded_spot = expand_spot(spot, catalog)
            prices.extend(expanded)
        except FetchError as exc:
            errors.append({"source": "regional_spot_api", "code": exc.code, "message": str(exc), "retryable": exc.retryable})
        except (ValueError, KeyError, TypeError):
            errors.append({"source": "regional_spot_api", "code": "parse_failed",
                           "message": "Regional Spot preset calculations could not be verified.", "retryable": False})
    contacts = []
    try:
        website = (nebius_catalog.collect_quotes(settings=settings, observed_at=observed_at)
                   if website_quotes is None else website_quotes)
        if not isinstance(website, list) or any(not isinstance(q, dict) for q in website):
            raise _invalid()
        known_models = {item["gpu_model"] for item in catalog["platforms"].values()}
        contacts = [deepcopy(q) for q in website if q.get("quote_status") == "contact_sales"]
        # Preserve source rates for a newly advertised model with no public
        # preset; neither invent a configuration nor drop its contact-sales row.
        prices.extend(deepcopy(q) for q in website
                      if q.get("gpu_model") not in known_models or q.get("quote_status") == "contact_sales")
    except FetchError as exc:
        errors.append({"source": "website_catalog", "code": exc.code, "message": str(exc), "retryable": exc.retryable})
    except (ValueError, KeyError, TypeError):
        errors.append({"source": "website_catalog", "code": "parse_failed",
                       "message": "Additional website catalog/contact rows could not be verified.", "retryable": False})
    summary = {"platform_count": len(catalog["platforms"]),
                         "preset_count": sum(len(item["presets"]) for item in catalog["platforms"].values()),
                         "raw_exact_gpu_rate_count": len(catalog["source_rate_groups"]),
                         "raw_exact_resource_rate_count": sum(len(item["rows"]) for item in catalog["source_rate_groups"]),
                         "raw_document_gpu_rate_count": len(catalog["source_rate_groups"]) + len(catalog["published_minimums"]),
                         "raw_document_resource_rate_count": sum(len(item["rows"]) for item in catalog["source_rate_groups"]) + len(catalog["published_minimums"]),
                         "reported_spot_api_quote_count": source_spot_count,
                         "country_verified_spot_api_quote_count": sum(bool(q.get("compute_countries")) for q in raw_spot),
                         "spot_api_region_codes": sorted({r for q in raw_spot for r in q.get("regions", [])}),
                         "spot_api_country_codes": sorted({c for q in raw_spot for c in q.get("compute_countries", [])}),
                         "unexpanded_spot_api_quote_count": sum(q.get("quote_origin") == "reported_regional_spot_rate" for q in prices),
                         "catalog_calculation_count": sum(q.get("quote_origin") == "published_tariff_preset_calculation" for q in prices),
                         "regional_spot_calculation_count": sum(q.get("quote_origin") == "regional_spot_preset_calculation" for q in prices),
                         "contact_sales_row_count": len(contacts),
                         "published_spot_minimums_not_used_as_quotes": catalog["published_minimums"],
                         "unexpanded_spot_regions": excluded_spot}
    return {"prices": prices, "errors": errors, "status": ("partial" if prices else "failed") if errors else "ok",
            "coverage": summary,
            "catalog_coverage": {"summary": summary, "platforms": deepcopy(catalog["platforms"]),
                                 "regions": deepcopy(catalog["regions"]), "source_rate_groups": catalog["source_rate_groups"],
                                 "reported_spot_api_quotes": raw_spot,
                                 "contact_sales_rows": contacts, "types_source_url": TYPES_URL,
                                 "pricing_source_url": SOURCE_URL, "regions_source_url": REGIONS_URL},
            "gaps": [{"scope": "account_specific_and_contract_prices", "status": "authentication_required",
                      "login_url": "https://console.nebius.com", "api_url": ACCOUNT_API_URL,
                      "documentation_url": ACCOUNT_DOCUMENTATION_URL,
                      "requires": ["valid IAM Bearer token", "authorized per-region project IDs", "explicit resource specs"]},
                     *[{"scope": q.get("raw_name", q.get("gpu_model")), "status": "contact_sales",
                        "source_url": q.get("source_url"), "reason": "Official website requires sales contact; no numeric quote was manufactured."}
                       for q in contacts]]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    result = collect_result(settings=settings, observed_at=observed_at)
    if result["errors"]:
        raise FetchError("partial_collection", "One independent Nebius public source failed; inspect collect_result diagnostics.")
    return result["prices"]


def build_account_target_batches(catalog: dict, projects: list[dict], *, currency: str,
                                 boot_disk_gib: int, aggregation_units=("hour",), contract=False) -> list[list[dict]]:
    """Prepare explicit calculator targets for caller-authorized projects; no I/O.

    Callers must select a real billing currency and boot-disk size. Account
    estimates are performed by the existing nebius_quote adapter, not here.
    """
    from . import nebius_quote
    import json

    if (not isinstance(projects, list) or not projects or currency not in {"usd", "ils"}
            or type(boot_disk_gib) is not int or not 1 <= boot_disk_gib <= 65536 or type(contract) is not bool):
        raise _invalid()
    targets = []
    for project in projects:
        if not isinstance(project, dict) or set(project) != {"project_id", "region", "country_code"}:
            raise _invalid()
        region = project["region"]
        if catalog["regions"].get(region, {}).get("country_code") != project["country_code"]:
            raise _invalid()
        for platform in catalog["platforms"].values():
            for preset in platform["presets"]:
                if region not in preset["coverage_regions"]:
                    continue
                identity = platform["platform_id"] + "-" + preset["preset"]
                targets.append({**project, "gpu_model": platform["gpu_model"], "gpu_count": preset["gpu_count"],
                                "currency": currency, "aggregation_units": list(aggregation_units),
                                "offer_types": ["OFFER_TYPE_CONTRACT_PRICE"] if contract else [],
                                "resource_specs": [{"spec": {"@type": "type.googleapis.com/nebius.compute.v1.CreateInstanceRequest",
                                    "metadata": {"parentId": project["project_id"], "name": "pricing-" + identity},
                                    "spec": {"resources": {"platform": platform["platform_id"], "preset": preset["preset"]},
                                             "onDemand": {}, "bootDisk": {"attachMode": "READ_WRITE", "managedDisk": {
                                                 "name": "pricing-boot-" + identity,
                                                 "spec": {"type": "NETWORK_SSD", "sizeGibibytes": str(boot_disk_gib)}}}}}}]})
    if not targets:
        return []
    return [nebius_quote.validate_targets(json.dumps(targets[offset:offset + nebius_quote.MAX_TARGETS]))
            for offset in range(0, len(targets), nebius_quote.MAX_TARGETS)]
