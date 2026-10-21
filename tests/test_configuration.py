"""Configuration behavior; no credentials or network access required."""

from __future__ import annotations

import copy
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings
from gpu_price_monitor.cli import main, validate_config


class EnvironmentTests(unittest.TestCase):
    def test_explicit_empty_mapping_does_not_read_host_credentials(self):
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "host-only-key",
                                    "GPU_PRICE_MONITOR_SOURCE_POLICY": "api_only"}, clear=True):
            settings = Settings.from_env({})
        self.assertIsNone(settings.lambda_api_key)
        self.assertEqual(settings.providers, ("nebius", "crusoe"))
        self.assertEqual(settings.source_policy, "configured")

    def test_source_policy_defaults_and_explicit_values_preserve_source_flags(self):
        self.assertEqual(Settings().source_policy, "configured")
        for policy in ("configured", "api_preferred", "api_only"):
            with self.subTest(policy=policy):
                self.assertEqual(Settings(source_policy=policy).source_policy, policy)
                settings = Settings.from_env({"GPU_PRICE_MONITOR_SOURCE_POLICY": policy,
                                              "LAMBDA_API_KEY": "synthetic-secret"})
                self.assertEqual(settings.source_policy, policy)
                self.assertEqual((settings.nebius_source, settings.lambda_source,
                                  settings.ucloud_source, settings.autodl_source),
                                 ("public", "public", "public", "public"))

    def test_invalid_direct_source_policy_is_a_safe_configuration_error(self):
        for policy in (None, True, 1, [], {}, "API_ONLY", "", "synthetic-secret-policy"):
            with self.subTest(policy=policy), self.assertRaises(ConfigurationError) as raised:
                Settings(source_policy=policy)
            self.assertNotIn("synthetic-secret-policy", str(raised.exception))

    def test_all_credentials_are_optional_and_hidden_from_repr(self):
        names = ("LAMBDA_API_KEY", "NEBIUS_ACCESS_TOKEN", "UCLOUD_PUBLIC_KEY",
                 "UCLOUD_PRIVATE_KEY", "UCLOUD_PROJECT_ID", "UCLOUD_PRICE_TARGETS_JSON",
                 "AUTODL_TOKEN", "AUTODL_STORAGE_STATE_PATH")
        env = {name: f"secret-value-{index}" for index, name in enumerate(names)}
        settings = Settings.from_env(env)
        self.assertEqual(settings.ucloud_private_key, env["UCLOUD_PRIVATE_KEY"])
        for secret in env.values():
            self.assertNotIn(secret, repr(settings))
        self.assertEqual(set(env), set(names))

    def test_request_options_and_provider_selection(self):
        settings = Settings.from_env({
            "GPU_PRICE_MONITOR_PROVIDERS": "Lambda, ucloud",
            "GPU_PRICE_MONITOR_TIMEOUT_SECONDS": "12.5",
            "GPU_PRICE_MONITOR_MAX_RETRIES": "0",
        })
        self.assertEqual(settings.providers, ("lambda", "ucloud"))
        self.assertEqual(settings.timeout_seconds, 12.5)
        self.assertEqual(settings.max_retries, 0)

    def test_invalid_environment_rejected_without_echoing_value(self):
        cases = [
            ("GPU_PRICE_MONITOR_PROVIDERS", "secret-unsupported-provider"),
            ("GPU_PRICE_MONITOR_PROVIDERS", "nebius,nebius"),
            ("GPU_PRICE_MONITOR_PROVIDERS", "nebius,"),
            ("GPU_PRICE_MONITOR_TIMEOUT_SECONDS", "secret-not-number"),
            ("GPU_PRICE_MONITOR_TIMEOUT_SECONDS", "nan"),
            ("GPU_PRICE_MONITOR_TIMEOUT_SECONDS", "inf"),
            ("GPU_PRICE_MONITOR_TIMEOUT_SECONDS", "0"),
            ("GPU_PRICE_MONITOR_MAX_RETRIES", "-1"),
            ("GPU_PRICE_MONITOR_MAX_RETRIES", "11"),
            ("GPU_PRICE_MONITOR_MAX_RETRIES", "secret-not-integer"),
            ("UCLOUD_SOURCE", "secret-unsupported-source"),
            ("GPU_PRICE_MONITOR_SOURCE_POLICY", "secret-unsupported-policy"),
            ("GPU_PRICE_MONITOR_SOURCE_POLICY", ""),
            ("GPU_PRICE_MONITOR_SOURCE_POLICY", "API_ONLY"),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                with self.assertRaises(ConfigurationError) as error:
                    Settings.from_env({name: value})
                if value.startswith("secret-"):
                    self.assertNotIn(value, str(error.exception))

    def test_status_never_prints_credentials(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "do-not-print"}, clear=True):
            with redirect_stdout(output), redirect_stderr(errors):
                code = main(["status"])
        self.assertEqual(code, 0)
        self.assertNotIn("do-not-print", output.getvalue() + errors.getvalue())
        self.assertIn("not implemented", output.getvalue())

    def test_status_shows_policy_and_actual_source_types_without_requests_or_secrets(self):
        output, errors = io.StringIO(), io.StringIO()
        sources = {"lambda": "official_api", "nebius": "official_public_api", "ucloud": "official_quote_api"}
        env = {"GPU_PRICE_MONITOR_PROVIDERS": "lambda,nebius,ucloud",
               "GPU_PRICE_MONITOR_SOURCE_POLICY": "api_preferred",
               "LAMBDA_API_KEY": "synthetic-secret-lambda",
               "NEBIUS_ACCESS_TOKEN": "synthetic-secret-nebius",
               "UCLOUD_PUBLIC_KEY": "synthetic-secret-public",
               "UCLOUD_PRIVATE_KEY": "synthetic-secret-private"}
        with patch.dict(os.environ, env, clear=True), patch(
            "gpu_price_monitor.cli.provider_source", side_effect=lambda provider, settings: sources[provider]
        ) as selected, patch("gpu_price_monitor.cli.collect_prices") as collector, patch(
            "gpu_price_monitor.transport._request_text", side_effect=AssertionError("Status must stay offline")
        ) as transport, redirect_stdout(output), redirect_stderr(errors):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Source policy: api_preferred", output.getvalue())
        for provider, source in sources.items():
            self.assertIn(f"{provider} source type: {source}", output.getvalue())
        self.assertEqual([call.args[0] for call in selected.call_args_list], list(sources))
        self.assertTrue(all(call.args[1].source_policy == "api_preferred" for call in selected.call_args_list))
        self.assertNotIn("synthetic-secret", output.getvalue() + errors.getvalue())
        collector.assert_not_called()
        transport.assert_not_called()


class CollectionBoundaryTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.config = json.loads((root / "configs/collect.example.json").read_text())

    def test_example_valid(self):
        self.assertEqual(validate_config(self.config), [])

    def test_library_rejects_application_service_configuration(self):
        for section in ("schedule", "notifications", "publication", "storage", "upload"):
            with self.subTest(section=section):
                config = copy.deepcopy(self.config)
                config[section] = {}
                self.assertTrue(validate_config(config))

    def test_source_policy_does_not_expand_the_json_configuration_schema(self):
        config = copy.deepcopy(self.config)
        config["source_policy"] = "api_preferred"
        self.assertTrue(validate_config(config))
        config = copy.deepcopy(self.config)
        config["request"]["source_policy"] = "api_only"
        self.assertTrue(validate_config(config))

    def test_filters_validate_conditions_without_enabling_collection(self):
        filters = self.config["providers"][0]["filters"]
        filters.update({"compute_countries": ["US"], "sales_countries": ["DE"],
                        "gpu_counts": [1, 8], "currencies": ["USD"],
                        "billing_modes": ["on_demand"]})
        self.assertEqual(validate_config(self.config), [])
        filters["gpu_counts"] = [True]
        self.assertTrue(validate_config(self.config))

    def test_mismatched_collector_source_cannot_be_enabled(self):
        self.config["providers"][4]["enabled"] = True
        self.config["providers"][4]["planned_source"] = "authorized_browser"
        self.assertTrue(validate_config(self.config))

    def test_extreme_timeout_is_a_validation_error_not_an_overflow(self):
        self.config["request"]["timeout_seconds"] = 10 ** 400
        self.assertTrue(validate_config(self.config))

    def test_malformed_values_return_errors_instead_of_crashing(self):
        for value in (None, [], {}, {"providers": [None]}):
            with self.subTest(value=value):
                self.assertTrue(validate_config(value))
        self.config["providers"][0]["planned_source"] = {}
        self.assertTrue(validate_config(self.config))


if __name__ == "__main__":
    unittest.main()
