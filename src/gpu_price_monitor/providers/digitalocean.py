"""Collect public GPU Droplet prices and strictly matched product specifications.

The price tables quote complete Droplet plans, not GPU components. The product
page supplies plan slugs and hardware for a subset of those same priced plans.
Neither page establishes account availability or a price location.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Context, Decimal, DecimalException, localcontext

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..settings import Settings
from ..transport import FetchError, fetch_text

SOURCE_URL = "https://docs.digitalocean.com/products/droplets/details/pricing/"
SOURCE_TYPE = "public_documentation"
GPU_COUNT_SOURCE_URL = "https://docs.digitalocean.com/products/droplets/how-to/gpu/create/"
CURRENCY_SOURCE_URL = "https://docs.digitalocean.com/reference/api/reference/sizes/"
PRODUCTS_URL = "https://www.digitalocean.com/products/gpu-droplets"

_SECTIONS = (
    ("on-demand-gpu-droplet-pricing", "on_demand"),
    ("spot-gpu-droplet-pricing", "spot"),
)
_PRICE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?) per hour")
_GPU = re.compile(r"(AMD|NVIDIA) ([A-Za-z0-9][A-Za-z0-9 -]*?)(?:, (air-cooled|liquid-cooled))?(?: \((8)x\))?")
_MONTHS = dict(zip("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), range(1, 13)))
_PRODUCT_IDENTITIES = {
    "AMD MI300X": ("AMD Instinct™ MI300X", "mi300"),
    "AMD MI325X": ("AMD Instinct™ MI325X", "mi325"),
    "NVIDIA H100": ("NVIDIA HGX H100", "h100"),
    "NVIDIA H200": ("NVIDIA HGX H200", "h200"),
    "NVIDIA L40s": ("NVIDIA L40S", "l40s"),
    "NVIDIA RTX 4000": ("NVIDIA RTX 4000 Ada Generation", "rtx4000"),
    "NVIDIA RTX 6000": ("NVIDIA RTX 6000 Ada Generation", "rtx6000"),
}
_SKU = re.compile(r"gpu-([a-z0-9]+?)x([1-9][0-9]*)-([1-9][0-9]*)gb")


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _section_table(main, section_id: str):
    headings = main.find_all(id=section_id)
    if len(headings) != 1 or headings[0].name != "h2":
        raise ValueError("DigitalOcean GPU price section was not uniquely identified")
    tables = []
    for sibling in headings[0].next_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name == "h2":
            break
        if sibling.name == "table":
            tables.append(sibling)
        else:
            tables.extend(sibling.find_all("table"))
    if len(tables) != 1:
        raise ValueError("DigitalOcean GPU price section must contain one table")
    return tables[0]


def _last_verified(main) -> str | None:
    matches = []
    for element in main.find_all("p"):
        match = re.fullmatch(r"Last verified ([0-9]{1,2}) ([A-Za-z]{3}) ([0-9]{4})", _text(element))
        if match:
            month = _MONTHS.get(match.group(2))
            if month is None:
                raise ValueError("DigitalOcean documentation verification date changed")
            matches.append(date(int(match.group(3)), month, int(match.group(1))).isoformat())
    if len(matches) > 1:
        raise ValueError("DigitalOcean documentation verification date is ambiguous")
    return matches[0] if matches else None


def parse_prices(content: str, *, observed_at: str, as_of: date | None = None) -> list[dict]:
    """Return on-demand and spot public plan rates; fail on ambiguous rows.

    ``as_of`` is accepted for the shared parser interface. The documentation
    verification date is metadata, never a price effective date. Spot rates are
    the published snapshot and may change daily; no stock request is made.
    """
    soup = BeautifulSoup(content, "html.parser")
    mains = soup.find_all("main")
    if len(mains) != 1:
        raise ValueError("DigitalOcean pricing document was not uniquely identified")
    main = mains[0]
    verified = _last_verified(main)
    result, seen = [], set()
    for section_id, billing_mode in _SECTIONS:
        table = _section_table(main, section_id)
        header_rows = table.select("thead > tr")
        bodies = table.find_all("tbody", recursive=False)
        if len(header_rows) != 1 or len(bodies) != 1:
            raise ValueError("DigitalOcean GPU price table structure changed")
        headers = header_rows[0].find_all(["th", "td"], recursive=False)
        if (tuple(_text(cell) for cell in headers) != ("GPU", "Price")
                or any(cell.name != "th" or cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in headers)):
            raise ValueError("DigitalOcean GPU price table columns changed")
        rows = bodies[0].find_all("tr", recursive=False)
        if not rows:
            raise ValueError("DigitalOcean GPU price table is empty")
        for row in rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if (len(cells) != 2 or any(cell.name != "td" or cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells)):
                raise ValueError("DigitalOcean GPU price row structure changed")
            raw_name, price_text = map(_text, cells)
            gpu, price = _GPU.fullmatch(raw_name), _PRICE.fullmatch(price_text)
            if not gpu or not price:
                raise ValueError("DigitalOcean GPU description or hourly price changed")
            vendor, model, variant, explicit_count = gpu.groups()
            model = model.upper()
            gpu_count = int(explicit_count) if explicit_count else 1
            identity = (billing_mode, vendor, model, variant, gpu_count)
            if identity in seen:
                raise ValueError("DigitalOcean GPU price table has duplicate configurations")
            seen.add(identity)
            price_number = price.group(1)
            if len(price_number) > 64:
                raise ValueError("DigitalOcean GPU price precision is invalid")
            total = Decimal(price_number)
            if total <= 0:
                raise ValueError("DigitalOcean GPU price must be positive")
            if total.adjusted() > 12 or total.as_tuple().exponent < -50:
                raise ValueError("DigitalOcean GPU price magnitude or precision is invalid")
            # Construct an independent context: a caller can enable traps or
            # restrict Emax/Emin without changing a public catalog amount.
            with localcontext(Context(prec=max(50, len(price_number) + 10))):
                amount = total / gpu_count
            notes = [
                "The published hourly rate is for a complete GPU Droplet plan; the normalized rate divides its instance total by GPU count.",
                "The (8x) suffix identifies eight GPUs; unsuffixed plans contain one GPU under the provider's documented single-GPU and 8-GPU configurations.",
                "The dollar denomination follows the provider's documented USD Droplet price convention.",
                "This pricing table does not state plan CPU, RAM, VRAM, storage, regions, zones, sales country or applicable taxes.",
                "Public list price; availability, account eligibility and orderability were not verified. Additional outbound transfer can incur charges.",
            ]
            if billing_mode == "spot":
                notes.append("Spot GPU Droplets are in public preview; their published prices may change daily and instances may be reclaimed.")
            result.append({
                "provider": "digitalocean",
                "product_type": "gpu_instance",
                "gpu_model": model,
                "gpu_vendor": vendor,
                "raw_name": raw_name,
                "raw_sku": None,
                "gpu_variant": variant,
                "vram_gb": None,
                "gpu_count": gpu_count,
                "amount": format(amount, "f"),
                "currency": "USD",
                "unit": "gpu_hour",
                "billing_mode": billing_mode,
                "price_basis": "instance_total_allocated",
                "quote_status": "quoted",
                "instance_price": {"amount": format(total, "f"), "currency": "USD", "unit": "instance_hour"},
                "resources": {},
                "regions": [],
                "zones": [],
                "geographic_scope": "unspecified",
                "account_scope": "public_catalog",
                "tax_scope": "unspecified",
                "observed_at": observed_at,
                "effective_from": None,
                "effective_until": None,
                "source_url": SOURCE_URL + "#" + section_id,
                "source_type": SOURCE_TYPE,
                "source_last_verified": verified,
                "gpu_count_source_url": GPU_COUNT_SOURCE_URL,
                "currency_source_url": CURRENCY_SOURCE_URL,
                "availability": "unknown",
                "preview": billing_mode == "spot",
                "notes": notes,
            })
    return result


def parse_product_plans(content: str) -> list[dict]:
    """Read the official product page's single embedded GPU plan catalog.

    The Next Flight script is JSON wrapped in a push call. Decode that wrapper
    before reading its nested plan object; never use substring regexes as a
    source of plan values.
    """
    soup = BeautifulSoup(content, "html.parser")
    scripts = [script.get_text() for script in soup.find_all("script")
               if "gpuDropletsData" in script.get_text()]
    if len(scripts) != 1:
        raise ValueError("DigitalOcean GPU product catalog was not uniquely identified")
    script = scripts[0].strip()
    prefix = "self.__next_f.push("
    if not script.startswith(prefix):
        raise ValueError("DigitalOcean GPU product catalog wrapper changed")
    wrapper, offset = json.JSONDecoder().raw_decode(script[len(prefix):])
    if script[len(prefix) + offset:].strip() != ")" or not isinstance(wrapper, list) or len(wrapper) != 2 or wrapper[0] != 1 or not isinstance(wrapper[1], str):
        raise ValueError("DigitalOcean GPU product catalog wrapper changed")
    payload = wrapper[1]
    marker = '"gpuDropletsData":'
    if payload.count(marker) != 1:
        raise ValueError("DigitalOcean GPU product catalog was ambiguous")
    catalog, _ = json.JSONDecoder(parse_float=Decimal).raw_decode(
        payload[payload.index(marker) + len(marker):])
    if not isinstance(catalog, dict) or not isinstance(catalog.get("plans"), list) or not catalog["plans"]:
        raise ValueError("DigitalOcean GPU product plans were not found")
    return catalog["plans"]


def _positive_int(value) -> bool:
    return type(value) is int and value > 0


def _matched_hardware(quote: dict, plan: dict) -> dict | None:
    identity = _PRODUCT_IDENTITIES.get(quote["raw_name"].replace(" (8x)", ""))
    if identity is None or not isinstance(plan, dict):
        return None
    count = quote["gpu_count"]
    description, sku_model = identity
    if plan.get("description") != description + ("×8" if count == 8 else ""):
        return None
    slug = plan.get("slug")
    sku = _SKU.fullmatch(slug) if isinstance(slug, str) else None
    gpu, disk, price = plan.get("gpu"), plan.get("disk"), plan.get("price")
    variant = gpu.get("variant", 1) if isinstance(gpu, dict) else None
    if (sku is None or sku.group(1) != sku_model or int(sku.group(2)) != count
            or not isinstance(gpu, dict) or not isinstance(disk, dict) or not isinstance(price, dict)
            or not all(_positive_int(plan.get(field)) for field in ("cpus", "memory"))
            or not _positive_int(gpu.get("memory")) or not _positive_int(disk.get("boot"))
            or ("scratch" in disk and not _positive_int(disk["scratch"]))
            or not _positive_int(variant) or variant != count
            or gpu["memory"] != int(sku.group(3))
            or gpu["memory"] % count != 0):
        return None
    hourly = price.get("hourly")
    if type(hourly) not in (int, Decimal) or Decimal(hourly) != Decimal(quote["instance_price"]["amount"]):
        return None
    resources = {"vcpus": plan["cpus"], "memory_gib": plan["memory"],
                 "storage_gib": disk["boot"]}
    if "scratch" in disk:
        resources["scratch_storage_gib"] = disk["scratch"]
    return {"raw_sku": slug, "vram_gb": gpu["memory"] // count,
            "resources": resources, "hardware_source_url": PRODUCTS_URL}


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Keep price evidence even when the separate product catalog is incomplete."""
    pricing = fetch_text(SOURCE_URL, settings, headers={"Accept": "text/html"})
    prices = parse_prices(pricing, observed_at=observed_at)
    try:
        products = fetch_text(PRODUCTS_URL, settings, headers={"Accept": "text/html"})
        plans = parse_product_plans(products)
    except (FetchError, ValueError, TypeError, KeyError, DecimalException) as exc:
        error = ({"code": exc.code, "message": str(exc), "retryable": exc.retryable}
                 if isinstance(exc, FetchError) else
                 {"code": "parse_failed", "message": "The GPU product catalog structure was not recognized.", "retryable": False})
        return {"prices": prices, "status": "partial", "errors": [{"source_url": PRODUCTS_URL, **error}],
                "catalog_coverage": {"priced_plan_count": len(prices), "matched_sku_count": 0,
                                     "product_catalog_status": "unavailable"}}
    gaps = []
    for quote in prices:
        if quote["billing_mode"] != "on_demand":
            continue  # Spot prices are not ordinary on-demand size identities.
        matches = [hardware for plan in plans
                   if (hardware := _matched_hardware(quote, plan)) is not None]
        if len(matches) == 1:
            quote.update(matches[0])
            quote["notes"].append("The separate official product catalog identifies this exact on-demand plan's SKU, CPU, RAM, per-GPU VRAM, boot disk and optional scratch disk; RAM and disk values are GiB.")
        else:
            gaps.append({"scope": "on_demand_gpu_plan_sku", "status": "unverified",
                         "raw_name": quote["raw_name"], "gpu_count": quote["gpu_count"],
                         "reason": "No unique product plan matched description, GPU count, exact hourly total and internally consistent SKU hardware."})
    matched = sum(q["raw_sku"] is not None for q in prices)
    errors = ([{"source_url": PRODUCTS_URL, "code": "catalog_identity_gap",
                "message": "Some priced GPU plans have no uniquely verified product SKU.", "retryable": False}]
              if gaps else [])
    return {"prices": prices, "status": "partial" if gaps else "ok", "errors": errors, "gaps": gaps,
            "catalog_coverage": {"priced_plan_count": len(prices), "on_demand_plan_count": sum(
                q["billing_mode"] == "on_demand" for q in prices), "matched_sku_count": matched,
                "product_catalog_status": "available"}}
