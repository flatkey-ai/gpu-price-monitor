"""Collect and reconcile the official public page and the caller's console.

Both sources remain separate observations. Reconciliation never copies price,
geography, stock, reservation terms, or account access from one into the other.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, DecimalException

from . import lambda_console_client, lambda_public
from ..settings import Settings
from ..transport import FetchError, fetch_text

SOURCE_URL = lambda_public.SOURCE_URL
SOURCE_TYPE = "mixed_official_sources"
_COMMON_FIELDS = ("gpu_model", "gpu_variant", "vram_gb", "gpu_count",
                  "vcpus", "memory_gib", "storage_gib")


def _specification(quote: dict) -> dict:
    """Compare only explicit fields; exact TiB/GiB conversion is lossless."""
    resources = quote.get("resources", {})
    storage = resources.get("storage_gib")
    public_storage = resources.get("storage", {})
    if storage is None and public_storage.get("unit") in {"GiB", "TiB"}:
        storage = Decimal(public_storage["amount"])
        if public_storage["unit"] == "TiB":
            storage *= 1024
    # Quadro is a product-line prefix, not a different RTX 6000 configuration.
    model = {"QUADRO RTX 6000": "RTX 6000"}.get(quote["gpu_model"], quote["gpu_model"])
    return {"gpu_model": model, "gpu_variant": quote.get("gpu_variant"),
            "vram_gb": quote.get("vram_gb"), "gpu_count": quote.get("gpu_count"),
            "vcpus": resources.get("vcpus"), "memory_gib": resources.get("memory_gib"),
            "storage_gib": None if storage is None else format(Decimal(storage).normalize(), "f")}


def _record(quote: dict) -> dict:
    """A small allowlisted price reference, without raw account/session data."""
    return {"record_id": quote["visible_record_id"], "raw_sku": quote.get("raw_sku"),
            "gpu_model": quote["gpu_model"], "gpu_count": quote.get("gpu_count"),
            "amount": quote["amount"], "currency": quote["currency"], "unit": quote["unit"],
            "source_url": quote["source_url"], "observed_at": quote["observed_at"]}


def reconcile_catalogs(public: list[dict], console: list[dict], *, sources_complete: bool) -> dict:
    """Describe corresponding advertised fields without deduplicating SKUs.

    Model and GPU count select candidates only. All common hardware fields and
    rates are compared afterwards. An absent variant is not a wildcard, rounded
    storage is not made equal, and reserved clusters are never paired across
    sources because the console does not establish their reservation terms.
    """
    public_instances = [q for q in public if q["product_type"] == "gpu_instance"]
    console_instances = [q for q in console if q["product_type"] == "gpu_instance"]
    checks, matched_console, unmatched = [], set(), []
    for public_quote in public_instances:
        public_spec = _specification(public_quote)
        candidates = []
        for console_quote in console_instances:
            console_spec = _specification(console_quote)
            if any(public_spec[key] != console_spec[key] for key in ("gpu_model", "gpu_count")):
                continue
            matched_console.add(console_quote["visible_record_id"])
            differences = [{"field": key, "public": public_spec[key], "console": console_spec[key]}
                           for key in _COMMON_FIELDS if public_spec[key] != console_spec[key]]
            comparable = (public_quote["currency"], public_quote["unit"], public_quote["billing_mode"]) == (
                console_quote["currency"], console_quote["unit"], console_quote["billing_mode"])
            candidates.append({**_record(console_quote),
                               "shared_specification_fields_equal": not differences,
                               "specification_differences": differences,
                               "hourly_rate_equal": (Decimal(public_quote["amount"]) == Decimal(console_quote["amount"]))
                               if comparable else None})
        checks.append({"public": _record(public_quote), "console_candidates": candidates})
        if not candidates:
            unmatched.append(_record(public_quote))
    return {
        "status": "compared" if sources_complete else "incomplete_sources",
        "records_merged": 0,
        "policy": "Preserve every source observation; model/count only select comparison candidates, never prove identical offers.",
        "shared_specification_fields": list(_COMMON_FIELDS),
        "uncompared_conditions": ["architecture absent on public page", "stock", "geographic applicability",
                                  "taxes", "account conditions", "checkout price"],
        "on_demand_checks": checks,
        "public_without_console_model_count_candidate": unmatched if sources_complete else [],
        "console_without_public_model_count_candidate": [
            _record(q) for q in console_instances if q["visible_record_id"] not in matched_console
        ] if sources_complete else [],
        "reserved_clusters": {
            "status": "separate_source_terms",
            "public_record_count": sum(q["product_type"] == "gpu_cluster" for q in public),
            "console_record_count": sum(q["product_type"] == "gpu_cluster" for q in console),
            "reason": "Public duration/count tiers and console configurations are retained separately; console reservation duration is unverified.",
        },
    }


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Read the two selected sources independently, including partial results.

    A valid exported session is required to complete the console half. Public
    success never masks an expired session, and session cookies are not passed
    to the anonymous website request. Contact-sales rows without a numeric
    price are excluded from prices and counted separately for reconciliation.
    """
    public, excluded, errors = [], [], []
    public_context = {"kind": "public_pricing_page", "source_url": SOURCE_URL,
                      "source_type": "public_page", "status": "failed", "observed_at": observed_at}
    try:
        content = fetch_text(SOURCE_URL, settings)
        rows = lambda_public.parse_prices(content, observed_at=observed_at)
        for quote in rows:
            if quote["amount"] is None or quote["quote_status"] != "quoted":
                excluded.append({"gpu_model": quote["gpu_model"], "source_url": quote["source_url"],
                                 "reason": "no_published_numeric_price", "quote_status": quote["quote_status"],
                                 "selected_configuration": deepcopy(quote.get("selected_configuration")),
                                 "source_conditions": deepcopy(quote.get("source_conditions"))})
            else:
                public.append(quote)
        public_context.update(status="success", source_record_count=len(rows),
                              numeric_quote_count=len(public), excluded_unpriced_record_count=len(excluded))
    except FetchError as exc:
        errors.append({"source_url": SOURCE_URL, "code": exc.code, "message": str(exc), "retryable": exc.retryable})
    except (ValueError, KeyError, TypeError, DecimalException):
        errors.append({"source_url": SOURCE_URL, "code": "parse_failed",
                       "message": "The Lambda public pricing schema or price units changed.", "retryable": False})

    console_result = lambda_console_client.collect_result(settings=settings, observed_at=observed_at)
    console = deepcopy(console_result["prices"])
    errors.extend(console_result["errors"])
    for source, quotes in (("public", public), ("console", console)):
        for index, quote in enumerate(quotes, 1):
            quote.update(visible_source=source, visible_record_id=f"lambda:{source}:{index}")
    # Raw directory reconciliation does not require a validated geography
    # statement. A frontend change still makes collection partial via errors,
    # while the fetched source rows can be compared without inventing locations.
    complete = (public_context["status"] == "success"
                and all(source["status"] == "success" for source in console_result["sources"]))
    prices = public + console
    coverage = {
        "scope": "official_public_pricing_page_and_current_account_visible_catalogs",
        "source_count": 2, "requested_sources_collected": complete,
        "public_source_record_count": public_context.get("source_record_count", 0),
        "public_numeric_quote_count": len(public), "public_unpriced_record_count": len(excluded),
        "console_numeric_quote_count": len(console), "source_observation_count": len(prices),
        "deduplicated_offer_count": None, "all_prices_complete": False,
        "console_catalog": console_result["catalog_coverage"],
        "reconciliation": reconcile_catalogs(public, console, sources_complete=complete),
        "excluded_public_records": excluded,
        "scope_exclusions": ["unpublished sales quotes", "private contracts", "purchased-resource-only pricing"],
    }
    return {
        "prices": prices, "errors": errors,
        "status": "success" if complete and not errors else "partial" if prices else "failed",
        "sources": [public_context, *console_result["sources"]], "catalog_coverage": coverage,
        "authentication_method": "anonymous_public_page_and_caller_supplied_session_cookie",
        **{key: console_result[key] for key in (
            "regions_catalog", "country_region_catalog", "price_applicability_verification",
            "excluded_non_gpu_records", "excluded_non_gpu_record_count")},
        "gaps": [gap for gap in console_result["gaps"]
                 if gap["scope"] != "negotiated_and_capacity_reservation_quotes"],
        "pricing_limitations": [
            "Counts are source observations, not unique configurations; matching values never cause source records to be merged.",
            "Public rows retain their own published specifications and terms; console rows retain their account-visible specifications and applicability.",
            "Public prices do not inherit console capacity locations or verified price regions; unknown geography remains unknown.",
            "Only numeric published GPU-hour prices are included; unpublished sales and private-contract prices are outside the requested scope.",
        ],
    }
