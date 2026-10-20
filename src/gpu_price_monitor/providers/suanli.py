"""Read Suanli's explicitly shared cloud-host and deployment card-hour rates.

The source states that elastic service deployment and cloud hosts use the same
GPU card-hour prices, billed by the second. This is a compute tariff, not a
token-inference API price or an invented complete-instance configuration.
"""

from datetime import date
from decimal import Decimal
import re

from bs4 import BeautifulSoup

SOURCE_URL = "https://suanli.cn/product/serverless/"
SOURCE_TYPE = "public_page"
_TITLE = "弹性服务部署算力价格"
_SCOPE = "弹性服务部署和云主机统一卡时定价，按秒收费"
_GPU_MODELS = {"4090", "5090", "H20", "H800", "H100", "H200", "PRO6000",
               "PRO6000D", "A100", "A800", "L20", "L40", "L40S", "摩尔线程S4000"}
# The provider labels the whole table GPU cards, but several rows are NPUs or
# other accelerators. BW1000's GPU classification has not been verified either.
_EXCLUDED_ACCELERATORS = {"昇腾910B2", "昇腾910C", "昆仑芯P800", "海光BW1000"}


def _invalid():
    return ValueError("The Suanli shared cloud-host GPU price table or billing scope was not recognized.")


def _text(element):
    return " ".join(element.get_text(" ", strip=True).split())


def parse_prices(content: str, *, observed_at: str, as_of: date) -> list[dict]:
    """Parse only a table whose local text explicitly includes cloud-host use."""
    soup = BeautifulSoup(content, "html.parser")
    headings = [h for h in soup.find_all("h2") if _text(h) == _TITLE]
    if len(headings) != 1:
        raise _invalid()
    section = headings[0].find_parent("section")
    if section is None or _SCOPE not in _text(section):
        raise _invalid()
    tables = section.find_all("table")
    if len(tables) != 1:
        raise _invalid()
    headers = tables[0].select("thead > tr")
    bodies = tables[0].find_all("tbody", recursive=False)
    if (len(headers) != 1 or len(bodies) != 1
            or [_text(cell) for cell in headers[0].find_all("th", recursive=False)] != ["GPU 卡型", "显存", "价格"]):
        raise _invalid()
    rows = bodies[0].find_all("tr", recursive=False)
    if not rows or len(rows) > 200:
        raise _invalid()
    quotes, seen = [], set()
    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) != 3 or any(cell.has_attr("rowspan") or cell.has_attr("colspan") for cell in cells):
            raise _invalid()
        raw_name, raw_vram, raw_price = map(_text, cells)
        vram = re.fullmatch(r"([1-9]\d{0,3}) G", raw_vram)
        price = re.fullmatch(r"(\d+(?:\.\d+)?) 元/小时", raw_price)
        if not vram or not price or len(price[1]) > 24 or not re.fullmatch(r"[A-Za-z0-9\u4e00-\u9fff -]{1,100}", raw_name):
            raise _invalid()
        if raw_name in _EXCLUDED_ACCELERATORS:
            continue
        amount = Decimal(price[1])
        if not amount.is_finite() or amount <= 0:
            raise _invalid()
        model = raw_name
        repeated_memory = re.search(r"-(\d+)G(?:B)?$", model, re.IGNORECASE)
        if repeated_memory:
            if int(repeated_memory[1]) != int(vram[1]):
                raise _invalid()
            model = model[:repeated_memory.start()]
        if model not in _GPU_MODELS:
            raise _invalid()
        identity = (model.upper(), int(vram[1]))
        if identity in seen:
            raise _invalid()
        seen.add(identity)
        quotes.append({
            "provider": "suanli", "product_type": "gpu_compute",
            "pricing_product_scope": ["cloud_host", "serverless_deployment"],
            "gpu_model": model.upper(), "gpu_variant": None,
            "gpu_vendor": "Moore Threads" if model == "摩尔线程S4000" else "NVIDIA",
            "raw_name": raw_name, "raw_sku": f"{raw_name}|{vram[1]}GB",
            "vram_gb": int(vram[1]), "gpu_count": None,
            "amount": format(amount, "f"), "currency": "CNY", "unit": "gpu_hour",
            "billing_mode": "on_demand", "price_basis": "advertised_per_gpu", "quote_status": "quoted",
            "resources": {}, "billing_meter": "second",
            "regions": [], "zones": [], "geographic_scope": "unspecified",
            "account_scope": "public_catalog", "tax_scope": "unspecified",
            "observed_at": observed_at, "effective_from": None, "effective_until": None,
            "source_url": SOURCE_URL, "source_type": SOURCE_TYPE, "availability": "unknown",
            "notes": [
                "The provider explicitly states a shared GPU card-hour tariff for cloud hosts and elastic service deployment, billed by the second.",
                "This is compute rental pricing; token-based model API prices are not included.",
                "Only recognized NVIDIA and Moore Threads GPUs are collected; Ascend/Kunlun NPUs and unverified Hygon accelerators are excluded.",
                "The current table does not specify GPU count per deployment, CPU, RAM, disk, compute region or availability zone.",
                "The per-GPU tariff is not a quote for a complete configured virtual machine; stock, eligibility, taxes and checkout charges were not verified.",
            ],
        })
    return quotes
