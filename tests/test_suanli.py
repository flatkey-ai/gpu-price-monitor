"""Shared cloud-host tariff scope checks, with historical reduced HTML."""

from datetime import date
import json
from pathlib import Path
import unittest

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import suanli

FIXTURE = Path(__file__).parent / "fixtures" / "suanli-pricing.html"
OBSERVED = "2026-10-20T10:40:00+00:00"


def fixture():
    return FIXTURE.read_text()


def parse(content=None):
    return suanli.parse_prices(fixture() if content is None else content,
                               observed_at=OBSERVED, as_of=date(2026, 10, 20))


class SuanliTests(unittest.TestCase):
    def test_explicit_shared_cloud_host_gpu_tariff(self):
        quotes = parse()
        self.assertEqual(len(quotes), 3)
        quote = next(q for q in quotes if q["gpu_model"] == "L20")
        self.assertEqual(quote["amount"], "4.00")
        self.assertEqual(quote["currency"], "CNY")
        self.assertEqual(quote["vram_gb"], 48)
        self.assertEqual(quote["unit"], "gpu_hour")
        self.assertEqual(quote["product_type"], "gpu_compute")
        self.assertEqual(quote["pricing_product_scope"], ["cloud_host", "serverless_deployment"])
        self.assertEqual(quote["billing_meter"], "second")
        self.assertEqual(quote["price_basis"], "advertised_per_gpu")
        self.assertIsNone(quote["gpu_count"])
        self.assertEqual(quote["resources"], {})
        self.assertEqual(quote["regions"], [])
        self.assertEqual(quote["availability"], "unknown")
        self.assertNotIn("instance_price", quote)
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_same_model_with_distinct_memory_is_preserved(self):
        h20 = [q for q in parse() if q["gpu_model"] == "H20"]
        self.assertEqual({q["vram_gb"] for q in h20}, {96, 141})
        self.assertEqual(len({q["raw_sku"] for q in h20}), 2)

    def test_cloud_host_scope_and_card_hour_statement_are_required(self):
        for content in (fixture().replace("弹性服务部署和云主机统一卡时定价", "仅弹性服务部署定价"),
                        fixture().replace("按秒收费", "每百万token收费")):
            with self.assertRaises(ValueError):
                parse(content)

    def test_invalid_unit_zero_price_and_memory_mismatch_fail(self):
        for content in (fixture().replace("4.00 元/小时", "4.00 元/百万tokens"),
                        fixture().replace("4.00 元/小时", "0 元/小时"),
                        fixture().replace("H20-96GB", "H20-80GB"),
                        fixture().replace("GPU 卡型", "CPU 型号")):
            with self.assertRaises(ValueError):
                parse(content)

    def test_duplicate_rows_are_rejected_and_other_tables_are_excluded(self):
        self.assertTrue(all(q["gpu_model"] != "L20 input tokens" for q in parse()))
        soup = BeautifulSoup(fixture(), "html.parser")
        table = next(t for t in soup.find_all("table") if t.find("tbody"))
        table.find("tbody").append(BeautifulSoup(str(table.find("tbody").find("tr")), "html.parser"))
        with self.assertRaises(ValueError):
            parse(str(soup))

    def test_npu_and_unverified_accelerator_rows_are_excluded(self):
        soup = BeautifulSoup(fixture(), "html.parser")
        body = soup.find("tbody")
        for model in ("昇腾910B2", "昇腾910C", "昆仑芯P800", "海光BW1000"):
            body.append(BeautifulSoup(f"<tr><td>{model}</td><td>64 G</td><td>4.00 元/小时</td></tr>", "html.parser"))
        self.assertEqual(len(parse(str(soup))), 3)
        body.append(BeautifulSoup("<tr><td>未知AI芯片</td><td>64 G</td><td>4.00 元/小时</td></tr>", "html.parser"))
        with self.assertRaises(ValueError):
            parse(str(soup))


if __name__ == "__main__":
    unittest.main()
