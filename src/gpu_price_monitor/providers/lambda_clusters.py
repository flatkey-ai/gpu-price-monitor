"""Parse Lambda's public 1-Click Cluster tariffs, including reservation terms."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import re

from bs4 import BeautifulSoup

from .lambda_public import _FOOTNOTE, _PRICE, _gpu_fields, _text
from ..settings import Settings
from ..transport import fetch_text

SOURCE_URL = "https://lambda.ai/1-click-clusters"
PRICING_URL = "https://lambda.ai/pricing"
BILLING_URL = "https://docs.lambda.ai/public-cloud/billing/"
SOURCE_TYPE = "public_page"
_COLUMNS = ("PLAN", "DURATION", "GPU COUNT", "PRICE/GPU/HR*", "ACTION")
_COUNT = re.compile(r"([1-9]\d*)(\+)?")
_DURATION = re.compile(r"([1-9]\d*) (weeks?|months?|years?)(?: (–) ([1-9]\d*) (weeks?|months?|years?)|(\+))")


def _term(value: str) -> tuple[dict, dict]:
    match = _DURATION.fullmatch(value)
    if not match:
        raise ValueError("Lambda cluster reservation duration changed")
    minimum = {"amount": int(match[1]), "unit": match[2].removesuffix("s")}
    maximum = None if match[6] else {"amount": int(match[4]), "unit": match[5].removesuffix("s")}
    if maximum and minimum["unit"] == maximum["unit"] and minimum["amount"] > maximum["amount"]:
        raise ValueError("Lambda cluster reservation duration is inconsistent")
    return {"duration": minimum}, {"minimum": minimum, "maximum": maximum, "source_label": value}


def parse_prices(content: str, *, observed_at: str, as_of: date | None = None,
                 source_url: str = SOURCE_URL) -> list[dict]:
    """Preserve cluster counts as cluster configuration, never GPUs per node.

    Prices are advertised per GPU-hour, while reservations are billed weekly.
    A count such as 256+ is a minimum, not an exact cluster or node total.
    Long-term contact-sales rows retain null amounts instead of invented rates.
    """
    if source_url not in {SOURCE_URL, PRICING_URL}:
        raise ValueError("Lambda cluster source URL is not recognized")
    soup = BeautifulSoup(content, "html.parser")
    headings = [h for h in soup.find_all("h2") if _text(h).casefold() in {
        "1-click clusters pricing", "go from prototype to production",
    }]
    if len(headings) != 1 or headings[0].find_parent("section") is None:
        raise ValueError("Lambda cluster pricing section was not uniquely identified")
    section = headings[0].find_parent("section")
    tablists = section.find_all(attrs={"role": "tablist"})
    panels = section.find_all(attrs={"role": "tabpanel"})
    tables = section.find_all("table")
    if len(tablists) != 1 or len(panels) != 2 or len(tables) != 2:
        raise ValueError("Lambda cluster pricing tab structure changed")
    tabs = tablists[0].find_all(attrs={"role": "tab"})
    if len(tabs) != len(panels):
        raise ValueError("Lambda cluster pricing tab structure changed")
    result, seen, used = [], set(), set()
    for tab in tabs:
        raw_plan = _text(tab)
        model, variant = _gpu_fields(raw_plan)
        tab_id, panel_id = tab.get("id"), tab.get("aria-controls")
        if (not isinstance(tab_id, str) or not tab_id or not isinstance(panel_id, str) or not panel_id
                or len(section.find_all(id=tab_id)) != 1 or len(section.find_all(id=panel_id)) != 1):
            raise ValueError("Lambda cluster pricing tab association is ambiguous")
        linked = [panel for panel in panels if panel.get("id") == panel_id]
        if len(linked) != 1 or linked[0].get("aria-labelledby") != tab_id or panel_id in used:
            raise ValueError("Lambda cluster pricing tab association changed")
        used.add(panel_id)
        panel = linked[0]
        titles, panel_tables, footnotes = panel.find_all("h3"), panel.find_all("table"), panel.select(".table-footer")
        if (len(titles) != 1 or _text(titles[0]) != raw_plan + " systems" or len(panel_tables) != 1
                or len(footnotes) != 1 or _text(footnotes[0]) != _FOOTNOTE):
            raise ValueError("Lambda cluster table, model heading or tax footnote changed")
        table = panel_tables[0]
        headers, bodies = table.select("thead > tr"), table.find_all("tbody", recursive=False)
        if len(headers) != 1 or len(bodies) != 1 or not bodies[0].find_all("tr", recursive=False):
            raise ValueError("Lambda cluster pricing table structure changed")
        cells = headers[0].find_all(["th", "td"], recursive=False)
        if (tuple(_text(cell).upper() for cell in cells) != _COLUMNS
                or any(cell.name != "th" or cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells)):
            raise ValueError("Lambda cluster pricing table columns changed")
        for row in bodies[0].find_all("tr", recursive=False):
            cells = row.find_all(["th", "td"], recursive=False)
            if (len(cells) != len(_COLUMNS) or cells[0].name != "th"
                    or tuple(str(cell.get("data-label", "")).upper() for cell in cells) != _COLUMNS
                    or any(cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells)):
                raise ValueError("Lambda cluster pricing row structure changed")
            plan, duration, count_label, price_label, action = map(_text, cells)
            if plan != raw_plan or row.get("data-plan") != plan or action != "Talk to our team":
                raise ValueError("Lambda cluster pricing row identity changed")
            count, price = _COUNT.fullmatch(count_label), _PRICE.fullmatch(price_label)
            if not count or (not price and price_label != "—"):
                raise ValueError("Lambda cluster GPU count or price unit changed")
            amount = price.group(1) if price else None
            if amount is not None and Decimal(amount) <= 0:
                raise ValueError("Lambda cluster price must be positive")
            minimum, reservation_term = _term(duration)
            identity = (model, variant, duration, count_label)
            if identity in seen:
                raise ValueError("Lambda cluster table has duplicate configurations")
            seen.add(identity)
            result.append({
                "provider": "lambda", "product_type": "gpu_cluster", "product_line": "1-Click Clusters",
                "price_record_kind": "published_price" if amount is not None else "contact_sales_listing",
                "configuration_expansion": False,
                "gpu_model": model, "gpu_variant": variant, "raw_name": plan, "raw_sku": None,
                "gpu_count": None, "vram_gb": None, "amount": amount, "currency": "USD", "unit": "gpu_hour",
                "billing_mode": "reserved", "price_basis": "advertised_per_gpu",
                "quote_status": "quoted" if amount is not None else "contact_sales",
                "minimum_commitment": minimum,
                "selected_configuration": {"cluster_gpu_count": int(count[1]),
                                           "cluster_gpu_count_relation": "minimum" if count[2] else "exact"},
                "source_conditions": {"reservation_term": reservation_term, "billing_increment": "week",
                                      "sales_contact_required": True},
                "regions": [], "zones": [], "compute_countries": [], "geographic_scope": "unspecified",
                "price_scope": "unlocated_catalog", "region_price_verified": False,
                "account_scope": "public_catalog", "tax_scope": "excluded", "availability": "unknown",
                "observed_at": observed_at, "effective_from": None, "effective_until": None,
                "source_url": source_url, "source_type": SOURCE_TYPE, "billing_source_url": BILLING_URL,
                "notes": ["Reserved 1-Click Cluster tariff per GPU-hour; reservations are billed in weekly increments.",
                          "The GPU count describes the whole cluster, not GPUs per node; no node or cluster hourly total was inferred.",
                          "A reservation term and sales contact apply; capacity, account eligibility and final contractual price were not verified."],
            })
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    return parse_prices(fetch_text(SOURCE_URL, settings), observed_at=observed_at)
