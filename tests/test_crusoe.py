"""Price boundary and structure checks for Crusoe's public instance table."""

from datetime import date
from pathlib import Path
import unittest

from gpu_price_monitor.providers.crusoe import SOURCE_URL, parse_prices


FIXTURE = Path(__file__).parent / "fixtures" / "crusoe-pricing.html"
OBSERVED_AT = "2026-10-15T09:00:00+00:00"


def parse(content):
    return parse_prices(content, observed_at=OBSERVED_AT, as_of=date(2026, 10, 15))


class CrusoeParserTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text(encoding="utf-8")

    def test_extracts_only_gpu_instance_prices_and_preserves_variants(self):
        prices = parse(self.content)
        self.assertEqual(len(prices), 10)
        quoted = [p for p in prices if p["quote_status"] == "quoted"]
        self.assertEqual(
            [(p["gpu_model"], p["gpu_variant"], p["amount"]) for p in quoted],
            [("H200", "HGX", "4.29"), ("H100", "HGX", "3.90"),
             ("A100", "SXM", "2.30"), ("A100", "PCIe", "2.00")],
        )
        for price in quoted:
            self.assertEqual(price["unit"], "gpu_hour")
            self.assertEqual(price["currency"], "USD")
            self.assertEqual(price["billing_mode"], "on_demand")
            self.assertEqual(price["price_basis"], "advertised_per_gpu")
            self.assertNotEqual(price["amount"], "5.50")

    def test_contact_sales_is_explicit_null_not_zero(self):
        prices = parse(self.content)
        contacts = [p for p in prices if p["quote_status"] == "contact_sales"]
        self.assertEqual(len(contacts), 6)
        self.assertTrue(all(p["amount"] is None for p in contacts))
        self.assertEqual({p["billing_mode"] for p in contacts}, {"on_demand", "spot"})
        self.assertEqual(prices[0]["gpu_variant"], "NVL72")
        self.assertEqual(prices[0]["vram_gb"], 186)

    def test_source_does_not_invent_regions_card_counts_dates_or_availability(self):
        for price in parse(self.content):
            self.assertEqual(price["regions"], [])
            self.assertEqual(price["geographic_scope"], "unspecified")
            self.assertIsNone(price["gpu_count"])
            self.assertIsNone(price["effective_from"])
            self.assertIsNone(price["effective_until"])
            self.assertEqual(price["availability"], "unknown")
            self.assertEqual(price["source_url"], SOURCE_URL)
            self.assertEqual(price["source_type"], "official_pricing_page")
            self.assertEqual(price["observed_at"], OBSERVED_AT)
            self.assertIn("orderability were not verified", " ".join(price["notes"]))

    def test_starting_price_is_not_an_unconditional_quote(self):
        prices = parse(self.content.replace("$3.90/GPU-hr", "Starting at $3.90/GPU-hr"))
        price = next(p for p in prices if p["gpu_model"] == "H100" and p["amount"])
        self.assertEqual(price["amount"], "3.90")
        self.assertEqual(price["quote_status"], "starting_at")
        self.assertEqual(price["price_basis"], "starting_price")

    def test_reordered_price_columns_follow_headers(self):
        prices = parse(self.content.replace("On-demand", "TEMP").replace("Current spot", "On-demand").replace("TEMP", "Current spot"))
        h100 = next(p for p in prices if p["gpu_model"] == "H100" and p["amount"])
        self.assertEqual(h100["billing_mode"], "spot")

    def test_unrecognized_page_or_structure_fails_closed(self):
        cases = [
            "<html><h1>Access denied</h1></html>",
            self.content.replace("GPU instances pricing", "All pricing"),
            self.content.replace("Current spot", "Reserved"),
            self.content.replace("pricing_gpu-item", "changed-item"),
            self.content.replace("$3.90/GPU-hr", "$3.90/token"),
            self.content.replace("$3.90/GPU-hr", "$0/GPU-hr"),
            self.content.replace("141GB", "unknown"),
            self.content.replace("<h4 class=\"pricing-item-heading\">NVIDIA H200</h4>", ""),
        ]
        for content in cases:
            with self.subTest(content=content[:100]):
                with self.assertRaises(ValueError):
                    parse(content)


if __name__ == "__main__":
    unittest.main()
