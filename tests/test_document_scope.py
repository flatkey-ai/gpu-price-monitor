"""Document scope and country-price provenance, without credentials or network."""

import copy
import io
import json
from decimal import Inexact, localcontext
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from gpu_price_monitor import ConfigurationError, Settings, collect_prices
from gpu_price_monitor.cli import main
from gpu_price_monitor.collector import IMPLEMENTED_PROVIDERS
from gpu_price_monitor.geography import describe_geography, geography_summary
from gpu_price_monitor.providers import ucloud


def quote(**changes):
    value = {"provider": "ucloud", "gpu_model": "A100", "gpu_count": 1,
             "amount": "100", "currency": "CNY", "unit": "gpu_month",
             "billing_mode": "monthly", "quote_status": "quoted",
             "source_type": "official_public_api", "geographic_scope": "zone",
             "regions": ["cn-bj2"], "zones": ["cn-bj2-02"],
             "compute_countries": ["CN"], "availability": "offline"}
    value.update(changes)
    return value


class DocumentScopeTests(unittest.TestCase):
    def test_document_providers_and_public_expansion_are_registered(self):
        self.assertEqual(set(IMPLEMENTED_PROVIDERS), {"nebius", "lambda", "crusoe", "autodl", "ucloud",
                                                    "runpod", "digitalocean", "verda", "azure"})
        with patch("gpu_price_monitor.collector.fetch_text") as fetch:
            for retired in ("ebcloud", "suanli", "unknown"):
                with self.subTest(provider=retired), self.assertRaises(ConfigurationError):
                    collect_prices([retired], settings=Settings())
        fetch.assert_not_called()

    def test_country_filter_uses_bound_source_country_and_preserves_offline_status(self):
        rows = [quote(), quote(regions=["us-ca"], zones=["us-ca-01"], compute_countries=["US"])]
        with patch("gpu_price_monitor.providers.ucloud_public.collect_quotes", return_value=rows):
            result = collect_prices(["ucloud"], {"compute_countries": ["CN"], "regions": ["cn-bj2"]}, settings=Settings())
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["availability"], "offline")
        self.assertEqual(result["prices"][0]["price_scope"], "zone_quote")
        self.assertEqual(result["geographic_coverage"]["country_codes"], ["CN"])

    def test_country_mismatch_is_no_matches_but_missing_country_evidence_is_unverifiable(self):
        with patch("gpu_price_monitor.providers.ucloud_public.collect_quotes", return_value=[quote()]):
            result = collect_prices(["ucloud"], {"compute_countries": ["US"]}, settings=Settings())
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")
        with patch("gpu_price_monitor.providers.ucloud_public.collect_quotes", return_value=[quote(compute_countries=[])]):
            result = collect_prices(["ucloud"], {"compute_countries": ["US"]}, settings=Settings())
        self.assertEqual(result["provider_results"][0]["error"]["code"], "unverifiable_filter")
        self.assertEqual(result["prices"], [])

    def test_catalog_currency_and_platform_coverage_do_not_establish_country_price(self):
        rows = [quote(provider="nebius", source_type="public_documentation", geographic_scope="regions",
                      regions=["eu-north1", "us-central1"], zones=[], compute_countries=["FI", "US"]),
                quote(provider="lambda", source_type="public_page", geographic_scope="unspecified",
                      regions=[], zones=[], compute_countries=["US"], currency="USD")]
        originals = copy.deepcopy(rows)
        for row in rows:
            describe_geography(row)
            self.assertEqual(row["compute_countries"], [])
            self.assertFalse(row["region_price_verified"])
        self.assertEqual(rows[0]["regions"], originals[0]["regions"])
        summary = geography_summary(rows)
        self.assertEqual(summary["region_bound_quote_count"], 0)
        self.assertEqual(summary["platform_coverage_quote_count"], 1)

    def test_cli_country_filter_remains_json_and_exposes_provenance(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(out), redirect_stderr(err), patch(
            "gpu_price_monitor.providers.ucloud_public.collect_quotes", return_value=[quote()]
        ):
            status = main(["collect", "--providers", "ucloud", "--country", "CN", "--zone", "cn-bj2-02"])
        self.assertEqual(status, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["prices"][0]["compute_countries"], ["CN"])
        self.assertEqual(err.getvalue(), "")

    def test_nebius_target_file_is_explicit_relative_and_process_can_clear_it(self):
        example = Path(__file__).resolve().parents[1] / "configs/nebius-targets.example.json"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            raw = example.read_text()
            (folder / "targets.json").write_text(raw)
            env_file = folder / ".env"
            env_file.write_text("NEBIUS_PRICE_TARGETS_FILE=targets.json\nNEBIUS_SOURCE=api\n")
            settings = Settings.from_env({}, env_file=env_file)
            self.assertEqual(settings.nebius_price_targets_json, raw)
            self.assertNotIn("project-replace", repr(settings))
            cleared = Settings.from_env({"NEBIUS_PRICE_TARGETS_JSON": ""}, env_file=env_file)
            self.assertIsNone(cleared.nebius_price_targets_file)
            self.assertIsNone(cleared.nebius_price_targets_json)

    def test_explicit_optional_sources_fail_without_credentials_without_falling_back(self):
        with patch.dict("os.environ", {}, clear=True), patch("gpu_price_monitor.collector.fetch_text") as fetch, patch(
            "gpu_price_monitor.providers.autodl.collect_quotes"
        ) as homepage:
            for provider, option, source, error in (("nebius", "--nebius-source", "api", "missing_credentials"),
                                                     ("autodl", "--autodl-source", "market", "login_required")):
                out, err = io.StringIO(), io.StringIO()
                with self.subTest(provider=provider), redirect_stdout(out), redirect_stderr(err):
                    code = main(["collect", "--providers", provider, option, source])
                    result = json.loads(out.getvalue())
                    self.assertEqual(code, 1)
                    self.assertEqual(result["provider_results"][0]["error"]["code"], error)
            fetch.assert_not_called()
            homepage.assert_not_called()

    def test_ucloud_positive_price_cannot_round_to_zero_and_ignores_callers_traps(self):
        target = {"Region": "cn-bj2", "Zone": "cn-bj2-02", "GpuType": "A100", "GPU": 3,
                  "MachineType": "G", "CPU": 12, "Memory": 65536, "Disks": []}
        payload = {"Action": "GetUHostInstancePriceResponse", "RetCode": 0,
                   "PriceSet": [{"ChargeType": "Dynamic", "Price": "1"}]}
        with localcontext() as context:
            context.traps[Inexact] = True
            context.Emax = 1
            result = ucloud.parse_quote(payload, target, observed_at="2026-10-21T00:00:00+00:00")
        self.assertEqual(result["amount"], "0.333333333333")
        target["GPU"] = 8
        payload["PriceSet"][0]["Price"] = "0.000000000001"
        with self.assertRaises(ValueError):
            ucloud.parse_quote(payload, target, observed_at="2026-10-21T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
