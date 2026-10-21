"""Read Lambda's authenticated instance catalog without creating resources.

The endpoint quotes complete instances. ``amount`` is a per-GPU allocation of
that instance price, and capacity regions never become regional price claims.
"""

from __future__ import annotations

import re
from decimal import Context, Decimal, localcontext

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://cloud.lambda.ai/api/v1/instance-types"
SOURCE_TYPE = "official_api"
DOCUMENTATION_URL = "https://docs.lambda.ai/api/cloud#list-available-instance-types"

_MEMORY = re.compile(r"\b(\d+)\s*GB\b", re.IGNORECASE)
_VARIANT = re.compile(r"\b(?:PCIe|SXM\d*|NVLink|HGX)\b", re.IGNORECASE)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Lambda instance catalog contains an invalid text field")
    return " ".join(value.split())


def _integer(value: object, *, zero_allowed: bool = False) -> int:
    if type(value) is not int or value < (0 if zero_allowed else 1):
        raise ValueError("Lambda instance catalog contains an invalid numeric field")
    return value


def _gpu_fields(description: str) -> tuple[str, str | None, int | None]:
    """Extract only information explicitly supplied in the GPU description."""
    description = re.sub(r"^(?:NVIDIA|AMD)\s+", "", description, flags=re.IGNORECASE)
    model, separator, details = description.partition("(")
    if separator:
        if not details.endswith(")") or "(" in details:
            raise ValueError("Lambda GPU description has an unrecognized structure")
        details = details[:-1].strip()
        memories = list(_MEMORY.finditer(details))
        if len(memories) > 1:
            raise ValueError("Lambda GPU description has ambiguous GPU memory")
        vram = int(memories[0].group(1)) if memories else None
        variant = _MEMORY.sub("", details).strip(" ,;/") or None
    else:
        memories = list(_MEMORY.finditer(model))
        if len(memories) > 1:
            raise ValueError("Lambda GPU description has ambiguous GPU memory")
        vram = int(memories[0].group(1)) if memories else None
        model = _MEMORY.sub("", model)
        variants = list(_VARIANT.finditer(model))
        variant = " ".join(match.group() for match in variants) or None
        model = _VARIANT.sub("", model)
    model = " ".join(model.split()).upper()
    if not model or vram == 0:
        raise ValueError("Lambda GPU description has an invalid model or GPU memory")
    return model, variant, vram


def _check_error(payload: dict) -> None:
    if "error" not in payload:
        return
    error = payload["error"]
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in {
        "global/invalid-api-key", "global/forbidden", "global/account-inactive",
    }:
        raise FetchError("authentication_error", "Lambda rejected the API credentials or account access.")
    raise FetchError("provider_error", "Lambda returned an API error response.")


def parse_prices(payload: dict, *, observed_at: str) -> list[dict]:
    """Parse the official ``instance-types`` schema into normalized quotes.

    A malformed entry fails the catalog rather than returning a partial success.
    An explicitly empty ``data`` object remains a legitimate empty catalog.
    """
    if not isinstance(payload, dict):
        raise ValueError("Lambda instance catalog must be a JSON object")
    _check_error(payload)
    catalog = payload.get("data")
    if not isinstance(catalog, dict):
        raise ValueError("Lambda instance catalog is missing its data object")
    result = []
    for sku, item in catalog.items():
        _string(sku)
        if not isinstance(item, dict) or not isinstance(item.get("instance_type"), dict):
            raise ValueError("Lambda instance catalog contains an invalid instance entry")
        instance = item["instance_type"]
        name = _string(instance.get("name"))
        if name != sku:
            raise ValueError("Lambda instance catalog contains inconsistent instance names")
        description = _string(instance.get("description"))
        gpu_description = _string(instance.get("gpu_description"))
        gpu_model, gpu_variant, vram_gb = _gpu_fields(gpu_description)
        price_cents = _integer(instance.get("price_cents_per_hour"), zero_allowed=True)
        specs = instance.get("specs")
        if not isinstance(specs, dict):
            raise ValueError("Lambda instance catalog is missing instance specifications")
        gpu_count = _integer(specs.get("gpus"))
        resources = {
            "vcpus": _integer(specs.get("vcpus")),
            "memory_gib": _integer(specs.get("memory_gib")),
            "storage_gib": _integer(specs.get("storage_gib"), zero_allowed=True),
            "architecture": _string(instance.get("architecture")),
        }
        capacity = item.get("regions_with_capacity_available")
        if not isinstance(capacity, list):
            raise ValueError("Lambda instance catalog is missing capacity regions")
        capacity_regions = []
        for region in capacity:
            if not isinstance(region, dict):
                raise ValueError("Lambda instance catalog contains an invalid capacity region")
            region_name = _string(region.get("name"))
            _string(region.get("description"))
            if region_name in capacity_regions:
                raise ValueError("Lambda instance catalog contains duplicate capacity regions")
            capacity_regions.append(region_name)
        # Keep integer-cent conversion exact. A per-GPU fraction may require
        # decimal rounding for uncommon counts; 50 digits avoids float loss.
        with localcontext(Context(prec=max(50, len(str(price_cents)) + len(str(gpu_count)) + 10))) as context:
            instance_amount = Decimal(price_cents) / Decimal(100)
            gpu_amount = instance_amount / Decimal(gpu_count)
        notes = [
            "Price is a per-GPU allocation of the complete instance price, including its listed resources.",
            "Capacity regions report available capacity; the catalog does not quote separate prices by region.",
            "Authenticated catalog price; checkout, discounts, taxes and orderability were not verified.",
        ]
        denominator = gpu_count
        for factor in (2, 5):
            while denominator % factor == 0:
                denominator //= factor
        if denominator != 1:
            notes.append(f"Per-GPU division uses {context.prec} significant decimal digits.")
        result.append({
            "provider": "lambda",
            "product_type": "gpu_instance",
            "product_line": "On-Demand Cloud",
            "price_record_kind": "api_catalog_price",
            "configuration_expansion": False,
            "gpu_model": gpu_model,
            "raw_name": description,
            "raw_sku": name,
            "gpu_variant": gpu_variant,
            "vram_gb": vram_gb,
            "gpu_count": gpu_count,
            "amount": format(gpu_amount, "f"),
            "currency": "USD",
            "unit": "gpu_hour",
            "billing_mode": "on_demand",
            "price_basis": "instance_total_allocated",
            "quote_status": "quoted",
            "instance_price": {
                "amount": format(instance_amount, "f"),
                "currency": "USD",
                "unit": "instance_hour",
            },
            "resources": resources,
            "regions": [],
            "geographic_scope": "unspecified",
            "capacity_regions": capacity_regions,
            "account_scope": "authenticated_catalog",
            "tax_scope": "unspecified",
            "observed_at": observed_at,
            "effective_from": None,
            "effective_until": None,
            "source_url": SOURCE_URL,
            "source_type": SOURCE_TYPE,
            "api_documentation_url": DOCUMENTATION_URL,
            "availability": "capacity_reported" if capacity_regions else "no_capacity_reported",
            "notes": notes,
        })
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Read the authenticated catalog once; missing credentials never send HTTP."""
    if not settings.lambda_api_key or not settings.lambda_api_key.strip():
        raise FetchError("missing_credentials", "Lambda requires LAMBDA_API_KEY.")
    payload = request_json(
        SOURCE_URL,
        settings,
        headers={"Authorization": f"Bearer {settings.lambda_api_key}"},
        authenticated=True,
    )
    return parse_prices(payload, observed_at=observed_at)
