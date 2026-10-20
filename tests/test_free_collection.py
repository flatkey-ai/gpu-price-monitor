"""Free public collection integration; HTTP and rendered pages are mocked."""

from contextlib import chdir, redirect_stderr, redirect_stdout
from copy import deepcopy
from decimal import localcontext
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main, validate_config
from gpu_price_monitor.providers import lambda_cloud, lambda_public
from gpu_price_monitor.transport import FetchError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OBSERVED = "2026-10-20T02:00:00+00:00"


def autodl_pages():
    """Minimal synthetic snapshots, preserving the two public tier conditions."""
    pages = []
    for member in (False, True):
        ordinary_active, member_active = ("", "active") if member else ("active", "")
        prices = ("9.98", "1.90") if member else ("10.50", "2.00")
        cards = []
        for (name, memory), amount in zip((("H100", 80), ("RTX 4090", 24)), prices):
            discount = '<span class="d-tag">会员95折</span>' if member else ""
            cards.append(
                f'<div class="gpu-item"><div class="name">{name} / {memory}GB</div>'
                f'<div class="price"><span class="unit">￥</span>'
                f'<span class="text">{amount}</span><span>/时</span>{discount}</div></div>'
            )
        pages.append(
            '<div class="display-module"><div class="header">'
            '<span class="title">炼丹会员及租用价格</span></div>'
            f'<div class="level-tab"><span class="{ordinary_active}">普通用户</span>'
            f'<span class="{member_active}">炼丹会员</span></div>'
            '<div class="member-gpu-price">' + "".join(cards) + "</div></div>"
        )
    return pages


class FreeCollectionTests(unittest.TestCase):
    def setUp(self):
        patches = {
            "environment": patch.dict(os.environ, {}, clear=True),
            "clock": patch("gpu_price_monitor.collector._now", return_value=OBSERVED),
            "fetch": patch("gpu_price_monitor.collector.fetch_text",
                           return_value=(FIXTURES / "lambda-public-pricing.html").read_text()),
            "render": patch("gpu_price_monitor.browser.fetch_autodl_pages", return_value=autodl_pages()),
            "authenticated": patch("gpu_price_monitor.providers.lambda_cloud.request_json",
                                   side_effect=AssertionError("Authentication was not explicitly enabled")),
            "transport": patch("gpu_price_monitor.transport._request_text",
                               side_effect=AssertionError("No real network is allowed")),
        }
        for name, item in patches.items():
            setattr(self, name, item.start())
            self.addCleanup(item.stop)
        self.patches = patches

    def cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_public_is_the_default_and_invalid_selection_is_rejected(self):
        self.assertEqual(Settings().lambda_source, "public")
        self.assertEqual(Settings.from_env({}).lambda_source, "public")
        self.assertEqual(Settings.from_env({"LAMBDA_SOURCE": "api"}).lambda_source, "api")
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"LAMBDA_SOURCE": "private-secret-invalid"})
        self.transport.assert_not_called()

    def test_python_collects_both_public_sources_without_credentials(self):
        result = collect_prices(["lambda", "autodl"], settings=Settings.from_env({}))
        self.assertEqual(result["status"], "success")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"lambda", "autodl"})
        self.assertTrue(all(q["account_scope"] == "public_catalog" for q in result["prices"]))
        self.assertTrue(all(p["source_type"] == "public_page" for p in result["provider_results"]))
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.fetch.assert_called_once()
        self.assertEqual(self.fetch.call_args.args[0], lambda_public.SOURCE_URL)
        self.render.assert_called_once()
        self.authenticated.assert_not_called()

    def test_existing_credentials_do_not_select_authentication_or_a_saved_session(self):
        settings = Settings(lambda_api_key="synthetic-lambda-secret",
                            autodl_token="synthetic-autodl-secret",
                            autodl_storage_state_path="/nonexistent/synthetic-private-session.json")
        result = collect_prices(["lambda", "autodl"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.authenticated.assert_not_called()
        self.assertEqual(result["provider_results"][0]["source_url"], lambda_public.SOURCE_URL)
        encoded = json.dumps(result)
        self.assertNotIn("synthetic-", encoded)

    def test_only_explicit_api_selection_uses_lambda_authentication(self):
        self.authenticated.side_effect = None
        self.authenticated.return_value = json.loads((FIXTURES / "lambda-instance-types.json").read_text())
        settings = Settings(lambda_source="api", lambda_api_key="synthetic-lambda-secret")
        result = collect_prices(["lambda"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.authenticated.assert_called_once_with(
            lambda_cloud.SOURCE_URL, settings,
            headers={"Authorization": "Bearer synthetic-lambda-secret"}, authenticated=True,
        )
        self.fetch.assert_not_called()
        self.render.assert_not_called()
        self.assertEqual(result["provider_results"][0]["source_type"], "official_api")
        self.assertEqual(result["provider_results"][0]["source_url"], lambda_cloud.SOURCE_URL)
        self.assertTrue(all(q["account_scope"] == "authenticated_catalog" for q in result["prices"]))
        self.assertNotIn("synthetic-lambda-secret", json.dumps(result))

    def test_gpu_currency_and_explicit_lambda_card_counts_filter_public_quotes(self):
        result = collect_prices(["lambda", "autodl"],
                                {"gpu_models": ["h100"], "currencies": ["usd"]}, settings=Settings())
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["prices"])
        self.assertTrue(all(q["provider"] == "lambda" and q["gpu_model"] == "H100"
                            and q["currency"] == "USD" for q in result["prices"]))
        self.assertEqual(result["provider_results"][1]["status"], "no_matches")
        result = collect_prices(["lambda"], {"gpu_models": ["H100"], "gpu_counts": [2]}, settings=Settings())
        self.assertEqual([(q["gpu_count"], q["amount"]) for q in result["prices"]], [(2, "4.19")])
        result = collect_prices(["autodl"], {"gpu_models": ["h100"], "currencies": ["cny"]}, settings=Settings())
        self.assertEqual({q["pricing_tier"] for q in result["prices"]}, {"ordinary", "member"})
        self.assertEqual(len(result["prices"]), 2)

    def test_autodl_region_and_card_count_filters_fail_before_any_requests(self):
        for conditions in ({"regions": ["cn-bj2"]}, {"gpu_counts": [1]}):
            with self.subTest(conditions=conditions):
                result = collect_prices(["autodl"], conditions, settings=Settings())
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["provider_results"][0]["error"]["code"], "unsupported_filter")
                self.assertEqual(result["prices"], [])
        self.fetch.assert_not_called()
        self.render.assert_not_called()
        self.authenticated.assert_not_called()
        self.transport.assert_not_called()

    def test_public_source_failures_keep_the_other_source_results(self):
        self.render.side_effect = FetchError("network_error", "The public source could not be reached.", True)
        result = collect_prices(["lambda", "autodl"], settings=Settings())
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"lambda"})
        self.render.side_effect = None
        self.fetch.side_effect = FetchError("network_error", "The public source could not be reached.", True)
        result = collect_prices(["lambda", "autodl"], settings=Settings())
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"autodl"})

    def test_derived_public_amounts_ignore_the_callers_decimal_precision(self):
        with localcontext() as context:
            context.prec = 2
            result = collect_prices(["lambda", "autodl"], settings=Settings())
        self.assertEqual(result["status"], "success")
        b200 = next(q for q in result["prices"]
                    if q["provider"] == "lambda" and q["gpu_model"] == "B200" and q["gpu_count"] == 8)
        self.assertEqual(b200["instance_price"]["amount"], "53.52")
        self.assertIn("9.98", {q["amount"] for q in result["prices"] if q["provider"] == "autodl"})

    def test_free_config_source_types_match_selected_lambda_mode_without_network(self):
        config = json.loads((ROOT / "configs" / "collect.free.example.json").read_text())
        self.assertEqual({p["id"] for p in config["providers"] if p["enabled"]}, {"lambda", "autodl"})
        self.assertEqual(validate_config(config), [])
        self.assertTrue(validate_config(config, settings=Settings(lambda_source="api")))
        api_config = deepcopy(config)
        next(p for p in api_config["providers"] if p["id"] == "lambda")["planned_source"] = "official_api"
        self.assertEqual(validate_config(api_config, settings=Settings(lambda_source="api")), [])
        self.assertTrue(validate_config(api_config))
        code, stdout, stderr = self.cli(["validate-config", "--config", str(ROOT / "configs/collect.free.example.json")])
        self.assertEqual(code, 0)
        self.fetch.assert_not_called()
        self.render.assert_not_called()
        self.authenticated.assert_not_called()

    def test_cli_free_config_returns_json_without_keys_or_authentication(self):
        code, stdout, stderr = self.cli(["collect", "--config", str(ROOT / "configs/collect.free.example.json")])
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "success")
        self.assertEqual({p["source_type"] for p in result["provider_results"]}, {"public_page"})
        self.assertEqual(stderr, "")
        self.authenticated.assert_not_called()

    def test_cli_can_explicitly_select_the_retained_authenticated_api(self):
        self.authenticated.side_effect = None
        self.authenticated.return_value = json.loads((FIXTURES / "lambda-instance-types.json").read_text())
        with patch.dict(os.environ, {"LAMBDA_API_KEY": "synthetic-secret"}, clear=True):
            code, stdout, stderr = self.cli([
                "collect", "--providers", "lambda", "--lambda-source", "api",
            ])
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["provider_results"][0]["source_type"], "official_api")
        self.assertTrue(self.authenticated.call_args.kwargs["authenticated"])
        self.assertNotIn("synthetic-secret", stdout + stderr)
        self.fetch.assert_not_called()
        self.render.assert_not_called()

    def test_cli_explicit_source_overrides_env_and_checks_config_metadata(self):
        with patch.dict(os.environ, {"LAMBDA_SOURCE": "api", "LAMBDA_API_KEY": "synthetic-secret"}, clear=True):
            code, stdout, stderr = self.cli(["collect", "--providers", "lambda", "--lambda-source", "public"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "public_page")
        self.assertNotIn("synthetic-secret", stdout + stderr)
        self.fetch.reset_mock()
        code, stdout, stderr = self.cli([
            "collect", "--config", str(ROOT / "configs/collect.free.example.json"), "--lambda-source", "api",
        ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["error"]["code"], "configuration_error")
        self.fetch.assert_not_called()
        self.render.assert_not_called()
        self.authenticated.assert_not_called()

    def test_missing_browser_dependency_is_a_safe_partial_cli_json_error(self):
        self.patches["render"].stop()
        with patch.dict("sys.modules", {"playwright.sync_api": None}):
            code, stdout, stderr = self.cli(["collect", "--providers", "lambda,autodl"])
        result = json.loads(stdout)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"lambda"})
        self.assertEqual(result["provider_results"][1]["error"]["code"], "browser_dependency_missing")
        self.assertIn("browser_dependency_missing", stderr)
        self.assertNotIn("Traceback", stdout + stderr)
        self.authenticated.assert_not_called()

    def test_python_and_cli_do_not_discover_a_local_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text("LAMBDA_SOURCE=api\nLAMBDA_API_KEY=hidden-local-secret\n")
            with chdir(folder):
                result = collect_prices(["lambda"])
                code, stdout, stderr = self.cli(["collect", "--providers", "lambda"])
        self.assertEqual(result["provider_results"][0]["source_type"], "public_page")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["provider_results"][0]["source_type"], "public_page")
        self.assertNotIn("hidden-local-secret", stdout + stderr)
        self.authenticated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
