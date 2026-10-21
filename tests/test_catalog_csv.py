"""Complete catalog exports retain sales gaps and distinguish calculated costs."""

import csv
from copy import deepcopy
import io
from pathlib import Path
import unittest

from gpu_price_monitor import CATALOG_CSV_HEADERS, prices_to_csv
from gpu_price_monitor.providers import lambda_public


def read(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


class CatalogCsvTests(unittest.TestCase):
    def setUp(self):
        html = (Path(__file__).parent / "fixtures/lambda-complete-pricing-20261021.html").read_text()
        self.prices = lambda_public.parse_prices(html, observed_at="2026-10-21T11:37:00+00:00")

    def test_full_public_catalog_keeps_unpriced_terms_and_market_keeps_numeric_rates(self):
        source = {"prices": self.prices, "status": "success"}
        before = deepcopy(source)
        catalog = read(prices_to_csv(source, profile="catalog", bilingual_headers=False))
        market = read(prices_to_csv(source, bilingual_headers=False))
        self.assertEqual(len(catalog), 30)
        self.assertEqual(len(market), 28)
        self.assertEqual(len(CATALOG_CSV_HEADERS), 10)
        sales = [row for row in catalog if "需销售报价" in row["pricing_conditions"]]
        self.assertEqual(len(sales), 2)
        self.assertTrue(all(row["amount"] == "" for row in sales))
        reserved = [row for row in market if "计费=预留" in row["pricing_conditions"]]
        self.assertEqual(len(reserved), 6)
        self.assertTrue(all("集群共" in row["gpu_model"] for row in reserved))
        self.assertTrue(all("按周结算" in row["pricing_conditions"] for row in reserved))
        self.assertTrue(all("最低承诺" in row["pricing_conditions"] for row in reserved))
        self.assertEqual(source, before)

    def test_calculation_is_visible_in_every_readable_profile(self):
        quote = deepcopy(self.prices[0])
        quote.update(provider="nebius", quote_origin="published_tariff_preset_calculation",
                     rate_derivation={"method": "computed_from_official_tariff",
                                      "independent_provider_quote": False},
                     price_scope="platform_coverage", region_price_verified=False,
                     coverage_regions=["eu-north1"], coverage_countries=["FI"])
        source = {"prices": [quote], "status": "success"}
        for profile in ("catalog", "market"):
            row = read(prices_to_csv(source, profile=profile, bilingual_headers=False))[0]
            self.assertIn("官方费率×规格计算", row["pricing_conditions"])
            self.assertIn("非账号独立询价", row["pricing_conditions"])
            self.assertIn("磁盘与网络另计", row["pricing_conditions"])
            self.assertNotIn("FI", row["location"])
            self.assertNotIn("eu-north1", row["location"])
        self.assertEqual(read(prices_to_csv(source, profile="compact")), [])

    def test_from_price_is_never_promoted_to_exact_hourly_quote(self):
        quote = deepcopy(self.prices[0])
        quote.update(quote_status="starting_at", price_basis="starting_price", amount="0.79")
        source = {"prices": [quote], "status": "success"}
        self.assertEqual(read(prices_to_csv(source)), [])
        catalog = read(prices_to_csv(source, profile="catalog", bilingual_headers=False))
        self.assertEqual(catalog[0]["amount"], "0.79")
        self.assertIn("起步价", catalog[0]["pricing_conditions"])


if __name__ == "__main__":
    unittest.main()
