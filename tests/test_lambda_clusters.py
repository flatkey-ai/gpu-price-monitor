"""Official public cluster tariffs retain term and whole-cluster count evidence."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import lambda_clusters, lambda_public
from gpu_price_monitor.settings import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "lambda-complete-pricing-20261021.html"
OBSERVED = "2026-10-21T10:00:00+00:00"


class LambdaClusterTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text()

    def parse(self, content=None):
        return lambda_clusters.parse_prices(self.content if content is None else content,
                                           observed_at=OBSERVED, source_url=lambda_clusters.PRICING_URL)

    def test_complete_public_page_keeps_all_instance_and_cluster_rows_once(self):
        quotes = lambda_public.parse_prices(self.content, observed_at=OBSERVED, as_of=date(2026, 10, 21))
        self.assertEqual(len(quotes), 30)
        self.assertEqual(len([q for q in quotes if q["billing_mode"] == "on_demand"]), 22)
        self.assertEqual(len([q for q in quotes if q["billing_mode"] == "reserved"]), 8)
        self.assertTrue(all(q["source_url"] == lambda_public.SOURCE_URL for q in quotes))
        self.assertTrue(all(q["configuration_expansion"] is False for q in quotes))
        self.assertEqual({q["price_record_kind"] for q in quotes}, {"published_price", "contact_sales_listing"})
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_numeric_cluster_rates_are_independent_reservation_tariffs_not_on_demand(self):
        quotes = [q for q in self.parse() if q["quote_status"] == "quoted"]
        self.assertEqual({model: [q["amount"] for q in quotes if q["gpu_model"] == model]
                          for model in ("B200", "H100")},
                         {"B200": ["9.86", "9.36", "8.87"], "H100": ["6.16", "5.85", "5.54"]})
        for quote in quotes:
            self.assertEqual((quote["currency"], quote["unit"], quote["billing_mode"]), ("USD", "gpu_hour", "reserved"))
            self.assertEqual(quote["minimum_commitment"], {"duration": {"amount": 2, "unit": "week"}})
            self.assertEqual(quote["source_conditions"]["reservation_term"]["maximum"], {"amount": 1, "unit": "year"})
            self.assertEqual(quote["source_conditions"]["billing_increment"], "week")
            self.assertTrue(quote["source_conditions"]["sales_contact_required"])
            self.assertEqual(quote["product_type"], "gpu_cluster")
            self.assertEqual(quote["product_line"], "1-Click Clusters")
            self.assertIsNone(quote["gpu_count"])
            self.assertIsNone(quote["vram_gb"])
            self.assertIsNone(quote["raw_sku"])
            self.assertNotIn("instance_price", quote)

    def test_minimum_cluster_gpu_count_does_not_become_exact_or_node_gpu_count(self):
        b200 = [q for q in self.parse() if q["gpu_model"] == "B200"]
        h100 = [q for q in self.parse() if q["gpu_model"] == "H100"]
        self.assertEqual(b200[0]["selected_configuration"], {"cluster_gpu_count": 16, "cluster_gpu_count_relation": "exact"})
        self.assertEqual(b200[2]["selected_configuration"], {"cluster_gpu_count": 256, "cluster_gpu_count_relation": "minimum"})
        self.assertEqual(h100[2]["selected_configuration"], {"cluster_gpu_count": 256, "cluster_gpu_count_relation": "exact"})
        self.assertTrue(all(q["gpu_count"] is None for q in b200 + h100))

    def test_long_term_sales_rows_keep_null_prices_and_unbounded_maximum(self):
        quotes = [q for q in self.parse() if q["quote_status"] == "contact_sales"]
        self.assertEqual(len(quotes), 2)
        for quote in quotes:
            self.assertIsNone(quote["amount"])
            self.assertEqual(quote["minimum_commitment"], {"duration": {"amount": 1, "unit": "year"}})
            self.assertIsNone(quote["source_conditions"]["reservation_term"]["maximum"])
            self.assertEqual(quote["selected_configuration"], {"cluster_gpu_count": 16, "cluster_gpu_count_relation": "minimum"})
            self.assertEqual(quote["price_record_kind"], "contact_sales_listing")

    def test_catalog_price_does_not_invent_region_country_capacity_or_effective_time(self):
        for quote in self.parse():
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["compute_countries"], [])
            self.assertEqual(quote["price_scope"], "unlocated_catalog")
            self.assertFalse(quote["region_price_verified"])
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["tax_scope"], "excluded")
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertIsNone(quote["effective_from"])
            self.assertIsNone(quote["effective_until"])
            self.assertEqual(quote["billing_source_url"], lambda_clusters.BILLING_URL)

    def test_cluster_tabs_follow_aria_identity_when_panels_are_reordered(self):
        soup = BeautifulSoup(self.content, "html.parser")
        panels = soup.find_all("section")[0].find_all(attrs={"role": "tabpanel"})
        panels[0].insert_before(panels[1].extract())
        self.assertEqual(self.parse(str(soup)), self.parse())

    def test_corrupt_cluster_table_prevents_partial_instance_only_success(self):
        for before, after in (("$9.86", "$9.86 / month"), ("2 weeks – 1 year", "Flexible"),
                              ("256+", "up to 256"), ("PRICE/GPU/HR*", "PRICE/CLUSTER/HR*"),
                              ("$9.86", "€9.86"), ("$9.86", "$0")):
            with self.subTest(change=(before, after)):
                changed = self.content.replace(before, after, 1)
                with self.assertRaises(ValueError):
                    self.parse(changed)
                with self.assertRaises(ValueError):
                    lambda_public.parse_prices(changed, observed_at=OBSERVED)

    def test_ambiguous_tabs_duplicates_and_missing_tax_are_rejected(self):
        for change in ("reverse_link", "missing_panel", "duplicate_row", "missing_tax", "changed_model"):
            soup = BeautifulSoup(self.content, "html.parser")
            panel = soup.find_all("section")[0].find(attrs={"role": "tabpanel"})
            if change == "reverse_link":
                panel["aria-labelledby"] = "unknown"
            elif change == "missing_panel":
                panel.decompose()
            elif change == "duplicate_row":
                panel.find("tbody").append(deepcopy(panel.find("tbody").find("tr")))
            elif change == "missing_tax":
                panel.select_one(".table-footer").decompose()
            else:
                panel.find("tbody").find("tr")["data-plan"] = "NVIDIA B300"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.parse(str(soup))

    def test_complete_pricing_page_requires_cluster_section_but_legacy_instance_fixture_still_works(self):
        soup = BeautifulSoup(self.content, "html.parser")
        soup.find_all("section")[0].decompose()
        with self.assertRaises(ValueError):
            lambda_public.parse_prices(str(soup), observed_at=OBSERVED)
        legacy = FIXTURE.with_name("lambda-public-pricing.html").read_text()
        self.assertEqual(len(lambda_public.parse_prices(legacy, observed_at=OBSERVED)), 9)

    @patch("gpu_price_monitor.providers.lambda_clusters.fetch_text")
    def test_reusable_collection_fetches_only_the_official_public_cluster_page(self, fetch):
        fetch.return_value = self.content
        settings = Settings()
        self.assertEqual(len(lambda_clusters.collect_quotes(settings=settings, observed_at=OBSERVED)), 8)
        fetch.assert_called_once_with(lambda_clusters.SOURCE_URL, settings)


if __name__ == "__main__":
    unittest.main()
