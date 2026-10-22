"""Collect public or authenticated quotes and return data without persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, DecimalException

from .filters import apply_filters, filter_support, normalize_filters, price_location_values
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
API_SOURCE_TYPES = frozenset({"official_api", "official_quote_api", "official_public_api", "official_internal_api"})


def _selected_module(provider: str, settings: Settings | None = None):
    """Choose a deterministic adapter before I/O; never retry via another source."""
    if settings is None:
        return IMPLEMENTED_PROVIDERS.get(provider)
    prefer_api = settings.source_policy in {"api_preferred", "api_only"}
    if provider == "lambda" and settings.lambda_source == "console":
        from .providers import lambda_console_client
        return lambda_console_client
    if provider == "lambda" and (settings.lambda_source == "api" or (
        prefer_api and (settings.lambda_api_key or settings.source_policy == "api_only")
    )):
        return lambda_cloud
    if provider == "ucloud" and settings.ucloud_source == "console":
        from .providers import ucloud_console
        return ucloud_console
    if provider == "ucloud" and (settings.ucloud_source == "api" or (
        prefer_api and (settings.ucloud_public_key or settings.ucloud_private_key)
    )):
        # Partial account configuration must fail visibly, rather than returning
        # unrelated monthly promotions when the caller intended hourly quotes.
        return ucloud
    if provider == "ucloud" and prefer_api:
        return ucloud_compshare
    if provider == "nebius":
        if settings.nebius_source == "spot_api":
            from .providers import nebius_spot_catalog
            return nebius_spot_catalog
        if settings.nebius_source == "catalog_api":
            from .providers import nebius_account_catalog
            return nebius_account_catalog
        if settings.nebius_source == "api":
            from .providers import nebius_quote
            return nebius_quote
        if settings.catalog_scope == "complete" and settings.source_policy != "api_only":
            from .providers import nebius_catalog_expanded
            return nebius_catalog_expanded
        if prefer_api:
            from .providers import nebius_spot
            return nebius_spot
    if provider == "crusoe" and (settings.crusoe_source == "account" or (
            settings.crusoe_source == "combined" and settings.source_policy == "api_only")):
        from .providers import crusoe_account
        return crusoe_account
    if (provider == "crusoe" and settings.catalog_scope == "complete"
            and settings.source_policy != "api_only"):
        from .providers import crusoe_catalog
        return crusoe_catalog
    if provider == "autodl" and settings.autodl_source == "market":
        from .providers import autodl_market_api
        return autodl_market_api
    return IMPLEMENTED_PROVIDERS.get(provider)


def provider_source(provider: str, settings: Settings | None = None) -> str:
    """Return the selected source type without making any requests."""
    module = _selected_module(provider, settings)
    if provider == "lambda" and settings is not None and settings.lambda_source == "console":
        return "official_internal_api"
    if provider == "ucloud" and settings is not None and settings.ucloud_source == "console":
        return "official_internal_api"
    if module is lambda_cloud:
        if settings is not None and settings.catalog_scope == "complete" and settings.source_policy != "api_only":
            return "official_public_sources"
        return "official_api"
    if module is ucloud:
        return "official_quote_api"
    if provider == "nebius" and settings is not None and settings.nebius_source in {"api", "catalog_api"}:
        return "official_quote_api"
    if provider == "nebius" and settings is not None and settings.nebius_source == "spot_api":
        return "official_public_api"
    if provider == "crusoe" and settings is not None and settings.crusoe_source != "public":
        return "official_public_sources" if settings.crusoe_source == "combined" and settings.source_policy != "api_only" else "official_api"
    if provider == "crusoe" and settings is not None and settings.catalog_scope == "complete" and settings.source_policy != "api_only":
        return "official_public_sources"
    if provider == "nebius" and settings is not None and settings.catalog_scope == "complete" and settings.source_policy != "api_only":
        return "official_public_sources"
    if provider == "nebius" and settings is not None and settings.source_policy == "api_preferred":
        return "official_public_sources"
    if provider == "nebius" and settings is not None and settings.source_policy != "configured":
        return "official_public_api"
    if provider == "autodl" and settings is not None and settings.autodl_source == "market":
        return "official_internal_api"
    return PROVIDER_SOURCES[provider]


def _source_selection(provider: str, settings: Settings, module) -> dict:
    source = provider_source(provider, settings)
    if provider == "nebius" and settings.nebius_source == "spot_api":
        from .providers import nebius_regions, nebius_spot
        return {"collection_method": "http_json_with_documented_location_metadata",
                "selection_reason": "anonymous_current_spot_api_with_live_country_verification",
                "fallback_reason": None, "api_endpoint": nebius_spot.SOURCE_URL,
                "additional_source_urls": [nebius_regions.REGIONS_URL]}
    if provider == "autodl" and source == "official_internal_api":
        from .providers import autodl_regions
        return {"collection_method": "authenticated_http_json",
                "selection_reason": "explicit_market_session_catalog",
                "fallback_reason": None, "api_endpoint": module.SOURCE_URL,
                "additional_source_urls": [autodl_regions.REGIONS_URL]}
    if provider == "ucloud" and source == "official_internal_api":
        return {"collection_method": "authenticated_http_json",
                "selection_reason": "explicit_uhost_console_session_catalog",
                "fallback_reason": None, "api_endpoint": module.SOURCE_URL}
    if provider == "lambda" and source == "official_internal_api":
        from .providers import lambda_console
        return {"collection_method": "authenticated_http_json",
                "selection_reason": "explicit_console_session_catalog",
                "fallback_reason": None, "api_endpoint": lambda_console.INSTANCE_TYPES_URL,
                "additional_source_urls": [lambda_console.RESERVED_CLUSTER_TYPES_URL, lambda_console.REGIONS_URL]}
    if source == "official_public_sources":
        if provider == "lambda":
            from .providers import lambda_clusters
            return {"collection_method": "http_json_and_http_html",
                    "selection_reason": "account_instance_api_and_public_reserved_catalog",
                    "fallback_reason": None, "api_endpoint": lambda_cloud.SOURCE_URL,
                    "source_types": ["official_api", lambda_clusters.SOURCE_TYPE],
                    "additional_source_urls": [lambda_clusters.SOURCE_URL]}
        if provider == "crusoe":
            from .providers import crusoe_account
            if settings.catalog_scope == "complete":
                from .providers import crusoe_catalog
                combined = settings.crusoe_source == "combined"
                return {"collection_method": "http_html_documents_and_authenticated_json" if combined else "http_html_and_documents",
                        "selection_reason": "public_catalog_locations_and_account_contract_audit" if combined else "public_price_and_deployment_catalogs",
                        "fallback_reason": "no_verified_gpu_rental_price_api",
                        "api_endpoint": crusoe_account.API_ENDPOINT_TEMPLATE if combined else None,
                        "source_types": ["public_page", "public_documentation"] + (["official_api"] if combined else []),
                        "additional_source_urls": [crusoe_catalog.VM_TYPES_URL, crusoe_catalog.LOCATIONS_URL] + ([crusoe_account.SOURCE_URL] if combined else [])}
            return {"collection_method": "http_html_and_authenticated_json",
                    "selection_reason": "public_prices_and_account_contract_audit",
                    "fallback_reason": None, "api_endpoint": crusoe_account.API_ENDPOINT_TEMPLATE,
                    "source_types": ["public_page", "official_api"],
                    "additional_source_urls": [crusoe_account.SOURCE_URL]}
        from .providers import nebius_catalog, nebius_spot
        if settings.catalog_scope == "complete":
            from .providers import nebius_catalog_expanded
            return {"collection_method": "http_documents_and_json",
                    "selection_reason": "official_tariff_preset_calculations_and_regional_spot_api",
                    "fallback_reason": None, "api_endpoint": nebius_spot.SOURCE_URL,
                    "source_types": [nebius_catalog_expanded.SOURCE_TYPE, "official_public_api", nebius_catalog.SOURCE_TYPE],
                    "additional_source_urls": [nebius_catalog_expanded.TYPES_URL,
                                               nebius_catalog_expanded.REGIONS_URL,
                                               nebius_spot.SOURCE_URL, nebius_catalog.SOURCE_URL]}
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
    api_endpoint = (getattr(module, "API_ENDPOINT_TEMPLATE", None) or getattr(module, "API_URL", None)
                    or getattr(module, "SOURCE_URL", None)) if source in API_SOURCE_TYPES else None
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


def _source_error(module, exc: Exception) -> dict:
    """Project safe source failures without exposing configuration values."""
    if isinstance(exc, FetchError):
        error = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
    elif isinstance(exc, ConfigurationError):
        error = {"code": "configuration_error", "message": str(exc), "retryable": False}
    else:
        error = {"code": "parse_failed", "message": "The source structure or price fields were not recognized.", "retryable": False}
    return {"source_url": module.SOURCE_URL, **error}


def _record_outcome(result: dict, outcome: dict, module, *, supplement: bool = False) -> tuple[list[dict], list[dict]]:
    """Keep independently reported source coverage and audit data beside quotes."""
    quotes, errors = outcome["prices"], outcome.get("errors", [])
    if not isinstance(quotes, list) or not isinstance(errors, list):
        raise ValueError("Invalid source outcome")
    if outcome.get("audit_only") and quotes:
        raise ValueError("Audit-only records cannot be admitted as GPU prices")
    errors = list(errors)
    if outcome.get("status") in {"partial", "failed"} and not errors:
        # A discovered but unpriceable preset/project is a catalog gap even
        # when every HTTP request succeeded. Do not turn that into success.
        errors.append({"source_url": module.SOURCE_URL, "code": "incomplete_catalog",
                       "message": "The selected source reported incomplete coverage; inspect its gaps.",
                       "retryable": False})
    context = {key: value for key, value in outcome.items() if key not in {"prices", "contract_records"}}
    context.setdefault("source_url", module.SOURCE_URL)
    context.setdefault("source_type", getattr(module, "SOURCE_TYPE", None))
    result.setdefault("source_contexts", []).append(context)
    for key in ("catalog_coverage", "coverage", "contract_records", "contract_record_count",
                "pricing_limitations", "authentication_method", "api_endpoint_template",
                "excluded_non_gpu_records", "excluded_non_gpu_record_count", "regions_catalog",
                "country_region_catalog", "price_applicability_verification"):
        if key in outcome:
            result[key] = outcome[key]
    if "gaps" in outcome:
        result.setdefault("gaps", []).extend(outcome["gaps"])
    if outcome.get("audit_only"):
        context["account_scope"] = "private_account_contract_audit"
        result["contract_records_scope"] = "private_account_contract_audit"
        result["account_audit_only" if supplement else "audit_only"] = True
    result.setdefault("errors", []).extend(errors)
    return quotes, errors


def _complete_mode_gaps(provider: str, settings: Settings) -> list[dict]:
    if settings.catalog_scope != "complete" or settings.source_policy != "api_only":
        return []
    if provider == "lambda" and settings.lambda_source == "console":
        return []
    if provider == "nebius" and settings.nebius_source in {"catalog_api", "spot_api"}:
        return []
    scope = {"nebius": "public_on_demand_preset_catalog", "lambda": "public_reserved_cluster_catalog",
             "crusoe": "public_gpu_price_catalog"}.get(provider)
    return ([{"scope": scope, "status": "source_policy_excluded",
              "reason": "API-only mode does not collect the independent public document/page catalog."}]
            if scope else [])


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
        if settings.catalog_scope == "complete":
            result["catalog_scope"] = "complete"
            result["gaps"] = _complete_mode_gaps(provider, settings)
        if provider == "crusoe" and (settings.crusoe_source == "account" or (
                settings.crusoe_source == "combined" and settings.source_policy == "api_only")):
            result["audit_only"] = True
            result["contract_records_scope"] = "private_account_contract_audit"
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
                is_authenticated = provider_source(provider, settings) in {"official_api", "official_quote_api", "official_internal_api", "authorized_browser"}
                target_errors = []
                source_errors = []
                completed_sources = 0
                uses_outcome = hasattr(module, "collect_result")
                if (provider == "crusoe" and settings.crusoe_source == "combined"
                        and settings.source_policy != "api_only"):
                    from .providers import crusoe_account
                    observed_at, quotes = _now(), []
                    # Public prices and account contracts are independent. A
                    # failure in either source must leave the other reviewable.
                    try:
                        if hasattr(module, "collect_result"):
                            outcome = module.collect_result(settings=settings, observed_at=observed_at)
                            public_quotes, errors = _record_outcome(result, outcome, module)
                            source_errors.extend(errors)
                            completed_sources += int(outcome.get("status") not in {"failed", "partial"})
                        else:
                            content = fetch_text(module.SOURCE_URL, settings)
                            public_quotes = module.parse_prices(content, observed_at=observed_at,
                                                                as_of=datetime.fromisoformat(observed_at).date())
                            result.setdefault("source_contexts", []).append({"source_url": module.SOURCE_URL,
                                                                             "source_type": "public_page", "status": "ok",
                                                                             "record_count": len(public_quotes)})
                            completed_sources += 1
                        _check_prices(public_quotes, provider, allow_empty=True)
                        quotes.extend(public_quotes)
                    except (FetchError, ValueError, KeyError, TypeError, DecimalException) as exc:
                        source_errors.append(_source_error(module, exc))
                    try:
                        outcome = crusoe_account.collect_result(settings=settings, observed_at=observed_at)
                        audit_quotes, errors = _record_outcome(result, outcome, crusoe_account, supplement=True)
                        if audit_quotes:
                            raise ValueError("Account contract audit must not emit GPU prices")
                        source_errors.extend(errors)
                        if outcome.get("status") not in {"failed", "partial"}:
                            completed_sources += 1
                    except (FetchError, ValueError, KeyError, TypeError, DecimalException) as exc:
                        source_errors.append(_source_error(crusoe_account, exc))
                    uses_outcome = True
                elif module is ucloud_compshare:
                    observed_at = _now()
                    outcome = module.collect_result(settings=settings, observed_at=observed_at,
                                                    regions=conditions[provider].get("regions"),
                                                    zones=conditions[provider].get("zones"))
                    quotes = outcome["prices"]
                    target_errors = outcome["errors"]
                    result["discovery"] = outcome["discovery"]
                    result["target_errors"] = target_errors
                    result["product_line"] = module.PRODUCT_LINE
                elif provider == "ucloud" and settings.ucloud_source == "console":
                    observed_at = _now()
                    outcome = module.collect_result(settings=settings, observed_at=observed_at,
                                                    regions=conditions[provider].get("regions"),
                                                    zones=conditions[provider].get("zones"),
                                                    gpu_models=conditions[provider].get("gpu_models"))
                    quotes, source_errors = _record_outcome(result, outcome, module)
                    completed_sources = int(outcome.get("status") not in {"failed", "partial"})
                elif uses_outcome:
                    observed_at = _now()
                    outcome = module.collect_result(settings=settings, observed_at=observed_at)
                    quotes, source_errors = _record_outcome(result, outcome, module)
                    completed_sources = int(outcome.get("status") not in {"failed", "partial"})
                elif hasattr(module, "collect_quotes"):
                    observed_at = _now()
                    extra = {"include_geography": True} if module is ucloud else {}
                    quotes = module.collect_quotes(settings=settings, observed_at=observed_at, **extra)
                    completed_sources = 1
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
                    if (module is lambda_cloud and settings.catalog_scope == "complete"
                            and settings.source_policy != "api_only"):
                        from .providers import lambda_clusters
                        result["catalog_coverage"] = {"account_instance_quote_count": len(quotes),
                                                      "public_cluster_record_count": 0}
                        result.setdefault("source_contexts", []).append({"source_url": lambda_cloud.SOURCE_URL,
                                                                         "source_type": "official_api", "status": "ok",
                                                                         "record_count": len(quotes)})
                        # Account API failure exits before this independent
                        # reserved catalog is requested; it is not a fallback.
                        try:
                            cluster_quotes = lambda_clusters.collect_quotes(settings=settings, observed_at=observed_at)
                            _check_prices(cluster_quotes, provider)
                            quotes.extend(cluster_quotes)
                            result["catalog_coverage"] = {"account_instance_quote_count": len(quotes) - len(cluster_quotes),
                                                          "public_cluster_record_count": len(cluster_quotes)}
                            result.setdefault("source_contexts", []).append({"source_url": lambda_clusters.SOURCE_URL,
                                                                             "source_type": lambda_clusters.SOURCE_TYPE,
                                                                             "status": "ok", "record_count": len(cluster_quotes)})
                        except (FetchError, ValueError, KeyError, TypeError, DecimalException) as exc:
                            source_errors.append(_source_error(lambda_clusters, exc))
                            result.setdefault("gaps", []).append({"scope": "public_reserved_cluster_catalog", "status": "collection_failed"})
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
                if source_errors:
                    result["source_errors"] = source_errors
                _check_prices(quotes, provider, allow_empty=is_authenticated or uses_outcome or module is lambda_cloud,
                              expected_units=("gpu_month",) if module is ucloud_public else
                              ("gpu_hour", "gpu_month") if provider == "nebius" and settings.nebius_source == "api" else ("gpu_hour",))
                for quote in quotes:
                    describe_geography(quote)
                if settings.catalog_scope == "complete":
                    coverage = result.setdefault("catalog_coverage", {})
                    coverage["collected_record_count"] = len(quotes)
                    coverage["numeric_hourly_record_count"] = sum(
                        q["unit"] == "gpu_hour" and q["quote_status"] == "quoted" and q["amount"] is not None
                        for q in quotes)
                    coverage["contact_sales_record_count"] = sum(q["quote_status"] == "contact_sales" for q in quotes)
                    if provider == "lambda":
                        result["gaps"].append({"scope": "negotiated_or_account_specific_prices",
                                               "status": "not_established_by_selected_catalog",
                                               "reason": "Public or API instance catalogs do not establish every account-specific agreement or sales-only price."})
                    if result.get("audit_only") or result.get("account_audit_only"):
                        result["gaps"].append({"scope": "crusoe_contract_gpu_hour_prices",
                                               "status": "unit_currency_and_gpu_product_unverified",
                                               "reason": "Existing account contracts are audit records; no GPU-hour price is inferred."})
                result["fetched_count"] = len(quotes)
                candidates = quotes
                if any(conditions[provider].get(k) for k in ("regions", "zones", "compute_countries")):
                    # A requested price location never matches bare capacity.
                    # A verified shared-SKU price flow can establish catalog
                    # applicability without inventing independent region quotes.
                    # Region-bound rows with missing country evidence remain
                    # candidates, so the existing unverifiable check applies.
                    candidates = [q for q in quotes if q["region_price_verified"]
                                  or (price_location_values(q, "regions")
                                      and price_location_values(q, "compute_countries"))]
                    result["excluded_unbound_geography_count"] = len(quotes) - len(candidates)
                unverified = []
                for dimension in ("regions", "zones", "compute_countries"):
                    other_conditions = {k: v for k, v in conditions[provider].items() if k != dimension}
                    relevant = apply_filters(candidates, other_conditions)
                    if conditions[provider].get(dimension) and any(not price_location_values(q, dimension) for q in relevant):
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
                    result["status"] = "success" if matched or result.get("audit_only") else "no_matches"
                    if target_errors:
                        result["status"] = "partial" if matched else "failed"
                        result["error"] = {"code": "partial_collection" if matched else "quote_failed",
                                           "message": "One or more CompShare hourly quotation targets failed; inspect target_errors.",
                                           "retryable": any(error.get("retryable") for error in target_errors)}
                    elif source_errors:
                        result["status"] = "partial" if matched or completed_sources else "failed"
                        result["error"] = {"code": "partial_collection",
                                           "message": "One or more independent sources failed; successful quotes and audit records are retained. Inspect source_errors.",
                                           "retryable": any(error.get("retryable") for error in source_errors)}
            except ConfigurationError as exc:
                result["error"] = {"code": "configuration_error", "message": str(exc), "retryable": False}
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
                      "source_policy": settings.source_policy, "catalog_scope": settings.catalog_scope},
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
    if "lambda" in selected and settings.lambda_source == "console":
        from .providers.lambda_locations import validated_applicability_locations
        catalog_locations = [locations for quote in prices
                             if (locations := validated_applicability_locations(quote))]
        result["catalog_applicability"] = {
            "scope": "shared_catalog_currently_selectable_regions",
            "quote_count": len(catalog_locations),
            "country_codes": sorted({location["country_code"]
                                      for locations in catalog_locations for location in locations}),
            "region_codes": sorted({location["region"]
                                     for locations in catalog_locations for location in locations}),
            "independent_regional_quotes": False,
        }
    if include_coverage:
        from .coverage import report_coverage

        result["coverage"] = report_coverage(result)
    if settings.catalog_scope == "complete":
        from .catalog_audit import report_catalog_audit
        result["catalog_audit"] = report_catalog_audit(result)
    return result
