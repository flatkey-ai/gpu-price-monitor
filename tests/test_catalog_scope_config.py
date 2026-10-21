"""Catalog scope and account-source configuration remain explicit and offline."""

from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import fields
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings
from gpu_price_monitor.cli import main, validate_config


CRUSOE_ENV = {
    "CRUSOE_ACCESS_KEY_ID": "synthetic-private-access-key",
    "CRUSOE_SECRET_KEY": "synthetic-private-secret-key",
    "CRUSOE_ORGANIZATION_ID": "synthetic-private-organization-id",
}
COLLECTION = {
    "schema_version": 1,
    "collected_at": "2026-10-21T08:33:00+00:00",
    "status": "success",
    "prices": [],
    "provider_results": [],
}
CONFIG = {
    "schema_version": 1,
    "request": {"timeout_seconds": 30, "max_retries": 2},
    "providers": [{"id": "crusoe", "enabled": True,
                   "planned_source": "public_page", "filters": {}}],
}


class CatalogScopeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.transport = self.stack.enter_context(patch(
            "gpu_price_monitor.transport._request_text",
            side_effect=AssertionError("Configuration tests must not make HTTP requests"),
        ))
        self.socket = self.stack.enter_context(patch(
            "socket.create_connection",
            side_effect=AssertionError("Configuration tests must not open sockets"),
        ))

    def assert_no_network(self):
        self.transport.assert_not_called()
        self.socket.assert_not_called()

    def assert_complete_scope_description(self, text):
        """Keep the boundary meaningful without freezing a particular sentence."""
        normalized = " ".join(text.lower().split())
        self.assertRegex(normalized, r"(?:official|published).{0,80}(?:tariff|rate)")
        self.assertRegex(normalized, r"reserved|reservation|commitment")
        self.assertIsNone(re.search(
            r"(?:all|entire|whole)\s+(?:market|account)\s+(?:prices|quotes)\s+(?:acquired|collected|covered)",
            normalized,
        ))

    def run_cli(self, args, env=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env or {}, clear=True), \
                patch("gpu_price_monitor.cli.collect_prices", return_value=deepcopy(COLLECTION)) as collect, \
                patch("gpu_price_monitor.cli._load_config", return_value=deepcopy(CONFIG)) as load, \
                redirect_stdout(output), redirect_stderr(errors):
            code = main(args)
        self.assert_no_network()
        return code, output.getvalue(), errors.getvalue(), collect, load

    def test_standard_scope_is_the_compatible_default(self):
        self.assertEqual(Settings().catalog_scope, "standard")
        self.assertEqual(Settings.from_env({}).catalog_scope, "standard")
        self.assertEqual(Settings().crusoe_source, "public")
        self.assertEqual(Settings.from_env({}).crusoe_source, "public")
        self.assert_no_network()

    def test_catalog_scope_accepts_both_explicit_modes(self):
        for scope in ("standard", "complete"):
            with self.subTest(scope=scope):
                self.assertEqual(Settings(catalog_scope=scope).catalog_scope, scope)
                self.assertEqual(Settings.from_env({
                    "GPU_PRICE_MONITOR_CATALOG_SCOPE": scope,
                }).catalog_scope, scope)
        self.assert_no_network()

    def test_direct_invalid_catalog_scope_is_a_safe_configuration_error(self):
        for scope in (None, True, 1, [], {}, "", "COMPLETE", "private-invalid-scope"):
            with self.subTest(scope=scope), self.assertRaises(ConfigurationError) as raised:
                Settings(catalog_scope=scope)
            self.assertNotIn("private-invalid-scope", str(raised.exception))
        self.assert_no_network()

    def test_invalid_or_empty_scope_environment_does_not_fall_back(self):
        for value in ("", " ", "COMPLETE", "private-invalid-scope"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as raised:
                Settings.from_env({"GPU_PRICE_MONITOR_CATALOG_SCOPE": value})
            self.assertNotIn("private-invalid-scope", str(raised.exception))
        self.assert_no_network()

    def test_explicit_empty_process_scope_overrides_a_valid_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "catalog.env"
            env_file.write_text("GPU_PRICE_MONITOR_CATALOG_SCOPE=complete\n", encoding="utf-8")
            self.assertEqual(Settings.from_env({}, env_file=env_file).catalog_scope, "complete")
            with self.assertRaises(ConfigurationError):
                Settings.from_env({"GPU_PRICE_MONITOR_CATALOG_SCOPE": ""}, env_file=env_file)
        self.assert_no_network()

    def test_explicit_environment_mapping_does_not_inherit_host_scope_or_credentials(self):
        with patch.dict(os.environ, {**CRUSOE_ENV, "GPU_PRICE_MONITOR_CATALOG_SCOPE": "complete",
                                    "CRUSOE_SOURCE": "combined"}, clear=True):
            settings = Settings.from_env({})
        self.assertEqual(settings.catalog_scope, "standard")
        self.assertEqual(settings.crusoe_source, "public")
        self.assertIsNone(settings.crusoe_access_key_id)
        self.assertIsNone(settings.crusoe_secret_key)
        self.assertIsNone(settings.crusoe_organization_id)
        self.assert_no_network()

    def test_crusoe_credentials_are_optional_and_hidden_from_repr(self):
        settings = Settings.from_env(CRUSOE_ENV)
        credential_fields = {
            "crusoe_access_key_id": "CRUSOE_ACCESS_KEY_ID",
            "crusoe_secret_key": "CRUSOE_SECRET_KEY",
            "crusoe_organization_id": "CRUSOE_ORGANIZATION_ID",
        }
        field_options = {item.name: item for item in fields(Settings)}
        for field_name, env_name in credential_fields.items():
            with self.subTest(field=field_name):
                self.assertEqual(getattr(settings, field_name), CRUSOE_ENV[env_name])
                self.assertFalse(field_options[field_name].repr)
                self.assertIsNone(getattr(Settings(), field_name))
                self.assertNotIn(CRUSOE_ENV[env_name], repr(settings))
        self.assert_no_network()

    def test_blank_crusoe_credentials_are_not_credentials(self):
        settings = Settings.from_env({name: "  " for name in CRUSOE_ENV})
        self.assertIsNone(settings.crusoe_access_key_id)
        self.assertIsNone(settings.crusoe_secret_key)
        self.assertIsNone(settings.crusoe_organization_id)
        self.assert_no_network()

    def test_crusoe_source_supports_public_account_and_combined(self):
        for source in ("public", "account", "combined"):
            with self.subTest(source=source):
                self.assertEqual(Settings(crusoe_source=source).crusoe_source, source)
                self.assertEqual(Settings.from_env({"CRUSOE_SOURCE": source}).crusoe_source, source)
        self.assert_no_network()

    def test_invalid_crusoe_source_is_rejected_without_echoing_environment_values(self):
        for value in ("", "ACCOUNT", "private-invalid-source"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as raised:
                Settings.from_env({"CRUSOE_SOURCE": value})
            self.assertNotIn("private-invalid-source", str(raised.exception))
        self.assert_no_network()

    def test_cli_catalog_scope_overrides_the_environment_on_all_commands(self):
        for scope, env_scope in (("standard", "complete"), ("complete", "standard")):
            for command in ("collect", "status", "validate-config"):
                args = [command, "--catalog-scope", scope]
                if command == "validate-config":
                    args.extend(["--config", "not-read.json"])
                with self.subTest(command=command, scope=scope):
                    code, output, errors, collect, load = self.run_cli(
                        args, {"GPU_PRICE_MONITOR_CATALOG_SCOPE": env_scope})
                    self.assertEqual(code, 0, errors)
                    if command == "collect":
                        self.assertEqual(collect.call_args.kwargs["settings"].catalog_scope, scope)
                        self.assertEqual(json.loads(output), COLLECTION)
                        load.assert_not_called()
                    elif command == "status":
                        self.assertIn(f"Catalog scope: {scope}", output)
                        collect.assert_not_called()
                        load.assert_not_called()
                    else:
                        self.assertEqual(load.call_args.args[1].catalog_scope, scope)
                        collect.assert_not_called()

    def test_collect_cli_explicit_crusoe_source_overrides_the_environment(self):
        for source in ("public", "account", "combined"):
            with self.subTest(source=source):
                code, output, errors, collect, _ = self.run_cli(
                    ["collect", "--providers", "crusoe", "--crusoe-source", source],
                    {"CRUSOE_SOURCE": "combined" if source == "public" else "public"},
                )
                self.assertEqual(code, 0, errors)
                self.assertEqual(collect.call_args.kwargs["settings"].crusoe_source, source)
                self.assertEqual(json.loads(output), COLLECTION)

    def test_status_shows_non_secret_scope_and_crusoe_source_without_collection(self):
        code, output, errors, collect, load = self.run_cli(["status"], {
            **CRUSOE_ENV, "GPU_PRICE_MONITOR_CATALOG_SCOPE": "complete", "CRUSOE_SOURCE": "combined",
        })
        self.assertEqual(code, 0, errors)
        self.assertIn("Catalog scope: complete", output)
        self.assertIn("Crusoe source: combined", output)
        for value in CRUSOE_ENV.values():
            self.assertNotIn(value, output + errors)
        self.assert_complete_scope_description(output)
        collect.assert_not_called()
        load.assert_not_called()

    def test_complete_collect_explains_scope_on_stderr_and_keeps_stdout_json(self):
        code, output, errors, collect, _ = self.run_cli(["collect", "--catalog-scope", "complete"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), COLLECTION)
        self.assertEqual(collect.call_args.kwargs["settings"].catalog_scope, "complete")
        self.assert_complete_scope_description(errors)

    def test_command_help_accepts_scope_choices_and_explains_complete_mode(self):
        for command in ("collect", "status", "validate-config"):
            with self.subTest(command=command):
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn("--catalog-scope {standard,complete}", output.getvalue())
                self.assert_complete_scope_description(output.getvalue())
        self.assert_no_network()

    def test_invalid_cli_scope_uses_argparse_choices_before_collection(self):
        for command in ("collect", "status", "validate-config"):
            with self.subTest(command=command):
                output, errors = io.StringIO(), io.StringIO()
                args = [command, "--catalog-scope", "unsupported"]
                if command == "validate-config":
                    args.extend(["--config", "not-read.json"])
                with patch("gpu_price_monitor.cli.collect_prices") as collect, \
                        redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    main(args)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("invalid choice", errors.getvalue())
                self.assertEqual(output.getvalue(), "")
                collect.assert_not_called()
        self.assert_no_network()

    def test_catalog_scope_does_not_expand_json_configuration_schema(self):
        self.assertEqual(validate_config(CONFIG), [])
        for container in ("top", "request", "provider"):
            config = deepcopy(CONFIG)
            target = config if container == "top" else (
                config["request"] if container == "request" else config["providers"][0])
            target["catalog_scope"] = "complete"
            with self.subTest(container=container):
                self.assertTrue(validate_config(config))
        self.assert_no_network()


if __name__ == "__main__":
    unittest.main()
