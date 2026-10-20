"""Free UCloud integration with synthetic quotes and no network or credentials."""

from contextlib import chdir, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main, validate_config
from gpu_price_monitor.providers import ucloud, ucloud_public
from gpu_price_monitor.transport import FetchError


ROOT = Path(__file__).resolve().parents[1]
OBSERVED = "2026-10-20T06:00:00+00:00"


def public_quotes():
    """Distinct public catalog scopes prevent region-only or zone-only matches."""
    quotes = []
    for region, zone, model, count, amount in (
        ("cn-bj2", "cn-bj2-02", "T4", 1, "720"),
        ("cn-bj2", "cn-bj2-04", "T4", 2, "800"),
        ("cn-sh2", "cn-sh2-01", "A100", 8, "3600"),
    ):
        quotes.append({
            "provider": "ucloud", "gpu_model": model, "gpu_count": count,
            "amount": amount, "currency": "CNY", "unit": "gpu_month",
            "billing_mode": "monthly", "quote_status": "quoted",
            "regions": [region], "zones": [zone],
            "geographic_scope": "zone", "account_scope": "public_promotion",
            "availability": "unknown", "observed_at": OBSERVED,
            "source_type": "official_public_api", "source_url": ucloud_public.SOURCE_URL,
        })
    return quotes


def public_config():
    return {
        "schema_version": 1,
        "request": {"timeout_seconds": 15, "max_retries": 0},
        "providers": [{
            "id": "ucloud", "enabled": True,
            "planned_source": "official_public_api", "filters": {},
        }],
    }


class UCloudFreeCollectionTests(unittest.TestCase):
    def setUp(self):
        patches = {
            "environment": patch.dict(os.environ, {}, clear=True),
            "clock": patch("gpu_price_monitor.collector._now", return_value=OBSERVED),
            "public": patch("gpu_price_monitor.providers.ucloud_public.collect_quotes",
                            side_effect=lambda **kwargs: public_quotes()),
            "authenticated": patch("gpu_price_monitor.providers.ucloud.collect_quotes",
                                   side_effect=AssertionError("Authentication must be explicitly selected")),
            "transport": patch("gpu_price_monitor.transport._request_text",
                               side_effect=AssertionError("No real network is allowed")),
            "fetch": patch("gpu_price_monitor.collector.fetch_text",
                           return_value=(ROOT / "tests/fixtures/lambda-public-pricing.html").read_text()),
        }
        for name, item in patches.items():
            setattr(self, name, item.start())
            self.addCleanup(item.stop)

    def cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_and_explicit_settings_sources_validate_without_network(self):
        self.assertEqual(Settings().ucloud_source, "public")
        self.assertEqual(Settings.from_env({}).ucloud_source, "public")
        self.assertEqual(Settings.from_env({"UCLOUD_SOURCE": "api"}).ucloud_source, "api")
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"UCLOUD_SOURCE": "synthetic-invalid-secret"})
        with self.assertRaises(ConfigurationError):
            Settings(ucloud_source="synthetic-invalid-secret")
        self.public.assert_not_called()
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_python_public_collection_returns_serializable_monthly_json(self):
        settings = Settings.from_env({})
        result = collect_prices(["ucloud"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual({q["unit"] for q in result["prices"]}, {"gpu_month"})
        self.assertEqual({q["billing_mode"] for q in result["prices"]}, {"monthly"})
        self.assertEqual({q["account_scope"] for q in result["prices"]}, {"public_promotion"})
        self.assertEqual(result["provider_results"][0]["source_type"], "official_public_api")
        self.assertEqual(result["provider_results"][0]["source_url"], ucloud_public.SOURCE_URL)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.public.assert_called_once_with(settings=settings, observed_at=OBSERVED)
        self.authenticated.assert_not_called()
        self.fetch.assert_not_called()
        self.transport.assert_not_called()

    def test_keys_and_unused_private_target_paths_never_enable_authentication(self):
        settings = Settings(
            ucloud_public_key="synthetic-public-secret",
            ucloud_private_key="synthetic-private-secret",
            ucloud_project_id="org-synthetic-secret",
            ucloud_price_targets_json="synthetic-invalid-private-targets",
            ucloud_price_targets_file="/nonexistent/synthetic-private-targets.json",
        )
        with patch.object(Path, "open", side_effect=AssertionError("No private target file may be read")):
            result = collect_prices(["ucloud"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_results"][0]["source_type"], "official_public_api")
        self.assertNotIn("synthetic-", json.dumps(result))
        self.public.assert_called_once()
        self.authenticated.assert_not_called()

    def test_region_zone_gpu_count_model_currency_and_monthly_filters_intersect(self):
        result = collect_prices(["ucloud"], {
            "regions": ["cn-bj2"], "zones": ["cn-bj2-04"],
            "gpu_counts": [2], "gpu_models": ["t4"],
            "currencies": ["cny"], "billing_modes": ["monthly"],
        }, settings=Settings())
        self.assertEqual(result["status"], "success")
        self.assertEqual([(q["regions"], q["zones"], q["gpu_count"])
                          for q in result["prices"]], [(["cn-bj2"], ["cn-bj2-04"], 2)])
        filters = result["provider_results"][0]["filters"]
        self.assertEqual(set(filters), {"regions", "zones", "gpu_counts", "gpu_models", "currencies", "billing_modes"})
        self.assertTrue(all(item["status"] == "applied_locally" for item in filters.values()))

    def test_disjoint_region_and_zone_produce_no_matches_without_weakening_filters(self):
        result = collect_prices(["ucloud"], {
            "regions": ["cn-bj2"], "zones": ["cn-sh2-01"],
        }, settings=Settings())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"], [])
        provider = result["provider_results"][0]
        self.assertEqual(provider["status"], "no_matches")
        self.assertEqual(provider["fetched_count"], 3)
        self.assertEqual(provider["returned_count"], 0)

    def test_unpublished_country_scope_fails_before_collection(self):
        result = collect_prices(["ucloud"], {"compute_countries": ["CN"]}, settings=Settings())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "unsupported_filter")
        self.public.assert_not_called()
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_only_explicit_api_selection_calls_the_retained_authenticated_adapter(self):
        quote = public_quotes()[0]
        quote.update({"unit": "gpu_hour", "billing_mode": "on_demand",
                      "account_scope": "account_quote", "source_url": ucloud.SOURCE_URL,
                      "source_type": "official_quote_api"})
        self.authenticated.side_effect = None
        self.authenticated.return_value = [quote]
        settings = Settings(ucloud_source="api", ucloud_public_key="synthetic-public-secret",
                            ucloud_private_key="synthetic-private-secret")
        result = collect_prices(["ucloud"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"][0]["unit"], "gpu_hour")
        self.assertEqual(result["provider_results"][0]["source_type"], "official_quote_api")
        self.assertEqual(result["provider_results"][0]["source_url"], ucloud.SOURCE_URL)
        self.authenticated.assert_called_once_with(settings=settings, observed_at=OBSERVED)
        self.public.assert_not_called()
        self.assertNotIn("synthetic-", json.dumps(result))

    def test_unrecognized_public_price_unit_fails_closed(self):
        for invalid_unit in ("instance_month", "gpu_year", "gpu_hour", "arbitrary_unit"):
            with self.subTest(unit=invalid_unit):
                quotes = public_quotes()
                quotes[0]["unit"] = invalid_unit
                self.public.side_effect = None
                self.public.return_value = quotes
                result = collect_prices(["ucloud"], settings=Settings())
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["prices"], [])
                self.assertEqual(result["provider_results"][0]["error"]["code"], "parse_failed")
        self.authenticated.assert_not_called()

    def test_public_failure_preserves_other_provider_prices_and_filter_state(self):
        self.public.side_effect = FetchError("network_error", "Public pricing could not be reached.", True)
        result = collect_prices(["ucloud", "lambda"], settings=Settings(),
                                provider_filters={"ucloud": {"zones": ["cn-bj2-02"]}})
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"lambda"})
        provider = result["provider_results"][0]
        self.assertEqual(provider["error"]["code"], "network_error")
        self.assertTrue(provider["error"]["retryable"])
        self.assertEqual(provider["filters"]["zones"]["status"], "not_applied")
        self.authenticated.assert_not_called()

    def test_cli_public_json_supports_precise_geographic_and_monthly_filters(self):
        code, stdout, stderr = self.cli([
            "collect", "--providers", "ucloud", "--pretty",
            "--region", "cn-bj2", "--zone", "cn-bj2-04", "--gpu-count", "2",
            "--gpu", "T4", "--currency", "CNY", "--billing-mode", "monthly",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        result = json.loads(stdout)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["zones"], ["cn-bj2-04"])
        self.assertEqual(result["prices"][0]["unit"], "gpu_month")
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_cli_explicit_public_overrides_api_environment_even_with_keys(self):
        with patch.dict(os.environ, {
            "UCLOUD_SOURCE": "api", "UCLOUD_PUBLIC_KEY": "synthetic-public-secret",
            "UCLOUD_PRIVATE_KEY": "synthetic-private-secret",
        }, clear=True):
            code, stdout, stderr = self.cli([
                "collect", "--providers", "ucloud", "--ucloud-source", "public",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "official_public_api")
        self.assertNotIn("synthetic-", stdout + stderr)
        self.authenticated.assert_not_called()

    def test_cli_explicit_api_overrides_public_environment(self):
        self.authenticated.side_effect = None
        self.authenticated.return_value = []
        with patch.dict(os.environ, {"UCLOUD_SOURCE": "public"}, clear=True):
            code, stdout, stderr = self.cli([
                "collect", "--providers", "ucloud", "--ucloud-source", "api",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "official_quote_api")
        self.assertEqual(self.authenticated.call_args.kwargs["settings"].ucloud_source, "api")
        self.public.assert_not_called()

    def test_explicit_env_file_source_is_overridden_by_process_then_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder, "synthetic.env")
            env_path.write_text("UCLOUD_SOURCE=api\nUCLOUD_PUBLIC_KEY=synthetic-env-secret\n")
            self.assertEqual(Settings.from_env({}, env_file=env_path).ucloud_source, "api")
            self.assertEqual(Settings.from_env({"UCLOUD_SOURCE": "public"}, env_file=env_path).ucloud_source, "public")
            with patch.dict(os.environ, {"UCLOUD_SOURCE": "api"}, clear=True):
                code, stdout, stderr = self.cli([
                    "collect", "--providers", "ucloud", "--env-file", str(env_path),
                    "--ucloud-source", "public",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "official_public_api")
        self.assertNotIn("synthetic-env-secret", stdout + stderr)
        self.assertEqual(self.public.call_args.kwargs["settings"].ucloud_source, "public")
        self.authenticated.assert_not_called()

    def test_selected_mode_and_configuration_source_must_agree_before_requests(self):
        config = public_config()
        self.assertEqual(validate_config(config), [])
        self.assertTrue(validate_config(config, settings=Settings(ucloud_source="api")))
        api_config = deepcopy(config)
        api_config["providers"][0]["planned_source"] = "official_quote_api"
        self.assertEqual(validate_config(api_config, settings=Settings(ucloud_source="api")), [])
        self.assertTrue(validate_config(api_config))
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder, "public-config.json")
            config_path.write_text(json.dumps(config))
            code, stdout, stderr = self.cli([
                "collect", "--config", str(config_path), "--ucloud-source", "api",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["error"]["code"], "configuration_error")
        self.public.assert_not_called()
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_cli_public_configuration_runs_and_validation_stays_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder, "public-config.json")
            config_path.write_text(json.dumps(public_config()))
            code, stdout, stderr = self.cli(["validate-config", "--config", str(config_path)])
            self.assertEqual(code, 0)
            self.public.assert_not_called()
            code, stdout, stderr = self.cli(["collect", "--config", str(config_path)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "official_public_api")
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_python_and_cli_never_discover_a_local_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text(
                "UCLOUD_SOURCE=api\nUCLOUD_PUBLIC_KEY=hidden-local-public-secret\n"
                "UCLOUD_PRIVATE_KEY=hidden-local-private-secret\n"
                "UCLOUD_PRICE_TARGETS_FILE=hidden-local-targets.json\n"
            )
            with chdir(folder):
                result = collect_prices(["ucloud"])
                code, stdout, stderr = self.cli(["collect", "--providers", "ucloud"])
        self.assertEqual(result["provider_results"][0]["source_type"], "official_public_api")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "official_public_api")
        self.assertNotIn("hidden-local-", stdout + stderr)
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
