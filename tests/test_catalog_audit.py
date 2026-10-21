"""Catalog audit counts rows and source rates without manufacturing completeness."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from gpu_price_monitor.catalog_audit import report_catalog_audit
from gpu_price_monitor.settings import ConfigurationError


def quote(provider="nebius", **changes):
    return {"provider": provider, "amount": "2.50", "currency": "USD", "unit": "gpu_hour",
            "quote_status": "quoted", "billing_mode": "on_demand", "region_price_verified": False,
            "regions": [], "compute_countries": [], **changes}


def result(prices, sources=None, **changes):
    if sources is None:
        sources = [{"provider": provider, "status": "success", "filters": {}}
                   for provider in dict.fromkeys(record["provider"] for record in prices)]
    return {"prices": prices, "provider_results": sources, "status": "success",
            "execution": {"catalog_scope": "complete", "source_policy": "api_preferred"}, **changes}


def provider(report, name="nebius"):
    return next(entry for entry in report["providers"] if entry["provider"] == name)


class CatalogAuditTests(unittest.TestCase):
    def test_counts_exact_rows_calculations_sales_floors_and_original_rates_separately(self):
        prices = [
            quote(quote_origin="published_tariff_preset_calculation"),
            quote(quote_origin="regional_spot_preset_calculation", billing_mode="spot",
                  source_type="official_public_api", regions=["real-region"], region_price_verified=True),
            quote(quote_origin="regional_spot_preset_calculation", billing_mode="spot", gpu_count=8,
                  source_type="official_public_api", regions=["real-region"], region_price_verified=True),
            quote(amount=None, quote_status="contact_sales"),
            quote("lambda", product_type="gpu_cluster", billing_mode="reserved",
                  source_conditions={"sales_contact_required": True}, configuration_expansion=False,
                  normalization={"formula": "instance price / GPU count"}),
            quote("lambda", amount=None, quote_status="contact_sales", billing_mode="reserved"),
            quote("crusoe"), quote("crusoe", quote_status="starting_at", amount="0.50"),
        ]
        sources = [{"provider": "nebius", "status": "success", "catalog_coverage": {"summary": {
            "raw_exact_gpu_rate_count": 2, "raw_exact_resource_rate_count": 4,
            "raw_document_gpu_rate_count": 3, "raw_document_resource_rate_count": 5,
            "reported_spot_api_quote_count": 1, "platform_count": 1, "preset_count": 2,
            "published_spot_minimums_not_used_as_quotes": [{"amount": "0.50"}],
        }}}, {"provider": "lambda", "status": "success"}, {"provider": "crusoe", "status": "success"}]
        report = report_catalog_audit(result(prices, sources))
        self.assertEqual(report["totals"]["record_count"], 8)
        self.assertEqual(report["totals"]["numeric_quoted_gpu_hour_count"], 5)
        self.assertEqual(report["totals"]["derived_calculation_count"], 3)
        self.assertEqual(report["totals"]["derived_numeric_quoted_gpu_hour_count"], 3)
        self.assertEqual(report["totals"]["direct_record_count"], 5)
        self.assertEqual(report["totals"]["direct_numeric_quoted_gpu_hour_count"], 2)
        self.assertEqual(report["totals"]["contact_sales_count"], 2)
        self.assertEqual(report["totals"]["starting_at_count"], 1)
        self.assertEqual(report["totals"]["regional_record_count"], 2)
        nebius = provider(report)
        self.assertEqual(nebius["independent_source_counts"]["reported_spot_api_quote_count"], 1)
        self.assertEqual(nebius["independent_source_counts"]["raw_exact_gpu_rate_count"], 2)
        self.assertEqual(nebius["source_catalog_structure_counts"], {"platform_count": 1, "preset_count": 2})
        self.assertEqual(nebius["source_published_spot_minimum_count"], 1)
        self.assertEqual(nebius["starting_at_count"], 0)
        self.assertEqual(provider(report, "lambda")["contact_sales_count"], 1)
        self.assertEqual(provider(report, "lambda")["direct_numeric_quoted_gpu_hour_count"], 1)
        self.assertFalse(report["all_prices_complete"])
        self.assertEqual(report["public_collect_status"], "success")

    def test_derivation_is_explicit_and_not_inferred_from_api_or_normalization(self):
        prices = [quote(quote_origin="unknown", rate_derivation={"independent_provider_quote": False}),
                  quote(configuration_expansion=True),
                  quote(rate_derivation={"method": "computed_from_official_tariff"}),
                  quote(source_type="official_api", normalization={"formula": "cents / gpu_count"}),
                  quote(source_type="official_public_api", quote_origin="reported_regional_spot_rate",
                        regions=["new-official-region"], region_price_verified=True),
                  quote(quote_origin={})]
        report = report_catalog_audit(result(prices))
        self.assertEqual(report["totals"]["derived_calculation_count"], 3)
        self.assertEqual(report["totals"]["direct_numeric_quoted_gpu_hour_count"], 3)
        self.assertEqual(report["totals"]["regional_record_count"], 1)

    def test_unknown_source_sizes_stay_unknown_and_duplicate_contexts_are_not_added(self):
        source = {"provider": "nebius", "status": "success", "coverage": {"reported_spot_api_quote_count": 999},
                  "source_contexts": [{"catalog_coverage": {"summary": {"reported_spot_api_quote_count": 888}}}]}
        report = report_catalog_audit(result([quote(quote_origin="regional_spot_preset_calculation")], [source]))
        self.assertTrue(all(value is None for value in provider(report)["independent_source_counts"].values()))
        source["catalog_coverage"] = {"summary": {"reported_spot_api_quote_count": 2}}
        report = report_catalog_audit(result([quote()], [source]))
        self.assertEqual(provider(report)["independent_source_counts"]["reported_spot_api_quote_count"], 2)

    def test_bool_negative_and_noninteger_source_sizes_are_not_counts(self):
        summary = {"raw_exact_gpu_rate_count": True, "raw_exact_resource_rate_count": -1,
                   "reported_spot_api_quote_count": "12", "platform_count": 1.5}
        source = {"provider": "nebius", "status": "success", "catalog_coverage": {"summary": summary}}
        report = report_catalog_audit(result([], [source]))
        self.assertTrue(all(value is None for value in provider(report)["independent_source_counts"].values()))
        self.assertIsNone(provider(report)["source_catalog_structure_counts"]["platform_count"])

    def test_only_valid_finite_decimal_quoted_hourly_amounts_count(self):
        invalid = (None, "", "bad", "NaN", "Infinity", "-Infinity", "-1", 0, True)
        prices = [quote(amount=amount) for amount in invalid]
        prices.extend([quote(amount="0"), quote(amount="2E-3"), quote(unit="gpu_month"),
                       quote(quote_status="starting_at"), quote(amount=None, quote_status="contact_sales")])
        report = report_catalog_audit(result(prices))
        self.assertEqual(report["totals"]["numeric_quoted_gpu_hour_count"], 2)
        self.assertEqual(report["totals"]["invalid_numeric_gpu_hour_record_count"], len(invalid))
        self.assertEqual(report["totals"]["record_count"], len(prices))

    def test_platform_coverage_and_capacity_never_become_regional_counts(self):
        prices = [quote(coverage_regions=["coverage"], compute_countries=["US"]),
                  quote(regions=["capacity"], region_price_verified=False),
                  quote(region_price_verified=True, coverage_regions=["coverage"]),
                  quote(region_price_verified=True, regions=["   "]),
                  quote(region_price_verified=True, regions=["verified"]),
                  quote(region_price_verified=True, zones=["verified-zone"])]
        self.assertEqual(report_catalog_audit(result(prices))["totals"]["regional_record_count"], 2)

    def test_filtered_records_and_unfiltered_summary_have_explicit_different_scopes(self):
        source = {"provider": "nebius", "status": "success", "source_type": "official_public_sources",
                  "source_url": "https://example.test/pricing", "fetched_count": 99,
                  "filters": {"gpu_counts": {"requested": [8], "status": "applied_locally"}},
                  "catalog_coverage": {"summary": {"reported_spot_api_quote_count": 7}},
                  "gaps": [{"scope": "account_specific_prices", "status": "authentication_required"}]}
        report = report_catalog_audit(result([quote(gpu_count=8)], [source]))
        entry = provider(report)
        self.assertEqual(report["scope"], "selected_scope")
        self.assertEqual(report["selected_scope"], {"basis": "returned_records_after_caller_filters",
                                                  "providers": ["nebius"], "source_policy": "api_preferred",
                                                  "catalog_scope": "complete"})
        self.assertEqual(entry["record_count"], 1)
        self.assertEqual(entry["selected_scope"]["fetched_record_count"], 99)
        self.assertEqual(entry["selected_scope"]["filters"], {"gpu_counts": [8]})
        self.assertIn("before_caller_filters", entry["source_count_scope"])
        self.assertEqual(entry["independent_source_counts"]["reported_spot_api_quote_count"], 7)
        self.assertTrue(any(gap["status"] == "caller_filtered" for gap in report["gaps"]))
        self.assertFalse(report["all_prices_complete"])

    def test_failed_sources_have_record_counts_but_do_not_contribute_numeric_claims(self):
        sources = [{"provider": "nebius", "status": "failed"}, {"provider": "lambda", "status": "partial"}]
        report = report_catalog_audit(result([quote(), quote("lambda")], sources, status="partial"))
        self.assertEqual(report["totals"]["record_count"], 2)
        self.assertEqual(report["totals"]["considered_record_count"], 1)
        self.assertEqual(report["totals"]["excluded_failed_source_record_count"], 1)
        self.assertEqual(report["totals"]["numeric_quoted_gpu_hour_count"], 1)
        self.assertEqual(report["public_collect_status"], "partial")
        self.assertTrue(any(gap["status"] == "failed" for gap in report["gaps"]))
        failed = report_catalog_audit(result([quote()], [{"provider": "nebius", "status": "success"}], status="failed"))
        self.assertEqual(failed["totals"]["considered_record_count"], 0)
        self.assertEqual(failed["public_collect_status"], "failed")

    def test_contract_audit_only_has_no_public_success_or_raw_contract_records(self):
        source = {"provider": "crusoe", "status": "success", "audit_only": True,
                  "contract_records": [{"private_contract_value": "PRIVATE_SENTINEL_DO_NOT_RETURN"}],
                  "contract_record_count": 1,
                  "source_contexts": [{"contract_records": ["PRIVATE_CONTEXT_SENTINEL"]}],
                  "gaps": [{"scope": "contract_gpu_hour_prices", "status": "unverified",
                            "contract_records": ["PRIVATE_GAP_SENTINEL"]}]}
        report = report_catalog_audit(result([], [source]))
        self.assertEqual(report["totals"]["contract_record_count"], 1)
        self.assertEqual(report["totals"]["numeric_quoted_gpu_hour_count"], 0)
        self.assertEqual(report["public_collect_status"], "not_requested")
        self.assertEqual(provider(report, "crusoe")["contract_records_scope"], "private_account_audit_count_only")
        self.assertNotIn("PRIVATE_", json.dumps(report))
        self.assertNotIn("contract_records", provider(report, "crusoe"))

    def test_combined_public_success_is_distinct_from_failed_account_audit(self):
        source = {"provider": "crusoe", "status": "partial",
                  "selection_reason": "public_prices_and_account_contract_audit",
                  "source_contexts": [{"source_type": "public_page", "status": "ok", "record_count": 1}],
                  "source_errors": [{"source_url": "https://example.test/account-audit", "code": "missing_credentials"}]}
        report = report_catalog_audit(result([quote("crusoe")], [source], status="partial"))
        self.assertEqual(report["collection_status"], "partial")
        self.assertEqual(report["public_collect_status"], "success")
        self.assertFalse(report["all_prices_complete"])

    def test_combined_public_failure_does_not_become_success_from_account_records(self):
        source = {"provider": "crusoe", "status": "partial", "account_audit_only": True,
                  "source_url": "https://example.test/public-pricing", "contract_record_count": 3,
                  "source_contexts": [{"audit_only": True, "status": "ok"}],
                  "source_errors": [{"source_url": "https://example.test/public-pricing", "code": "http_error"}]}
        report = report_catalog_audit(result([], [source], status="partial"))
        self.assertEqual(report["public_collect_status"], "failed")
        self.assertEqual(report["totals"]["contract_record_count"], 3)
        self.assertEqual(report["totals"]["numeric_quoted_gpu_hour_count"], 0)

    def test_failed_account_only_does_not_claim_public_collection_was_requested(self):
        source = {"provider": "crusoe", "status": "failed", "source_type": "official_api",
                  "api_endpoint": "https://api.cloud.crusoe.ai/v1/organizations/{organization_id}/reservations",
                  "error": {"code": "configuration_error"}}
        report = report_catalog_audit(result([], [source], status="failed"))
        self.assertEqual(report["public_collect_status"], "not_requested")
        self.assertEqual(report["collection_status"], "failed")

    def test_missing_source_metadata_stays_unknown_even_if_numeric_rows_exist(self):
        report = report_catalog_audit({"prices": [quote()], "provider_results": []})
        self.assertEqual(report["collection_status"], "unknown")
        self.assertEqual(report["public_collect_status"], "unknown")
        self.assertIsNone(report["selected_scope"]["catalog_scope"])
        self.assertFalse(report["all_prices_complete"])
        empty = report_catalog_audit({"prices": []})
        self.assertEqual(empty["totals"]["record_count"], 0)
        self.assertEqual(empty["public_collect_status"], "not_requested")

    def test_report_is_pure_offline_and_json_serializable(self):
        data = result([quote(quote_origin="published_tariff_preset_calculation")])
        before = deepcopy(data)
        with patch("socket.create_connection", side_effect=AssertionError("No network in report")):
            report = report_catalog_audit(data)
        self.assertEqual(data, before)
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)
        self.assertFalse(any(key in report for key in ("prices", "provider_results", "source_contexts")))

    def test_invalid_input_structure_uses_safe_configuration_errors(self):
        invalid = (None, [], {}, {"prices": None}, {"prices": [None]}, {"prices": [{}]},
                   {"prices": [], "provider_results": {}}, {"prices": [], "provider_results": [None]},
                   {"prices": [], "provider_results": [{"provider": "x"}, {"provider": "x"}]})
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ConfigurationError):
                report_catalog_audit(data)


if __name__ == "__main__":
    unittest.main()
