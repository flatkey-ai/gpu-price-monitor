"""Offline v1 calculator contract tests. All fixture costs are synthetic, not
live prices, and no credentials from the environment are read by these tests.
"""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import nebius_quote as nebius
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-21T06:00:00+00:00"
TOKEN = "dummy-test-access-token"
PROJECT = "project-private-test"


def target(**updates):
    item = {
        "project_id": PROJECT, "region": "eu-north1", "country_code": "FI",
        "gpu_model": "H100", "gpu_variant": "SXM", "gpu_count": 8, "vram_gb": 80,
        "currency": "usd", "aggregation_units": ["hour", "month"], "offer_types": [],
        "resource_specs": [{"spec": {
            "@type": nebius._TYPE_PREFIX + "CreateInstanceRequest",
            "metadata": {"parentId": PROJECT, "name": "private-resource-name"},
            "spec": {"resources": {"platform": "gpu-h100-sxm", "preset": "8gpu-128vcpu-1600gb"},
                     "onDemand": {}, "bootDisk": {"attachMode": "READ_WRITE", "managedDisk": {
                         "name": "private-boot-name", "spec": {"type": "NETWORK_SSD", "sizeGibibytes": "100"},
                     }}}}}],
    }
    item.update(updates)
    return item


def settings_for(items=None, **updates):
    values = {"providers": ("nebius",), "nebius_source": "api", "max_retries": 0,
              "nebius_access_token": TOKEN,
              "nebius_price_targets_json": json.dumps([target()] if items is None else items)}
    values.update(updates)
    return Settings(**values)


def response():
    return json.loads((FIXTURES / "nebius-quote-synthetic.json").read_text(), parse_float=Decimal)


def project(region="eu-north1"):
    return {"metadata": {"id": PROJECT, "name": "private-project-name"}, "spec": {"region": region}}


class NebiusQuoteTests(unittest.TestCase):
    def test_official_v1_request_shape_and_all_specs_are_pricing_only(self):
        item = nebius.load_targets(settings_for())[0]
        body = json.loads(nebius.build_request(item))
        self.assertEqual(set(body), {"resourceSpecs", "currency", "offerTypes", "filterAggregationUnit"})
        self.assertEqual(body["currency"], "usd")
        self.assertEqual(body["filterAggregationUnit"]["filterAggregationUnitValues"],
                         ["FILTER_AGGREGATION_UNIT_HOUR", "FILTER_AGGREGATION_UNIT_MONTH"])
        self.assertEqual(body["resourceSpecs"][0]["spec"]["@type"], "type.googleapis.com/nebius.compute.v1.CreateInstanceRequest")
        self.assertNotIn(TOKEN, json.dumps(body))

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_collect_only_reads_project_and_calculator_preserving_totals_units_and_country(self, request):
        request.side_effect = [project(), response()]
        quotes = nebius.collect_quotes(settings=settings_for(), observed_at=OBSERVED)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0], nebius.PROJECT_URL + PROJECT)
        self.assertEqual(request.call_args_list[0].kwargs.get("method", "GET"), "GET")
        self.assertEqual(request.call_args_list[1].args[0], nebius.SOURCE_URL)
        self.assertEqual(request.call_args_list[1].kwargs["method"], "POST")
        for call in request.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer " + TOKEN)
            self.assertTrue(call.kwargs["authenticated"])
        self.assertEqual([quote["unit"] for quote in quotes], ["gpu_hour", "gpu_month"])
        self.assertEqual([quote["amount"] for quote in quotes], ["3.02793209864", "2259.62375"])
        self.assertEqual([quote["instance_price"]["amount"] for quote in quotes], ["24.223456789123", "18076.99"])
        self.assertEqual(quotes[1]["instance_price"]["unit"], "instance_month")
        self.assertEqual(quotes[0]["components"][0]["per_instance"]["amount"], "24.123456789123")
        self.assertEqual(quotes[0]["compute_countries"], ["FI"])
        self.assertEqual(quotes[0]["location"]["region"], "eu-north1")
        self.assertEqual(quotes[0]["regions"], ["eu-north1"])
        self.assertEqual(quotes[0]["zones"], [])
        self.assertEqual(quotes[0]["geographic_scope"], "requested_region")
        self.assertTrue(quotes[0]["location_validation"]["project_region_verified"])
        self.assertEqual(quotes[0]["source_type"], "official_quote_api")
        self.assertEqual(quotes[0]["account_scope"], "account_quote")
        self.assertEqual(quotes[0]["target_index"], 0)
        self.assertEqual(quotes[0]["price_basis"], "instance_total_allocated")
        self.assertEqual(quotes[0]["observed_at"], OBSERVED)
        self.assertEqual(quotes[0]["resources"]["vcpus"], 128)
        self.assertEqual(quotes[0]["resources"]["memory_gib"], 1600)
        serialized = json.dumps(quotes)
        for private in (TOKEN, PROJECT, "private-resource-name", "private-project-name", "private-boot-name", "Authorization"):
            self.assertNotIn(private, serialized)

    def test_precise_division_ignores_callers_decimal_context_and_does_not_invent_month_hours(self):
        item = nebius.load_targets(settings_for())[0]
        with localcontext() as context:
            context.prec = 2
            quotes = nebius.parse_quote(response(), item, observed_at=OBSERVED)
        self.assertEqual(quotes[0]["amount"], "3.02793209864")
        self.assertEqual(quotes[1]["amount"], "2259.62375")
        self.assertNotEqual(Decimal(quotes[1]["amount"]), Decimal(quotes[0]["amount"]) * 720)
        self.assertFalse(quotes[0]["location_validation"]["project_region_verified"])

    def test_host_decimal_traps_and_exponent_range_cannot_change_estimate_arithmetic(self):
        item = nebius.load_targets(settings_for())[0]
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.Emin = -2
            context.traps[Inexact] = True
            quotes = nebius.parse_quote(response(), item, observed_at=OBSERVED)
        self.assertEqual(quotes[0]["amount"], "3.02793209864")
        self.assertEqual(quotes[1]["amount"], "2259.62375")

    def test_a_positive_cost_must_never_round_to_a_free_gpu(self):
        item = nebius.load_targets(settings_for([target(aggregation_units=["hour"])]))[0]
        tiny = "0.000000000000000001"
        payload = {"currency": "usd", "resourceCosts": [{"metadata": {"name": "private-resource-name"},
            "aggregationUnit": {"unit": "hour", "unitType": "UNIT_TYPE_TIME_BASED"},
            "general": {"total": {"cost": tiny, "skuCosts": []}}}], "totalCosts": [{
                "aggregationUnit": {"unit": "hour", "unitType": "UNIT_TYPE_TIME_BASED"},
                "general": {"total": {"cost": tiny, "skuCosts": []}}}]}
        with self.assertRaisesRegex(ValueError, "below the supported decimal precision"):
            nebius.parse_quote(payload, item, observed_at=OBSERVED)

    def test_contract_currency_and_compute_country_stay_independent(self):
        item = nebius.load_targets(settings_for([target(currency="ils", offer_types=["OFFER_TYPE_CONTRACT_PRICE"])]))[0]
        payload = response()
        payload["currency"] = "ils"
        quote = nebius.parse_quote(payload, item, observed_at=OBSERVED)[0]
        self.assertEqual(quote["currency"], "ILS")
        self.assertEqual(quote["compute_countries"], ["FI"])
        self.assertEqual(quote["account_scope"], "account_contract_quote")
        self.assertIn("contract", " ".join(quote["notes"]).lower())

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_project_region_mismatch_or_unknown_response_stops_before_estimate_without_echo(self, request):
        for payload in (project("us-central1"), {"metadata": {"id": TOKEN}, "spec": {"region": "eu-north1"}}, {"message": TOKEN}):
            request.reset_mock()
            request.return_value = payload
            with self.assertRaises(FetchError) as captured:
                nebius.collect_quotes(settings=settings_for(), observed_at=OBSERVED)
            self.assertIn(captured.exception.code, {"project_region_mismatch", "project_region_unverified"})
            self.assertNotIn(TOKEN, str(captured.exception))
            self.assertEqual(request.call_count, 1)

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_missing_credentials_bad_headers_and_missing_targets_make_no_requests(self, request):
        for changes, code in (({"nebius_access_token": None}, "missing_credentials"),
                              ({"nebius_access_token": "token\r\nAuthorization: injected"}, "invalid_credentials"),
                              ({"nebius_access_token": "   "}, "invalid_credentials"),
                              ({"nebius_price_targets_json": None}, "missing_price_targets")):
            with self.subTest(code=code), self.assertRaises(FetchError) as captured:
                nebius.collect_quotes(settings=settings_for(**changes), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, code)
        request.assert_not_called()

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_invalid_or_mutating_target_shapes_are_all_rejected_before_network(self, request):
        invalid = [[], {}, [target()] * 21, [target(), target()]]
        for changes in ({"region": "eu-north1", "country_code": "US"}, {"region": "invented-region"},
                        {"project_id": "../../token"}, {"gpu_count": 0}, {"gpu_count": True}, {"gpu_count": 7},
                        {"currency": []}, {"currency": "EUR"}, {"aggregation_units": ["day"]},
                        {"aggregation_units": ["hour", "hour"]}, {"offer_types": ["OFFER_TYPE_UNSPECIFIED"]},
                        {"zones": ["eu-north1-zone-guessed"]}, {"endpoint": "https://evil.example/create"}):
            invalid.append([target(**changes)])
        for path, value in ((["@type"], nebius._TYPE_PREFIX + "DeleteInstanceRequest"),
                            (["metadata", "parentId"], "project-other"),
                            (["spec", "cloudInitUserData"], TOKEN),
                            (["spec", "bootDisk"], {"attachMode": "READ_WRITE", "existingDisk": {"id": TOKEN}}),
                            (["spec", "bootDisk", "managedDisk", "spec", "type"], []),
                            (["spec", "resources", "preset"], "8gpu-unknown")):
            supplied = target()
            node = supplied["resource_specs"][0]["spec"]
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            invalid.append([supplied])
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(FetchError) as captured:
                nebius.collect_quotes(settings=settings_for(values), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, "invalid_price_targets")
        for raw in ('[{"project_id":"one","project_id":"two"}]', '[NaN]', 'token', 'x' * 262145):
            with self.assertRaises(FetchError):
                nebius.load_targets(settings_for(nebius_price_targets_json=raw))
        request.assert_not_called()

    def test_rejects_ambiguous_units_ranges_counts_and_inconsistent_totals(self):
        invalid = []
        for value in (None, "private-token", True, -1, "NaN", "1e10"):
            payload = response()
            payload["totalCosts"][0]["general"]["total"]["cost"] = value
            invalid.append(payload)
        payload = response()
        payload["currency"] = "ils"
        invalid.append(payload)
        payload = response()
        payload["resourceCosts"][0]["aggregationUnit"]["unit"] = "request"
        invalid.append(payload)
        payload = response()
        payload["resourceCosts"][0]["aggregationUnit"]["unitType"] = "UNIT_TYPE_USAGE_BASED"
        invalid.append(payload)
        payload = response()
        payload["resourceCosts"][0]["fixedInstance"]["instanceCount"] = 8
        invalid.append(payload)
        payload = response()
        payload["resourceCosts"][0]["autoscale"] = payload["resourceCosts"][0].pop("fixedInstance")
        invalid.append(payload)
        payload = response()
        payload["totalCosts"][0]["range"] = {}
        invalid.append(payload)
        payload = response()
        payload["totalCosts"] = [payload["totalCosts"][0]] * 2
        invalid.append(payload)
        payload = response()
        payload["resourceCosts"].pop(1)
        invalid.append(payload)
        payload = response()
        payload["totalCosts"][0]["general"]["total"]["skuCosts"][0]["cost"] = "1"
        invalid.append(payload)
        item = nebius.load_targets(settings_for())[0]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                nebius.parse_quote(payload, item, observed_at=OBSERVED)
        with self.assertRaises(FetchError) as captured:
            nebius.parse_quote({"code": 7, "message": TOKEN}, item, observed_at=OBSERVED)
        self.assertNotIn(TOKEN, str(captured.exception))

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_project_verification_is_reused_but_failed_target_returns_no_partial_success(self, request):
        alternative = target(currency="ils")
        request.side_effect = [project(), response(), {"code": 7, "message": TOKEN}]
        with self.assertRaises(FetchError):
            nebius.collect_quotes(settings=settings_for([target(), alternative]), observed_at=OBSERVED)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sum(call.args[0].startswith(nebius.PROJECT_URL) for call in request.call_args_list), 1)

    def test_only_documented_create_specs_are_calculator_payloads_and_example_is_a_template(self):
        item = target()
        item["resource_specs"].append({"spec": {"@type": nebius._TYPE_PREFIX + "CreateFilesystemRequest",
            "metadata": {"parentId": PROJECT, "name": "extra-storage"},
            "spec": {"type": "NETWORK_SSD", "sizeGibibytes": "500"}}})
        self.assertEqual(len(nebius.load_targets(settings_for([item]))[0]["resource_specs"]), 2)
        original = deepcopy(item)
        payload = response()
        for unit in ("hour", "month"):
            payload["resourceCosts"].append({"metadata": {"name": "extra-storage"},
                "aggregationUnit": {"unit": unit, "unitType": "UNIT_TYPE_TIME_BASED"},
                "general": {"total": {"cost": "0", "skuCosts": []}}})
        nebius.parse_quote(payload, nebius.load_targets(settings_for([item]))[0], observed_at=OBSERVED)
        self.assertEqual(item, original)
        example = Path(__file__).parents[1] / "configs" / "nebius-targets.example.json"
        validated = nebius.validate_targets(example.read_text())
        self.assertIn("replace", validated[0]["project_id"])

    @patch("gpu_price_monitor.providers.nebius_quote.request_json")
    def test_model_board_memory_preset_and_platform_region_must_match_the_documented_identity(self, request):
        invalid = [target(gpu_model="A100"), target(gpu_variant="PCIe"), target(vram_gb=141),
                   target(region="us-central1", country_code="US")]
        for platform, preset in (("gpu-a100-sxm", "8gpu-128vcpu-1600gb"),
                                 ("gpu-future-unknown", "8gpu-128vcpu-1600gb"),
                                 ("gpu-h100-sxm", "8gpu-128vcpu-1200gb")):
            supplied = target()
            supplied["resource_specs"][0]["spec"]["spec"]["resources"] = {"platform": platform, "preset": preset}
            invalid.append(supplied)
        for supplied in invalid:
            with self.subTest(supplied=supplied), self.assertRaises(FetchError) as captured:
                nebius.collect_quotes(settings=settings_for([supplied]), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, "invalid_price_targets")
            with self.assertRaises(FetchError):
                nebius.parse_quote(response(), supplied, observed_at=OBSERVED)
        request.assert_not_called()
        verified = nebius.load_targets(settings_for([target(gpu_variant=None, vram_gb=None)]))[0]
        self.assertEqual((verified["gpu_variant"], verified["vram_gb"]), ("SXM", 80))
        self.assertEqual(len(nebius.SUPPORTED_PLATFORMS), 9)

    def test_storage_only_month_total_cannot_be_reported_as_gpu_month_and_unmatched_resources_fail(self):
        item = nebius.load_targets(settings_for())[0]
        payload = response()
        payload["resourceCosts"].pop(2)
        payload["totalCosts"][1]["general"]["total"] = {"cost": "77", "skuCosts": [{"skuId": "sku-managed-boot-disk", "quantity": "100", "cost": "77"}]}
        with self.assertRaisesRegex(ValueError, "complete requested configuration"):
            nebius.parse_quote(payload, item, observed_at=OBSERVED)
        for metadata in ({}, {"name": "unrequested-private-resource"}):
            payload = response()
            payload["resourceCosts"][0]["metadata"] = metadata
            with self.assertRaisesRegex(ValueError, "matched to the requested"):
                nebius.parse_quote(payload, item, observed_at=OBSERVED)


if __name__ == "__main__":
    unittest.main()
