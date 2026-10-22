"""Optional, account-scoped Nebius GPU configuration estimates.

Only GET Project and POST Calculator.EstimateBatch are used. The Create*Request
messages below are inert specifications inside the calculator's protobuf Any;
they are never sent to a compute create endpoint. Test fixtures are synthetic.

Schema checked against https://api.nebius.cloud/openapi.json on 2026-10-21:
nebius.billing.v1.EstimateBatch{Request,Response}, ResourceSpec, CostBreakdown,
ResourceCost and TotalCost. This is v1, not the incompatible v1alpha1 calculator.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_UP, localcontext
import json
import re

from ..settings import Settings
from ..transport import FetchError, request_json
from .nebius_regions import REGION_COUNTRIES

SOURCE_URL = "https://api.nebius.cloud/billing/v1/calculator/estimate-batch"
DOCUMENTATION_URL = "https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch"
OPENAPI_URL = "https://api.nebius.cloud/openapi.json"
REGIONS_URL = "https://docs.nebius.com/overview/regions"
PLATFORMS_URL = "https://docs.nebius.com/compute/virtual-machines/types"
PROJECT_URL = "https://api.nebius.cloud/iam/v2/projects/"
MAX_TARGETS = 20
MAX_TARGET_JSON_BYTES = 256 * 1024
_TYPE_PREFIX = "type.googleapis.com/nebius.compute.v1."
_KINDS = {"CreateInstanceRequest", "CreateDiskRequest", "CreateFilesystemRequest"}
_COUNTRIES = REGION_COUNTRIES
_UNITS = {"hour": ("FILTER_AGGREGATION_UNIT_HOUR", "gpu_hour", "instance_hour"),
          "month": ("FILTER_AGGREGATION_UNIT_MONTH", "gpu_month", "instance_month")}
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_VARIANT_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .+/_-]{0,127}\Z")
_DECIMAL = re.compile(r"\d+(?:\.\d{1,24})?\Z")
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*\Z")
_PRESET = re.compile(r"([1-9]\d*)gpu-([1-9]\d*)vcpu-([1-9]\d*)gb\Z")
_DISK_TYPES = {"NETWORK_SSD", "NETWORK_HDD", "NETWORK_SSD_NON_REPLICATED", "NETWORK_SSD_IO_M3"}
_SIZES = {"sizeBytes", "sizeKibibytes", "sizeMebibytes", "sizeGibibytes"}
_DECIMAL_CONTEXT = Context(prec=100, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999,
                           capitals=1, clamp=0, traps=[InvalidOperation, DivisionByZero, Overflow])
# Explicit platform/preset identity from the official VM types table, checked
# 2026-10-21. New platforms fail closed until their identity is documented here.
# These are configuration identities, not a claim about current stock or access.
_H_PRESETS = {"1gpu-16vcpu-200gb", "8gpu-128vcpu-1600gb"}
_B_PRESETS = {"1gpu-20vcpu-224gb", "8gpu-160vcpu-1792gb"}
_RTX_PRESETS = {"1gpu-24vcpu-218gb", "8gpu-192vcpu-1744gb"}
_PLATFORMS = {
    "gpu-h100-sxm": ("H100", "SXM", 80, _H_PRESETS, {"eu-north1"}),
    "gpu-h200-sxm": ("H200", "SXM", 141, _H_PRESETS, {"eu-north1", "eu-north2", "eu-west1", "us-central1"}),
    "gpu-b200-sxm": ("B200", "SXM", 180, _B_PRESETS, {"us-central1"}),
    "gpu-b200-sxm-a": ("B200", "SXM", 180, _B_PRESETS, {"me-west1"}),
    "gpu-b300-sxm": ("B300", "SXM", 288, {"1gpu-24vcpu-346gb", "8gpu-192vcpu-2768gb"}, {"uk-south1", "eu-west2", "us-north1"}),
    "gpu-rtx6000": ("RTX PRO 6000", "PCIe", 96, _RTX_PRESETS, {"us-central1"}),
    "gpu-rtx6000-a": ("RTX PRO 6000", "PCIe", 96, _RTX_PRESETS, {"uk-south2", "eu-south1"}),
    "gpu-l40s-a": ("L40S", "PCIe", 48, {"1gpu-8vcpu-32gb", "1gpu-16vcpu-64gb", "1gpu-24vcpu-96gb", "1gpu-32vcpu-128gb", "1gpu-40vcpu-160gb"}, {"eu-north1"}),
    "gpu-l40s-d": ("L40S", "PCIe", 48, {"1gpu-16vcpu-96gb", "1gpu-32vcpu-192gb", "1gpu-48vcpu-288gb", "2gpu-64vcpu-384gb", "2gpu-96vcpu-576gb", "4gpu-128vcpu-768gb", "4gpu-192vcpu-1152gb"}, {"eu-north1"}),
}
SUPPORTED_PLATFORMS = tuple(_PLATFORMS)


def _target_error() -> FetchError:
    return FetchError("invalid_price_targets", "Nebius targets must contain 1-20 explicit GPU instance configurations with a project, documented region/country, managed boot disk, resourceSpecs, currency, hour/month units and optional contract offers. No standalone Nebius zone is verified by this adapter.")


def _label(value: object) -> bool:
    return isinstance(value, str) and _LABEL.fullmatch(value) is not None


def _keys(value: object, required: set, optional: set = frozenset()) -> bool:
    return isinstance(value, dict) and required <= value.keys() and not value.keys() - required - optional


def _positive_int(value: object, maximum: int = 1_000_000) -> bool:
    return type(value) is int and 0 < value <= maximum


def _disk_spec(value: object, *, filesystem: bool = False) -> None:
    if not _keys(value, {"type"}, _SIZES | {"blockSizeBytes"}):
        raise _target_error()
    allowed = {"NETWORK_SSD", "NETWORK_HDD"} if filesystem else _DISK_TYPES
    sizes = _SIZES & value.keys()
    if not isinstance(value["type"], str) or value["type"] not in allowed or len(sizes) != 1:
        raise _target_error()
    size = value[next(iter(sizes))]
    if not isinstance(size, str) or not re.fullmatch(r"[1-9]\d{0,15}", size):
        raise _target_error()
    if "blockSizeBytes" in value and (not isinstance(value["blockSizeBytes"], str) or value["blockSizeBytes"] not in {"4096", "8192", "16384", "32768", "65536", "131072"}):
        raise _target_error()


def _attached_disk(value: object) -> None:
    # Managed disks have an explicit size/type; an existing disk ID alone would
    # hide its configuration and could silently omit its storage estimate.
    if not _keys(value, {"attachMode", "managedDisk"}, {"deviceId"}):
        raise _target_error()
    if not isinstance(value["attachMode"], str) or value["attachMode"] not in {"READ_ONLY", "READ_WRITE"}:
        raise _target_error()
    if "deviceId" in value and not _label(value["deviceId"]):
        raise _target_error()
    managed = value["managedDisk"]
    if not _keys(managed, {"name", "spec"}) or not _label(managed["name"]):
        raise _target_error()
    _disk_spec(managed["spec"])


def _resource(resource: object, target: dict, identity_catalog: dict | None = None) -> str:
    if not _keys(resource, {"spec"}):
        raise _target_error()
    request = resource["spec"]
    if not _keys(request, {"@type", "metadata", "spec"}):
        raise _target_error()
    kind = request["@type"]
    if not isinstance(kind, str) or not kind.startswith(_TYPE_PREFIX) or kind[len(_TYPE_PREFIX):] not in _KINDS:
        raise _target_error()
    kind = kind[len(_TYPE_PREFIX):]
    metadata = request["metadata"]
    if (not _keys(metadata, {"parentId", "name"}) or metadata["parentId"] != target["project_id"]
            or not _label(metadata["name"])):
        raise _target_error()
    spec = request["spec"]
    if kind != "CreateInstanceRequest":
        _disk_spec(spec, filesystem=kind == "CreateFilesystemRequest")
        return kind
    if not _keys(spec, {"resources", "bootDisk"}, {"secondaryDisks", "onDemand", "preemptible"}):
        raise _target_error()
    resources = spec["resources"]
    if not _keys(resources, {"platform", "preset"}) or not _label(resources["platform"]) or not resources["platform"].startswith("gpu-"):
        raise _target_error()
    preset = _PRESET.fullmatch(resources["preset"]) if isinstance(resources["preset"], str) else None
    if not preset or int(preset[1]) != target["gpu_count"]:
        raise _target_error()
    platform = (_PLATFORMS if identity_catalog is None else identity_catalog).get(resources["platform"])
    if (platform is None or target["gpu_model"] != platform[0]
            or resources["preset"] not in platform[3] or target["region"] not in platform[4]
            or target.get("gpu_variant") not in (None, platform[1])
            or target.get("vram_gb") not in (None, platform[2])):
        raise _target_error()
    target["gpu_variant"], target["vram_gb"] = platform[1], platform[2]
    _attached_disk(spec["bootDisk"])
    if "secondaryDisks" in spec:
        if not isinstance(spec["secondaryDisks"], list) or len(spec["secondaryDisks"]) > 8:
            raise _target_error()
        for disk in spec["secondaryDisks"]:
            _attached_disk(disk)
    if "onDemand" in spec and spec["onDemand"] != {}:
        raise _target_error()
    if "preemptible" in spec:
        preemptible = spec["preemptible"]
        if ("onDemand" in spec or not _keys(preemptible, {"onPreemption"}, {"priority"})
                or preemptible["onPreemption"] != "STOP"
                or ("priority" in preemptible and (type(preemptible["priority"]) is not int or not 0 <= preemptible["priority"] <= 2**31 - 1))):
            raise _target_error()
    return kind


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _target_error()
        result[key] = value
    return result


def _reject_constant(value: str):
    raise _target_error()


def validate_targets(raw: str, *, identity_catalog: dict | None = None,
                     region_countries: dict | None = None) -> list[dict]:
    """Validate every target before any HTTP call. Never interpolate its values
    into errors. Only pricing-relevant specs are accepted, without user data or
    arbitrary request URLs, headers, actions, identities or existing disk IDs.
    """
    try:
        if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > MAX_TARGET_JSON_BYTES:
            raise _target_error()
        targets = json.loads(raw, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _target_error() from None
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        raise _target_error()
    required = {"project_id", "region", "country_code", "gpu_model", "gpu_count", "resource_specs"}
    optional = {"currency", "aggregation_units", "offer_types", "gpu_variant", "vram_gb", "zones"}
    validated, seen = [], set()
    for supplied in targets:
        if not _keys(supplied, required, optional):
            raise _target_error()
        target = deepcopy(supplied)
        if (not _label(target["project_id"]) or not target["project_id"].startswith("project-")
                or not isinstance(target["region"], str)
                or (_COUNTRIES if region_countries is None else region_countries).get(target["region"]) != target["country_code"]
                or not isinstance(target["gpu_model"], str) or not re.fullmatch(r"[A-Z0-9][A-Za-z0-9 ]{0,63}", target["gpu_model"])
                or not _positive_int(target["gpu_count"], 128)):
            raise _target_error()
        if target.get("zones") not in (None, []):
            raise _target_error()
        if ("gpu_variant" in target and target["gpu_variant"] is not None
                and (not isinstance(target["gpu_variant"], str) or not _VARIANT_LABEL.fullmatch(target["gpu_variant"]))):
            raise _target_error()
        if "vram_gb" in target and target["vram_gb"] is not None and not _positive_int(target["vram_gb"], 4096):
            raise _target_error()
        target.setdefault("currency", "usd")
        target.setdefault("aggregation_units", ["hour"])
        target.setdefault("offer_types", [])
        if not isinstance(target["currency"], str) or target["currency"] not in {"usd", "ils"}:
            raise _target_error()
        units, offers = target["aggregation_units"], target["offer_types"]
        if (not isinstance(units, list) or not 1 <= len(units) <= 2 or any(not isinstance(unit, str) or unit not in _UNITS for unit in units)
                or len(set(units)) != len(units) or not isinstance(offers, list)
                or offers not in ([], ["OFFER_TYPE_CONTRACT_PRICE"])):
            raise _target_error()
        resources = target["resource_specs"]
        if not isinstance(resources, list) or not 1 <= len(resources) <= 8:
            raise _target_error()
        kinds = [_resource(resource, target, identity_catalog) for resource in resources]
        names = [resource["spec"]["metadata"]["name"] for resource in resources]
        for resource, kind in zip(resources, kinds):
            if kind == "CreateInstanceRequest":
                spec = resource["spec"]["spec"]
                names.extend(disk["managedDisk"]["name"] for disk in [spec["bootDisk"], *spec.get("secondaryDisks", [])])
        if kinds.count("CreateInstanceRequest") != 1 or len(set(names)) != len(names):
            raise _target_error()
        canonical = json.dumps(target, sort_keys=True)
        if canonical in seen:
            raise _target_error()
        seen.add(canonical)
        validated.append(target)
    return validated


def load_targets(settings: Settings) -> list[dict]:
    raw = getattr(settings, "nebius_price_targets_json", None)
    if raw is None or raw == "":
        raise FetchError("missing_price_targets", "Set NEBIUS_PRICE_TARGETS_JSON or NEBIUS_PRICE_TARGETS_FILE for explicit configuration estimates.")
    return validate_targets(raw)


def build_request(target: dict) -> bytes:
    return json.dumps({"resourceSpecs": target["resource_specs"], "currency": target["currency"],
                       "offerTypes": target["offer_types"], "filterAggregationUnit": {
                           "filterAggregationUnitValues": [_UNITS[unit][0] for unit in target["aggregation_units"]],
                       }}, separators=(",", ":")).encode("utf-8")


def _amount(value: object) -> Decimal:
    if not isinstance(value, str) or len(value) > 100 or not _DECIMAL.fullmatch(value):
        raise ValueError("Nebius estimate contains an invalid decimal amount")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Nebius estimate contains an invalid decimal amount") from None
    if not result.is_finite() or result < 0 or result > Decimal("1e18"):
        raise ValueError("Nebius estimate contains an invalid decimal amount")
    return result


def _breakdown(value: object) -> dict:
    if not isinstance(value, dict) or "cost" not in value:
        raise ValueError("Nebius estimate is missing its precise cost")
    cost = _amount(value["cost"])
    result = {"amount": value["cost"], "sku_costs": []}
    if "costRounded" in value:
        _amount(value["costRounded"])
        result["rounded_amount"] = value["costRounded"]
    skus = value.get("skuCosts", [])
    if not isinstance(skus, list) or len(skus) > 1000:
        raise ValueError("Nebius SKU breakdown changed")
    for sku in skus:
        if not isinstance(sku, dict) or not _label(sku.get("skuId")):
            raise ValueError("Nebius SKU breakdown changed")
        for key in ("quantity", "cost"):
            _amount(sku.get(key))
        result["sku_costs"].append({"sku_id": sku["skuId"], "quantity": sku["quantity"], "amount": sku["cost"]})
    with localcontext(_DECIMAL_CONTEXT):
        if skus and sum((_amount(sku["cost"]) for sku in skus), Decimal(0)) != cost:
            raise ValueError("Nebius SKU costs do not match their resource total")
    return result


def _aggregation(value: object, target: dict) -> str:
    if (not isinstance(value, dict) or value.get("unitType") != "UNIT_TYPE_TIME_BASED"
            or value.get("unit") not in target["aggregation_units"]):
        raise ValueError("Nebius estimate has an unsupported or unrequested aggregation unit")
    return value["unit"]


def _resource_cost(value: object, target: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Nebius resource cost schema changed")
    unit = _aggregation(value.get("aggregationUnit"), target)
    branches = {name for name in ("general", "fixedInstance", "autoscale") if name in value}
    if branches == {"general"} and isinstance(value["general"], dict):
        return {"aggregation_unit": unit, "cost_type": "general", **_breakdown(value["general"].get("total"))}
    if branches == {"fixedInstance"} and isinstance(value["fixedInstance"], dict):
        fixed = value["fixedInstance"]
        if type(fixed.get("instanceCount")) is not int or fixed["instanceCount"] != 1:
            raise ValueError("Nebius fixed instance count does not match the single requested VM")
        total, per = _breakdown(fixed.get("total")), _breakdown(fixed.get("perInstance"))
        if _amount(total["amount"]) != _amount(per["amount"]):
            raise ValueError("Nebius fixed instance totals are inconsistent")
        return {"aggregation_unit": unit, "cost_type": "fixed_instance", "instance_count": 1, "per_instance": per, **total}
    raise ValueError("Nebius estimate is variable, ambiguous or not a supported fixed configuration")


def _configuration(target: dict) -> dict:
    # Only pricing specifications are returned. Parent/project IDs, resource
    # names, response metadata, tokens and unrelated account payload are omitted.
    specs = []
    for resource in target["resource_specs"]:
        request = resource["spec"]
        spec = deepcopy(request["spec"])
        for key in ("bootDisk", "secondaryDisks"):
            disks = [spec[key]] if key == "bootDisk" and key in spec else spec.get(key, [])
            for disk in disks:
                disk["managedDisk"].pop("name", None)
                disk.pop("deviceId", None)
        specs.append({"type": request["@type"].removeprefix(_TYPE_PREFIX), "spec": spec})
    return {"resource_specs": specs, "aggregation_units": list(target["aggregation_units"]),
            "currency": target["currency"], "offer_types": list(target["offer_types"])}


def parse_quote(payload: dict, target: dict, *, observed_at: str, project_region_verified: bool = False,
                identity_catalog: dict | None = None, region_countries: dict | None = None) -> list[dict]:
    """Normalize a verified target's estimate, preserving totals and itemization.
    The caller must verify the project's region before using this parser's output
    as a live, region-bound quote; collect_quotes always performs that read.
    """
    try:
        target = validate_targets(json.dumps([target], allow_nan=False), identity_catalog=identity_catalog,
                                  region_countries=region_countries)[0]
    except (ValueError, TypeError, RecursionError):
        raise _target_error() from None
    if type(project_region_verified) is not bool:
        raise ValueError("Nebius project verification flag must be boolean")
    if not isinstance(payload, dict) or "error" in payload or "code" in payload:
        raise FetchError("provider_api_error", "Nebius did not return a successful estimate.")
    if not isinstance(payload.get("currency"), str) or payload["currency"].lower() != target["currency"]:
        raise ValueError("Nebius estimate currency does not match the request")
    raw_costs, raw_totals = payload.get("resourceCosts"), payload.get("totalCosts")
    if not isinstance(raw_costs, list) or not 1 <= len(raw_costs) <= 1000 or not isinstance(raw_totals, list):
        raise ValueError("Nebius estimate resource/total costs are missing")
    declared = {resource["spec"]["metadata"]["name"]: resource["spec"]["@type"].removeprefix(_TYPE_PREFIX)
                for resource in target["resource_specs"]}
    mandatory_names = set(declared)
    for resource in target["resource_specs"]:
        if resource["spec"]["@type"] == _TYPE_PREFIX + "CreateInstanceRequest":
            spec = resource["spec"]["spec"]
            for disk in [spec["bootDisk"], *spec.get("secondaryDisks", [])]:
                declared[disk["managedDisk"]["name"]] = "ManagedDisk"
    indices = {name: index for index, name in enumerate(declared)}
    components, seen_components, represented = [], set(), set()
    for value in raw_costs:
        if not isinstance(value, dict):
            raise ValueError("Nebius resource cost metadata is missing")
        metadata = value.get("overrideMetadata") or value.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) or metadata["name"] not in declared:
            raise ValueError("Nebius resource costs could not be matched to the requested specifications")
        name = metadata["name"]
        line = _resource_cost(value, target)
        pair = (name, line["aggregation_unit"])
        if pair in seen_components:
            raise ValueError("Nebius resource costs contain duplicate specification/unit entries")
        seen_components.add(pair)
        represented.add(name)
        components.append({"resource_index": indices[name], "resource_type": declared[name], **line})
    # At least the actual VM (and each separate requested resource) must be
    # priced in every requested time unit. A month-only storage line is not a
    # GPU-month estimate. If a nested disk is separately itemized, it must also
    # be present in every unit rather than silently disappearing from a total.
    for name in mandatory_names | represented:
        if any((name, unit) not in seen_components for unit in target["aggregation_units"]):
            raise ValueError("Nebius did not price the complete requested configuration in each aggregation unit")
    totals = {}
    for total in raw_totals:
        if not isinstance(total, dict):
            raise ValueError("Nebius total cost schema changed")
        unit = _aggregation(total.get("aggregationUnit"), target)
        if unit in totals or "range" in total or not isinstance(total.get("general"), dict):
            raise ValueError("Nebius estimate total is duplicate, variable or unsupported")
        totals[unit] = _breakdown(total["general"].get("total"))
    if set(totals) != set(target["aggregation_units"]):
        raise ValueError("Nebius estimate omitted a requested aggregation unit")
    instance = next(resource["spec"]["spec"] for resource in target["resource_specs"]
                    if resource["spec"]["@type"] == _TYPE_PREFIX + "CreateInstanceRequest")
    preset = _PRESET.fullmatch(instance["resources"]["preset"])
    result = []
    for unit in target["aggregation_units"]:
        lines = [line for line in components if line["aggregation_unit"] == unit]
        with localcontext(_DECIMAL_CONTEXT):
            cost = _amount(totals[unit]["amount"])
            if not lines or sum((_amount(line["amount"]) for line in lines), Decimal(0)) != cost:
                raise ValueError("Nebius resource costs do not match the batch total")
            allocated = cost / Decimal(target["gpu_count"])
            allocated = allocated.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            if cost > 0 and allocated == 0:
                raise ValueError("Nebius positive GPU price is below the supported decimal precision")
        amount = format(allocated, "f").rstrip("0").rstrip(".") or "0"
        contract = bool(target["offer_types"])
        result.append({
            "provider": "nebius", "product_type": "gpu_instance", "gpu_model": target["gpu_model"],
            "raw_name": instance["resources"]["preset"], "raw_sku": instance["resources"]["platform"],
            "gpu_variant": target.get("gpu_variant"), "gpu_count": target["gpu_count"], "vram_gb": target.get("vram_gb"),
            "amount": amount, "currency": payload["currency"].upper(), "unit": _UNITS[unit][1],
            "billing_mode": "spot" if "preemptible" in instance else "on_demand", "quote_status": "quoted",
            "price_basis": "instance_total_allocated", "account_scope": "account_contract_quote" if contract else "account_quote",
            "tax_scope": "unspecified", "regions": [target["region"]], "zones": [], "compute_countries": [target["country_code"]],
            "geographic_scope": "requested_region", "region_scope": "verified_project_region" if project_region_verified else "requested_region",
            "location": {"region": target["region"], "country_code": target["country_code"], "country_source": REGIONS_URL},
            "location_validation": {"project_region_verified": project_region_verified, "method": "GET /iam/v2/projects/{id}" if project_region_verified else "not verified by standalone parser"},
            "availability": "unknown", "observed_at": observed_at, "source_url": SOURCE_URL,
            "source_type": "official_quote_api", "documentation_url": DOCUMENTATION_URL,
            "instance_price": {"amount": totals[unit]["amount"], "currency": payload["currency"].upper(),
                               "unit": _UNITS[unit][2], "breakdown": totals[unit]},
            "components": lines, "resources": {**instance["resources"], "vcpus": int(preset[2]), "memory_gib": int(preset[3])},
            "configuration_source": PLATFORMS_URL,
            "requested_configuration": _configuration(target),
            "normalization": {"method": "batch total for one configured VM and requested resources / explicit GPU count",
                              "decimal_places": 12, "rounding": "ROUND_HALF_UP"},
            "source_conditions": {"offer_types": list(target["offer_types"]), "aggregation_unit": unit},
            "notes": [
                "Account-scoped fixed configuration estimate, not a public Nebius price catalog or guaranteed invoice.",
                "Returned batch costs for one VM and explicitly itemized storage resources are allocated across its GPU count; nested managed-disk configuration alone does not establish that disk fees were included.",
                ("Compute project region was checked with the read-only Project API; country follows that explicit region in official Nebius documentation, never the requested currency."
                 if project_region_verified else "Standalone parser: region is caller-supplied and has not been verified with the Project API; country only describes that region in official documentation."),
                "GPU model, form factor, VRAM, GPU count, preset CPU/RAM and platform region are checked against the official VM types documentation; this does not verify current inventory or account access.",
                "Monthly cost retains the API's month aggregation; no month-to-hour conversion was assumed.",
                "Tax, network traffic, services outside this request, inventory and orderability were not verified.",
                *( ["Account-specific contract pricing was explicitly requested; verify contractual eligibility and any minimum commitment. This is not an ordinary public rate."] if contract else [] ),
            ],
        })
    return result


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    token = getattr(settings, "nebius_access_token", None)
    if not isinstance(token, str) or not token:
        raise FetchError("missing_credentials", "Set NEBIUS_ACCESS_TOKEN to query account-scoped Nebius configuration estimates.")
    if len(token) > 16384 or not _TOKEN.fullmatch(token):
        raise FetchError("invalid_credentials", "The configured Nebius access token has an invalid format.")
    targets = load_targets(settings)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    verified_projects, result = {}, []
    for index, target in enumerate(targets):
        project_id = target["project_id"]
        if project_id not in verified_projects:
            project = request_json(PROJECT_URL + project_id, settings, headers=headers, authenticated=True)
            if (not isinstance(project, dict) or not isinstance(project.get("metadata"), dict)
                    or project["metadata"].get("id") != project_id or not isinstance(project.get("spec"), dict)
                    or not isinstance(project["spec"].get("region"), str)):
                raise FetchError("project_region_unverified", "Nebius project location could not be verified.")
            verified_projects[project_id] = project["spec"]["region"]
        if verified_projects[project_id] != target["region"]:
            raise FetchError("project_region_mismatch", "The Nebius project region does not match the requested target.")
        payload = request_json(SOURCE_URL, settings, method="POST", headers=headers,
                               data=build_request(target), authenticated=True)
        quotes = parse_quote(payload, target, observed_at=observed_at, project_region_verified=True)
        for quote in quotes:
            quote["target_index"] = index
        result.extend(quotes)
    return result
