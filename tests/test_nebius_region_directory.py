"""Live country evidence must not be confused with capacity or billing currency."""

from copy import deepcopy
import unittest

from gpu_price_monitor.providers import nebius_regions


DIRECTORY = """# Nebius AI Cloud regions
## Public regions
Public regions are available to all Nebius users:
* `eu-north1`: Finland
* `eu-new1`: Marseille, France&#x20;
* `us-new1`: France
## Private regions
* `eu-north2`: Iceland
## Availability of platforms per region
"""
OBSERVED = "2026-10-22T03:40:00Z"


def quote(region="eu-new1"):
    return {"provider": "nebius", "billing_mode": "spot", "source_type": "official_public_api",
            "amount": "4.19", "currency": "USD", "unit": "gpu_hour", "regions": [region],
            "compute_countries": ["US"], "location": {"region": region, "country_code": "US"}}


class NebiusRegionDirectoryTests(unittest.TestCase):
    def test_new_regions_use_fresh_explicit_country_not_region_prefix(self):
        directory = nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED)
        self.assertEqual(directory["eu-new1"]["country_code"], "FR")
        self.assertEqual(directory["eu-new1"]["region_name"], "Marseille, France")
        self.assertEqual(directory["us-new1"]["country_code"], "FR")
        self.assertEqual(directory["eu-north1"]["country_name_zh"], "芬兰")
        self.assertTrue(directory["eu-north2"]["private_region"])
        self.assertEqual(directory["eu-new1"]["observed_at"], OBSERVED)
        self.assertEqual(len(directory["eu-new1"]["directory_sha256"]), 64)

    def test_enrichment_never_expands_one_api_quote_into_other_regions(self):
        original = quote()
        before = deepcopy(original)
        quotes, gaps = nebius_regions.attach_spot_locations([original], nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED))
        self.assertEqual(len(quotes), 1)
        self.assertEqual(gaps, [])
        self.assertEqual(quotes[0]["amount"], "4.19")
        self.assertEqual(quotes[0]["compute_countries"], ["FR"])
        self.assertEqual(quotes[0]["regions"], ["eu-new1"])
        self.assertEqual(quotes[0]["location_source"]["observed_at"], OBSERVED)
        self.assertEqual(original, before)

    def test_absent_or_unrecognized_country_is_not_replaced_with_stale_mapping(self):
        directory = nebius_regions.parse_directory(DIRECTORY.replace("Finland", "Unknownland"))
        for region in ("eu-north1", "us-future1"):
            quotes, gaps = nebius_regions.attach_spot_locations([quote(region)], directory)
            self.assertEqual(quotes[0]["compute_countries"], [])
            self.assertEqual(quotes[0]["location"], {"region": region})
            self.assertEqual(gaps[0]["status"], "country_not_verified")
            self.assertEqual(quotes[0]["amount"], "4.19")

    def test_private_region_access_is_explicit(self):
        quotes, _ = nebius_regions.attach_spot_locations([quote("eu-north2")], nebius_regions.parse_directory(DIRECTORY))
        self.assertEqual(quotes[0]["region_access"], "existing_deployments_only")
        self.assertEqual(quotes[0]["compute_countries"], ["IS"])

    def test_country_enrichment_rejects_coverage_or_non_api_rows(self):
        for mutation in ({"billing_mode": "on_demand"}, {"regions": []},
                         {"source_type": "official_pricing_document"}, {"regions": ["eu-new1", "us-new1"]}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                nebius_regions.attach_spot_locations([{**quote(), **mutation}], {})

    def test_missing_sections_and_duplicate_region_labels_fail_closed(self):
        for doc in (DIRECTORY.replace("## Public regions", "## Markets"),
                    DIRECTORY.replace("* `eu-north2`: Iceland", "* `eu-north1`: Iceland"),
                    "## Public regions\n## Private regions\n"):
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                nebius_regions.parse_directory(doc)


if __name__ == "__main__":
    unittest.main()
