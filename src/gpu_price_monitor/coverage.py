"""Describe GPU model coverage without comparing prices or changing quotes.

Families intentionally combine interface/VRAM variants only for the question
"is this GPU series represented?". Quote indices preserve every original
condition. A family match never says its variants have the same price.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from .settings import ConfigurationError

MAINSTREAM_GPU_MODELS = (
    "H100", "H200", "B200", "B300", "GB200", "GB300", "GH200",
    "A100", "A800", "H800", "H20", "L20", "L40", "L40S", "L4",
    "A40", "A10", "T4", "V100",
    "RTX 5090", "RTX 4090", "RTX 4090D", "RTX 3090", "RTX 3080 TI", "RTX 2080 TI",
    "RTX PRO 6000", "RTX 6000 ADA", "RTX A6000", "RTX A5000", "RTX A4000",
    "MI300X", "MI325X", "MI350X", "MI355X",
)

_BOUNDARY = r"(?=$|[ ()/,])"
_GPU_BOUNDARY = r"(?=$|[ ()/,]|(?:SXM\d*|PCIE|NVL\d*)(?=$|[ ()/,]))"
_DATACENTER = re.compile(
    r"^(GB200|GB300|GH200|B200|B300|H100|H200|H800|H20|A100|A800|A40|A10|L40S|L40|L20|L4|T4|V100S?)" + _GPU_BOUNDARY
)
_AMD = re.compile(r"^(MI300X|MI325X|MI350X|MI355X)" + _BOUNDARY)
_PRO = re.compile(r"^RTX\s*PRO\s*6000" + _BOUNDARY)
_ADA = re.compile(r"^RTX\s*6000\s*ADA" + _BOUNDARY)
_WORKSTATION = re.compile(r"^(?:RTX\s*)?(A6000|A5000|A4000)" + _BOUNDARY)
_CONSUMER = re.compile(r"^RTX\s*(5090|4090\s*D|4090|3090|3080\s*TI|2080\s*TI)" + _BOUNDARY)
_BARE_CONSUMER = re.compile(r"^(5090|4090\s*D|4090|3090|3080\s*TI|2080\s*TI)" + _BOUNDARY)
_UNAVAILABLE = {"offline", "ended", "upcoming", "unavailable", "out_of_stock", "sold_out"}
_STATUSES = ("priced", "unavailable_listings_only", "contact_sales_only", "not_found")


def gpu_family(quote: Mapping) -> str | None:
    """Return a conservative family label without mutating the source quote.

    Unrecognized, nonempty GPU names remain distinct uppercase labels so that
    they can appear as extra coverage. No substring matching joins GB200 with
    B200, or RTX 4090D with RTX 4090. T4S stays T4S; V100S is the V100 family.
    """
    if not isinstance(quote, Mapping):
        return None
    name = quote.get("gpu_model")
    if not isinstance(name, str) or not name.strip():
        name = quote.get("raw_name")
    if not isinstance(name, str) or not name.strip():
        return None
    name = re.sub(r"[®™]", "", name.upper())
    name = re.sub(r"[_\s-]+", " ", name).strip()
    name = re.sub(r"^[1-9]\d*\s*[X×]\s*", "", name)
    name = re.sub(r"^(?:(?:NVIDIA|AMD|INSTINCT|GEFORCE|TESLA|HGX|QUADRO)\s+)+", "", name)
    if not name:
        return None
    for pattern in (_DATACENTER, _AMD):
        match = pattern.match(name)
        if match:
            return "V100" if match.group(1) == "V100S" else match.group(1)
    if _PRO.match(name):
        return "RTX PRO 6000"
    if _ADA.match(name):
        return "RTX 6000 ADA"
    match = _WORKSTATION.match(name)
    if match:
        return "RTX " + match.group(1)
    match = _CONSUMER.match(name) or _BARE_CONSUMER.match(name)
    if match:
        suffix = re.sub(r"\s+", "", match.group(1))
        if suffix.endswith("TI"):
            suffix = suffix[:-2] + " TI"
        return "RTX " + suffix
    return name


def _target_models(models) -> tuple[str, ...]:
    if models is None:
        return MAINSTREAM_GPU_MODELS
    if not isinstance(models, (list, tuple)) or not models:
        raise ConfigurationError("coverage models must be a nonempty list or tuple of GPU names")
    result = []
    for model in models:
        if (not isinstance(model, str) or not model.strip() or len(model) > 120
                or any(ord(char) < 32 for char in model)):
            raise ConfigurationError("coverage models must contain valid GPU names")
        family = gpu_family({"gpu_model": model})
        if family is None or family in result:
            raise ConfigurationError("coverage models must contain unique GPU families")
        result.append(family)
    return tuple(result)


def _is_numeric(quote: Mapping) -> bool:
    amount = quote.get("amount")
    if quote.get("quote_status") == "contact_sales":
        if amount is not None:
            raise ConfigurationError("contact-sales coverage quotes must not contain an amount")
        return False
    if not isinstance(amount, str) or not amount.strip() or len(amount) > 128:
        raise ConfigurationError("coverage price amounts must be finite nonnegative decimal strings")
    try:
        value = Decimal(amount)
    except InvalidOperation:
        raise ConfigurationError("coverage price amounts must be finite nonnegative decimal strings") from None
    if not value.is_finite() or value < 0:
        raise ConfigurationError("coverage price amounts must be finite nonnegative decimal strings")
    return True


def _entry(model: str | None, indices: list[int], prices: list, numeric: dict[int, bool]) -> dict:
    records = [prices[index] for index in indices]
    numeric_indices = [index for index in indices if numeric[index]]
    active = [index for index in numeric_indices if str(prices[index].get("availability", "unknown")).casefold() not in _UNAVAILABLE]
    if active:
        status = "priced"
    elif numeric_indices:
        status = "unavailable_listings_only"
    elif records:
        status = "contact_sales_only"
    else:
        status = "not_found"

    def values(key):
        return sorted({record[key] for record in records if isinstance(record.get(key), str) and record[key]})

    return {
        "gpu_model": model,
        "status": status,
        "quote_count": len(indices),
        "numeric_quote_count": len(numeric_indices),
        "providers": values("provider"),
        "currencies": values("currency"),
        "units": values("unit"),
        "quote_indices": list(indices),
    }


def report_coverage(result: Mapping, models=None) -> dict:
    """Report model presence among returned quotes, retaining gaps explicitly.

    This report does not fetch data, compare prices, convert currencies or
    infer stock. Invalid monetary records are rejected. Quotes attributed to
    explicitly failed sources (or an entirely failed collection) are excluded
    and their original indices are returned. Missing collection/source metadata
    remains unknown, even if valid quotes were supplied by the caller.
    """
    targets = _target_models(models)
    if not isinstance(result, Mapping) or not isinstance(result.get("prices"), list):
        raise ConfigurationError("coverage result must contain a prices list")
    prices = result["prices"]
    if any(not isinstance(quote, Mapping) for quote in prices):
        raise ConfigurationError("coverage prices must contain quote objects")
    raw_status = result.get("status")
    collection_status = raw_status if isinstance(raw_status, str) and raw_status in {"success", "partial", "failed"} else "unknown"
    provider_results = result.get("provider_results")
    if provider_results is not None and (not isinstance(provider_results, list)
                                         or any(not isinstance(item, Mapping) for item in provider_results)):
        raise ConfigurationError("coverage provider results must contain source objects")
    source_summary = {"requested_count": None, "success_count": 0, "no_matches_count": 0, "failed_count": 0, "unknown_count": 0}
    failed_providers = set()
    if provider_results is not None:
        source_summary["requested_count"] = len(provider_results)
        for source in provider_results:
            status = source.get("status")
            key = status + "_count" if isinstance(status, str) and status in {"success", "no_matches", "failed"} else "unknown_count"
            source_summary[key] += 1
            if status == "failed" and isinstance(source.get("provider"), str):
                failed_providers.add(source["provider"])
    grouped = {model: [] for model in targets}
    extra, numeric, excluded = {}, {}, []
    for index, quote in enumerate(prices):
        provider = quote.get("provider")
        if collection_status == "failed" or (isinstance(provider, str) and provider in failed_providers):
            excluded.append(index)
            continue
        numeric[index] = _is_numeric(quote)
        family = gpu_family(quote)
        if family in grouped:
            grouped[family].append(index)
        else:
            extra.setdefault(family, []).append(index)
    model_entries = [_entry(model, grouped[model], prices, numeric) for model in targets]
    extra_entries = [_entry(model, indices, prices, numeric) for model, indices in sorted(extra.items(), key=lambda item: (item[0] is None, item[0] or ""))]
    totals = {
        "requested_models": len(targets),
        **{status + "_models": sum(entry["status"] == status for entry in model_entries) for status in _STATUSES},
        "returned_quotes": len(prices),
        "considered_quotes": len(prices) - len(excluded),
        "matched_quotes": sum(entry["quote_count"] for entry in model_entries),
        "extra_models": len(extra_entries),
        "excluded_quotes": len(excluded),
    }
    return {
        "schema_version": 1,
        "scope": "returned_quotes",
        "collection_status": collection_status,
        "source_summary": source_summary,
        "totals": totals,
        "models": model_entries,
        "extra_models": extra_entries,
        "excluded_quote_indices": excluded,
        "notes": [
            "Coverage describes returned quotes after caller filters, not the entire GPU market or all source catalogs.",
            "A priced family has at least one numeric listing that is not explicitly unavailable; unknown availability does not prove stock or orderability.",
            "Family grouping can combine interface, cooling and VRAM variants for coverage only; it does not imply equivalent configurations or prices.",
            "No lowest, mean or converted price is calculated. Quote indices refer to the original prices array and retain currencies, units and conditions.",
            "Models without returned matches remain not_found; failed sources and missing source metadata do not establish complete coverage.",
        ],
    }
