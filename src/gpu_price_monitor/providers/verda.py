"""Parse Verda's public GPU-instance table, with separate currency pages.

GPU instances, confidential-computing instances, and explicitly sized instant
clusters are collected. Instance units are verified against official JSON-LD;
the visible cluster per-GPU tariff is retained when structured totals differ.
CPU, serverless, and percentage-only reserved discounts are outside this scope.
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


def _section_tables(soup: BeautifulSoup, section: str, title: str) -> dict[str, Tag]:
    headings = soup.select("h2#" + section)
    if not headings:
        return {}
    if len(headings) != 1 or _text(headings[0]) != title:
        raise _invalid()
    subsection, tables = None, {}
    for element in headings[0].next_elements:
        if not isinstance(element, Tag):
            continue
        if element.name == "h2":
            break
        if element.name == "h3":
            subsection = _text(element)
        if element.name == "table" and subsection in {"On-demand", "Confidential computing"}:
            if subsection in tables:
                raise _invalid()
            tables[subsection] = element
    return tables


def _gpu_table(soup: BeautifulSoup) -> Tag:
    table = _section_tables(soup, "gpu-instances", "GPU instances").get("On-demand")
    if table is None:
        raise _invalid()
    return table


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
                    and item.get("description") in {"Hourly on-demand instance price", "Hourly spot instance price",
                                                     "Hourly instant cluster price"}):
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
        # The page rounds some displayed prices (11.13 vs metadata 11.1275).
        # Check consistency at the actual displayed precision, then retain the
        # visible table amount rather than silently replacing it with metadata.
        with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
            agrees = Decimal(value).quantize(Decimal(1).scaleb(amount.as_tuple().exponent)) == amount
        if (Decimal(value) == Decimal(unit_price) and agrees and unit.get("priceCurrency") == currency
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
    offers = _instance_offers(soup)
    instance_tables = _section_tables(soup, "gpu-instances", "GPU instances")
    if "On-demand" not in instance_tables:
        raise _invalid()
    result = []
    for section, table in instance_tables.items():
        result.extend(_parse_instance_table(table, offers, currency=currency, observed_at=observed_at,
                                           confidential=section == "Confidential computing"))
    clusters = _section_tables(soup, "instant-clusters", "Instant clusters")
    if clusters:
        if set(clusters) != {"On-demand"}:
            raise _invalid()
        result.extend(_parse_clusters(clusters["On-demand"], offers, currency=currency, observed_at=observed_at))
    return result


def _parse_instance_table(table, offers, *, currency, observed_at, confidential=False):
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
        if bool(re.search(r"\bCC\b", full_model)) != confidential:
            raise _invalid()
        name = re.sub(r"\bCC\b", "", re.sub(r"^(?:NVIDIA|Tesla)\s+", "", full_model)).strip()
        name = " ".join(name.split())
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
                **({"cloud_tier": "confidential_computing",
                    "conditions": {"confidential_computing": True,
                                   "product_variant": "GPU instances / Confidential computing"}}
                   if confidential else {}),
            })
    return result


def _parse_clusters(table, offers, *, currency, observed_at):
    """Read explicit cluster counts/totals; never invent a one-GPU cluster.

    The visible table states per-GPU resources and reference price. JSON-LD
    separately publishes exact cluster sizes, with totals that can differ from
    the visible per-GPU tariff. Preserve that evidence but never substitute the
    inconsistent metadata total for the user's visible price or fabricate a
    checkout total from it.
    """
    rows = table.find_all("tr")
    if len(rows) < 2 or [_text(c) for c in rows[0].find_all("th")] != _HEADERS[:4] + ["Price (1x GPU)"]:
        raise _invalid()
    result, seen_models, seen_offers = [], set(), set()
    for row in rows[1:]:
        cells = [_text(c) for c in row.find_all("td")]
        if len(cells) != 5:
            raise _invalid()
        hardware_name, raw_cpu, raw_ram, raw_vram, raw_price = cells
        hardware = _HARDWARE.fullmatch("1x " + hardware_name)
        ram, vram = _MEMORY.fullmatch(raw_ram), _MEMORY.fullmatch(raw_vram)
        if (not hardware or not ram or not vram or not re.fullmatch(r"[1-9]\d{0,4}", raw_cpu)
                or int(ram[1]) <= 0 or int(vram[1]) != int(hardware[3]) or hardware_name in seen_models):
            raise _invalid()
        seen_models.add(hardware_name)
        reference = _price(raw_price, currency)
        full_model = re.sub(r"^(?:NVIDIA|Tesla)\s+", "", hardware[2])
        variant = re.search(r"\s+(SXM\d+)\Z", full_model)
        model = full_model[:variant.start()] if variant else full_model
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,63}", model):
            raise _invalid()
        matching = []
        for offer in offers:
            if offer.get("description") != "Hourly instant cluster price" or offer.get("priceCurrency") != currency:
                continue
            match = re.fullmatch(r"([1-9]\d{0,3})x " + re.escape(hardware_name) + r" instant cluster", str(offer.get("name", "")))
            if match:
                matching.append((int(match[1]), offer))
        if not matching:
            raise _invalid()
        for count, offer in matching:
            unit, value = offer.get("priceSpecification"), offer.get("price")
            identity = hardware_name, count
            if (identity in seen_offers or count < 2 or count > 1024 or type(value) not in (int, Decimal)
                    or not isinstance(unit, dict) or type(unit.get("price")) not in (int, Decimal)
                    or Decimal(unit["price"]) != Decimal(value) or unit.get("priceCurrency") != currency
                    or unit.get("unitText") != "hour"):
                raise _invalid()
            seen_offers.add(identity)
            total = Decimal(value)
            if not total.is_finite() or not 0 < total < Decimal("1e12"):
                raise _invalid()
            result.append({
                "provider": "verda", "product_type": "gpu_cluster", "gpu_model": model.upper(),
                "gpu_variant": variant[1] if variant else None,
                "raw_name": offer["name"], "raw_sku": f"instant-cluster|{count}x {hardware_name}|{raw_cpu}CPU-per-GPU|{ram[1]}GB-RAM-per-GPU",
                "gpu_count": count, "vram_gb": int(hardware[3]),
                "amount": format(reference, "f"), "currency": currency,
                "unit": "gpu_hour", "billing_mode": "on_demand", "quote_status": "quoted",
                "price_basis": "advertised_per_gpu", "cloud_tier": "instant_cluster",
                "regions": [], "zones": [], "geographic_scope": "unspecified",
                "account_scope": "public_catalog", "tax_scope": "unspecified", "availability": "unknown",
                "observed_at": observed_at, "effective_from": None, "effective_until": None,
                "source_url": _CURRENCY_URLS[currency], "source_type": SOURCE_TYPE,
                "resources": {"cpu_count": int(raw_cpu) * count, "ram_gb": int(ram[1]) * count,
                              "listed_gpu_vram_gb": int(vram[1]) * count, "interconnect": "InfiniBand"},
                "worker_resources": {"cpu_cores_per_gpu": int(raw_cpu),
                                     "memory_per_gpu": {"amount": int(ram[1]), "unit": "GB"}},
                "selected_configuration": {"cluster_gpu_count": count, "cluster_gpu_count_relation": "exact"},
                "conditions": {"product_variant": "Instant clusters", "interconnect": "InfiniBand",
                               "listed_per_gpu_reference": {"amount": format(reference, "f"), "currency": currency, "unit": "gpu_hour"},
                               "resource_basis": "Visible table explicitly states specifications per GPU",
                               "configuration_source": "Official JSON-LD explicitly sized instant-cluster offer",
                               "published_structured_total": {"amount": format(total, "f"), "currency": currency, "unit": "instance_hour"},
                               "structured_total_matches_table": total == reference * count,
                               "pricing_conflict": total != reference * count,
                               "total_price_source": "Official JSON-LD Hourly instant cluster price"},
                "notes": ["Explicitly sized public instant-cluster configuration with InfiniBand; the price is the visible table's stated per-GPU hourly tariff.",
                          "Structured cluster totals can differ from the visible per-GPU tariff. The source metadata total is preserved as evidence, not asserted as a checkout total.",
                          "CPU and RAM totals scale the table's explicitly per-GPU specifications by the published cluster count.",
                          "This price source does not state an applicable country or region; no worldwide-uniform price or stock was inferred."],
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
