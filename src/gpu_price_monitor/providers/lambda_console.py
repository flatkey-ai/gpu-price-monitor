"""Parse Lambda's authenticated console catalogs without accessing a session.

Only the GET response schemas observed in Lambda's official console frontend
are supported here. This module performs no I/O and exposes no create/reserve
operation. Capacity locations never become independently obtained price regions.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Context, Decimal, localcontext

from . import lambda_cloud, lambda_locations
from ..transport import FetchError


SOURCE_URL = "https://cloud.lambda.ai/api/internal/dashboard/v1"
SOURCE_TYPE = "official_internal_api"
AUTH_KIND = "session"
INSTANCE_TYPES_URL = SOURCE_URL + "/instance-types"
RESERVED_CLUSTER_TYPES_URL = SOURCE_URL + "/cluster-types/reserved"
REGIONS_URL = SOURCE_URL + "/regions"
FRONTEND_SOURCE_URL = "https://cloud.lambda.ai/static/cloud-app/assets/main-BdOFEme8.js"
FRONTEND_COMMON_URL = "https://cloud.lambda.ai/static/cloud-app/assets/common-DirxWaW8.js"
CLOUD_TERMS_URL = "https://lambda.ai/legal/terms-of-service"
BILLING_URL = "https://docs.lambda.ai/public-cloud/billing/"
AUTH_DOCUMENTATION_URL = "https://docs.lambda.ai/public-cloud/access-security/"
SCHEMA_VERIFIED_ON = "2026-10-23"
_SAFE_INTEGER_MAX = 2**53 - 1


def _invalid() -> ValueError:
    return ValueError("The Lambda console catalog schema or price units were not recognized.")


def _object(value: object, required: set[str], optional: set[str] | None = None) -> dict:
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - (optional or set())):
        raise _invalid()
    return value


def _text(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(ord(character) < 32 for character in value)):
        raise _invalid()
    return " ".join(value.split())


def _integer(value: object, *, zero_allowed: bool = False) -> int:
    if type(value) is not int or not (0 if zero_allowed else 1) <= value <= _SAFE_INTEGER_MAX:
        raise _invalid()
    return value


def _payload_data(payload: object, expected: type):
    if not isinstance(payload, dict):
        raise _invalid()
    if "error" in payload:
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and code in {"global/invalid-authentication", "global/invalid-api-key", "global/forbidden",
                    "global/account-inactive", "global/permission-denied"}:
            raise FetchError("authentication_error", "Lambda rejected the console session or account permissions.")
        raise FetchError("provider_error", "Lambda returned a console API error response.")
    _object(payload, {"data"})
    data = payload["data"]
    if not isinstance(data, expected):
        raise _invalid()
    return data


def _locations(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise _invalid()
    locations, seen = [], set()
    for region in value:
        _object(region, {"name", "description"}, {"dedicated"})
        name, description = _text(region["name"]), _text(region["description"])
        if name in seen or "dedicated" in region and type(region["dedicated"]) is not bool:
            raise _invalid()
        seen.add(name)
        item = {"name": name, "description": description}
        if "dedicated" in region:
            item["dedicated"] = region["dedicated"]
        locations.append(item)
    return locations


def _instance(value: object) -> dict:
    instance = _object(value, {"name", "description", "gpu_description", "price_cents_per_hour", "specs", "architecture"},
                       {"metadata", "compute_partition_required"})
    for key in ("name", "description", "gpu_description", "architecture"):
        _text(instance[key])
    if instance["architecture"] not in {"x86_64", "arm64"}:
        raise _invalid()
    _integer(instance["price_cents_per_hour"], zero_allowed=True)
    specs = _object(instance["specs"], {"vcpus", "memory_gib", "storage_gib", "gpus"})
    for key in specs:
        _integer(specs[key], zero_allowed=key in {"storage_gib", "gpus"})
    if "metadata" in instance:
        metadata = _object(instance["metadata"], set(), {"is_new", "is_cheaper"})
        if any(type(value) is not bool for value in metadata.values()):
            raise _invalid()
    if "compute_partition_required" in instance and type(instance["compute_partition_required"]) is not bool:
        raise _invalid()
    return instance


def _evidence(field: str, *, source_unit: str, normalization: str) -> dict:
    return {
        "currency": {"value": "USD", "source_url": CLOUD_TERMS_URL,
                     "basis": "Lambda Cloud terms specify Fees quoted and payable in US dollars."},
        "unit": {"value": "gpu_hour", "source_unit": source_unit, "source_field": field,
                 "source_url": FRONTEND_SOURCE_URL, "normalization": normalization},
        "frontend_source_url": FRONTEND_SOURCE_URL,
        "cents_formatter_source_url": FRONTEND_COMMON_URL,
        "verified_on": SCHEMA_VERIFIED_ON,
    }


def _capacity_metadata(quote: dict, locations: list[dict]) -> None:
    quote.update(regions=[], zones=[], compute_countries=[], geographic_scope="unspecified",
                 price_scope="unlocated_catalog", region_price_verified=False,
                 capacity_regions=[location["name"] for location in locations],
                 capacity_locations=deepcopy(locations),
                 availability="capacity_reported" if locations else "no_capacity_reported")
    quote["availability_metadata"] = {
        "basis": "catalog_capacity_locations_not_independent_regional_prices",
        "locations": deepcopy(locations), "orderability_verified": False,
    }
    quote.update(lambda_locations.enrich_price_applicability(quote))


def parse_instance_catalog(payload: dict, *, observed_at: str) -> dict:
    """Parse the console's full catalog, auditing CPU exclusions explicitly."""
    catalog = _payload_data(payload, dict)
    gpu_catalog, locations_by_sku, excluded = {}, {}, []
    for sku, item in catalog.items():
        _text(sku)
        _object(item, {"instance_type", "regions_with_capacity_available"})
        instance = _instance(item["instance_type"])
        if instance["name"] != sku:
            raise _invalid()
        locations = _locations(item["regions_with_capacity_available"])
        if instance["specs"]["gpus"] == 0:
            excluded.append({"raw_sku": sku, "product_type": "cpu_instance", "gpu_count": 0,
                             "reason": "zero_gpu_instance"})
            continue
        gpu_catalog[sku] = item
        locations_by_sku[sku] = locations
    # Reuse the public API parser's GPU extraction and exact instance-to-GPU
    # allocation only after explicitly separating the zero-GPU console entries.
    prices = lambda_cloud.parse_prices({"data": gpu_catalog}, observed_at=observed_at)
    for quote in prices:
        quote.update(source_type=SOURCE_TYPE, source_url=INSTANCE_TYPES_URL,
                     auth_kind=AUTH_KIND, account_scope="authenticated_console_catalog",
                     price_record_kind="console_catalog_price")
        # The public API documents a shared schema, not this internal route.
        quote.pop("api_documentation_url", None)
        quote["schema_reference_url"] = lambda_cloud.DOCUMENTATION_URL
        quote["pricing_evidence"] = _evidence("instance_type.price_cents_per_hour", source_unit="instance_hour",
                                              normalization="price_cents_per_hour / 100 / specs.gpus")
        _capacity_metadata(quote, locations_by_sku[quote["raw_sku"]])
    return {"prices": prices, "excluded_non_gpu_records": excluded,
            "excluded_non_gpu_record_count": len(excluded), "source_record_count": len(catalog)}


def parse_instance_prices(payload: dict, *, observed_at: str) -> list[dict]:
    """Compatibility list view; use parse_instance_catalog to retain exclusions."""
    return parse_instance_catalog(payload, observed_at=observed_at)["prices"]


def parse_regions(payload: dict) -> list[dict]:
    """Return explicit region descriptions, without inventing price geography."""
    return _locations(_payload_data(payload, list))


def parse_cluster_prices(payload: dict, *, observed_at: str) -> list[dict]:
    """Parse explicit 1CC configurations using the frontend's chosen GPU rate.

    The legacy cluster/worker totals can disagree with the GPU rate displayed
    in checkout. They remain audit fields and never replace that source rate.
    Duration validation depends on account feature flags and is unverified here.
    """
    catalog, prices, seen = _payload_data(payload, list), [], set()
    for item in catalog:
        _object(item, {"cluster_type", "regions_available"})
        cluster = _object(item["cluster_type"], {"worker_instance_type", "num_workers", "num_gpus",
                                               "price_cents_per_hour", "price_cents_per_gpu_hour", "description"})
        worker = _instance(cluster["worker_instance_type"])
        workers, gpus = _integer(cluster["num_workers"]), _integer(cluster["num_gpus"])
        gpus_per_worker = _integer(worker["specs"]["gpus"])
        if workers * gpus_per_worker != gpus:
            raise _invalid()
        cents = _integer(cluster["price_cents_per_gpu_hour"], zero_allowed=True)
        raw_cluster_cents = _integer(cluster["price_cents_per_hour"], zero_allowed=True)
        description, locations = _text(cluster["description"]), _locations(item["regions_available"])
        identity = (worker["name"], workers)
        if identity in seen:
            raise _invalid()
        seen.add(identity)
        model, variant, vram = lambda_cloud._gpu_fields(worker["gpu_description"])
        with localcontext(Context(prec=50)):
            amount = format(Decimal(cents) / 100, "f")
            total = format(Decimal(cents) * gpus / 100, "f")
        ui_cluster_cents = cents * gpus
        conflicts = []
        if raw_cluster_cents != ui_cluster_cents:
            conflicts.append("cluster_type.price_cents_per_hour")
        if worker["price_cents_per_hour"] * workers != ui_cluster_cents:
            conflicts.append("cluster_type.worker_instance_type.price_cents_per_hour")
        quote = {
            "provider": "lambda", "product_type": "gpu_cluster", "product_line": "1-Click Clusters",
            "price_record_kind": "console_catalog_price", "configuration_expansion": False,
            "gpu_model": model, "gpu_variant": variant, "vram_gb": vram,
            "gpu_count": None, "raw_name": description, "raw_sku": worker["name"],
            "amount": amount, "currency": "USD", "unit": "gpu_hour", "billing_mode": "reserved",
            "price_basis": "advertised_per_gpu", "quote_status": "quoted",
            "selected_configuration": {"worker_instance_type": worker["name"], "cluster_gpu_count": gpus,
                                       "cluster_gpu_count_relation": "exact", "num_workers": workers,
                                       "gpus_per_worker": gpus_per_worker},
            "worker_resources": deepcopy(worker["specs"]),
            "source_price_fields": {"cluster_type.price_cents_per_gpu_hour": cents,
                                    "cluster_type.price_cents_per_hour": raw_cluster_cents,
                                    "cluster_type.worker_instance_type.price_cents_per_hour": worker["price_cents_per_hour"]},
            "source_field_conflict": bool(conflicts), "conflicting_source_price_fields": conflicts,
            "computed_cluster_total": {"amount": total, "currency": "USD", "unit": "cluster_hour",
                                       "formula": "price_cents_per_gpu_hour * num_gpus / 100",
                                       "independent_provider_quote": False},
            "duration_unverified": True, "pricing_terms_unverified": True,
            "source_conditions": {"duration_unverified": True, "pricing_terms_unverified": True,
                                  "reservation_term": None, "billing_increment": "week"},
            "account_scope": "authenticated_console_catalog", "auth_kind": AUTH_KIND,
            "tax_scope": "excluded", "observed_at": observed_at,
            "effective_from": None, "effective_until": None,
            "source_url": RESERVED_CLUSTER_TYPES_URL, "source_type": SOURCE_TYPE,
            "billing_source_url": BILLING_URL,
            "pricing_evidence": _evidence("cluster_type.price_cents_per_gpu_hour", source_unit="gpu_hour",
                                           normalization="price_cents_per_gpu_hour / 100"),
            "notes": [
                "The official frontend selects price_cents_per_gpu_hour for cluster cards and payment summaries.",
                "Legacy cluster and worker hourly price fields are retained for audit; conflicting lower values never replace the displayed GPU-hour rate.",
                "Cluster totals are frontend-formula calculations, not independent source quotations or per-node prices.",
                "Duration limits, account eligibility, final contractual terms and orderability were not verified; no universal minimum reservation duration is inferred.",
                "Available regions describe this catalog configuration's capacity locations; no independent regional price was queried.",
                "Reservations are billed weekly; the frontend calculates applicable taxes on the invoice.",
            ],
        }
        _capacity_metadata(quote, locations)
        prices.append(quote)
    return prices
