"""Collect public or authenticated quotes and return data without persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .filters import apply_filters, filter_support, normalize_filters
from .providers import autodl, crusoe, lambda_cloud, lambda_public, nebius, ucloud
from .settings import ConfigurationError, PROVIDERS, Settings
from .transport import FetchError, fetch_text

IMPLEMENTED_PROVIDERS = {"nebius": nebius, "crusoe": crusoe, "lambda": lambda_public,
                         "ucloud": ucloud, "autodl": autodl}
PROVIDER_SOURCES = {"nebius": "public_documentation", "crusoe": "public_page",
                    "lambda": "public_page", "ucloud": "official_quote_api", "autodl": "public_page"}


def provider_source(provider: str, settings: Settings | None = None) -> str:
    """Return the selected source type without making any requests."""
    if provider == "lambda" and settings is not None and settings.lambda_source == "api":
        return "official_api"
    return PROVIDER_SOURCES[provider]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_prices(prices: list[dict], provider: str, *, allow_empty: bool = False) -> None:
    if not isinstance(prices, list) or (not prices and not allow_empty):
        raise ValueError("No recognizable GPU price records were found.")
    for quote in prices:
        if quote["provider"] != provider or quote["unit"] != "gpu_hour":
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
) -> dict:
    """Fetch configured prices. This function never uploads or saves data.

    Explicit providers override settings.providers. Global filters override
    per-provider filters by key. Unsupported filter dimensions fail that source
    rather than returning an unverified match. Runtime errors stay per-source;
    invalid call configuration raises ConfigurationError before any requests.
    """
    settings = settings if settings is not None else Settings.from_env()
    if not isinstance(settings, Settings):
        raise ConfigurationError("settings must be a Settings instance")
    if providers is None:
        selected = settings.providers
    elif isinstance(providers, (list, tuple)):
        selected = tuple(providers)
    else:
        raise ConfigurationError("providers must be a list or tuple")
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
        module = IMPLEMENTED_PROVIDERS.get(provider)
        if provider == "lambda" and settings.lambda_source == "api":
            module = lambda_cloud
        result = {
            "provider": provider, "source_url": module.SOURCE_URL if module else None,
            "source_type": provider_source(provider, settings) if module else None,
            "status": "failed", "observed_at": None, "fetched_count": 0,
            "returned_count": 0, "filters": filter_support(provider, conditions[provider]),
            "error": None,
        }
        if module is None:
            result["error"] = {"code": "not_implemented", "message": "This provider adapter is not implemented.", "retryable": False}
        elif any(item["status"] == "unsupported" for item in result["filters"].values()):
            result["error"] = {"code": "unsupported_filter", "message": "The source cannot verify one or more requested conditions.", "retryable": False}
        else:
            try:
                is_authenticated = module in (lambda_cloud, ucloud)
                if hasattr(module, "collect_quotes"):
                    observed_at = _now()
                    quotes = module.collect_quotes(settings=settings, observed_at=observed_at)
                else:
                    content = fetch_text(module.SOURCE_URL, settings)
                    observed_at = _now()
                    quotes = module.parse_prices(content, observed_at=observed_at, as_of=datetime.fromisoformat(observed_at).date())
                result["observed_at"] = observed_at
                _check_prices(quotes, provider, allow_empty=is_authenticated)
                result["fetched_count"] = len(quotes)
                other_conditions = {k: v for k, v in conditions[provider].items() if k != "regions"}
                relevant = apply_filters(quotes, other_conditions)
                if conditions[provider].get("regions") and any(not q["regions"] for q in relevant):
                    result["filters"]["regions"]["status"] = "unverifiable"
                    result["filters"]["regions"]["reason"] = "One or more relevant quotes do not state applicable regions."
                    result["error"] = {"code": "unverifiable_filter", "message": "The source does not state regions for all relevant quotes.", "retryable": False}
                else:
                    matched = apply_filters(quotes, conditions[provider])
                    prices.extend(matched)
                    result["returned_count"] = len(matched)
                    result["status"] = "success" if matched else "no_matches"
            except FetchError as exc:
                result["error"] = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
            except (ValueError, KeyError, TypeError, InvalidOperation):
                result["error"] = {"code": "parse_failed", "message": "The source structure, dates or price fields were not recognized.", "retryable": False}
        # A filter was only applied if the source actually succeeded.
        if result["status"] == "failed":
            for item in result["filters"].values():
                if item["status"] == "applied_locally":
                    item["status"] = "not_applied"
        results.append(result)
    successful = sum(result["status"] in {"success", "no_matches"} for result in results)
    return {
        "schema_version": 1,
        "collected_at": _now(),
        "status": "success" if successful == len(results) else "partial" if successful else "failed",
        "prices": prices,
        "provider_results": results,
    }
