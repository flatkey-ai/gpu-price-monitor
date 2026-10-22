"""Account discovery is explicit, bounded and never replaced by public rates."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.collector import provider_source
from gpu_price_monitor.filters import filter_support
from gpu_price_monitor.transport import FetchError


class NebiusCatalogConfigurationTests(unittest.TestCase):
    def test_explicit_catalog_options_load_without_reading_targets(self):
        settings = Settings.from_env({"NEBIUS_SOURCE": "catalog_api", "NEBIUS_CATALOG_BOOT_DISK_GIB": "80",
                                      "NEBIUS_CATALOG_CURRENCY": "ils", "NEBIUS_ACCESS_TOKEN": "private-test-token"})
        self.assertEqual(settings.nebius_source, "catalog_api")
        self.assertEqual(settings.nebius_catalog_boot_disk_gib, 80)
        self.assertEqual(settings.nebius_catalog_currency, "ils")
        self.assertIsNone(settings.nebius_price_targets_json)
        self.assertNotIn("private-test-token", repr(settings))

    def test_invalid_catalog_configuration_does_not_echo_input(self):
        for env in ({"NEBIUS_CATALOG_BOOT_DISK_GIB": "private-invalid"},
                    {"NEBIUS_CATALOG_BOOT_DISK_GIB": "0"},
                    {"NEBIUS_CATALOG_BOOT_DISK_GIB": "32769"},
                    {"NEBIUS_CATALOG_CURRENCY": "private-invalid"}):
            with self.subTest(env=env), self.assertRaises(ConfigurationError) as raised:
                Settings.from_env(env)
            self.assertNotIn("private-invalid", str(raised.exception))
        with self.assertRaises(ConfigurationError):
            Settings(nebius_catalog_boot_disk_gib=True)

    def test_catalog_source_and_filters_stay_offline(self):
        settings = Settings(nebius_source="catalog_api", source_policy="api_only", catalog_scope="complete")
        with patch("gpu_price_monitor.transport._request_text", side_effect=AssertionError("No I/O")):
            self.assertEqual(provider_source("nebius", settings), "official_quote_api")
            support = filter_support("nebius", {"regions": ["eu-north1"], "compute_countries": ["FI"],
                                                "gpu_counts": [8]}, settings=settings)
        self.assertTrue(all(value["status"] == "applied_locally" for value in support.values()))

    def test_catalog_failure_never_becomes_public_or_derived_price(self):
        settings = Settings(providers=("nebius",), nebius_source="catalog_api", source_policy="api_only", catalog_scope="complete")
        with patch("gpu_price_monitor.providers.nebius_account_catalog.collect_result",
                   side_effect=FetchError("authentication_error", "Configured credentials were rejected.")), \
                patch("gpu_price_monitor.providers.nebius_spot.collect_quotes", side_effect=AssertionError("No fallback")), \
                patch("gpu_price_monitor.providers.nebius_catalog_expanded.collect_result", side_effect=AssertionError("No fallback")):
            result = collect_prices(settings=settings)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["error"]["code"], "authentication_error")
        self.assertNotIn("source_policy_excluded", json.dumps(result))

    def test_cli_explicit_source_passes_account_discovery_setting(self):
        result = {"status": "success", "prices": [], "provider_results": []}
        with patch.dict(os.environ, {}, clear=True), patch("gpu_price_monitor.cli.collect_prices", return_value=result) as collect, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["collect", "--providers", "nebius", "--nebius-source", "catalog_api", "--source-policy", "api_only"])
        self.assertEqual(code, 0)
        self.assertEqual(collect.call_args.kwargs["settings"].nebius_source, "catalog_api")

    def test_incomplete_discovery_without_transport_errors_does_not_claim_success(self):
        settings = Settings(providers=("nebius",), nebius_source="catalog_api", source_policy="api_only")
        outcome = {"prices": [], "errors": [], "status": "failed",
                   "gaps": [{"scope": "authorized_projects", "status": "no_accessible_projects"}]}
        with patch("gpu_price_monitor.providers.nebius_account_catalog.collect_result", return_value=outcome):
            result = collect_prices(settings=settings)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "partial_collection")
        self.assertEqual(result["provider_results"][0]["source_errors"][0]["code"], "incomplete_catalog")


if __name__ == "__main__":
    unittest.main()
