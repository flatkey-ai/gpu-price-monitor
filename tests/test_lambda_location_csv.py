"""Lambda shared catalog geography stays explicit without duplicating quotes."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest

from gpu_price_monitor.csv_export import (
    CATALOG_CSV_COLUMNS, MARKET_CSV_COLUMNS, catalog_eligible_record,
    market_eligible_quote, prices_to_csv, publishable_quote,
)
from gpu_price_monitor.providers import lambda_console, lambda_locations


FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-22T03:05:00+00:00"


def quote_with_locations(locations):
    payload = json.loads((FIXTURES / "lambda-console-instance-types-20261022.json").read_text())
    quote = lambda_console.parse_instance_prices(payload, observed_at=OBSERVED)[0]
    quote["capacity_locations"] = deepcopy(locations)
    quote["capacity_regions"] = [location["name"] for location in locations]
    return lambda_locations.enrich_price_applicability(quote)


def collection(*quotes):
    return {"status": "success", "collected_at": OBSERVED, "prices": list(quotes)}


def csv_rows(source, *, profile="market"):
    output = prices_to_csv(source, profile=profile, bilingual_headers=False)
    return list(csv.DictReader(io.StringIO(output.removeprefix("\ufeff"), newline="")))


class LambdaLocationCsvTests(unittest.TestCase):
    def test_two_us_regions_share_one_original_price_row_with_chinese_names_and_codes(self):
        quote = quote_with_locations([
            {"name": "us-east-3", "description": "Washington DC, USA"},
            {"name": "us-south-3", "description": "Central Texas, USA"},
        ])
        source = collection(quote)
        before = deepcopy(source)
        rows = csv_rows(source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), MARKET_CSV_COLUMNS)
        self.assertEqual(rows[0]["location"],
                         "统一目录价｜美国·华盛顿特区（us-east-3）、美国·得克萨斯州中部（us-south-3）")
        self.assertEqual(rows[0]["amount"], quote["amount"])
        self.assertEqual(rows[0]["currency"], "USD")
        self.assertEqual(rows[0]["unit"], "gpu_hour")
        self.assertEqual(rows[0]["source_url"], quote["source_url"])
        self.assertIn("同规格在所列可选地区共享目录价", rows[0]["pricing_conditions"])
        self.assertIn("非逐地区独立询价", rows[0]["pricing_conditions"])
        self.assertIn("不保证税费、合同与最终购买价", rows[0]["pricing_conditions"])
        self.assertNotIn("可选容量地区=", rows[0]["pricing_conditions"])
        self.assertEqual(source, before)
        self.assertEqual(quote["regions"], [])
        self.assertEqual(quote["compute_countries"], [])
        self.assertFalse(quote["region_price_verified"])
        self.assertFalse(publishable_quote(quote))
        self.assertEqual(csv_rows(source, profile="compact"), [])

    def test_cross_country_scope_names_each_location_without_nationwide_or_worldwide_claim(self):
        quote = quote_with_locations([
            {"name": "us-west-1", "description": "California, USA"},
            {"name": "asia-northeast-1", "description": "Osaka, Japan"},
            {"name": "europe-central-1", "description": "Germany"},
        ])
        location = csv_rows(collection(quote))[0]["location"]
        for expected in ("美国·加利福尼亚州（us-west-1）", "日本·大阪（asia-northeast-1）",
                         "德国·德国（官方未细分城市）（europe-central-1）"):
            self.assertIn(expected, location)
        for claim in ("全国", "全球", "所有地区", "适用地区未标明", "未公布"):
            self.assertNotIn(claim, location)

    def test_unknown_country_excludes_whole_sku_from_market_without_dropping_catalog_or_audit(self):
        quote = quote_with_locations([
            {"name": "us-west-1", "description": "California, USA"},
            {"name": "us-future-1", "description": "Location not identified by Lambda"},
        ])
        self.assertFalse(market_eligible_quote(quote))
        self.assertTrue(catalog_eligible_record(quote))
        self.assertEqual(csv_rows(collection(quote)), [])
        catalog = csv_rows(collection(quote), profile="catalog")
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["amount"], quote["amount"])
        self.assertIn("国家与价格适用信息待核实", catalog[0]["location"])
        full = csv_rows(collection(quote), profile="full")
        self.assertEqual(len(full), 1)
        self.assertEqual(json.loads(full[0]["extra_metadata_json"])["price_applicability"],
                         quote["price_applicability"])

    def test_empty_capacity_is_not_a_market_quote_but_remains_a_numeric_catalog_record(self):
        quote = quote_with_locations([])
        self.assertFalse(market_eligible_quote(quote))
        self.assertTrue(catalog_eligible_record(quote))
        self.assertEqual(csv_rows(collection(quote)), [])
        rows = csv_rows(collection(quote), profile="catalog")
        self.assertEqual(tuple(rows[0]), CATALOG_CSV_COLUMNS)
        self.assertEqual(rows[0]["location"], "统一目录价；当前无可选地区（无库存）")
        self.assertEqual(rows[0]["amount"], quote["amount"])
        self.assertEqual(len(csv_rows(collection(quote), profile="full")), 1)

    def test_dedicated_capacity_never_acquires_standard_directory_price_applicability(self):
        quote = quote_with_locations([
            {"name": "us-east-3", "description": "Washington DC, USA", "dedicated": True},
        ])
        self.assertFalse(market_eligible_quote(quote))
        self.assertEqual(csv_rows(collection(quote)), [])
        location = csv_rows(collection(quote), profile="catalog")[0]["location"]
        self.assertEqual(location, "统一目录价；当前无可选标准地区（私有地区价格待核实）")
        self.assertNotIn("无库存", location)
        self.assertNotIn("华盛顿", location)

    def test_dedicated_location_is_omitted_when_same_sku_has_selectable_standard_capacity(self):
        quote = quote_with_locations([
            {"name": "us-west-1", "description": "California, USA"},
            {"name": "asia-northeast-1", "description": "Osaka, Japan", "dedicated": True},
        ])
        row = csv_rows(collection(quote))[0]
        self.assertEqual(row["location"], "统一目录价｜美国·加利福尼亚州（us-west-1）")
        self.assertNotIn("日本", row["location"])
        self.assertNotIn("asia-northeast-1", row["pricing_conditions"])

    def test_capacity_alone_and_copied_applicability_from_other_sources_never_claim_shared_regions(self):
        original = quote_with_locations([{"name": "us-west-1", "description": "California, USA"}])
        for changes in ({"source_type": "public_page"}, {"provider": "nebius"}):
            quote = {**original, **changes}
            rows = csv_rows(collection(quote))
            self.assertEqual(len(rows), 1)
            self.assertNotIn("统一目录价", rows[0]["location"])
            self.assertNotIn("加利福尼亚", rows[0]["location"])
        without_metadata = deepcopy(original)
        without_metadata.pop("price_applicability")
        self.assertNotIn("统一目录价", csv_rows(collection(without_metadata))[0]["location"])

    def test_tampered_new_metadata_is_excluded_from_market_instead_of_silently_downgraded(self):
        original = quote_with_locations([{"name": "us-west-1", "description": "California, USA"}])
        for field, value in (("basis", "platform_coverage"), ("scope", "worldwide"),
                             ("independent_region_quotes", True), ("final_checkout_verified", True),
                             ("evidence", {})):
            quote = deepcopy(original)
            quote["price_applicability"][field] = value
            with self.subTest(field=field):
                self.assertFalse(market_eligible_quote(quote))
                self.assertEqual(csv_rows(collection(quote)), [])
                self.assertEqual(len(csv_rows(collection(quote), profile="full")), 1)
        quote = deepcopy(original)
        quote["price_applicability"]["locations"][0]["region"] = "us-east-3"
        self.assertFalse(market_eligible_quote(quote))
        quote = deepcopy(original)
        quote["price_applicability"]["locations"][0]["country_code"] = "JP"
        self.assertFalse(market_eligible_quote(quote))

    def test_unreviewed_current_frontend_never_publishes_a_shared_region_claim(self):
        quote = quote_with_locations([{"name": "us-west-1", "description": "California, USA"}])
        quote["price_applicability"]["verification_status"] = "frontend_version_unverified"
        self.assertFalse(market_eligible_quote(quote))
        self.assertEqual(csv_rows(collection(quote)), [])
        rows = csv_rows(collection(quote), profile="catalog")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], quote["amount"])
        self.assertNotIn("统一目录价", rows[0]["location"])
        self.assertNotIn("共享目录价", rows[0]["pricing_conditions"])

    def test_catalog_exception_does_not_admit_non_hourly_non_numeric_or_invalid_status_records(self):
        original = quote_with_locations([])
        for fields in ({"unit": "gpu_month"}, {"amount": "NaN"}, {"amount": None},
                       {"quote_status": "unknown"}, {"price_basis": "gpu_component"},
                       {"billing_mode": "yearly"}, {"product_type": "cpu_instance"}):
            quote = {**original, **fields}
            with self.subTest(fields=fields):
                self.assertFalse(catalog_eligible_record(quote))
                self.assertEqual(csv_rows(collection(quote), profile="catalog"), [])

    def test_reserved_cluster_uses_same_location_display_without_changing_gpu_rate_or_config(self):
        payload = json.loads((FIXTURES / "lambda-console-cluster-types-20261022.json").read_text())
        quote = lambda_console.parse_cluster_prices(payload, observed_at=OBSERVED)[0]
        before = deepcopy(quote)
        row = csv_rows(collection(quote))[0]
        self.assertEqual(row["amount"], "6.16")
        self.assertIn("集群共16卡", row["gpu_model"])
        self.assertIn("us-east-2", row["location"])
        self.assertIn("us-south-3", row["location"])
        self.assertIn("按周结算", row["pricing_conditions"])
        self.assertNotIn("Available regions", row["pricing_conditions"])
        self.assertNotIn("Duration limits", row["pricing_conditions"])
        self.assertEqual(quote, before)


if __name__ == "__main__":
    unittest.main()
