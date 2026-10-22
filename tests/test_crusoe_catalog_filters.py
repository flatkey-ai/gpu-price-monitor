"""Deployment filters match one location and never become price filters."""

from datetime import date
from pathlib import Path
import unittest

from gpu_price_monitor.filters import apply_filters, filter_support
from gpu_price_monitor.providers import crusoe, crusoe_catalog
from gpu_price_monitor.settings import Settings


FIXTURES = Path(__file__).parent / "fixtures"


class CrusoeCatalogFilterTests(unittest.TestCase):
    def setUp(self):
        locations = crusoe_catalog.parse_locations((FIXTURES / "crusoe-locations-docs-20261022.html").read_text())
        catalog = crusoe_catalog.parse_vm_catalog((FIXTURES / "crusoe-vm-docs-20261022.html").read_text(), locations)
        prices = crusoe.parse_prices((FIXTURES / "crusoe-pricing-20261022.html").read_text(),
                                    observed_at="2026-10-22T03:47:00+00:00", as_of=date(2026, 10, 22))
        self.prices = crusoe_catalog.annotate_prices(prices, catalog, locations)

    def test_country_and_coverage_region_must_describe_same_place(self):
        h100 = [q for q in self.prices if q["gpu_model"] == "H100"]
        self.assertTrue(h100)
        invalid = {"coverage_countries": ["US"], "coverage_regions": ["eu-iceland1"]}
        self.assertEqual(apply_filters(h100, invalid), [])
        valid = {"coverage_countries": ["IS"], "coverage_regions": ["eu-iceland1"]}
        self.assertEqual(apply_filters(h100, valid), h100)
        for quote in h100:
            self.assertEqual(quote["regions"], [])
            self.assertFalse(quote["region_price_verified"])

    def test_deployment_coverage_does_not_enable_price_region_filters(self):
        settings = Settings(providers=("crusoe",), catalog_scope="complete")
        support = filter_support("crusoe", {"coverage_regions": ["eu-iceland1"],
                                            "regions": ["eu-iceland1"], "compute_countries": ["IS"]}, settings=settings)
        self.assertEqual(support["coverage_regions"]["status"], "applied_locally")
        self.assertEqual(support["regions"]["status"], "unsupported")
        self.assertEqual(support["compute_countries"]["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
