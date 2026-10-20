"""One-call public collection, with isolated sources and no real network."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main, validate_config
from gpu_price_monitor.collector import IMPLEMENTED_PROVIDERS, provider_source
from gpu_price_monitor.transport import FetchError


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"nebius", "crusoe", "lambda", "ucloud", "autodl",
             "runpod", "digitalocean", "verda", "ebcloud", "azure", "suanli"}


def quote(provider):
    return {
        "provider": provider, "gpu_model": "H100", "gpu_variant": "SXM",
        "gpu_count": None if provider == "runpod" else 1,
        "amount": "2.5", "currency": "CNY" if provider == "ucloud" else "USD",
        "unit": "gpu_month" if provider == "ucloud" else "gpu_hour",
        "billing_mode": "monthly" if provider == "ucloud" else "on_demand",
        "quote_status": "quoted", "regions": [], "zones": [],
        "source_type": provider_source(provider), "availability": "unknown",
    }


class AllCollectionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch("gpu_price_monitor.collector.fetch_text", return_value="synthetic-public-page").start()
        patch("gpu_price_monitor.transport._request_text",
              side_effect=AssertionError("Offline tests may not make requests")).start()
        self.sources = {}
        for name, module in IMPLEMENTED_PROVIDERS.items():
            method = "collect_quotes" if hasattr(module, "collect_quotes") else "parse_prices"
            self.sources[name] = patch.object(module, method, return_value=[quote(name)]).start()

    def cli(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_python_collects_all_public_sources_with_optional_coverage(self):
        result = collect_prices(list(IMPLEMENTED_PROVIDERS), settings=Settings.from_env({}),
                                include_coverage=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual({q["provider"] for q in result["prices"]}, PROVIDERS)
        self.assertEqual(result["coverage"]["scope"], "returned_quotes")
        h100 = next(row for row in result["coverage"]["models"] if row["gpu_model"] == "H100")
        self.assertEqual(h100["status"], "priced")
        self.assertEqual(set(h100["providers"]), PROVIDERS)
        self.assertEqual(set(h100["currencies"]), {"USD", "CNY"})
        self.assertEqual(set(h100["units"]), {"gpu_hour", "gpu_month"})
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertTrue(all(source.call_count == 1 for source in self.sources.values()))

    def test_default_python_response_does_not_add_coverage_or_change_providers(self):
        result = collect_prices(settings=Settings())
        self.assertNotIn("coverage", result)
        self.assertEqual({q["provider"] for q in result["prices"]}, {"nebius", "crusoe"})
        for name in PROVIDERS - {"nebius", "crusoe"}:
            self.sources[name].assert_not_called()

    def test_python_all_alias_is_explicit_and_selects_registered_sources(self):
        result = collect_prices("all", settings=Settings(), include_coverage=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual({q["provider"] for q in result["prices"]}, PROVIDERS)
        with self.assertRaises(ConfigurationError):
            collect_prices("runpod", settings=Settings())

    def test_cli_all_returns_all_sources_as_json_with_coverage(self):
        code, stdout, stderr = self.cli(["collect", "--providers", "all", "--coverage", "--pretty"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        result = json.loads(stdout)
        self.assertEqual({p["provider"] for p in result["provider_results"]}, PROVIDERS)
        self.assertIn("coverage", result)

    def test_cli_all_respects_the_configuration_enabled_subset(self):
        code, stdout, stderr = self.cli([
            "collect", "--providers", "all", "--config", str(ROOT / "configs/collect.free.example.json"),
        ])
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual({p["provider"] for p in result["provider_results"]}, {"lambda", "autodl", "ucloud"})
        self.assertNotIn("coverage", result)

    def test_new_sources_preserve_success_when_one_source_fails(self):
        self.sources["runpod"].side_effect = FetchError("public_api_error", "Public catalog request failed.")
        result = collect_prices(["runpod", "digitalocean", "verda"], settings=Settings(), include_coverage=True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"digitalocean", "verda"})
        self.assertEqual(result["provider_results"][0]["error"]["code"], "public_api_error")
        self.assertEqual(result["coverage"]["collection_status"], "partial")

    def test_card_counts_are_supported_only_for_explicit_instance_configurations(self):
        for name in ("digitalocean", "verda", "ebcloud", "azure"):
            with self.subTest(provider=name):
                result = collect_prices([name], {"gpu_counts": [1]}, settings=Settings())
                self.assertEqual(result["status"], "success")
                self.assertEqual(len(result["prices"]), 1)
        result = collect_prices(["runpod"], {"gpu_counts": [1]}, settings=Settings())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "unsupported_filter")
        self.sources["runpod"].assert_not_called()

    def test_new_sources_do_not_assign_geography_to_public_rates(self):
        for name in ("runpod", "digitalocean", "verda"):
            with self.subTest(provider=name):
                result = collect_prices([name], {"regions": ["us-east-1"]}, settings=Settings())
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["provider_results"][0]["error"]["code"], "unsupported_filter")
                self.sources[name].assert_not_called()

    def test_coverage_option_is_validated_before_any_source_runs(self):
        for value in ("yes", 1, None, []):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                collect_prices(["runpod"], settings=Settings(), include_coverage=value)
        self.assertTrue(all(source.call_count == 0 for source in self.sources.values()))

    def test_public_sources_do_not_require_or_serialize_credentials(self):
        settings = replace(Settings(), lambda_api_key="unused-secret", ucloud_private_key="unused-secret",
                           autodl_token="unused-secret", autodl_storage_state_path="/nonexistent/unused-session")
        result = collect_prices(["runpod", "digitalocean", "verda"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertNotIn("unused-", json.dumps(result))

    def test_all_example_configuration_matches_public_sources(self):
        config_path = ROOT / "configs/collect.all.example.json"
        config = json.loads(config_path.read_text())
        self.assertEqual({p["id"] for p in config["providers"] if p["enabled"]}, PROVIDERS)
        self.assertEqual(validate_config(config), [])
        code, stdout, stderr = self.cli(["validate-config", "--config", str(config_path)])
        self.assertEqual(code, 0)
        self.assertTrue(all(source.call_count == 0 for source in self.sources.values()))


if __name__ == "__main__":
    unittest.main()
