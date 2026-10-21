"""Audit the selected catalog records without claiming market completeness."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .settings import ConfigurationError


_SOURCE_COUNTS = (
    "raw_exact_gpu_rate_count", "raw_exact_resource_rate_count",
    "raw_document_gpu_rate_count", "raw_document_resource_rate_count",
    "reported_spot_api_quote_count",
)
_STRUCTURE_COUNTS = ("platform_count", "preset_count")
_CALCULATION_ORIGINS = {"published_tariff_preset_calculation", "regional_spot_preset_calculation"}
_GAP_FIELDS = {"scope", "status", "reason", "source_url", "login_url", "api_url", "documentation_url", "requires"}
_STATUSES = {"success", "partial", "failed", "no_matches"}
_COUNT_FIELDS = (
    "record_count", "considered_record_count", "excluded_failed_source_record_count",
    "numeric_quoted_gpu_hour_count", "invalid_numeric_gpu_hour_record_count",
    "derived_calculation_count", "derived_numeric_quoted_gpu_hour_count",
    "direct_record_count", "direct_numeric_quoted_gpu_hour_count",
    "contact_sales_count", "starting_at_count", "regional_record_count",
    "numeric_regional_gpu_hour_count", "contract_record_count",
)


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _status(value: object) -> str:
    return value if isinstance(value, str) and value in _STATUSES else "unknown"


def _numeric(quote: Mapping) -> bool:
    if quote.get("quote_status") != "quoted" or quote.get("unit") != "gpu_hour":
        return False
    amount = quote.get("amount")
    if not isinstance(amount, str) or not amount.strip() or len(amount) > 128:
        return False
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return False
    return value.is_finite() and value >= 0


def _derived(quote: Mapping) -> bool:
    derivation = quote.get("rate_derivation")
    origin = quote.get("quote_origin")
    return (isinstance(origin, str) and origin in _CALCULATION_ORIGINS
            or quote.get("configuration_expansion") is True
            or isinstance(derivation, Mapping) and (
                derivation.get("independent_provider_quote") is False
                or str(derivation.get("method", "")).startswith("computed_")))


def _regional(quote: Mapping) -> bool:
    def bound(name):
        values = quote.get(name)
        return isinstance(values, list) and any(isinstance(value, str) and value.strip() for value in values)

    return quote.get("region_price_verified") is True and (bound("regions") or bound("zones"))


def _aggregate_status(statuses: list[str]) -> str:
    statuses = [status for status in statuses if status != "not_requested"]
    if not statuses:
        return "not_requested"
    if all(status in {"success", "no_matches"} for status in statuses):
        return "success"
    if all(status == "failed" for status in statuses):
        return "failed"
    if any(status in {"success", "no_matches", "partial"} for status in statuses):
        return "partial"
    return "unknown"


def _public_status(source: Mapping) -> str:
    """Exclude contract-only audit execution from public catalog status."""
    endpoint = source.get("api_endpoint_template", source.get("api_endpoint"))
    contract_only_endpoint = (source.get("provider") == "crusoe" and source.get("source_type") == "official_api"
                              and isinstance(endpoint, str)
                              and endpoint.endswith("/organizations/{organization_id}/reservations"))
    if source.get("audit_only") is True or contract_only_endpoint:
        return "not_requested"
    contexts = source.get("source_contexts")
    combined = (source.get("account_audit_only") is True
                or source.get("selection_reason") == "public_prices_and_account_contract_audit")
    if combined and isinstance(contexts, list):
        public = [context for context in contexts if isinstance(context, Mapping)
                  and not context.get("audit_only")
                  and context.get("account_scope") != "private_account_contract_audit"]
        if public:
            return _aggregate_status(["success" if context.get("status") == "ok"
                                      else _status(context.get("status")) for context in public])
        errors = source.get("source_errors")
        if isinstance(errors, list) and any(isinstance(error, Mapping)
                                           and error.get("source_url") == source.get("source_url") for error in errors):
            return "failed"
    return _status(source.get("status"))


def _safe_gaps(source: Mapping) -> list[dict]:
    gaps = source.get("gaps", [])
    if not isinstance(gaps, list):
        return []
    # Never copy arbitrary source contexts or private contract projections.
    return [{key: deepcopy(value) for key, value in gap.items() if key in _GAP_FIELDS
             and (isinstance(value, (str, bool, int)) or value is None
                  or isinstance(value, list) and all(isinstance(item, str) for item in value))}
            for gap in gaps if isinstance(gap, Mapping)]


def _source_counts(source: Mapping) -> tuple[dict, dict, int | None]:
    coverage = source.get("catalog_coverage")
    summary = coverage.get("summary") if isinstance(coverage, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    source_counts = {name: _count(summary.get(name)) for name in _SOURCE_COUNTS}
    structure_counts = {name: _count(summary.get(name)) for name in _STRUCTURE_COUNTS}
    minimums = summary.get("published_spot_minimums_not_used_as_quotes")
    minimum_count = len(minimums) if isinstance(minimums, list) else None
    return source_counts, structure_counts, minimum_count


def _provider_entry(provider: str, source: Mapping, records: list[Mapping], *, collection_failed: bool) -> dict:
    failed = collection_failed or source.get("status") == "failed"
    considered = [] if failed else records
    numeric = [quote for quote in considered if _numeric(quote)]
    derived = [quote for quote in considered if _derived(quote)]
    direct = [quote for quote in considered if not _derived(quote)]
    contracts = source.get("contract_records")
    contract_count = len(contracts) if isinstance(contracts, list) else _count(source.get("contract_record_count"))
    source_counts, structure_counts, minimum_count = _source_counts(source)
    filters = source.get("filters")
    filters = filters if isinstance(filters, Mapping) else {}
    selected_filters = {key: deepcopy(value["requested"]) for key, value in filters.items()
                        if isinstance(value, Mapping) and isinstance(value.get("requested"), list)}
    fetched_count = _count(source.get("fetched_count"))
    gaps = _safe_gaps(source)
    if failed or source.get("status") == "partial":
        gaps.append({"scope": "selected_source_collection", "status": "failed" if failed else "partial",
                     "reason": "Source execution did not establish a complete selected catalog."})
    if selected_filters:
        gaps.append({"scope": "returned_records", "status": "caller_filtered",
                     "reason": "Counts describe returned records after the selected filters."})
    sales = sum(quote.get("quote_status") == "contact_sales" for quote in considered)
    floors = sum(quote.get("quote_status") == "starting_at" for quote in considered)
    if sales:
        gaps.append({"scope": "contact_sales_listings", "status": "contact_sales", "record_count": sales})
    if floors or minimum_count:
        gaps.append({"scope": "published_price_minimums", "status": "starting_at",
                     "reason": "Published minimums do not establish an exact configuration or regional price."})
    public_status = _public_status(source)
    if collection_failed and public_status != "not_requested":
        public_status = "failed"
    return {
        "provider": provider, "collect_status": _status(source.get("status")),
        "public_collect_status": public_status, "all_prices_complete": False,
        "selected_scope": {"basis": "returned_records_after_caller_filters",
                           "source_type": source.get("source_type") if isinstance(source.get("source_type"), str) else None,
                           "source_url": source.get("source_url") if isinstance(source.get("source_url"), str) else None,
                           "filters": selected_filters, "fetched_record_count": fetched_count},
        "record_count": len(records), "considered_record_count": len(considered),
        "excluded_failed_source_record_count": len(records) - len(considered),
        "numeric_quoted_gpu_hour_count": len(numeric),
        "invalid_numeric_gpu_hour_record_count": sum(
            quote.get("unit") == "gpu_hour" and quote.get("quote_status") == "quoted" and not _numeric(quote)
            for quote in considered),
        "derived_calculation_count": len(derived),
        "derived_numeric_quoted_gpu_hour_count": sum(_derived(quote) for quote in numeric),
        "direct_record_count": len(direct),
        "direct_numeric_quoted_gpu_hour_count": sum(not _derived(quote) for quote in numeric),
        "contact_sales_count": sales, "starting_at_count": floors,
        "regional_record_count": sum(_regional(quote) for quote in considered),
        "numeric_regional_gpu_hour_count": sum(_regional(quote) for quote in numeric),
        "derived_calculation_by_origin": dict(sorted(Counter(
            str(quote.get("quote_origin") or "declared_configuration_calculation") for quote in derived).items())),
        "independent_source_counts": source_counts,
        "source_catalog_structure_counts": structure_counts,
        "source_published_spot_minimum_count": minimum_count,
        "source_count_scope": "source_catalog_before_caller_filters; not derived record counts or independent complete-instance quotes",
        "contract_record_count": contract_count or 0,
        "contract_records_scope": "private_account_audit_count_only" if contract_count is not None else "not_reported",
        "gaps": gaps,
    }


def report_catalog_audit(result: Mapping) -> dict:
    """Count selected records and original source sizes without fetching data.

    The report contains no raw quotes, configurations, source contexts or private
    contract records. Count categories overlap; no prices or source rate counts
    are summed into an estimated number of independent market quotations.
    """
    if not isinstance(result, Mapping) or not isinstance(result.get("prices"), list):
        raise ConfigurationError("catalog audit result must contain a prices list")
    prices = result["prices"]
    if any(not isinstance(quote, Mapping) or not isinstance(quote.get("provider"), str)
           or not quote["provider"] for quote in prices):
        raise ConfigurationError("catalog audit prices must contain provider quote objects")
    sources = result.get("provider_results", [])
    if not isinstance(sources, list) or any(not isinstance(source, Mapping)
                                           or not isinstance(source.get("provider"), str)
                                           or not source["provider"] for source in sources):
        raise ConfigurationError("catalog audit provider results must contain provider source objects")
    by_provider = {source["provider"]: source for source in sources}
    if len(by_provider) != len(sources):
        raise ConfigurationError("catalog audit provider results must contain unique providers")
    order = list(by_provider)
    order.extend(dict.fromkeys(quote["provider"] for quote in prices if quote["provider"] not in by_provider))
    entries = [_provider_entry(provider, by_provider.get(provider, {}),
                               [quote for quote in prices if quote["provider"] == provider],
                               collection_failed=result.get("status") == "failed") for provider in order]
    execution = result.get("execution")
    execution = execution if isinstance(execution, Mapping) else {}
    return {
        "schema_version": 1, "scope": "selected_scope", "all_prices_complete": False,
        "collection_status": _status(result.get("status")),
        "public_collect_status": _aggregate_status([entry["public_collect_status"] for entry in entries]),
        "selected_scope": {"basis": "returned_records_after_caller_filters",
                           "providers": order,
                           "source_policy": execution.get("source_policy") if isinstance(execution.get("source_policy"), str) else None,
                           "catalog_scope": execution.get("catalog_scope") if isinstance(execution.get("catalog_scope"), str) else None},
        "totals": {key: sum(entry[key] for entry in entries) for key in _COUNT_FIELDS},
        "providers": entries,
        "gaps": [{"provider": entry["provider"], **gap} for entry in entries for gap in entry["gaps"]],
        "notes": [
            "Counts describe the selected providers and returned records after caller filters, not an enumeration of the entire market.",
            "Official catalogs and APIs do not establish every private contract, account discount, resource configuration or sales-only price; all_prices_complete remains false even after successful collection.",
            "Derived configuration rows are calculations from source rates and presets, not additional independent provider quotations. Direct records include sales/floor listings; direct_numeric_quoted_gpu_hour_count counts exact numeric hourly records only.",
            "Original source rate/API counts remain separate and may precede caller filters. GPU rate groups, resource component rows, presets and Spot API records must not be added together as independent complete-instance quotations.",
            "Regional counts require explicit verified price-region or price-zone bindings. Platform coverage and capacity regions do not establish regional prices or stock.",
            "Contract records are represented by counts only and are not admitted as numeric GPU-hour quotations. Numeric catalog records do not establish availability, final bills or comparable reservation terms.",
        ],
    }
