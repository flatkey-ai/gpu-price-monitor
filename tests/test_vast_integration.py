"""Vast country evidence, exact geo filtering and partial coverage end to end."""

import json
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor import Settings, collect_prices, publishable_quote
from gpu_price_monitor.geography import describe_geography
from gpu_price_monitor.providers import vast

OBSERVED = "2026-10-23T07:39:02Z"


class VastIntegrationTests(unittest.TestCase):
    def responses(self, payload):
        def respond(url, settings, **kwargs):
            if url == vast.GPU_DIRECTORY_URL:
                return {"success": True, "gpu_names": sorted({r["gpu_name"] for r in payload["offers"]})}
            model = json.loads(kwargs["data"])["gpu_name"]["eq"]
            return {"offers": [r for r in payload["offers"] if r["gpu_name"] == model], "truncated": False}
        return respond

    def payload(self):
        return json.loads((Path(__file__).parent / "fixtures/vast-public-offers.json").read_text(), parse_float=Decimal)

    def test_country_only_never_becomes_region_and_filters_preserve_partial(self):
        payload = self.payload()
        row = payload["offers"][0]
        row["geolocation"] = "Czechia, CZ"
        payload["offers"] = [row]
        with patch.object(vast, "request_json", side_effect=self.responses(payload)):
            result = collect_prices(["vast"], {"compute_countries": ["CZ"]}, settings=Settings())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        q = result["prices"][0]
        self.assertEqual(q["compute_countries"], ["CZ"])
        self.assertEqual(q["regions"], [])
        self.assertEqual(q["price_scope"], "country_quote")
        self.assertFalse(q["region_price_verified"])
        self.assertFalse(publishable_quote(q))
        self.assertFalse(result["provider_results"][0]["catalog_coverage"]["complete"])
        with patch.object(vast, "request_json", side_effect=self.responses(payload)):
            regional = collect_prices(["vast"], {"compute_countries": ["CZ"], "regions": ["Czechia, CZ"]}, settings=Settings())
        self.assertEqual(regional["prices"], [])

    def test_regional_offer_can_pass_strict_filter_without_claiming_market_complete(self):
        payload = self.payload()
        row = payload["offers"][0]
        row["geolocation"] = "California, US"
        payload["offers"] = [row]
        with patch.object(vast, "request_json", side_effect=self.responses(payload)):
            result = collect_prices(["vast"], {"regions": ["California, US"], "compute_countries": ["US"]}, settings=Settings())
        self.assertEqual(result["status"], "partial")
        self.assertTrue(publishable_quote(result["prices"][0]))

    def test_country_scope_is_not_applied_to_untrusted_catalog(self):
        q = vast.parse_result(self.payload(), observed_at=OBSERVED)["prices"][0]
        q.update(regions=[], zones=[], geographic_scope="offer_country", source_url="https://untrusted.invalid/")
        describe_geography(q)
        self.assertEqual(q["price_scope"], "unlocated_catalog")
        self.assertEqual(q["compute_countries"], [])


if __name__ == "__main__":
    unittest.main()
