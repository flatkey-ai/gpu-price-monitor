"""Anonymous current API rates require fresh country metadata in this mode."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import nebius_spot_catalog as catalog
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-22T03:55:00Z"
DIRECTORY = """## Public regions
* `eu-north1`: Finland
* `us-new1`: France
## Private regions
* `eu-north2`: Iceland
"""


def quote(region="eu-north1"):
    return {"provider": "nebius", "source_type": "official_public_api", "source_url": catalog.SOURCE_URL,
            "gpu_model": "H200", "raw_sku": "gpu-h200-sxm", "amount": "2.0", "currency": "USD",
            "unit": "gpu_hour", "billing_mode": "spot", "quote_status": "quoted", "price_basis": "advertised_per_gpu",
            "regions": [region], "compute_countries": ["US"], "location": {"region": region, "country_code": "US"},
            "location_source": {"country_basis": "old_static_mapping"}, "observed_at": OBSERVED,
            "effective_from": "2026-10-22T03:51:00Z"}


class NebiusSpotCatalogTests(unittest.TestCase):
    @patch.object(catalog, "fetch_text", return_value=DIRECTORY)
    @patch.object(catalog.nebius_spot, "collect_quotes")
    def test_success_preserves_exact_api_rates_without_preset_expansion_and_refreshes_countries(self, api, fetch):
        original = [quote(), quote("us-new1")]
        api.return_value = deepcopy(original)
        result = catalog.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["coverage"]["reported_spot_api_quote_count"], 2)
        self.assertEqual(result["coverage"]["derived_preset_row_count"], 0)
        self.assertEqual(result["coverage"]["country_verified_spot_api_quote_count"], 2)
        self.assertEqual(result["prices"][0]["compute_countries"], ["FI"])
        self.assertEqual(result["prices"][1]["compute_countries"], ["FR"])
        self.assertEqual(result["prices"][1]["location"]["country_name_zh"], "法国")
        self.assertEqual([q["amount"] for q in result["prices"]], ["2.0", "2.0"])
        self.assertEqual(result["prices"][0]["effective_from"], original[0]["effective_from"])
        self.assertEqual(api.return_value, original)
        fetch.assert_called_once_with(catalog.REGIONS_URL, Settings())
        api.assert_called_once_with(settings=Settings(), observed_at=OBSERVED)

    @patch.object(catalog, "fetch_text", side_effect=FetchError("http_503", "unavailable", True))
    @patch.object(catalog.nebius_spot, "collect_quotes", return_value=[quote()])
    def test_directory_failure_keeps_api_amount_and_region_but_clears_historical_country(self, api, fetch):
        result = catalog.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["prices"][0]["amount"], "2.0")
        self.assertEqual(result["prices"][0]["regions"], ["eu-north1"])
        self.assertEqual(result["prices"][0]["compute_countries"], [])
        self.assertEqual(result["prices"][0]["location"], {"region": "eu-north1"})
        self.assertNotIn("old_static_mapping", str(result))
        self.assertEqual(result["coverage"]["country_verified_spot_api_quote_count"], 0)
        self.assertEqual(result["errors"][0]["code"], "http_503")
        with self.assertRaises(FetchError):
            catalog.collect_quotes(settings=Settings(), observed_at=OBSERVED)

    @patch.object(catalog, "fetch_text", return_value=DIRECTORY)
    @patch.object(catalog.nebius_spot, "collect_quotes", return_value=[quote("us-future1")])
    def test_new_api_region_absent_from_directory_has_gap_and_no_prefix_country_guess(self, api, fetch):
        result = catalog.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["prices"][0]["compute_countries"], [])
        self.assertEqual(result["prices"][0]["location"], {"region": "us-future1"})
        self.assertEqual(result["gaps"][0]["status"], "country_not_verified")
        self.assertEqual(result["errors"], [])

    @patch.object(catalog, "fetch_text", return_value="malformed directory")
    @patch.object(catalog.nebius_spot, "collect_quotes", return_value=[quote()])
    def test_directory_schema_change_cannot_fall_back_to_familiar_country(self, api, fetch):
        result = catalog.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"][0]["code"], "parse_failed")
        self.assertEqual(result["prices"][0]["compute_countries"], [])

    @patch.object(catalog, "fetch_text", return_value=DIRECTORY)
    @patch.object(catalog.nebius_spot, "collect_quotes", side_effect=FetchError("http_502", "upstream", True))
    def test_price_api_failure_does_not_manufacture_prices_from_location_directory(self, api, fetch):
        result = catalog.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["coverage"]["reported_spot_api_quote_count"], 0)
        self.assertEqual(result["errors"][0]["source"], "regional_spot_api")
        self.assertEqual(len(result["catalog_coverage"]["regions"]), 3)


if __name__ == "__main__":
    unittest.main()
