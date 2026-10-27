"""Offline checks for currency, instance price units and GPU-table boundaries."""

from datetime import date
from decimal import Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import verda
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-20T10:30:00+00:00"


def fixture(currency="usd"):
    return (FIXTURES / f"verda-{currency}-pricing.html").read_text()


def parse(content=None, **kwargs):
    return verda.parse_prices(fixture() if content is None else content,
                              observed_at=OBSERVED, as_of=date(2026, 10, 20), **kwargs)


class VerdaTests(unittest.TestCase):
    def test_only_gpu_instance_on_demand_and_spot_tables_are_collected(self):
        quotes = parse()
        self.assertEqual(len(quotes), 6)
        self.assertEqual({q["gpu_model"] for q in quotes}, {"GB300", "H100"})
        self.assertEqual({q["billing_mode"] for q in quotes}, {"on_demand", "spot"})
        first = quotes[0]
        self.assertEqual(first["amount"], "11.82")
        self.assertEqual(first["instance_price"], {"amount": "11.82", "currency": "USD", "unit": "instance_hour"})
        self.assertEqual(first["resources"], {"cpu_count": 32, "ram_gb": 225, "listed_gpu_vram_gb": 288})
        self.assertEqual(first["vram_gb"], 288)
        self.assertEqual(first["gpu_variant"], "SXM6")
        self.assertEqual(first["regions"], [])
        self.assertEqual(first["availability"], "unknown")
        self.assertEqual(first["source_type"], "public_page")
        self.assertTrue(any("interruption" in note for note in quotes[1]["notes"]))
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_same_gpu_with_different_cpu_and_ram_is_not_deduplicated(self):
        quotes = [q for q in parse() if q["gpu_model"] == "H100" and q["billing_mode"] == "on_demand"]
        self.assertEqual(len(quotes), 2)
        self.assertEqual({q["resources"]["cpu_count"] for q in quotes}, {30, 32})
        self.assertEqual({q["resources"]["ram_gb"] for q in quotes}, {120, 170})
        self.assertEqual(len({q["raw_sku"] for q in quotes}), 2)

    def test_eur_currency_tab_is_independent_of_usd(self):
        quote = parse(fixture("eur"), expected_currency="EUR")[0]
        self.assertEqual(quote["currency"], "EUR")
        self.assertEqual(quote["amount"], "10.51")
        self.assertEqual(quote["source_url"], "https://verda.com/pricing?currency=eur")
        with self.assertRaises(ValueError):
            parse(fixture("eur"), expected_currency="USD")
        with self.assertRaises(ValueError):
            parse(fixture("eur").replace("€10.51/h", "$10.51/h"))

    def test_multi_gpu_prices_are_allocated_from_total_not_multiplied(self):
        # Synthetic mutation exercises a future explicitly listed 2-GPU row.
        content = fixture().replace("1x GB300 SXM6 288GB", "2x GB300 SXM6 288GB")
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.traps[Inexact] = True
            quote = parse(content)[0]
        self.assertEqual(quote["gpu_count"], 2)
        self.assertEqual(quote["amount"], "5.91")
        self.assertEqual(quote["instance_price"]["amount"], "11.82")
        self.assertEqual(quote["vram_gb"], 288)

    def test_requires_explicit_instance_hour_semantics_in_official_metadata(self):
        for content in (fixture().replace("Hourly on-demand instance price", "GPU hourly price"),
                        fixture().replace('"unitText": "hour"', '"unitText": "GPU-hour"'),
                        fixture().replace('"priceCurrency": "USD"', '"priceCurrency": "EUR"'),
                        fixture().replace("$11.82/h", "$11.82/GPU/h")):
            with self.subTest(content=content[:100]), self.assertRaises(ValueError):
                parse(content)

    def test_missing_currency_duplicate_table_or_malformed_rows_fail_closed(self):
        bad = [fixture().replace('aria-current="true"', 'aria-current="false"'),
               fixture().replace("<h3>On-demand</h3>", "<h3>Reserved</h3>", 1),
               fixture().replace("$11.82/h", "Contact sales"),
               fixture().replace("$11.82/h", "$0/h"),
               fixture().replace("11.82", "0.0000000000001"),
               fixture().replace("288 GB", "287 GB", 1)]
        soup = BeautifulSoup(fixture(), "html.parser")
        soup.find("table").insert_after(BeautifulSoup(str(soup.find("table")), "html.parser"))
        bad.append(str(soup))
        soup = BeautifulSoup(fixture(), "html.parser")
        soup.find("table").append(BeautifulSoup(str(soup.find("table").find_all("tr")[1]), "html.parser"))
        bad.append(str(soup))
        for content in bad:
            with self.subTest(content=content[:100]), self.assertRaises(ValueError):
                parse(content)

    @patch("gpu_price_monitor.providers.verda.fetch_text")
    def test_collection_fetches_both_public_currency_pages(self, fetch):
        fetch.side_effect = lambda url, settings: fixture("eur" if "eur" in url else "usd")
        quotes = verda.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(quotes), 12)
        self.assertEqual({q["currency"] for q in quotes}, {"USD", "EUR"})

    @patch("gpu_price_monitor.providers.verda.fetch_text")
    def test_currency_fallback_or_partial_network_failure_does_not_report_complete_catalog(self, fetch):
        fetch.return_value = fixture()
        with self.assertRaises(ValueError):
            verda.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        fetch.side_effect = [fixture(), FetchError("http_error", "The pricing source returned HTTP 403.")]
        with self.assertRaises(FetchError):
            verda.collect_quotes(settings=Settings(), observed_at=OBSERVED)

    def test_all_public_gpu_sections_and_explicit_cluster_sizes(self):
        for currency in ("usd", "eur"):
            content = (FIXTURES / f"verda-full-{currency}-pricing-20261027.html").read_text()
            quotes = parse(content, expected_currency=currency.upper())
            self.assertEqual(len(quotes), 88)
            cc = [q for q in quotes if q.get("cloud_tier") == "confidential_computing"]
            clusters = [q for q in quotes if q.get("cloud_tier") == "instant_cluster"]
            self.assertEqual(len(cc), 6)
            self.assertEqual(len(clusters), 56)
            self.assertEqual({q["gpu_model"] for q in cc}, {"B300", "B200", "RTX PRO 6000"})
            self.assertEqual({q["gpu_count"] for q in clusters if q["gpu_model"] == "GB300"}, set(range(8, 73, 4)))
            self.assertTrue(all(q["product_type"] == "gpu_cluster" and q["gpu_count"] > 1 for q in clusters))
            self.assertTrue(all(not q["regions"] and q["geographic_scope"] == "unspecified" for q in quotes))
            self.assertEqual(len({(q["raw_sku"], q["billing_mode"]) for q in quotes}), 88)

    def test_visible_cluster_tariff_is_not_overwritten_by_conflicting_metadata(self):
        content = (FIXTURES / "verda-full-usd-pricing-20261027.html").read_text()
        quote = next(q for q in parse(content) if q.get("cloud_tier") == "instant_cluster"
                     and q["gpu_model"] == "B200" and q["gpu_count"] == 32)
        self.assertEqual(quote["amount"], "8.525")
        self.assertEqual(quote["price_basis"], "advertised_per_gpu")
        self.assertNotIn("instance_price", quote)
        self.assertTrue(quote["conditions"]["pricing_conflict"])
        self.assertEqual(quote["conditions"]["published_structured_total"]["amount"], "272.7")
        self.assertEqual(quote["resources"]["cpu_count"], 30 * 32)
        self.assertEqual(quote["resources"]["ram_gb"], 170 * 32)

    def test_confidential_computing_display_rounding_and_product_identity(self):
        content = (FIXTURES / "verda-full-usd-pricing-20261027.html").read_text()
        quote = next(q for q in parse(content) if q.get("cloud_tier") == "confidential_computing"
                     and q["gpu_model"] == "B300" and q["billing_mode"] == "on_demand")
        self.assertEqual(quote["amount"], "11.13")
        self.assertIn("CC", quote["raw_sku"])
        self.assertTrue(quote["conditions"]["confidential_computing"])
        with self.assertRaises(ValueError):
            parse(content.replace("$11.13/h", "$11.14/h"))

    def test_clusters_require_explicit_sizes_and_hourly_metadata(self):
        content = (FIXTURES / "verda-full-usd-pricing-20261027.html").read_text()
        for changed in (content.replace("Hourly instant cluster price", "Monthly instant cluster price"),
                        content.replace("Price (1x GPU)", "Price"),
                        content.replace("8x GB300 SXM6 288GB instant cluster", "1x GB300 SXM6 288GB instant cluster")):
            with self.assertRaises(ValueError):
                parse(changed)


if __name__ == "__main__":
    unittest.main()
