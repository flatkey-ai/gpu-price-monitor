"""Offline integration of the explicit UHost console adapter with Python/CLI."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch

from gpu_price_monitor import Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.collector import _selected_module, provider_source
from gpu_price_monitor import providers
from gpu_price_monitor.providers import ucloud, ucloud_compshare, ucloud_public
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-22T10:00:00+00:00"
SOURCE_URL = "https://api.ucloud.cn?Action=GetUHostInstancePrice"


def quote(region="cn-bj2", zone="cn-bj2-02"):
    return {"provider": "ucloud", "product_type": "gpu_instance", "gpu_model": "T4", "gpu_count": 1,
            "raw_name": "Synthetic UHost GPU", "raw_sku": "synthetic-uhost-1", "vram_gb": 16,
            "amount": "3.50", "currency": "CNY", "unit": "gpu_hour", "billing_mode": "on_demand",
            "price_basis": "calculated_per_gpu", "quote_status": "quoted", "pricing_tier": "ordinary",
            "regions": [region], "zones": [zone], "compute_countries": ["CN"],
            "geographic_scope": "requested_zone", "availability": "unknown", "conditions": [],
            "source_url": SOURCE_URL, "source_type": "official_internal_api", "observed_at": OBSERVED}


def outcome():
    return {"status": "ok", "prices": [quote(), quote("cn-sh2", "cn-sh2-02")], "errors": [], "gaps": [],
            "coverage": {"quoted_target_count": 2}, "authentication_method": "caller_exported_console_session"}


class UCloudConsoleRoutingTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.adapter = ModuleType("gpu_price_monitor.providers.ucloud_console")
        self.adapter.SOURCE_URL = SOURCE_URL
        self.adapter.SOURCE_TYPE = "official_internal_api"
        self.adapter.collect_result = Mock(side_effect=lambda **_: deepcopy(outcome()))
        # Isolate selection/outcome behavior from HTTP/protocol implementation.
        self.stack.enter_context(patch.object(providers, "ucloud_console", self.adapter, create=True))
        self.stack.enter_context(patch("gpu_price_monitor.collector._now", return_value=OBSERVED))
        self.network = self.stack.enter_context(patch("gpu_price_monitor.transport._request_text", side_effect=AssertionError("No network")))
        self.legacy = [self.stack.enter_context(patch.object(module, name, side_effect=AssertionError("No fallback")))
                       for module, name in ((ucloud, "collect_quotes"), (ucloud_public, "collect_quotes"),
                                            (ucloud_compshare, "collect_result"))]

    def test_console_selection_wins_every_policy_even_with_unused_api_keys(self):
        for policy in ("configured", "api_preferred", "api_only"):
            for with_keys in (False, True):
                with self.subTest(policy=policy, with_keys=with_keys):
                    settings = Settings(providers=("ucloud",), source_policy=policy, ucloud_source="console",
                                        ucloud_public_key="unused-private-key" if with_keys else None,
                                        ucloud_private_key="unused-private-secret" if with_keys else None)
                    self.assertIs(_selected_module("ucloud", settings), self.adapter)
                    self.assertEqual(provider_source("ucloud", settings), "official_internal_api")
                    result = collect_prices(settings=settings)
                    source = result["provider_results"][0]
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(source["source_url"], SOURCE_URL)
                    self.assertEqual(source["source_type"], "official_internal_api")
                    self.assertEqual(source["collection_method"], "authenticated_http_json")
                    self.assertEqual(source["selection_reason"], "explicit_uhost_console_session_catalog")
                    self.assertEqual(source["api_endpoint"], SOURCE_URL)
                    self.assertIsNone(source["fallback_reason"])
                    self.assertEqual(source["coverage"], {"quoted_target_count": 2})
                    self.assertNotIn("unused-private", json.dumps(result))
        self.network.assert_not_called()
        for legacy in self.legacy:
            legacy.assert_not_called()

    def test_country_region_and_zone_filters_apply_to_returned_uhost_quotes(self):
        settings = Settings(ucloud_source="console", source_policy="api_only")
        result = collect_prices(["ucloud"], {"regions": ["cn-bj2"], "zones": ["cn-bj2-02"],
                                            "compute_countries": ["CN"]}, settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["regions"], ["cn-bj2"])
        self.assertEqual(result["prices"][0]["zones"], ["cn-bj2-02"])
        self.adapter.collect_result.assert_called_once_with(settings=settings, observed_at=OBSERVED,
                                                            regions=["cn-bj2"], zones=["cn-bj2-02"], gpu_models=None)

    def test_session_failure_has_no_signed_api_public_promotion_or_compshare_fallback(self):
        self.adapter.collect_result.side_effect = FetchError("authentication_error", "The configured session was rejected.")
        for policy in ("configured", "api_preferred", "api_only"):
            with self.subTest(policy=policy):
                result = collect_prices(["ucloud"], settings=Settings(ucloud_source="console", source_policy=policy))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["prices"], [])
                source = result["provider_results"][0]
                self.assertEqual(source["error"]["code"], "authentication_error")
                self.assertEqual(source["source_type"], "official_internal_api")
                self.assertIsNone(source["fallback_reason"])
        for legacy in self.legacy:
            legacy.assert_not_called()

    def test_partial_catalog_retains_real_quotes_and_reports_unpriced_targets(self):
        partial = outcome()
        partial["status"] = "partial"
        partial["gaps"] = [{"scope": "uhost_gpu_configuration", "status": "quote_rejected", "region": "cn-gz"}]
        self.adapter.collect_result.side_effect = None
        self.adapter.collect_result.return_value = partial
        result = collect_prices(["ucloud"], settings=Settings(ucloud_source="console", source_policy="api_only",
                                                            catalog_scope="complete"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        source = result["provider_results"][0]
        self.assertEqual(source["gaps"], partial["gaps"])
        self.assertEqual(source["source_errors"][0]["code"], "incomplete_catalog")
        self.assertEqual(source["source_contexts"][0]["status"], "partial")
        self.assertEqual(source["authentication_method"], "caller_exported_console_session")

    def test_empty_failed_catalog_does_not_become_success(self):
        self.adapter.collect_result.side_effect = None
        self.adapter.collect_result.return_value = {"status": "failed", "prices": [], "errors": [],
                                                   "gaps": [{"scope": "uhost_gpu_catalog", "status": "unavailable"}]}
        result = collect_prices(["ucloud"], settings=Settings(ucloud_source="console"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["source_errors"][0]["code"], "incomplete_catalog")

    def test_cli_accepts_console_source_and_status_exposes_no_session_path(self):
        with patch.dict(os.environ, {"UCLOUD_SESSION_PATH": "/private/synthetic-session.json"}, clear=True), \
                redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(["collect", "--providers", "ucloud", "--ucloud-source", "console", "--source-policy", "api_only"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "success")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(self.adapter.collect_result.call_args.kwargs["settings"].ucloud_source, "console")
        self.assertNotIn("synthetic-session", stdout.getvalue())
        with patch.dict(os.environ, {"GPU_PRICE_MONITOR_PROVIDERS": "ucloud", "UCLOUD_SOURCE": "console",
                                    "UCLOUD_SESSION_PATH": "/private/synthetic-session.json"}, clear=True), \
                redirect_stdout(io.StringIO()) as status_output, redirect_stderr(io.StringIO()):
            status_code = main(["status", "--source-policy", "api_only"])
        self.assertEqual(status_code, 0)
        self.assertIn("ucloud source type: official_internal_api", status_output.getvalue())
        self.assertNotIn("synthetic-session", status_output.getvalue())
