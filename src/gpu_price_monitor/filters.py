"""Validate requested conditions and report unsupported source dimensions."""

from collections.abc import Mapping

from .settings import ConfigurationError, Settings
from .providers.lambda_locations import validated_applicability_locations

FILTER_FIELDS = frozenset({
    "compute_countries", "sales_countries", "regions", "zones",
    "gpu_models", "gpu_counts", "billing_modes", "currencies",
    "coverage_regions", "coverage_countries",
})
BILLING_MODES = frozenset({"on_demand", "spot", "reserved", "monthly", "yearly"})


def normalize_filters(filters: Mapping | None) -> dict[str, list]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping) or set(filters) - FILTER_FIELDS:
        raise ConfigurationError("filters must be a mapping of supported condition names")
    result = {}
    for name, values in filters.items():
        if not isinstance(values, (list, tuple)):
            raise ConfigurationError("each filter must be a list or tuple")
        if name == "gpu_counts":
            if any(type(value) is not int or value <= 0 for value in values):
                raise ConfigurationError("gpu_counts must contain positive integers")
            normalized = list(values)
        else:
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ConfigurationError("string filters must contain non-empty strings")
            normalized = [value.strip() for value in values]
            if name in {"compute_countries", "sales_countries", "currencies", "coverage_countries"}:
                normalized = [value.upper() for value in normalized]
                length = 3 if name == "currencies" else 2
                if any(len(value) != length or not value.isascii() or not value.isalpha() for value in normalized):
                    raise ConfigurationError("country and currency filters must use ISO code format")
            if name == "billing_modes" and any(value not in BILLING_MODES for value in normalized):
                raise ConfigurationError("billing_modes contains an unsupported mode")
        result[name] = list(dict.fromkeys(normalized))
    return result


def filter_support(provider: str, filters: dict[str, list], *, settings: Settings | None = None) -> dict:
    supported = {"gpu_models", "currencies", "billing_modes"}
    if provider == "nebius":
        if settings is not None and settings.nebius_source in {"api", "catalog_api"}:
            supported.update({"regions", "compute_countries", "gpu_counts"})
        elif settings is not None and settings.nebius_source == "spot_api":
            supported.update({"regions", "compute_countries"})
        else:
            supported.update({"regions", "compute_countries"})
            complete_public = (settings is not None and settings.catalog_scope == "complete"
                               and settings.source_policy != "api_only")
            if complete_public:
                supported.add("gpu_counts")
            if settings is None or settings.source_policy == "configured" or complete_public:
                supported.update({"coverage_regions", "coverage_countries"})
    if provider in {"lambda", "digitalocean", "verda", "azure"}:
        supported.add("gpu_counts")
    if provider == "lambda" and settings is not None and settings.lambda_source in {"console", "visible"}:
        supported.update({"regions", "compute_countries"})
    if provider == "azure":
        supported.update({"regions", "compute_countries"})
    if provider == "autodl" and settings is not None and settings.autodl_source == "market":
        supported.add("regions")
    if provider == "ucloud":
        supported.update({"compute_countries", "regions", "zones", "gpu_counts"})
        reason = ("Matched against official UHost console catalog locations and regional quotation request fields; a quote does not establish current stock."
                  if settings is not None and settings.ucloud_source == "console" else
                  "Matched against the configured quotation request context; availability was not verified."
                  if settings is not None and (settings.ucloud_source == "api" or settings.source_policy != "configured") else
                  "Matched against public package configurations and the provider's region/zone mapping; listings do not establish orderability.")
    else:
        reason = "Matched against explicit quote fields; capacity regions do not establish regional prices."
    if (provider == "crusoe" and settings is not None and settings.catalog_scope == "complete"
            and settings.source_policy != "api_only" and settings.crusoe_source != "account"):
        supported.update({"coverage_regions", "coverage_countries"})
    if provider == "lambda" and settings is not None and settings.lambda_source in {"console", "visible"}:
        reason = ("Matched against the selectable countries/regions sharing this exact SKU's standard "
                  "console catalog price, after source-version verification; not an independent regional quotation.")
    return {
        name: {
            "requested": values,
            "status": "applied_locally" if name in supported else "unsupported",
            "reason": (
                ("Matched only documented platform coverage; this does not verify a regional price or stock."
                 if name in {"coverage_regions", "coverage_countries"} else reason)
                if name in supported else
                "The selected collector does not support verifying this filter."
            ),
        }
        for name, values in filters.items() if values
    }


def price_location_values(quote: dict, dimension: str) -> list:
    """Keep shared catalog applicability separate from independent price fields."""
    if dimension in {"compute_countries", "regions"}:
        locations = validated_applicability_locations(quote)
        if locations is not None:
            key = "country_code" if dimension == "compute_countries" else "region"
            return list(dict.fromkeys(location[key] for location in locations))
    return quote.get(dimension, [])


def apply_filters(prices: list[dict], filters: dict[str, list]) -> list[dict]:
    result = []
    for quote in prices:
        match = True
        locations = validated_applicability_locations(quote)
        if (quote.get("provider") == "crusoe" and filters.get("coverage_countries")
                and filters.get("coverage_regions") and "coverage_locations" in quote):
            # A multi-country deployment catalog must match a country and its
            # own region together; two unrelated locations are not a match.
            coverage = quote["coverage_locations"]
            if not isinstance(coverage, list) or not any(
                isinstance(location, dict)
                and location.get("country_code") in filters["coverage_countries"]
                and location.get("region") in filters["coverage_regions"] for location in coverage
            ):
                continue
        if locations is not None and filters.get("compute_countries") and filters.get("regions"):
            # A country and region must refer to the same applicable location,
            # rather than matching two unrelated entries of a multi-country SKU.
            match = any(location["country_code"] in filters["compute_countries"]
                        and location["region"] in filters["regions"] for location in locations)
            if not match:
                continue
        for name, values in filters.items():
            if not values:
                continue
            if name in {"regions", "zones", "compute_countries", "sales_countries", "coverage_regions", "coverage_countries"}:
                match = bool(set(values) & set(price_location_values(quote, name)))
            elif name == "gpu_counts":
                match = quote.get("gpu_count") in values
            else:
                field = {"gpu_models": "gpu_model", "currencies": "currency", "billing_modes": "billing_mode"}[name]
                match = str(quote[field]).casefold() in {value.casefold() for value in values}
            if not match:
                break
        if match:
            result.append(quote)
    return result
