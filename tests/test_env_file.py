"""Explicit dotenv and target-file loading, using temporary synthetic inputs."""

from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings
from gpu_price_monitor.cli import main
from gpu_price_monitor.providers.ucloud import load_targets


def target():
    return {
        "Region": "cn-bj2", "Zone": "cn-bj2-02", "MachineType": "G",
        "GpuType": "T4", "GPU": 1, "CPU": 4, "Memory": 16384,
        "Disks": [{"IsBoot": True, "Size": 40, "Type": "CLOUD_SSD"}],
    }


class TemporaryEnvironmentCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env_file = self.root / ".env"
        # Any accidental provider call fails locally rather than reaching HTTP.
        transport = patch("gpu_price_monitor.transport._request_text",
                          side_effect=AssertionError("No HTTP requests are allowed in env-file tests"))
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    def write_env(self, content):
        self.env_file.write_text(content, encoding="utf-8")
        return self.env_file

    def write_targets(self, name="targets.json", items=None):
        path = self.root / name
        path.write_text(json.dumps([target()] if items is None else items), encoding="utf-8")
        return path

    def assert_safe_configuration_error(self, env, *, env_file=None, secret="synthetic-secret"):
        with self.assertRaises(ConfigurationError) as raised:
            Settings.from_env(env, env_file=env_file)
        self.assertNotIn(secret, str(raised.exception))
        self.transport.assert_not_called()


class EnvFileTests(TemporaryEnvironmentCase):
    def test_source_policy_uses_file_then_process_layer_without_changing_source_flags(self):
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred\nLAMBDA_SOURCE=public\n")
        file_settings = Settings.from_env({}, env_file=self.env_file)
        self.assertEqual(file_settings.source_policy, "api_preferred")
        process_settings = Settings.from_env({"GPU_PRICE_MONITOR_SOURCE_POLICY": "api_only"},
                                             env_file=self.env_file)
        self.assertEqual(process_settings.source_policy, "api_only")
        self.assertEqual(process_settings.lambda_source, "public")
        self.transport.assert_not_called()

    def test_empty_or_invalid_source_policy_override_does_not_fall_back_to_file(self):
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred\n")
        for policy in ("", "synthetic-secret-policy", "API_ONLY"):
            with self.subTest(policy=policy):
                self.assert_safe_configuration_error({"GPU_PRICE_MONITOR_SOURCE_POLICY": policy},
                                                     env_file=self.env_file)
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=synthetic-secret-policy\n")
        self.assert_safe_configuration_error({}, env_file=self.env_file)

    def test_loading_is_explicit_and_empty_mapping_isolates_host(self):
        self.write_env("LAMBDA_API_KEY=from-local-file\n")
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "from-host-process"}, clear=True):
            with chdir(self.root):
                self.assertIsNone(Settings.from_env({}).lambda_api_key)
                settings = Settings.from_env({}, env_file=".env")
        self.assertEqual(settings.lambda_api_key, "from-local-file")

    def test_env_file_accepts_string_and_path(self):
        self.write_env("GPU_PRICE_MONITOR_TIMEOUT_SECONDS=12.5\n")
        for path in (self.env_file, str(self.env_file)):
            with self.subTest(path_type=type(path).__name__):
                self.assertEqual(Settings.from_env({}, env_file=path).timeout_seconds, 12.5)

    def test_process_environment_overrides_file_without_mutating_environment(self):
        self.write_env("LAMBDA_API_KEY=file-secret\nGPU_PRICE_MONITOR_TIMEOUT_SECONDS=12\n")
        values = {"LAMBDA_API_KEY": "process-secret", "GPU_PRICE_MONITOR_TIMEOUT_SECONDS": "19"}
        with patch.dict(os.environ, values, clear=True):
            before = dict(os.environ)
            settings = Settings.from_env(env_file=self.env_file)
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(settings.lambda_api_key, "process-secret")
        self.assertEqual(settings.timeout_seconds, 19)

    def test_explicit_mapping_is_complete_and_overrides_file(self):
        self.write_env("LAMBDA_API_KEY=file-secret\nNEBIUS_ACCESS_TOKEN=file-nebius\n")
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "host-secret", "AUTODL_TOKEN": "host-token"}, clear=True):
            settings = Settings.from_env({"LAMBDA_API_KEY": "mapping-secret"}, env_file=self.env_file)
        self.assertEqual(settings.lambda_api_key, "mapping-secret")
        self.assertEqual(settings.nebius_access_token, "file-nebius")
        self.assertIsNone(settings.autodl_token)

    def test_empty_higher_layer_value_clears_file_credential(self):
        self.write_env("LAMBDA_API_KEY=file-secret\n")
        self.assertIsNone(Settings.from_env({"LAMBDA_API_KEY": ""}, env_file=self.env_file).lambda_api_key)
        with patch.dict(os.environ, {"LAMBDA_API_KEY": ""}, clear=True):
            self.assertIsNone(Settings.from_env(env_file=self.env_file).lambda_api_key)

    def test_empty_numeric_override_is_an_error_instead_of_using_file_default(self):
        self.write_env("GPU_PRICE_MONITOR_TIMEOUT_SECONDS=20\n")
        self.assert_safe_configuration_error({"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": ""}, env_file=self.env_file)

    def test_bom_export_quotes_comments_escapes_and_multiline_values(self):
        self.env_file.write_text(
            "\ufeff# 配置示例\nexport LAMBDA_API_KEY='quoted # secret'\n"
            'NEBIUS_ACCESS_TOKEN="line1\\nline2" # comment\n'
            'AUTODL_TOKEN="first\nsecond"\n'
            "UCLOUD_PUBLIC_KEY=plain#fragment # discarded comment\n",
            encoding="utf-8",
        )
        settings = Settings.from_env({}, env_file=self.env_file)
        self.assertEqual(settings.lambda_api_key, "quoted # secret")
        self.assertEqual(settings.nebius_access_token, "line1\nline2")
        self.assertEqual(settings.autodl_token, "first\nsecond")
        self.assertEqual(settings.ucloud_public_key, "plain#fragment")

    def test_variable_and_shell_expressions_remain_literal(self):
        marker = self.root / "must-not-be-created"
        command = f"$(touch {marker})"
        self.write_env(f"LAMBDA_API_KEY='${{HOST_SECRET}}'\nAUTODL_TOKEN='{command}'\n")
        with patch.dict(os.environ, {"HOST_SECRET": "host-expanded-secret"}, clear=True):
            settings = Settings.from_env(env_file=self.env_file)
        self.assertEqual(settings.lambda_api_key, "${HOST_SECRET}")
        self.assertEqual(settings.autodl_token, command)
        self.assertFalse(marker.exists())

    def test_invalid_or_incomplete_dotenv_syntax_is_rejected_safely(self):
        cases = (
            "LAMBDA_API_KEY\n",
            "LAMBDA_API_KEY='synthetic-secret\n",
            'LAMBDA_API_KEY="synthetic-secret\n',
            "LAMBDA_API_KEY='synthetic-secret' unexpected\n",
            "=synthetic-secret\n",
        )
        for content in cases:
            with self.subTest(content=content):
                self.write_env(content)
                self.assert_safe_configuration_error({}, env_file=self.env_file)

    def test_duplicate_assignments_are_rejected_including_unknown_names(self):
        for name in ("LAMBDA_API_KEY", "CUSTOM_UNUSED_VALUE"):
            with self.subTest(name=name):
                self.write_env(f"{name}=synthetic-secret\nexport {name}=another-secret\n")
                self.assert_safe_configuration_error({}, env_file=self.env_file)

    def test_invalid_file_is_not_hidden_by_process_overrides(self):
        self.write_env("LAMBDA_API_KEY='synthetic-secret\n")
        self.assert_safe_configuration_error({"LAMBDA_API_KEY": "valid-process-value"}, env_file=self.env_file)

    def test_missing_unreadable_or_non_utf8_env_file_is_a_safe_error(self):
        missing = self.root / "synthetic-secret.env"
        self.env_file.write_bytes(b"LAMBDA_API_KEY=\xff\xfe")
        for path in (missing, self.root, self.env_file):
            with self.subTest(kind=path.name):
                self.assert_safe_configuration_error({}, env_file=path)

    def test_env_file_size_limit_accepts_boundary_and_rejects_overflow(self):
        maximum = 256 * 1024
        self.env_file.write_bytes(b"#" + b"x" * (maximum - 1))
        self.assertEqual(Settings.from_env({}, env_file=self.env_file).providers, ("nebius", "crusoe"))
        self.env_file.write_bytes(b"#" + b"x" * maximum)
        self.assert_safe_configuration_error({}, env_file=self.env_file)

    def test_file_credentials_and_target_paths_are_hidden_from_repr(self):
        targets = self.write_targets("synthetic-secret-targets.json")
        self.write_env(
            "LAMBDA_API_KEY=synthetic-secret-lambda\n"
            "UCLOUD_PUBLIC_KEY=synthetic-secret-public\n"
            "UCLOUD_PRIVATE_KEY=synthetic-secret-private\n"
            "UCLOUD_PROJECT_ID=org-synthetic-secret\n"
            f"UCLOUD_PRICE_TARGETS_FILE={targets.name}\n"
        )
        settings = Settings.from_env({}, env_file=self.env_file)
        self.assertNotIn("synthetic-secret", repr(settings))
        self.assertNotIn(settings.ucloud_price_targets_json, repr(settings))


class TargetFileTests(TemporaryEnvironmentCase):
    def test_relative_target_file_uses_env_file_parent_even_for_process_override(self):
        file = self.write_targets("configured.json")
        other_cwd = self.root / "elsewhere"
        other_cwd.mkdir()
        self.write_env("UCLOUD_PRICE_TARGETS_FILE=does-not-exist.json\n")
        with chdir(other_cwd):
            settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_FILE": file.name}, env_file=self.env_file)
        self.assertEqual(json.loads(settings.ucloud_price_targets_json), [target()])
        self.assertEqual(settings.ucloud_price_targets_file, file.name)
        self.assertEqual(load_targets(settings)[0]["Region"], "cn-bj2")

    def test_relative_target_file_without_env_file_uses_cwd(self):
        self.write_targets()
        with chdir(self.root):
            settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_FILE": "targets.json"})
        self.assertEqual(json.loads(settings.ucloud_price_targets_json), [target()])

    def test_absolute_target_file_is_not_rebased(self):
        path = self.write_targets()
        subdirectory = self.root / "config"
        subdirectory.mkdir()
        env_file = subdirectory / ".env"
        env_file.write_text(f"UCLOUD_PRICE_TARGETS_FILE={path}\n")
        self.assertEqual(json.loads(Settings.from_env({}, env_file=env_file).ucloud_price_targets_json), [target()])

    def test_direct_settings_construction_does_not_read_target_file(self):
        path = self.root / "missing.json"
        settings = Settings(ucloud_price_targets_file=str(path))
        self.assertIsNone(settings.ucloud_price_targets_json)
        self.assertEqual(settings.ucloud_price_targets_file, str(path))

    def test_process_json_replaces_lower_target_file_without_reading_it(self):
        self.write_env("UCLOUD_PRICE_TARGETS_FILE=synthetic-secret-missing.json\n")
        raw = json.dumps([target()])
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_JSON": raw}, env_file=self.env_file)
        self.assertEqual(settings.ucloud_price_targets_json, raw)
        self.assertIsNone(settings.ucloud_price_targets_file)

    def test_process_target_file_replaces_lower_json(self):
        self.write_targets()
        self.write_env("UCLOUD_PRICE_TARGETS_JSON=synthetic-secret-invalid-json\n")
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_FILE": "targets.json"}, env_file=self.env_file)
        self.assertEqual(json.loads(settings.ucloud_price_targets_json), [target()])

    def test_either_empty_process_source_clears_both_lower_sources(self):
        file_sources = (
            "UCLOUD_PRICE_TARGETS_JSON='" + json.dumps([target()]) + "'\n",
            "UCLOUD_PRICE_TARGETS_FILE=synthetic-secret-missing.json\n",
        )
        for lower in file_sources:
            self.write_env(lower)
            for name in ("UCLOUD_PRICE_TARGETS_JSON", "UCLOUD_PRICE_TARGETS_FILE"):
                with self.subTest(lower=lower[:35], process_key=name):
                    settings = Settings.from_env({name: ""}, env_file=self.env_file)
                    self.assertIsNone(settings.ucloud_price_targets_json)
                    self.assertIsNone(settings.ucloud_price_targets_file)

    def test_process_source_group_override_also_applies_with_os_environ(self):
        self.write_env("UCLOUD_PRICE_TARGETS_FILE=synthetic-secret-missing.json\n")
        with patch.dict(os.environ, {"UCLOUD_PRICE_TARGETS_JSON": ""}, clear=True):
            settings = Settings.from_env(env_file=self.env_file)
        self.assertIsNone(settings.ucloud_price_targets_json)
        self.assertIsNone(settings.ucloud_price_targets_file)

    def test_same_selected_layer_rejects_two_nonempty_sources(self):
        self.write_targets()
        raw = json.dumps([target()])
        values = {"UCLOUD_PRICE_TARGETS_JSON": raw, "UCLOUD_PRICE_TARGETS_FILE": "targets.json"}
        self.assert_safe_configuration_error(values)
        self.write_env("UCLOUD_PRICE_TARGETS_JSON='" + raw + "'\nUCLOUD_PRICE_TARGETS_FILE=targets.json\n")
        self.assert_safe_configuration_error({}, env_file=self.env_file)

    def test_valid_upper_source_replaces_ambiguous_lower_source_group(self):
        raw = json.dumps([target()])
        self.write_env("UCLOUD_PRICE_TARGETS_JSON='" + raw + "'\nUCLOUD_PRICE_TARGETS_FILE=missing.json\n")
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_JSON": raw}, env_file=self.env_file)
        self.assertEqual(settings.ucloud_price_targets_json, raw)
        self.assertIsNone(settings.ucloud_price_targets_file)

    def test_empty_companion_source_does_not_conflict_with_nonempty_source(self):
        path = self.write_targets()
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_JSON": "", "UCLOUD_PRICE_TARGETS_FILE": str(path)})
        self.assertEqual(json.loads(settings.ucloud_price_targets_json), [target()])
        raw = json.dumps([target()])
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_JSON": raw, "UCLOUD_PRICE_TARGETS_FILE": ""})
        self.assertEqual(settings.ucloud_price_targets_json, raw)
        self.assertIsNone(settings.ucloud_price_targets_file)

    def test_missing_selected_target_file_does_not_fall_back_to_lower_json(self):
        self.write_env("UCLOUD_PRICE_TARGETS_JSON='" + json.dumps([target()]) + "'\n")
        self.assert_safe_configuration_error(
            {"UCLOUD_PRICE_TARGETS_FILE": "synthetic-secret-missing.json"}, env_file=self.env_file,
        )

    def test_target_file_missing_malformed_non_utf8_or_invalid_schema_is_safe_error(self):
        path = self.root / "synthetic-secret-targets.json"
        self.assert_safe_configuration_error({"UCLOUD_PRICE_TARGETS_FILE": str(path)})
        for content in (b"\xff\xfe", b"synthetic-secret", b"[]", b"{}",
                        json.dumps([{**target(), "GPU": 0}]).encode(),
                        b'[{"Region":"cn-bj2","Region":"cn-sh2"}]'):
            with self.subTest(content=content[:30]):
                path.write_bytes(content)
                self.assert_safe_configuration_error({"UCLOUD_PRICE_TARGETS_FILE": str(path)})

    def test_target_file_size_limit_is_128_kib(self):
        path = self.write_targets()
        prefix = path.read_bytes()
        path.write_bytes(prefix + b" " * (128 * 1024 - len(prefix)))
        settings = Settings.from_env({"UCLOUD_PRICE_TARGETS_FILE": str(path)})
        self.assertEqual(json.loads(settings.ucloud_price_targets_json), [target()])
        path.write_bytes(prefix + b" " * (128 * 1024 + 1 - len(prefix)))
        self.assert_safe_configuration_error({"UCLOUD_PRICE_TARGETS_FILE": str(path)})


class EnvFileCliTests(TemporaryEnvironmentCase):
    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_global_and_status_option_positions_load_file_without_requests_or_secrets(self):
        self.write_env("GPU_PRICE_MONITOR_PROVIDERS=lambda\nLAMBDA_API_KEY=synthetic-secret\n")
        with patch("gpu_price_monitor.cli.collect_prices") as collector:
            for arguments in (["--env-file", str(self.env_file), "status"],
                              ["status", "--env-file", str(self.env_file)]):
                with self.subTest(arguments=arguments):
                    code, stdout, stderr = self.run_cli(arguments)
                    self.assertEqual(code, 0)
                    self.assertIn("Configured providers: lambda", stdout)
                    self.assertNotIn("synthetic-secret", stdout + stderr)
            collector.assert_not_called()
        self.transport.assert_not_called()

    def test_validate_config_accepts_env_file_after_subcommand_without_requests(self):
        self.write_env("LAMBDA_API_KEY=synthetic-secret\n")
        config = Path(__file__).resolve().parents[1] / "configs/collect.example.json"
        code, stdout, stderr = self.run_cli(["validate-config", "--config", str(config), "--env-file", str(self.env_file)])
        self.assertEqual(code, 0)
        self.assertNotIn("synthetic-secret", stdout + stderr)
        self.transport.assert_not_called()

    def test_collect_env_file_is_loaded_before_mocked_collection_and_stdout_is_json(self):
        self.write_env("GPU_PRICE_MONITOR_PROVIDERS=lambda\nLAMBDA_API_KEY=synthetic-secret\n")
        response = {"schema_version": 1, "status": "success", "prices": [], "provider_results": []}
        with patch("gpu_price_monitor.cli.collect_prices", return_value=response) as collector:
            code, stdout, stderr = self.run_cli(["collect", "--env-file", str(self.env_file)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), response)
        self.assertEqual(collector.call_args.kwargs["settings"].lambda_api_key, "synthetic-secret")
        self.assertEqual(collector.call_args.kwargs["settings"].providers, ("lambda",))
        self.assertNotIn("synthetic-secret", stdout + stderr)

    def test_collect_source_policy_inherits_env_file_unless_cli_explicitly_overrides_it(self):
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred\nLAMBDA_SOURCE=public\n"
                       "LAMBDA_API_KEY=synthetic-secret\n")
        response = {"schema_version": 1, "status": "success", "prices": [], "provider_results": []}
        for extra, expected in (([], "api_preferred"), (["--source-policy", "configured"], "configured"),
                                (["--source-policy", "api_only"], "api_only")):
            with self.subTest(expected=expected), patch(
                "gpu_price_monitor.cli.collect_prices", return_value=response
            ) as collector:
                code, stdout, stderr = self.run_cli(["collect", "--env-file", str(self.env_file), *extra])
            self.assertEqual(code, 0)
            settings = collector.call_args.kwargs["settings"]
            self.assertEqual(settings.source_policy, expected)
            self.assertEqual(settings.lambda_source, "public")
            self.assertNotIn("synthetic-secret", stdout + stderr)
        self.transport.assert_not_called()

    def test_status_source_policy_cli_override_reaches_source_selection_without_network(self):
        self.write_env("GPU_PRICE_MONITOR_PROVIDERS=lambda\nGPU_PRICE_MONITOR_SOURCE_POLICY=configured\n"
                       "LAMBDA_API_KEY=synthetic-secret\n")
        with patch("gpu_price_monitor.cli.provider_source", return_value="official_api") as selected:
            code, stdout, stderr = self.run_cli(["status", "--env-file", str(self.env_file),
                                                "--source-policy", "api_preferred"])
        self.assertEqual(code, 0)
        self.assertEqual(selected.call_args.args[1].source_policy, "api_preferred")
        self.assertIn("Source policy: api_preferred", stdout)
        self.assertIn("lambda source type: official_api", stdout)
        self.assertNotIn("synthetic-secret", stdout + stderr)
        self.transport.assert_not_called()

    def test_validate_config_source_policy_cli_override_is_applied_before_validation(self):
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=api_only\nLAMBDA_API_KEY=synthetic-secret\n")
        config = Path(__file__).resolve().parents[1] / "configs/collect.example.json"
        code, stdout, stderr = self.run_cli(["validate-config", "--config", str(config),
                                            "--env-file", str(self.env_file), "--source-policy", "configured"])
        self.assertEqual(code, 0)
        self.assertNotIn("synthetic-secret", stdout + stderr)
        self.transport.assert_not_called()

    def test_collect_invalid_source_policy_environment_is_safe_json_before_collection(self):
        self.write_env("GPU_PRICE_MONITOR_SOURCE_POLICY=synthetic-secret-policy\n")
        with patch("gpu_price_monitor.cli.collect_prices") as collector:
            code, stdout, stderr = self.run_cli(["collect", "--env-file", str(self.env_file)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["error"]["code"], "configuration_error")
        self.assertNotIn("synthetic-secret", stdout + stderr)
        collector.assert_not_called()
        self.transport.assert_not_called()

    def test_collect_invalid_env_file_returns_safe_json_instead_of_collecting(self):
        self.write_env("LAMBDA_API_KEY='synthetic-secret\n")
        with patch("gpu_price_monitor.cli.collect_prices") as collector:
            for arguments in (["collect", "--env-file", str(self.env_file)],
                              ["--env-file", str(self.env_file), "collect"]):
                with self.subTest(arguments=arguments):
                    code, stdout, stderr = self.run_cli(arguments)
                    self.assertEqual(code, 1)
                    result = json.loads(stdout)
                    self.assertEqual(result["error"]["code"], "configuration_error")
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(result["prices"], [])
                    self.assertNotIn("synthetic-secret", stdout + stderr)
            collector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
