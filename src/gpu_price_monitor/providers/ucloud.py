"""Collect explicit UHost GPU configuration quotes from the official API.

This adapter only calls GetUHostInstancePrice. It never creates resources and
does not discover inventory: callers must supply configurations they intend to
compare. The source's CNY instance-hour amount includes the requested CPU, RAM
and disks; the per-GPU amount is a cost allocation, not a GPU-only tariff.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
import re
from urllib.parse import urlencode

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://api.ucloud.cn/"
DOCUMENTATION_URL = "https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price"
MAX_TARGETS = 20
MAX_TARGET_JSON_BYTES = 128 * 1024
_ACTION = "GetUHostInstancePrice"
_REQUIRED = {"Region", "Zone", "MachineType", "GpuType", "GPU", "CPU", "Memory", "Disks"}
_OPTIONAL = {
    "ProjectId", "ImageId", "CpuPlatform", "UHostFamily", "NetCapability",
    "UDSetUHostInstance", "ShowPriceDetails", "ChargeType", "Count",
}
# These are exact provider model labels, not inventory or availability claims.
# Fractional/shared GPU labels (for example T4/4) are deliberately unsupported.
_GPU_TYPES = {
    "K80", "P40", "V100", "T4", "T4A", "T4S", "2080Ti", "1080Ti",
    "MI100", "V100S", "2080", "2080TiS", "2080TiPro", "3090", "4090",
    "4090Pro", "4090_48G", "A100", "A800", "H20", "5090",
}
_DISK_FIELDS = {"IsBoot", "Size", "Type", "BackupType"}
_DISK_TYPES = {"CLOUD_NORMAL", "CLOUD_SSD", "CLOUD_RSSD", "LOCAL_NORMAL", "LOCAL_SSD"}
_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")


def _target_error() -> FetchError:
    return FetchError(
        "invalid_price_targets",
        "UCloud price targets are invalid. Supply 1-20 explicit GPU configurations with Region, Zone, MachineType=G, GpuType, GPU, CPU, Memory in MB and Disks in GB; only Dynamic and Count=1 are supported.",
    )


def _label(value: object) -> bool:
    return isinstance(value, str) and _SAFE_LABEL.fullmatch(value) is not None


def _positive_integer(value: object) -> bool:
    return type(value) is int and 0 < value <= 1_000_000


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise _target_error()
        result[name] = value
    return result


def load_targets(settings: Settings) -> list[dict]:
    """Validate all targets before sending any requests; never echo ENV values."""
    raw = settings.ucloud_price_targets_json
    if raw is None or raw == "":
        raise FetchError(
            "missing_price_targets",
            "Set UCLOUD_PRICE_TARGETS_JSON or load UCLOUD_PRICE_TARGETS_FILE with Settings.from_env to supply explicit UCloud GPU quote targets.",
        )
    if not isinstance(raw, str):
        raise _target_error()
    try:
        if len(raw.encode("utf-8")) > MAX_TARGET_JSON_BYTES:
            raise _target_error()
    except UnicodeError:
        raise _target_error() from None
    try:
        targets = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, TypeError, RecursionError):
        raise _target_error() from None
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        raise _target_error()
    if settings.ucloud_project_id is not None and not _label(settings.ucloud_project_id):
        raise _target_error()
    validated = []
    seen = set()
    for supplied in targets:
        if not isinstance(supplied, dict) or not _REQUIRED <= supplied.keys():
            raise _target_error()
        if supplied.keys() - (_REQUIRED | _OPTIONAL):
            raise _target_error()
        target = deepcopy(supplied)
        if (target["MachineType"] != "G" or not isinstance(target["GpuType"], str)
                or target["GpuType"] not in _GPU_TYPES):
            raise _target_error()
        if not _label(target["Region"]) or not _label(target["Zone"]):
            raise _target_error()
        if not target["Zone"].startswith(target["Region"] + "-"):
            raise _target_error()
        if any(not _positive_integer(target[name]) for name in ("GPU", "CPU", "Memory")):
            raise _target_error()
        if target["Memory"] % 1024:
            raise _target_error()
        if target.get("ChargeType", "Dynamic") != "Dynamic":
            raise _target_error()
        if type(target.get("Count", 1)) is not int or target.get("Count", 1) != 1:
            raise _target_error()
        for name in ("ProjectId", "ImageId", "CpuPlatform", "UHostFamily", "NetCapability"):
            if name in target and not _label(target[name]):
                raise _target_error()
        for name in ("UDSetUHostInstance", "ShowPriceDetails"):
            if name in target and type(target[name]) is not bool:
                raise _target_error()
        disks = target["Disks"]
        if not isinstance(disks, list) or not 1 <= len(disks) <= 16:
            raise _target_error()
        boot_count = 0
        for disk in disks:
            if (not isinstance(disk, dict) or set(disk) - _DISK_FIELDS
                    or not {"IsBoot", "Size", "Type"} <= disk.keys()):
                raise _target_error()
            boot = disk["IsBoot"]
            if type(boot) is bool:
                boot = "True" if boot else "False"
            if boot not in ("True", "False"):
                raise _target_error()
            disk["IsBoot"] = boot
            boot_count += boot == "True"
            if (not _positive_integer(disk["Size"]) or not isinstance(disk["Type"], str)
                    or disk["Type"] not in _DISK_TYPES):
                raise _target_error()
            if ("BackupType" in disk and (not isinstance(disk["BackupType"], str)
                    or disk["BackupType"] not in {"NONE", "DATAARK", "SNAPSHOT"})):
                raise _target_error()
        if boot_count != 1:
            raise _target_error()
        target["ChargeType"] = "Dynamic"
        target["Count"] = 1
        target.setdefault("ShowPriceDetails", True)
        if settings.ucloud_project_id:
            target.setdefault("ProjectId", settings.ucloud_project_id)
        identity = json.dumps(target, sort_keys=True, separators=(",", ":"))
        if identity in seen:
            raise _target_error()
        seen.add(identity)
        validated.append(target)
    return validated


def _wire_value(value: str | int | bool) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def sign_parameters(parameters: dict[str, str | int | bool], private_key: str) -> str:
    """UAPI SHA1 signature; verified against the official documentation vector.

    Parameter strings are concatenated before URL encoding. Booleans use lower
    case. Floats are excluded from our request schema, avoiding ambiguous float
    formatting. The private key is only used in this local digest.
    """
    content = "".join(key + _wire_value(parameters[key]) for key in sorted(parameters)) + private_key
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def build_request(target: dict, public_key: str, private_key: str) -> bytes:
    parameters = {key: value for key, value in target.items() if key != "Disks"}
    for index, disk in enumerate(target["Disks"]):
        for field, value in disk.items():
            parameters[f"Disks.{index}.{field}"] = value
    parameters.update(Action=_ACTION, PublicKey=public_key)
    parameters["Signature"] = sign_parameters(parameters, private_key)
    return urlencode({key: _wire_value(value) for key, value in parameters.items()}).encode("ascii")


def _amount(value: object) -> Decimal:
    if type(value) not in (str, int, float, Decimal) or len(str(value)) > 64:
        raise ValueError("UCloud price is not a supported decimal amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("UCloud price is not a supported decimal amount") from None
    if (not amount.is_finite() or amount < 0 or amount >= Decimal("1e15")
            or amount.as_tuple().exponent < -12):
        raise ValueError("UCloud price is outside the supported range")
    return amount


def _price_detail(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("UCloud price details have an unexpected structure")
    # Ignore unrecognized fields rather than expose raw provider response data.
    return {name: format(_amount(value[name]), "f")
            for name in ("UHost", "UDisk", "Snapshot", "Volume") if name in value}


def parse_quote(payload: dict, target: dict, *, observed_at: str) -> dict:
    """Return one normalized quote, rejecting API errors and ambiguous periods."""
    if not isinstance(payload, dict) or type(payload.get("RetCode")) is not int:
        raise ValueError("UCloud response is missing a numeric result code")
    if payload["RetCode"] != 0:
        raise FetchError("provider_api_error", "UCloud rejected the configured price request; verify API permissions and target configuration.")
    if payload.get("Action") != _ACTION + "Response":
        raise ValueError("UCloud response action does not match the quote request")
    prices = payload.get("PriceSet")
    if (not isinstance(prices, list) or len(prices) != 1
            or not isinstance(prices[0], dict) or prices[0].get("ChargeType") != "Dynamic"):
        raise ValueError("UCloud did not return one hourly price")
    raw = prices[0]
    instance_amount = _amount(raw.get("Price"))
    with localcontext() as context:
        context.prec = 50
        allocated = (instance_amount / Decimal(target["GPU"])).quantize(
            Decimal("0.000000000001"), rounding=ROUND_HALF_UP,
        )
    amount = format(allocated, "f").rstrip("0").rstrip(".") or "0"
    instance_price = {"amount": format(instance_amount, "f"), "currency": "CNY", "unit": "instance_hour"}
    if "OriginalPrice" in raw:
        instance_price["original_amount"] = format(_amount(raw["OriginalPrice"]), "f")
    for name, output in (("PriceDetail", "details"), ("OriginalPriceDetail", "original_details")):
        if name in raw:
            instance_price[output] = _price_detail(raw[name])
    requested_configuration = {name: deepcopy(value) for name, value in target.items() if name != "ProjectId"}
    return {
        "provider": "ucloud", "product_type": "gpu_instance",
        "gpu_model": target["GpuType"].upper(), "gpu_variant": None,
        "raw_name": f"UHost {target['MachineType']} {target['GpuType']}",
        "raw_sku": None, "vram_gb": None, "gpu_count": target["GPU"],
        "amount": amount, "currency": "CNY", "unit": "gpu_hour",
        "billing_mode": "on_demand", "price_basis": "instance_total_allocated",
        "quote_status": "quoted", "regions": [target["Region"]], "zones": [target["Zone"]],
        "geographic_scope": "requested_zone", "account_scope": "account_quote",
        "tax_scope": "unspecified", "observed_at": observed_at,
        "effective_from": None, "effective_until": None,
        "source_url": DOCUMENTATION_URL, "source_type": "official_quote_api",
        "availability": "unknown", "instance_price": instance_price,
        "normalization": {
            "formula": "instance_price.amount / gpu_count",
            "decimal_places": 12, "rounding": "ROUND_HALF_UP",
        },
        "resources": {"vcpu_count": target["CPU"], "memory_mb": target["Memory"], "disks": deepcopy(target["Disks"])},
        "requested_configuration": requested_configuration,
        "notes": [
            "Account-specific CNY hourly quote for one explicitly configured UHost instance; this is not a complete UCloud price catalog.",
            "The per-GPU rate allocates the entire requested instance price, including CPU, RAM and disks, across its GPU count.",
            "Region and zone are request conditions; the quote response does not independently echo or verify them.",
            "The caller must verify the configuration against the console or DescribeAvailableInstanceTypes; inventory and orderability were not checked.",
            "Bandwidth, traffic and other services not included in this request may be billed separately.",
        ],
    }


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Fetch hourly quotes for the configured targets, failing closed on error."""
    if any(not isinstance(value, str) or not value.strip()
           for value in (settings.ucloud_public_key, settings.ucloud_private_key)):
        raise FetchError("missing_credentials", "Set UCLOUD_PUBLIC_KEY and UCLOUD_PRIVATE_KEY to collect UCloud configuration quotes.")
    targets = load_targets(settings)
    result = []
    for target_index, target in enumerate(targets):
        body = build_request(target, settings.ucloud_public_key, settings.ucloud_private_key)
        payload = request_json(
            SOURCE_URL, settings, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body, authenticated=True,
        )
        quote = parse_quote(payload, target, observed_at=observed_at)
        # Link filtered results to the caller's original target without
        # returning account/project identifiers in the price data.
        quote["target_index"] = target_index
        result.append(quote)
    return result
