"""Shared console catalog applicability is separate from regional quotations."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from gpu_price_monitor.providers import lambda_console, lambda_locations


FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-22T02:00:00+00:00"


class LambdaLocationsTests(unittest.TestCase):
    def quote(self, locations=None, **updates):
        quote = {
            "provider": "lambda", "source_type": "official_internal_api",
            "source_url": lambda_console.INSTANCE_TYPES_URL,
            "account_scope": "authenticated_console_catalog",
            "product_type": "gpu_instance", "amount": "1.09", "currency": "USD",
            "unit": "gpu_hour", "regions": [], "compute_countries": [],
            "region_price_verified": False,
            "capacity_locations": [] if locations is None else locations,
        }
        quote.update(updates)
        return quote

    def test_all_eighteen_live_region_descriptions_have_explicit_country_mappings(self):
        payload = json.loads((FIXTURES / "lambda-console-regions-20261022.json").read_text())
        actual = {location["name"]: lambda_locations.describe_location(location)
                  for location in payload["data"]}
        self.assertEqual(len(actual), 18)
        expected = {
            "us-midwest-2": ("US", "美国", "俄亥俄州"),
            "europe-central-1": ("DE", "德国", "德国（官方未细分城市）"),
            "us-west-1": ("US", "美国", "加利福尼亚州"),
            "us-south-1": ("US", "美国", "得克萨斯州"),
            "asia-northeast-1": ("JP", "日本", "大阪"),
            "us-southeast-1": ("US", "美国", "佐治亚州"),
            "us-west-2": ("US", "美国", "亚利桑那州"),
            "australia-east-1": ("AU", "澳大利亚", "悉尼"),
            "asia-south-1": ("IN", "印度", "印度（官方未细分城市）"),
            "us-south-2": ("US", "美国", "得克萨斯州北部"),
            "us-south-3": ("US", "美国", "得克萨斯州中部"),
            "asia-northeast-2": ("JP", "日本", "东京"),
            "us-east-3": ("US", "美国", "华盛顿特区"),
            "us-east-1": ("US", "美国", "弗吉尼亚州"),
            "us-west-3": ("US", "美国", "犹他州"),
            "us-midwest-1": ("US", "美国", "伊利诺伊州"),
            "us-east-2": ("US", "美国", "华盛顿特区"),
            "me-west-1": ("IL", "以色列", "以色列（官方未细分城市）"),
        }
        for region, values in expected.items():
            item = actual[region]
            self.assertEqual((item["country_code"], item["country_name_zh"], item["region_name_zh"]), values)

    def test_official_description_overrides_any_region_prefix_assumption(self):
        item = lambda_locations.describe_location({"name": "us-east-1", "description": "Osaka, Japan"})
        self.assertEqual(item["country_code"], "JP")
        self.assertEqual(item["region_name_zh"], "大阪")

    def test_unfamiliar_description_is_preserved_without_country_prefix_guessing(self):
        location = {"name": "us-east-1", "description": "New provider location"}
        result = lambda_locations.enrich_price_applicability(self.quote([location]))
        item = result["price_applicability"]["locations"][0]
        self.assertEqual(item["description"], "New provider location")
        self.assertEqual(item["region_name_zh"], "New provider location")
        self.assertIsNone(item["country_code"])
        self.assertIsNone(item["country_name_zh"])
        self.assertEqual(result["applicable_countries"], [])
        self.assertEqual(result["applicable_regions"], ["us-east-1"])

    def test_dedicated_locations_do_not_inherit_standard_catalog_price(self):
        dedicated = {"name": "us-east-2", "description": "Washington DC, USA", "dedicated": True}
        standard = {"name": "asia-northeast-1", "description": "Osaka, Japan", "dedicated": False}
        quote = self.quote([dedicated, standard])
        before = deepcopy(quote)
        result = lambda_locations.enrich_price_applicability(quote)
        self.assertEqual(result["applicable_countries"], ["JP"])
        self.assertEqual(result["applicable_regions"], ["asia-northeast-1"])
        self.assertEqual(result["price_applicability"]["excluded_dedicated_locations"][0]["region"], "us-east-2")
        self.assertEqual(result["capacity_locations"], [dedicated, standard])
        self.assertEqual(quote, before)

    def test_empty_capacity_never_expands_to_all_platform_regions_or_countries(self):
        result = lambda_locations.enrich_price_applicability(self.quote())
        metadata = result["price_applicability"]
        self.assertEqual(metadata["locations"], [])
        self.assertEqual(result["applicable_regions"], [])
        self.assertEqual(result["applicable_countries"], [])
        self.assertEqual(metadata["scope"], "currently_selectable_standard_regions")
        self.assertEqual(metadata["location_status"], "no_currently_selectable_standard_regions")
        self.assertFalse(metadata["independent_region_quotes"])
        self.assertFalse(metadata["final_checkout_verified"])

    def test_enrichment_does_not_change_prices_or_independent_geography(self):
        quote = self.quote(
            [{"name": "us-east-2", "description": "Washington DC, USA"}],
            instance_price={"amount": "8.72", "currency": "USD", "unit": "instance_hour"},
            source_field_conflict=True,
        )
        before = deepcopy(quote)
        result = lambda_locations.enrich_price_applicability(quote)
        for field, value in before.items():
            self.assertEqual(result[field], value)
        result["capacity_locations"][0]["description"] = "Changed copy"
        self.assertEqual(quote, before)
        metadata = result["price_applicability"]
        self.assertEqual(metadata["basis"], "official_console_shared_sku_catalog")
        self.assertEqual(metadata["label_zh"], "所列可选地区统一目录价")
        self.assertEqual(metadata["evidence"]["source_url"], lambda_console.FRONTEND_SOURCE_URL)
        self.assertRegex(metadata["evidence"]["source_sha256"], r"^[0-9a-f]{64}$")

    def test_real_cluster_quotes_keep_exact_capacity_without_price_duplication(self):
        payload = json.loads((FIXTURES / "lambda-console-cluster-types-20261022.json").read_text())
        quotes = lambda_console.parse_cluster_prices(payload, observed_at=OBSERVED)
        self.assertEqual(len(quotes), 14)
        for raw, quote in zip(payload["data"], quotes):
            regions = [r["name"] for r in raw["regions_available"]]
            self.assertEqual(quote["applicable_regions"], regions)
            self.assertEqual(quote["applicable_countries"], ["US"])
            self.assertEqual(quote["capacity_locations"], raw["regions_available"])
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["compute_countries"], [])
            self.assertFalse(quote["region_price_verified"])
            self.assertTrue(quote["source_field_conflict"])
            self.assertIn("price_cents_per_gpu_hour", quote["price_applicability"]["evidence"]["price_display_basis"])

    def test_instance_quotes_only_include_each_exact_sku_capacity(self):
        payload = json.loads((FIXTURES / "lambda-console-instance-types-20261022.json").read_text())
        quotes = lambda_console.parse_instance_prices(payload, observed_at=OBSERVED)
        self.assertEqual(len(quotes), 22)
        for quote in quotes:
            locations = payload["data"][quote["raw_sku"]]["regions_with_capacity_available"]
            self.assertEqual(quote["capacity_locations"], locations)
            self.assertEqual(quote["applicable_regions"], [r["name"] for r in locations])
            self.assertEqual(quote["regions"], [])
            self.assertFalse(quote["region_price_verified"])

    def test_public_or_non_lambda_quotes_cannot_receive_console_shared_price_claim(self):
        for quote in (self.quote(source_type="public_page"), self.quote(provider="another"), None):
            with self.assertRaises(ValueError):
                lambda_locations.enrich_price_applicability(quote)

    def test_duplicate_regions_and_invalid_dedicated_flags_are_rejected(self):
        location = {"name": "us-east-2", "description": "Washington DC, USA"}
        for locations in ([location, location], [dict(location, dedicated="yes")]):
            with self.assertRaises(ValueError):
                lambda_locations.enrich_price_applicability(self.quote(locations))

    def test_validation_preserves_valid_empty_and_known_location_distinction(self):
        empty = lambda_locations.enrich_price_applicability(self.quote())
        self.assertEqual(lambda_locations.validated_applicability_locations(empty), [])
        known = lambda_locations.enrich_price_applicability(self.quote([
            {"name": "us-east-2", "description": "Washington DC, USA"},
        ]))
        self.assertEqual(lambda_locations.validated_applicability_locations(known),
                         known["price_applicability"]["locations"])

    def test_validation_unknown_country_can_only_match_explicit_region_filters(self):
        unknown = lambda_locations.enrich_price_applicability(self.quote([
            {"name": "us-new-1", "description": "New official location"},
        ]))
        self.assertIsNone(lambda_locations.validated_applicability_locations(unknown))
        locations = lambda_locations.validated_applicability_locations(unknown, require_country=False)
        self.assertEqual(locations[0]["region"], "us-new-1")
        self.assertIsNone(locations[0]["country_code"])

    def test_validation_rejects_incomplete_forged_or_contradictory_scope(self):
        original = lambda_locations.enrich_price_applicability(self.quote([
            {"name": "us-east-2", "description": "Washington DC, USA"},
            {"name": "asia-northeast-1", "description": "Osaka, Japan"},
        ]))
        mutations = [
            lambda q: q.update(provider="another"),
            lambda q: q.update(source_url="https://example.org/prices"),
            lambda q: q.update(source_url=[]),
            lambda q: q.update(product_type=[]),
            lambda q: q.update(source_type="public_page"),
            lambda q: q.update(account_scope="unknown"),
            lambda q: q.update(regions=["us-east-2"]),
            lambda q: q.update(compute_countries=["US"]),
            lambda q: q.update(region_price_verified=True),
            lambda q: q.update(applicable_countries=["US"]),
            lambda q: q.update(applicable_regions=["us-east-2"]),
            lambda q: q["price_applicability"].update(scope="all_worldwide_regions"),
            lambda q: q["price_applicability"].update(verification_status="frontend_version_unverified"),
            lambda q: q["price_applicability"].update(verification_status=[]),
            lambda q: q["price_applicability"].update(independent_region_quotes=True),
            lambda q: q["price_applicability"].update(final_checkout_verified=True),
            lambda q: q["price_applicability"].update(evidence={}),
            lambda q: q["price_applicability"]["evidence"].update(source_sha256="wrong"),
            lambda q: q["price_applicability"]["locations"].pop(),
            lambda q: q["price_applicability"]["locations"][0].update(country_code="JP"),
            lambda q: q["capacity_locations"][0].update(dedicated=True),
        ]
        for mutate in mutations:
            quote = deepcopy(original)
            mutate(quote)
            with self.subTest(quote=quote):
                self.assertIsNone(lambda_locations.validated_applicability_locations(quote))
        self.assertEqual(lambda_locations.validated_applicability_locations(original),
                         original["price_applicability"]["locations"])
        original["price_applicability"]["verification_status"] = "verified_current_frontend"
        self.assertEqual(lambda_locations.validated_applicability_locations(original),
                         original["price_applicability"]["locations"])


if __name__ == "__main__":
    unittest.main()
