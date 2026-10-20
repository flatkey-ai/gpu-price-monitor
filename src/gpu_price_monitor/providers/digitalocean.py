"""Parse key-free DigitalOcean GPU Droplet list prices.

The two GPU tables quote complete Droplet plans, not GPU components. The
provider documents single-GPU and 8-GPU configurations; the ``(8x)`` suffix
identifies the latter. Resource specifications and geography are deliberately
not joined from unrelated availability or marketing pages.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Context, Decimal, localcontext

from bs4 import BeautifulSoup
from bs4.element import Tag

SOURCE_URL = "https://docs.digitalocean.com/products/droplets/details/pricing/"
SOURCE_TYPE = "public_documentation"
GPU_COUNT_SOURCE_URL = "https://docs.digitalocean.com/products/droplets/how-to/gpu/create/"
CURRENCY_SOURCE_URL = "https://docs.digitalocean.com/reference/api/reference/sizes/"

_SECTIONS = (
    ("on-demand-gpu-droplet-pricing", "on_demand"),
    ("spot-gpu-droplet-pricing", "spot"),
)
_PRICE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?) per hour")
_GPU = re.compile(r"(AMD|NVIDIA) ([A-Za-z0-9][A-Za-z0-9 -]*?)(?:, (air-cooled|liquid-cooled))?(?: \((8)x\))?")
_MONTHS = dict(zip("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), range(1, 13)))


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
            total = Decimal(price.group(1))
            if total <= 0:
                raise ValueError("DigitalOcean GPU price must be positive")
            with localcontext(Context(prec=max(50, len(price.group(1)) + 10))):
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
