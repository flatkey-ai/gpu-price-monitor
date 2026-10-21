"""Synthetic Lambda API fixtures: instance arithmetic and credential isolation."""

from copy import deepcopy
from decimal import localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers.lambda_cloud import SOURCE_URL, collect_quotes, parse_prices
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


OBSERVED = "2026-10-15T00:00:00+00:00"
FIXTURE = Path(__file__).parent / "fixtures" / "lambda-instance-types.json"


class LambdaParserTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def parse(self, payload=None):
        return parse_prices(self.payload if payload is None else payload, observed_at=OBSERVED)

    def instance(self, payload=None):
        value = self.payload if payload is None else payload
        return value["data"]["gpu_8x_h100_sxm5"]["instance_type"]

    def test_complete_instance_price_is_allocated_by_gpu_count(self):
        rows = self.parse()
        self.assertEqual(len(rows), 3)
        row = rows[0]
        self.assertEqual(row["amount"], "4.49")
        self.assertEqual(row["price_basis"], "instance_total_allocated")
        self.assertEqual(row["instance_price"], {
            "amount": "35.92", "currency": "USD", "unit": "instance_hour",
        })
        self.assertEqual(row["unit"], "gpu_hour")
        self.assertEqual(row["gpu_count"], 8)
        self.assertEqual(row["resources"], {
            "vcpus": 208, "memory_gib": 1800, "storage_gib": 24780,
            "architecture": "x86_64",
        })
        self.assertEqual(row["gpu_model"], "H100")
        self.assertEqual(row["gpu_variant"], "SXM5")
        self.assertEqual(row["vram_gb"], 80)
        self.assertEqual(row["raw_sku"], "gpu_8x_h100_sxm5")
        self.assertEqual(row["account_scope"], "authenticated_catalog")
        self.assertEqual(row["observed_at"], OBSERVED)
        self.assertEqual(row["source_url"], SOURCE_URL)

    def test_capacity_regions_do_not_become_regional_prices(self):
        rows = self.parse()
        self.assertEqual(rows[0]["regions"], [])
        self.assertEqual(rows[0]["capacity_regions"], ["us-west-1", "us-east-1"])
        self.assertEqual(rows[0]["geographic_scope"], "unspecified")
        self.assertEqual(rows[1]["capacity_regions"], [])
        self.assertEqual(rows[1]["availability"], "no_capacity_reported")
        self.assertEqual(rows[1]["amount"], "0.75")

    def test_unpublished_vram_and_variant_are_not_inferred_from_sku(self):
        row = self.parse()[2]
        self.assertEqual(row["gpu_model"], "EXAMPLE GPU")
        self.assertIsNone(row["vram_gb"])
        self.assertIsNone(row["gpu_variant"])
        self.assertEqual(row["amount"], "1.005")

    def test_decimal_conversion_does_not_use_callers_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            rows = self.parse()
        self.assertEqual(rows[0]["amount"], "4.49")
        self.assertEqual(rows[2]["amount"], "1.005")
        self.instance()["specs"]["gpus"] = 3
        row = self.parse()[0]
        self.assertTrue(row["amount"].startswith("11.973333333333333333333333333333"))
        self.assertTrue(any("significant decimal digits" in note for note in row["notes"]))

    def test_explicit_zero_price_is_retained(self):
        self.instance()["price_cents_per_hour"] = 0
        self.assertEqual(self.parse()[0]["amount"], "0")

    def test_no_extra_requests_or_price_rows_for_capacity_regions(self):
        self.assertEqual(len(self.parse()), len(self.payload["data"]))

    def test_every_returned_sku_including_new_gpus_and_counts_is_parsed_without_a_roster_filter(self):
        payload = deepcopy(self.payload)
        template = deepcopy(payload["data"]["gpu_8x_h100_sxm5"])
        for count in (1, 2, 4, 8, 16):
            sku = f"synthetic_{count}x_b300"
            item = deepcopy(template)
            item["instance_type"].update(name=sku, description=f"{count}x B300 synthetic fixture",
                                         gpu_description="NVIDIA B300 (288 GB SXM6)", price_cents_per_hour=12345)
            item["instance_type"]["specs"]["gpus"] = count
            payload["data"][sku] = item
        rows = self.parse(payload)
        self.assertEqual({q["raw_sku"] for q in rows}, set(payload["data"]))
        self.assertEqual(len(rows), len(payload["data"]))
        b300 = [q for q in rows if q["gpu_model"] == "B300"]
        self.assertEqual({q["gpu_count"] for q in b300}, {1, 2, 4, 8, 16})
        self.assertTrue(all(q["gpu_variant"] == "SXM6" and q["vram_gb"] == 288 for q in b300))
        self.assertTrue(all(q["product_line"] == "On-Demand Cloud" and q["configuration_expansion"] is False for q in rows))
        self.assertTrue(all(q["price_record_kind"] == "api_catalog_price" for q in rows))

    def test_empty_catalog_is_explicitly_accepted(self):
        self.assertEqual(self.parse({"data": {}}), [])

    def test_missing_and_malformed_payloads_fail_closed(self):
        for payload in ([], None, {}, {"data": []}, {"data": None}, {"data": {"bad": {}}}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_prices(payload, observed_at=OBSERVED)

    def test_invalid_prices_and_gpu_counts_fail_without_partial_catalog(self):
        for field, value in (
            ("price_cents_per_hour", -1), ("price_cents_per_hour", 1.5),
            ("price_cents_per_hour", "3592"), ("price_cents_per_hour", True),
            ("gpus", 0), ("gpus", -1), ("gpus", 1.5), ("gpus", True),
        ):
            with self.subTest(field=field, value=value):
                payload = deepcopy(self.payload)
                instance = self.instance(payload)
                (instance["specs"] if field == "gpus" else instance)[field] = value
                with self.assertRaises(ValueError):
                    self.parse(payload)

    def test_invalid_configuration_fields_are_rejected(self):
        for field, value in (("name", "different-sku"), ("description", ""),
                             ("gpu_description", None), ("architecture", "")):
            with self.subTest(field=field):
                payload = deepcopy(self.payload)
                self.instance(payload)[field] = value
                with self.assertRaises(ValueError):
                    self.parse(payload)
        for field, value in (("vcpus", 0), ("memory_gib", "1800"), ("storage_gib", -1)):
            with self.subTest(field=field):
                payload = deepcopy(self.payload)
                self.instance(payload)["specs"][field] = value
                with self.assertRaises(ValueError):
                    self.parse(payload)

    def test_gpu_description_without_parentheses_uses_explicit_fields(self):
        self.instance()["gpu_description"] = "NVIDIA H100 80GB PCIe"
        row = self.parse()[0]
        self.assertEqual((row["gpu_model"], row["gpu_variant"], row["vram_gb"]),
                         ("H100", "PCIe", 80))

    def test_missing_or_invalid_capacity_regions_fail(self):
        for capacity in (None, {}, ["us-west-1"], [{"name": "us-west-1"}],
                         [{"name": "us-west-1", "description": "USA"}] * 2):
            with self.subTest(capacity=capacity):
                payload = deepcopy(self.payload)
                payload["data"]["gpu_8x_h100_sxm5"]["regions_with_capacity_available"] = capacity
                with self.assertRaises(ValueError):
                    self.parse(payload)

    def test_api_error_messages_are_not_exposed(self):
        for code in ("global/invalid-api-key", "provider/internal-unavailable"):
            with self.subTest(code=code):
                with self.assertRaises(FetchError) as raised:
                    self.parse({"error": {"code": code, "message": "sensitive-test-value"}})
                self.assertNotIn("sensitive-test-value", str(raised.exception))
                self.assertIn(raised.exception.code, {"authentication_error", "provider_error"})


class LambdaCollectionTests(unittest.TestCase):
    @patch("gpu_price_monitor.providers.lambda_cloud.request_json")
    def test_missing_credentials_do_not_make_requests(self, request):
        for key in (None, "", "   "):
            with self.subTest(key=key):
                with self.assertRaises(FetchError) as raised:
                    collect_quotes(settings=Settings(lambda_api_key=key), observed_at=OBSERVED)
                self.assertEqual(raised.exception.code, "missing_credentials")
        request.assert_not_called()

    @patch("gpu_price_monitor.providers.lambda_cloud.request_json")
    def test_bearer_authentication_is_outside_json_results(self, request):
        request.return_value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        settings = Settings(lambda_api_key="synthetic-api-key")
        rows = collect_quotes(settings=settings, observed_at=OBSERVED)
        request.assert_called_once_with(
            SOURCE_URL, settings,
            headers={"Authorization": "Bearer synthetic-api-key"}, authenticated=True,
        )
        self.assertNotIn("synthetic-api-key", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
