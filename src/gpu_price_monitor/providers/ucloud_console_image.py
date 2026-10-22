"""Choose one source-derived Linux image and minimal boot disk per target.

This baseline does not enumerate OS variants, additional disks or networking.
Image compatibility follows the official GPU creation page's feature filters.
No resource is created and no image or disk price is invented here; the caller
still needs the configuration-price response, including its price breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .ucloud_console_catalog import ConsoleQuoteTarget


@dataclass
class ImageDiskSelection:
    request: dict
    metadata: dict


def _text(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 512 and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _size(value: object) -> int | None:
    if type(value) not in (int, float, Decimal):
        return None
    number = Decimal(str(value))
    if not number.is_finite() or not 0 < number <= 1_000_000 or number != number.to_integral_value():
        return None
    return int(number)


def _compatible_image(image: dict, target: ConsoleQuoteTarget, *, gpu_market: bool) -> bool:
    if any(image.get(field) != expected for field, expected in
           (("ImageType", "Business" if gpu_market else "Base"),
            ("OsType", "Linux"), ("State", "Available"))):
        return False
    if gpu_market:
        supported = image.get("SupportedGPUTypes")
        if (not isinstance(supported, list) or any(not _text(model) for model in supported)
                or target.gpu_model not in supported):
            return False
    if any(not _text(image.get(field)) for field in ("ImageId", "ImageName", "OsName", "Zone")):
        return False
    # DescribeImage is requested by Region, not Zone. Its image's home zone may
    # differ from the chosen deployment zone within that same region.
    if not image["Zone"].startswith(target.request["Region"] + "-"):
        return False
    features = image.get("Features")
    if not isinstance(features, list) or any(not _text(feature) for feature in features):
        return False
    # The catalog's mode-specific prerequisites apply in addition to the GPU
    # creation page's model filters (notably Super requires NetEnhanced).
    required = target.metadata.get("network_mode_required_image_features", [])
    if (not isinstance(required, list) or any(not _text(feature) for feature in required)
            or not set(required).issubset(features)):
        return False
    special_network = {"Extreme": "NetEnhanced_Extreme", "Infiniband": "NetEnhanced_Infiniband"}
    mode_feature = special_network.get(target.request.get("NetCapability"))
    if mode_feature and mode_feature not in features:
        return False
    if {"Vgpu_AMD", "Vgpu_NVIDIA"}.intersection(features):
        return False
    if any(model in image["OsName"] for model in ("MI100", "V100S")):
        return False
    if target.request["CpuPlatform"] in {"Ampere", "Kunpeng"}:
        return "Aarch64_Type" in features
    if target.gpu_model in {"A800", "H200", "B200"}:
        return "NetEnhanced_Extreme" in features
    if target.gpu_model in {"MetaX-C500", "H20", "H100", "H800"}:
        return "NetEnhanced_Infiniband" in features
    return ("StandardKernel" in features and not
            {"Aarch64_Type", "NetEnhanced_Extreme", "NetEnhanced_Infiniband"}.intersection(features))


def select_image_and_disk(target: ConsoleQuoteTarget, images_payload: dict,
                          *, gpu_market: bool = False) -> ImageDiskSelection:
    """Select a compatible official Linux image and a minimal boot disk.

    Uses only this region's complete ``DescribeImage`` response and the target's
    catalog disk options. ``OpenClaw`` images are considered only when no other
    compatible image/disk pair exists. The default selects Base images. With
    ``gpu_market=True``, only Business images explicitly listing the target's
    GPU in ``SupportedGPUTypes`` qualify. Their license cost must still be
    verified from the price response. Selection is deterministic;
    after software and boot-size preference, newer source images win ties.
    """
    if type(gpu_market) is not bool:
        raise ValueError("Invalid UCloud GPU market image selection flag.")
    if (not isinstance(images_payload, dict) or type(images_payload.get("RetCode", 0)) is not int
            or images_payload.get("RetCode", 0) != 0 or not isinstance(images_payload.get("ImageSet"), list)):
        raise ValueError("Invalid UCloud image directory response.")
    images = images_payload["ImageSet"]
    total = images_payload.get("TotalCount")
    if total is not None and (type(total) is not int or total != len(images)):
        raise ValueError("UCloud image directory is incomplete or has an invalid TotalCount.")
    if len(images) > 100_000 or any(not isinstance(image, dict) for image in images):
        raise ValueError("Invalid UCloud image directory rows.")
    if any(not _text(target.request.get(field)) for field in ("Region", "Zone", "CpuPlatform")):
        raise ValueError("Invalid UCloud image target.")
    boot_options = [option for group in target.disk_options for option in group.get("BootDisk", [])]
    candidates = []
    seen_ids = {}
    for image in images:
        if not _compatible_image(image, target, gpu_market=gpu_market):
            continue
        image_id = image["ImageId"]
        if image_id in seen_ids and image != seen_ids[image_id]:
            raise ValueError("Conflicting UCloud image identities.")
        seen_ids[image_id] = image
        image_size = _size(image.get("ImageSize"))
        if image_size is None:
            continue
        for option in boot_options:
            if not isinstance(option, dict) or not _text(option.get("Name")):
                continue
            minimum = _size(option["MinimalSize"]) if "MinimalSize" in option else image_size
            maximum = _size(option.get("MaximalSize"))
            if minimum is None or maximum is None:
                continue
            boot_size = max(image_size, minimum)
            if boot_size > maximum:
                continue
            if option.get("InstantResize") is False and boot_size != image_size:
                continue
            if option["Name"] == "CLOUD_RSSD" and "RssdAttachable" not in image["Features"]:
                continue
            created = image.get("CreateTime")
            created = created if type(created) is int and created >= 0 else 0
            software_name = (image["ImageName"] + " " + image["OsName"]).casefold()
            order = ("openclaw" in software_name, boot_size, -created,
                     image["ImageName"], image_id, option["Name"])
            candidates.append((order, image, option, boot_size, minimum, maximum))
    if not candidates:
        kind = "GPU market" if gpu_market else "Base"
        raise ValueError(f"No verified compatible {kind} Linux image and boot disk for this UCloud configuration.")
    _, image, disk, boot_size, minimum, maximum = min(candidates, key=lambda item: item[0])
    return ImageDiskSelection(
        request={"ImageId": image["ImageId"], "Disks": [{"IsBoot": "True", "Type": disk["Name"],
                                                       "Size": boot_size, "BackupType": "NONE"}]},
        metadata={"image_id": image["ImageId"], "image_name": image["ImageName"], "image_type": image["ImageType"],
                  "os_type": "Linux", "os_name": image["OsName"], "image_home_zone": image["Zone"],
                  "image_size_gb": _size(image["ImageSize"]), "image_features": list(image["Features"]),
                  **({"image_supported_gpu_types": list(image["SupportedGPUTypes"])} if gpu_market else {}),
                  "boot_disk_type": disk["Name"], "boot_disk_size_gb": boot_size,
                  "boot_disk_catalog_minimum_gb": minimum, "boot_disk_catalog_maximum_gb": maximum,
                  "boot_disk_minimum_basis": "MinimalSize" if "MinimalSize" in disk else "ImageSize",
                  "configuration_scope": ("one_compatible_gpu_market_linux_image_and_minimal_boot_disk"
                                          if gpu_market else "one_compatible_base_linux_image_and_minimal_boot_disk"),
                  "extra_data_disks": False, "public_network_included": False,
                  "image_selection_basis": "official_gpu_create_feature_filters",
                  "image_license_price_verified": False})
