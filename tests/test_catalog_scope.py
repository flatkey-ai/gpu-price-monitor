"""Complete catalogs retain independent-source evidence without implicit fallback."""

from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

from gpu_price_monitor.collector import collect_prices, provider_source
from gpu_price_monitor.providers import (
    crusoe, crusoe_account, lambda_cloud, lambda_clusters, lambda_public,
    nebius, nebius_catalog_expanded, nebius_quote, nebius_spot,
)
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


OBSERVED = "2026-10-21T10:00:00+00:00"


def quote(provider, *, source_type="public_page", regional=False, **changes):
    return {"provider": provider, "gpu_model": "H100", "gpu_count": 8,
            "amount": "2.50", "currency": "USD", "unit": "gpu_hour",
            "billing_mode": "on_demand", "quote_status": "quoted",
            "price_basis": "advertised_per_gpu", "observed_at": OBSERVED,
            "source_url": "https://example.test/official-prices", "source_type": source_type,
            "regions": ["eu-north1"] if regional else [],
            "compute_countries": ["FI"] if regional else [],
            "geographic_scope": "regional" if regional else "unspecified", **changes}


def expanded_outcome(*, errors=None, prices=None):
    return {"prices": prices if prices is not None else [quote(
                "nebius", source_type="official_pricing_document", regions=["eu-north1"],
                compute_countries=["FI"], geographic_scope="platform_coverage")],
            "errors": errors or [], "status": "partial" if errors else "ok",
            "coverage": {"preset_count": 26, "reported_spot_api_quote_count": 12},
            "catalog_coverage": {"summary": {"preset_count": 26},
                                 "pricing_source_url": nebius_catalog_expanded.SOURCE_URL},
            "gaps": [{"scope": "account_specific_and_contract_prices", "status": "authentication_required"}]}


def audit_outcome():
    return {"prices": [], "errors": [], "status": "ok", "audit_only": True,
            "source_url": crusoe_account.SOURCE_URL, "source_type": "official_api",
            "contract_records": [{"account_scope": "account_contract_audit", "price_as_returned": "1000",
                                  "price_admissible_as_gpu_hour_quote": False}],
            "contract_record_count": 1, "pricing_limitations": ["Currency and hourly unit are unverified."]}


class CompleteCatalogCollectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("gpu_price_monitor.collector._now", return_value=OBSERVED))
        self.stack.enter_context(patch("gpu_price_monitor.transport._request_text",
                                       side_effect=AssertionError("Unexpected HTTP in offline test")))
        self.html = self.block("gpu_price_monitor.collector.fetch_text")
        self.expanded = self.block("gpu_price_monitor.providers.nebius_catalog_expanded.collect_result")
        self.spot = self.block("gpu_price_monitor.providers.nebius_spot.collect_quotes")
        self.catalog = self.block("gpu_price_monitor.providers.nebius_catalog.collect_quotes")
        self.signed_nebius = self.block("gpu_price_monitor.providers.nebius_quote.collect_quotes")
        self.lambda_api = self.block("gpu_price_monitor.providers.lambda_cloud.collect_quotes")
        self.clusters = self.block("gpu_price_monitor.providers.lambda_clusters.collect_quotes")
        self.account = self.block("gpu_price_monitor.providers.crusoe_account.collect_result")
        self.browser = self.block("gpu_price_monitor.browser.fetch_autodl_pages")

    def block(self, target):
        return self.stack.enter_context(patch(target, side_effect=AssertionError("Unexpected source call")))

    @staticmethod
    def allow(mock, result):
        mock.side_effect = None
        mock.return_value = deepcopy(result)

    def collect(self, provider, **options):
        settings = Settings(providers=(provider,), catalog_scope="complete", **options)
        result = collect_prices(settings=settings)
        source = result["provider_results"][0]
        self.assertEqual(result["execution"]["catalog_scope"], "complete")
        self.assertEqual(source["source_type"], provider_source(provider, settings))
        return result, source

    def test_complete_nebius_uses_result_and_preserves_document_evidence_and_gaps(self):
        for policy in ("configured", "api_preferred"):
            with self.subTest(policy=policy):
                self.allow(self.expanded, expanded_outcome())
                result, source = self.collect("nebius", source_policy=policy)
                self.assertEqual(result["status"], "success")
                self.assertEqual(source["source_type"], "official_public_sources")
                self.assertIn("official_pricing_document", source["source_types"])
                self.assertEqual(source["catalog_coverage"]["summary"]["preset_count"], 26)
                self.assertEqual(source["coverage"]["reported_spot_api_quote_count"], 12)
                self.assertEqual(source["source_contexts"][0]["source_type"], "official_pricing_document")
                self.assertEqual(source["gaps"][0]["status"], "authentication_required")
                catalog_quote = result["prices"][0]
                self.assertEqual(catalog_quote["regions"], [])
                self.assertEqual(catalog_quote["compute_countries"], [])
                self.assertEqual(catalog_quote["coverage_regions"], ["eu-north1"])
                self.assertFalse(catalog_quote["region_price_verified"])
        self.spot.assert_not_called()
        self.catalog.assert_not_called()
        self.html.assert_not_called()

    def test_complete_nebius_partial_keeps_prices_errors_and_coverage(self):
        error = {"source": "regional_spot_api", "code": "http_503", "message": "Unavailable", "retryable": True}
        self.allow(self.expanded, expanded_outcome(errors=[error]))
        result, source = self.collect("nebius", source_policy="api_preferred")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(source["source_errors"], [error])
        self.assertEqual(source["errors"], [error])
        self.assertTrue(source["error"]["retryable"])

    def test_complete_nebius_all_failed_keeps_diagnostics(self):
        self.allow(self.expanded, expanded_outcome(errors=[{"code": "http_error", "message": "Unavailable"}], prices=[]))
        result, source = self.collect("nebius")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertIn("catalog_coverage", source)
        self.assertIn("gaps", source)
        self.assertEqual(source["error"]["code"], "partial_collection")

    def test_api_only_nebius_uses_only_spot_and_marks_missing_public_catalog(self):
        self.allow(self.spot, [quote("nebius", source_type="official_public_api", regional=True)])
        result, source = self.collect("nebius", source_policy="api_only")
        self.assertEqual(result["status"], "success")
        self.assertEqual(source["source_type"], "official_public_api")
        self.assertEqual(source["gaps"][0]["scope"], "public_on_demand_preset_catalog")
        self.assertEqual(source["gaps"][0]["status"], "source_policy_excluded")
        self.expanded.assert_not_called()
        self.html.assert_not_called()

    def test_complete_nebius_explicit_signed_path_is_preserved(self):
        self.allow(self.signed_nebius, [quote("nebius", source_type="official_quote_api", regional=True)])
        result, source = self.collect("nebius", nebius_source="api", source_policy="api_preferred")
        self.assertEqual(result["status"], "success")
        self.assertEqual(source["source_type"], "official_quote_api")
        self.expanded.assert_not_called()
        self.spot.assert_not_called()

    def test_standard_nebius_keeps_document_and_spot_path(self):
        self.allow(self.html, "synthetic official document")
        self.allow(self.spot, [quote("nebius", source_type="official_public_api", regional=True)])
        with patch.object(nebius, "parse_prices", return_value=[quote("nebius", source_type="public_documentation")]):
            result = collect_prices(settings=Settings(providers=("nebius",)))
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["execution"]["catalog_scope"], "standard")
        self.expanded.assert_not_called()

    def test_complete_lambda_api_adds_reserved_catalog_after_success(self):
        self.allow(self.lambda_api, [quote("lambda", source_type="official_api")])
        self.allow(self.clusters, [quote("lambda", billing_mode="reserved", product_type="gpu_cluster",
                                        gpu_count=None, minimum_commitment={"duration": {"amount": 2, "unit": "week"}})])
        result, source = self.collect("lambda", source_policy="api_preferred", lambda_api_key="synthetic-private-key")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["prices"][1]["billing_mode"], "reserved")
        self.assertEqual(source["source_types"], ["official_api", "public_page"])
        self.assertEqual(source["catalog_coverage"]["account_instance_quote_count"], 1)
        self.assertEqual(source["catalog_coverage"]["public_cluster_record_count"], 1)
        self.assertEqual(source["catalog_coverage"]["collected_record_count"], 2)
        self.assertEqual(source["api_endpoint"], lambda_cloud.SOURCE_URL)
        self.html.assert_not_called()

    def test_complete_lambda_cluster_failure_retains_account_quotes(self):
        self.allow(self.lambda_api, [quote("lambda", source_type="official_api")])
        self.clusters.side_effect = FetchError("http_503", "Cluster catalog unavailable", retryable=True)
        result, source = self.collect("lambda", source_policy="api_preferred", lambda_api_key="synthetic-key")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(source["source_errors"][0]["code"], "http_503")
        self.assertEqual(source["gaps"][0]["status"], "collection_failed")
        self.html.assert_not_called()

    def test_complete_lambda_malformed_cluster_does_not_discard_account_quotes(self):
        self.allow(self.lambda_api, [quote("lambda", source_type="official_api")])
        self.allow(self.clusters, [quote("lambda", amount="NaN")])
        result, source = self.collect("lambda", source_policy="api_preferred", lambda_api_key="synthetic-key")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(source["source_errors"][0]["code"], "parse_failed")

    def test_complete_lambda_api_failure_never_fetches_cluster_or_page(self):
        self.lambda_api.side_effect = FetchError("http_401", "API authentication rejected")
        result, source = self.collect("lambda", source_policy="api_preferred", lambda_api_key="synthetic-key")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(source["error"]["code"], "http_401")
        self.clusters.assert_not_called()
        self.html.assert_not_called()

    def test_api_only_lambda_has_no_html_supplement_and_reports_gap(self):
        self.allow(self.lambda_api, [quote("lambda", source_type="official_api")])
        result, source = self.collect("lambda", source_policy="api_only", lambda_api_key="synthetic-key")
        self.assertEqual(result["status"], "success")
        self.assertEqual(source["source_type"], "official_api")
        self.assertEqual(source["gaps"][0]["scope"], "public_reserved_cluster_catalog")
        self.clusters.assert_not_called()
        self.html.assert_not_called()

    def test_complete_lambda_public_does_not_repeat_embedded_cluster_catalog(self):
        self.allow(self.html, "synthetic complete public page")
        with patch.object(lambda_public, "parse_prices", return_value=[quote("lambda")]) as parser:
            result, _ = self.collect("lambda", source_policy="api_preferred")
        self.assertEqual(result["status"], "success")
        self.assertEqual(parser.call_count, 1)
        self.clusters.assert_not_called()
        self.lambda_api.assert_not_called()

    def test_crusoe_account_records_are_audit_only_and_never_quotes(self):
        self.allow(self.account, audit_outcome())
        result, source = self.collect("crusoe", crusoe_source="account")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["market_comparison"]["eligible_quote_count"], 0)
        self.assertTrue(source["audit_only"])
        self.assertEqual(source["contract_record_count"], 1)
        self.assertFalse(source["contract_records"][0]["price_admissible_as_gpu_hour_quote"])
        self.assertEqual(source["source_type"], "official_api")
        self.assertIn("{organization_id}", source["api_endpoint"])
        self.html.assert_not_called()

    def test_crusoe_combined_keeps_public_prices_and_separate_contract_records(self):
        self.allow(self.html, "public prices")
        self.allow(self.account, audit_outcome())
        with patch.object(crusoe, "parse_prices", return_value=[quote("crusoe")]):
            result, source = self.collect("crusoe", crusoe_source="combined")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 1)
        self.assertTrue(source["account_audit_only"])
        self.assertNotIn("audit_only", source)
        self.assertEqual(source["contract_record_count"], 1)
        self.assertEqual(source["source_types"], ["public_page", "official_api"])

    def test_crusoe_combined_missing_credentials_is_partial_and_does_not_hide_prices(self):
        self.allow(self.html, "public prices")
        # Use the real credential gate, while every HTTP transport stays blocked.
        self.account.side_effect = None
        self.account.side_effect = lambda **kwargs: self.real_account(**kwargs)
        with patch.object(crusoe, "parse_prices", return_value=[quote("crusoe")]):
            result, source = self.collect("crusoe", crusoe_source="combined")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(source["source_errors"][0]["code"], "configuration_error")
        self.assertIn("CRUSOE_SECRET_KEY", source["source_errors"][0]["message"])

    def test_crusoe_combined_public_failure_retains_successful_audit(self):
        self.html.side_effect = FetchError("http_503", "Public price page unavailable")
        self.allow(self.account, audit_outcome())
        result, source = self.collect("crusoe", crusoe_source="combined")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["prices"], [])
        self.assertEqual(source["contract_record_count"], 1)
        self.assertEqual(source["source_errors"][0]["code"], "http_503")

    def test_crusoe_account_rejects_any_attempt_to_emit_audit_as_quote(self):
        outcome = audit_outcome()
        outcome["prices"] = [quote("crusoe", source_type="official_api")]
        self.allow(self.account, outcome)
        result, source = self.collect("crusoe", crusoe_source="account")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual(source["error"]["code"], "parse_failed")

    def test_api_only_combined_crusoe_reads_account_only_and_marks_public_gap(self):
        self.allow(self.account, audit_outcome())
        result, source = self.collect("crusoe", crusoe_source="combined", source_policy="api_only")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        self.assertEqual(source["source_type"], "official_api")
        self.assertEqual(source["gaps"][0]["scope"], "public_gpu_price_catalog")
        self.html.assert_not_called()

    # Save the unpatched callable before setUp enters its mock.
    real_account = staticmethod(crusoe_account.collect_result)


if __name__ == "__main__":
    unittest.main()
