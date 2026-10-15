"""Parse the public Nebius Compute pricing document.

The Markdown export is served by the official documentation site. Dates within
each currency table, rather than the page's position or last update, determine
which prices apply. This module performs no requests and needs no credentials.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re


SOURCE_URL = "https://docs.nebius.com/compute/resources/pricing.md"
PUBLIC_URL = "https://docs.nebius.com/compute/resources/pricing"

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"), 1
    )
}
_DATE_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?")
_TAB_RE = re.compile(
    r'<Tab\s+title=["\'](USD|ILS)["\']\s*>(.*?)</Tab>', re.DOTALL
)


def _plain(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    return value.replace("\\", "").replace("**", "").strip()


def _parse_date(value: str, inherited_year: int | None = None) -> date:
    match = _DATE_RE.fullmatch(value.strip())
    if not match or match[1] not in _MONTHS:
        raise ValueError("Nebius pricing has an unsupported effective date")
    year = int(match[3]) if match[3] else inherited_year
    if year is None:
        raise ValueError("Nebius pricing has an incomplete effective date")
    try:
        return date(year, _MONTHS[match[1]], int(match[2]))
    except ValueError as exc:
        raise ValueError("Nebius pricing has an invalid effective date") from exc


def _period(header: str) -> tuple[date | None, date | None]:
    """Return an inclusive start and exclusive end for an Item header."""
    label = _plain(header)
    if label == "Item":
        return None, None
    suffix = re.sub(r"^Item\s*[—–-]\s*", "", label)
    if suffix == label:
        raise ValueError("Nebius pricing table header changed")
    if suffix.startswith("before "):
        return None, _parse_date(suffix.removeprefix("before "))
    if suffix.startswith("from "):
        value = suffix.removeprefix("from ")
        if " until " in value:
            first, last = value.split(" until ", 1)
            end = _parse_date(last)
            start = _parse_date(first, end.year)
            if start >= end:
                raise ValueError("Nebius pricing has an invalid effective range")
            return start, end
        return _parse_date(value), None
    raise ValueError("Nebius pricing has an unsupported effective period")


def _table_rows(body: str, currency: str, as_of: date) -> list[dict]:
    rows = []
    period: tuple[date | None, date | None] | None = None
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [_plain(cell) for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            raise ValueError("Nebius pricing table columns changed")
        name, raw_price, unit = cells
        if all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
            continue
        if name.startswith("Item"):
            if raw_price != "Price" or unit != "Per":
                raise ValueError("Nebius pricing table columns changed")
            period = _period(name)
            continue
        if period is None:
            raise ValueError("Nebius pricing table is missing its header")
        start, end = period
        if (start is not None and as_of < start) or (end is not None and as_of >= end):
            continue
        if unit not in ("1 GPU hour", "1 CPU hour", "1 GiB hour"):
            raise ValueError("Nebius pricing has an unsupported resource unit")
        symbol = "$" if currency == "USD" else "₪"
        price_match = re.fullmatch(
            rf"(?P<starting>From\s+)?{re.escape(symbol)}(?P<amount>\d+(?:\.\d+)?)",
            raw_price,
        )
        if not price_match:
            raise ValueError("Nebius pricing has an unrecognized amount")
        try:
            amount = format(Decimal(price_match["amount"]), "f")
        except InvalidOperation as exc:
            raise ValueError("Nebius pricing has an invalid amount") from exc
        rows.append({
            "name": name, "amount": amount, "unit": unit,
            "starting": bool(price_match["starting"]),
            "billing_mode": "spot" if name.startswith("Preemptible ") else "on_demand",
            "effective_from": start.isoformat() if start else None,
            "effective_until": end.isoformat() if end else None,
        })
    return rows


def _model_and_variant(name: str) -> tuple[str, str | None]:
    name = re.sub(r"^Preemptible\s+", "", name)
    name = re.sub(r"\.\s*GPU$", "", name)
    name = re.sub(r"^NVIDIA[®™]?\s+", "", name)
    name = name.replace("®", "").replace("™", "").strip()
    model = re.fullmatch(r"(RTX PRO\s+\d+|[A-Z]+\d+[A-Z]*)(?:\s+(.+))?", name)
    if not model:
        raise ValueError("Nebius pricing has an unrecognized GPU name")
    return model[1], model[2]


def parse_prices(content: str, *, observed_at: str, as_of: date) -> list[dict]:
    """Return the document's GPU rates effective on ``as_of``.

    GPU quantity and VRAM remain unknown: a per-GPU rate does not document a
    particular VM configuration. USD/ILS selection describes the customer
    billing jurisdiction and is independent of compute-region availability.
    ``ValueError`` indicates an incompatible or unrecognizable source document.
    """
    section = re.search(
        r"^### Virtual machines[^\n]*\n(.*?)(?=^### |\Z)",
        content, re.MULTILINE | re.DOTALL,
    )
    if not section:
        raise ValueError("Nebius virtual-machine pricing section was not found")
    platforms = list(re.finditer(
        r"^#### (?P<title>NVIDIA[^\n]+)\n(?P<body>.*?)(?=^#### |\Z)",
        section[1], re.MULTILINE | re.DOTALL,
    ))
    if not platforms:
        raise ValueError("Nebius GPU pricing sections were not found")

    tax_scope = "excluded" if re.search(
        r"prices are shown without any applicable taxes", content, re.IGNORECASE
    ) else "unspecified"
    prices = []
    seen = set()
    for platform in platforms:
        title, body = platform["title"], platform["body"]
        preamble = body.split("<Tabs>", 1)[0]
        regions = list(dict.fromkeys(re.findall(r"`([a-z]{2}-[a-z]+\d+)`", preamble)))
        raw_sku_match = re.search(r"\b(gpu-[a-z0-9-]+)\b", title)
        raw_sku = raw_sku_match[1] if raw_sku_match else None
        tabs = list(_TAB_RE.finditer(body))
        if not tabs:
            raise ValueError("Nebius GPU currency tables were not found")
        if not re.search(r"\|\s*1 GPU hour\s*\|", body):
            raise ValueError("Nebius GPU resource rows were not found")
        for tab in tabs:
            currency = tab[1]
            rows = _table_rows(tab[2], currency, as_of)
            for row in rows:
                if row["unit"] != "1 GPU hour":
                    continue
                gpu_model, gpu_variant = _model_and_variant(row["name"])
                component = bool(re.search(r"\.\s*GPU$", row["name"]))
                key = (title, currency, row["billing_mode"])
                if key in seen:
                    raise ValueError("Nebius pricing has overlapping effective rates")
                seen.add(key)
                notes = [
                    "Published platform availability is not a region-specific price quote.",
                    ("USD prices apply to customers except companies from Israel."
                     if currency == "USD"
                     else "ILS prices apply to companies from Israel; this is not a compute-region restriction."),
                ]
                if row["billing_mode"] == "spot":
                    notes.append("Preemptible capacity; interruption conditions apply.")
                if row["starting"]:
                    notes.append("Published minimum spot price; the live dynamic quote may be higher.")
                if component:
                    notes.append("GPU component only; CPU and RAM are billed separately.")
                if "Private region" in preamble:
                    notes.append("The platform's region list includes a private-region footnote; access may be restricted.")
                components = [
                    {
                        "resource": "cpu" if item["unit"] == "1 CPU hour" else "ram",
                        "amount": item["amount"], "currency": currency,
                        "unit": "cpu_hour" if item["unit"] == "1 CPU hour" else "gib_hour",
                    }
                    for item in rows
                    if item["billing_mode"] == row["billing_mode"]
                    and item["unit"] in ("1 CPU hour", "1 GiB hour")
                ] if component else []
                prices.append({
                    "provider": "nebius", "product_type": "gpu_instance", "gpu_model": gpu_model,
                    "raw_name": row["name"], "raw_sku": raw_sku,
                    "gpu_variant": gpu_variant, "vram_gb": None, "gpu_count": None,
                    "amount": row["amount"], "currency": currency, "unit": "gpu_hour",
                    "billing_mode": row["billing_mode"],
                    "price_basis": ("starting_price" if row["starting"] else
                                    "gpu_component" if component else "advertised_per_gpu"),
                    "quote_status": "starting_at" if row["starting"] else "quoted",
                    "regions": regions, "geographic_scope": "regions" if regions else "unspecified",
                    "account_scope": "public_catalog", "tax_scope": tax_scope,
                    "observed_at": observed_at,
                    "effective_from": row["effective_from"], "effective_until": row["effective_until"],
                    "source_url": PUBLIC_URL, "source_type": "official_pricing_document",
                    "availability": "unknown", "notes": notes,
                    "components": components,
                })
    if not prices:
        raise ValueError("Nebius has no effective GPU prices")
    return prices
