"""Collect public or authenticated quotes and return data without persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, DecimalException

from .filters import apply_filters, filter_support, normalize_filters
from .geography import describe_geography, geography_summary
from .csv_export import market_eligible_quote, publishable_quote
from .providers import (autodl, azure, crusoe, digitalocean, lambda_cloud, lambda_public,
                        nebius, runpod, ucloud, ucloud_compshare, ucloud_public, verda)
from .settings import ConfigurationError, PROVIDERS, Settings
from .transport import FetchError, fetch_text

IMPLEMENTED_PROVIDERS = {"nebius": nebius, "crusoe": crusoe, "lambda": lambda_public,
                         "ucloud": ucloud_public, "autodl": autodl,
                         "runpod": runpod, "digitalocean": digitalocean,
                         "verda": verda, "azure": azure}
PROVIDER_SOURCES = {"nebius": "public_documentation", "crusoe": "public_page",
                    "lambda": "public_page", "ucloud": "official_public_api", "autodl": "public_page",
                    "runpod": "official_public_api", "digitalocean": "public_documentation",
                    "verda": "public_page", "azure": "official_public_api"}
API_SOURCE_TYPES = frozenset({"official_api", "official_quote_api", "official_public_api"})


def _selected_module(provider: str, settings: Settings | None = None):
    """Choose a deterministic adapter before I/O; never retry via another source."""
    if settings is None:
        return IMPLEMENTED_PROVIDERS.get(provider)
    prefer_api = settings.source_policy in {"api_preferred", "api_only"}
    if provider == "lambda" and (settings.lambda_source == "api" or (
        prefer_api and (settings.lambda_api_key or settings.source_policy == "api_only")
    )):
        return lambda_cloud
    if provider == "ucloud" and (settings.ucloud_source == "api" or (
        prefer_api and (settings.ucloud_public_key or settings.ucloud_private_key)
    )):
        # Partial account configuration must fail visibly, rather than returning
        # unrelated monthly promotions when the caller intended hourly quotes.
        return ucloud
    if provider == "ucloud" and prefer_api:
        return ucloud_compshare
    if provider == "nebius":
        if settings.nebius_source == "api":
            from .providers import nebius_quote
            return nebius_quote
        if prefer_api:
            from .providers import nebius_spot
            return nebius_spot
    if provider == "autodl" and settings.autodl_source == "market":
        from .providers import autodl_market
        return autodl_market
    return IMPLEMENTED_PROVIDERS.get(provider)


def provider_source(provider: str, settings: Settings | None = None) -> str:
    """Return the selected source type without making any requests."""
    module = _selected_module(provider, settings)
    if module is lambda_cloud:
        return "official_api"
    if module is ucloud:
        return "official_quote_api"
    if provider == "nebius" and settings is not None and settings.nebius_source == "api":
        return "official_quote_api"
    if provider == "nebius" and settings is not None and settings.source_policy == "api_preferred":
        return "official_public_sources"
    if provider == "nebius" and settings is not None and settings.source_policy != "configured":
        return "official_public_api"
    if provider == "autodl" and settings is not None and settings.autodl_source == "market":
        return "authorized_browser"
    return PROVIDER_SOURCES[provider]


def _source_selection(provider: str, settings: Settings, module) -> dict:
    source = provider_source(provider, settings)
    if source == "official_public_sources":
        from .providers import nebius_catalog, nebius_spot
        return {"collection_method": "http_json_with_website_bootstrap",
                "selection_reason": "regional_spot_api_and_on_demand_website_json",
                "fallback_reason": None, "api_endpoint": nebius_spot.SOURCE_URL,
                "source_types": ["official_public_api", nebius_catalog.SOURCE_TYPE],
                "additional_source_urls": [nebius_catalog.SOURCE_URL]}
    method = ("http_json" if source in API_SOURCE_TYPES else
              "browser_dom" if provider == "autodl" else
              "hybrid_http" if module is nebius else
              "http_document" if source == "public_documentation" else "http_html")
    reason, fallback = "configured_source", None
    if settings.source_policy != "configured":
        if source in API_SOURCE_TYPES:
            reason = "api_selected"
            if provider == "nebius" and settings.nebius_source == "public":
                reason = "anonymous_regional_spot_api"
            elif module is ucloud_public:
                reason = "anonymous_monthly_promotion_api"
            elif module is ucloud_compshare:
                reason = "anonymous_compshare_hourly_quote_api"
        else:
            if settings.source_policy == "api_only":
                reason = "api_required_but_unavailable"
            else:
                reason = "programmatic_page_fallback"
                fallback = ("api_credentials_not_configured" if provider == "lambda" else
                            "no_verified_gpu_rental_price_api" if provider == "crusoe" else
                            "no_verified_market_price_api" if provider == "autodl" else
                            "no_configured_public_price_api_adapter")
    api_endpoint = (getattr(module, "API_URL", None) or getattr(module, "SOURCE_URL", None)) if source in API_SOURCE_TYPES else None
    return {"collection_method": method, "selection_reason": reason, "fallback_reason": fallback,
            "api_endpoint": api_endpoint}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_prices(prices: list[dict], provider: str, *, allow_empty: bool = False,
                  expected_units: tuple[str, ...] = ("gpu_hour",)) -> None:
    if not isinstance(prices, list) or (not prices and not allow_empty):
        raise ValueError("No recognizable GPU price records were found.")
    for quote in prices:
        if quote["provider"] != provider or quote["unit"] not in expected_units:
            raise ValueError("Unrecognized provider or price unit.")
        if quote["quote_status"] == "contact_sales":
            if quote["amount"] is not None:
                raise ValueError("A sales inquiry must not contain an amount.")
        else:
            if not isinstance(quote["amount"], str):
                raise ValueError("Amounts must be decimal strings.")
            amount = Decimal(quote["amount"])
            if not amount.is_finite() or amount < 0:
                raise ValueError("Invalid price amount.")
        quote.setdefault("product_type", "gpu_instance")


def collect_prices(
    providers: Sequence[str] | None = None,
    filters: Mapping | None = None,
    *,
    settings: Settings | None = None,
    provider_filters: Mapping[str, Mapping] | None = None,
    include_coverage: bool = False,
) -> dict:
    """Fetch configured prices. This function never uploads or saves data.

    Explicit providers override settings.providers; "all" selects every
    implemented collector. Global filters override
    per-provider filters by key. Unsupported filter dimensions fail that source
    rather than returning an unverified match. Runtime errors stay per-source;
    invalid call configuration raises ConfigurationError before any requests.
    Optional coverage describes GPU families represented by the returned
    records, without combining prices, currencies or purchase conditions.
    """
    settings = settings if settings is not None else Settings.from_env()
    if not isinstance(settings, Settings):
        raise ConfigurationError("settings must be a Settings instance")
    if type(include_coverage) is not bool:
        raise ConfigurationError("include_coverage must be boolean")
    if providers is None:
        selected = settings.providers
    elif isinstance(providers, str) and providers == "all":
        selected = tuple(IMPLEMENTED_PROVIDERS)
    elif isinstance(providers, (list, tuple)):
        selected = tuple(providers)
    else:
        raise ConfigurationError("providers must be a list, tuple or the string all")
    if (not selected or any(not isinstance(p, str) or p not in PROVIDERS for p in selected)
            or len(set(selected)) != len(selected)):
        raise ConfigurationError("providers must contain unique supported provider names")
    global_filters = normalize_filters(filters)
    if provider_filters is None:
        provider_filters = {}
    if not isinstance(provider_filters, Mapping) or set(provider_filters) - set(selected):
        raise ConfigurationError("provider_filters must reference selected providers only")
    conditions = {}
    for provider in selected:
        conditions[provider] = normalize_filters(provider_filters.get(provider))
        conditions[provider].update(global_filters)

    prices, results = [], []
    for provider in selected:
        module = _selected_module(provider, settings)
        result = {
            "provider": provider, "source_url": module.SOURCE_URL if module else None,
            "source_type": provider_source(provider, settings) if module else None,
            "status": "failed", "observed_at": None, "fetched_count": 0,
            "returned_count": 0, "filters": filter_support(provider, conditions[provider], settings=settings),
            "error": None,
            **_source_selection(provider, settings, module),
        }
        if module is nebius:
            from .providers import nebius_spot
            result["additional_source_urls"] = [nebius_spot.SOURCE_URL]
        if module is None:
            result["error"] = {"code": "not_implemented", "message": "This provider adapter is not implemented.", "retryable": False}
        elif settings.source_policy == "api_only" and result["source_type"] not in API_SOURCE_TYPES:
            result["error"] = {"code": "api_price_source_unavailable", "message": "No suitable price API adapter is selected; API-only mode forbids page and browser collection.", "retryable": False}
        elif any(item["status"] == "unsupported" for item in result["filters"].values()):
            result["error"] = {"code": "unsupported_filter", "message": "The source cannot verify one or more requested conditions.", "retryable": False}
        else:
            try:
                is_authenticated = provider_source(provider, settings) in {"official_api", "official_quote_api", "authorized_browser"}
                target_errors = []
                source_errors = []
                if module is ucloud_compshare:
                    observed_at = _now()
                    outcome = module.collect_result(settings=settings, observed_at=observed_at,
                                                    regions=conditions[provider].get("regions"),
                                                    zones=conditions[provider].get("zones"))
                    quotes = outcome["prices"]
                    target_errors = outcome["errors"]
                    result["discovery"] = outcome["discovery"]
                    result["target_errors"] = target_errors
                    result["product_line"] = module.PRODUCT_LINE
                elif hasattr(module, "collect_quotes"):
                    observed_at = _now()
                    extra = {"include_geography": True} if module is ucloud else {}
                    quotes = module.collect_quotes(settings=settings, observed_at=observed_at, **extra)
                    if (provider == "nebius" and settings.nebius_source == "public"
                            and settings.source_policy == "api_preferred"):
                        from .providers import nebius_catalog
                        # The regional API must succeed first. The independent
                        # website JSON supplies on-demand catalog rows, never
                        # replacement prices after a failed API request.
                        try:
                            quotes.extend(nebius_catalog.collect_quotes(settings=settings, observed_at=_now()))
                        except FetchError as exc:
                            source_errors.append({"source_url": nebius_catalog.SOURCE_URL,
                                                  "code": exc.code, "message": str(exc),
                                                  "retryable": exc.retryable})
                        result["source_errors"] = source_errors
                else:
                    content = fetch_text(module.SOURCE_URL, settings)
                    observed_at = _now()
                    quotes = module.parse_prices(content, observed_at=observed_at, as_of=datetime.fromisoformat(observed_at).date())
                    if module is nebius:
                        # The document's From prices are only floors. The
                        # anonymous official API supplies actual regional Spot
                        # rates, including their separate effective times.
                        quotes.extend(nebius_spot.collect_quotes(settings=settings, observed_at=_now()))
                result["observed_at"] = observed_at
                _check_prices(quotes, provider, allow_empty=is_authenticated or module is ucloud_compshare,
                              expected_units=("gpu_month",) if module is ucloud_public else
                              ("gpu_hour", "gpu_month") if provider == "nebius" and settings.nebius_source == "api" else ("gpu_hour",))
                for quote in quotes:
                    describe_geography(quote)
                result["fetched_count"] = len(quotes)
                candidates = quotes
                if any(conditions[provider].get(k) for k in ("regions", "zones", "compute_countries")):
                    # A requested price location never matches platform
                    # coverage or a catalog without a price-region binding.
                    # Region-bound rows with missing country evidence remain
                    # candidates, so the existing unverifiable check applies.
                    candidates = [q for q in quotes if q["region_price_verified"]]
                    result["excluded_unbound_geography_count"] = len(quotes) - len(candidates)
                unverified = []
                for dimension in ("regions", "zones", "compute_countries"):
                    other_conditions = {k: v for k, v in conditions[provider].items() if k != dimension}
                    relevant = apply_filters(candidates, other_conditions)
                    if conditions[provider].get(dimension) and any(not q.get(dimension) for q in relevant):
                        result["filters"][dimension]["status"] = "unverifiable"
                        result["filters"][dimension]["reason"] = "One or more relevant quotes lack verified source location metadata."
                        unverified.append(dimension)
                if unverified:
                    result["error"] = {"code": "unverifiable_filter", "message": "The source cannot verify all requested geographic conditions.", "retryable": False}
                else:
                    matched = apply_filters(candidates, conditions[provider])
                    prices.extend(matched)
                    result["geography"] = geography_summary(matched)
                    result["returned_count"] = len(matched)
                    result["status"] = "success" if matched else "no_matches"
                    if target_errors:
                        result["status"] = "partial" if matched else "failed"
                        result["error"] = {"code": "partial_collection" if matched else "quote_failed",
                                           "message": "One or more CompShare hourly quotation targets failed; inspect target_errors.",
                                           "retryable": any(error.get("retryable") for error in target_errors)}
                    elif source_errors:
                        result["status"] = "partial" if matched else "failed"
                        result["error"] = {"code": "partial_collection",
                                           "message": "The independent on-demand website catalog failed; successful regional Spot quotes are retained. Inspect source_errors.",
                                           "retryable": any(error.get("retryable") for error in source_errors)}
            except FetchError as exc:
                result["error"] = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
            except (ValueError, KeyError, TypeError, DecimalException):
                result["error"] = {"code": "parse_failed", "message": "The source structure, dates or price fields were not recognized.", "retryable": False}
        # A filter was only applied if the source actually succeeded.
        if result["status"] == "failed":
            for item in result["filters"].values():
                if item["status"] == "applied_locally":
                    item["status"] = "not_applied"
        results.append(result)
    successful = sum(result["status"] in {"success", "no_matches"} for result in results)
    for source_result in results:
        source_quotes = [quote for quote in prices if quote["provider"] == source_result["provider"]]
        source_result["market_quote_count"] = sum(market_eligible_quote(q) for q in source_quotes)
        source_result["regional_hourly_quote_count"] = sum(publishable_quote(q) for q in source_quotes)
    market_quotes = [quote for quote in prices if market_eligible_quote(quote)]
    result = {
        "schema_version": 1,
        "collected_at": _now(),
        "status": "success" if successful == len(results) else "partial" if successful or any(
            source["status"] == "partial" for source in results) else "failed",
        "execution": {"runtime": "python", "parsing": "deterministic_rules", "uses_llm": False,
                      "source_policy": settings.source_policy},
        "prices": prices,
        "provider_results": results,
        "geographic_coverage": geography_summary(prices),
        "comparison": {
            "scope": "verified_regional_gpu_hour",
            "eligible_quote_count": sum(publishable_quote(q) for q in prices),
            "excluded_quote_count": sum(not publishable_quote(q) for q in prices),
        },
        "market_comparison": {
            "scope": "catalog_and_regional_gpu_hour",
            "eligible_quote_count": len(market_quotes),
            "regional_quote_count": sum(publishable_quote(q) for q in market_quotes),
            "catalog_quote_count": sum(not publishable_quote(q) for q in market_quotes),
            "excluded_quote_count": len(prices) - len(market_quotes),
            "providers_with_quotes": [source["provider"] for source in results if source["market_quote_count"]],
        },
    }
    if include_coverage:
        from .coverage import report_coverage

        result["coverage"] = report_coverage(result)
    return result
