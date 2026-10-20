"""Read the default, explicitly selected EBCloud GPU-container configurations.

The anonymous homepage server-renders one GPU and pay-as-you-go as checked
radio choices. Only those configurations are collected; unchecked multi-GPU,
monthly and yearly options, trial credits and model-inference APIs are excluded.
"""

from datetime import date
from decimal import Decimal
import re

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.ebcloud.com/"
SOURCE_TYPE = "public_page"
_HARDWARE = re.compile(r"(?P<model>(?:RTX-)?[A-Za-z0-9]+)\s+(?P<vram>\d+)GB(?:\s+(?P<variant>NVLink))?\Z")
_MEMORY = re.compile(r"(?P<technology>DDR\d+)\s+(?P<amount>\d+(?:\.\d+)?)\s+(?P<unit>GB|GiB)\Z")


def _invalid():
    return ValueError("The EBCloud GPU-container price, unit or selected configuration was not recognized.")


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _one(parent, selector):
    matches = parent.select(selector)
    if len(matches) != 1:
        raise _invalid()
    return matches[0]


def _number(text: str) -> str:
    if not re.fullmatch(r"\d+(?:\.\d+)?", text) or len(text) > 24:
        raise _invalid()
    value = Decimal(text)
    if not value.is_finite() or value <= 0:
        raise _invalid()
    return format(value, "f")


def _selected(row, expected: str) -> None:
    labels = row.select("label")
    checked = [label for label in labels if label.select('input[type="radio"][checked]')]
    selected = [label for label in labels if "is-selected" in label.get("class", [])]
    if len(checked) != 1 or len(selected) != 1 or checked[0] is not selected[0] or _text(checked[0]) != expected:
        raise _invalid()


def parse_prices(content: str, *, observed_at: str, as_of: date) -> list[dict]:
    """Return only the public hourly configuration visibly selected per card."""
    soup = BeautifulSoup(content, "html.parser")
    lists = soup.select(".card-list")
    if len(lists) != 1:
        raise _invalid()
    heading = lists[0].find_previous_sibling()
    if heading is None or _text(_one(heading, ".eb-header-1")) != "GPU 容器服务平台":
        raise _invalid()
    cards = lists[0].select(":scope > .card-content")
    if not cards or len(cards) > 100:
        raise _invalid()
    result, seen = [], set()
    for card in cards:
        name = _text(_one(card, ".card-title"))
        model = _HARDWARE.fullmatch(name)
        if not model or int(model["vram"]) <= 0:
            raise _invalid()
        fields = {}
        for row in card.select(".info-row"):
            label = _text(_one(row, ".info-label"))
            if label in fields:
                raise _invalid()
            fields[label] = row
        if not {"计费模式", "显卡数量", "内存", "CPU"} <= fields.keys():
            raise _invalid()
        _selected(fields["计费模式"], "按量付费")
        _selected(fields["显卡数量"], "1卡")
        if _text(_one(card, ".card-price .price-symbol")) != "¥" or _text(_one(card, ".card-price .price-unit")) != "/小时":
            raise _invalid()
        amount = _number(_text(_one(card, ".card-price .price-amount")))
        memory_text = _text(_one(fields["内存"], ".info-value"))
        memory = _MEMORY.fullmatch(memory_text)
        cpu = re.fullmatch(r"(\d+(?:\.\d+)?) Core", _text(_one(fields["CPU"], ".info-value")))
        if not memory or not cpu:
            raise _invalid()
        cpu_cores, memory_amount = _number(cpu[1]), _number(memory["amount"])
        gpu_model = model["model"]
        if gpu_model.startswith("RTX-A"):
            gpu_model = gpu_model.removeprefix("RTX-")
        elif gpu_model.startswith("RTX-"):
            gpu_model = gpu_model.replace("RTX-", "RTX ", 1)
        identity = (gpu_model, model["vram"], model["variant"], cpu_cores, memory_text)
        if identity in seen:
            raise _invalid()
        seen.add(identity)
        resources = {"cpu_cores": cpu_cores, "memory": {"amount": memory_amount, "unit": memory["unit"], "technology": memory["technology"]}}
        if "计算网络" in fields:
            resources["compute_network"] = _text(_one(fields["计算网络"], ".info-value"))
        if "支持存储" in fields:
            resources["supported_storage_types"] = _text(_one(fields["支持存储"], ".info-value"))
        result.append({
            "provider": "ebcloud", "product_type": "gpu_container", "gpu_model": gpu_model.upper(),
            "gpu_variant": model["variant"], "raw_name": name,
            "raw_sku": f"{name}|1GPU|{cpu_cores}Core|{memory_text}",
            "vram_gb": int(model["vram"]), "gpu_count": 1,
            "amount": amount, "currency": "CNY", "unit": "gpu_hour",
            "billing_mode": "on_demand", "price_basis": "instance_total_allocated", "quote_status": "quoted",
            "instance_price": {"amount": amount, "currency": "CNY", "unit": "instance_hour"},
            "resources": resources, "selected_configuration": {"billing_label": "按量付费", "gpu_count_label": "1卡"},
            "regions": [], "zones": [], "geographic_scope": "unspecified", "account_scope": "public_catalog",
            "tax_scope": "unspecified", "observed_at": observed_at, "effective_from": None, "effective_until": None,
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "availability": "unknown",
            "normalization": {"formula": "instance_price.amount / gpu_count", "gpu_count": 1},
            "notes": [
                "GPU container rental, not a standalone virtual machine or a serverless inference-execution price.",
                "The page explicitly selects pay-as-you-go and one GPU; only that published container configuration is quoted.",
                "Trial hours, registration credits and unselected monthly/yearly or multi-GPU choices are not applied to this price.",
                "The homepage does not state a compute region, zone, current stock, tax scope or separate storage/networking charges.",
                "Supported storage types describe compatibility; included storage capacity and full physical-board allocation were not verified.",
            ],
        })
    return result
