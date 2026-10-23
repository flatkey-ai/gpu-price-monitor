"""Real schema regressions for anonymous, explicitly bound data-center prices."""

import json
from decimal import Decimal
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import runpod
from gpu_price_monitor.filters import apply_filters, filter_support
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

TIME = "2026-10-23T07:00:00+00:00"
SKU = "NVIDIA H100 80GB HBM3"


def catalog_payload():
    # Reduced official anonymous response, observed 2026-10-23; not a fallback.
    return json.loads('''{"data":{"gpuTypes":[{"id":"NVIDIA H100 80GB HBM3",
      "displayName":"H100 SXM","memoryInGb":80,"secureCloud":true,
      "communityCloud":true,"securePrice":3.99,"communityPrice":2.69}]}}''', parse_float=Decimal)


def centers_payload():
    return {"data": {"dataCenters": [
        {"id": "AP-IN-1", "name": "AP-IN-1", "location": "India"},
        {"id": "EU-CZ-1", "name": "EU-CZ-1", "location": "Europe"},
        {"id": "SEA-SG-1", "name": "SEA-SG-1", "location": "SE Asia"},
    ]}}


def regional_payload():
    return {"data": {"gpuTypes": [{"id": SKU, "secure": {
        "uninterruptablePrice": Decimal("3.99"), "countryCode": None,
        "stockStatus": "Low", "minMemory": 251, "minVcpu": 28},
        "community": {"uninterruptablePrice": None, "countryCode": None,
                      "stockStatus": None, "minMemory": None, "minVcpu": None}}]}}


def parse(payload=None):
    center = runpod.parse_data_centers(centers_payload())[0][0]
    return runpod.parse_region_prices(payload or regional_payload(), center=center,
        catalog=runpod.parse_catalog(catalog_payload(), observed_at=TIME), expected_ids={SKU}, observed_at=TIME)


class RunpodRegionalTests(unittest.TestCase):
    def test_geographic_filter_rejects_catalog_and_other_locations(self):
        catalog = runpod.parse_catalog(catalog_payload(), observed_at=TIME)
        regional, _ = parse()
        filters = {"compute_countries": ["IN"], "zones": ["AP-IN-1"], "gpu_counts": [1]}
        self.assertEqual(apply_filters(catalog + regional, filters), regional)
        self.assertEqual(apply_filters(regional, {**filters, "compute_countries": ["US"]}), [])
        for scope, status in (("complete", "applied_locally"), ("standard", "unsupported")):
            support = filter_support("runpod", filters, settings=Settings(providers=("runpod",), catalog_scope=scope))
            self.assertTrue(all(item["status"] == status for item in support.values()))

    def test_country_comes_from_explicit_location_not_datacenter_code(self):
        centers, exclusions = runpod.parse_data_centers(centers_payload())
        self.assertEqual([(c["id"], c["country_code"]) for c in centers], [("AP-IN-1", "IN")])
        self.assertEqual([e["data_center_id"] for e in exclusions], ["EU-CZ-1", "SEA-SG-1"])
        self.assertTrue(all(e["code"] == "country_not_explicit" for e in exclusions))

    def test_lowest_price_keeps_request_binding_and_is_not_a_fixed_configuration(self):
        rows, missing = parse()
        self.assertEqual((len(rows), missing), (1, 1))
        q = rows[0]
        self.assertEqual((q["amount"], q["gpu_count"], q["cloud_tier"]), ("3.99", 1, "secure"))
        self.assertEqual((q["quote_status"], q["price_basis"]), ("starting_at", "starting_price"))
        self.assertEqual(q["conditions"]["quote_request"], {"dataCenterId": "AP-IN-1", "gpuCount": 1, "secureCloud": True})
        self.assertEqual(q["compute_countries"], ["IN"])
        self.assertEqual(q["zones"], ["AP-IN-1"])
        self.assertEqual(q["price_scope"], "requested_zone_quote")
        self.assertEqual(q["conditions"]["minimum_ram_gb"], 251)
        self.assertNotIn("vcpus", q)
        self.assertEqual(q["availability"], "available")
        self.assertEqual(q["observed_at"], TIME)

    def test_null_or_zero_region_never_falls_back_to_catalog_price(self):
        for amount in (None, 0):
            value = regional_payload()
            value["data"]["gpuTypes"][0]["secure"]["uninterruptablePrice"] = amount
            self.assertEqual(parse(value), ([], 2))

    def test_mismatched_country_schema_and_partial_errors_fail(self):
        for modify in (
            lambda p: p["data"]["gpuTypes"][0]["secure"].update(countryCode="US"),
            lambda p: p["data"]["gpuTypes"][0]["secure"].update(minVcpu=True),
            lambda p: p["data"]["gpuTypes"][0]["secure"].update(uninterruptablePrice="3.99"),
            lambda p: p["data"]["gpuTypes"][0].pop("community"),
            lambda p: p["data"]["gpuTypes"].append(p["data"]["gpuTypes"][0]),
            lambda p: p.update(errors=[{"message": "untrusted upstream body"}]),
        ):
            value = regional_payload()
            modify(value)
            with self.assertRaises(ValueError):
                parse(value)

    def test_datacenter_limit_duplicates_and_unknown_country_are_not_guessed(self):
        value = centers_payload()
        value["data"]["dataCenters"] *= 30
        with self.assertRaises(ValueError):
            runpod.parse_data_centers(value)
        value = centers_payload()
        value["data"]["dataCenters"].append(value["data"]["dataCenters"][0])
        with self.assertRaises(ValueError):
            runpod.parse_data_centers(value)

    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_complete_collection_is_anonymous_fixed_query_and_bounded(self, request):
        request.side_effect = [catalog_payload(), centers_payload(), regional_payload()]
        settings = Settings(providers=("runpod",), catalog_scope="complete", timeout_seconds=200, max_retries=10,
                            lambda_api_key="unused-credential")
        result = runpod.collect_result(settings=settings, observed_at=TIME)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual(result["coverage"]["regional_quote_count"], 1)
        self.assertEqual(result["coverage"]["queried_data_center_count"], 1)
        self.assertEqual(len(result["coverage"]["country_unverified_data_centers"]), 2)
        self.assertEqual(request.call_count, 3)
        for call in request.call_args_list:
            self.assertEqual(call.args[0], runpod.API_URL)
            self.assertLessEqual(call.args[1].timeout_seconds, 20)
            self.assertEqual(call.args[1].max_retries, 0)
            self.assertFalse(call.kwargs["authenticated"])
            self.assertNotIn("Authorization", call.kwargs["headers"])
        body = json.loads(request.call_args.kwargs["data"])
        self.assertEqual(body["query"], runpod.REGION_PRICES_QUERY)
        self.assertEqual(body["variables"]["community"], {"dataCenterId": "AP-IN-1", "gpuCount": 1, "secureCloud": False})
        self.assertNotIn("unused-credential", json.dumps(result))

    def test_regional_price_does_not_require_a_positive_global_catalog_rate(self):
        for secure_rate, community_rate, expected_catalog_count in (
                (None, Decimal("2.69"), 1), (0, Decimal("2.69"), 1), (None, 0, 0)):
            with self.subTest(secure_rate=secure_rate, community_rate=community_rate):
                payload = catalog_payload()
                payload["data"]["gpuTypes"][0].update(securePrice=secure_rate, communityPrice=community_rate)
                with patch.object(runpod, "request_json", side_effect=[
                        payload, centers_payload(), regional_payload()]):
                    result = runpod.collect_result(settings=Settings(providers=("runpod",), catalog_scope="complete"),
                                                   observed_at=TIME)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["coverage"]["catalog_quote_count"], expected_catalog_count)
                self.assertEqual(result["coverage"]["regional_quote_count"], 1)
                self.assertEqual(result["coverage"]["unquoted_region_tier_count"], 1)
                regional = [q for q in result["prices"] if q["regions"]]
                self.assertEqual(len(regional), 1)
                self.assertEqual((regional[0]["amount"], regional[0]["cloud_tier"], regional[0]["regions"]),
                                 ("3.99", "secure", ["AP-IN-1"]))
                self.assertEqual(regional[0]["quote_status"], "starting_at")
                self.assertFalse(any(q["cloud_tier"] == "secure" and not q["regions"] for q in result["prices"]))
                self.assertTrue(all(Decimal(q["amount"]) > 0 for q in result["prices"]))

    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_unpriced_metadata_does_not_enable_a_disabled_cloud_tier(self, request):
        payload = catalog_payload()
        payload["data"]["gpuTypes"][0].update(secureCloud=False, securePrice=None)
        request.side_effect = [payload, centers_payload(), regional_payload()]
        result = runpod.collect_result(settings=Settings(providers=("runpod",), catalog_scope="complete"),
                                       observed_at=TIME)
        self.assertEqual(result["coverage"]["regional_quote_count"], 0)
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["cloud_tier"], "community")

    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_failure_preserves_catalog_but_reports_partial_and_does_not_echo_body(self, request):
        request.side_effect = [catalog_payload(), centers_payload(), {"errors": [{"message": "private upstream detail"}]}]
        result = runpod.collect_result(settings=Settings(providers=("runpod",), catalog_scope="complete"), observed_at=TIME)
        self.assertEqual((result["status"], len(result["prices"])), ("partial", 2))
        self.assertEqual(result["errors"][0]["data_center_id"], "AP-IN-1")
        self.assertNotIn("private upstream detail", json.dumps(result))

    @patch("gpu_price_monitor.providers.runpod.time.monotonic", side_effect=[0, 181])
    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_budget_stops_before_another_regional_request(self, request, _clock):
        request.side_effect = [catalog_payload(), centers_payload()]
        result = runpod.collect_result(settings=Settings(providers=("runpod",), catalog_scope="complete"), observed_at=TIME)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"][0]["code"], "collection_budget_exceeded")
        self.assertEqual(request.call_count, 2)

    @patch("gpu_price_monitor.providers.runpod.request_json")
    def test_standard_result_remains_catalog_only(self, request):
        request.return_value = catalog_payload()
        result = runpod.collect_result(settings=Settings(providers=("runpod",)), observed_at=TIME)
        self.assertEqual(len(result["prices"]), 2)
        self.assertTrue(all(not q["regions"] for q in result["prices"]))
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
