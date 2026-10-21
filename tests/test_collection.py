"""Offline API/CLI contract checks using minimal public source fixtures."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-15T09:15:00+00:00"


def fixture_fetch(url, settings):
    name = "nebius-pricing.md" if "nebius" in url else "crusoe-pricing.html"
    return (FIXTURES / name).read_text()


def spot_quote(observed_at=OBSERVED, **changes):
    quote = {
        "provider": "nebius", "product_type": "gpu_instance", "gpu_model": "H100",
        "raw_name": "Preemptible NVIDIA® H100 NVLink", "raw_sku": "gpu-h100-sxm",
        "amount": "1.25", "currency": "USD", "unit": "gpu_hour", "billing_mode": "spot",
        "price_basis": "advertised_per_gpu", "quote_status": "quoted", "gpu_count": None,
        "regions": ["eu-north1"], "zones": [], "compute_countries": ["FI"],
        "geographic_scope": "regions", "source_type": "official_public_api",
        "source_url": "https://api.nebius.cloud/billing/v1alpha1/spot-price",
        "observed_at": observed_at, "effective_from": observed_at, "source_snapshot_at": observed_at,
        "availability": "unknown",
    }
    quote.update(changes)
    return quote


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(max_retries=0)
        self.fetch = patch("gpu_price_monitor.collector.fetch_text", side_effect=fixture_fetch)
        self.clock = patch("gpu_price_monitor.collector._now", return_value=OBSERVED)
        self.spot = patch("gpu_price_monitor.providers.nebius_spot.collect_quotes",
                          side_effect=lambda *, settings, observed_at: [spot_quote(observed_at)])
        self.transport = patch("gpu_price_monitor.transport._request_text",
                               side_effect=AssertionError("Offline tests may not make requests"))
        self.fetcher = self.fetch.start()
        self.clock.start()
        self.spotter = self.spot.start()
        self.transport.start()
        self.addCleanup(self.fetch.stop)
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.spot.stop)
        self.addCleanup(self.transport.stop)

    def test_python_api_returns_serializable_quotes_with_current_price(self):
        result = collect_prices(filters={"gpu_models": ["h100"], "currencies": ["usd"], "billing_modes": ["on_demand"]}, settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual([(q["provider"], q["amount"]) for q in result["prices"]], [("nebius", "4.50"), ("crusoe", "3.90")])
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertTrue(all(q["observed_at"] == OBSERVED for q in result["prices"]))
        nebius = result["prices"][0]
        self.assertEqual(nebius["regions"], [])
        self.assertEqual(nebius["compute_countries"], [])
        self.assertEqual(nebius["coverage_regions"], ["eu-north1"])
        self.assertEqual(nebius["coverage_countries"], ["FI"])
        self.assertEqual(result["comparison"]["eligible_quote_count"], 0)
        self.assertEqual(result["market_comparison"], {
            "scope": "catalog_and_regional_gpu_hour", "eligible_quote_count": 2,
            "regional_quote_count": 0, "catalog_quote_count": 2, "excluded_quote_count": 0,
            "providers_with_quotes": ["nebius", "crusoe"],
        })
        self.assertEqual([p["market_quote_count"] for p in result["provider_results"]], [1, 1])
        self.assertEqual([p["regional_hourly_quote_count"] for p in result["provider_results"]], [0, 0])

    def test_partial_failure_keeps_other_provider_prices_and_hides_error_body(self):
        def fetch(url, settings):
            if "crusoe" in url:
                raise FetchError("network_error", "The pricing source could not be reached.", True)
            return fixture_fetch(url, settings)
        self.fetcher.side_effect = fetch
        result = collect_prices(settings=self.settings)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["prices"])
        self.assertEqual({q["provider"] for q in result["prices"]}, {"nebius"})
        self.assertTrue(result["provider_results"][1]["error"]["retryable"])

    def test_region_filter_matches_only_verified_nebius_spot_price(self):
        result = collect_prices(filters={"regions": ["eu-north1"]}, settings=self.settings)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all("eu-north1" in q["regions"] for q in result["prices"]))
        self.assertEqual([(q["amount"], q["billing_mode"]) for q in result["prices"]], [("1.25", "spot")])
        self.assertTrue(all(q["region_price_verified"] for q in result["prices"]))
        self.assertEqual(result["provider_results"][1]["error"]["code"], "unsupported_filter")
        self.assertEqual(self.fetcher.call_count, 1)

    def test_country_filter_uses_actual_spot_country_not_currency_or_platform_coverage(self):
        result = collect_prices(filters={"compute_countries": ["US"]}, settings=self.settings)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")
        self.assertIsNone(result["provider_results"][0]["error"])
        self.assertEqual(result["provider_results"][1]["error"]["code"], "unsupported_filter")
        self.assertEqual(self.fetcher.call_count, 1)
        self.spotter.assert_called_once()

    def test_unlocated_rows_are_excluded_from_price_region_candidates(self):
        content = (FIXTURES / "nebius-pricing.md").read_text()
        content = content.replace("The platform is only available in the `eu-north1` region.", "Region not stated.")
        self.fetcher.side_effect = None
        self.fetcher.return_value = content
        self.spotter.side_effect = None
        self.spotter.return_value = [spot_quote(regions=[], compute_countries=[])]
        result = collect_prices(["nebius"], {"gpu_models": ["H100"], "regions": ["eu-north1"]}, settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")
        self.assertIsNone(result["provider_results"][0]["error"])
        self.assertGreater(result["provider_results"][0]["excluded_unbound_geography_count"], 0)

    def test_spot_api_failure_fails_whole_nebius_source_and_preserves_other_provider(self):
        self.spotter.side_effect = FetchError("network_error", "The pricing source could not be reached.", True)
        result = collect_prices(settings=self.settings)
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"crusoe"})
        self.assertEqual(result["provider_results"][0]["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "network_error")
        self.assertTrue(result["provider_results"][0]["error"]["retryable"])

    def test_no_matches_is_distinct_from_parse_failure(self):
        result = collect_prices(filters={"gpu_models": ["UNLISTED"]}, settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        self.assertTrue(all(p["status"] == "no_matches" and p["error"] is None for p in result["provider_results"]))
        self.fetcher.return_value = "<html>login</html>"
        self.fetcher.side_effect = None
        failed = collect_prices(settings=self.settings)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(all(p["error"]["code"] == "parse_failed" for p in failed["provider_results"]))

    def test_missing_optional_browser_does_not_erase_supported_results(self):
        with patch("gpu_price_monitor.providers.autodl.collect_quotes",
                   side_effect=FetchError("browser_dependency_missing", "Install the optional browser extra.")):
            result = collect_prices(["nebius", "autodl"], settings=self.settings)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["provider_results"][1]["error"]["code"], "browser_dependency_missing")

    def test_invalid_call_configuration_fails_before_network(self):
        for args in ({"providers": []}, {"providers": "nebius"}, {"filters": {"upload": ["secret"]}}, {"filters": {"gpu_counts": [True]}}):
            with self.subTest(args=args), self.assertRaises(ConfigurationError):
                collect_prices(settings=self.settings, **args)
        self.fetcher.assert_not_called()
        self.spotter.assert_not_called()

    def test_explicit_settings_do_not_read_environment(self):
        with patch.dict("os.environ", {"GPU_PRICE_MONITOR_PROVIDERS": "invalid"}, clear=True):
            result = collect_prices(settings=self.settings)
        self.assertEqual(result["status"], "success")

    def test_cli_stdout_is_json_with_partial_failure_exit_code(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["collect", "--providers", "nebius,crusoe", "--region", "eu-north1"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "partial")
        self.assertIn("unsupported_filter", stderr.getvalue())

    def test_cli_config_and_command_filters_produce_current_quotes(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        config = str(Path(__file__).parents[1] / "configs/collect.example.json")
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["collect", "--config", config, "--gpu", "H100", "--currency", "USD", "--billing-mode", "on_demand"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["prices"]), 2)
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_explicit_coverage_filters_do_not_turn_catalog_prices_into_region_quotes(self):
        base = ["collect", "--providers", "nebius", "--gpu", "H100", "--currency", "USD",
                "--billing-mode", "on_demand"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(base + ["--coverage-region", "eu-north1", "--coverage-country", "fi"])
        self.assertEqual(code, 0)
        coverage = json.loads(stdout.getvalue())
        self.assertEqual(len(coverage["prices"]), 1)
        self.assertEqual(coverage["prices"][0]["coverage_countries"], ["FI"])
        self.assertEqual(coverage["prices"][0]["price_scope"], "platform_coverage")
        self.assertEqual(coverage["prices"][0]["regions"], [])
        self.assertEqual(coverage["prices"][0]["compute_countries"], [])
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(base + ["--region", "eu-north1", "--country", "FI"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["provider_results"][0]["status"], "no_matches")
        self.assertEqual(json.loads(stdout.getvalue())["prices"], [])

    def test_cli_configuration_error_is_machine_readable_and_does_not_leak(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": "private-token"}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["collect"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "configuration_error")
        self.assertNotIn("private-token", stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
