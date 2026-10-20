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
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "host-only-key"}, clear=True):
            settings = Settings.from_env({})
        self.assertIsNone(settings.lambda_api_key)
        self.assertEqual(settings.providers, ("nebius", "crusoe"))

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
