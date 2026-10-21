"""Parse Lambda's key-free instance and reserved-cluster price tables.

GPU counts come from the accessible tab/panel association, not table order.
The advertised amount is per GPU; its complete-instance total is computed
separately. Published resource units are retained without GB/GiB conversion.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Context, Decimal, localcontext

from bs4 import BeautifulSoup

SOURCE_URL = "https://lambda.ai/pricing"
SOURCE_TYPE = "public_page"
CURRENCY_SOURCE_URL = "https://docs.lambda.ai/api/cloud"

_COLUMNS = ("PLAN", "VRAM/GPU", "VCPUS", "RAM", "STORAGE", "PRICE/GPU/HR*")
_GPU_COUNT = re.compile(r"([1-9]\d*)x", re.IGNORECASE)
_INTEGER = re.compile(r"[1-9]\d*")
_VRAM = re.compile(r"([1-9]\d*) GB")
_RAM = re.compile(r"([1-9]\d*) GiB")
_STORAGE = re.compile(r"([1-9]\d*(?:\.\d+)?) (GiB|TiB) SSD")
_PRICE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
_VARIANT = re.compile(r"\b(?:SXM\d*|PCIe|NVLink|HGX)\b", re.IGNORECASE)
_FOOTNOTE = "* plus applicable sales tax/VAT/GST"


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _gpu_fields(raw_name: str) -> tuple[str, str | None]:
    name = re.sub(r"^(?:NVIDIA|AMD)\s+", "", raw_name, flags=re.IGNORECASE)
    if name == raw_name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .-]*", name):
        raise ValueError("Lambda public GPU description changed")
    variants = _VARIANT.findall(name)
    if len(variants) > 1:
        raise ValueError("Lambda public GPU variant is ambiguous")
    model = " ".join(_VARIANT.sub("", name).split()).upper()
    if not model:
        raise ValueError("Lambda public GPU description has no model")
    return model, variants[0] if variants else None


def _tables(section) -> list[tuple[int, object]]:
    """Validate both directions of ARIA links and read their explicit counts."""
    tablists = section.find_all(attrs={"role": "tablist"})
    panels = section.find_all(attrs={"role": "tabpanel"})
    tables = section.find_all("table")
    if len(tablists) != 1 or len(panels) != 4 or len(tables) != 4:
        raise ValueError("Lambda public pricing tab structure changed")
    tabs = tablists[0].find_all(attrs={"role": "tab"})
    if len(tabs) != 4:
        raise ValueError("Lambda public pricing GPU counts changed")
    result, counts, used_panels = [], set(), set()
    for tab in tabs:
        match = _GPU_COUNT.fullmatch(_text(tab))
        if not match:
            raise ValueError("Lambda public pricing tab has no explicit GPU count")
        count = int(match.group(1))
        tab_id, panel_id = tab.get("id"), tab.get("aria-controls")
        if not isinstance(tab_id, str) or not tab_id or not isinstance(panel_id, str) or not panel_id:
            raise ValueError("Lambda public pricing tab association changed")
        # Duplicate IDs make an otherwise valid-looking relationship ambiguous.
        if len(section.find_all(id=tab_id)) != 1 or len(section.find_all(id=panel_id)) != 1:
            raise ValueError("Lambda public pricing tab association is ambiguous")
        linked = [panel for panel in panels if panel.get("id") == panel_id]
        if len(linked) != 1 or linked[0].get("aria-labelledby") != tab_id:
            raise ValueError("Lambda public pricing panel association changed")
        panel = linked[0]
        panel_tables = panel.find_all("table")
        footnotes = panel.select(".table-footer")
        if (len(panel_tables) != 1 or len(footnotes) != 1
                or _text(footnotes[0]) != _FOOTNOTE):
            raise ValueError("Lambda public pricing table or tax footnote changed")
        if count in counts or panel_id in used_panels:
            raise ValueError("Lambda public pricing GPU counts are ambiguous")
        counts.add(count)
        used_panels.add(panel_id)
        result.append((count, panel_tables[0]))
    if counts != {1, 2, 4, 8}:
        raise ValueError("Lambda public pricing GPU counts changed")
    return result


def parse_prices(content: str, *, observed_at: str, as_of: date | None = None) -> list[dict]:
    """Return public list prices or fail the whole source on ambiguous markup.

    ``as_of`` is accepted for the shared public-page interface. This source has
    no effective dates. USD follows the provider's documented price convention;
    it does not imply a compute country, sales country, region, or tax amount.
    """
    soup = BeautifulSoup(content, "html.parser")
    headings = [
        heading for heading in soup.find_all(re.compile(r"^h[1-6]$"))
        if _text(heading).casefold() in {"pay by the minute", "instances pricing"}
    ]
    if len(headings) != 1:
        raise ValueError("Lambda public on-demand pricing section was not uniquely identified")
    section = headings[0].find_parent("section")
    if section is None:
        raise ValueError("Lambda public on-demand pricing section changed")
    result, seen = [], set()
    for gpu_count, table in _tables(section):
        header_rows = table.select("thead > tr")
        bodies = table.find_all("tbody", recursive=False)
        if len(header_rows) != 1 or len(bodies) != 1:
            raise ValueError("Lambda public price table structure changed")
        headers = header_rows[0].find_all(["th", "td"], recursive=False)
        if (any(cell.name != "th" or cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in headers)
                or tuple(_text(cell).upper() for cell in headers) != _COLUMNS):
            raise ValueError("Lambda public price table columns changed")
        rows = bodies[0].find_all("tr", recursive=False)
        if not rows:
            raise ValueError("Lambda public price table contains no rows")
        for row in rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if (len(cells) != len(_COLUMNS) or cells[0].name != "th"
                    or any(cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells)):
                raise ValueError("Lambda public price row structure changed")
            if tuple(str(cell.get("data-label", "")).upper() for cell in cells) != _COLUMNS:
                raise ValueError("Lambda public price row labels changed")
            raw_name, vram_text, cpu_text, ram_text, disk_text, price_text = map(_text, cells)
            if row.get("data-plan") != raw_name:
                raise ValueError("Lambda public price row has inconsistent GPU names")
            model, variant = _gpu_fields(raw_name)
            vram = _VRAM.fullmatch(vram_text)
            ram = _RAM.fullmatch(ram_text)
            disk = _STORAGE.fullmatch(disk_text)
            price = _PRICE.fullmatch(price_text)
            if not (vram and _INTEGER.fullmatch(cpu_text) and ram and disk and price):
                raise ValueError("Lambda public price or resource unit changed")
            amount = Decimal(price.group(1))
            if amount <= 0:
                raise ValueError("Lambda public price must be positive")
            with localcontext(Context(prec=max(50, len(price.group(1)) + len(str(gpu_count)) + 10))):
                instance_amount = amount * gpu_count
            vram_gb = int(vram.group(1))
            identity = (model, variant, vram_gb, gpu_count)
            if identity in seen:
                raise ValueError("Lambda public price table contains ambiguous duplicate rows")
            seen.add(identity)
            result.append({
                "provider": "lambda",
                "product_type": "gpu_instance",
                "product_line": "On-Demand Cloud",
                "price_record_kind": "published_price",
                "configuration_expansion": False,
                "gpu_model": model,
                "raw_name": raw_name,
                "raw_sku": None,
                "gpu_variant": variant,
                "vram_gb": vram_gb,
                "gpu_count": gpu_count,
                "amount": format(amount, "f"),
                "currency": "USD",
                "unit": "gpu_hour",
                "billing_mode": "on_demand",
                "price_basis": "advertised_per_gpu",
                "quote_status": "quoted",
                "instance_price": {
                    "amount": format(instance_amount, "f"),
                    "currency": "USD",
                    "unit": "instance_hour",
                },
                "resources": {
                    "vcpus": int(cpu_text),
                    "memory_gib": int(ram.group(1)),
                    "storage": {"amount": disk.group(1), "unit": disk.group(2), "type": "SSD"},
                },
                "regions": [],
                "geographic_scope": "unspecified",
                "account_scope": "public_catalog",
                "tax_scope": "excluded",
                "observed_at": observed_at,
                "effective_from": None,
                "effective_until": None,
                "source_url": SOURCE_URL,
                "source_type": SOURCE_TYPE,
                "currency_source_url": CURRENCY_SOURCE_URL,
                "availability": "unknown",
                "notes": [
                    "Advertised per-GPU hourly rate for a complete bundled instance; listed CPU, RAM and storage describe the whole instance.",
                    "Instance hourly total is computed from the advertised per-GPU rate and the explicitly labeled GPU count.",
                    "USD denomination follows the provider's documented cloud price convention; the page displays dollar amounts.",
                    "The source excludes applicable sales tax/VAT/GST and does not state a region, sales country or tax amount.",
                    "Public catalog; availability, orderability and account-specific discounts were not verified.",
                ],
            })
    if _text(headings[0]).casefold() == "instances pricing":
        from . import lambda_clusters
        result.extend(lambda_clusters.parse_prices(content, observed_at=observed_at, source_url=SOURCE_URL))
    return result
