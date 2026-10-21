"""Read the anonymous RunPod GPU Pods catalog, without provisioning resources.

The catalog's cloud-enable flags matter: a disabled cloud can still carry a
placeholder amount. These are per-GPU catalog rates, not complete-instance
quotes or a promise that any datacenter currently has stock.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from ..settings import Settings
from ..transport import FetchError, request_json

SOURCE_URL = "https://www.runpod.io/pricing"
SOURCE_TYPE = "official_public_api"
API_URL = "https://api.runpod.io/graphql"
DOCUMENTATION_URL = "https://graphql-spec.runpod.io/"
PRICE_BASIS_URL = "https://www.runpod.io/articles/comparison/runpod-vs-replicate"

# Only GPU Pods on-demand prices. No mutations, account queries, serverless,
# spot, reserved plans, or datacenter inventory fields are requested.
GPU_TYPES_QUERY = """query PublicGpuPodPrices {
  gpuTypes {
    id displayName memoryInGb
    secureCloud communityCloud securePrice communityPrice
  }
}"""
_TIERS = (("secure", "secureCloud", "securePrice"),
          ("community", "communityCloud", "communityPrice"))
_VARIANT = re.compile(r"\b(?:SXM\d*|PCIe|NVL)\b", re.IGNORECASE)
_PARTITION = re.compile(r"\b(?:MIG|vGPU)\b", re.IGNORECASE)
_MAX_GPU_TYPES = 1000


def _name(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or not value.isascii() or any(ord(char) < 32 for char in value)):
        raise ValueError("RunPod GPU catalog name is invalid")
    return " ".join(value.split())


def _gpu_fields(display_name: str, raw_sku: str) -> tuple[str, str | None]:
    name = re.sub(r"^(?:NVIDIA|AMD|Tesla)\s+", "", display_name, flags=re.IGNORECASE)
    # Display names can repeat the separate memory field (A100 SXM 40GB).
    name = re.sub(r"\s+\d+\s*GB$", "", name, flags=re.IGNORECASE)
    variants = _VARIANT.findall(name)
    if len(variants) > 1:
        raise ValueError("RunPod GPU variant is ambiguous")
    model = " ".join(_VARIANT.sub("", name).split()).upper()
    if not model or not re.fullmatch(r"[A-Z0-9][A-Z0-9 .-]*", model):
        raise ValueError("RunPod GPU model is invalid")
    variant = variants[0] if variants else None
    # The V100 PCIe display name omits the variant retained in its catalog id.
    if variant is None:
        raw_variants = _VARIANT.findall(raw_sku)
        if len(raw_variants) == 1:
            variant = raw_variants[0]
    if variant and variant.casefold() == "pcie":
        variant = "PCIe"
    elif variant:
        variant = variant.upper()
    return model, variant


def _price(value: object) -> Decimal | None:
    # JSON floats are decoded as Decimal by the shared transport. Strings and
    # binary floats are deliberately rejected, rather than silently rounded.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("RunPod GPU catalog price is not an exact JSON number")
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError("RunPod GPU catalog price is invalid")
    if amount and (amount.adjusted() > 12 or amount.as_tuple().exponent < -50):
        raise ValueError("RunPod GPU catalog price magnitude or precision is invalid")
    return amount


def parse_catalog(payload: dict, *, observed_at: str) -> list[dict]:
    """Normalize enabled, priced full-GPU types from one complete response.

    Missing/zero rates are unquoted catalog entries, never free GPU offers.
    MIG/vGPU partitions are intentionally outside the full-GPU Pods scope.
    """
    if not isinstance(payload, dict):
        raise ValueError("RunPod GPU catalog response is invalid")
    if payload.get("errors"):
        raise FetchError("public_api_error", "RunPod rejected the public GPU catalog query.")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("gpuTypes"), list):
        raise ValueError("RunPod GPU catalog response structure changed")
    rows = data["gpuTypes"]
    if not rows or len(rows) > _MAX_GPU_TYPES:
        raise ValueError("RunPod GPU catalog size is invalid")
    quotes, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("RunPod GPU catalog row is invalid")
        raw_sku, raw_name = _name(row.get("id")), _name(row.get("displayName"))
        if raw_sku in seen:
            raise ValueError("RunPod GPU catalog contains duplicate identifiers")
        seen.add(raw_sku)
        if any(type(row.get(flag)) is not bool for _, flag, _ in _TIERS):
            raise ValueError("RunPod GPU cloud eligibility is invalid")
        # Unavailable/inactive sentinels can have memory=0 and placeholder prices.
        if not row["secureCloud"] and not row["communityCloud"]:
            continue
        if _PARTITION.search(raw_sku) or _PARTITION.search(raw_name):
            continue
        memory = row.get("memoryInGb")
        if type(memory) is not int or not 0 < memory <= 10000:
            raise ValueError("RunPod GPU catalog memory is invalid")
        model, variant = _gpu_fields(raw_name, raw_sku)
        for tier, flag, price_key in _TIERS:
            if not row[flag]:
                continue
            if price_key not in row:
                raise ValueError("RunPod GPU catalog price field is missing")
            amount = _price(row[price_key])
            if amount is None or amount == 0:
                continue
            quotes.append({
                "provider": "runpod",
                "product_type": "gpu_instance",
                "gpu_model": model,
                "raw_name": raw_name,
                "raw_sku": raw_sku,
                "gpu_variant": variant,
                "vram_gb": memory,
                "gpu_count": None,
                "amount": format(amount, "f"),
                "currency": "USD",
                "unit": "gpu_hour",
                "billing_mode": "on_demand",
                "price_basis": "advertised_per_gpu",
                "quote_status": "quoted",
                "cloud_tier": tier,
                "conditions": {"cloud_type": f"{tier}_cloud", "rate_type": "catalog"},
                "regions": [],
                "zones": [],
                "geographic_scope": "unspecified",
                "account_scope": "public_catalog",
                "tax_scope": "unspecified",
                "observed_at": observed_at,
                "effective_from": None,
                "effective_until": None,
                "source_url": SOURCE_URL,
                "source_type": SOURCE_TYPE,
                "api_source_url": API_URL,
                "price_basis_source_url": PRICE_BASIS_URL,
                "availability": "unknown",
                "notes": [
                    "Public GPU Pods on-demand catalog rate in USD per GPU-hour for the named cloud tier; storage is charged separately.",
                    "The catalog does not identify an instance GPU count, CPU/RAM allocation, datacenter or availability zone for this rate.",
                    "Cloud eligibility is not current stock; availability, orderability and account-specific checkout totals were not verified.",
                    "Only enabled cloud tiers with positive public rates are returned; unquoted entries, inactive entries and MIG/vGPU partitions are excluded.",
                ],
            })
    if not quotes:
        raise ValueError("RunPod GPU catalog contains no priced full-GPU types")
    return quotes


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Make one anonymous, read-only query; credentials are never consulted."""
    payload = request_json(
        API_URL, settings, method="POST", authenticated=False,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"query": GPU_TYPES_QUERY}, separators=(",", ":")).encode("utf-8"),
    )
    return parse_catalog(payload, observed_at=observed_at)
