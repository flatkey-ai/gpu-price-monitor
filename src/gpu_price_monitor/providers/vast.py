"""Bounded anonymous Vast.ai model-directory searches; never rent resources.

An offer is a concrete GPU bundle with its own CPU/RAM allocation and declared
location. The search has no verified pagination/total-count contract: even an
API ``truncated: false`` does not establish complete marketplace coverage.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
import json
import re
import time

from ..settings import Settings
from ..transport import FetchError, request_json

API_URL = "https://console.vast.ai/api/v0/bundles"
GPU_DIRECTORY_URL = "https://console.vast.ai/api/v0/gpu_names/unique/"
SOURCE_URL = "https://cloud.vast.ai/create/"
SOURCE_TYPE = "official_public_api"
DOCUMENTATION_URL = "https://docs.vast.ai/api-reference/search/search-offers"
PRICING_URL = "https://docs.vast.ai/guides/instances/pricing"
CLI_SOURCE_URL = "https://github.com/vast-ai/vast-cli/blob/master/vast.py"
ALLOCATED_STORAGE = 8
MAX_OFFERS = 1000
MAX_MODELS = 256
MAX_WORKERS = 4
# ISO 3166-1 alpha-2 validation only. Country evidence is the offer's own
# explicitly supplied suffix, never a host IP, currency, or inferred city.
_COUNTRIES = frozenset("""AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW""".split())
_VARIANT = re.compile(r"\b(?:SXM\d*|PCI[Ee]|NVL)\b", re.I)
_PARTITION = re.compile(r"\b(?:MIG|vGPU)\b", re.I)
# Only explicit subnational labels are promoted to regions. All other source
# labels retain country evidence and raw location without inventing a region.
_SUBDIVISIONS = {
    "US": frozenset("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming".split("|")),
    "CA": frozenset("Alberta|British Columbia|Manitoba|New Brunswick|Newfoundland and Labrador|Northwest Territories|Nova Scotia|Nunavut|Ontario|Prince Edward Island|Quebec|Saskatchewan|Yukon".split("|")),
}


class _Excluded(ValueError):
    pass


def _text(value: object, field: str, *, max_length: int = 200) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > max_length
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise _Excluded("invalid_" + field)
    return value.strip()


def _number(value: object, field: str, *, positive: bool = True) -> Decimal:
    # The shared JSON transport uses Decimal, never rounded binary floats.
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _Excluded("invalid_" + field)
    result = Decimal(value)
    if (not result.is_finite() or result < 0 or (positive and result == 0)
            or result.as_tuple().exponent < -50
            or (result and result.adjusted() > 12)):
        raise _Excluded("invalid_" + field)
    return result


def _integer(value: object, field: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise _Excluded("invalid_" + field)
    return value


def _native(value: Decimal) -> int | float:
    # Only resource quantities use native JSON numbers; money stays decimal text.
    return int(value) if value == value.to_integral_value() else float(value)


def _location(value: object) -> tuple[str, str]:
    location = _text(value, "geolocation")
    code = location.rsplit(",", 1)[-1].strip()
    if code not in _COUNTRIES or ("," not in location and location != code):
        raise _Excluded("country_not_explicit")
    # ", US" supplies a country only. Retain that explicit code without making
    # up a city, cloud region identifier, or a nationwide-uniform rate.
    return location if location.strip(" ,") != code else code, code


def _query(limit: int, gpu_name: str | None = None) -> dict:
    if type(limit) is not int or not 1 <= limit <= MAX_OFFERS:
        raise ValueError("Vast.ai limit must be an integer from 1 to 1000")
    return {"limit": limit, "type": "on-demand",
            "allocated_storage": ALLOCATED_STORAGE, "order": [["id", "asc"]],
            **({"gpu_name": {"eq": gpu_name}} if gpu_name is not None else {})}


def _quote(row: dict, *, observed_at: str) -> dict:
    offer_id = _integer(row.get("id"), "offer_id", 10**15)
    count = _integer(row.get("num_gpus"), "gpu_count", 1024)
    name = _text(row.get("gpu_name"), "gpu_name")
    if _PARTITION.search(name):
        raise _Excluded("partitioned_gpu")
    if (type(row.get("rentable")) is not bool or type(row.get("rented")) is not bool
            or row.get("is_bid") is not False or row.get("verification") not in {"verified", "deverified", "unverified"}
            or row.get("resource_type") != "gpu"):
        raise _Excluded("outside_requested_offer_scope")
    model = re.sub(r"^(?:NVIDIA|AMD|Tesla)\s+", "", name, flags=re.I)
    variants = _VARIANT.findall(model)
    if len(variants) > 1:
        raise _Excluded("ambiguous_gpu_variant")
    variant = variants[0].upper() if variants else None
    if variant == "PCIE":
        variant = "PCIe"
    model = " ".join(_VARIANT.sub("", model).split()).upper()
    if not model:
        raise _Excluded("invalid_gpu_model")
    arch = row.get("gpu_arch")
    if arch not in ("nvidia", "amd"):
        raise _Excluded("unknown_gpu_vendor")
    location, country = _location(row.get("geolocation"))
    subdivision = location.rsplit(",", 1)[0].strip() if "," in location else ""
    has_region = subdivision in _SUBDIVISIONS.get(country, ())
    raw_cpu = row.get("cpu_cores_effective")
    cpu = (None if raw_cpu is None or (type(raw_cpu) in (int, Decimal) and raw_cpu == 0)
           else _number(raw_cpu, "cpu_cores_effective"))
    ram = _number(row.get("cpu_ram"), "cpu_ram")
    vram = _number(row.get("gpu_ram"), "gpu_ram")
    raw_cpu_name = row.get("cpu_name")
    cpu_name = (None if raw_cpu_name is None or (isinstance(raw_cpu_name, str) and not raw_cpu_name.strip())
                else _text(raw_cpu_name, "cpu_name"))
    disk_available = _number(row.get("disk_space"), "disk_space")
    if disk_available < ALLOCATED_STORAGE:
        raise _Excluded("insufficient_storage")
    total = _number(row.get("dph_total"), "dph_total")
    base = _number(row.get("dph_base"), "dph_base")
    disk_hour = _number(row.get("storage_total_cost"), "storage_total_cost", positive=False)
    disk_month = _number(row.get("storage_cost"), "storage_cost", positive=False)
    fraction = _number(row.get("gpu_frac"), "gpu_frac")
    if fraction > 1:
        raise _Excluded("invalid_gpu_frac")
    with localcontext(Context(prec=80)):
        # Providers expose rounded arithmetic; allow only numerical roundoff,
        # never silently choose a conflicting breakdown or add storage twice.
        tolerance = max(Decimal("0.000000001"), total * Decimal("0.000000001"))
        if abs(total - base - disk_hour) > tolerance:
            raise _Excluded("price_breakdown_mismatch")
        amount = total / count
        memory_gb, vram_gb = ram / 1000, vram / 1000
    return {
        "provider": "vast", "product_type": "gpu_container", "gpu_model": model,
        "gpu_vendor": "NVIDIA" if arch == "nvidia" else "AMD", "gpu_variant": variant,
        "raw_name": name, "raw_sku": str(offer_id), "gpu_count": count,
        "vram_gb": _native(vram_gb), "amount": format(amount, "f"), "currency": "USD",
        "unit": "gpu_hour", "billing_mode": "on_demand", "quote_status": "quoted",
        "price_basis": "instance_total_allocated",
        "instance_price": {"amount": format(total, "f"), "currency": "USD", "unit": "instance_hour"},
        "resources": {"vcpus": _native(cpu) if cpu is not None else None, "cpu_name": cpu_name,
                      "memory_gb": _native(memory_gb), "memory_mb": format(ram, "f"),
                      "gpu_memory_mb_per_gpu": format(vram, "f"), "storage_gb": ALLOCATED_STORAGE},
        "regions": [location] if has_region else [], "zones": [], "compute_countries": [country],
        "geographic_scope": "offer_location" if has_region else "offer_country",
        "price_scope": "regional_quote" if has_region else "country_quote",
        "region_price_verified": has_region, "account_scope": "public_catalog", "tax_scope": "unspecified",
        "availability": "available" if row["rentable"] and not row["rented"] else "unavailable", "observed_at": observed_at,
        "effective_from": None, "effective_until": None,
        "source_url": API_URL, "source_type": SOURCE_TYPE, "pricing_page_url": SOURCE_URL,
        "documentation_url": DOCUMENTATION_URL,
        "location_source": {"source_url": API_URL, "documentation_url": DOCUMENTATION_URL,
                            "basis": "offer_geolocation", "field": "geolocation",
                            "raw_location": row["geolocation"], "country_code": country,
                            "location_granularity": "subdivision" if has_region else "country",
                            "uniform_country_price": False},
        "conditions": {"offer_id": offer_id, "rate_type": "concrete_offer", "verification": row["verification"],
                       "rentable": row["rentable"], "rented": row["rented"],
                       "missing_resource_fields": (["cpu_cores_effective"] if cpu is None else []) + (["cpu_name"] if cpu_name is None else []),
                       "allocated_storage": ALLOCATED_STORAGE, "storage_unit": "GB_as_documented_by_API",
                       "storage_unit_caveat": "API documentation says GB; CLI help says GiB. The request value is used unchanged.",
                       "gpu_fraction_of_host": format(fraction, "f"),
                       "compute_per_instance_hour_usd": format(base, "f"),
                       "storage_per_instance_hour_usd": format(disk_hour, "f"),
                       "storage_per_gb_month_usd": format(disk_month, "f"),
                       "bandwidth_included": False, "catalog_coverage": "partial"},
        "notes": [
            "A concrete public on-demand GPU offer, including the explicitly requested 8-unit storage allocation; verification and current rentability are preserved separately, not used to hide published prices.",
            "The API's dph_total is the complete selected offer hourly rate before additional bandwidth and unspecified taxes; divided by num_gpus for GPU-hour comparison.",
            "GPU fraction describes this offer's share of the host GPU count, not a fraction of a GPU; CPU/RAM are the offer allocations.",
            "Location is exactly the offer's declared geolocation. It may identify only a country; it is not an availability zone or a nationwide-uniform price.",
            "RAM/VRAM are source-reported MB divided by 1000 for GB display, not nominal model specifications.",
            "Missing or zero CPU allocation metadata remains unknown (null); it does not erase an independently quoted offer price.",
            "Bounded anonymous search; complete marketplace coverage and checkout availability were not established.",
        ],
    }


def parse_result(payload: dict, *, observed_at: str, limit: int = MAX_OFFERS) -> dict:
    """Validate each returned offer, exposing omissions without inventing data."""
    query = _query(limit)
    if not isinstance(payload, dict) or payload.get("error") or payload.get("success") is False:
        raise FetchError("public_api_error", "Vast.ai rejected the anonymous pricing search.")
    rows = payload.get("offers")
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("Vast.ai offer response has invalid structure or exceeds the requested limit")
    truncated = payload.get("truncated")
    if truncated is not None and type(truncated) is not bool:
        raise ValueError("Vast.ai search truncation flag is invalid")
    prices, exclusions, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Vast.ai offer row is invalid")
        identifier = row.get("id")
        if type(identifier) is not int or identifier in seen:
            raise ValueError("Vast.ai offer identity is invalid or duplicated")
        seen.add(identifier)
        try:
            prices.append(_quote(row, observed_at=observed_at))
        except _Excluded as exc:
            exclusions.append({"offer_id": identifier, "code": str(exc)})
    coverage = {
        "scope": "bounded_public_on_demand_offer_search", "complete": False,
        "status": "partial", "request_count": 1, "request_limit": limit, "request": query,
        "source_offer_count": len(rows), "quote_count": len(prices), "excluded_count": len(exclusions),
        "exclusion_counts": dict(sorted(Counter(e["code"] for e in exclusions).items())),
        "exclusions": exclusions, "api_truncated": truncated, "marketplace_total": None,
        "country_codes": sorted({c for q in prices for c in q["compute_countries"]}),
        "region_bound_quote_count": sum(bool(q["regions"]) for q in prices),
        "country_only_quote_count": sum(not q["regions"] for q in prices),
        "gpu_models": sorted({q["gpu_model"] for q in prices}),
        "reason": "The public search has no verified pagination or total-count contract; a false truncated flag does not prove full marketplace coverage.",
    }
    return {"prices": prices, "status": "partial", "errors": [], "coverage": coverage,
            "catalog_coverage": coverage,
            "pricing_limitations": [coverage["reason"],
                                    "On-demand GPU offers with complete required fields are included, independently of verification and rentability. Bid, reserved and prepaid discounts are separate pricing terms and are excluded.",
                                    "Anonymous search is currently accessible but official API documentation requires an API key; access may change."]}


def collect_result(*, settings: Settings, observed_at: str, limit: int = MAX_OFFERS) -> dict:
    """Search every official directory model, not one capped mixed-model page.

    The official CLI uses the public GPU-name directory and the documented
    gpu_name equality filter. Each model remains bounded because the API has no
    verified continuation/total contract; coverage never claims full inventory.
    """
    _query(limit)  # Validate before any request.
    bounded = replace(settings, timeout_seconds=min(settings.timeout_seconds, 20), max_retries=0)
    directory = request_json(GPU_DIRECTORY_URL, bounded, authenticated=False, max_response_bytes=128 * 1024)
    models = directory.get("gpu_names") if isinstance(directory, dict) else None
    if (not isinstance(models, list) or not 1 <= len(models) <= MAX_MODELS
            or any(not isinstance(name, str) or not name or len(name) > 128
                   or name != name.strip() or any(ord(c) < 32 for c in name) for name in models)
            or len(set(models)) != len(models) or directory.get("success") is False):
        raise ValueError("Vast.ai GPU directory has invalid structure")
    def search(model):
        query = _query(limit, model)
        try:
            payload = request_json(API_URL, bounded, method="POST", authenticated=False,
                                   headers={"Content-Type": "application/json"},
                                   data=json.dumps(query, separators=(",", ":")).encode(),
                                   max_response_bytes=5 * 1024 * 1024)
            result = parse_result(payload, observed_at=datetime.now(timezone.utc).isoformat(), limit=limit)
            if any(row.get("gpu_name") != model for row in payload["offers"]):
                raise ValueError("Vast.ai returned offers outside the requested model")
            return model, result, None
        except (FetchError, ValueError) as exc:
            return model, None, {"source_url": API_URL, "gpu_name": model,
                                 "code": exc.code if isinstance(exc, FetchError) else "invalid_model_response",
                                 "message": "The public model price search did not produce verified data."}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(search, sorted(models)))
    requests = len(models) + 1
    # Retry only transient failures, after a bounded provider cooldown. A
    # serial retry round avoids amplifying 429s with another directory scan.
    for _ in range(min(settings.max_retries, 2)):
        pending = [index for index, (_, _, error) in enumerate(results)
                   if error and error["code"] in {"rate_limited", "timeout", "network_error"}]
        if not pending:
            break
        time.sleep(60)
        for position, index in enumerate(pending):
            if position:
                time.sleep(2)
            results[index] = search(results[index][0])
            requests += 1
    prices, seen, model_results, errors, exclusions = [], set(), [], [], []
    for model, result, error in results:
        if error:
            errors.append(error)
            model_results.append({"gpu_name": model, "status": "failed"})
            continue
        coverage = result["coverage"]
        model_results.append({"gpu_name": model, "status": "queried", "source_offer_count": coverage["source_offer_count"],
                              "quote_count": coverage["quote_count"], "api_truncated": coverage["api_truncated"],
                              "limit_reached": coverage["source_offer_count"] >= limit})
        exclusions.extend(coverage["exclusions"])
        for quote in result["prices"]:
            identifier = quote["conditions"]["offer_id"]
            if identifier not in seen:
                prices.append(quote)
                seen.add(identifier)
    coverage = {"scope": "official_gpu_directory_per_model_on_demand_search", "complete": False,
                "status": "partial", "directory_source_url": GPU_DIRECTORY_URL,
                "directory_model_count": len(models), "models_queried": len(models) - len(errors),
                "request_count": requests, "retry_request_count": requests - len(models) - 1, "request_limit_per_model": limit,
                "model_results": model_results, "source_offer_count": sum(row.get("source_offer_count", 0) for row in model_results),
                "quote_count": len(prices), "excluded_count": len(exclusions), "exclusions": exclusions,
                "exclusion_counts": dict(sorted(Counter(e["code"] for e in exclusions).items())),
                "country_codes": sorted({c for q in prices for c in q["compute_countries"]}),
                "gpu_models": sorted({q["gpu_model"] for q in prices}), "marketplace_total": None,
                "reason": "Every current public directory model is searched separately; each model response is bounded and no verified inventory pagination contract exists."}
    return {"prices": prices, "status": "partial", "errors": errors, "coverage": coverage, "catalog_coverage": coverage,
            "pricing_limitations": [coverage["reason"],
                                    "Published on-demand prices are retained independently of verification and rentability; those source fields remain explicit.",
                                    "Bid, reserved, prepaid discounts and partitioned GPUs are outside this price scope. Anonymous API access may change."]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Return bounded offers; use collect_result for coverage and exclusions."""
    return collect_result(settings=settings, observed_at=observed_at)["prices"]
