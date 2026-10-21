"""Authenticated API integration with synthetic responses, never real keys."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

from gpu_price_monitor import Settings, collect_prices
from gpu_price_monitor.cli import main, validate_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def response(payload_file):
    item = MagicMock()
    item.__enter__.return_value = item
    body = (FIXTURES / payload_file).read_bytes()
    item.read.return_value = body
    item.headers = Message()
    item.headers["Content-Type"] = "application/json; charset=utf-8"
    item.headers["Content-Length"] = str(len(body))
    return item


class AuthenticatedIntegrationTests(unittest.TestCase):
    def setUp(self):
        catalog = {"cn-bj2-02": {"region": "cn-bj2", "zone": "cn-bj2-02",
                   "country_code": "CN", "region_name": "北京二", "zone_name": "可用区B"}}
        geography = patch("gpu_price_monitor.providers.ucloud_public.load_location_catalog", return_value=catalog)
        geography.start()
        self.addCleanup(geography.stop)
        self.settings = Settings(
            providers=("lambda", "ucloud"), max_retries=0,
            lambda_source="api", ucloud_source="api",
            lambda_api_key="synthetic-lambda-key",
            ucloud_public_key="synthetic-public", ucloud_private_key="synthetic-private",
            ucloud_project_id="org-synthetic",
            ucloud_price_targets_json=(ROOT / "configs/ucloud-targets.example.json").read_text(),
        )

    def test_real_transport_parses_decimal_prices_and_normalizes_both_providers(self):
        opener = MagicMock()
        opener.open.side_effect = [response("lambda-instance-types.json"), response("ucloud-price.json")]
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            result = collect_prices(settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual({q["provider"] for q in result["prices"]}, {"lambda", "ucloud"})
        lambda_quote = next(q for q in result["prices"] if q["provider"] == "lambda")
        self.assertEqual(lambda_quote["amount"], "4.49")
        self.assertEqual(lambda_quote["instance_price"]["amount"], "35.92")
        ucloud_quote = next(q for q in result["prices"] if q["provider"] == "ucloud")
        self.assertEqual(ucloud_quote["amount"], "8.4")
        serialized = json.dumps(result, allow_nan=False)
        for secret in ("synthetic-lambda-key", "synthetic-public", "synthetic-private", "org-synthetic"):
            self.assertNotIn(secret, serialized)
        first = opener.open.call_args_list[0].args[0]
        self.assertEqual(first.get_method(), "GET")
        self.assertEqual(first.get_header("Authorization"), "Bearer synthetic-lambda-key")
        second = opener.open.call_args_list[1].args[0]
        self.assertEqual(second.get_method(), "POST")
        params = parse_qs(second.data.decode())
        self.assertEqual(params["Action"], ["GetUHostInstancePrice"])
        self.assertEqual(params["Count"], ["1"])
        self.assertNotIn("PrivateKey", params)

    def test_missing_keys_are_structured_without_any_network_request(self):
        with patch("gpu_price_monitor.transport.build_opener") as opener:
            result = collect_prices(["lambda", "ucloud"], settings=Settings(lambda_source="api", ucloud_source="api"))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(p["error"]["code"] == "missing_credentials" for p in result["provider_results"]))
        opener.assert_not_called()

    def test_missing_ucloud_targets_do_not_send_a_request(self):
        with patch("gpu_price_monitor.transport.build_opener") as opener:
            result = collect_prices(["ucloud"], settings=Settings(ucloud_source="api", ucloud_public_key="test", ucloud_private_key="test"))
        self.assertEqual(result["provider_results"][0]["error"]["code"], "missing_price_targets")
        opener.assert_not_called()

    def test_lambda_capacity_cannot_satisfy_a_region_filter(self):
        with patch("gpu_price_monitor.transport.build_opener") as opener:
            result = collect_prices(["lambda"], {"regions": ["us-west-1"]}, settings=self.settings)
        self.assertEqual(result["provider_results"][0]["error"]["code"], "unsupported_filter")
        opener.assert_not_called()

    def test_lambda_gpu_count_filter_matches_known_instance_count(self):
        opener = MagicMock()
        opener.open.return_value = response("lambda-instance-types.json")
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            result = collect_prices(["lambda"], {"gpu_counts": [8]}, settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["gpu_count"], 8)

    def test_ucloud_zone_and_region_match_request_context(self):
        opener = MagicMock()
        opener.open.return_value = response("ucloud-price.json")
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            result = collect_prices(["ucloud"], {"regions": ["cn-bj2"], "zones": ["cn-bj2-02"], "gpu_counts": [1]}, settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["prices"][0]["geographic_scope"], "requested_zone")
        self.assertEqual(result["prices"][0]["account_scope"], "account_quote")

    def test_ucloud_targets_remain_identifiable_without_project_ids(self):
        targets = json.loads(self.settings.ucloud_price_targets_json)
        first, second = dict(targets[0]), dict(targets[0])
        first["ProjectId"], second["ProjectId"] = "org-first", "org-second"
        settings = Settings(ucloud_source="api", ucloud_public_key="test", ucloud_private_key="test",
                            ucloud_price_targets_json=json.dumps([first, second]), max_retries=0)
        opener = MagicMock()
        opener.open.side_effect = [response("ucloud-price.json"), response("ucloud-price.json")]
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            result = collect_prices(["ucloud"], settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual([q["target_index"] for q in result["prices"]], [0, 1])
        self.assertNotIn("org-first", json.dumps(result))
        self.assertNotIn("org-second", json.dumps(result))

    def test_empty_authenticated_catalog_is_no_matches_not_parse_failure(self):
        opener = MagicMock()
        empty = response("lambda-instance-types.json")
        empty.read.return_value = b'{"data": {}}'
        empty.headers.replace_header("Content-Length", "12")
        opener.open.return_value = empty
        with patch("gpu_price_monitor.transport.build_opener", return_value=opener):
            result = collect_prices(["lambda"], settings=self.settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_results"][0]["status"], "no_matches")

    def test_authenticated_config_enabled_and_cli_json_failure_contract(self):
        config = json.loads((ROOT / "configs/collect.example.json").read_text())
        config["providers"][2]["enabled"] = True
        config["providers"][2]["planned_source"] = "official_api"
        config["providers"][3]["enabled"] = True
        config["providers"][3]["planned_source"] = "official_quote_api"
        self.assertEqual(validate_config(config, settings=self.settings), [])
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {"LAMBDA_SOURCE": "api", "UCLOUD_SOURCE": "api"}, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = main(["collect", "--providers", "lambda,ucloud"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["status"], "failed")
        self.assertIn("missing_credentials", err.getvalue())


if __name__ == "__main__":
    unittest.main()
