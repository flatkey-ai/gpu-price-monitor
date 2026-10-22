"""Parse Crusoe's public GPU instance price table without making requests."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.crusoe.ai/cloud/pricing"
SOURCE_TYPE = "official_pricing_page"

_MEMORY = re.compile(r"^(\d+)\s*GB$", re.IGNORECASE)
_OTHER_MEMORY = re.compile(r"^(?:\d+(?:\.\d+)?)\s*(?:TB|TiB|GiB)$", re.IGNORECASE)
_PRICE = re.compile(
    r"^(?:(starting\s+(?:at|from)|from|as\s+low\s+as)\s+)?"
    r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*/\s*GPU\s*[-/]\s*(?:hr|hour)$",
    re.IGNORECASE,
)
_BILLING_MODES = {"on-demand": "on_demand", "current spot": "spot"}
_VARIANT = re.compile(r"\b(?:HGX|NVL\d+|SXM\d*|PCIe)\b", re.IGNORECASE)


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _price(text: str) -> tuple[str | None, str, str]:
    if text.casefold() == "contact sales":
        return None, "contact_sales", "advertised_per_gpu"
    match = _PRICE.fullmatch(text)
    if not match:
        raise ValueError("Crusoe GPU instance price has an unrecognized amount or unit")
    amount = Decimal(match.group(2).replace(",", ""))
    if amount <= 0:
        raise ValueError("Crusoe GPU instance price must be positive")
    starting = match.group(1) is not None
    return (
        format(amount, "f"),
        "starting_at" if starting else "quoted",
        "starting_price" if starting else "advertised_per_gpu",
    )


def parse_prices(content: str, *, observed_at: str, as_of: date) -> list[dict]:
    """Return public list prices, including explicit ``contact_sales`` entries.

    The neighboring managed inference tables also list GPUs, at different
    prices. Only the explicitly titled GPU instances table is accepted. Unknown
    structures fail rather than silently returning an incomplete catalog.
    ``as_of`` is part of the provider interface; this table has no dated tiers.
    """
    soup = BeautifulSoup(content, "html.parser")
    headings = [
        heading
        for heading in soup.find_all(re.compile(r"^h[1-6]$"))
        if _text(heading).casefold() == "gpu instances pricing"
    ]
    if len(headings) != 1:
        raise ValueError("Crusoe GPU instances pricing section was not uniquely identified")
    section = headings[0].find_parent(class_="pricing-dd")
    if section is None:
        raise ValueError("Crusoe GPU instances pricing section structure changed")
    header_rows = section.select(".pricing-table-heading")
    if len(header_rows) != 1:
        raise ValueError("Crusoe GPU instances pricing columns were not uniquely identified")
    columns = [_text(cell).casefold() for cell in header_rows[0].select(".pricing-heading")]
    if len(columns) != 3 or columns[0] != "gpu model" or set(columns[1:]) != set(_BILLING_MODES):
        raise ValueError("Crusoe GPU instances pricing columns changed")
    rows = section.select(".pricing_gpu-item")
    if not rows:
        raise ValueError("Crusoe GPU instances pricing table contains no rows")

    result = []
    seen = set()
    for row in rows:
        names = row.select(".pricing-item-heading")
        prices = row.select(".pricing-rich")
        if len(names) != 1 or len(prices) != 2:
            raise ValueError("Crusoe GPU instance row structure changed")
        raw_name = _text(names[0])
        model_name = re.sub(r"^(?:NVIDIA|AMD)\s+", "", raw_name, flags=re.IGNORECASE)
        heading_variants = [match.group() for match in _VARIANT.finditer(model_name)]
        gpu_model = " ".join(_VARIANT.sub("", model_name).split()).upper()
        if not gpu_model:
            raise ValueError("Crusoe GPU instance row is missing its model")
        tags = [_text(tag) for tag in row.select(".pricing-tag")]
        parsed_prices = [_price(_text(price)) for price in prices]
        memories = [match for tag in tags if (match := _MEMORY.fullmatch(tag))]
        # Contact-sales products can omit memory or publish an NVL system-level
        # TB label. Retain the label, but never infer per-GPU GB from it; numeric
        # quotes still require one explicit per-GPU GB memory label.
        unpriced_memory_description = [tag for tag in tags if _OTHER_MEMORY.fullmatch(tag)]
        empty_contact_listing = (
            not memories
            and bool(tags)
            and all(status == "contact_sales" for _, status, _ in parsed_prices)
            and len(unpriced_memory_description) <= 1
            and all(not tag or _VARIANT.fullmatch(tag) or _OTHER_MEMORY.fullmatch(tag) for tag in tags)
        )
        if len(memories) != 1 and not empty_contact_listing:
            raise ValueError("Crusoe GPU instance row has no unique GB memory size")
        vram_gb = int(memories[0].group(1)) if memories else None
        if vram_gb is not None and vram_gb <= 0:
            raise ValueError("Crusoe GPU instance row has an invalid memory size")
        variant_parts = []
        for value in heading_variants + [tag for tag in tags if tag and not _MEMORY.fullmatch(tag)
                                         and not _OTHER_MEMORY.fullmatch(tag)]:
            canonical = "PCIe" if value.casefold() == "pcie" else value.upper()
            if canonical not in variant_parts:
                variant_parts.append(canonical)
        variant = " ".join(variant_parts) or None

        for column, (amount, status, basis) in zip(columns[1:], parsed_prices):
            billing_mode = _BILLING_MODES[column]
            identity = (gpu_model, variant, vram_gb, billing_mode)
            if identity in seen:
                raise ValueError("Crusoe GPU instance table contains ambiguous duplicate rows")
            seen.add(identity)
            notes = [
                "Public GPU instances list price; availability and orderability were not verified.",
                "The source does not specify a region or the number of GPUs per instance.",
            ]
            if status == "contact_sales":
                notes.append("The source requests contacting sales and provides no numeric price.")
            if vram_gb is None:
                notes.append("The source does not specify GPU memory capacity in per-GPU GB for this contact-sales listing.")
                if unpriced_memory_description:
                    notes.append("The raw non-GB memory label is retained without converting a possible NVL system total to per-GPU memory.")
            result.append({
                "provider": "crusoe",
                "product_type": "gpu_instance",
                "gpu_model": gpu_model,
                "raw_name": raw_name,
                "raw_sku": None,
                "gpu_variant": variant,
                "vram_gb": vram_gb,
                **({"gpu_memory_description": unpriced_memory_description[0]}
                   if unpriced_memory_description else {}),
                "gpu_count": None,
                "amount": amount,
                "currency": "USD",
                "unit": "gpu_hour",
                "billing_mode": billing_mode,
                "price_basis": basis,
                "quote_status": status,
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
