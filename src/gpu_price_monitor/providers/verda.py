"""Parse Verda's public GPU-instance table, with separate currency pages.

Only GPU instances / On-demand is collected. Its Price and Spot price columns
are hourly instance totals, also stated explicitly in the official JSON-LD.
Instant clusters, confidential computing, CPU, serverless and reserved offers
have different terms and are deliberately outside this adapter's scope.
"""

from datetime import date
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import json
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..settings import Settings
from ..transport import fetch_text

SOURCE_URL = "https://verda.com/pricing"
SOURCE_TYPE = "public_page"
_CURRENCY_URLS = {currency: SOURCE_URL + "?currency=" + currency.lower() for currency in ("USD", "EUR")}
_HARDWARE = re.compile(r"([1248])x\s+(.+?)\s+(\d+)GB\Z")
_MEMORY = re.compile(r"(\d+) GB\Z")
_HEADERS = ["Hardware", "CPUs", "RAM", "GPU VRAM", "Price", "Spot price"]


def _invalid() -> ValueError:
    return ValueError("The Verda GPU pricing table, currency or instance-price unit was not recognized.")


def _text(element: Tag) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _currency(soup: BeautifulSoup) -> str:
    selected = soup.select('[data-component="currency-toggle"] [data-currency-link][aria-current="true"]')
    if len(selected) != 1:
        raise _invalid()
    query = parse_qs(urlparse(selected[0].get("href", "")).query)
    values = query.get("currency", [])
    if len(values) != 1 or values[0] not in ("usd", "eur"):
        raise _invalid()
    currency = values[0].upper()
    if _text(selected[0]) != ("$ USD" if currency == "USD" else "€ EUR"):
        raise _invalid()
    return currency


def _gpu_table(soup: BeautifulSoup) -> Tag:
    headings = soup.select("h2#gpu-instances")
    if len(headings) != 1 or _text(headings[0]) != "GPU instances":
        raise _invalid()
    subsection, tables = None, []
    for element in headings[0].next_elements:
        if not isinstance(element, Tag):
            continue
        if element.name == "h2":
            break
        if element.name == "h3":
            subsection = _text(element)
        if element.name == "table" and subsection == "On-demand":
            tables.append(element)
    if len(tables) != 1:
        raise _invalid()
    return tables[0]


def _price(text: str, currency: str) -> Decimal:
    symbol = "$" if currency == "USD" else "€"
    match = re.fullmatch(re.escape(symbol) + r"(\d+(?:\.\d+)?)/h", text)
    if not match or len(match[1]) > 32:
        raise _invalid()
    amount = Decimal(match[1])
    if not amount.is_finite() or not 0 < amount < Decimal("1e12"):
        raise _invalid()
    return amount


def _instance_offers(soup: BeautifulSoup) -> list[dict]:
    """Use provider metadata to verify these are hourly instance totals."""
    scripts = soup.find_all("script", type="application/ld+json")
    offers = []
    for script in scripts:
        raw = script.get_text()
        if len(raw) > 512 * 1024:
            raise _invalid()
        try:
            payload = json.loads(raw, parse_float=Decimal)
        except (ValueError, RecursionError):
            raise _invalid() from None
        if not isinstance(payload, dict):
            continue
        graph = payload.get("@graph", [])
        if not isinstance(graph, list) or len(graph) > 2000:
            raise _invalid()
        for item in graph:
            if (isinstance(item, dict) and item.get("@type") == "Offer"
                    and item.get("description") in {"Hourly on-demand instance price", "Hourly spot instance price"}):
                offers.append(item)
    if not offers:
        raise _invalid()
    return offers


def _verify_instance_offer(offers: list[dict], name: str, mode: str, currency: str, amount: Decimal) -> None:
    suffix = "on-demand" if mode == "on_demand" else "spot"
    description = f"Hourly {suffix} instance price"
    matching = [item for item in offers if item.get("name") == name + " " + suffix
                and item.get("description") == description and item.get("priceCurrency") == currency]
    for item in matching:
        value = item.get("price")
        unit = item.get("priceSpecification")
        if type(value) not in (int, Decimal) or not isinstance(unit, dict):
            continue
        unit_price = unit.get("price")
        if type(unit_price) not in (int, Decimal):
            continue
        if (Decimal(value) == amount == Decimal(unit_price) and unit.get("priceCurrency") == currency
                and unit.get("unitText") == "hour"):
            return
    raise _invalid()


def parse_prices(content: str, *, observed_at: str, as_of: date,
                 expected_currency: str | None = None) -> list[dict]:
    """Parse one currency page. Never infer price geography from the company."""
    soup = BeautifulSoup(content, "html.parser")
    currency = _currency(soup)
    if expected_currency is not None and currency != expected_currency:
        raise _invalid()
    table, offers = _gpu_table(soup), _instance_offers(soup)
    rows = table.find_all("tr")
    if len(rows) < 2 or [_text(cell) for cell in rows[0].find_all("th")] != _HEADERS:
        raise _invalid()
    result, seen = [], set()
    for row in rows[1:]:
        cells = [_text(cell) for cell in row.find_all("td")]
        if len(cells) != len(_HEADERS):
            raise _invalid()
        raw_name, raw_cpus, raw_ram, raw_vram, on_demand, spot = cells
        hardware, ram, vram = _HARDWARE.fullmatch(raw_name), _MEMORY.fullmatch(raw_ram), _MEMORY.fullmatch(raw_vram)
        if (not hardware or not ram or not vram or not re.fullmatch(r"[1-9]\d{0,4}", raw_cpus)
                or int(ram[1]) <= 0 or int(vram[1]) <= 0):
            raise _invalid()
        count, full_model, per_gpu_vram = int(hardware[1]), hardware[2], int(hardware[3])
        if per_gpu_vram <= 0 or int(vram[1]) not in {per_gpu_vram, per_gpu_vram * count}:
            raise _invalid()
        name = re.sub(r"^(?:NVIDIA|Tesla)\s+", "", full_model)
        variant = re.search(r"\s+(SXM\d+)\Z", name)
        model = name[:variant.start()] if variant else name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,63}", model):
            raise _invalid()
        identity = (raw_name, int(raw_cpus), int(ram[1]), int(vram[1]))
        if identity in seen:
            raise _invalid()
        seen.add(identity)
        for mode, raw_price in (("on_demand", on_demand), ("spot", spot)):
            total = _price(raw_price, currency)
            _verify_instance_offer(offers, raw_name, mode, currency, total)
            with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
                allocated = (total / count).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            if allocated <= 0:
                raise _invalid()
            amount = format(allocated, "f").rstrip("0").rstrip(".") or "0"
            notes = [
                "Published hourly instance list price; the per-GPU amount allocates the full listed configuration across its explicit GPU count.",
                "The GPU-instance pricing table does not state an applicable compute region or country; no geographic scope was inferred.",
                "Availability, account-specific discounts, tax and separately billed storage or networking were not verified.",
            ]
            if mode == "spot":
                notes.append("Spot pricing has separate capacity and interruption conditions; availability and interruption notice were not verified.")
            result.append({
                "provider": "verda", "product_type": "gpu_instance", "gpu_model": model.upper(),
                "gpu_variant": variant[1] if variant else None, "raw_name": raw_name,
                "raw_sku": f"{raw_name}|{raw_cpus}cpu|{ram[1]}GB-RAM|{vram[1]}GB-VRAM",
                "vram_gb": per_gpu_vram, "gpu_count": count,
                "amount": amount, "currency": currency, "unit": "gpu_hour",
                "billing_mode": mode, "price_basis": "instance_total_allocated", "quote_status": "quoted",
                "regions": [], "zones": [], "geographic_scope": "unspecified",
                "account_scope": "public_catalog", "tax_scope": "unspecified",
                "observed_at": observed_at, "effective_from": None, "effective_until": None,
                "source_url": _CURRENCY_URLS[currency], "source_type": SOURCE_TYPE, "availability": "unknown",
                "instance_price": {"amount": format(total, "f"), "currency": currency, "unit": "instance_hour"},
                "resources": {"cpu_count": int(raw_cpus), "ram_gb": int(ram[1]), "listed_gpu_vram_gb": int(vram[1])},
                "normalization": {"formula": "instance_price.amount / gpu_count", "decimal_places": 12, "rounding": "ROUND_HALF_UP"},
                "notes": notes,
            })
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Fetch each currency independently and reject currency-tab mismatches."""
    as_of = date.fromisoformat(observed_at[:10])
    quotes = []
    identities = None
    for currency, url in _CURRENCY_URLS.items():
        content = fetch_text(url, settings)
        prices = parse_prices(content, observed_at=observed_at, as_of=as_of, expected_currency=currency)
        current = {(q["raw_sku"], q["billing_mode"]) for q in prices}
        if identities is not None and current != identities:
            raise _invalid()
        identities = current
        quotes.extend(prices)
    return quotes
