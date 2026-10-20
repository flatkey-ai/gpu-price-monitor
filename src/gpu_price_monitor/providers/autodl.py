"""Read AutoDL's unauthenticated, rendered homepage price cards.

The homepage advertises catalog prices for ordinary and member users. It does
not state a datacenter, machine configuration, GPU count or available stock.
The marketplace and the homepage catalog must not be treated as equivalent.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from bs4 import BeautifulSoup

from ..settings import Settings

SOURCE_URL = "https://www.autodl.com/home"
SOURCE_TYPE = "public_page"

_TITLE = "炼丹会员及租用价格"
_TIERS = {"普通用户": "ordinary", "炼丹会员": "member"}
_NAME = re.compile(r"^(.+?)\s*/\s*(\d+)\s*GB$", re.IGNORECASE)
_AMOUNT = r"\d+(?:\.\d+)?"
_PRICE = re.compile(rf"^￥\s*({_AMOUNT})\s*/时(?:\s*会员\s*({_AMOUNT})折)?$")


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _gpu_fields(raw_name: str) -> tuple[str, int]:
    match = _NAME.fullmatch(raw_name)
    if not match:
        raise ValueError("AutoDL homepage GPU name or memory is unrecognized")
    model = re.sub(r"^(?:NVIDIA|AMD|摩尔线程|华为)\s+", "", match.group(1), flags=re.IGNORECASE)
    vram_gb = int(match.group(2))
    # The source's A800-80GB name repeats its separately displayed memory.
    model = re.sub(rf"-{vram_gb}GB$", "", model, flags=re.IGNORECASE)
    if not model.strip() or vram_gb <= 0:
        raise ValueError("AutoDL homepage GPU name or memory is invalid")
    return model.upper(), vram_gb


def parse_prices(content: str, *, observed_at: str, as_of: date | None = None) -> list[dict]:
    """Parse the one active pricing tab, without executing or fetching anything.

    ``content`` can be a whole rendered page or the pricing section outerHTML.
    All cards in that tab must be recognized. ``as_of`` is unused because this
    source publishes no effective dates.
    """
    if not isinstance(content, str):
        raise ValueError("AutoDL homepage content must be HTML text")
    soup = BeautifulSoup(content, "html.parser")
    sections = [section for section in soup.select(".display-module")
                if any(_text(title) == _TITLE for title in section.select(".header .title"))]
    if len(sections) != 1:
        raise ValueError("AutoDL homepage pricing section was not uniquely identified")
    section = sections[0]
    tabs = section.select(".level-tab")
    if len(tabs) != 1:
        raise ValueError("AutoDL homepage pricing tabs changed")
    labels = [_text(tab) for tab in tabs[0].find_all("span", recursive=False)]
    if len(labels) != 2 or set(labels) != set(_TIERS):
        raise ValueError("AutoDL homepage pricing tier labels changed")
    active = tabs[0].select("span.active")
    if len(active) != 1 or _text(active[0]) not in _TIERS:
        raise ValueError("AutoDL homepage active pricing tier was not identified")
    tier = _TIERS[_text(active[0])]
    containers = section.select(".member-gpu-price")
    if len(containers) != 1:
        raise ValueError("AutoDL homepage GPU card container changed")
    cards = containers[0].find_all("div", class_="gpu-item", recursive=False)
    if not cards or len(cards) != len(containers[0].find_all(recursive=False)):
        raise ValueError("AutoDL homepage GPU cards were not recognized")

    result = []
    seen = set()
    for card in cards:
        names, amounts = card.select(".name"), card.select(".price")
        if len(names) != 1 or len(amounts) != 1:
            raise ValueError("AutoDL homepage GPU card structure changed")
        raw_name = _text(names[0])
        model, vram_gb = _gpu_fields(raw_name)
        identity = (model, vram_gb)
        if identity in seen:
            raise ValueError("AutoDL homepage contains duplicate GPU cards")
        seen.add(identity)
        price = amounts[0]
        match = _PRICE.fullmatch(_text(price))
        numeric_fields = price.select(".text")
        units = price.select(".unit")
        discounts = price.select(".d-tag")
        if (not match or len(numeric_fields) != 1 or len(units) != 1
                or _text(units[0]) != "￥" or _text(numeric_fields[0]) != match.group(1)):
            raise ValueError("AutoDL homepage price amount or unit changed")
        amount = Decimal(match.group(1))
        if amount <= 0:
            raise ValueError("AutoDL homepage price must be positive")
        discount = None
        if tier == "member":
            if len(discounts) != 1 or match.group(2) is None:
                raise ValueError("AutoDL homepage member discount was not identified")
            shown_discount = Decimal(match.group(2))
            # AutoDL displays both Chinese '9折' and '95折' notation.
            with localcontext(Context(prec=50)):
                discount = shown_discount / (100 if shown_discount > 10 else 10)
            if not 0 < discount <= 1:
                raise ValueError("AutoDL homepage member discount is invalid")
        elif discounts or match.group(2) is not None:
            raise ValueError("AutoDL ordinary price unexpectedly has a member discount")
        notes = [
            "Public homepage catalog price per GPU-hour; this is not a region-specific marketplace quote.",
            "The source does not specify datacenter, instance GPU count, CPU, RAM or disk configuration.",
            "Availability, orderability and checkout price were not verified.",
        ]
        if tier == "member":
            notes.append("This displayed discounted price requires AutoDL membership eligibility; no membership was purchased or verified.")
        else:
            notes.append("The source labels this tier ordinary user (普通用户).")
        result.append({
            "provider": "autodl",
            "product_type": "gpu_instance",
            "gpu_model": model,
            "raw_name": raw_name,
            "raw_sku": None,
            "gpu_variant": None,
            "vram_gb": vram_gb,
            "gpu_count": None,
            "amount": format(amount, "f"),
            "currency": "CNY",
            "unit": "gpu_hour",
            "billing_mode": "on_demand",
            "price_basis": "advertised_per_gpu",
            "quote_status": "quoted",
            "pricing_tier": tier,
            "membership_required": tier == "member",
            "membership_discount": format(discount, "f") if discount is not None else None,
            "regions": [],
            "geographic_scope": "unspecified",
            "account_scope": "public_catalog",
            "tax_scope": "unspecified",
            "observed_at": observed_at,
            "effective_from": None,
            "effective_until": None,
            "source_url": SOURCE_URL,
            "source_type": SOURCE_TYPE,
            "availability": "unknown",
            "notes": notes,
        })
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Read both tabs in an isolated browser without credentials or purchases."""
    from ..browser import fetch_autodl_pages

    pages = fetch_autodl_pages(settings)
    if not isinstance(pages, list) or len(pages) != 2:
        raise ValueError("AutoDL public collection must return both pricing tabs")
    groups = [parse_prices(page, observed_at=observed_at) for page in pages]
    if [group[0]["pricing_tier"] for group in groups] != ["ordinary", "member"]:
        raise ValueError("AutoDL public collection returned inconsistent pricing tabs")
    ordinary = {(quote["gpu_model"], quote["vram_gb"]): quote for quote in groups[0]}
    member = {(quote["gpu_model"], quote["vram_gb"]): quote for quote in groups[1]}
    if ordinary.keys() != member.keys():
        raise ValueError("AutoDL public pricing tabs contain different GPU catalogs")
    for identity, quote in member.items():
        with localcontext(Context(prec=50)):
            expected = (Decimal(ordinary[identity]["amount"]) * Decimal(quote["membership_discount"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
        if expected != Decimal(quote["amount"]):
            raise ValueError("AutoDL public prices do not match the displayed member discount")
    return groups[0] + groups[1]
