"""Opt-in member tariff selection; collection results remain the audit record."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Context, Decimal, InvalidOperation, MAX_EMAX, MIN_EMIN, ROUND_HALF_UP, localcontext
import json
import re

_AUTODL_MARKET_API = "https://www.autodl.com/api/v1/user/machine/list"
_MEMBER_CONDITION = "Requires AutoDL member eligibility."
_MONEY = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
# Every other field, including unknown future configuration/eligibility fields,
# remains in the identity. Different snapshots, locations and clouds cannot pair.
_TARIFF_FIELDS = {
    "amount", "exact_api_hourly_amount", "pricing_tier", "membership_required",
    "membership_discount_badge", "conditions", "price_source",
}


def _money(value: object) -> Decimal | None:
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def _identity(quote: object) -> str | None:
    if (not isinstance(quote, dict) or quote.get("provider") != "autodl"
            or quote.get("source_url") != _AUTODL_MARKET_API
            or quote.get("source_type") != "official_internal_api"
            or quote.get("product_type") != "gpu_container"
            or quote.get("unit") != "gpu_hour" or quote.get("billing_mode") != "on_demand"
            or quote.get("price_basis") != "advertised_per_gpu"
            or quote.get("quote_status") != "quoted" or quote.get("currency") != "CNY"
            or not isinstance(quote.get("raw_sku"), str) or not quote["raw_sku"].strip()
            or not isinstance(quote.get("gpu_model"), str) or not quote["gpu_model"].strip()
            or any(field not in quote for field in ("gpu_variant", "vram_gb", "gpu_count"))
            or type(quote["vram_gb"]) is not int or quote["vram_gb"] <= 0
            or not isinstance(quote.get("regions"), list) or len(quote["regions"]) != 1
            or not isinstance(quote["regions"][0], str) or not quote["regions"][0]
            or not isinstance(quote.get("zones"), list)
            or not isinstance(quote.get("location"), dict)
            or quote["location"].get("region") != quote["regions"][0]
            or not isinstance(quote.get("resources"), dict) or not quote["resources"]):
        return None
    try:
        observed = datetime.fromisoformat(quote["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        return None
    # Only the adapter's exact membership condition is a known tier difference.
    # Unrecognized eligibility conditions stay in the comparison, not discarded.
    conditions = quote.get("conditions")
    if conditions not in ([], [_MEMBER_CONDITION]):
        return None
    identity = {key: value for key, value in quote.items() if key not in _TARIFF_FIELDS}
    price_source = quote.get("price_source")
    if price_source is not None:
        if not isinstance(price_source, dict):
            return None
        identity["price_source"] = {key: value for key, value in price_source.items()
                                    if key not in {"field", "native_amount_milli_cny"}}
    try:
        return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None


def _tariff(quote: dict, *, member: bool) -> tuple[Decimal, Decimal] | None:
    tier = "member" if member else "ordinary"
    if (quote.get("pricing_tier") != tier or quote.get("membership_required") is not member
            or quote.get("conditions") != ([_MEMBER_CONDITION] if member else [])
            or (not member and "membership_discount_badge" in quote)):
        return None
    amount = _money(quote.get("amount"))
    if amount is None:
        return None
    exact = _money(quote.get("exact_api_hourly_amount", quote["amount"]))
    if exact is None:
        return None
    price_source = quote.get("price_source")
    if price_source is not None:
        level = "member_user" if member else "normal_user"
        native = price_source.get("native_amount_milli_cny")
        if (price_source.get("field") != f"machine_sku_info[0].level_config[{level}].discounted_price"
                or price_source.get("native_currency") != "CNY"
                or type(native) is not int or native < 0):
            return None
    else:
        native = None
    # A caller may use a low precision or trap Rounded/Inexact in its own
    # context. Neither can alter tariff identity or the official half-up rule.
    native_decimal = Decimal(native) if native is not None else None
    precision = max(28, len(amount.as_tuple().digits) + 4, len(exact.as_tuple().digits) + 4,
                    len(native_decimal.as_tuple().digits) + 4 if native_decimal is not None else 0)
    context = Context(prec=precision, rounding=ROUND_HALF_UP, Emin=MIN_EMIN, Emax=MAX_EMAX,
                      traps=[InvalidOperation])
    try:
        with localcontext(context):
            if native_decimal is not None:
                native_exact = native_decimal / 1000
                if "exact_api_hourly_amount" in quote and native_exact != exact:
                    return None
                exact = native_exact
            if exact.quantize(Decimal("0.01")) != amount:
                return None
    except InvalidOperation:
        return None
    return amount, exact


def prefer_member_quotes(quotes: list[dict]) -> list[dict]:
    """Copy quotes, omitting ordinary rows only for verified AutoDL tariff pairs.

    A pair must contain exactly one ordinary and one explicitly member-required
    quote for the same machine, complete configuration and observed timestamp.
    Both displayed and exact prices must be finite, nonnegative, and the member
    price must not exceed the ordinary price. The member row keeps its original
    eligibility label; this function does not assert that the caller is a member.
    Unsupported sources, ambiguous pairs and unknown conditions remain intact.
    RunPod Secure/Community are cloud types and never treated as membership.
    Input order is retained and neither the input list nor its records is changed.
    """
    if not isinstance(quotes, list):
        raise ValueError("quotes must be a list")
    groups: dict[str, list[int]] = defaultdict(list)
    for index, quote in enumerate(quotes):
        identity = _identity(quote)
        if identity is not None:
            groups[identity].append(index)
    omitted = set()
    for indices in groups.values():
        if len(indices) != 2:
            continue
        ordinary = [index for index in indices if quotes[index].get("membership_required") is False]
        member = [index for index in indices if quotes[index].get("membership_required") is True]
        if len(ordinary) != 1 or len(member) != 1:
            continue
        ordinary_price = _tariff(quotes[ordinary[0]], member=False)
        member_price = _tariff(quotes[member[0]], member=True)
        if (ordinary_price is not None and member_price is not None
                and all(member_value <= ordinary_value
                        for member_value, ordinary_value in zip(member_price, ordinary_price))):
            omitted.add(ordinary[0])
    return deepcopy([quote for index, quote in enumerate(quotes) if index not in omitted])
