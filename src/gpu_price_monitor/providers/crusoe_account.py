"""Read existing Crusoe reservation contracts using the documented HMAC auth.

The Reservation schema supplies ``price`` and a generic ``product_line``, but
does not supply a structured currency, hourly unit, or GPU-product type. Such
records are account audit evidence, never fabricated GPU-hour quotes.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import re

from ..settings import ConfigurationError, Settings
from ..transport import FetchError, request_json

API_BASE_URL = "https://api.cloud.crusoe.ai"
API_ENDPOINT_TEMPLATE = API_BASE_URL + "/v1/organizations/{organization_id}/reservations"
SOURCE_URL = "https://docs.crusoecloud.com/usage-billing/reservations/overview/"
SOURCE_TYPE = "official_api"
AUTH_DOCUMENTATION_URL = "https://docs.crusoecloud.com/reference/api/"
SCHEMA_URL = "https://api.crusoecloud.com/v1/openapi.json"
LOGIN_URL = "https://console.crusoecloud.com/"
MAX_CONTRACTS = 5000
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_PRICE = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,20})?")


def _invalid() -> ValueError:
    return ValueError("The Crusoe reservation contract structure was not recognized.")


def _secret_bytes(secret: object) -> bytes:
    if (not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}={0,2}", secret)
            or len(secret) % 4 == 1):
        raise ConfigurationError("CRUSOE_SECRET_KEY must be the API secret in URL-safe Base64 format.")
    try:
        decoded = base64.b64decode(secret + "=" * (-len(secret) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise ConfigurationError("CRUSOE_SECRET_KEY must be the API secret in URL-safe Base64 format.") from None
    if not decoded:
        raise ConfigurationError("CRUSOE_SECRET_KEY must not be empty.")
    return decoded


def _credentials(settings: Settings) -> tuple[str, str, str]:
    access = getattr(settings, "crusoe_access_key_id", None)
    secret = getattr(settings, "crusoe_secret_key", None)
    organization = getattr(settings, "crusoe_organization_id", None)
    if not all(isinstance(value, str) and value for value in (access, secret, organization)):
        raise ConfigurationError("Crusoe contract audit requires CRUSOE_ACCESS_KEY_ID, CRUSOE_SECRET_KEY and CRUSOE_ORGANIZATION_ID.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", access):
        raise ConfigurationError("CRUSOE_ACCESS_KEY_ID has an invalid API access-key format.")
    _secret_bytes(secret)
    if not _UUID.fullmatch(organization):
        raise ConfigurationError("CRUSOE_ORGANIZATION_ID must be an organization UUID.")
    return access, secret, organization


def _instant(value: object, *, empty_allowed: bool = False) -> str | None:
    if empty_allowed and value == "":
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 40 or "T" not in value:
        raise _invalid()
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (ValueError, OverflowError):
        raise _invalid() from None
    return value


def _request_time() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def signed_get_headers(path: str, *, access_key_id: str, secret_key: str, timestamp: str) -> dict[str, str]:
    """Sign one reservation-list GET with no query; no mutation signer is exposed.

    Matches the official Python algorithm: raw URL-safe Base64 secret decode,
    HMAC-SHA256 of path/query/verb/timestamp plus final newline, and unpadded
    URL-safe Base64 signature. The empty query is a blank payload line.
    """
    path_match = re.fullmatch(r"/v1/organizations/([^/]+)/reservations", path) if isinstance(path, str) else None
    if path_match is None or not _UUID.fullmatch(path_match[1]):
        raise ConfigurationError("Crusoe account collection only signs the reservation-list GET path.")
    if not isinstance(access_key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", access_key_id):
        raise ConfigurationError("CRUSOE_ACCESS_KEY_ID has an invalid API access-key format.")
    _instant(timestamp)
    payload = f"{path}\n\nGET\n{timestamp}\n".encode("ascii")
    signature = base64.urlsafe_b64encode(hmac.new(_secret_bytes(secret_key), payload, hashlib.sha256).digest()).decode("ascii").rstrip("=")
    return {"X-Crusoe-Timestamp": timestamp,
            "Authorization": f"Bearer 1.0:{access_key_id}:{signature}"}


def _text(value: object, maximum: int = 256) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 for char in value)):
        raise _invalid()
    return value


def _count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000_000_000:
        raise _invalid()
    return value


def parse_contracts(payload: dict, *, observed_at: str) -> list[dict]:
    """Return only an explicit whitelist, excluding organization/project/VM IDs."""
    _instant(observed_at)
    if (not isinstance(payload, dict) or set(payload) != {"items"}
            or not isinstance(payload["items"], list) or len(payload["items"]) > MAX_CONTRACTS):
        raise _invalid()
    records, seen = [], set()
    for row in payload["items"]:
        if not isinstance(row, dict):
            raise _invalid()
        identity = row.get("id")
        if not isinstance(identity, str) or not _UUID.fullmatch(identity) or identity.lower() in seen:
            raise _invalid()
        seen.add(identity.lower())
        price = row.get("price")
        if not isinstance(price, str) or not _PRICE.fullmatch(price) or not Decimal(price).is_finite():
            raise _invalid()
        locations = row.get("locations")
        if (not isinstance(locations, list) or len(locations) > 100
                or any(not isinstance(location, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,127}", location) for location in locations)
                or len(set(locations)) != len(locations)):
            raise _invalid()
        duration = row.get("duration")
        if type(duration) not in (int, Decimal) or not Decimal(duration).is_finite() or Decimal(duration) < 0:
            raise _invalid()
        records.append({
            "provider": "crusoe", "record_type": "reservation_contract",
            "account_scope": "account_contract_audit",
            "contract_reference_sha256": hashlib.sha256(identity.lower().encode("ascii")).hexdigest(),
            "reservation_type": _text(row.get("reservation_type"), 64),
            "product_line": _text(row.get("product_line")),
            "price_as_returned": price, "currency": None, "unit": None, "gpu_model": None,
            "quantity_as_returned": _count(row.get("quantity")),
            "used_quantity_as_returned": _count(row.get("used_quantity")),
            "duration_as_returned": format(Decimal(duration), "f"), "duration_unit": None,
            "contract_location_constraints": list(locations),
            "contract_start_date": _instant(row.get("contract_start_date"), empty_allowed=True),
            "contract_end_date": _instant(row.get("contract_end_date"), empty_allowed=True),
            "delivery_deadline": _instant(row.get("delivery_deadline"), empty_allowed=True),
            "date_delivered": _instant(row.get("date_delivered"), empty_allowed=True),
            "currency_verified": False, "hourly_unit_verified": False, "gpu_product_verified": False,
            "price_admissible_as_gpu_hour_quote": False,
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE,
            "api_endpoint_template": API_ENDPOINT_TEMPLATE, "observed_at": observed_at,
            "notes": [
                "Existing organization reservation contract, not a public rental-price catalog.",
                "The API Reservation schema lacks structured currency, hourly-unit and GPU-product evidence; no GPU-hour quote is inferred.",
                "Quantity is contract capacity, not the number of GPUs in one VM; duration unit is not declared in this response.",
                "Location constraints belong to the contract; they do not independently establish regional public prices or stock.",
                "Private resource identifiers and unrelated account fields are excluded from this audit projection.",
            ],
        })
    return records


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """GET existing contracts only; credentials and actual private URL stay local."""
    access, secret, organization = _credentials(settings)
    path = f"/v1/organizations/{organization}/reservations"
    headers = signed_get_headers(path, access_key_id=access, secret_key=secret, timestamp=_request_time())
    payload = request_json(API_BASE_URL + path, settings, method="GET", headers=headers, authenticated=True)
    try:
        records = parse_contracts(payload, observed_at=observed_at)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        raise FetchError("parse_failed", "The Crusoe account reservation response could not be verified.") from None
    return {"status": "ok", "prices": [], "contract_records": records,
            "audit_only": True, "contract_record_count": len(records),
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE,
            "api_endpoint_template": API_ENDPOINT_TEMPLATE,
            "pricing_limitations": ["Reservation price currency, hourly unit and GPU-product classification are not established by the API schema."],
            "authentication_method": "crusoe_hmac_sha256_v1_0", "uses_llm": False}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Compatibility wrapper: audit-only records never become price quotes."""
    return collect_result(settings=settings, observed_at=observed_at)["prices"]
