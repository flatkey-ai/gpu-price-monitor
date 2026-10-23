"""Provider exports are small, native-price views of proven hourly locations."""

from copy import deepcopy
import csv
from decimal import Inexact, Rounded, localcontext
import io
import json
from pathlib import Path
import unittest

from gpu_price_monitor.provider_csv import (
    PROVIDER_CSV_COLUMNS, PROVIDER_CSV_HEADERS, prices_to_provider_csvs, provider_csv_coverage,
)
from gpu_price_monitor.providers import lambda_console
from gpu_price_monitor.providers.autodl_market_api import parse_listing


OBSERVED = "2026-10-23T08:30:00+00:00"
FIXTURES = Path(__file__).parent / "fixtures"


def quote(provider="nebius", **overrides):
    return {"provider": provider, "product_type": "gpu_instance", "gpu_model": "H100",
            "gpu_variant": "SXM", "vram_gb": 80, "gpu_count": 8, "raw_sku": "gpu-h100-sxm",
            "amount": "2.123456789", "currency": "USD", "unit": "gpu_hour", "billing_mode": "on_demand",
            "price_basis": "instance_total_allocated", "quote_status": "quoted",
            "regions": ["eu-north1"], "zones": [], "compute_countries": ["FI"],
            "price_scope": "regional_quote", "region_price_verified": True,
            "availability": "unknown", "account_scope": "account_quote", "tax_scope": "excluded",
            "resources": {"platform": "gpu-h100-sxm", "preset": "8gpu-128vcpu-1600gb", "vcpus": 128, "memory_gib": 1600},
            "instance_price": {"amount": "16.987654312", "currency": "USD", "unit": "instance_hour", "scope": "compute_resources_only"},
            "source_url": "https://api.nebius.cloud/billing/v1/estimate", "source_type": "official_api",
            "observed_at": OBSERVED, **overrides}


def envelope(prices, providers=()):
    return {"prices": prices, "status": "success", "provider_results": [{"provider": provider} for provider in providers]}


def rows(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def exported(prices, provider="nebius"):
    return rows(prices_to_provider_csvs(envelope(prices), bilingual_headers=False)[provider])


def member_pair():
    identity = {"machine_id": "synthetic-machine", "chip_corp": "nvidia", "gpu_memory": 24 * 2**30,
                "gpu_name": "RTX 4090", "region_sign": "bj-B1", "region_name": "北京B区"}
    item = {"payg": True, "cpu_per_gpu": 12, "mem_per_gpu": 62 * 2**30,
            "on_line": 2, "gpu_idle_num": 2, "max_instance_num": 10, "binding_instance_num": 1,
            "machine_sku_info": [{"type": "payg", "current_price": 1660, "level_config": [
                {"level_name": "normal_user", "discount": 100, "discounted_price": 1660},
                {"level_name": "member_user", "discount": 95, "discounted_price": 1577}]}]}
    result = parse_listing(item, identity=identity, observed_at=OBSERVED)
    for item in result:
        item.update(compute_countries=["CN"], price_scope="regional_quote", region_price_verified=True)
    return result


class ProviderCsvTests(unittest.TestCase):
    def test_each_provider_has_its_own_small_bilingual_schema_and_empty_header(self):
        result = prices_to_provider_csvs(envelope([], PROVIDER_CSV_COLUMNS))
        self.assertEqual(set(result), set(PROVIDER_CSV_COLUMNS))
        for provider, content in result.items():
            self.assertTrue(content.startswith("\ufeff"))
            reader = csv.reader(io.StringIO(content.lstrip("\ufeff")))
            self.assertEqual(tuple(next(reader)), PROVIDER_CSV_HEADERS[provider])
            self.assertEqual(list(reader), [])
            self.assertLessEqual(len(PROVIDER_CSV_COLUMNS[provider]), 18)
        self.assertNotEqual(PROVIDER_CSV_COLUMNS["autodl"], PROVIDER_CSV_COLUMNS["ucloud"])
        self.assertIn("offer_id", PROVIDER_CSV_COLUMNS["vast"])

    def test_native_precision_and_input_are_unchanged_under_low_decimal_context(self):
        source = envelope([quote()])
        before = deepcopy(source)
        with localcontext() as context:
            context.prec = 1
            context.traps[Inexact] = context.traps[Rounded] = True
            row = rows(prices_to_provider_csvs(source, bilingual_headers=False)["nebius"])[0]
        self.assertEqual(row["gpu_hour_amount"], "2.123456789")
        self.assertEqual(row["instance_hour_amount"], "16.987654312")
        self.assertEqual((row["currency"], row["country"], row["region"]), ("USD", "FI", "eu-north1"))
        self.assertEqual((row["platform"], row["preset"]), ("gpu-h100-sxm", "8gpu-128vcpu-1600gb"))
        self.assertIn("1600 GiB", row["resource_config"])
        self.assertIn("磁盘和网络另计", row["pricing_conditions"])
        self.assertEqual(source, before)

    def test_unlocated_crusoe_is_header_only_with_explicit_coverage_reason(self):
        item = quote("crusoe", regions=[], compute_countries=[], price_scope="unlocated_catalog", region_price_verified=False)
        source = envelope([item], ["crusoe"])
        self.assertEqual(rows(prices_to_provider_csvs(source)["crusoe"]), [])
        stats = provider_csv_coverage(source)["crusoe"]
        self.assertEqual(stats["source_quote_count"], 1)
        self.assertEqual(stats["row_count"], 0)
        self.assertEqual(stats["excluded_reasons"], {"country_region_not_verified": 1})

    def test_exact_hourly_geography_gate_never_uses_coverage_or_guessed_global_price(self):
        changes = [{"unit": "gpu_month"}, {"quote_status": "starting_at"}, {"price_basis": "gpu_component"},
                   {"amount": "NaN"}, {"amount": "-1"}, {"amount": None}, {"currency": "usd"},
                   {"price_scope": "platform_coverage"}, {"region_price_verified": False},
                   {"compute_countries": []}, {"regions": []}, {"regions": ["Global"]},
                   {"compute_countries": ["EU"]}, {"compute_countries": ["FI", "US"]},
                   {"availability": "offline"}, {"availability": "ended"}]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(exported([quote(**change)]), [])
        self.assertEqual(exported([quote(amount="0.000")])[0]["gpu_hour_amount"], "0.000")

    def test_shared_lambda_locations_keep_country_join_and_are_not_independent_quotes(self):
        payload = json.loads((FIXTURES / "lambda-console-instance-types-20261022.json").read_text())
        quotes = lambda_console.parse_instance_prices(payload, observed_at=OBSERVED)
        eligible = next(item for item in quotes if item["price_applicability"]["locations"])
        source = envelope([eligible])
        expected = eligible["price_applicability"]["locations"]
        table = rows(prices_to_provider_csvs(source, bilingual_headers=False)["lambda"])
        self.assertEqual([(row["country"], row["region"]) for row in table],
                         [(item["country_code"], item["region"]) for item in expected])
        self.assertTrue(all("统一目录价" in row["pricing_conditions"] and "非逐地区独立询价" in row["pricing_conditions"] for row in table))
        stats = provider_csv_coverage(source)["lambda"]
        self.assertEqual((stats["source_quote_count"], stats["exported_quote_count"], stats["row_count"]), (1, 1, len(expected)))
        tampered = deepcopy(eligible)
        tampered["price_applicability"]["evidence"]["source_sha256"] = "unverified"
        self.assertEqual(exported([tampered], "lambda"), [])

    def test_lambda_cluster_card_count_and_worker_resources_do_not_become_instance_totals(self):
        payload = json.loads((FIXTURES / "lambda-console-cluster-types-20261022.json").read_text())
        item = next(q for q in lambda_console.parse_cluster_prices(payload, observed_at=OBSERVED)
                    if q["price_applicability"]["locations"])
        row = exported([item], "lambda")[0]
        self.assertEqual(row["gpu_count"], str(item["selected_configuration"]["cluster_gpu_count"]))
        self.assertEqual(row["instance_hour_amount"], "")
        self.assertTrue(row["cpu"].startswith("每节点 "))
        self.assertIn("预留期限未核实", row["pricing_conditions"])
        self.assertIn("结算周期=week", row["pricing_conditions"])

    def test_member_preference_defaults_to_verified_exact_pairs_with_eligibility_visible(self):
        source = envelope(member_pair())
        table = rows(prices_to_provider_csvs(source, bilingual_headers=False)["autodl"])
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["gpu_hour_amount"], "1.58")
        self.assertEqual(table[0]["currency"], "CNY")
        self.assertIn("需会员资格", table[0]["membership"])
        self.assertEqual(table[0]["data_center"], "北京B区")
        self.assertEqual(table[0]["gpu_count"], "")  # Advertised slot does not imply a configured instance.
        self.assertIn("CPU核/卡", table[0]["resource_config"])
        self.assertEqual(len(rows(prices_to_provider_csvs(source, bilingual_headers=False, prefer_member=False)["autodl"])), 2)
        self.assertEqual(provider_csv_coverage(source)["autodl"]["ordinary_member_pairs_hidden"], 1)
        source["prices"][1]["observed_at"] = "2026-10-23T09:30:00+00:00"
        self.assertEqual(len(rows(prices_to_provider_csvs(source)["autodl"])), 2)

    def test_ucloud_keeps_exact_boot_disk_image_network_and_hourly_total(self):
        item = quote("ucloud", raw_sku=None, raw_name="UHost A800", currency="CNY", amount="3.60",
                     instance_price={"amount": "28.80", "currency": "CNY", "unit": "instance_hour"},
                     resources={"vcpu_count": 16, "memory_mb": 131072, "cpu_platform": "Intel", "net_capability": "Normal",
                                "disks": [{"IsBoot": "True", "Type": "CLOUD_RSSD", "Size": 40},
                                          {"IsBoot": "False", "Type": "CLOUD_SSD", "Size": 500}]},
                     image_selection={"image_name": "Ubuntu CUDA12.4", "image_id": "private-image-id"},
                     source_type="official_internal_api", zones=["cn-wlcb-01"], regions=["cn-wlcb"], compute_countries=["CN"])
        row = exported([item], "ucloud")[0]
        self.assertEqual(row["boot_disk"], "40 GB / CLOUD_RSSD")
        self.assertEqual(row["image_network"], "Ubuntu CUDA12.4 / Normal")
        self.assertIn("131072 MB", row["cpu_memory"])
        self.assertEqual(row["instance_hour_amount"], "28.80")
        self.assertEqual(row["zone"], "cn-wlcb-01")

    def test_instance_total_is_never_invented_or_mislabelled_with_another_currency_or_period(self):
        for value in (None, {"amount": "100", "currency": "CNY", "unit": "instance_hour"},
                      {"amount": "100", "currency": "USD", "unit": "instance_month"}):
            self.assertEqual(exported([quote(instance_price=value)])[0]["instance_hour_amount"], "")

    def test_vast_storage_units_bandwidth_and_clickable_page_remain_explicit(self):
        item = quote("vast", raw_sku="123456", regions=["California, US"], compute_countries=["US"],
                     resources={"vcpus": 12, "memory_mb": "64000", "memory_gb": 64, "storage_gb": 8},
                     conditions={"storage_unit": "GB_as_documented_by_API", "bandwidth_included": False},
                     source_url="https://console.vast.ai/api/v0/bundles", pricing_page_url="https://cloud.vast.ai/create/",
                     tax_scope="unspecified")
        row = exported([item], "vast")[0]
        self.assertEqual(row["offer_id"], "123456")
        self.assertIn("64000 MB", row["cpu_memory"])
        self.assertEqual(row["storage"], "8 GB（API文档；CLI称GiB，未换算）")
        self.assertIn("带宽另计", row["extra_costs"])
        self.assertIn("税费未说明", row["extra_costs"])
        self.assertEqual(row["source_url"], "https://cloud.vast.ai/create/")

    def test_unrelated_and_private_metadata_do_not_become_export_columns(self):
        item = quote(project_reference="DO_NOT_EXPORT_PROJECT", quote_request={"token": "DO_NOT_EXPORT_TOKEN"})
        content = prices_to_provider_csvs(envelope([item]))["nebius"]
        self.assertNotIn("DO_NOT_EXPORT", content)
        self.assertNotIn("quote_request", content)

    def test_text_formulas_are_escaped_but_decimal_amounts_remain_numeric(self):
        row = exported([quote(gpu_model="=HYPERLINK(\"evil\")", observed_at="\tformula", source_url="+evil")])[0]
        self.assertTrue(row["gpu_model"].startswith("'="))
        self.assertEqual(row["source_url"], "'+evil")
        self.assertEqual(row["observed_at"], "'\tformula")
        self.assertEqual(row["gpu_hour_amount"], "2.123456789")

    def test_invalid_export_arguments_and_provider_paths_are_rejected(self):
        for source in ({}, {"prices": {}}, envelope([None]), envelope([quote(provider="../private")]),
                       {"prices": [], "provider_results": [None]}):
            with self.assertRaises(ValueError):
                prices_to_provider_csvs(source)
        for kwargs in ({"prefer_member": 1}, {"bilingual_headers": "yes"}):
            with self.assertRaises(ValueError):
                prices_to_provider_csvs(envelope([]), **kwargs)


if __name__ == "__main__":
    unittest.main()
