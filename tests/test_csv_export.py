"""CSV price precision, provenance, conditions and spreadsheet-safe output."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest

from gpu_price_monitor.csv_export import (
    COMPACT_CSV_COLUMNS, COMPACT_CSV_HEADERS, CSV_COLUMNS, CSV_HEADERS,
    MARKET_CSV_COLUMNS, MARKET_CSV_HEADERS, market_eligible_quote, prices_to_csv, publishable_quote,
)


def quote(**overrides):
    return {
        "provider": "nebius", "product_type": "gpu_instance", "gpu_model": "B300",
        "gpu_variant": "SXM6", "vram_gb": 288, "gpu_count": None,
        "raw_name": "NVIDIA B300", "raw_sku": "gpu-b300-sxm",
        "amount": "9.500000000000000000000000000123400", "currency": "USD",
        "unit": "gpu_hour", "billing_mode": "on_demand", "price_basis": "advertised_per_gpu",
        "quote_status": "quoted", "regions": [], "zones": [], "compute_countries": [],
        "price_scope": "unlocated_catalog", "region_price_verified": False,
        "availability": "unknown", "account_scope": "public_catalog", "tax_scope": "unspecified",
        "source_url": "https://example.com/prices", "source_type": "public_page",
        "observed_at": "2026-10-21T07:12:32.449168+00:00", "notes": [], **overrides,
    }


def result(*prices, status="success"):
    return {"schema_version": 1, "collected_at": "2026-10-21T07:12:56.913219+00:00",
            "status": status, "prices": list(prices), "provider_results": []}


def english_csv(source):
    return prices_to_csv(source, bilingual_headers=False, profile="full")


def rows(text):
    return list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline="")))


class CsvExportTests(unittest.TestCase):
    def test_default_headers_translate_every_stable_english_column(self):
        output = prices_to_csv(result(quote()), profile="full")
        self.assertTrue(output.startswith("\ufeffprovider（平台）,"))
        self.assertEqual(tuple(next(csv.reader(io.StringIO(output[1:], newline="")))), CSV_HEADERS)
        self.assertIsInstance(CSV_HEADERS, tuple)
        self.assertEqual(len(CSV_HEADERS), len(CSV_COLUMNS))
        self.assertEqual(len(set(CSV_HEADERS)), len(CSV_COLUMNS))
        for column, header in zip(CSV_COLUMNS, CSV_HEADERS):
            self.assertTrue(header.startswith(column + "（"), header)
            self.assertTrue(header.endswith("）"), header)
            self.assertRegex(header, r"[\u4e00-\u9fff]", header)
        expected = {
            "provider": "provider（平台）", "gpu_model": "gpu_model（GPU型号）",
            "amount": "amount（原币单GPU价格）", "currency": "currency（原币币种）",
            "unit": "unit（计费单位）", "regions": "regions（地区）", "zones": "zones（可用区）",
            "collected_at": "collected_at（本批采集时间）", "collection_status": "collection_status（本批采集状态）",
        }
        self.assertEqual({column: CSV_HEADERS[CSV_COLUMNS.index(column)] for column in expected}, expected)
        self.assertEqual(tuple(rows(output)[0]), CSV_HEADERS)
        self.assertEqual(rows(output)[0]["amount（原币单GPU价格）"], quote()["amount"])

    def test_header_option_only_changes_header_not_quote_rows_or_input(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "nine-providers-2026-10-21.json"
        source = json.loads(path.read_text())
        before = deepcopy(source)
        bilingual = prices_to_csv(source, profile="full")
        english = prices_to_csv(source, bilingual_headers=False, profile="full")
        self.assertEqual(bilingual.partition("\r\n")[2], english.partition("\r\n")[2])
        self.assertEqual(len(rows(bilingual)), len(source["prices"]))
        self.assertEqual(tuple(rows(english)[0]), CSV_COLUMNS)
        self.assertEqual(source, before)
        empty = prices_to_csv(result(), profile="full")
        self.assertEqual(tuple(next(csv.reader(io.StringIO(empty[1:], newline="")))), CSV_HEADERS)
        self.assertEqual(rows(empty), [])

    def test_bilingual_headers_requires_an_actual_boolean_and_is_keyword_only(self):
        for value in (None, 0, 1, "false", "true", [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "bilingual_headers must be boolean"):
                prices_to_csv(result(quote()), bilingual_headers=value)
        self.assertEqual(prices_to_csv(result(), bilingual_headers=True), prices_to_csv(result()))
        with self.assertRaises(TypeError):
            prices_to_csv(result(), False)

    def test_fixed_columns_bom_crlf_and_exact_native_decimals_without_conversion(self):
        source = result(quote(), quote(provider="verda", currency="EUR", amount="7.3030"),
                        quote(provider="nebius", currency="ILS", amount="29.450000"))
        output = english_csv(source)
        self.assertTrue(output.startswith("\ufeffprovider,"))
        self.assertTrue(output.endswith("\r\n"))
        self.assertEqual(output.encode("utf-8")[:3], b"\xef\xbb\xbf")
        self.assertNotIn("\n", output.replace("\r\n", ""))
        self.assertEqual(tuple(next(csv.reader(io.StringIO(output[1:], newline="")))), CSV_COLUMNS)
        self.assertEqual(len(CSV_COLUMNS), 51)
        self.assertEqual(len(set(CSV_COLUMNS)), len(CSV_COLUMNS))
        actual = rows(output)
        self.assertEqual([row["amount"] for row in actual], [q["amount"] for q in source["prices"]])
        self.assertEqual([row["currency"] for row in actual], ["USD", "EUR", "ILS"])
        self.assertEqual(actual[0]["gpu_count"], "")
        self.assertEqual(actual[0]["availability"], "unknown")
        self.assertEqual(actual[0]["tax_scope"], "unspecified")
        self.assertEqual(actual[0]["region_price_verified"], "false")
        self.assertFalse(any("usd_amount" in column or "exchange" in column for column in CSV_COLUMNS))

    def test_monthly_offline_and_contact_sales_preserve_period_and_nulls(self):
        monthly = quote(provider="ucloud", amount="467.7900", currency="CNY", unit="gpu_month",
                        billing_mode="monthly", gpu_count=4, availability="offline",
                        instance_price={"amount": "1871.1600", "currency": "CNY", "unit": "instance_month", "original_amount": "16681"},
                        promotion={"only_new_users": False, "purchase_limit": 3, "eligibility_verified": False})
        sales = quote(provider="crusoe", amount=None, quote_status="contact_sales", gpu_variant=None, vram_gb=None)
        actual = rows(english_csv(result(monthly, sales, quote(amount="0.0000"))))
        self.assertEqual((actual[0]["amount"], actual[0]["currency"], actual[0]["unit"], actual[0]["availability"]),
                         ("467.7900", "CNY", "gpu_month", "offline"))
        self.assertEqual((actual[0]["instance_amount"], actual[0]["instance_unit"], actual[0]["instance_original_amount"]),
                         ("1871.1600", "instance_month", "16681"))
        self.assertEqual(json.loads(actual[0]["promotion_json"]), monthly["promotion"])
        self.assertEqual(actual[1]["amount"], "")
        self.assertEqual(actual[1]["instance_amount"], "")
        self.assertEqual(actual[1]["vram_gb"], "")
        self.assertEqual(actual[1]["quote_status"], "contact_sales")
        self.assertEqual(actual[2]["amount"], "0.0000")

    def test_member_cloud_tier_spot_and_account_conditions_are_separate_rows(self):
        source = result(
            quote(provider="autodl", currency="CNY", pricing_tier="member", membership_required=True, membership_discount="0.95"),
            quote(provider="autodl", currency="CNY", pricing_tier="ordinary", membership_required=False),
            quote(provider="runpod", cloud_tier="secure"),
            quote(provider="runpod", cloud_tier="community"),
            quote(provider="azure", billing_mode="spot", conditions={"purchase_option": "spot"}),
            quote(account_scope="account_contract_quote", minimum_commitment={"months": 12}),
        )
        actual = rows(english_csv(source))
        self.assertEqual(len(actual), len(source["prices"]))
        self.assertEqual([row["membership_required"] for row in actual[:2]], ["true", "false"])
        self.assertEqual(actual[0]["membership_discount"], "0.95")
        self.assertEqual([row["cloud_tier"] for row in actual[2:4]], ["secure", "community"])
        self.assertEqual(actual[4]["billing_mode"], "spot")
        self.assertEqual(json.loads(actual[4]["conditions_json"]), {"purchase_option": "spot"})
        self.assertEqual(actual[5]["account_scope"], "account_contract_quote")
        self.assertEqual(json.loads(actual[5]["minimum_commitment_json"]), {"months": 12})

    def test_country_region_and_zone_evidence_is_copied_without_inference(self):
        coverage = quote(regions=["eu-west2", "us-north1"], price_scope="platform_coverage")
        regional = quote(provider="azure", regions=["westus3"], price_scope="regional_quote",
                         region_price_verified=True, compute_countries=["US"],
                         location_source={"url": "https://learn.microsoft.com/en-us/azure/reliability/regions-list"})
        zonal = quote(provider="ucloud", regions=["cn-bj2"], zones=["cn-bj2-02"],
                      compute_countries=["CN"], price_scope="zone_quote", region_price_verified=True,
                      location={"country_code": "CN", "zone_name": "北京可用区 B"})
        actual = rows(english_csv(result(coverage, regional, zonal)))
        self.assertEqual(actual[0]["compute_countries"], "")
        self.assertEqual(json.loads(actual[0]["regions"]), coverage["regions"])
        self.assertEqual((actual[0]["price_scope"], actual[0]["region_price_verified"]), ("platform_coverage", "false"))
        self.assertEqual(json.loads(actual[1]["compute_countries"]), ["US"])
        self.assertEqual(json.loads(actual[1]["location_source_json"]), regional["location_source"])
        self.assertEqual(json.loads(actual[2]["zones"]), ["cn-bj2-02"])
        self.assertEqual(json.loads(actual[2]["location_json"]), zonal["location"])

    def test_unicode_quotes_commas_and_embedded_newlines_round_trip(self):
        name = "华北, \"促销\" GPU\r\n第二行\n第三行"
        source = result(quote(raw_name=name, notes=["中文, \"来源\"\n说明"], resources={"memory_gib": 900, "disk": "SSD, NVMe"}))
        actual = rows(english_csv(source))[0]
        self.assertEqual(actual["raw_name"], name)
        self.assertEqual(json.loads(actual["notes_json"]), source["prices"][0]["notes"])
        self.assertEqual(json.loads(actual["resources_json"]), source["prices"][0]["resources"])

    def test_text_formula_injection_is_a_literal_but_decimal_prices_are_unchanged(self):
        dangerous = ["=1+1", "+cmd", "-cmd", "@SUM(1,2)", " \t=HYPERLINK(\"bad\")", "\n=1", "\r@SUM(1)", "\ufeff=1", "\ttext"]
        for value in dangerous:
            with self.subTest(value=value):
                actual = rows(english_csv(result(quote(raw_name=value, raw_sku=value, source_url=value))))[0]
                self.assertEqual(actual["raw_name"], "'" + value)
                self.assertEqual(actual["raw_sku"], "'" + value)
                self.assertEqual(actual["source_url"], "'" + value)
                self.assertEqual(actual["amount"], quote()["amount"])
        for value in ("+1.2300", "0.00000000000000000001", "1.234567890123456789E-12"):
            with self.subTest(amount=value):
                self.assertEqual(rows(english_csv(result(quote(amount=value))))[0]["amount"], value)

    def test_partial_status_timestamps_extra_evidence_and_input_identity_remain(self):
        source = result(quote(api_source_url="https://api.example.com/", azure_meter={"meter_id": "one"},
                              selected_configuration={"gpu_count": 8}, source_conditions={"offer_types": ["contract"]}), status="partial")
        before = deepcopy(source)
        actual = rows(english_csv(source))[0]
        self.assertEqual(actual["collected_at"], source["collected_at"])
        self.assertEqual(actual["observed_at"], source["prices"][0]["observed_at"])
        self.assertEqual(actual["collection_status"], "partial")
        self.assertEqual(json.loads(actual["extra_metadata_json"]), {
            "api_source_url": "https://api.example.com/", "azure_meter": {"meter_id": "one"}, "source_conditions": {"offer_types": ["contract"]}})
        self.assertEqual(json.loads(actual["selected_configuration_json"]), {"gpu_count": 8})
        self.assertEqual(source, before)

    def test_empty_collection_has_header_only_without_fake_quote(self):
        for source in (result(), result(status="failed")):
            with self.subTest(source=source):
                output = english_csv(source)
                self.assertEqual(rows(output), [])
                self.assertEqual(output.count("\r\n"), 1)

    def test_malformed_prices_fail_without_exposing_or_coercing_upstream_values(self):
        for value in (1.25, -1, True, "NaN", "Infinity", "-1.00", "=private_upstream_text", "+SUM(1)"):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                english_csv(result(quote(amount=value)))
            self.assertNotIn("private_upstream_text", str(error.exception))
        for value in (None, [], {}, {"status": "success"}, {"prices": {}}, {"prices": [None]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                english_csv(value)

    def test_real_nine_provider_example_retains_every_quote_amount_and_condition(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "nine-providers-2026-10-21.json"
        source = json.loads(path.read_text())
        before = deepcopy(source)
        actual = rows(english_csv(source))
        self.assertEqual(len(actual), len(source["prices"]))
        self.assertEqual(len({row["provider"] for row in actual}), 9)
        for price, row in zip(source["prices"], actual):
            self.assertEqual(row["amount"], price["amount"] if price["amount"] is not None else "")
            for field in ("provider", "currency", "unit", "billing_mode", "availability", "source_url"):
                self.assertEqual(row[field], price[field])
            for field in ("compute_countries", "regions", "zones"):
                self.assertEqual(json.loads(row[field]) if row[field] else [], price.get(field, []))
        self.assertEqual(source, before)


def regional_quote(**overrides):
    return quote(**{
        "provider": "azure", "regions": ["westus3"], "compute_countries": ["US"],
        "price_scope": "regional_quote", "region_price_verified": True, **overrides,
    })


class CompactCsvExportTests(unittest.TestCase):
    def compact_rows(self, source, **options):
        return rows(prices_to_csv(source, bilingual_headers=False, profile="compact", **options))

    def test_compact_keeps_ten_bilingual_columns_and_full_remains_opt_in(self):
        source = result(regional_quote())
        output = prices_to_csv(source, profile="compact")
        self.assertEqual(tuple(next(csv.reader(io.StringIO(output[1:], newline="")))), COMPACT_CSV_HEADERS)
        self.assertEqual(COMPACT_CSV_COLUMNS, (
            "gpu_model", "provider", "location", "amount", "currency", "unit",
            "pricing_conditions", "availability", "source_url", "observed_at",
        ))
        self.assertEqual(len(COMPACT_CSV_HEADERS), 10)
        self.assertEqual(len(CSV_COLUMNS), 51)
        self.assertEqual(tuple(self.compact_rows(source)[0]), COMPACT_CSV_COLUMNS)
        self.assertEqual(output, prices_to_csv(source, profile="compact"))
        self.assertEqual(output.partition("\r\n")[2], prices_to_csv(source, bilingual_headers=False, profile="compact").partition("\r\n")[2])
        self.assertTrue(output.startswith("\ufeffgpu_model（"))
        self.assertTrue(output.endswith("\r\n"))

    def test_gpu_configuration_keeps_variant_cards_cpu_ram_and_source_units(self):
        source = result(
            regional_quote(gpu_count=8, resources={"vcpus": 208, "memory_gib": 2900, "storage": {"amount": "22", "unit": "TiB", "type": "SSD"}}),
            regional_quote(provider="ucloud", resources={"vcpu_count": 32, "memory_mb": 131072, "disk_gb": 100}),
            regional_quote(provider="autodl", resources={"allocation_scope": "per_gpu", "cpu_cores_per_gpu": "12", "memory_per_gpu": {"amount": "60", "unit": "GB"}}),
        )
        actual = self.compact_rows(source)
        for text in ("B300", "SXM6", "288GB/卡", "8卡", "208 vCPU", "2900 GiB RAM", "22 TiB SSD", "gpu-b300-sxm"):
            self.assertIn(text, actual[0]["gpu_model"])
        self.assertIn("131072 MB RAM", actual[1]["gpu_model"])
        self.assertIn("100GB", actual[1]["gpu_model"].replace(" ", ""))
        self.assertNotIn("128 GiB", actual[1]["gpu_model"])
        self.assertIn("12 CPU核/卡", actual[2]["gpu_model"])
        self.assertIn("60 GB RAM/卡", actual[2]["gpu_model"])
        self.assertNotIn("8卡", actual[2]["gpu_model"])

    def test_unknown_coverage_and_capacity_never_become_regional_prices(self):
        source = result(
            quote(),
            regional_quote(regions=[], coverage_regions=["eu-north1"], coverage_countries=["FI"], price_scope="platform_coverage"),
            regional_quote(regions=["us-central1"], price_scope="platform_coverage"),
            quote(provider="lambda", capacity_regions=["us-west-1"]),
            regional_quote(provider="azure", regions=["westus3"], compute_countries=["US"], region_price_verified=False),
        )
        self.assertEqual(self.compact_rows(source), [])
        self.assertEqual(len(rows(english_csv(source))), 5)
        self.assertTrue(all(not publishable_quote(item) for item in source["prices"]))

    def test_regional_and_requested_quotes_preserve_country_region_and_zone(self):
        actual = self.compact_rows(result(
            regional_quote(provider="ucloud", regions=["cn-bj2"], zones=["cn-bj2-02"], compute_countries=["CN"],
                  price_scope="zone_quote", region_price_verified=True, location={"zone_name": "北京可用区 B"}),
            regional_quote(regions=["eu-north1"], compute_countries=["FI"], price_scope="requested_region_quote", region_price_verified=True),
        ))
        for text in ("国家=CN", "地区=cn-bj2", "可用区=cn-bj2-02", "北京可用区 B"):
            self.assertIn(text, actual[0]["location"])
        self.assertIn("请求配置询价地区", actual[1]["location"])
        self.assertIn("国家=FI", actual[1]["location"])
        self.assertNotIn("平台覆盖", actual[1]["location"])

    def test_conditions_keep_member_cloud_actual_spot_account_and_tax(self):
        source = result(
            regional_quote(provider="autodl", pricing_tier="ordinary", membership_required=False),
            regional_quote(provider="autodl", pricing_tier="member", membership_required=True, membership_discount="0.95", ordinary_price_amount="3.8000"),
            regional_quote(provider="runpod", cloud_tier="secure", conditions={"cloud_type": "secure_cloud"}),
            regional_quote(provider="runpod", cloud_tier="community"),
            regional_quote(billing_mode="spot", effective_from="2026-10-21T08:15:00+00:00"),
            regional_quote(price_basis="instance_total_allocated", tax_scope="excluded", notes=["USD prices apply to customers except companies from Israel."]),
            regional_quote(account_scope="account_contract_quote", source_conditions={"offer_types": ["contract"]}, minimum_commitment={"months": 12}),
            regional_quote(billing_mode="spot", quote_status="starting_at", price_basis="starting_price"),
            regional_quote(price_basis="gpu_component"),
        )
        actual = self.compact_rows(source)
        self.assertIn("普通用户", actual[0]["pricing_conditions"])
        self.assertIn("无需会员", actual[0]["pricing_conditions"])
        for text in ("会员", "需会员", "会员折扣=0.95", "普通用户每GPU原币金额=3.8000"):
            self.assertIn(text, actual[1]["pricing_conditions"])
        self.assertIn("云档位=secure", actual[2]["pricing_conditions"])
        self.assertIn("secure_cloud", actual[2]["pricing_conditions"])
        self.assertIn("云档位=community", actual[3]["pricing_conditions"])
        self.assertIn("Spot", actual[4]["pricing_conditions"])
        self.assertIn("2026-10-21T08:15:00+00:00", actual[4]["pricing_conditions"])
        self.assertNotIn("起步价", actual[4]["pricing_conditions"])
        self.assertEqual(len(actual), 7)
        for text in ("整机价按卡分摊", "未含税", "Israel"):
            self.assertIn(text, actual[5]["pricing_conditions"])
        for text in ("账号合同价", '"months":12', '"offer_types":["contract"]'):
            self.assertIn(text, actual[6]["pricing_conditions"])

    def test_hourly_instance_amounts_promotions_and_zero_remain_monthly_contact_offline_are_excluded(self):
        monthly = regional_quote(provider="ucloud", amount="467.7900", currency="CNY", unit="gpu_month", billing_mode="monthly",
                        price_basis="instance_total_allocated", availability="offline",
                        instance_price={"amount": "1871.1600", "original_amount": "16681.0000", "currency": "CNY", "unit": "instance_month"},
                        promotion={"only_new_users": False, "purchase_limit": 3, "eligibility_verified": False})
        hourly = {**monthly, "unit": "gpu_hour", "billing_mode": "on_demand", "availability": "unknown",
                  "instance_price": {**monthly["instance_price"], "unit": "instance_hour"}}
        source = result(hourly, regional_quote(amount="0.0000"), monthly,
                        regional_quote(provider="crusoe", amount=None, quote_status="contact_sales"),
                        regional_quote(availability="offline"))
        actual = self.compact_rows(source)
        self.assertEqual(len(actual), 2)
        self.assertEqual([row["amount"] for row in actual], ["467.7900", "0.0000"])
        self.assertEqual((actual[0]["currency"], actual[0]["unit"], actual[0]["availability"]), ("CNY", "gpu_hour", "unknown"))
        for text in ("按需", "整机价按卡分摊", "1871.1600 CNY instance_hour", "16681.0000 CNY instance_hour", '"purchase_limit":3', '"eligibility_verified":false'):
            self.assertIn(text, actual[0]["pricing_conditions"])
        self.assertNotIn("整实例总价", actual[1]["pricing_conditions"])
        self.assertEqual(len(rows(english_csv(source))), 5)

    def test_publishable_requires_all_explicit_price_location_and_numeric_evidence(self):
        self.assertTrue(publishable_quote(regional_quote()))
        self.assertTrue(publishable_quote(regional_quote(amount="0.0000")))
        for overrides in (
            {"unit": "gpu_month"}, {"amount": None}, {"amount": "NaN"}, {"amount": 1.0},
            {"quote_status": "contact_sales"}, {"quote_status": "starting_at"}, {"price_basis": "starting_price"}, {"price_basis": "gpu_component"},
            {"price_scope": "platform_coverage"}, {"price_scope": "unlocated_catalog"},
            {"region_price_verified": False}, {"region_price_verified": 1},
            {"compute_countries": []}, {"compute_countries": ["us"]}, {"compute_countries": ["USA"]},
            {"compute_countries": ["US", ""]}, {"compute_countries": "US"},
            {"regions": []}, {"regions": [""]}, {"regions": "westus3"},
            {"availability": "offline"}, {"availability": "ended"}, {"availability": "upcoming"}, {"availability": "unavailable"},
        ):
            with self.subTest(overrides=overrides):
                item = regional_quote(**overrides)
                self.assertFalse(publishable_quote(item))
                self.assertEqual(self.compact_rows(result(item)), [])
        for value in (None, [], "quoted"):
            self.assertFalse(publishable_quote(value))

    def test_native_decimals_iso_time_formula_protection_and_input_identity(self):
        source = result(regional_quote(gpu_model="=1+1", source_url="\t=HYPERLINK(bad)", amount="+1.234567890123456789E-12", currency="EUR"), status="partial")
        before = deepcopy(source)
        row = self.compact_rows(source)[0]
        self.assertTrue(row["gpu_model"].startswith("'=1+1"))
        self.assertEqual(row["source_url"], "'\t=HYPERLINK(bad)")
        self.assertEqual(row["amount"], source["prices"][0]["amount"])
        self.assertEqual(row["currency"], "EUR")
        self.assertEqual(row["observed_at"], source["prices"][0]["observed_at"])
        self.assertIn("采集状态=partial", row["pricing_conditions"])
        self.assertEqual(source, before)

    def test_invalid_profile_and_invalid_instance_amount_fail_safely(self):
        for profile in (None, "", "wide", 10, [], {}):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "profile must be market, compact or full"):
                prices_to_csv(result(), profile=profile)
        for value in (1.5, "NaN", "-1", "=private_upstream_text"):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                self.compact_rows(result(regional_quote(instance_price={"amount": value})))
            self.assertNotIn("private_upstream_text", str(error.exception))
        with self.assertRaisesRegex(ValueError, "instance prices must be objects"):
            self.compact_rows(result(regional_quote(instance_price=[])))

    def test_real_nine_provider_example_preserves_rows_amounts_and_provenance(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "nine-providers-2026-10-21.json"
        source = json.loads(path.read_text())
        before = deepcopy(source)
        actual = self.compact_rows(source)
        eligible = [price for price in source["prices"] if publishable_quote(price)]
        self.assertEqual(len(actual), len(eligible))
        self.assertGreater(len(actual), 0)
        self.assertLess(len(actual), len(source["prices"]))
        self.assertIn("azure", {row["provider"] for row in actual})
        for price, row in zip(eligible, actual):
            self.assertEqual(row["amount"], price["amount"] if price["amount"] is not None else "")
            for field in ("provider", "currency", "unit", "availability", "source_url", "observed_at"):
                self.assertEqual(row[field], price[field])
            self.assertEqual(row["unit"], "gpu_hour")
            self.assertIn("国家=", row["location"])
            self.assertIn("地区=", row["location"])
            if price.get("instance_price", {}).get("amount") is not None:
                self.assertIn(price["instance_price"]["amount"], row["pricing_conditions"])
        self.assertEqual(source, before)
        empty = prices_to_csv(result())
        self.assertEqual(rows(empty), [])
        self.assertEqual(empty.count("\r\n"), 1)


class MarketCsvExportTests(unittest.TestCase):
    def market_rows(self, source):
        return rows(prices_to_csv(source, bilingual_headers=False, profile="market"))

    def test_compute_rate_and_additional_disk_cost_remain_separate_in_both_profiles(self):
        item = regional_quote(
            amount="8.50000000", gpu_count=8,
            instance_price={"amount": "68.00000000", "currency": "USD", "unit": "instance_hour",
                            "scope": "compute_resources_only"},
            storage_quote={"amount": "0.00388888", "currency": "USD", "unit": "disk_hour",
                           "included_in_main_gpu_price": False},
            full_configuration_price={"amount": "68.00388888", "currency": "USD", "unit": "instance_hour"},
        )
        source = result(item)
        before = deepcopy(source)
        for profile in ("market", "compact"):
            with self.subTest(profile=profile):
                row = rows(prices_to_csv(source, bilingual_headers=False, profile=profile))[0]
                self.assertEqual(row["amount"], "8.50000000")
                self.assertIn("实例计算资源小时费=68.00000000 USD instance_hour", row["pricing_conditions"])
                self.assertNotIn("整实例总价=68.00000000", row["pricing_conditions"])
                self.assertIn("另计磁盘小时费=0.00388888 USD disk_hour", row["pricing_conditions"])
                self.assertIn("计算资源加磁盘每实例小时合计=68.00388888 USD instance_hour", row["pricing_conditions"])
        self.assertEqual(source, before)
        full_row = rows(english_csv(source))[0]
        extra = json.loads(full_row["extra_metadata_json"])
        self.assertEqual(extra["storage_quote"], item["storage_quote"])
        self.assertEqual(extra["full_configuration_price"], item["full_configuration_price"])

    def test_invalid_supplemental_amounts_fail_without_echoing_input(self):
        for field in ("storage_quote", "full_configuration_price"):
            for value in ({"amount": "=private_upstream_value"}, {"amount": "-1"}, [], "invalid"):
                for profile in ("market", "compact"):
                    with self.subTest(field=field, value=value, profile=profile), self.assertRaises(ValueError) as error:
                        prices_to_csv(result(regional_quote(instance_price={"amount": "8.5"}, **{field: value})), profile=profile)
                    self.assertNotIn("private_upstream_value", str(error.exception))

    def test_discovered_compute_market_summary_keeps_restrictions_and_omits_request_dtos(self):
        item = regional_quote(
            instance_price={"amount": "9.5", "scope": "compute_resources_only"},
            catalog_discovery={"method": "authenticated_tenant_project_platform_list"},
            conditions=["普通报价仅含VM计算费（GPU、CPU、RAM），按GPU数量分摊。",
                        "40 GiB SSD额外0.0039 USD/小时；实例加盘总额9.5039 USD/小时。",
                        "盘费来自同批独立CreateDiskRequest；不创建资源。",
                        "项目API已核实部署地区；逐项目询价。", "仅适用于现有账号；网络与税费未验证。"],
            selected_configuration={"preset": "1gpu-24vcpu-346gb", "boot_disk_gib": 40},
            requested_configuration={"resource_specs": [{"type": "CreateInstanceRequest"}]},
        )
        source = result(item)
        before = deepcopy(source)
        row = self.market_rows(source)[0]
        conditions = row["pricing_conditions"]
        self.assertIn("含GPU/CPU/RAM计算费；磁盘与网络另计", conditions)
        self.assertIn("仅适用于现有账号；网络与税费未验证。", conditions)
        self.assertIn("规格=1gpu-24vcpu-346gb；另配SSD=40 GiB", conditions)
        self.assertNotIn("CreateDiskRequest", conditions)
        self.assertNotIn("CreateInstanceRequest", conditions)
        self.assertEqual(json.loads(rows(english_csv(source))[0]["extra_metadata_json"])["requested_configuration"], item["requested_configuration"])
        self.assertEqual(source, before)

    def test_default_market_has_ten_columns_and_keeps_catalog_and_regional_quotes(self):
        source = result(quote(provider="lambda"), regional_quote())
        before = deepcopy(source)
        output = prices_to_csv(source)
        self.assertEqual(output, prices_to_csv(source, profile="market"))
        self.assertEqual(tuple(next(csv.reader(io.StringIO(output[1:], newline="")))), MARKET_CSV_HEADERS)
        self.assertEqual(MARKET_CSV_COLUMNS, COMPACT_CSV_COLUMNS)
        self.assertEqual(len(MARKET_CSV_COLUMNS), 10)
        self.assertIn("location（报价适用范围）", MARKET_CSV_HEADERS)
        self.assertEqual(len(rows(output)), 2)
        self.assertEqual(len(rows(prices_to_csv(source, profile="compact"))), 1)
        self.assertEqual(len(rows(english_csv(source))), 2)
        self.assertEqual(output.partition("\r\n")[2],
                         prices_to_csv(source, bilingual_headers=False).partition("\r\n")[2])
        self.assertTrue(output.startswith("\ufeff"))
        self.assertTrue(output.endswith("\r\n"))
        self.assertEqual(source, before)

    def test_catalog_geography_is_unstated_despite_currency_coverage_capacity_or_country(self):
        source = result(
            quote(provider="autodl", currency="CNY"),
            quote(provider="lambda", capacity_regions=["us-west-1"], account_scope="authenticated_catalog"),
            quote(price_scope="platform_coverage", coverage_regions=["eu-north1"],
                  coverage_countries=["FI"], regions=["eu-north1"], compute_countries=["FI"]),
        )
        actual = self.market_rows(source)
        self.assertEqual(actual[0]["location"], "公开目录报价；适用地区未标明（不代表全球统一价）")
        self.assertEqual(actual[1]["location"], "账号目录报价；适用地区未标明（不代表全球统一价）")
        self.assertEqual(actual[2]["location"], "公开目录报价；适用地区未标明（不代表全球统一价）")
        for row in actual:
            for unproven in ("国家=", "地区="):
                self.assertNotIn(unproven, row["location"])
            self.assertIn("不代表全球统一价", row["location"])
        self.assertNotIn("CN", actual[0]["location"])
        self.assertNotIn("US", actual[1]["location"])
        self.assertNotIn("FI", actual[2]["location"])
        self.assertIn("可用容量地区（非地区报价）", actual[1]["pricing_conditions"])
        self.assertIn("平台覆盖（非地区报价）", actual[2]["pricing_conditions"])
        for row in actual:
            for evidence in ("原始地域证据", "price_scope", "region_price_verified", "coverage_regions",
                             "capacity_regions", "eu-north1", "us-west-1"):
                self.assertNotIn(evidence, row["pricing_conditions"])
        full = rows(english_csv(source))
        self.assertEqual(json.loads(full[1]["extra_metadata_json"])["capacity_regions"], ["us-west-1"])
        self.assertEqual(json.loads(full[2]["extra_metadata_json"])["coverage_regions"], ["eu-north1"])

    def test_verified_regions_and_unknown_country_remain_distinct_from_catalog(self):
        source = result(
            regional_quote(),
            regional_quote(provider="ucloud", regions=["cn-bj2"], zones=["cn-bj2-02"],
                           compute_countries=["CN"], price_scope="requested_zone_quote"),
            regional_quote(regions=["sgxsingapore1"], compute_countries=[]),
            regional_quote(regions=["us-future1"], compute_countries=["USA"]),
            regional_quote(regions=["us-future1"], compute_countries=["US"], region_price_verified=False),
        )
        actual = self.market_rows(source)
        self.assertIn("价格地区：国家=US / 地区=westus3", actual[0]["location"])
        self.assertIn("请求配置询价地区：国家=CN", actual[1]["location"])
        self.assertIn("可用区=cn-bj2-02", actual[1]["location"])
        self.assertEqual(actual[2]["location"], "价格地区：国家未核实 / 地区=sgxsingapore1")
        self.assertEqual(actual[3]["location"], "价格地区：国家未核实 / 地区=us-future1")
        self.assertEqual(actual[4]["location"], "公开目录报价；适用地区未标明（不代表全球统一价）")
        for row in actual[2:]:
            self.assertNotIn("国家=", row["location"])
        self.assertEqual(len(rows(prices_to_csv(source, profile="compact"))), 2)

    def test_ordinary_member_spot_and_instance_allocation_are_separate_market_rows(self):
        source = result(
            quote(provider="autodl", currency="CNY", amount="10.50", pricing_tier="ordinary", membership_required=False),
            quote(provider="autodl", currency="CNY", amount="9.98", pricing_tier="member", membership_required=True,
                  membership_discount="0.95", ordinary_price_amount="10.50"),
            regional_quote(provider="nebius", amount="1.60", billing_mode="spot", source_type="official_public_api",
                           effective_from="2026-10-21T08:16:00+00:00", source_snapshot_at="2026-10-21T08:32:12+00:00",
                           source_snapshot_basis="earliest_per_sku_snapshot"),
            quote(provider="lambda", amount="2.000", price_basis="instance_total_allocated", gpu_count=8,
                  instance_price={"amount": "16.000", "currency": "USD", "unit": "instance_hour"}),
        )
        actual = self.market_rows(source)
        self.assertEqual([row["amount"] for row in actual], ["10.50", "9.98", "1.60", "2.000"])
        self.assertIn("普通用户", actual[0]["pricing_conditions"])
        self.assertIn("无需会员", actual[0]["pricing_conditions"])
        for text in ("会员", "需会员", "会员折扣=0.95", "普通用户每GPU原币金额=10.50"):
            self.assertIn(text, actual[1]["pricing_conditions"])
        for text in ("Spot（可中断）", "2026-10-21T08:16:00+00:00", "来源=官方公开接口"):
            self.assertIn(text, actual[2]["pricing_conditions"])
        for text in ("2026-10-21T08:32:12+00:00", "earliest_per_sku_snapshot", "official_public_api"):
            self.assertNotIn(text, actual[2]["pricing_conditions"])
        self.assertIn("整机价按卡分摊", actual[3]["pricing_conditions"])
        self.assertIn("整实例总价=16.000 USD instance_hour", actual[3]["pricing_conditions"])
        self.assertIn("8卡", actual[3]["gpu_model"])

    def test_market_eligibility_excludes_inapplicable_periods_statuses_and_non_prices(self):
        self.assertTrue(market_eligible_quote(quote()))
        self.assertTrue(market_eligible_quote(regional_quote()))
        self.assertTrue(market_eligible_quote(quote(provider="autodl", product_type="gpu_container")))
        self.assertTrue(market_eligible_quote(quote(amount="0.0000")))
        self.assertTrue(market_eligible_quote(quote(billing_mode="reserved", minimum_commitment={"months": 12})))
        for overrides in (
            {"unit": "gpu_month"}, {"unit": "instance_hour"}, {"billing_mode": "monthly"},
            {"billing_mode": "yearly"}, {"quote_status": "contact_sales"}, {"quote_status": "starting_at"},
            {"price_basis": "starting_price"}, {"price_basis": "gpu_component"}, {"price_basis": "unrecognized"},
            {"amount": None}, {"amount": ""}, {"amount": "NaN"}, {"amount": "Infinity"},
            {"amount": "-1"}, {"amount": 2.5}, {"amount": True},
            {"availability": "offline"}, {"availability": "ended"}, {"availability": "upcoming"},
            {"availability": "unavailable"}, {"product_type": "cpu_instance"}, {"gpu_model": ""},
            {"currency": "usd"}, {"currency": "US"}, {"currency": None},
        ):
            with self.subTest(overrides=overrides):
                item = quote(**overrides)
                self.assertFalse(market_eligible_quote(item))
                self.assertEqual(self.market_rows(result(item)), [])
        for item in (None, [], "quoted"):
            self.assertFalse(market_eligible_quote(item))

    def test_market_preserves_native_decimals_formula_safety_status_and_source(self):
        source = result(quote(gpu_model="=1+1", currency="EUR", amount="+1.234567890123456789E-12",
                              source_url="\t=HYPERLINK(bad)", notes=["Quoted tax and account terms."]), status="partial")
        before = deepcopy(source)
        row = self.market_rows(source)[0]
        self.assertTrue(row["gpu_model"].startswith("'=1+1"))
        self.assertEqual(row["source_url"], "'\t=HYPERLINK(bad)")
        self.assertEqual((row["amount"], row["currency"]), (source["prices"][0]["amount"], "EUR"))
        self.assertEqual(row["observed_at"], source["prices"][0]["observed_at"])
        self.assertIn("采集状态=partial", row["pricing_conditions"])
        self.assertNotIn("Quoted tax and account terms.", row["pricing_conditions"])
        self.assertEqual(source, before)

    def test_market_keeps_only_material_billing_notes_and_leaves_full_evidence_intact(self):
        source = result(regional_quote(
            provider="nebius", billing_mode="spot", tax_scope="excluded",
            source_type="official_public_api", product_line="Public Cloud",
            conditions={"capacity_type": "preemptible", "pricing_policy_url": "https://example.com/policy"},
            location_source={"url": "https://example.com/regions", "verified_on": "2026-10-21"},
            source_snapshot_at="2026-10-21T08:32:12+00:00", source_snapshot_basis="earliest_per_sku_snapshot",
            notes=[
                "Current anonymous API spot price for one GPU hour on this exact platform in this region; this is not the published minimum or an averaged history point.",
                "Preemptible prices can change as often as every 15 minutes before and during use; interruption conditions apply and capacity is not verified.",
                "The API supplies the currency. USD billing applies except to companies from Israel, where ILS billing applies; customer billing jurisdiction is separate from compute location.",
                "Public catalog; availability, orderability and account-specific discounts were not verified.",
            ],
        ))
        before = deepcopy(source)
        condition = self.market_rows(source)[0]["pricing_conditions"]
        for text in ("Spot（可中断）", "未含税", "产品线=Public Cloud", "以色列公司按ILS计费",
                     "其余客户按USD计费", "每15分钟变动", "来源=官方公开接口"):
            self.assertIn(text, condition)
        for text in ("原始地域证据", "location_source", "快照", "https://example.com", "not verified",
                     "Current anonymous", "capacity_type", "earliest_per_sku_snapshot"):
            self.assertNotIn(text, condition)
        self.assertLess(len(condition), 200)
        full = rows(english_csv(source))[0]
        self.assertEqual(json.loads(full["notes_json"]), source["prices"][0]["notes"])
        self.assertEqual(json.loads(full["location_source_json"]), source["prices"][0]["location_source"])
        self.assertEqual(json.loads(full["extra_metadata_json"])["source_snapshot_at"], source["prices"][0]["source_snapshot_at"])
        self.assertEqual(source, before)

    def test_market_retains_contract_configuration_dates_and_unstructured_additional_charges(self):
        source = result(quote(
            account_scope="account_contract_quote", price_basis="instance_total_allocated",
            source_type="official_quote_api", source_conditions={"offer_types": ["contract"], "aggregation_unit": "hour"},
            minimum_commitment={"months": 12}, selected_configuration={"gpu_count": 8, "boot_disk_gib": 100},
            effective_from="2026-10-21T00:00:00+00:00", effective_until="2026-11-21T00:00:00+00:00",
            notes=["Additional egress traffic incurs a per-GB fee.", "A minimum rental commitment of one hour applies.",
                   "Public catalog; default collection; availability was not verified."],
        ))
        condition = self.market_rows(source)[0]["pricing_conditions"]
        for text in ("账号合同价", "整机价按卡分摊", "价格方案=contract", '最低承诺={"months":12}',
                     '选定配置={"boot_disk_gib":100,"gpu_count":8}', "2026-10-21T00:00:00+00:00",
                     "2026-11-21T00:00:00+00:00", "Additional egress traffic incurs a per-GB fee.",
                     "A minimum rental commitment of one hour applies.", "来源=官方询价接口"):
            self.assertIn(text, condition)
        self.assertNotIn("default collection", condition)
        self.assertNotIn("aggregation_unit", condition)

    def test_market_preserves_unstructured_tax_or_eligibility_limits_without_repeating_known_tax(self):
        note = "VAT applies to this quote."
        actual = self.market_rows(result(
            quote(notes=[note, "Only educational customers qualify for this rate."]),
            quote(tax_scope="excluded", notes=["Prices exclude applicable VAT."]),
            quote(currency="ILS", notes=["ILS prices apply to companies from Israel; this is not a compute-region restriction."]),
        ))
        self.assertIn(note, actual[0]["pricing_conditions"])
        self.assertIn("Only educational customers qualify for this rate.", actual[0]["pricing_conditions"])
        self.assertIn("税费=未含税", actual[1]["pricing_conditions"])
        self.assertNotIn("Prices exclude applicable VAT.", actual[1]["pricing_conditions"])
        self.assertIn("ILS价适用于以色列公司", actual[2]["pricing_conditions"])

    def test_real_five_provider_batch_retains_hourly_catalogs_without_promoting_monthly_ucloud(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "five-providers-2026-10-21.json"
        source = json.loads(path.read_text())
        before = deepcopy(source)
        expected = [price for price in source["prices"] if market_eligible_quote(price)]
        actual = self.market_rows(source)
        self.assertEqual(len(actual), len(expected))
        self.assertGreater(len(actual), 0)
        self.assertEqual({row["provider"] for row in actual}, {"nebius", "lambda", "crusoe", "autodl"})
        self.assertTrue(all(not market_eligible_quote(q) for q in source["prices"] if q["provider"] == "ucloud"))
        for price, row in zip(expected, actual):
            for field in ("provider", "amount", "currency", "unit", "source_url", "observed_at"):
                self.assertEqual(row[field], price[field])
            if not price.get("region_price_verified"):
                self.assertIn("适用地区未标明", row["location"])
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()
