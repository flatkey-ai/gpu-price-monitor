"""CSV price precision, provenance, conditions and spreadsheet-safe output."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest

from gpu_price_monitor.csv_export import CSV_COLUMNS, prices_to_csv


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


def rows(text):
    return list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline="")))


class CsvExportTests(unittest.TestCase):
    def test_fixed_columns_bom_crlf_and_exact_native_decimals_without_conversion(self):
        source = result(quote(), quote(provider="verda", currency="EUR", amount="7.3030"),
                        quote(provider="nebius", currency="ILS", amount="29.450000"))
        output = prices_to_csv(source)
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
        actual = rows(prices_to_csv(result(monthly, sales, quote(amount="0.0000"))))
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
        actual = rows(prices_to_csv(source))
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
        actual = rows(prices_to_csv(result(coverage, regional, zonal)))
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
        actual = rows(prices_to_csv(source))[0]
        self.assertEqual(actual["raw_name"], name)
        self.assertEqual(json.loads(actual["notes_json"]), source["prices"][0]["notes"])
        self.assertEqual(json.loads(actual["resources_json"]), source["prices"][0]["resources"])

    def test_text_formula_injection_is_a_literal_but_decimal_prices_are_unchanged(self):
        dangerous = ["=1+1", "+cmd", "-cmd", "@SUM(1,2)", " \t=HYPERLINK(\"bad\")", "\n=1", "\r@SUM(1)", "\ufeff=1", "\ttext"]
        for value in dangerous:
            with self.subTest(value=value):
                actual = rows(prices_to_csv(result(quote(raw_name=value, raw_sku=value, source_url=value))))[0]
                self.assertEqual(actual["raw_name"], "'" + value)
                self.assertEqual(actual["raw_sku"], "'" + value)
                self.assertEqual(actual["source_url"], "'" + value)
                self.assertEqual(actual["amount"], quote()["amount"])
        for value in ("+1.2300", "0.00000000000000000001", "1.234567890123456789E-12"):
            with self.subTest(amount=value):
                self.assertEqual(rows(prices_to_csv(result(quote(amount=value))))[0]["amount"], value)

    def test_partial_status_timestamps_extra_evidence_and_input_identity_remain(self):
        source = result(quote(api_source_url="https://api.example.com/", azure_meter={"meter_id": "one"},
                              selected_configuration={"gpu_count": 8}, source_conditions={"offer_types": ["contract"]}), status="partial")
        before = deepcopy(source)
        actual = rows(prices_to_csv(source))[0]
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
                output = prices_to_csv(source)
                self.assertEqual(rows(output), [])
                self.assertEqual(output.count("\r\n"), 1)

    def test_malformed_prices_fail_without_exposing_or_coercing_upstream_values(self):
        for value in (1.25, -1, True, "NaN", "Infinity", "-1.00", "=private_upstream_text", "+SUM(1)"):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                prices_to_csv(result(quote(amount=value)))
            self.assertNotIn("private_upstream_text", str(error.exception))
        for value in (None, [], {}, {"status": "success"}, {"prices": {}}, {"prices": [None]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prices_to_csv(value)

    def test_real_nine_provider_example_retains_every_quote_amount_and_condition(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "nine-providers-2026-10-21.json"
        source = json.loads(path.read_text())
        before = deepcopy(source)
        actual = rows(prices_to_csv(source))
        self.assertEqual(len(actual), len(source["prices"]))
        self.assertEqual(len({row["provider"] for row in actual}), 9)
        for price, row in zip(source["prices"], actual):
            self.assertEqual(row["amount"], price["amount"] if price["amount"] is not None else "")
            for field in ("provider", "currency", "unit", "billing_mode", "availability", "source_url"):
                self.assertEqual(row[field], price[field])
            for field in ("compute_countries", "regions", "zones"):
                self.assertEqual(json.loads(row[field]) if row[field] else [], price.get(field, []))
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()
