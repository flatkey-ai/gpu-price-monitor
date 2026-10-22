"""Explicit console collection integrates session GETs without public fallback."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import csv
from dataclasses import fields
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.collector import _selected_module, provider_source
from gpu_price_monitor.providers import lambda_cloud, lambda_console, lambda_console_client, lambda_public
from gpu_price_monitor.transport import FetchError


FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-22T02:00:00+00:00"
PRIVATE = "synthetic-private-console-session-cookie"


class LambdaConsoleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "private-console-session.json"
        self.state.write_text(json.dumps({"cookies": [{
            "name": "session", "value": PRIVATE, "domain": "cloud.lambda.ai", "path": "/",
            "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax",
        }], "origins": []}), encoding="utf-8")
        self.state.chmod(0o600)
        self.payloads = {
            lambda_console.INSTANCE_TYPES_URL: self.fixture("lambda-console-instance-types-20261022.json"),
            lambda_console.RESERVED_CLUSTER_TYPES_URL: self.fixture("lambda-console-cluster-types-20261022.json"),
            lambda_console.REGIONS_URL: self.fixture("lambda-console-regions-20261022.json"),
        }
        self.transport = self.block("gpu_price_monitor.transport._request_text")
        self.socket = self.block("socket.create_connection")
        self.html = self.block("gpu_price_monitor.collector.fetch_text")
        self.public = self.block("gpu_price_monitor.providers.lambda_public.parse_prices")
        self.keyed_api = self.block("gpu_price_monitor.providers.lambda_cloud.collect_quotes")
        self.cluster_page = self.block("gpu_price_monitor.providers.lambda_clusters.collect_quotes")
        self.stack.enter_context(patch("gpu_price_monitor.collector._now", return_value=OBSERVED))
        self.request = self.stack.enter_context(patch(
            "gpu_price_monitor.lambda_session.request_json", side_effect=self.get_catalog))

    def block(self, target):
        return self.stack.enter_context(patch(
            target, side_effect=AssertionError("Unexpected network, browser, or alternate Lambda source")))

    @staticmethod
    def fixture(name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def get_catalog(self, url, settings, **options):
        self.assertIn(url, self.payloads)
        self.assertEqual(options["method"], "GET")
        self.assertIs(options["authenticated"], True)
        self.assertEqual(str(options["headers"]["Cookie"]), "session=" + PRIVATE)
        return deepcopy(self.payloads[url])

    def settings(self, **overrides):
        return Settings(**{"providers": ("lambda",), "lambda_source": "console",
                           "lambda_storage_state_path": str(self.state), **overrides})

    def collect(self, **overrides):
        return collect_prices(settings=self.settings(**overrides))

    def assert_private_result(self, value):
        serialized = json.dumps(value, ensure_ascii=False)
        self.assertNotIn(PRIVATE, serialized)
        self.assertNotIn(str(self.state), serialized)

    def tearDown(self):
        for blocked in (self.transport, self.socket, self.html, self.public, self.keyed_api, self.cluster_page):
            blocked.assert_not_called()

    def test_console_session_setting_is_optional_explicit_and_hidden_from_repr(self):
        self.assertIsNone(Settings().lambda_storage_state_path)
        option = next(field for field in fields(Settings) if field.name == "lambda_storage_state_path")
        self.assertFalse(option.repr)
        settings = Settings.from_env({"LAMBDA_SOURCE": "console", "LAMBDA_STORAGE_STATE_PATH": str(self.state)})
        self.assertEqual(settings.lambda_source, "console")
        self.assertEqual(settings.lambda_storage_state_path, str(self.state))
        self.assertNotIn(str(self.state), repr(settings))
        self.request.assert_not_called()

    def test_relative_session_path_is_resolved_against_the_explicit_env_file(self):
        env_file = Path(self.directory.name) / "lambda.env"
        env_file.write_text("LAMBDA_SOURCE=console\nLAMBDA_STORAGE_STATE_PATH=private-console-session.json\n")
        settings = Settings.from_env({}, env_file=env_file)
        self.assertEqual(Path(settings.lambda_storage_state_path), self.state)
        self.assertEqual(settings.lambda_source, "console")
        blank = Settings.from_env({"LAMBDA_STORAGE_STATE_PATH": ""}, env_file=env_file)
        self.assertIsNone(blank.lambda_storage_state_path)
        self.request.assert_not_called()

    def test_tilde_session_path_expands_before_env_file_relative_resolution(self):
        env_file = Path(self.directory.name) / "lambda.env"
        env_file.write_text("LAMBDA_SOURCE=console\nLAMBDA_STORAGE_STATE_PATH=~/.lambda-console/session.json\n")
        for values, selected in (({}, "~/.lambda-console/session.json"),
                                 ({"LAMBDA_STORAGE_STATE_PATH": "~/.lambda-console/override.json"},
                                  "~/.lambda-console/override.json")):
            with self.subTest(process_override=bool(values)):
                settings = Settings.from_env(values, env_file=env_file)
                selected_path = Path(settings.lambda_storage_state_path).expanduser()
                self.assertEqual(selected_path, Path(selected).expanduser())
                self.assertTrue(selected_path.is_absolute())
        self.request.assert_not_called()

    def test_session_path_does_not_implicitly_select_console_over_public_or_keyed_api(self):
        for source, policy, key, expected in (
            ("public", "configured", None, lambda_public),
            ("api", "configured", None, lambda_cloud),
            ("public", "api_preferred", "synthetic-key", lambda_cloud),
            ("public", "api_only", None, lambda_cloud),
        ):
            with self.subTest(source=source, policy=policy):
                settings = self.settings(lambda_source=source, source_policy=policy, lambda_api_key=key)
                self.assertIs(_selected_module("lambda", settings), expected)
        self.request.assert_not_called()

    def test_explicit_console_wins_source_policy_and_retains_actual_source_type(self):
        for policy in ("configured", "api_preferred", "api_only"):
            with self.subTest(policy=policy):
                settings = self.settings(source_policy=policy, catalog_scope="complete", lambda_api_key="unused-key")
                self.assertIs(_selected_module("lambda", settings), lambda_console_client)
                self.assertEqual(provider_source("lambda", settings), "official_internal_api")
        self.request.assert_not_called()

    def test_console_collects_three_fixed_get_catalogs_and_retains_coverage_limits(self):
        result = self.collect(catalog_scope="complete", source_policy="api_only")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 36)
        self.assertEqual([call.args[0] for call in self.request.call_args_list], list(self.payloads))
        source = result["provider_results"][0]
        self.assertEqual(source["source_type"], "official_internal_api")
        self.assertEqual(source["collection_method"], "authenticated_http_json")
        self.assertIsNone(source["fallback_reason"])
        coverage = source["catalog_coverage"]
        self.assertEqual(coverage["instance_source_record_count"], 24)
        self.assertEqual(coverage["gpu_instance_quote_count"], 22)
        self.assertEqual(coverage["excluded_non_gpu_record_count"], 2)
        self.assertEqual(coverage["cluster_configuration_count"], 14)
        self.assertEqual(coverage["cluster_gpu_rate_tier_count"], 6)
        self.assertEqual(coverage["region_metadata_count"], 18)
        self.assertIs(coverage["all_prices_complete"], False)
        self.assertEqual(len(source["excluded_non_gpu_records"]), 2)
        self.assertEqual(len(source["regions_catalog"]), 18)
        self.assertTrue(source["gaps"])
        self.assertTrue(all(not quote["region_price_verified"] for quote in result["prices"]))
        self.assertTrue(all(quote["regions"] == quote["compute_countries"] == [] for quote in result["prices"]))
        self.assert_private_result(result)

    def test_cluster_failure_retains_successful_instance_quotes_and_region_audit(self):
        original = self.get_catalog

        def response(url, settings, **options):
            if url == lambda_console.RESERVED_CLUSTER_TYPES_URL:
                raise FetchError("authentication_error", "Lambda rejected the session permissions.")
            return original(url, settings, **options)

        self.request.side_effect = response
        result = self.collect(catalog_scope="complete")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 22)
        source = result["provider_results"][0]
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["error"]["code"], "partial_collection")
        self.assertEqual(source["source_errors"][0]["code"], "authentication_error")
        self.assertEqual(source["source_errors"][0]["source_url"], lambda_console.RESERVED_CLUSTER_TYPES_URL)
        self.assertEqual(len(source["regions_catalog"]), 18)
        self.assert_private_result(result)

    def test_instance_schema_change_retains_cluster_rows_without_using_public_skus(self):
        self.payloads[lambda_console.INSTANCE_TYPES_URL] = {"data": {"unknown": {"changed_schema": True}}}
        result = self.collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 14)
        self.assertTrue(all(quote["product_type"] == "gpu_cluster" for quote in result["prices"]))
        self.assertEqual(result["provider_results"][0]["source_errors"][0]["code"], "parse_failed")
        self.assert_private_result(result)

    def test_region_catalog_failure_is_visible_and_does_not_discard_pricing(self):
        self.payloads[lambda_console.REGIONS_URL] = {"data": {"changed_schema": True}}
        result = self.collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 36)
        source = result["provider_results"][0]
        self.assertEqual(source["source_errors"][0]["source_url"], lambda_console.REGIONS_URL)
        self.assertEqual(source["regions_catalog"], [])
        self.assert_private_result(result)

    def test_region_metadata_alone_does_not_make_failed_price_collection_partial(self):
        original = self.get_catalog

        def response(url, settings, **options):
            if url != lambda_console.REGIONS_URL:
                raise FetchError("authentication_error", "Lambda rejected pricing catalog permissions.")
            return original(url, settings, **options)

        self.request.side_effect = response
        result = self.collect()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        source = result["provider_results"][0]
        self.assertEqual(source["status"], "failed")
        self.assertEqual(len(source["regions_catalog"]), 18)
        self.assertEqual(source["catalog_coverage"]["region_metadata_count"], 18)
        self.assertEqual(source["catalog_coverage"]["gpu_instance_quote_count"], 0)
        self.assertEqual(source["catalog_coverage"]["cluster_configuration_count"], 0)
        self.assertEqual(len(source["source_errors"]), 2)
        self.assertTrue(source["gaps"])
        context = source["source_contexts"][0]
        self.assertEqual(context["status"], "partial")
        self.assertEqual([item["status"] for item in context["sources"]], ["failed", "failed", "success"])
        self.assert_private_result(result)

    def test_missing_or_expired_session_fails_explicitly_without_public_fallback(self):
        for state in (None, "missing-private-session.json"):
            with self.subTest(state=state):
                result = self.collect(lambda_storage_state_path=state, source_policy="api_only")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["prices"], [])
                self.assertTrue(result["provider_results"][0]["source_errors"])
                self.assert_private_result(result)
        self.request.assert_not_called()
        self.request.side_effect = FetchError("authentication_error", "Lambda rejected the exported session.")
        result = self.collect()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assert_private_result(result)

    def test_explicit_empty_console_catalogs_are_successful_empty_results(self):
        self.payloads = {lambda_console.INSTANCE_TYPES_URL: {"data": {}},
                         lambda_console.RESERVED_CLUSTER_TYPES_URL: {"data": []},
                         lambda_console.REGIONS_URL: {"data": []}}
        result = self.collect()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")
        self.assertEqual(result["provider_results"][0]["catalog_coverage"]["instance_source_record_count"], 0)

    def test_cli_console_source_overrides_environment_and_keeps_json_stdout_private(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"LAMBDA_SOURCE": "public", "LAMBDA_STORAGE_STATE_PATH": str(self.state)}, clear=True), \
                redirect_stdout(output), redirect_stderr(errors):
            code = main(["collect", "--providers", "lambda", "--lambda-source", "console", "--source-policy", "api_only"])
        self.assertEqual(code, 0, errors.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["prices"]), 36)
        self.assertEqual(result["provider_results"][0]["source_type"], "official_internal_api")
        self.assert_private_result(result)
        self.assertNotIn(PRIVATE, errors.getvalue())
        self.assertNotIn(str(self.state), errors.getvalue())

    def test_cli_csv_is_valid_and_does_not_expose_saved_session_details(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"LAMBDA_SOURCE": "console", "LAMBDA_STORAGE_STATE_PATH": str(self.state)}, clear=True), \
                redirect_stdout(output), redirect_stderr(errors):
            code = main(["collect", "--providers", "lambda", "--format", "csv", "--csv-headers", "english"])
        self.assertEqual(code, 0, errors.getvalue())
        rows = list(csv.DictReader(io.StringIO(output.getvalue().lstrip("\ufeff"))))
        self.assertTrue(rows)
        self.assertTrue(all(row["provider"] == "lambda" for row in rows))
        self.assertNotIn(PRIVATE, output.getvalue() + errors.getvalue())
        self.assertNotIn(str(self.state), output.getvalue() + errors.getvalue())

    def test_status_reports_console_source_without_opening_the_session_file(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"GPU_PRICE_MONITOR_PROVIDERS": "lambda", "LAMBDA_SOURCE": "console",
                                    "LAMBDA_STORAGE_STATE_PATH": str(self.state)}, clear=True), \
                patch("gpu_price_monitor.lambda_session._read_state", side_effect=AssertionError("Status must not read a login")) as state, \
                redirect_stdout(output), redirect_stderr(errors):
            code = main(["status"])
        self.assertEqual(code, 0, errors.getvalue())
        self.assertIn("Lambda source: console", output.getvalue())
        self.assertIn("lambda source type: official_internal_api", output.getvalue())
        self.assertNotIn(str(self.state), output.getvalue() + errors.getvalue())
        state.assert_not_called()
        self.request.assert_not_called()

    def test_login_cli_delegates_to_manual_login_with_required_path_and_default_timeout(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("gpu_price_monitor.lambda_login.save_lambda_session") as login, \
                redirect_stdout(output), redirect_stderr(errors):
            code = main(["lambda-login", "--state-file", str(self.state)])
        self.assertEqual(code, 0, errors.getvalue())
        login.assert_called_once_with(self.state, timeout_seconds=300)
        self.assertNotIn(str(self.state), output.getvalue() + errors.getvalue())
        self.request.assert_not_called()

    def test_login_cli_supports_explicit_timeout_and_redacts_runtime_failures(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("gpu_price_monitor.lambda_login.save_lambda_session", side_effect=FetchError(
            "timeout", "Manual Lambda login timed out.")) as login, redirect_stdout(output), redirect_stderr(errors):
            code = main(["lambda-login", "--state-file", str(self.state), "--timeout", "10"])
        self.assertEqual(code, 1)
        login.assert_called_once_with(self.state, timeout_seconds=10)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("timeout", errors.getvalue())
        self.assertNotIn(str(self.state), errors.getvalue())

    def test_login_cli_rejects_out_of_range_timeouts_before_login(self):
        for value in ("0", "-1", "301"):
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(value=value), patch("gpu_price_monitor.lambda_login.save_lambda_session") as login, \
                    redirect_stdout(output), redirect_stderr(errors):
                code = main(["lambda-login", "--state-file", str(self.state), "--timeout", value])
                self.assertEqual(code, 1)
                login.assert_not_called()
                self.assertNotIn(str(self.state), output.getvalue() + errors.getvalue())


if __name__ == "__main__":
    unittest.main()
