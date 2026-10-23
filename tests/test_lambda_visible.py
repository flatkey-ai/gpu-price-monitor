"""Offline regression checks for public/account-visible Lambda reconciliation."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor import Settings, prices_to_csv
from gpu_price_monitor.providers import lambda_console, lambda_console_client, lambda_visible
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-23T03:00:00+00:00"


class LambdaVisibleTests(unittest.TestCase):
    def setUp(self):
        self.html = (FIXTURES / "lambda-complete-pricing-20261021.html").read_text()
        payloads = {
            lambda_console.INSTANCE_TYPES_URL: json.loads((FIXTURES / "lambda-console-instance-types-20261022.json").read_text()),
            lambda_console.RESERVED_CLUSTER_TYPES_URL: json.loads((FIXTURES / "lambda-console-cluster-types-20261022.json").read_text()),
            lambda_console.REGIONS_URL: json.loads((FIXTURES / "lambda-console-regions-20261022.json").read_text()),
        }
        with patch.object(lambda_console_client, "LambdaConsoleSession") as session, \
                patch.object(lambda_console_client, "verify_frontend_version", return_value={"status": "verified"}):
            session.return_value.get_json.side_effect = lambda url: deepcopy(payloads[url])
            self.console = lambda_console_client.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.public = self.enterContext(patch.object(lambda_visible, "fetch_text", return_value=self.html))
        self.account = self.enterContext(patch.object(lambda_console_client, "collect_result",
                                                     side_effect=lambda **kwargs: deepcopy(self.console)))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("Offline test attempted network")))

    def collect(self):
        return lambda_visible.collect_result(settings=Settings(), observed_at=OBSERVED)

    def test_preserves_all_source_observations_and_excludes_only_unpriced_rows(self):
        result = self.collect()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 64)
        coverage = result["catalog_coverage"]
        self.assertEqual((coverage["public_source_record_count"], coverage["public_numeric_quote_count"],
                          coverage["public_unpriced_record_count"], coverage["console_numeric_quote_count"]), (30, 28, 2, 36))
        self.assertTrue(coverage["requested_sources_collected"])
        self.assertFalse(coverage["all_prices_complete"])
        self.assertIsNone(coverage["deduplicated_offer_count"])
        self.assertEqual(len({q["visible_record_id"] for q in result["prices"]}), 64)
        self.assertTrue(all(q["amount"] is not None and q["quote_status"] == "quoted" for q in result["prices"]))
        self.assertTrue(all(row["reason"] == "no_published_numeric_price" for row in coverage["excluded_public_records"]))
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_public_only_four_gpu_b200_is_included_without_borrowing_regions(self):
        result = self.collect()
        quote = next(q for q in result["prices"] if q["gpu_model"] == "B200" and q["gpu_count"] == 4)
        self.assertEqual((quote["amount"], quote["visible_source"]), ("6.79", "public"))
        self.assertEqual(quote["regions"], [])
        self.assertNotIn("price_applicability", quote)
        report = result["catalog_coverage"]["reconciliation"]
        self.assertEqual([(q["gpu_model"], q["gpu_count"]) for q in
                          report["public_without_console_model_count_candidate"]], [("B200", 4)])

    def test_same_model_and_rate_do_not_hide_different_instance_resources(self):
        result = self.collect()
        check = next(check for check in result["catalog_coverage"]["reconciliation"]["on_demand_checks"]
                     if check["public"]["amount"] == "3.29"
                     and any(c["raw_sku"] == "gpu_1x_h100_pcie" for c in check["console_candidates"]))
        candidate = next(c for c in check["console_candidates"] if c["raw_sku"] == "gpu_1x_h100_pcie")
        self.assertTrue(candidate["hourly_rate_equal"])
        self.assertFalse(candidate["shared_specification_fields_equal"])
        self.assertIn({"field": "memory_gib", "public": 225, "console": 200}, candidate["specification_differences"])
        self.assertEqual(result["catalog_coverage"]["reconciliation"]["records_merged"], 0)

    def test_distinct_v100_skus_and_cluster_terms_are_never_deduplicated(self):
        result = self.collect()
        v100 = [q for q in result["prices"] if q["gpu_model"] == "TESLA V100"]
        self.assertEqual(len(v100), 3)
        self.assertEqual(len({q["raw_sku"] for q in v100 if q["visible_source"] == "console"}), 2)
        clusters = [q for q in result["prices"] if q["product_type"] == "gpu_cluster"]
        self.assertEqual(len(clusters), 20)
        self.assertTrue(all(q.get("source_conditions", {}).get("reservation_term")
                            for q in clusters if q["visible_source"] == "public"))
        self.assertTrue(all(q["duration_unverified"] for q in clusters if q["visible_source"] == "console"))
        self.assertEqual(result["catalog_coverage"]["reconciliation"]["reserved_clusters"]["status"], "separate_source_terms")

    def test_price_disagreement_is_reported_without_overwriting_either_source(self):
        self.public.return_value = self.html.replace("$6.99", "$7.99")
        result = self.collect()
        quotes = [q for q in result["prices"] if q["gpu_model"] == "B200" and q["gpu_count"] == 1]
        self.assertEqual({q["amount"] for q in quotes}, {"6.99", "7.99"})
        check = next(c for c in result["catalog_coverage"]["reconciliation"]["on_demand_checks"]
                     if c["public"]["gpu_model"] == "B200" and c["public"]["gpu_count"] == 1)
        self.assertFalse(check["console_candidates"][0]["hourly_rate_equal"])

    def test_exact_gib_conversion_does_not_round_different_storage_into_match(self):
        result = self.collect()
        report = result["catalog_coverage"]["reconciliation"]
        b200 = next(c for c in report["on_demand_checks"] if c["public"]["gpu_model"] == "B200"
                    and c["public"]["gpu_count"] == 1)
        self.assertTrue(b200["console_candidates"][0]["shared_specification_fields_equal"])
        v100 = next(c for c in report["on_demand_checks"] if c["public"]["gpu_model"] == "TESLA V100")
        for candidate in v100["console_candidates"]:
            self.assertIn({"field": "storage_gib", "public": "5939.2", "console": "6041"},
                          candidate["specification_differences"])

    def test_public_failure_keeps_console_but_never_reports_public_missing_offers(self):
        self.public.side_effect = FetchError("network_error", "The pricing source could not be reached.")
        result = self.collect()
        self.assertEqual((result["status"], len(result["prices"])), ("partial", 36))
        self.assertEqual(result["errors"][0]["source_url"], lambda_visible.SOURCE_URL)
        reconciliation = result["catalog_coverage"]["reconciliation"]
        self.assertEqual(reconciliation["status"], "incomplete_sources")
        self.assertEqual(reconciliation["console_without_public_model_count_candidate"], [])
        self.assertFalse(result["catalog_coverage"]["requested_sources_collected"])

    def test_expired_console_is_partial_not_public_fallback_success(self):
        self.console.update(status="failed", prices=[], errors=[{
            "source_url": lambda_console.INSTANCE_TYPES_URL, "code": "authentication_error",
            "message": "Lambda rejected the session.", "retryable": False}])
        for source in self.console["sources"]:
            source["status"] = "failed"
        result = self.collect()
        self.assertEqual((result["status"], len(result["prices"])), ("partial", 28))
        self.assertEqual(result["errors"][0]["code"], "authentication_error")
        self.assertEqual(result["catalog_coverage"]["reconciliation"]["public_without_console_model_count_candidate"], [])

    def test_unverified_frontend_does_not_prevent_raw_catalog_reconciliation(self):
        self.console.update(status="partial", errors=[{
            "source_url": "https://cloud.lambda.ai/instances", "code": "catalog_geography_unverified",
            "message": "The current console version is unverified.", "retryable": False}])
        result = self.collect()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["catalog_coverage"]["requested_sources_collected"])
        self.assertEqual(result["catalog_coverage"]["reconciliation"]["status"], "compared")
        self.assertTrue(result["catalog_coverage"]["reconciliation"]["public_without_console_model_count_candidate"])

    def test_changed_public_markup_fails_closed_without_leaking_page_content(self):
        self.public.return_value = "<h1>private-secret unexpected login</h1>"
        result = self.collect()
        self.assertEqual((result["status"], len(result["prices"])), ("partial", 36))
        self.assertEqual(result["errors"][0]["code"], "parse_failed")
        self.assertNotIn("private-secret", json.dumps(result))

    def test_public_request_is_anonymous_and_reconciliation_does_not_mutate_console(self):
        before = deepcopy(self.console)
        result = self.collect()
        self.assertEqual(self.console, before)
        self.assertEqual(self.public.call_args.kwargs, {})
        self.assertEqual(self.public.call_args.args[0], "https://lambda.ai/pricing")
        self.assertEqual(len(result["sources"]), 4)
        self.assertFalse(any(gap["scope"] == "negotiated_and_capacity_reservation_quotes" for gap in result["gaps"]))

    @staticmethod
    def csv_rows(result, profile):
        text = prices_to_csv(result, profile=profile, bilingual_headers=False)
        return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))

    def test_native_market_csv_excludes_all_public_unknown_geography_and_unavailable_console_rows(self):
        result = self.collect()
        rows = self.csv_rows(result, "market")
        self.assertEqual(len(rows), 20)  # Fixture: six located instances and fourteen clusters.
        self.assertEqual({r["currency"] for r in rows}, {"USD"})
        self.assertEqual({r["unit"] for r in rows}, {"gpu_hour"})
        self.assertTrue(all(r["source_url"].startswith(lambda_console.SOURCE_URL) for r in rows))
        self.assertTrue(all("美国" in r["location"] and "统一目录价" in r["location"] for r in rows))
        self.assertFalse(any("未公布" in r["location"] or "未核实" in r["location"] for r in rows))
        self.assertFalse(any("B200" in r["gpu_model"] and " / 4卡 / " in r["gpu_model"] for r in rows))

    def test_native_catalog_and_full_csv_retain_all_source_prices_without_borrowing_public_geography(self):
        result = self.collect()
        for profile in ("catalog", "full"):
            with self.subTest(profile=profile):
                rows = self.csv_rows(result, profile)
                self.assertEqual(len(rows), 64)
                self.assertTrue(all(r["amount"] for r in rows))
        full = self.csv_rows(result, "full")
        b200 = next(r for r in full if r["gpu_model"] == "B200" and r["gpu_count"] == "4")
        self.assertEqual((b200["amount"], b200["source_url"]), ("6.79", "https://lambda.ai/pricing"))
        self.assertEqual(b200["regions"], "")
        self.assertEqual(b200["compute_countries"], "")
        metadata = json.loads(b200["extra_metadata_json"])
        self.assertEqual(metadata["visible_source"], "public")
        self.assertNotIn("price_applicability", metadata)

    def test_native_market_csv_does_not_admit_unverified_console_geography_after_public_supplement(self):
        result = self.collect()
        for quote in result["prices"]:
            if quote["visible_source"] == "console":
                quote["price_applicability"]["verification_status"] = "frontend_version_unverified"
        self.assertEqual(self.csv_rows(result, "market"), [])
        self.assertEqual(len(self.csv_rows(result, "catalog")), 64)


if __name__ == "__main__":
    unittest.main()
