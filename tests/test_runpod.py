"""Anonymous full-GPU RunPod catalog pricing and fail-closed schema checks."""

from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import runpod
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "runpod-public-catalog.json"
OBSERVED = "2026-10-20T10:00:00+00:00"


def source():
    return json.loads(FIXTURE.read_text(), parse_float=Decimal)


def parse(payload=None):
    return runpod.parse_catalog(source() if payload is None else payload, observed_at=OBSERVED)


class RunPodTests(unittest.TestCase):
    def test_b300_and_h200_secure_and_community_rates_are_distinct_catalog_quotes(self):
        # Reduced shapes and amounts observed from the anonymous official API
        # on 2026-10-21; historical regression data, never a runtime fallback.
        payload = json.loads('''{"data":{"gpuTypes":[
          {"id":"NVIDIA B300 SXM6 AC","displayName":"B300","memoryInGb":288,
           "secureCloud":true,"communityCloud":true,"securePrice":8.99,"communityPrice":6.94},
          {"id":"NVIDIA H200","displayName":"H200 SXM","memoryInGb":141,
           "secureCloud":true,"communityCloud":true,"securePrice":5.29,"communityPrice":3.59}
        ]}}''', parse_float=Decimal)
        quotes = parse(payload)
        by_model_tier = {(q["gpu_model"], q["cloud_tier"]): q for q in quotes}
        self.assertEqual({k: q["amount"] for k, q in by_model_tier.items()}, {
            ("B300", "secure"): "8.99", ("B300", "community"): "6.94",
            ("H200", "secure"): "5.29", ("H200", "community"): "3.59",
        })
        self.assertEqual(by_model_tier["B300", "secure"]["gpu_variant"], "SXM6")
        self.assertEqual(by_model_tier["B300", "secure"]["vram_gb"], 288)
        self.assertEqual(by_model_tier["H200", "secure"]["gpu_variant"], "SXM")
        self.assertTrue(all(q["conditions"]["cloud_type"] == q["cloud_tier"] + "_cloud" for q in quotes))

    def test_enabled_cloud_tiers_and_per_gpu_prices_keep_unknown_geography_and_stock(self):
        quotes = parse()
        self.assertEqual(len(quotes), 9)
        by_sku_tier = {(q["raw_sku"], q["cloud_tier"]): q for q in quotes}
        mi300 = by_sku_tier["AMD Instinct MI300X OAM", "secure"]
        self.assertEqual(mi300["amount"], "2.39")
        self.assertNotIn(("AMD Instinct MI300X OAM", "community"), by_sku_tier)
        h100 = by_sku_tier["NVIDIA H100 80GB HBM3", "secure"]
        self.assertEqual((h100["gpu_model"], h100["gpu_variant"], h100["vram_gb"]), ("H100", "SXM", 80))
        self.assertEqual(h100["amount"], "3.99")
        self.assertEqual(by_sku_tier["NVIDIA H100 80GB HBM3", "community"]["amount"], "2.69")
        a100 = by_sku_tier["NVIDIA A100-SXM4-40GB", "community"]
        self.assertEqual((a100["gpu_model"], a100["vram_gb"]), ("A100", 40))
        self.assertEqual(by_sku_tier["Tesla V100-PCIE-16GB", "community"]["gpu_variant"], "PCIe")
        self.assertEqual(by_sku_tier["NVIDIA GeForce RTX 4090", "community"]["gpu_model"], "RTX 4090")
        for quote in quotes:
            self.assertIsNone(quote["gpu_count"])
            self.assertNotIn("instance_price", quote)
            self.assertEqual(quote["currency"], "USD")
            self.assertEqual(quote["unit"], "gpu_hour")
            self.assertEqual(quote["billing_mode"], "on_demand")
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["zones"], [])
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["account_scope"], "public_catalog")
            self.assertEqual(quote["geographic_scope"], "unspecified")
            self.assertEqual(quote["source_type"], "official_public_api")
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertEqual(quote["conditions"]["cloud_type"], quote["cloud_tier"] + "_cloud")
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_inactive_cloud_placeholder_prices_and_mig_are_never_full_gpu_quotes(self):
        quotes = parse()
        self.assertFalse(any("MIG" in q["raw_sku"] or q["raw_sku"] == "unknown" for q in quotes))
        self.assertFalse(any(q["raw_sku"] == "NVIDIA A100-SXM4-40GB" and q["cloud_tier"] == "secure" for q in quotes))

    def test_null_and_zero_enabled_catalog_rates_are_unquoted_not_free(self):
        for amount in (None, 0):
            payload = source()
            row = next(row for row in payload["data"]["gpuTypes"] if row["id"] == "AMD Instinct MI300X OAM")
            row["securePrice"] = amount
            quotes = parse(payload)
            self.assertEqual(len(quotes), 8)
            self.assertFalse(any(q["raw_sku"] == row["id"] for q in quotes))

    def test_prices_are_exact_and_independent_of_callers_decimal_context(self):
        payload = source()
        row = payload["data"]["gpuTypes"][0]
        row["securePrice"] = Decimal("2.390000000000000000000001")
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.Emax = 2
            quote = parse(payload)[0]
        self.assertEqual(quote["amount"], "2.390000000000000000000001")

    def test_partial_graphql_errors_never_return_data_or_echo_provider_message(self):
        payload = source()
        payload["errors"] = [{"message": "sensitive-test-provider-response"}]
        with self.assertRaises(FetchError) as captured:
            parse(payload)
        self.assertEqual(captured.exception.code, "public_api_error")
        self.assertNotIn("sensitive-test-provider-response", str(captured.exception))

    def test_malformed_rows_fail_instead_of_returning_partial_prices(self):
        changes = ({"secureCloud": 1}, {"securePrice": True}, {"securePrice": "2.39"},
                   {"securePrice": 2.39}, {"securePrice": -1}, {"securePrice": Decimal("NaN")},
                   {"securePrice": Decimal("Infinity")}, {"securePrice": Decimal("1E+1000000")},
                   {"securePrice": Decimal("1E-1000000")}, {"memoryInGb": 0}, {"memoryInGb": True},
                   {"displayName": ""}, {"displayName": "GPU\nname"}, {"id": "x" * 201})
        for change in changes:
            payload = source()
            payload["data"]["gpuTypes"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse(payload)
        payload = source()
        del payload["data"]["gpuTypes"][0]["securePrice"]
        with self.assertRaises(ValueError):
            parse(payload)

    def test_schema_empty_and_duplicate_catalogs_fail(self):
        for payload in ({}, {"data": None}, {"data": {"gpuTypes": []}},
                        {"data": {"gpuTypes": {}}}, {"data": {"gpuTypes": [None]}},
                        {"data": {"gpuTypes": source()["data"]["gpuTypes"] * 2}},
                        {"data": {"gpuTypes": [source()["data"]["gpuTypes"][-1]]}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse(payload)

    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_collection_makes_one_anonymous_readonly_pods_catalog_query(self, request):
        request.return_value = source()
        settings = Settings(lambda_api_key="unused-key", ucloud_private_key="unused-private-key")
        quotes = runpod.collect_quotes(settings=settings, observed_at=OBSERVED)
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args, ("https://api.runpod.io/graphql", settings))
        self.assertEqual(kwargs["method"], "POST")
        self.assertFalse(kwargs["authenticated"])
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        payload = json.loads(kwargs["data"])
        self.assertEqual(payload, {"query": runpod.GPU_TYPES_QUERY})
        self.assertTrue(payload["query"].startswith("query "))
        for forbidden in ("mutation", "myself", "lowestPrice", "SpotPrice", "clusterPrice", "api_key"):
            self.assertNotIn(forbidden, payload["query"])
        self.assertNotIn("unused-", json.dumps(quotes))


if __name__ == "__main__":
    unittest.main()
