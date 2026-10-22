"""Keep documented Crusoe deployment coverage distinct from price geography."""

from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import crusoe, crusoe_catalog
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED_AT = "2026-10-22T04:00:00+00:00"


class CrusoeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.locations_html = (FIXTURES / "crusoe-locations-docs-20261022.html").read_text()
        self.vms_html = (FIXTURES / "crusoe-vm-docs-20261022.html").read_text()
        self.pricing_html = (FIXTURES / "crusoe-pricing-20261021.html").read_text()
        self.locations = crusoe_catalog.parse_locations(self.locations_html)

    def test_location_directory_has_explicit_country_and_chinese_labels(self):
        self.assertEqual(len(self.locations), 7)
        self.assertEqual({v["country_code"] for v in self.locations.values()}, {"US", "IS", "NO"})
        self.assertEqual(self.locations["us-east1-a"]["region_name_zh"], "弗吉尼亚州")
        self.assertEqual(self.locations["eu-iceland2-a"]["country_name_zh"], "冰岛")
        self.assertTrue(all(v["country_basis"] == "normalized_explicit_place_label_not_region_prefix"
                            for v in self.locations.values()))

    def test_exact_vm_configurations_and_gpu_counts_are_preserved(self):
        catalog = crusoe_catalog.parse_vm_catalog(self.vms_html, self.locations)
        self.assertEqual(len(catalog), 17)
        l40s = [v for v in catalog if v["gpu_model"] == "L40S"]
        self.assertEqual({v["gpu_count"] for v in l40s}, {1, 2, 4, 8, 10})
        b200 = next(v for v in catalog if v["gpu_model"] == "B200")
        self.assertEqual(b200["coverage_countries"], ["IS", "NO", "US"])
        self.assertEqual(b200["gpu_count"], 8)
        self.assertFalse(b200["independent_provider_quote"])
        self.assertFalse(b200["stock_verified"])

    def test_docs_cannot_turn_a_public_rate_into_a_regional_or_uniform_price(self):
        catalog = crusoe_catalog.parse_vm_catalog(self.vms_html, self.locations)
        original = crusoe.parse_prices(self.pricing_html, observed_at=OBSERVED_AT, as_of=date(2026, 10, 22))
        result = crusoe_catalog.annotate_prices(original, catalog, self.locations)
        self.assertEqual(len(result), len(original))
        self.assertEqual([q["amount"] for q in result], [q["amount"] for q in original])
        for quote in result:
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["zones"], [])
            self.assertEqual(quote["compute_countries"], [])
            self.assertFalse(quote["region_price_verified"])
            self.assertEqual(quote["price_applicability"]["status"], "unverified")
            self.assertFalse(quote["price_applicability"]["uniform_price_verified"])
        h100 = next(q for q in result if q["gpu_model"] == "H100")
        self.assertEqual(h100["coverage_countries"], ["IS", "US"])
        self.assertEqual(len(h100["documented_vm_configurations"]), 1)
        self.assertIsNone(h100["gpu_count"])
        self.assertNotIn("coverage_countries", original[0])

    def test_a100_pcie_and_sxm_deployment_candidates_do_not_mix(self):
        catalog = crusoe_catalog.parse_vm_catalog(self.vms_html, self.locations)
        prices = crusoe.parse_prices(self.pricing_html, observed_at=OBSERVED_AT, as_of=date(2026, 10, 22))
        result = crusoe_catalog.annotate_prices(prices, catalog, self.locations)
        sxm = next(q for q in result if q["gpu_model"] == "A100" and q["gpu_variant"] == "SXM")
        pcie = next(q for q in result if q["gpu_model"] == "A100" and q["gpu_variant"] == "PCIe")
        self.assertEqual(len(sxm["documented_vm_configurations"]), 1)
        self.assertEqual(len(pcie["documented_vm_configurations"]), 4)
        self.assertEqual({v["gpu_variant"] for v in sxm["documented_vm_configurations"]}, {"SXM4"})
        self.assertEqual({v["gpu_variant"] for v in pcie["documented_vm_configurations"]}, {"PCIe"})

    def test_unknown_country_label_or_zone_never_uses_prefix_guess(self):
        with self.assertRaises(ValueError):
            crusoe_catalog.parse_locations(self.locations_html.replace("Virginia", "Unknown City"))
        with self.assertRaises(ValueError):
            crusoe_catalog.parse_vm_catalog(self.vms_html.replace("us-east2-a", "us-east9-a"), self.locations)

    def test_changed_columns_or_missing_table_fail_closed(self):
        for content in (self.vms_html.replace("Zones", "Pricing regions"),
                        self.vms_html.replace("GPU-enabled VMs", "Changed"),
                        self.vms_html.replace("17.5 Gbps", "")):
            with self.subTest(content=content[:80]), self.assertRaises(ValueError):
                crusoe_catalog.parse_vm_catalog(content, self.locations)

    def _fetch(self, url, settings):
        return {crusoe_catalog.SOURCE_URL: self.pricing_html,
                crusoe_catalog.VM_CATALOG_URL: self.vms_html,
                crusoe_catalog.LOCATIONS_URL: self.locations_html}[url]

    def test_collection_retains_source_prices_and_metadata_without_credentials(self):
        with patch.object(crusoe_catalog, "fetch_text", side_effect=self._fetch) as fetch:
            outcome = crusoe_catalog.collect_result(settings=Settings(), observed_at=OBSERVED_AT)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(outcome["coverage"]["public_price_cell_count"], 24)
        self.assertEqual(outcome["coverage"]["documented_vm_configuration_count"], 17)
        self.assertEqual(outcome["coverage"]["independent_regional_quote_count"], 0)
        self.assertFalse(outcome["uses_llm"])
        self.assertEqual(len(outcome["catalog_coverage"]["availability_catalog"]), 17)
        self.assertTrue(all(q["source_type"] == "official_pricing_page" for q in outcome["prices"]))

    def test_metadata_failure_does_not_erase_valid_prices(self):
        def fetch(url, settings):
            if url == crusoe_catalog.LOCATIONS_URL:
                raise FetchError("timeout", "The source timed out.", True)
            return self._fetch(url, settings)
        with patch.object(crusoe_catalog, "fetch_text", side_effect=fetch):
            outcome = crusoe_catalog.collect_result(settings=Settings(), observed_at=OBSERVED_AT)
        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(len(outcome["prices"]), 24)
        self.assertEqual({error["code"] for error in outcome["errors"]}, {"timeout", "dependency_failed"})
        self.assertEqual(outcome["catalog_coverage"]["availability_catalog"], [])
        self.assertTrue(all(not q["coverage_countries"] for q in outcome["prices"]))

    def test_price_failure_retains_non_price_vm_catalog_and_reports_failed(self):
        def fetch(url, settings):
            return "<h1>Access denied</h1>" if url == crusoe_catalog.SOURCE_URL else self._fetch(url, settings)
        with patch.object(crusoe_catalog, "fetch_text", side_effect=fetch):
            outcome = crusoe_catalog.collect_result(settings=Settings(), observed_at=OBSERVED_AT)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["prices"], [])
        self.assertEqual(len(outcome["catalog_coverage"]["availability_catalog"]), 17)
        self.assertEqual(outcome["errors"][0]["code"], "parse_failed")


if __name__ == "__main__":
    unittest.main()
