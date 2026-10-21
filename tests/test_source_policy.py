"""Source selection is deterministic, offline and never retries another adapter."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import csv
from datetime import date
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from gpu_price_monitor import Settings, collect_prices
from gpu_price_monitor.cli import main, validate_config
from gpu_price_monitor.collector import provider_source
from gpu_price_monitor.csv_export import prices_to_csv, publishable_quote
from gpu_price_monitor.providers import (
    autodl, crusoe, lambda_cloud, lambda_public, nebius, nebius_quote,
    nebius_spot, ucloud, ucloud_compshare, ucloud_public,
)
from gpu_price_monitor.transport import FetchError


FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-21T08:33:00+00:00"
FIVE = ("nebius", "lambda", "ucloud", "crusoe", "autodl")
PRIVATE = "synthetic-private-test-key"


def text_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def json_fixture(name):
    return json.loads(text_fixture(name), parse_float=Decimal)


def spot_quotes():
    return nebius_spot.parse_prices(json_fixture("nebius-current-spot.json"), observed_at=OBSERVED)


def public_ucloud_quotes():
    payload = json_fixture("ucloud-public-catalog.json")
    payload.pop("_fixture_note")
    return ucloud_public.parse_catalog(**payload, observed_at=OBSERVED)


def hourly_ucloud_outcome():
    # Synthetic routing fixture; the adapter's numeric/unit/schema contracts
    # are exercised separately in test_ucloud_compshare.py.
    quote = {**public_ucloud_quotes()[0], "unit": "gpu_hour", "billing_mode": "on_demand",
             "availability": "unknown", "geographic_scope": "requested_zone",
             "source_url": ucloud_compshare.SOURCE_URL,
             "product_line": ucloud_compshare.PRODUCT_LINE}
    quote["instance_price"] = {**quote["instance_price"], "unit": "instance_hour"}
    return {"prices": [quote], "errors": [], "status": "ok", "discovery": {"requested_target_count": 1}}


def autodl_pages():
    soup = BeautifulSoup(text_fixture("autodl-public-pricing.html"), "html.parser")
    return [str(section) for section in soup.select(".display-module")]


def ucloud_target():
    return {"Region": "cn-bj2", "Zone": "cn-bj2-02", "MachineType": "G", "GpuType": "T4",
            "GPU": 2, "CPU": 8, "Memory": 32768,
            "Disks": [{"IsBoot": True, "Size": 40, "Type": "CLOUD_SSD"}]}


class SourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch("gpu_price_monitor.collector._now", return_value=OBSERVED))
        self.transport = self.block("gpu_price_monitor.transport._request_text")
        self.html = self.block("gpu_price_monitor.collector.fetch_text")
        self.browser = self.block("gpu_price_monitor.browser.fetch_autodl_pages")
        self.market = self.block("gpu_price_monitor.providers.autodl_market._render_market_pages")
        self.spot_api = self.block("gpu_price_monitor.providers.nebius_spot.request_json")
        self.lambda_api = self.block("gpu_price_monitor.providers.lambda_cloud.request_json")
        self.ucloud_api = self.block("gpu_price_monitor.providers.ucloud.request_json")
        self.compshare = self.block("gpu_price_monitor.providers.ucloud_compshare.collect_result")
        self.catalog = self.stack.enter_context(patch(
            "gpu_price_monitor.providers.nebius_catalog.collect_quotes", return_value=[]))

    def block(self, target):
        return self.stack.enter_context(patch(
            target, side_effect=AssertionError("Unexpected transport or browser call in offline test"),
        ))

    @staticmethod
    def allow(mock, value):
        mock.side_effect = None
        mock.return_value = value

    def collect_one(self, provider, **options):
        settings = Settings(providers=(provider,), **options)
        result = collect_prices(settings=settings)
        self.assertEqual(result["execution"], {
            "runtime": "python", "parsing": "deterministic_rules", "uses_llm": False,
            "source_policy": settings.source_policy,
        })
        self.assertEqual(result["provider_results"][0]["source_type"], provider_source(provider, settings))
        self.transport.assert_not_called()
        return result, result["provider_results"][0]

    def test_preferred_nebius_returns_on_demand_catalog_beside_regional_spot(self):
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        catalog_quote = {**spot_quotes()[0], "amount": "9.50", "billing_mode": "on_demand",
                         "regions": [], "compute_countries": [], "geographic_scope": "unspecified",
                         "source_url": "https://nebius.com/prices", "source_type": "official_website_json",
                         "account_scope": "public_catalog"}
        self.catalog.return_value = [catalog_quote]
        result, source = self.collect_one("nebius", source_policy="api_preferred")
        self.assertEqual(result["market_comparison"]["eligible_quote_count"], len(spot_quotes()) + 1)
        self.assertEqual(result["comparison"]["eligible_quote_count"], len(spot_quotes()))
        self.assertEqual(result["prices"][-1]["price_scope"], "unlocated_catalog")
        self.assertFalse(result["prices"][-1]["region_price_verified"])
        self.assertEqual(source["source_types"], ["official_public_api", "official_website_json"])
        self.catalog.assert_called_once()

    def test_nebius_api_failure_does_not_return_catalog_as_replacement(self):
        self.spot_api.side_effect = FetchError("network_error", "The pricing source could not be reached.", True)
        result, source = self.collect_one("nebius", source_policy="api_preferred")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual(source["error"]["code"], "network_error")
        self.catalog.assert_not_called()

    def test_nebius_api_only_never_calls_website_json(self):
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        self.catalog.side_effect = AssertionError("API-only must not call website bootstrap or catalog")
        result, _ = self.collect_one("nebius", source_policy="api_only")
        self.assertEqual(result["status"], "success")
        self.catalog.assert_not_called()

    def test_nebius_catalog_failure_retains_successful_spot_with_partial_status(self):
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        self.catalog.side_effect = FetchError("parse_failed", "Website data changed.")
        result, source = self.collect_one("nebius", source_policy="api_preferred")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["error"]["code"], "partial_collection")
        self.assertEqual(source["source_errors"][0]["code"], "parse_failed")
        self.assertEqual(len(result["prices"]), len(spot_quotes()))
        self.assertEqual({q["source_type"] for q in result["prices"]}, {"official_public_api"})

    def test_config_accepts_the_selected_mixed_public_nebius_source(self):
        settings = Settings(source_policy="api_preferred")
        config = {"schema_version": 1, "request": {"timeout_seconds": 30, "max_retries": 2},
                  "providers": [{"id": "nebius", "enabled": True,
                                 "planned_source": "official_public_sources", "filters": {}}]}
        self.assertEqual(validate_config(config, settings=settings), [])
        self.spot_api.assert_not_called()
        self.catalog.assert_not_called()

    def test_nebius_api_only_stays_pure_and_preferred_adds_website_json_catalog(self):
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        for policy in ("api_preferred", "api_only"):
            with self.subTest(policy=policy):
                self.spot_api.reset_mock()
                result, source = self.collect_one("nebius", source_policy=policy)
                self.assertEqual(result["status"], "success")
                self.assertEqual(source["source_type"], "official_public_sources" if policy == "api_preferred" else "official_public_api")
                self.assertEqual(source["source_url"], nebius_spot.SOURCE_URL)
                self.assertEqual(source["api_endpoint"], nebius_spot.SOURCE_URL)
                self.assertEqual(source["collection_method"], "http_json_with_website_bootstrap" if policy == "api_preferred" else "http_json")
                self.assertEqual(source["selection_reason"], "regional_spot_api_and_on_demand_website_json" if policy == "api_preferred" else "anonymous_regional_spot_api")
                self.assertIsNone(source["fallback_reason"])
                if policy == "api_only":
                    self.assertNotIn("additional_source_urls", source)
                self.assertEqual(result["comparison"]["eligible_quote_count"], len(spot_quotes()))
                self.assertEqual({q["source_type"] for q in result["prices"]}, {"official_public_api"})
                self.spot_api.assert_called_once_with(
                    nebius_spot.query_url(), Settings(providers=("nebius",), source_policy=policy),
                    authenticated=False,
                )
        self.html.assert_not_called()
        self.browser.assert_not_called()

    def test_configured_nebius_preserves_document_and_current_api_sources(self):
        content = text_fixture("nebius-pricing.md")
        expected_document = nebius.parse_prices(content, observed_at=OBSERVED, as_of=date(2026, 10, 21))
        self.allow(self.html, content)
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        result, source = self.collect_one("nebius")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), len(expected_document) + len(spot_quotes()))
        self.assertEqual(source["source_type"], "public_documentation")
        self.assertEqual(source["collection_method"], "hybrid_http")
        self.assertEqual(source["additional_source_urls"], [nebius_spot.SOURCE_URL])
        self.assertEqual(source["selection_reason"], "configured_source")
        self.assertEqual(result["comparison"]["eligible_quote_count"], len(spot_quotes()))
        self.html.assert_called_once_with(nebius.SOURCE_URL, Settings(providers=("nebius",)))
        self.spot_api.assert_called_once()

    def test_nebius_api_coverage_filters_fail_before_any_io(self):
        for policy in ("api_preferred", "api_only"):
            for dimension, value in (("coverage_regions", "eu-north1"), ("coverage_countries", "FI")):
                with self.subTest(policy=policy, dimension=dimension):
                    result = collect_prices(["nebius"], {dimension: [value]},
                                            settings=Settings(source_policy=policy))
                    source = result["provider_results"][0]
                    self.assertEqual(source["error"]["code"], "unsupported_filter")
                    self.assertEqual(source["filters"][dimension]["status"], "unsupported")
                    self.assertEqual(source["fetched_count"], 0)
        for mock in (self.html, self.spot_api, self.transport, self.browser):
            mock.assert_not_called()

    def test_lambda_key_selects_api_and_capacity_does_not_become_price_geography(self):
        self.allow(self.lambda_api, json_fixture("lambda-instance-types.json"))
        for policy in ("api_preferred", "api_only"):
            with self.subTest(policy=policy):
                self.lambda_api.reset_mock()
                result, source = self.collect_one("lambda", source_policy=policy, lambda_api_key=PRIVATE)
                self.assertEqual(result["status"], "success")
                self.assertEqual(source["source_type"], "official_api")
                self.assertEqual(source["source_url"], lambda_cloud.SOURCE_URL)
                self.assertEqual(source["api_endpoint"], lambda_cloud.SOURCE_URL)
                self.assertEqual(source["selection_reason"], "api_selected")
                self.assertEqual(source["collection_method"], "http_json")
                self.assertIsNone(source["fallback_reason"])
                self.assertTrue(any(q["capacity_regions"] for q in result["prices"]))
                self.assertTrue(all(q["regions"] == q["compute_countries"] == [] for q in result["prices"]))
                self.assertEqual(result["comparison"]["eligible_quote_count"], 0)
                self.assertNotIn(PRIVATE, json.dumps(result))
                self.lambda_api.assert_called_once()
        self.html.assert_not_called()

    def test_lambda_api_preferred_without_key_uses_declared_page_fallback(self):
        self.allow(self.html, text_fixture("lambda-public-pricing.html"))
        result, source = self.collect_one("lambda", source_policy="api_preferred")
        self.assertEqual(result["status"], "success")
        self.assertEqual(source["source_type"], "public_page")
        self.assertEqual(source["source_url"], lambda_public.SOURCE_URL)
        self.assertIsNone(source["api_endpoint"])
        self.assertEqual(source["collection_method"], "http_html")
        self.assertEqual(source["selection_reason"], "programmatic_page_fallback")
        self.assertEqual(source["fallback_reason"], "api_credentials_not_configured")
        self.html.assert_called_once()
        self.lambda_api.assert_not_called()

    def test_lambda_api_only_without_key_fails_without_html_or_http(self):
        result, source = self.collect_one("lambda", source_policy="api_only")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(source["error"]["code"], "missing_credentials")
        self.assertEqual(source["source_type"], "official_api")
        self.assertIsNone(source["fallback_reason"])
        self.lambda_api.assert_not_called()
        self.html.assert_not_called()
        self.browser.assert_not_called()

    def test_partial_ucloud_credentials_and_missing_targets_never_fall_back_to_promotions(self):
        cases = (
            ({"ucloud_public_key": PRIVATE}, "missing_credentials"),
            ({"ucloud_private_key": PRIVATE}, "missing_credentials"),
            ({"ucloud_public_key": PRIVATE, "ucloud_private_key": PRIVATE}, "missing_price_targets"),
        )
        with patch.object(ucloud_public, "collect_quotes") as promotion, \
                patch.object(ucloud_public, "load_location_catalog") as directory:
            for policy in ("api_preferred", "api_only"):
                for credentials, expected in cases:
                    with self.subTest(policy=policy, expected=expected, fields=tuple(credentials)):
                        result, source = self.collect_one("ucloud", source_policy=policy, **credentials)
                        self.assertEqual(result["status"], "failed")
                        self.assertEqual(source["error"]["code"], expected)
                        self.assertEqual(source["source_type"], "official_quote_api")
                        self.assertEqual(source["source_url"], ucloud.SOURCE_URL)
                        self.assertEqual(source["api_endpoint"], ucloud.SOURCE_URL)
                        self.assertIsNone(source["fallback_reason"])
                        self.assertNotIn(PRIVATE, json.dumps(result))
            promotion.assert_not_called()
            directory.assert_not_called()
        self.ucloud_api.assert_not_called()

    def test_ucloud_keys_select_hourly_quote_adapter_with_explicit_geography(self):
        payload = json_fixture("ucloud-public-catalog.json")
        directory = ucloud_public.parse_location_catalog(payload["regions"], payload["zones"])
        self.allow(self.ucloud_api, json_fixture("ucloud-price.json"))
        with patch.object(ucloud_public, "load_location_catalog", return_value=directory) as load, \
                patch.object(ucloud_public, "collect_quotes") as promotion:
            result, source = self.collect_one(
                "ucloud", source_policy="api_preferred", ucloud_public_key=PRIVATE,
                ucloud_private_key=PRIVATE, ucloud_price_targets_json=json.dumps([ucloud_target()]),
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(source["source_type"], "official_quote_api")
            self.assertEqual(source["selection_reason"], "api_selected")
            self.assertEqual(result["prices"][0]["unit"], "gpu_hour")
            self.assertEqual(result["prices"][0]["price_scope"], "requested_zone_quote")
            self.assertEqual(result["prices"][0]["compute_countries"], ["CN"])
            self.assertEqual(result["comparison"]["eligible_quote_count"], 1)
            load.assert_called_once()
            promotion.assert_not_called()
        self.ucloud_api.assert_called_once()
        self.html.assert_not_called()

    def test_ucloud_without_keys_uses_anonymous_hourly_compshare_api(self):
        self.allow(self.compshare, hourly_ucloud_outcome())
        for policy in ("api_preferred", "api_only"):
            with self.subTest(policy=policy), patch.object(
                ucloud_public, "collect_quotes", return_value=public_ucloud_quotes(),
            ) as promotion:
                result, source = self.collect_one("ucloud", source_policy=policy)
                self.assertEqual(result["status"], "success")
                self.assertEqual(source["source_type"], "official_public_api")
                self.assertEqual(source["source_url"], ucloud_compshare.SOURCE_URL)
                self.assertEqual(source["api_endpoint"], ucloud_compshare.API_URL)
                self.assertNotEqual(source["source_url"], source["api_endpoint"])
                self.assertEqual(source["selection_reason"], "anonymous_compshare_hourly_quote_api")
                self.assertEqual({q["unit"] for q in result["prices"]}, {"gpu_hour"})
                self.assertEqual(result["comparison"]["eligible_quote_count"], 1)
                self.assertEqual(len(list(csv.DictReader(io.StringIO(
                    prices_to_csv(result, bilingual_headers=False).lstrip("\ufeff"),
                )))), 1)
                promotion.assert_not_called()
        self.ucloud_api.assert_not_called()

    def test_compshare_partial_failure_retains_successes_and_exposes_target_errors(self):
        outcome = hourly_ucloud_outcome()
        outcome["status"] = "partial"
        outcome["errors"] = [{"code": "quote_rejected", "message": "Synthetic rejection.",
                              "retryable": False, "target": {"Region": "cn-sh2", "Zone": "cn-sh2-02"}}]
        self.allow(self.compshare, outcome)
        result, source = self.collect_one("ucloud", source_policy="api_preferred")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["error"]["code"], "partial_collection")
        self.assertEqual(source["target_errors"], outcome["errors"])
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(source["market_quote_count"], 1)

    def test_compshare_region_and_zone_are_passed_to_target_selection(self):
        self.allow(self.compshare, hourly_ucloud_outcome())
        result = collect_prices(["ucloud"], {"regions": ["cn-sh2"], "zones": ["cn-sh2-02"]},
                                settings=Settings(source_policy="api_preferred"))
        self.compshare.assert_called_once_with(settings=Settings(source_policy="api_preferred"),
                                              observed_at=OBSERVED, regions=["cn-sh2"], zones=["cn-sh2-02"])
        self.assertNotEqual(result["status"], "failed")

    def test_configured_policy_preserves_public_adapters_even_with_unused_keys(self):
        self.allow(self.html, text_fixture("lambda-public-pricing.html"))
        result, source = self.collect_one("lambda", lambda_api_key=PRIVATE)
        self.assertEqual(result["status"], "success")
        self.assertEqual(source["source_type"], "public_page")
        self.assertEqual(source["selection_reason"], "configured_source")
        with patch.object(ucloud_public, "collect_quotes", return_value=public_ucloud_quotes()) as promotion:
            result, source = self.collect_one("ucloud", ucloud_public_key=PRIVATE, ucloud_private_key=PRIVATE)
            self.assertEqual(result["status"], "success")
            self.assertEqual(source["source_type"], "official_public_api")
            promotion.assert_called_once()
        self.lambda_api.assert_not_called()
        self.ucloud_api.assert_not_called()

    def test_api_preferred_page_sources_report_programmatic_fallback(self):
        cases = (("crusoe", "http_html", "no_verified_gpu_rental_price_api"),
                 ("autodl", "browser_dom", "no_verified_market_price_api"))
        self.allow(self.html, text_fixture("crusoe-pricing.html"))
        self.allow(self.browser, autodl_pages())
        for provider, method, reason in cases:
            with self.subTest(provider=provider):
                result, source = self.collect_one(provider, source_policy="api_preferred")
                self.assertEqual(result["status"], "success")
                self.assertEqual(source["source_type"], "public_page")
                self.assertEqual(source["collection_method"], method)
                self.assertEqual(source["selection_reason"], "programmatic_page_fallback")
                self.assertEqual(source["fallback_reason"], reason)
                self.assertIsNone(source["api_endpoint"])
                self.assertEqual(result["comparison"]["eligible_quote_count"], 0)
        self.html.assert_called_once()
        self.browser.assert_called_once()

    def test_api_only_rejects_page_and_authorized_browser_before_io(self):
        for provider, options in (("crusoe", {}), ("autodl", {}),
                                  ("autodl", {"autodl_source": "market"})):
            with self.subTest(provider=provider, options=options):
                result, source = self.collect_one(provider, source_policy="api_only", **options)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(source["error"]["code"], "api_price_source_unavailable")
                self.assertEqual(source["selection_reason"], "api_required_but_unavailable")
                self.assertIsNone(source["fallback_reason"])
                self.assertIsNone(source["api_endpoint"])
                self.assertEqual(source["fetched_count"], 0)
                self.assertIsNone(source["observed_at"])
        for mock in (self.html, self.browser, self.market, self.transport):
            mock.assert_not_called()

    def test_explicit_api_failure_never_retries_public_or_spot_adapters(self):
        adapters = (("lambda", lambda_cloud), ("ucloud", ucloud), ("nebius", nebius_quote))
        for policy in ("configured", "api_preferred", "api_only"):
            for provider, module in adapters:
                with self.subTest(policy=policy, provider=provider), patch.object(
                    module, "collect_quotes", side_effect=FetchError("authentication_error", "Synthetic rejection."),
                ) as selected, patch.object(ucloud_public, "collect_quotes") as promotion:
                    result, source = self.collect_one(
                        provider, source_policy=policy, **{provider + "_source": "api"},
                    )
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(result["prices"], [])
                    self.assertEqual(source["error"]["code"], "authentication_error")
                    self.assertIsNone(source["fallback_reason"])
                    selected.assert_called_once()
                    promotion.assert_not_called()
        for mock in (self.html, self.browser, self.spot_api, self.transport):
            mock.assert_not_called()

    def test_five_provider_api_preferred_batch_and_status_use_actual_selected_sources(self):
        settings = Settings(providers=FIVE, source_policy="api_preferred", lambda_api_key=PRIVATE)
        expected = {
            "nebius": spot_quotes(),
            "lambda": lambda_cloud.parse_prices(json_fixture("lambda-instance-types.json"), observed_at=OBSERVED),
            "ucloud": hourly_ucloud_outcome()["prices"],
            "crusoe": crusoe.parse_prices(text_fixture("crusoe-pricing.html"), observed_at=OBSERVED,
                                           as_of=date(2026, 10, 21)),
            "autodl": [quote for page in autodl_pages()
                       for quote in autodl.parse_prices(page, observed_at=OBSERVED)],
        }
        self.allow(self.spot_api, json_fixture("nebius-current-spot.json"))
        self.allow(self.lambda_api, json_fixture("lambda-instance-types.json"))
        self.allow(self.html, text_fixture("crusoe-pricing.html"))
        self.allow(self.browser, autodl_pages())
        self.allow(self.compshare, hourly_ucloud_outcome())
        result = collect_prices(settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), sum(len(group) for group in expected.values()))
        self.assertEqual({r["provider"]: r["returned_count"] for r in result["provider_results"]},
                         {provider: len(group) for provider, group in expected.items()})
        self.assertEqual({r["status"] for r in result["provider_results"]}, {"success"})
        eligible = [q for q in result["prices"] if publishable_quote(q)]
        self.assertEqual(len(eligible), len(expected["nebius"]) + len(expected["ucloud"]))
        self.assertEqual({q["provider"] for q in eligible}, {"nebius", "ucloud"})
        self.assertEqual(result["comparison"]["eligible_quote_count"], len(eligible))
        self.assertEqual(result["execution"], {"runtime": "python", "parsing": "deterministic_rules",
                                               "uses_llm": False, "source_policy": "api_preferred"})

        # Status uses the same settings and selection as the collection, without I/O.
        for mock in (self.html, self.browser, self.spot_api, self.lambda_api):
            mock.reset_mock()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"GPU_PRICE_MONITOR_PROVIDERS": ",".join(FIVE),
                                     "LAMBDA_API_KEY": PRIVATE}, clear=True), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["status", "--source-policy", "api_preferred"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("Source policy: api_preferred", stdout.getvalue())
        for source in result["provider_results"]:
            self.assertIn(f"{source['provider']} source type: {source['source_type']}", stdout.getvalue())
        self.assertNotIn(PRIVATE, stdout.getvalue() + json.dumps(result))
        for mock in (self.html, self.browser, self.market, self.spot_api, self.lambda_api,
                     self.ucloud_api, self.transport):
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
