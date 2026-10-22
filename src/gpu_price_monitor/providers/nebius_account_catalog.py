"""Discover authorized Nebius regional GPU presets and ask the cost calculator.

Only tenant/project/platform GETs and the non-provisioning EstimateBatch POST
are permitted. This is an account-scoped catalog, never all customer contracts.
The default comparison target includes a 40 GiB managed SSD boot disk; no disk
or VM is created. Users can explicitly choose a different disk size/currency.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from urllib.parse import urlencode

from ..settings import Settings
from ..transport import FetchError, fetch_text, request_json
from . import nebius_catalog_expanded, nebius_quote, nebius_regions

SOURCE_URL = nebius_quote.SOURCE_URL
SOURCE_TYPE = "official_quote_api"
DOCUMENTATION_URL = nebius_quote.DOCUMENTATION_URL
TENANTS_URL = "https://api.nebius.cloud/iam/v2/tenants"
PROJECTS_URL = "https://api.nebius.cloud/iam/v2/projects"
PLATFORMS_URL = "https://api.nebius.cloud/compute/v1/platforms"
MAX_PAGES = 10
PAGE_SIZE = 100
MAX_TARGETS = 1000
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _invalid() -> ValueError:
    return ValueError("The Nebius account catalog identity, region or preset structure changed.")


def _label(value) -> bool:
    return isinstance(value, str) and _LABEL.fullmatch(value) is not None


def _reference(identity: str) -> str:
    return sha256(identity.encode("utf-8")).hexdigest()[:16]


def _list(url: str, settings: Settings, headers: dict, *, parent: str | None = None) -> list[dict]:
    """Bounded fixed-origin pagination; opaque tokens stay query values."""
    rows, tokens, identities = [], set(), set()
    token = None
    for _ in range(MAX_PAGES):
        query = {"pageSize": str(PAGE_SIZE)}
        if parent is not None:
            query["parentId"] = parent
        if token is not None:
            query["pageToken"] = token
        payload = request_json(url + "?" + urlencode(query), settings, headers=headers, authenticated=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > PAGE_SIZE:
            raise _invalid()
        for item in payload["items"]:
            metadata = item.get("metadata") if isinstance(item, dict) else None
            identity = (metadata.get("id") or metadata.get("name")) if isinstance(metadata, dict) else None
            if not _label(identity) or identity in identities:
                raise _invalid()
            identities.add(identity)
            rows.append(item)
        token = payload.get("nextPageToken")
        if token in (None, ""):
            return rows
        if (not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 32 for c in token)
                or token in tokens or not payload["items"]):
            raise FetchError("invalid_pagination", "Nebius account catalog pagination was invalid.")
        tokens.add(token)
    raise FetchError("pagination_limit", "Nebius account catalog exceeded its pagination safety limit.")


def identity_catalog(platforms: dict) -> dict:
    """Build validation identities from the freshly fetched official types table."""
    return {
        identity: (p["gpu_model"], p["form_factor"], p["vram_gb"],
                   {preset["preset"] for preset in p["presets"]}, set(p["coverage_regions"]))
        for identity, p in platforms.items()
    }


def discover_targets(platform_rows: list[dict], project: dict, platforms: dict, *,
                     boot_disk_gib: int, currency: str) -> dict:
    """Cross-check API presets with current documentation before estimating.

    New or changed API presets are reported as gaps, not silently dropped or
    mapped to the nearest familiar GPU. CPU-only platforms are counted apart.
    The returned targets are private request data; collect_result never emits
    them or account names/IDs in its public result.
    """
    if (not isinstance(platform_rows, list) or not isinstance(project, dict)
            or not _label(project.get("project_id")) or not project["project_id"].startswith("project-")
            or type(boot_disk_gib) is not int or not 1 <= boot_disk_gib <= 32768 or currency not in {"usd", "ils"}):
        raise _invalid()
    targets, gaps, seen = [], [], set()
    excluded_cpu, discovered_gpu = 0, 0
    for row in platform_rows:
        metadata = row.get("metadata") if isinstance(row, dict) else None
        spec = row.get("spec") if isinstance(row, dict) else None
        name = metadata.get("name") if isinstance(metadata, dict) else None
        presets = spec.get("presets") if isinstance(spec, dict) else None
        if not _label(name) or not isinstance(presets, list):
            raise _invalid()
        gpu_presets = []
        for preset in presets:
            resources = preset.get("resources") if isinstance(preset, dict) else None
            preset_name = preset.get("name") if isinstance(preset, dict) else None
            if not _label(preset_name):
                raise _invalid()
            count = resources.get("gpuCount") if isinstance(resources, dict) else None
            if type(count) is int and count > 0:
                gpu_presets.append(preset)
            elif name.startswith("cpu-") and type(count) is int and count == 0:
                excluded_cpu += 1
            else:
                if name.startswith("gpu-") or name in platforms:
                    discovered_gpu += 1
                gaps.append({"platform": name, "preset": preset_name, "region": project["region"],
                             "status": "preset_resource_conflict",
                             "reason": "A GPU/unknown platform preset has no valid positive GPU count; it was not classified as a CPU preset."})
        if not gpu_presets:
            continue
        documented = platforms.get(name)
        for preset in gpu_presets:
            discovered_gpu += 1
            preset_name, resources = preset.get("name"), preset["resources"]
            if not _label(preset_name) or (name, preset_name) in seen:
                raise _invalid()
            seen.add((name, preset_name))
            scope = {"platform": name, "preset": preset_name, "region": project["region"]}
            matching = ([p for p in documented["presets"] if p["preset"] == preset_name
                         and project["region"] in p["coverage_regions"]] if documented else [])
            if len(matching) != 1:
                gaps.append({**scope, "status": "identity_not_verified",
                             "reason": "API preset has no matching current documented platform/preset/region."})
                continue
            expected = matching[0]
            if ("gpuMemoryGigabytes" in spec
                    and (type(spec["gpuMemoryGigabytes"]) is not int
                         or spec["gpuMemoryGigabytes"] != documented["vram_gb"])):
                gaps.append({**scope, "status": "gpu_memory_gb_conflict",
                             "reason": "Explicit API GPU-memory GB differs from the current documented per-GPU GB identity or has an invalid type."})
                continue
            if any(type(resources.get(key)) is not int or resources[key] != expected[expected_key]
                   for key, expected_key in (("gpuCount", "gpu_count"), ("vcpuCount", "vcpus"), ("memoryGibibytes", "memory_gib"))):
                gaps.append({**scope, "status": "preset_resource_conflict",
                             "reason": "API GPU/CPU/RAM quantities disagree with the documented preset."})
                continue
            serial = len(targets)
            targets.append({
                **project, "gpu_model": documented["gpu_model"], "gpu_count": expected["gpu_count"],
                "gpu_variant": documented["form_factor"], "vram_gb": documented["vram_gb"],
                "currency": currency, "aggregation_units": ["hour"], "offer_types": [],
                "resource_specs": [{"spec": {"@type": "type.googleapis.com/nebius.compute.v1.CreateInstanceRequest",
                    "metadata": {"parentId": project["project_id"], "name": f"catalog-price-{serial}"},
                    "spec": {"resources": {"platform": name, "preset": preset_name}, "onDemand": {},
                        "bootDisk": {"attachMode": "READ_WRITE", "managedDisk": {
                            "name": f"catalog-boot-{serial}", "spec": {"type": "NETWORK_SSD", "sizeGibibytes": str(boot_disk_gib)}}}}}}],
            })
    return {"targets": targets, "gaps": gaps, "discovered_gpu_preset_count": discovered_gpu,
            "excluded_cpu_preset_count": excluded_cpu}


def _error(scope: str, exc, *, region: str | None = None, project_ref: str | None = None) -> dict:
    # Do not include provider error bodies, tokens, project IDs or account names.
    return {"scope": scope, "region": region, "project_reference": project_ref,
            "code": exc.code if isinstance(exc, FetchError) else "parse_failed",
            "message": "The read-only Nebius account catalog/estimate request could not be verified.",
            "retryable": exc.retryable if isinstance(exc, FetchError) else False}


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Discover all readable regional presets, estimating each independently.

    No stable shared-region-price claim is made: each returned account quote
    comes from one calculator request for a project whose API region was read.
    """
    token = getattr(settings, "nebius_access_token", None)
    if not isinstance(token, str) or not token:
        raise FetchError("missing_credentials", "Set NEBIUS_ACCESS_TOKEN for the read-only regional Nebius catalog and calculator.")
    if len(token) > 16384 or not nebius_quote._TOKEN.fullmatch(token):
        raise FetchError("invalid_credentials", "The configured Nebius access token has an invalid format.")
    disk = getattr(settings, "nebius_catalog_boot_disk_gib", 40)
    currency = getattr(settings, "nebius_catalog_currency", "usd")
    if type(disk) is not int or not 1 <= disk <= 32768 or currency not in {"usd", "ils"}:
        raise FetchError("invalid_catalog_configuration", "Nebius catalog targets need an explicit valid SSD boot disk size and USD/ILS currency.")
    headers = {"Authorization": "Bearer " + token}
    regions = nebius_catalog_expanded.parse_regions(
        fetch_text(nebius_catalog_expanded.REGIONS_URL, settings), observed_at=observed_at)
    platforms = nebius_catalog_expanded.parse_platforms(fetch_text(nebius_catalog_expanded.TYPES_URL, settings), regions)
    identities = identity_catalog(platforms)
    country_codes = {region: info["country_code"] for region, info in regions.items()}
    tenants = _list(TENANTS_URL, settings, headers)
    errors, gaps, prices, contexts, projects = [], [], [], [], []
    coverage = {"tenant_count": len(tenants), "project_count": 0, "verified_project_count": 0,
                "discovered_gpu_preset_count": 0, "excluded_cpu_preset_count": 0,
                "estimate_target_count": 0, "successful_estimate_count": 0,
                "region_codes": [], "country_codes": [], "all_account_prices_complete": False}
    project_ids = set()
    for tenant in tenants:
        tenant_id = tenant["metadata"].get("id")
        if not isinstance(tenant_id, str) or not tenant_id.startswith("tenant-"):
            raise _invalid()
        try:
            discovered = _list(PROJECTS_URL, settings, headers, parent=tenant_id)
            for project in discovered:
                metadata, spec = project.get("metadata"), project.get("spec")
                project_id = metadata.get("id") if isinstance(metadata, dict) else None
                region = spec.get("region") if isinstance(spec, dict) else None
                if (not _label(project_id) or not project_id.startswith("project-") or project_id in project_ids
                        or not isinstance(region, str)):
                    raise _invalid()
                project_ids.add(project_id)
                coverage["project_count"] += 1
                if region not in regions:
                    gaps.append({"scope": "project_region", "project_reference": _reference(project_id), "region": region,
                                 "status": "country_not_verified", "reason": "Project API region is absent from the current official country directory."})
                    continue
                projects.append({"project_id": project_id, "region": region, "country_code": regions[region]["country_code"]})
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            errors.append(_error("project_discovery", exc))
    coverage["verified_project_count"] = len(projects)
    readable_regions = {project["region"] for project in projects}
    for region, info in regions.items():
        if not info["private_region"] and region not in readable_regions:
            gaps.append({"scope": "documented_public_region", "region": region,
                         "country_code": info["country_code"], "status": "no_accessible_project",
                         "reason": "The official directory lists this public region, but no authorized project was returned; its account prices were not estimated."})
    targets_seen = 0
    for project in projects:
        region, reference = project["region"], _reference(project["project_id"])
        try:
            platform_rows = _list(PLATFORMS_URL, settings, headers, parent=project["project_id"])
            discovery = discover_targets(platform_rows, project, platforms, boot_disk_gib=disk, currency=currency)
            coverage["discovered_gpu_preset_count"] += discovery["discovered_gpu_preset_count"]
            coverage["excluded_cpu_preset_count"] += discovery["excluded_cpu_preset_count"]
            gaps.extend({**g, "project_reference": reference} for g in discovery["gaps"])
            targets = discovery["targets"]
            contexts.append({"source": "regional_platform_catalog", "region": region,
                             "country_code": project["country_code"], "project_reference": reference,
                             "gpu_preset_count": discovery["discovered_gpu_preset_count"], "verified_target_count": len(targets),
                             "source_url": PLATFORMS_URL, "status": "ok"})
        except (FetchError, ValueError, TypeError, KeyError) as exc:
            errors.append(_error("platform_discovery", exc, region=region, project_ref=reference))
            continue
        for target in targets:
            targets_seen += 1
            if targets_seen > MAX_TARGETS:
                errors.append({"scope": "account_catalog", "code": "target_limit", "retryable": False,
                               "message": "Nebius target safety limit reached; remaining account presets were not estimated."})
                break
            coverage["estimate_target_count"] += 1
            resource = target["resource_specs"][0]["spec"]["spec"]["resources"]
            try:
                validated = nebius_quote.validate_targets(json.dumps([target]), identity_catalog=identities,
                                                         region_countries=country_codes)[0]
                payload = request_json(SOURCE_URL, settings, method="POST",
                                       headers={**headers, "Content-Type": "application/json"},
                                       data=nebius_quote.build_request(validated), authenticated=True)
                quotes = nebius_quote.parse_quote(payload, validated, observed_at=observed_at,
                                                  project_region_verified=True, identity_catalog=identities,
                                                  region_countries=country_codes)
                for quote in quotes:
                    quote["project_reference"] = reference
                    quote["location_validation"] = {"project_region_verified": True,
                                                    "method": "GET /iam/v2/projects (authorized tenant list)",
                                                    "region_field": "items[].spec.region"}
                    quote["location"].update({key: regions[region][key] for key in
                                              ("region_name", "region_name_zh", "country_name", "country_name_zh")})
                    quote["location_source"] = deepcopy(regions[region])
                    quote["catalog_discovery"] = {"method": "authenticated_tenant_project_platform_list",
                                                   "platform_catalog_url": PLATFORMS_URL,
                                                   "project_region_source_url": PROJECTS_URL,
                                                   "fresh_platform_and_preset_verified": True}
                    quote["selected_configuration"] = {**resource, "boot_disk_gib": disk, "boot_disk_type": "NETWORK_SSD"}
                    quote["conditions"] = [f"一个GPU实例及{disk} GiB SSD启动盘的账号估价，按GPU数量分摊；不创建资源。",
                                           "项目API已核实部署地区；逐项目询价，不假定跨地区统一。",
                                           "不含本次未请求的网络及其他服务；库存、税项、最终订单价格未验证。"]
                    prices.append(quote)
                coverage["successful_estimate_count"] += 1
            except (FetchError, ValueError, TypeError, KeyError) as exc:
                errors.append({**_error("regional_configuration_estimate", exc, region=region, project_ref=reference), **resource})
        if targets_seen > MAX_TARGETS:
            break
    coverage["region_codes"] = sorted({p["region"] for p in projects})
    coverage["country_codes"] = sorted({p["country_code"] for p in projects})
    if not tenants or not projects:
        gaps.append({"scope": "authorized_projects", "status": "no_accessible_projects",
                     "reason": "No readable regional GPU projects were returned; no account prices were manufactured."})
    gaps.append({"scope": "other_accounts_and_contracts", "status": "outside_authorized_account_scope",
                 "reason": "Only accessible projects and ordinary on-demand estimates are queried; private sales/contract offers and capacity are not guaranteed."})
    return {"status": ("partial" if prices else "failed") if errors or not prices or len(gaps) > 1 else "ok",
            "prices": prices, "errors": errors, "gaps": gaps, "source_contexts": contexts,
            "authentication_method": "IAM_Bearer_token", "coverage": coverage,
            "catalog_coverage": {"summary": coverage, "regions": deepcopy(regions),
                                 "target_configuration": {"boot_disk_gib": disk, "boot_disk_type": "NETWORK_SSD",
                                                          "currency": currency.upper(), "aggregation_unit": "hour",
                                                          "capacity_type": "on_demand"},
                                 "source_urls": [TENANTS_URL, PROJECTS_URL, PLATFORMS_URL, SOURCE_URL]},
            "pricing_limitations": ["API discovery is account-scoped, not a worldwide price catalog.",
                                     "Each estimate includes the explicitly configured SSD boot disk; no resources are provisioned."]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    result = collect_result(settings=settings, observed_at=observed_at)
    if result["status"] != "ok":
        raise FetchError("partial_collection", "Inspect Nebius account catalog diagnostics for unpriced projects/presets.")
    return result["prices"]
