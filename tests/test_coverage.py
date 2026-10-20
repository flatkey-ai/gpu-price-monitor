"""Coverage reports keep model gaps and original quotation conditions visible."""

import copy
import json
import unittest

from gpu_price_monitor.coverage import MAINSTREAM_GPU_MODELS, gpu_family, report_coverage
from gpu_price_monitor.settings import ConfigurationError


def quote(model, amount="1.00", *, provider="example", availability="unknown", status="quoted", currency="USD", unit="gpu_hour"):
    return {"gpu_model": model, "amount": amount, "provider": provider, "availability": availability,
            "quote_status": status, "currency": currency, "unit": unit}


class CoverageTests(unittest.TestCase):
    def test_default_targets_keep_missing_models_and_all_requested_families(self):
        self.assertEqual(len(MAINSTREAM_GPU_MODELS), 34)
        self.assertEqual(len(set(MAINSTREAM_GPU_MODELS)), 34)
        self.assertEqual(tuple(gpu_family({"gpu_model": name}) for name in MAINSTREAM_GPU_MODELS), MAINSTREAM_GPU_MODELS)
        report = report_coverage({"prices": []})
        self.assertEqual(report["totals"]["requested_models"], 34)
        self.assertEqual(report["totals"]["not_found_models"], 34)
        self.assertEqual(report["totals"]["priced_models"], 0)
        self.assertEqual(report["collection_status"], "unknown")
        self.assertIsNone(report["source_summary"]["requested_count"])
        self.assertEqual(report["scope"], "returned_quotes")
        self.assertEqual(report["schema_version"], 1)

    def test_family_preserves_gb_b_d_non_d_and_t4s(self):
        cases = {
            "GB200 NVL72": "GB200", "B200 SXM6": "B200", "GB300 NVL72": "GB300",
            "GH200": "GH200", "H200 SXM": "H200", "RTX 4090D": "RTX 4090D",
            "RTX 4090 D 24GB": "RTX 4090D", "RTX 4090": "RTX 4090", "T4S": "T4S", "T4": "T4",
            "Tesla V100S 32GB": "V100", "RTX 6000 Ada": "RTX 6000 ADA", "RTX 6000": "RTX 6000",
            "RTX A6000": "RTX A6000", "A6000": "RTX A6000", "RTX PRO 6000 WS": "RTX PRO 6000",
            "RTX3080Ti": "RTX 3080 TI", "RTX 3080": "RTX 3080", "RTX A4000": "RTX A4000",
            "8x NVIDIA H100 SXM5 80GB": "H100", "AMD Instinct MI355X": "MI355X",
            "NVIDIA® HGX H100 NVL": "H100", "H100_FAKE": "H100",
            "H100SXM": "H100", "H100PCIe": "H100", "H100NVL": "H100",
            "4090": "RTX 4090", "4090_48G": "RTX 4090", "5090": "RTX 5090",
            "3090": "RTX 3090", "3080Ti": "RTX 3080 TI", "2080Ti": "RTX 2080 TI",
            "4090D": "RTX 4090D", "4090D_48G": "RTX 4090D", "PRO 6000": "PRO 6000",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(gpu_family({"gpu_model": raw}), expected)
        self.assertEqual(gpu_family({"raw_name": "NVIDIA H100 PCIe"}), "H100")
        for value in (None, [], {}, {"gpu_model": None}, {"raw_name": " "}):
            self.assertIsNone(gpu_family(value))

    def test_variants_units_currencies_remain_original_and_no_prices_aggregated(self):
        result = {"status": "success", "prices": [
            quote("H100 SXM", "3.00"), quote("H100 PCIe", "2.00", currency="EUR"),
            quote("H100 NVL", "1000.00", currency="CNY", unit="gpu_month"),
        ], "provider_results": [{"provider": "example", "status": "success"}]}
        before = copy.deepcopy(result)
        report = report_coverage(result, ["H100"])
        item = report["models"][0]
        self.assertEqual(item, {"gpu_model": "H100", "status": "priced", "quote_count": 3,
                               "numeric_quote_count": 3, "providers": ["example"],
                               "currencies": ["CNY", "EUR", "USD"], "units": ["gpu_hour", "gpu_month"],
                               "quote_indices": [0, 1, 2]})
        self.assertEqual(result, before)
        self.assertNotIn("min", json.dumps(report))
        self.assertNotIn("average", json.dumps(report))
        self.assertEqual(report["source_summary"]["success_count"], 1)

    def test_unknown_availability_counts_list_price_and_zero_is_numeric(self):
        report = report_coverage({"prices": [quote("H100", "0", availability="unknown")]}, ["H100"])
        self.assertEqual(report["models"][0]["status"], "priced")
        self.assertEqual(report["models"][0]["numeric_quote_count"], 1)
        self.assertEqual(report["collection_status"], "unknown")

    def test_unavailable_numeric_and_contact_sales_have_explicit_statuses(self):
        prices = [quote("A100", availability=value) for value in ("offline", "ended", "upcoming", "out_of_stock")]
        prices += [quote("A100", None, status="contact_sales"), quote("B200", None, status="contact_sales")]
        report = report_coverage({"prices": prices}, ["A100", "B200", "H100"])
        a100, b200, h100 = report["models"]
        self.assertEqual((a100["status"], a100["quote_count"], a100["numeric_quote_count"]), ("unavailable_listings_only", 5, 4))
        self.assertEqual((b200["status"], b200["numeric_quote_count"]), ("contact_sales_only", 0))
        self.assertEqual(h100["status"], "not_found")
        self.assertEqual(report["totals"]["unavailable_listings_only_models"], 1)
        self.assertEqual(report["totals"]["contact_sales_only_models"], 1)
        self.assertEqual(report["totals"]["not_found_models"], 1)
        prices.append(quote("A100", availability="unknown"))
        self.assertEqual(report_coverage({"prices": prices}, ["A100"])["models"][0]["status"], "priced")

    def test_extra_models_are_retained_with_indices_and_unknown_name(self):
        report = report_coverage({"prices": [quote("T4S"), quote("RTX 4060"), quote(None), quote("H100")]}, ["H100"])
        self.assertEqual(report["totals"]["extra_models"], 3)
        self.assertEqual(report["totals"]["matched_quotes"], 1)
        extra = {item["gpu_model"]: item for item in report["extra_models"]}
        self.assertEqual(extra["T4S"]["quote_indices"], [0])
        self.assertEqual(extra["RTX 4060"]["quote_indices"], [1])
        self.assertEqual(extra[None]["quote_indices"], [2])
        self.assertEqual(report["models"][0]["quote_indices"], [3])

    def test_failed_sources_do_not_contribute_quotes_or_fake_success(self):
        result = {"status": "partial", "prices": [quote("H100", provider="failed"), quote("B200", provider="ok")],
                  "provider_results": [{"provider": "failed", "status": "failed"}, {"provider": "ok", "status": "success"},
                                       {"provider": "empty", "status": "no_matches"}, {"provider": "unknown"}]}
        report = report_coverage(result, ["H100", "B200"])
        self.assertEqual(report["collection_status"], "partial")
        self.assertEqual(report["source_summary"], {"requested_count": 4, "success_count": 1, "failed_count": 1, "no_matches_count": 1, "unknown_count": 1})
        self.assertEqual(report["models"][0]["status"], "not_found")
        self.assertEqual(report["models"][1]["status"], "priced")
        self.assertEqual(report["excluded_quote_indices"], [0])
        result["status"] = "failed"
        report = report_coverage(result, ["H100", "B200"])
        self.assertEqual(report["totals"]["priced_models"], 0)
        self.assertEqual(report["excluded_quote_indices"], [0, 1])
        self.assertEqual(report["totals"]["considered_quotes"], 0)

    def test_negative_non_finite_missing_and_non_string_amounts_are_rejected(self):
        for amount in (None, "", "bad", "NaN", "Infinity", "-Infinity", "-0.01", 0, 1.5, True):
            with self.subTest(amount=amount), self.assertRaises(ConfigurationError):
                report_coverage({"prices": [quote("H100", amount)]})
        with self.assertRaises(ConfigurationError):
            report_coverage({"prices": [quote("H100", "1.00", status="contact_sales")]})
        self.assertEqual(report_coverage({"prices": [quote("H100", None, status="contact_sales")]}, ["H100"])["models"][0]["status"], "contact_sales_only")

    def test_bad_models_and_result_arguments_fail_with_safe_errors(self):
        for models in ("H100", [], (), [1], [None], [""], ["H100", "h100 sxm"], ["bad\nname"], ["X" * 121]):
            with self.subTest(models=models), self.assertRaises(ConfigurationError):
                report_coverage({"prices": []}, models)
        for result in (None, [], {}, {"prices": None}, {"prices": ()}, {"prices": [1]}, {"prices": [], "provider_results": {}}, {"prices": [], "provider_results": [None]}):
            with self.subTest(result=result), self.assertRaises(ConfigurationError):
                report_coverage(result)
        self.assertEqual(report_coverage({"prices": [], "status": {}}, ["H100"])["collection_status"], "unknown")

    def test_custom_models_are_normalized_in_order_without_modifying_argument(self):
        models = ["RTX4090D", "NVIDIA H100 SXM"]
        before = list(models)
        report = report_coverage({"prices": [quote("H100")]}, models)
        self.assertEqual([entry["gpu_model"] for entry in report["models"]], ["RTX 4090D", "H100"])
        self.assertEqual(models, before)
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_bare_consumer_names_group_without_changing_vram_or_raw_quotes(self):
        prices = [quote("4090"), quote("4090_48G"), quote("4090D")]
        prices[0]["vram_gb"] = 24
        prices[1]["vram_gb"] = 48
        before = copy.deepcopy(prices)
        report = report_coverage({"prices": prices}, ["RTX 4090", "RTX 4090D"])
        self.assertEqual(report["models"][0]["quote_indices"], [0, 1])
        self.assertEqual(report["models"][1]["quote_indices"], [2])
        self.assertEqual(prices, before)


if __name__ == "__main__":
    unittest.main()
