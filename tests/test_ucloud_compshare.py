from copy import deepcopy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import ucloud_compshare as compshare
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


OBSERVED = "2026-10-21T10:00:00+00:00"
ASSET = "https://www.compshare.cn/_next/static/chunks/app/price-list/page-example.js"
HTML = """<html><script src="/_next/static/chunks/app/price-list/page-example.js"></script>
<div class="pl-table-card" id="a100"><span class="pl-table-name">A100</span><span class="pl-table-spec">80G</span></div>
<div class="pl-table-card" id="rtx2080ti"><span class="pl-table-name">RTX2080Ti</span><span class="pl-table-spec">11G</span></div>
</html>"""


def config(**updates):
    result = {"Gpu": 1, "Cpu": 16, "Memory": 65536, "DiskSize": 100,
              "DiskType": "CLOUD_SSD", "ChargeType": "Postpay",
              "TotalOriginal": 99999, "TotalPrice": 99998}
    result.update(updates)
    return result


def script(groups=None):
    groups = groups if groups is not None else [
        {"MachineType": "A100", "ZoneId": 10027, "Configs": [config(), config(), config(ChargeType="Month")]},
        {"MachineType": "2080Ti", "ZoneId": 8200, "Configs": [config(Gpu=4, Cpu=16, Memory=98304)]},
        {"MachineType": "5090", "ZoneId": 10049, "Configs": [config()]},
    ]
    return "let P=JSON.parse('" + json.dumps({"MachineTypePrices": groups}) + "');"


def payload(**updates):
    result = {"Action": "GetCompShareInstancePriceResponse", "RetCode": 0,
              "PriceDetails": [{"ChargeType": "Postpay", "Instance": Decimal("1.77"), "SystemDisks": Decimal("0.01")}],
              "OriginalPriceDetails": [{"ChargeType": "Postpay", "Instance": Decimal("1.86"), "SystemDisks": Decimal("0.02")}],
              "ListPriceDetails": [{"ChargeType": "Postpay", "Instance": Decimal("1.86"), "SystemDisks": Decimal("0.02")}],
              "request_uuid": "discard-request-id"}
    result.update(updates)
    return result


LOCATIONS = {
    "cn-wlcb-01": {"region": "cn-wlcb", "country_code": "CN", "region_name": "乌兰察布", "zone_name": "可用区A"},
    "cn-sh2-02": {"region": "cn-sh2", "country_code": "CN", "region_name": "上海2", "zone_name": "可用区B"},
}


class CompShareDiscoveryTests(unittest.TestCase):
    def test_exact_configuration_dedup_and_unknown_zone_exclusion(self):
        targets, excluded = compshare.discover_targets(HTML, script())
        self.assertEqual(len(targets), 2)
        self.assertEqual(excluded, [{"gpu_type": "5090", "zone_id": 10049, "reason": "unverified_zone_id"}])
        self.assertEqual(targets[0]["request"]["Region"], "cn-wlcb")
        self.assertEqual(targets[1]["request"]["Zone"], "cn-sh2-02")
        self.assertEqual(targets[1]["vram_gb"], 11)
        self.assertNotIn("TotalOriginal", json.dumps(targets))
        self.assertEqual(targets[0]["request"]["Disks"], [{"IsBoot": True, "Type": "CLOUD_SSD", "Size": 100}])

    def test_bundle_path_is_same_origin_and_discovered_each_run(self):
        self.assertEqual(compshare.discover_asset(HTML), ASSET)
        for replacement in ("https://evil.invalid/_next/static/chunks/app/price-list/page-example.js",
                            "//evil.invalid/_next/static/chunks/app/price-list/page-example.js",
                            "/_next/static/chunks/app/price-list/../../account.js"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                compshare.discover_asset(HTML.replace("/_next/static/chunks/app/price-list/page-example.js", replacement))

    def test_conflicting_json_keys_and_unknown_units_fail(self):
        with self.assertRaises(ValueError):
            compshare.discover_targets(HTML, 'JSON.parse(\'{"MachineTypePrices":[],"MachineTypePrices":[]}\')')
        groups = [{"MachineType": "A100", "ZoneId": 10027, "Configs": [config(ChargeType="Dynamic")]}]
        with self.assertRaises(ValueError):
            compshare.discover_targets(HTML, script(groups))
        with self.assertRaises(ValueError):
            compshare.discover_targets(HTML.replace("80G", "80M"), script())


class CompShareQuoteTests(unittest.TestCase):
    def setUp(self):
        self.target = compshare.discover_targets(HTML, script())[0][1]
        self.location = {"zone": "cn-sh2-02", **LOCATIONS["cn-sh2-02"]}

    def parse(self, data):
        return compshare.parse_quote(data, target=self.target, location=self.location,
                                    observed_at=OBSERVED, catalog_url=ASSET)

    def test_original_instance_tariff_is_allocated_without_member_claim(self):
        quote = self.parse(payload())
        self.assertEqual(quote["amount"], "0.47")
        self.assertEqual(quote["unit"], "gpu_hour")
        self.assertEqual(quote["instance_price"]["amount"], "1.88")
        self.assertEqual(quote["current_discounted_quote"]["amount"], "1.78")
        self.assertFalse(quote["current_discounted_quote"]["eligibility_verified"])
        self.assertEqual(quote["pricing_tier"], "ordinary")
        self.assertFalse(quote["membership_required"])
        self.assertEqual(quote["price_field"], "OriginalPriceDetails")
        self.assertEqual(quote["product_line"], "UCloud · CompShare（优云智算）")
        self.assertEqual(quote["pricing_product_scope"], "ucloud_compshare")
        self.assertEqual(quote["compute_countries"], ["CN"])
        self.assertEqual(quote["geographic_scope"], "requested_zone")
        self.assertEqual(quote["availability"], "unknown")
        self.assertNotIn("discard-request-id", json.dumps(quote))

    def test_missing_original_no_discount_fallback(self):
        data = payload()
        del data["OriginalPriceDetails"]
        with self.assertRaises(ValueError):
            self.parse(data)

    def test_wrong_billing_mode_and_unknown_price_component_fail(self):
        for updates in ({"ChargeType": "Month"}, {"Instance": Decimal("NaN")},
                        {"Instance": -1}, {"Instance": True}, {"GPUFee": 1}):
            data = payload()
            data["OriginalPriceDetails"][0].update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.parse(data)

    def test_request_and_location_must_be_same_pair(self):
        self.location["region"] = "cn-wlcb"
        with self.assertRaises(ValueError):
            self.parse(payload())


class CompShareCollectionTests(unittest.TestCase):
    def run_collection(self, response, **filters):
        settings = Settings(providers=("ucloud",), ucloud_public_key="unused-key", ucloud_private_key="unused-secret")
        with patch.object(compshare, "fetch_text", side_effect=[HTML, script()]) as fetch, \
             patch.object(compshare.ucloud_public, "load_location_catalog", return_value=deepcopy(LOCATIONS)), \
             patch.object(compshare, "request_json", side_effect=response) as request, \
             patch.object(compshare.time, "sleep"):
            result = compshare.collect_result(settings=settings, observed_at=OBSERVED, **filters)
        self.assertEqual(fetch.call_args_list[1].args[0], ASSET)
        for call in request.call_args_list:
            self.assertFalse(call.kwargs["authenticated"])
            self.assertEqual(call.kwargs["headers"], {"Content-Type": "application/json"})
            self.assertNotIn(b"unused", call.kwargs["data"])
        return result, request

    def test_api_prices_are_fresh_and_region_filter_limits_requests(self):
        result, request = self.run_collection(lambda *a, **k: payload(), regions={"cn-sh2"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(request.call_count, 1)
        sent = json.loads(request.call_args.kwargs["data"])
        self.assertEqual(sent["Zone"], "cn-sh2-02")
        self.assertEqual(result["discovery"]["discovered_target_count"], 2)
        self.assertEqual(result["discovery"]["requested_target_count"], 1)

    def test_partial_success_keeps_target_errors_and_no_fallback(self):
        def response(*args, **kwargs):
            if json.loads(kwargs["data"])["Zone"] == "cn-sh2-02":
                return {"RetCode": 170, "Message": "do-not-echo-response"}
            return payload()
        result, request = self.run_collection(response)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "authentication_required")
        self.assertEqual(result["errors"][0]["target"]["Zone"], "cn-sh2-02")
        self.assertNotIn("do-not-echo-response", json.dumps(result))
        self.assertEqual(request.call_count, 2)

    def test_simple_adapter_refuses_hidden_partial(self):
        with patch.object(compshare, "collect_result", return_value={"prices": [{}], "errors": [{}]}):
            with self.assertRaises(FetchError) as caught:
                compshare.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "partial_collection")


if __name__ == "__main__":
    unittest.main()
