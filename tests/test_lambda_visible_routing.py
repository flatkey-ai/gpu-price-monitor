"""Visible catalog selection must remain explicit and respect API-only policy."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch

from gpu_price_monitor import Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.collector import _selected_module, provider_source
from gpu_price_monitor.filters import filter_support
from gpu_price_monitor import providers
from gpu_price_monitor.providers import lambda_public


class LambdaVisibleRoutingTests(TestCase):
    def setUp(self):
        self.adapter = ModuleType("gpu_price_monitor.providers.lambda_visible")
        self.adapter.SOURCE_URL = lambda_public.SOURCE_URL
        self.adapter.SOURCE_TYPE = "mixed_official_sources"
        html = (Path(__file__).parent / "fixtures/lambda-public-pricing.html").read_text()
        quotes = lambda_public.parse_prices(html, observed_at="2026-10-23T03:00:00+00:00")
        self.adapter.collect_result = Mock(side_effect=lambda **_: {
            "status": "ok", "prices": deepcopy(quotes), "errors": [], "gaps": [],
            "coverage": {"scope": "public_and_current_account_visible", "source_record_count": len(quotes)},
        })
        self.patcher = patch.object(providers, "lambda_visible", self.adapter, create=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_explicit_visible_wins_unused_key_and_session_presence(self):
        for policy in ("configured", "api_preferred"):
            with self.subTest(policy=policy):
                settings = Settings(lambda_source="visible", source_policy=policy,
                                    lambda_api_key="unused-private-key",
                                    lambda_storage_state_path="/private/session.json")
                self.assertIs(_selected_module("lambda", settings), self.adapter)
                self.assertEqual(provider_source("lambda", settings), "mixed_official_sources")
                result = collect_prices(["lambda"], settings=settings)
                self.assertEqual(result["status"], "success")
                source = result["provider_results"][0]
                self.assertEqual(source["selection_reason"], "explicit_public_and_console_visible_catalogs")
                self.assertIsNone(source["fallback_reason"])
                self.assertNotIn("unused-private-key", json.dumps(result))
                self.assertNotIn("/private/session.json", json.dumps(result))

    def test_api_only_rejects_mixed_source_before_network(self):
        result = collect_prices(["lambda"], settings=Settings(lambda_source="visible", source_policy="api_only"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "api_price_source_unavailable")
        self.adapter.collect_result.assert_not_called()

    def test_complete_does_not_add_unrequested_contract_price_gap(self):
        result = collect_prices(["lambda"], settings=Settings(lambda_source="visible", catalog_scope="complete"))
        self.assertEqual(result["status"], "success")
        self.assertNotIn("negotiated_or_account_specific_prices", json.dumps(result["provider_results"][0]["gaps"]))

    def test_geographic_filters_are_supported_but_do_not_bind_public_prices(self):
        settings = Settings(lambda_source="visible")
        filters = {"regions": ["us-east-1"], "compute_countries": ["US"]}
        self.assertTrue(all(item["status"] == "applied_locally" for item in filter_support("lambda", filters, settings=settings).values()))
        result = collect_prices(["lambda"], filters=filters, settings=settings)
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")

    def test_cli_selects_visible_and_returns_json(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as output:
            status = main(["collect", "--providers", "lambda", "--lambda-source", "visible"])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["provider_results"][0]["source_type"], "mixed_official_sources")
        self.assertEqual(self.adapter.collect_result.call_args.kwargs["settings"].lambda_source, "visible")

    def test_env_visible_is_accepted_without_accessing_credentials(self):
        settings = Settings.from_env({"LAMBDA_SOURCE": "visible"})
        self.assertEqual(settings.lambda_source, "visible")
        self.adapter.collect_result.assert_not_called()
