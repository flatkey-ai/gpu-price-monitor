"""Read AutoDL's market with an explicitly supplied, existing browser session.

The anonymous market currently redirects to login. This opt-in adapter neither
logs in nor buys resources. Only the market list, pricing-support requests and
frontend account bootstrap reads are allowed. Account responses remain in the
frontend's memory; only market price/configuration metadata is projected.
Existing instance, machine-detail, wallet and order APIs are blocked.
Public template evidence: the official market component and GPU allocation docs.
Authenticated success still requires validation with the caller's own session.
"""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from decimal import Decimal
import json
from math import ceil
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from ..settings import Settings
from ..transport import FetchError, MAX_RESPONSE_BYTES
from .autodl import _gpu_fields
from . import autodl_regions

SOURCE_URL = "https://www.autodl.com/market/list"
SOURCE_TYPE = "authorized_browser"
ALLOCATION_SOURCE_URL = "https://www.autodl.com/docs/gpu/"
MARKET_PATH = "/api/v1/user/machine/list"
REGIONS_PATH = "/api/v1/region/list"
PAGE_SIZE = 90
MAX_PAGES = 100
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_READS = {
    ("POST", MARKET_PATH), ("GET", "/api/v1/time_sync"),
    ("GET", "/api/v1/common"), ("GET", "/api/v1/region/list"),
    ("GET", "/api/v1/machine/gpu_type"), ("POST", "/api/v1/machine/region/gpu_type"),
    ("GET", "/api/v1/machine/tag"), ("GET", "/api/v1/user/level"),
    ("GET", "/api/v1/user/member/detail"), ("GET", "/api/v1/user/detail"),
}


def _invalid() -> ValueError:
    return ValueError("AutoDL market pricing, location, configuration or pagination changed.")


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _one(parent, selector):
    elements = parent.select(selector)
    if len(elements) != 1:
        raise _invalid()
    return elements[0]


def _number(value: str) -> str:
    if not re.fullmatch(r"\d+(?:\.\d+)?", value) or len(value) > 24 or Decimal(value) <= 0:
        raise _invalid()
    return format(Decimal(value), "f")


def market_query(page: int, *, page_size: int = PAGE_SIZE) -> dict:
    if type(page) is not int or not 1 <= page <= MAX_PAGES:
        raise _invalid()
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise _invalid()
    return {"charge_type": "payg", "region_sign_list": [], "gpu_type_name": [],
            "machine_tag_name": [], "gpu_idle_num": 0, "mount_net_disk": False,
            "cpu_arch": [], "chip_corp": [], "instance_disk_size_order": "",
            "date_range": "", "date_from": "", "date_to": "", "page_index": page,
            "page_size": page_size, "pay_price_order": "", "gpu_idle_type": "", "default_order": True}


def project_market_response(payload: dict, request: dict) -> dict:
    """Immediately discard all fields except market pagination and GPU locations.

    The source's machine list is market inventory, not a caller's instance list.
    Raw bodies, session headers, user details and SSH fields are never returned.
    """
    if not isinstance(payload, dict) or not isinstance(request, dict):
        raise _invalid()
    if payload.get("code") == "AuthorizeFailed":
        raise FetchError("login_required", "AutoDL market requires a valid, caller-supplied browser session.")
    if payload.get("code") != "Success":
        raise FetchError("market_request_failed", "AutoDL did not accept the read-only market listing request.")
    if request.get("charge_type") != "payg":
        raise _invalid()
    # A full-market run must not inherit a hidden browser filter.
    if any(request.get(key) for key in ("region_sign", "region_sign_list", "gpu_type_name", "machine_tag_name", "cpu_arch", "chip_corp", "gpu_idle_num", "mount_net_disk", "date_from", "date_to", "gpu_idle_type", "pay_price_order")):
        raise _invalid()
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise _invalid()
    page, size, total = (data.get(key) for key in ("page_index", "page_size", "result_total"))
    if (any(type(value) is not int for value in (page, size, total)) or not 1 <= page <= MAX_PAGES
            or not 1 <= size <= 5000 or size != request.get("page_size") or not 0 <= total <= size * MAX_PAGES
            or request.get("page_index") != page or request.get("page_size") != size
            or len(data["list"]) != min(size, max(0, total - (page - 1) * size))):
        raise _invalid()
    rows, seen = [], set()
    for item in data["list"]:
        if not isinstance(item, dict):
            raise _invalid()
        row = {key: item.get(key) for key in ("machine_id", "region_sign", "region_name", "gpu_name", "gpu_memory", "chip_corp")}
        if (any(not isinstance(row[key], str) or not _CODE.fullmatch(row[key]) for key in ("machine_id", "region_sign"))
                or any(not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 200
                       or any(ord(c) < 32 for c in row[key]) for key in ("region_name", "gpu_name", "chip_corp"))
                or type(row["gpu_memory"]) is not int or row["gpu_memory"] < 0 or row["gpu_memory"] > 10000 * 2**30
                or row["machine_id"] in seen):
            raise _invalid()
        seen.add(row["machine_id"])
        rows.append(row)
    return {"page_index": page, "page_size": size, "result_total": total, "rows": rows}


def project_region_response(payload: dict) -> dict:
    """Keep only public code/name/DC fields, never a raw response or headers.

    Country validation happens with the collection timestamp after complete
    price pagination. Invalid/missing country metadata cannot discard prices.
    """
    if (not isinstance(payload, dict) or payload.get("code") != "Success"
            or not isinstance(payload.get("data"), list) or not 1 <= len(payload["data"]) <= 1000
            or any(not isinstance(row, dict) for row in payload["data"])):
        raise ValueError("AutoDL's public region directory was not recognized.")
    return {"code": "Success", "data": [
        {field: row.get(field) for field in ("region_sign", "region_name", "data_center")}
        for row in payload["data"]]}


def _read_market_response(response, *, request_page: int | None, expected_page: int) -> dict | None:
    # Reloading Vue can cancel an earlier page's duplicate list request after
    # its headers arrived. Ignore that request BEFORE asking for its lost body.
    # The current page must still pass every identity/pagination check.
    if request_page != expected_page:
        return None
    if response.status != 200:
        raise FetchError("login_required" if response.status in {401, 403} else "http_error",
                         "AutoDL did not return the requested market page response.", response.status >= 500)
    body = response.body()
    if len(body) > MAX_RESPONSE_BYTES:
        raise FetchError("response_too_large", "AutoDL's market response exceeds the size limit.")
    return project_market_response(json.loads(body), market_query(expected_page))


def parse_market_page(content: str, *, metadata: dict, observed_at: str) -> list[dict]:
    """Read visible card prices; API metadata only verifies identity and location."""
    soup = BeautifulSoup(content, "html.parser")
    cards = soup.select(".gpu-market .list-content > .list-item")
    if not cards:
        # The official Vue list component can add a root wrapper.
        cards = soup.select(".gpu-market .list-content .list-item")
    rows = metadata.get("rows")
    if not isinstance(rows, list) or len(cards) != len(rows):
        raise _invalid()
    by_id = {row["machine_id"]: row for row in rows}
    quotes, seen = [], set()
    for card in cards:
        identity = _text(_one(card, ".machine-id"))
        if identity not in by_id or identity in seen:
            raise _invalid()
        seen.add(identity)
        source = by_id[identity]
        # Market filters also expose CPUs and non-GPU accelerators.
        if source["chip_corp"] in {"huawei", "cambricon", "cpu"}:
            continue
        if source["chip_corp"] not in {"nvidia", "amd", "mthreads"}:
            raise _invalid()
        raw_name = _text(_one(card, ".gpu-name .name"))
        model, memory = _gpu_fields(raw_name)
        if (source["gpu_memory"] != memory * 2**30
                or raw_name != f'{source["gpu_name"]} / {memory} GB'):
            # Whitespace around the source's NBSP/GB varies; compare normalized form.
            if (source["gpu_memory"] != memory * 2**30
                    or re.sub(r"\s+", "", raw_name) != re.sub(r"\s+", "", f'{source["gpu_name"]}/{memory}GB')):
                raise _invalid()
        money = _one(card, ".price .money")
        if _text(_one(money, ".rmb")) != "￥" or _text(_one(money, ".unit")) != "/时":
            raise _invalid()
        amount = _number(_text(_one(money, ":scope > .num")))
        member = money.select(".member_level")
        original = money.select(".origin-price")
        if len(member) > 1 or len(original) > 1 or bool(member) != bool(original):
            raise _invalid()
        conditions = []
        member_condition = None
        ordinary_amount = None
        if member:
            if not re.fullmatch(r"\d+(?:\.\d+)?折", _text(member[0])):
                raise _invalid()
            match = re.fullmatch(r"￥\s*(\d+(?:\.\d+)?)\s*/时", _text(original[0]))
            if not match:
                raise _invalid()
            ordinary_amount = _number(match[1])
            if Decimal(amount) > Decimal(ordinary_amount):
                raise _invalid()
            member_condition = "The displayed account tier applies a member discount: " + _text(member[0])
        expected_money = "￥" + amount + "/时"
        if member:
            expected_money += _text(original[0]) + _text(member[0])
        if re.sub(r"\s+", "", _text(money)) != re.sub(r"\s+", "", expected_money):
            raise _invalid()
        allocations = [c for c in card.select(".config-card") if c.select(":scope > .label") and _text(c.select(":scope > .label")[0]) == "每GPU分配"]
        if len(allocations) != 1:
            raise _invalid()
        allocation = _text(allocations[0])
        cpu = re.search(r"CPU:\s*(\d+(?:\.\d+)?)\s*核", allocation)
        ram = re.search(r"内存:\s*(\d+(?:\.\d+)?)\s*GB", allocation)
        if not cpu or not ram:
            raise _invalid()
        rent = _text(_one(card, ".price .rent button"))
        available = re.fullmatch(r"([1-9]\d*)卡可租", rent)
        if rent != "已租完" and not available:
            raise _invalid()
        conditions += [_text(tag) for tag in card.select(".more .text") if _text(tag)]
        quote = {
            "provider": "autodl", "product_type": "gpu_container", "gpu_model": model,
            "gpu_variant": None, "vram_gb": memory, "gpu_count": None,
            "raw_name": raw_name, "raw_sku": identity,
            "amount": amount, "currency": "CNY", "unit": "gpu_hour", "billing_mode": "on_demand",
            "price_basis": "advertised_per_gpu", "quote_status": "quoted",
            "pricing_tier": "member" if member else "authenticated_market",
            "membership_required": bool(member), "ordinary_price_amount": ordinary_amount,
            "regions": [source["region_sign"]], "zones": [], "geographic_scope": "regions",
            "location": {"region": source["region_sign"], "region_name": source["region_name"]},
            "resources": {"allocation_scope": "per_gpu", "cpu_cores_per_gpu": _number(cpu[1]),
                          "memory_per_gpu": {"amount": _number(ram[1]), "unit": "GB"},
                          "configuration_text": [_text(c) for c in card.select(".config-card")]},
            "availability": "available" if available else "unavailable",
            "available_gpu_count": int(available[1]) if available else 0,
            "account_scope": "authenticated_catalog", "tax_scope": "unspecified",
            "conditions": conditions + ([member_condition] if member_condition else []),
            "price_source": {"selector": ".price .money > .num", "value_text": _text(_one(money, ":scope > .num"))},
            "observed_at": observed_at, "effective_from": None, "effective_until": None,
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "allocation_source_url": ALLOCATION_SOURCE_URL,
            "notes": [
                "Caller-authorized market listing; displayed account/member prices may differ from the anonymous homepage catalog.",
                "The market explicitly lists CPU and RAM per GPU. No instance GPU count or complete-node total was invented.",
                "Region code and name come from this exact market listing; no deployment country or availability zone was inferred.",
                "Availability is the observed rent-button state, not a booking or future capacity guarantee.",
                "Only the default hourly pay-as-you-go market is collected; monthly, yearly, trial, existing-instance and SSH data are excluded.",
            ],
        }
        if member:
            quote["membership_discount_badge"] = _text(member[0])
            ordinary_quote = deepcopy(quote)
            ordinary_quote.update(
                amount=ordinary_amount, pricing_tier="ordinary", membership_required=False,
                ordinary_price_amount=None, conditions=list(conditions),
                price_source={"selector": ".price .money .origin-price", "value_text": _text(original[0])},
            )
            ordinary_quote.pop("membership_discount_badge")
            ordinary_quote["notes"].append(
                "Ordinary hourly amount is read directly from this card's visible original price, not calculated from the member discount."
            )
            quotes.append(ordinary_quote)
        quotes.append(quote)
    return quotes


def request_is_allowed(url: str, method: str, resource_type: str) -> bool:
    """Keep saved credentials on the official origin and only permit known reads."""
    try:
        parsed = urlsplit(url)
        valid_origin = parsed.scheme == "https" and parsed.hostname in {"www.autodl.com", "autodl.com"} and parsed.port in (None, 443)
    except ValueError:
        return False
    if not valid_origin:
        return False
    if parsed.username or parsed.password or resource_type in {"image", "font", "media"}:
        return False
    if parsed.path.startswith("/api/"):
        return (method, parsed.path) in _READS
    return method == "GET" and (parsed.path in {"/market/list", "/login", "/version.json"} or parsed.path.startswith("/assets/"))


def _render_market_pages(settings: Settings) -> list[dict]:
    state = settings.autodl_storage_state_path
    if not state:
        raise FetchError("login_required", "AutoDL market requires an explicitly supplied browser storage-state file.")
    try:
        valid_state = isinstance(state, str) and Path(state).is_file()
    except (OSError, ValueError):
        valid_state = False
    if not valid_state:
        raise FetchError("storage_state_invalid", "The configured AutoDL browser session file is unavailable.")
    try:
        from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout, sync_playwright
    except ImportError:
        raise FetchError("browser_dependency_missing", "AutoDL market needs the optional local Playwright browser dependency.") from None
    deadline = time.monotonic() + settings.timeout_seconds

    def remaining_ms():
        value = deadline - time.monotonic()
        if value <= 0:
            raise FetchError("timeout", "AutoDL market collection timed out.", True)
        return max(1, int(value * 1000))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=remaining_ms())
            try:
                try:
                    context = browser.new_context(storage_state=state, service_workers="block", accept_downloads=False)
                except (BrowserError, OSError, ValueError):
                    raise FetchError("storage_state_invalid", "The configured AutoDL browser session could not be loaded.") from None
                requested_index = 1
                request_pages = {}

                def route_request(route):
                    request = route.request
                    if not request_is_allowed(request.url, request.method, request.resource_type):
                        route.abort()
                    elif urlsplit(request.url).path == MARKET_PATH:
                        # Normalize only this read-only list query. Vue's initial
                        # filter mount can reset URL pagination; no hidden saved
                        # filter or smaller page may truncate the collection.
                        request_pages[request] = requested_index
                        route.continue_(post_data=json.dumps(market_query(requested_index)))
                    else:
                        route.continue_()

                context.route("**/*", route_request)
                context.route_web_socket("**/*", lambda websocket: websocket.close())
                page, captured, errors = context.new_page(), [], []
                directory_state = {"payload": None, "error": None}

                def response_received(response):
                    parsed = urlsplit(response.url)
                    if parsed.hostname not in {"www.autodl.com", "autodl.com"}:
                        return
                    if parsed.path == REGIONS_PATH:
                        try:
                            body = response.body()
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise FetchError("response_too_large", "AutoDL's public region directory exceeds the size limit.")
                            directory_state["payload"] = project_region_response(json.loads(body))
                            directory_state["error"] = None
                        except (FetchError, ValueError, TypeError, KeyError, BrowserError):
                            directory_state["error"] = {"source": "region_country_directory", "code": "region_directory_unavailable",
                                                        "message": "AutoDL's current public region directory could not be verified; prices remain available without a guessed country.",
                                                        "retryable": False}
                        return
                    if parsed.path != MARKET_PATH:
                        return
                    try:
                        projected = _read_market_response(response, request_page=request_pages.pop(response.request, None),
                                                          expected_page=requested_index)
                        if projected is not None:
                            captured.append(projected)
                    except FetchError as exc:
                        errors.append(exc)
                    except BrowserError:
                        errors.append(FetchError("market_response_unavailable", "AutoDL's current market response could not be read completely.", True))
                    except (ValueError, TypeError, KeyError):
                        errors.append(FetchError("parse_failed", "AutoDL's market response was not recognized."))

                page.on("response", response_received)
                # The frontend may bootstrap only /common. Obtain the exact
                # public directory endpoint rather than misattribute /common
                # data to /region/list. This isolated page only performs the
                # already-allowlisted same-origin GET, with no account reads.
                directory_page = context.new_page()
                directory_page.on("response", response_received)
                try:
                    directory_page.goto(autodl_regions.REGIONS_URL, wait_until="domcontentloaded",
                                        timeout=min(5000, remaining_ms()))
                except (BrowserTimeout, BrowserError):
                    if directory_state["payload"] is None:
                        directory_state["error"] = {"source": "region_country_directory", "code": "region_directory_unavailable",
                                                    "message": "AutoDL's public region directory could not be read; no country fallback was used.",
                                                    "retryable": True}
                finally:
                    with suppress(BrowserError):
                        directory_page.close()
                pages, expected_total = [], None
                for index in range(1, MAX_PAGES + 1):
                    requested_index = index
                    captured.clear()
                    page.goto(SOURCE_URL + "?" + urlencode({"page_index": index, "page_size": PAGE_SIZE}), wait_until="domcontentloaded", timeout=remaining_ms())
                    while True:
                        if errors:
                            raise errors[0]
                        if urlsplit(page.url).path.startswith("/login"):
                            raise FetchError("login_required", "AutoDL's saved browser session is missing or expired.")
                        location = urlsplit(page.url)
                        if location.hostname not in {"www.autodl.com", "autodl.com"} or location.path != "/market/list":
                            raise FetchError("unexpected_page", "AutoDL did not return the authorized market page.")
                        matching = [entry for entry in captured if entry["page_index"] == index]
                        if matching and page.locator(".gpu-market .list-content .list-item").count() == len(matching[-1]["rows"]):
                            meta = matching[-1]
                            break
                        page.wait_for_timeout(min(100, remaining_ms()))
                    if expected_total is None:
                        expected_total = meta["result_total"]
                        if expected_total == 0:
                            raise FetchError("empty_marketplace", "AutoDL returned no market listings.")
                    if meta["result_total"] != expected_total:
                        raise FetchError("market_changed", "AutoDL's market changed during pagination; retry the complete collection.", True)
                    # The current frontend nests two .gpu-market wrappers.
                    # Anchor extraction to the unique listing, then retain its
                    # nearest source wrapper for the deterministic HTML parser.
                    listing = page.locator(".gpu-market .list-content")
                    if listing.count() != 1:
                        raise FetchError("page_structure_changed", "AutoDL's market listing container was not uniquely identified.")
                    content = listing.evaluate("element => element.closest('.gpu-market').outerHTML", timeout=remaining_ms())
                    if len(content.encode()) > MAX_RESPONSE_BYTES:
                        raise FetchError("response_too_large", "AutoDL's rendered market exceeds the size limit.")
                    pages.append({"metadata": meta, "html": content})
                    if index == ceil(expected_total / PAGE_SIZE):
                        # Attach projected public metadata once, not once per
                        # machine/page. No account bootstrap body is captured.
                        pages[0]["region_directory_payload"] = directory_state["payload"]
                        pages[0]["region_directory_error"] = directory_state["error"]
                        return pages
                raise FetchError("pagination_limit", "AutoDL market pagination exceeded the collection limit.")
            finally:
                with suppress(BrowserError):
                    browser.close()
    except BrowserTimeout:
        raise FetchError("timeout", "AutoDL market collection timed out.", True) from None
    except BrowserError:
        raise FetchError("browser_error", "The local browser could not read AutoDL's authorized market.") from None


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Return real prices plus independently verified country metadata/gaps."""
    pages = _render_market_pages(settings)
    quotes, seen = [], set()
    total = pages[0]["metadata"]["result_total"] if pages else 0
    if not total or len(pages) != ceil(total / PAGE_SIZE):
        raise _invalid()
    count = 0
    for index, page in enumerate(pages, 1):
        meta = page["metadata"]
        if meta["page_index"] != index or meta["page_size"] != PAGE_SIZE or meta["result_total"] != total:
            raise _invalid()
        for row in meta["rows"]:
            if row["machine_id"] in seen:
                raise _invalid()
            seen.add(row["machine_id"])
            count += 1
        quotes.extend(parse_market_page(page["html"], metadata=meta, observed_at=observed_at))
    if count != total or not quotes:
        raise _invalid()
    errors, metadata, directory_status = [], {}, "failed"
    try:
        projected = pages[0].get("region_directory_payload")
        if projected is None:
            raise ValueError("The current directory was unavailable.")
        metadata = autodl_regions.parse_region_directory(projected, observed_at=observed_at)
        directory_status = "ok"
    except (ValueError, TypeError, KeyError):
        supplied_error = pages[0].get("region_directory_error")
        errors.append({"source": "region_country_directory", "code": "region_directory_unavailable",
                       "message": "The current public country/region metadata was not verified; all native market prices were retained.",
                       "retryable": isinstance(supplied_error, dict) and supplied_error.get("retryable") is True})
    quotes, country_gaps = autodl_regions.enrich_market_quotes(quotes, region_directory=metadata)
    # Region gaps are per region, not duplicate rows for each machine/member
    # tier. Every returned quote still carries its own country-evidence reason.
    gaps = list({(gap["region"], gap["reason"]): gap for gap in country_gaps}.values())
    summary = {"market_listing_count": total, "gpu_listing_count": len({q["raw_sku"] for q in quotes}),
               "returned_price_count": len(quotes), "country_verified_price_count": sum(bool(q["compute_countries"]) for q in quotes),
               "country_unverified_region_codes": sorted({g["region"] for g in gaps}),
               "country_codes": sorted({c for q in quotes for c in q["compute_countries"]}),
               "region_codes": sorted({r for q in quotes for r in q["regions"]}),
               "public_directory_region_count": len(metadata), "all_market_prices_complete": False}
    return {"status": "partial" if errors or gaps else "ok", "prices": quotes, "errors": errors, "gaps": gaps,
            "coverage": summary, "catalog_coverage": {"summary": summary, "regions": metadata},
            "authentication_method": "caller_supplied_saved_browser_session",
            "source_contexts": [{"source": "market_prices", "source_url": SOURCE_URL, "source_type": SOURCE_TYPE,
                                 "status": "ok", "quote_count": len(quotes)},
                                {"source": "region_country_directory", "source_url": autodl_regions.REGIONS_URL,
                                 "source_type": "official_public_api", "status": directory_status}],
            "pricing_limitations": ["Country is attached only to reviewed exact region/name/DC identities; no nationwide price or new price-region binding is inferred."]}


def collect_quotes(*, settings: Settings, observed_at: str) -> list[dict]:
    """Retain all real native prices even when country metadata is incomplete.

    Use collect_result for source diagnostics. Each list-only quote retains the
    verified country evidence or an explicit reason why its country is empty.
    """
    return collect_result(settings=settings, observed_at=observed_at)["prices"]
