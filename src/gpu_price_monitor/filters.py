"""Validate requested conditions and report unsupported source dimensions."""

from collections.abc import Mapping

from .settings import ConfigurationError

FILTER_FIELDS = frozenset({
    "compute_countries", "sales_countries", "regions", "zones",
    "gpu_models", "gpu_counts", "billing_modes", "currencies",
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
            if name in {"compute_countries", "sales_countries", "currencies"}:
                normalized = [value.upper() for value in normalized]
                length = 3 if name == "currencies" else 2
                if any(len(value) != length or not value.isascii() or not value.isalpha() for value in normalized):
                    raise ConfigurationError("country and currency filters must use ISO code format")
            if name == "billing_modes" and any(value not in BILLING_MODES for value in normalized):
                raise ConfigurationError("billing_modes contains an unsupported mode")
        result[name] = list(dict.fromkeys(normalized))
    return result


def filter_support(provider: str, filters: dict[str, list]) -> dict:
    supported = {"gpu_models", "currencies", "billing_modes"}
    if provider == "nebius":
        supported.add("regions")
    return {
        name: {
            "requested": values,
            "status": "applied_locally" if name in supported else "unsupported",
            "reason": (
                "Matched against explicitly published quote fields; no regional inquiry was performed."
                if name in supported else
                "This public source does not provide verifiable values for this condition."
            ),
        }
        for name, values in filters.items() if values
    }


def apply_filters(prices: list[dict], filters: dict[str, list]) -> list[dict]:
    result = []
    for quote in prices:
        match = True
        for name, values in filters.items():
            if not values:
                continue
            if name == "regions":
                match = bool(set(values) & set(quote["regions"]))
            else:
                field = {"gpu_models": "gpu_model", "currencies": "currency", "billing_modes": "billing_mode"}[name]
                match = str(quote[field]).casefold() in {value.casefold() for value in values}
            if not match:
                break
        if match:
            result.append(quote)
    return result
