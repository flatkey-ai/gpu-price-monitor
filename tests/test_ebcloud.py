"""Explicit SSR billing/count checks for EBCloud GPU-container rates."""

from datetime import date
import json
from pathlib import Path
import unittest

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import ebcloud

FIXTURE = Path(__file__).parent / "fixtures" / "ebcloud-pricing.html"
OBSERVED = "2026-10-20T10:30:00+00:00"


def fixture():
    return FIXTURE.read_text()


def parse(content=None):
    return ebcloud.parse_prices(fixture() if content is None else content,
                                observed_at=OBSERVED, as_of=date(2026, 10, 20))


class EBCloudTests(unittest.TestCase):
    def test_default_explicit_single_gpu_container_hourly_prices(self):
        quotes = parse()
        self.assertEqual(len(quotes), 2)
        quote = quotes[0]
        self.assertEqual(quote["gpu_model"], "RTX 4090D")
        self.assertEqual(quote["amount"], "2.06")
        self.assertEqual(quote["gpu_count"], 1)
        self.assertEqual(quote["vram_gb"], 24)
        self.assertEqual(quote["currency"], "CNY")
        self.assertEqual(quote["product_type"], "gpu_container")
        self.assertEqual(quote["instance_price"]["amount"], quote["amount"])
        self.assertEqual(quote["billing_mode"], "on_demand")
        self.assertEqual(quote["resources"]["cpu_cores"], "10")
        self.assertEqual(quote["resources"]["memory"], {"amount": "100", "unit": "GB", "technology": "DDR4"})
        self.assertEqual(quote["regions"], [])
        self.assertEqual(quote["availability"], "unknown")
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_decimal_cpu_does_not_imply_fractional_gpu(self):
        quote = parse()[1]
        self.assertEqual(quote["gpu_model"], "A16")
        self.assertEqual(quote["gpu_count"], 1)
        self.assertEqual(quote["resources"]["cpu_cores"], "1.75")
        self.assertEqual(quote["amount"], "0.99")

    def test_no_selected_radio_or_conflicting_selection_is_rejected(self):
        for variant in (fixture().replace(' checked=""', "", 1),
                        fixture().replace("is-selected", "unselected", 1),
                        fixture().replace("按量付费", "包年包月", 1),
                        fixture().replace("1卡", "2卡", 1)):
            with self.subTest(content=variant[:100]), self.assertRaises(ValueError):
                parse(variant)

    def test_unselected_monthly_and_multigpu_prices_are_not_synthesized(self):
        quotes = parse()
        self.assertEqual({q["gpu_count"] for q in quotes}, {1})
        self.assertEqual({q["billing_mode"] for q in quotes}, {"on_demand"})
        self.assertTrue(all(q["amount"] != "0" for q in quotes))
        self.assertTrue(any("Trial hours" in note for note in quotes[0]["notes"]))

    def test_unrecognized_currency_period_or_amount_fails(self):
        for variant in (fixture().replace('>¥<', '>$<', 1),
                        fixture().replace("/小时", "/月", 1),
                        fixture().replace(">2.06<", ">低至2.06<", 1),
                        fixture().replace(">2.06<", ">0<", 1),
                        fixture().replace("RTX-4090D 24GB", "未知GPU")):
            with self.subTest(content=variant[:100]), self.assertRaises(ValueError):
                parse(variant)

    def test_api_prices_other_sections_and_duplicate_cards_do_not_pollute_rates(self):
        self.assertEqual(len(parse(fixture().replace("输入 ¥0.01/百万tokens", "RTX-4090D ¥0.001/小时"))), 2)
        soup = BeautifulSoup(fixture(), "html.parser")
        card = soup.select_one(".card-content")
        soup.select_one(".card-list").append(BeautifulSoup(str(card), "html.parser"))
        with self.assertRaises(ValueError):
            parse(str(soup))


if __name__ == "__main__":
    unittest.main()
