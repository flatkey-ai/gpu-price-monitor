"""Pure projection of UCloud's current UHost GPU and geography directories.

Targets describe configurations, not prices or stock. The caller must verify
configuration availability and choose a compatible image and disk before
requesting a price. CPU generations sharing a vendor have the same price
request, but their complete catalog options remain available for validation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_COUNTRY = re.compile(r"[A-Z]{2}\Z")
CONSOLE_NETWORK_RULE_SOURCE = "https://console-s2.ucloud.cn/uhost-components/20261021021640/main.26decb0f52dc886128fa.js"
_EIGHT_GPU_NETWORK_MODELS = frozenset({"H100", "H20", "A800", "MetaX-C500"})


@dataclass
class ConsoleQuoteTarget:
    request: dict
    gpu_model: str
    gpu_count: int
    gpu_memory_gb: int | float | None
    memory_gb: int | float
    cpu_platform_options: list[str]
    country_code: str
    region_name: str
    zone_name: str
    disk_options: list[dict]
    catalog_status: str
    metadata: dict = field(default_factory=dict)

    @property
    def location(self) -> dict:
        return {"country_code": self.country_code, "region": self.request["Region"],
                "region_name": self.region_name, "zone": self.request["Zone"],
                "zone_name": self.zone_name}


@dataclass
class CatalogTargets:
    targets: list[ConsoleQuoteTarget]
    counts: dict[str, int]
    gaps: list[dict]
    exclusions: list[dict] = field(default_factory=list)


def _rows(payload: object, field_name: str) -> list[dict]:
    if (not isinstance(payload, dict) or type(payload.get("RetCode", 0)) is not int
            or payload.get("RetCode", 0) != 0
            or not isinstance(payload.get(field_name), list)
            or len(payload[field_name]) > 100_000
            or any(not isinstance(row, dict) for row in payload[field_name])):
        raise ValueError(f"Invalid UCloud {field_name} response.")
    return payload[field_name]


def _text(value: object, *, code: bool = False) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 256 and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and (not code or _CODE.fullmatch(value) is not None))


def _positive_int(value: object) -> bool:
    return type(value) is int and 0 < value <= 1_000_000


def _number(value: object) -> Decimal:
    if type(value) not in (int, float, Decimal):
        raise ValueError("Invalid numeric specification.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid numeric specification.") from None
    if not number.is_finite() or not 0 < number <= 1_000_000:
        raise ValueError("Invalid numeric specification.")
    return number


def _native_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _directory(payload: dict, collection: str, identity: str) -> dict[str, dict]:
    result = {}
    for row in _rows(payload, collection):
        key = row.get(identity)
        if not _text(key, code=True) or key in result:
            raise ValueError(f"Invalid or duplicate UCloud {identity} identity.")
        result[key] = row
    return result


def _platforms(row: dict, collection: dict) -> dict[str, list[str]]:
    """An explicitly empty restriction is not permission to use every vendor."""
    if "MinimalCpuPlatform" in collection:
        options = collection["MinimalCpuPlatform"]
    else:
        platforms = row.get("CpuPlatforms")
        if isinstance(platforms, dict):
            options = []
            for vendor, values in platforms.items():
                if not _text(vendor, code=True) or not isinstance(values, list):
                    raise ValueError("Invalid CPU platform directory.")
                if any(not isinstance(value, str) or not value.startswith(vendor + "/")
                       for value in values):
                    raise ValueError("CPU platform vendor mismatch.")
                options.extend(values)
        else:
            options = platforms
    if not isinstance(options, list) or not options:
        raise ValueError("No explicit CPU platforms.")
    grouped: dict[str, list[str]] = {}
    for option in options:
        if not _text(option) or option.count("/") != 1:
            raise ValueError("Invalid CPU platform option.")
        vendor, generation = option.split("/")
        if not _text(vendor, code=True) or not _text(generation):
            raise ValueError("Invalid CPU platform option.")
        grouped.setdefault(vendor, [])
        if option not in grouped[vendor]:
            grouped[vendor].append(option)
    return grouped


def _disks(row: dict) -> list[dict]:
    result = []
    supplied = row.get("Disks", [])
    if not isinstance(supplied, list):
        raise ValueError("Invalid disk specifications.")
    for group in supplied:
        if not isinstance(group, dict):
            raise ValueError("Invalid disk group.")
        output = {"Name": group["Name"]} if _text(group.get("Name")) else {}
        for kind in ("BootDisk", "DataDisk"):
            if kind not in group:
                continue
            if not isinstance(group[kind], list):
                raise ValueError("Invalid disk options.")
            output[kind] = []
            for option in group[kind]:
                if not isinstance(option, dict) or not _text(option.get("Name")):
                    raise ValueError("Invalid disk option.")
                output[kind].append(deepcopy({key: option[key] for key in
                    ("Name", "MinimalSize", "MaximalSize", "InstantResize", "Features") if key in option}))
        result.append(output)
    return result


def _network_mode(row: dict, gpu_count: int) -> tuple[str, list[dict], list[str], str]:
    """Apply the console's GPU-count rules before selecting a network baseline.

    The published feature component disables Extreme/Infiniband below eight
    GPUs for these four models, then falls back to Normal. An explicitly empty
    Modes collection also falls back to Normal; a missing/malformed feature
    directory remains an error. This is a frontend rule, not a retry that drops
    an unsupported parameter after the API rejects a different configuration.
    """
    features = row.get("Features")
    if not isinstance(features, list) or any(not isinstance(feature, dict) for feature in features):
        raise ValueError("Missing or invalid GPU network mode directory.")
    network = [feature for feature in features if feature.get("Name") == "NetCapability"]
    if len(network) != 1:
        raise ValueError("Missing or ambiguous GPU network mode directory.")
    modes = network[0].get("Modes")
    if "Modes" in network[0] and (modes is None or modes == []):
        return "Normal", [], [], "official_console_empty_modes_normal"
    if not isinstance(modes, list) or not modes:
        raise ValueError("No explicit GPU network modes.")
    seen = set()
    for mode in modes:
        if not isinstance(mode, dict) or not _text(mode.get("Name"), code=True) or mode["Name"] in seen:
            raise ValueError("Invalid or duplicate GPU network mode.")
        seen.add(mode["Name"])
        related = mode.get("RelatedToImageFeature", [])
        if not isinstance(related, list) or any(not _text(feature, code=True) for feature in related):
            raise ValueError("Invalid GPU network image requirements.")
    advanced = next((mode for name in ("Extreme", "Infiniband")
                     for mode in modes if mode["Name"] == name), None)
    if row.get("Name") in _EIGHT_GPU_NETWORK_MODELS and advanced is not None:
        if gpu_count < 8:
            return "Normal", deepcopy(modes), [], "official_console_gpu_count_normal"
        selected = advanced
        basis = "official_console_gpu_count_enhanced"
    else:
        selected = next((mode for mode in modes if mode["Name"] == "Normal"), None)
        basis = "catalog_normal_or_only_mode"
    if selected is None:
        if len(modes) != 1:
            raise ValueError("GPU network baseline is ambiguous without Normal mode.")
        selected = modes[0]
    if selected["Name"] not in {"Normal", "Super", "Ultra", "Extreme", "Infiniband"}:
        raise ValueError("Unsupported GPU network baseline mode.")
    if selected.get("MinimalCpuPlatform"):
        raise ValueError("GPU network baseline CPU restriction cannot be verified.")
    return selected["Name"], deepcopy(modes), list(selected.get("RelatedToImageFeature", [])), basis


def _row_targets(row: dict, geography: dict, row_index: int) -> list[ConsoleQuoteTarget]:
    name, status = row.get("Name"), row.get("Status")
    if not _text(name) or not _text(status):
        raise ValueError("Missing model or catalog status.")
    graphics = row.get("GraphicsMemory")
    vram = _native_number(_number(graphics["Value"])) if isinstance(graphics, dict) and "Value" in graphics else None
    disks = _disks(row)
    sizes = row.get("MachineSizes")
    if not isinstance(sizes, list) or not sizes:
        raise ValueError("No explicit GPU configurations.")
    targets = {}
    for size in sizes:
        if not isinstance(size, dict) or not _positive_int(size.get("Gpu")):
            raise ValueError("Invalid GPU count.")
        network_mode, network_options, network_image_features, network_basis = _network_mode(row, size["Gpu"])
        collections = size.get("Collection")
        if not isinstance(collections, list) or not collections:
            raise ValueError("Missing CPU/memory configurations.")
        for collection in collections:
            if not isinstance(collection, dict) or not _positive_int(collection.get("Cpu")):
                raise ValueError("Invalid CPU configuration.")
            memories = collection.get("Memory")
            if not isinstance(memories, list) or not memories:
                raise ValueError("Missing memory configurations.")
            platforms = _platforms(row, collection)
            for memory in memories:
                memory_gb = _number(memory)
                memory_mb = memory_gb * 1024
                if memory_mb != memory_mb.to_integral_value():
                    raise ValueError("Memory cannot be represented as integer MB.")
                for vendor, options in platforms.items():
                    identity = (size["Gpu"], collection["Cpu"], int(memory_mb), vendor)
                    if identity in targets:
                        current = targets[identity]
                        current.cpu_platform_options = list(dict.fromkeys(current.cpu_platform_options + options))
                        continue
                    request = {"Region": geography["region"], "Zone": geography["zone"],
                               "MachineType": "G", "GpuType": name, "GPU": size["Gpu"],
                               "CPU": collection["Cpu"], "Memory": int(memory_mb), "CpuPlatform": vendor,
                               "NetCapability": network_mode,
                               "ChargeType": "Dynamic", "Count": 1, "ShowPriceDetails": True}
                    targets[identity] = ConsoleQuoteTarget(
                        request=request, gpu_model=name, gpu_count=size["Gpu"], gpu_memory_gb=vram,
                        memory_gb=_native_number(memory_gb), cpu_platform_options=list(options),
                        country_code=geography["country_code"], region_name=geography["region_name"],
                        zone_name=geography["zone_name"], disk_options=deepcopy(disks), catalog_status=status,
                        metadata={"catalog_row_index": row_index, "instance_type": "uhost",
                                  "billing_scope": "on_demand_only", "availability_verified": False,
                                  "country_basis": "ListRegions.CountryCode",
                                  "cpu_platform_price_scope": "vendor",
                                  "network_mode": network_mode,
                                  "network_mode_options": deepcopy(network_options),
                                  "network_mode_required_image_features": list(network_image_features),
                                  "network_mode_selection_basis": network_basis,
                                  **({"network_mode_selection_source": CONSOLE_NETWORK_RULE_SOURCE}
                                     if network_basis.startswith("official_console_") else {}),
                                  "image_and_disks_selected": False})
    return list(targets.values())


def build_catalog_targets(regions_response: dict, zones_response: dict,
                          instances_response: dict) -> CatalogTargets:
    """Build region-specific on-demand candidates; never infer a country.

    Invalid individual GPU rows are reported in ``gaps`` and excluded in full.
    Invalid/duplicate directory identities reject the directory. Spot is counted
    but excluded from this on-demand collector. A catalog status is never turned
    into a claim that the configuration is currently available.
    """
    regions = _directory(regions_response, "Regions", "Region")
    zones = _directory(zones_response, "Zones", "Zone")
    rows = _rows(instances_response, "AvailableInstanceTypes")
    counts = {"catalog_rows": len(rows), "gpu_catalog_rows": 0, "uhost_gpu_catalog_rows": 0,
              "spot_gpu_catalog_rows": 0, "other_gpu_catalog_rows": 0,
              "uhost_gpu_rows_with_targets": 0, "uhost_gpu_rows_excluded": 0,
              "duplicate_gpu_catalog_rows": 0, "duplicate_quote_targets": 0,
              "uhost_gpu_rows_outside_console_scope": 0}
    targets, gaps, exclusions, seen_rows, conflicts = {}, [], [], [], set()
    for index, original in enumerate(rows):
        if original.get("ParentType") != "G":
            continue
        counts["gpu_catalog_rows"] += 1
        kind = original.get("InstanceType")
        if kind != "uhost":
            counts["spot_gpu_catalog_rows" if kind == "spot" else "other_gpu_catalog_rows"] += 1
            continue
        counts["uhost_gpu_catalog_rows"] += 1
        row = dict(original)
        if isinstance(row.get("GpuType"), dict):
            row.update(row["GpuType"])
        if row in seen_rows:
            counts["duplicate_gpu_catalog_rows"] += 1
            continue
        seen_rows.append(row)
        gap = {"catalog_row_index": index, "code": "invalid_gpu_configuration"}
        for key in ("Name", "Zone"):
            if _text(row.get(key)):
                gap[key.lower()] = row[key]
        # The GPU page filters its catalog through the current official zone
        # directory, then Status=Normal. Preserve known omissions separately
        # from malformed visible data; neither is a quoted/offline GPU price.
        exclusion = None
        if _text(row.get("Zone"), code=True) and row["Zone"] not in zones:
            exclusion = {**gap, "code": "outside_current_console_zone_directory",
                         "reason": "The current console zone directory does not expose this catalog row."}
        elif row.get("Status") == "Soldout" and not row.get("MachineSizes"):
            exclusion = {**gap, "code": "soldout_catalog_without_configurations", "catalog_status": "Soldout",
                         "reason": "The official catalog supplies no configurations and the GPU page excludes this Soldout row."}
        if exclusion:
            counts["uhost_gpu_rows_outside_console_scope"] += 1
            exclusions.append(exclusion)
            continue
        try:
            zone = zones.get(row.get("Zone"))
            region = regions.get(zone.get("Region")) if zone else None
            country = region.get("CountryCode") if region else None
            if (not zone or not region or not isinstance(country, str) or not _COUNTRY.fullmatch(country)
                    or not _text(zone.get("LocalName")) or not _text(region.get("LocalName"))):
                gap["code"] = "unverified_country_or_region"
                raise ValueError("Complete official country, region and zone information is required.")
            geography = {"country_code": country, "region": region["Region"], "zone": zone["Zone"],
                         "region_name": region["LocalName"], "zone_name": zone["LocalName"]}
            candidates = _row_targets(row, geography, index)
            for candidate in candidates:
                identity = tuple(candidate.request.items())
                if identity in conflicts:
                    continue
                previous = targets.get(identity)
                if previous is None:
                    targets[identity] = candidate
                elif (previous.gpu_memory_gb, previous.disk_options, previous.catalog_status,
                      previous.metadata["network_mode_options"]) == (
                        candidate.gpu_memory_gb, candidate.disk_options, candidate.catalog_status,
                        candidate.metadata["network_mode_options"]):
                    counts["duplicate_quote_targets"] += 1
                    previous.cpu_platform_options = list(dict.fromkeys(
                        previous.cpu_platform_options + candidate.cpu_platform_options))
                else:
                    targets.pop(identity)
                    conflicts.add(identity)
                    gaps.append({**gap, "code": "conflicting_gpu_configuration"})
            counts["uhost_gpu_rows_with_targets"] += 1
        except (ValueError, TypeError) as error:
            counts["uhost_gpu_rows_excluded"] += 1
            if isinstance(error, ValueError):
                gap["reason"] = str(error)
            gaps.append(gap)
    targets = list(targets.values())
    targets.sort(key=lambda target: (target.gpu_model, target.request["Region"], target.request["Zone"],
                                    target.gpu_count, target.request["CPU"], target.request["Memory"],
                                    target.request["CpuPlatform"]))
    counts.update(quote_targets=len(targets), gpu_models=len({t.gpu_model for t in targets}),
                  regions=len({t.request["Region"] for t in targets}), zones=len({t.request["Zone"] for t in targets}))
    return CatalogTargets(targets, counts, gaps, exclusions)
