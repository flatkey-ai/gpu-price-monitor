"""Synthetic console API responses verify zone-specific hourly quote collection."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
import threading
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import ucloud_console as provider
from gpu_price_monitor.providers.ucloud_console_catalog import build_catalog_targets
from gpu_price_monitor.providers.ucloud_console_image import select_image_and_disk
from gpu_price_monitor.providers.ucloud_console_session import UCloudAPIError
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


OBSERVED = "2026-10-22T10:00:00+00:00"
PRIVATE_MARKER = "private-session-must-not-appear"


def catalog():
    regions = {"RetCode": 0, "Regions": [
        {"Region": "region-cn", "CountryCode": "CN", "LocalName": "China region"},
        {"Region": "region-us", "CountryCode": "US", "LocalName": "US region"}]}
    zones = {"RetCode": 0, "Zones": [
        {"Region": "region-cn", "Zone": "region-cn-01", "LocalName": "China zone 1"},
        {"Region": "region-cn", "Zone": "region-cn-02", "LocalName": "China zone 2"},
        {"Region": "region-us", "Zone": "region-us-01", "LocalName": "US zone 1"}]}
    rows = []
    for zone in zones["Zones"]:
        rows.append({"Name": "Future-GPU", "ParentType": "G", "InstanceType": "uhost",
            "Features": [{"Name": "NetCapability", "Modes": [{"Name": "Normal"}]}],
            "Zone": zone["Zone"], "Status": "Normal", "GraphicsMemory": {"Value": Decimal("48.0")},
            "CpuPlatforms": {"Amd": ["Amd/Epyc5"]},
            "MachineSizes": [{"Gpu": 2, "Collection": [{"Cpu": 8, "Memory": [32],
                                                        "MinimalCpuPlatform": ["Amd/Epyc5"]}]}],
            "Disks": [{"Name": "cloudDisk", "BootDisk": [{"Name": "CLOUD_SSD", "MaximalSize": 500,
                                                           "InstantResize": True}]}]})
    spot = deepcopy(rows[0])
    spot["InstanceType"] = "spot"
    rows.append(spot)
    return regions, zones, {"RetCode": 0, "AvailableInstanceTypes": rows}


def images(region):
    return {"RetCode": 0, "TotalCount": 1, "ImageSet": [{
        "ImageId": "base-" + region, "ImageName": "Ubuntu Base", "OsName": "Ubuntu Base",
        "ImageType": "Base", "OsType": "Linux", "State": "Available", "Zone": region + "-01",
        "Features": ["StandardKernel", "RssdAttachable"], "ImageSize": 20, "CreateTime": 100}]}


def price(amount="8.4", **changes):
    amount = Decimal(amount)
    row = {"Price": amount, "ChargeType": "Dynamic", "PriceDetail": {
        "UHost": amount - Decimal("0.4"), "UDisk": Decimal("0.4"),
        "Snapshot": 0, "Volume": 0, "UImage": 0, "UMkt": 0}}
    row.update(changes)
    return {"Action": "GetUHostInstancePriceResponse", "RetCode": 0, "PriceSet": [row],
            "irrelevant_private_field": PRIVATE_MARKER}


class FakeSession:
    def __init__(self):
        self.regions, self.zones, self.instances = catalog()
        self.calls = []
        self.fail_quote_zones = set()
        self.invalid_quote_zones = set()
        self.fail_availability = False
        self.availability = [{"Region": row["Region"], "Zone": row["Zone"],
                              "Status": "Soldout" if row["Zone"] == "region-cn-02" else "Available"}
                             for row in self.zones["Zones"]]

    def request(self, action, params=None, *, settings):
        params = params or {}
        self.calls.append((action, deepcopy(params)))
        if action == "ListRegions":
            return deepcopy(self.regions)
        if action == "ListZones":
            return deepcopy(self.zones)
        if action == "DescribeAvailableInstanceTypes":
            return deepcopy(self.instances)
        if action == "DescribeImage":
            return images(params["Region"])
        if action == "DescribeUHostMachineTypeAvailableZones":
            if self.fail_availability:
                raise FetchError("network_error", PRIVATE_MARKER, retryable=True)
            return {"RetCode": 0, "AvailableZones": deepcopy(self.availability)}
        if action == "GetUHostInstancePrice":
            if params["Zone"] in self.fail_quote_zones:
                raise FetchError("network_error", PRIVATE_MARKER, retryable=True)
            if params["Zone"] in self.invalid_quote_zones:
                return price(ChargeType="Month")
            return price({"region-cn-01": "8.4", "region-cn-02": "12.6", "region-us-01": "20.8"}[params["Zone"]])
        raise AssertionError("Unexpected action: " + action)


def collect(session, *, check_availability=True, project_id=None, **filters):
    options = {"ucloud_project_id": project_id}
    if check_availability is not None:
        options["ucloud_check_availability"] = check_availability
    with patch.object(provider.UCloudConsoleSession, "from_settings", return_value=session):
        return provider.collect_result(settings=Settings(providers=("ucloud",), max_retries=0, **options),
                                       observed_at=OBSERVED, **filters)


def parsed_inputs():
    target = build_catalog_targets(*catalog()).targets[0]
    return target, select_image_and_disk(target, images(target.request["Region"]))


class UCloudConsoleTests(unittest.TestCase):
    def test_small_a800_quotes_use_console_normal_mode_on_first_request(self):
        session = FakeSession()
        for row in session.instances["AvailableInstanceTypes"]:
            row["Name"] = "A800"
            row["Features"][0]["Modes"] = [{"Name": "Extreme"}]
        original = session.request

        def request(action, params=None, *, settings):
            if action == "GetUHostInstancePrice" and params["NetCapability"] != "Normal":
                raise UCloudAPIError(action, 8059)
            payload = original(action, params, settings=settings)
            if action == "DescribeImage":
                payload["ImageSet"][0]["Features"].append("NetEnhanced_Extreme")
            return payload

        session.request = request
        result = collect(session, check_availability=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual(len([call for call in session.calls if call[0] == "GetUHostInstancePrice"]), 3)
        for quote in result["prices"]:
            self.assertEqual(quote["requested_configuration"]["NetCapability"], "Normal")
            self.assertEqual(quote["network_selection"]["selection_basis"], "official_console_gpu_count_normal")
            self.assertTrue(quote["network_selection"]["selection_source_url"].startswith("https://console-s2.ucloud.cn/"))

    def test_null_network_modes_are_quoted_and_page_exclusions_do_not_fake_failures(self):
        session = FakeSession()
        for row in session.instances["AvailableInstanceTypes"]:
            row["Name"] = "P40"
            row["Features"][0]["Modes"] = None
        session.instances["AvailableInstanceTypes"].extend([
            {"Name": "T4", "ParentType": "G", "InstanceType": "uhost", "Zone": "region-cn-01", "Status": "Soldout"},
            {"Name": "T4", "ParentType": "G", "InstanceType": "uhost", "Zone": "outside-directory-01", "Status": "Normal"}])
        result = collect(session, check_availability=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertFalse(result["gaps"])
        self.assertFalse(result["errors"])
        self.assertEqual(len(result["coverage"]["console_scope_exclusions"]), 2)
        self.assertEqual(result["coverage"]["quote_gap_count"], 0)
        self.assertTrue(all(q["requested_configuration"]["NetCapability"] == "Normal" for q in result["prices"]))

    def test_filtered_empty_catalog_is_no_matches_not_failed_collection(self):
        from gpu_price_monitor import collect_prices

        session = FakeSession()
        result = collect(session, regions=["not-in-catalog"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["coverage"]["selected_targets"], 0)
        self.assertFalse(any(action in {"DescribeImage", "GetUHostInstancePrice"} for action, _ in session.calls))
        with patch.object(provider.UCloudConsoleSession, "from_settings", return_value=FakeSession()):
            collected = collect_prices(["ucloud"], {"regions": ["not-in-catalog"]},
                                       settings=Settings(ucloud_source="console", source_policy="api_only"))
        self.assertEqual(collected["status"], "success")
        self.assertEqual(collected["provider_results"][0]["status"], "no_matches")
        self.assertIsNone(collected["provider_results"][0]["error"])

    def test_concurrent_quote_timestamps_capture_worker_receipt_not_ordered_consumption(self):
        session = FakeSession()
        original = session.request
        local = threading.local()
        second_completed = threading.Event()
        stamps = {"region-cn-01": "2026-10-22T10:02:00+00:00",
                  "region-cn-02": "2026-10-22T10:01:00+00:00",
                  "region-us-01": "2026-10-22T10:03:00+00:00"}

        class ReceiptClock:
            @staticmethod
            def now(_timezone):
                return datetime.fromisoformat(getattr(local, "stamp", "2099-01-01T00:00:00+00:00"))

        def request(action, params=None, *, settings):
            payload = original(action, params, settings=settings)
            if action == "GetUHostInstancePrice":
                zone = params["Zone"]
                if zone == "region-cn-01":
                    if not second_completed.wait(timeout=2):
                        raise AssertionError("The second quote did not run concurrently.")
                local.stamp = stamps[zone]
                if zone == "region-cn-02":
                    second_completed.set()
            return payload

        session.request = request
        with patch.object(provider, "datetime", ReceiptClock):
            result = collect(session, check_availability=False)
        self.assertEqual({q["zones"][0]: q["observed_at"] for q in result["prices"]}, stamps)

    def test_retryable_failures_survive_each_optional_or_quote_stage(self):
        for stage in ("image", "market_image", "availability", "quote"):
            with self.subTest(stage=stage):
                session = FakeSession()
                original = session.request

                def request(action, params=None, *, settings):
                    if stage in {"image", "market_image"} and action == "DescribeImage" and params["Region"] == "region-us":
                        if stage == "market_image" and params.get("ImageType") != "Business":
                            return {"RetCode": 0, "ImageSet": [], "TotalCount": 0}
                        raise FetchError("network_error", PRIVATE_MARKER, retryable=True)
                    if stage == "availability" and action == "DescribeUHostMachineTypeAvailableZones":
                        raise FetchError("timeout", PRIVATE_MARKER, retryable=True)
                    if stage == "quote" and action == "GetUHostInstancePrice" and params["Zone"] == "region-cn-02":
                        raise FetchError("rate_limited", PRIVATE_MARKER, retryable=True)
                    return original(action, params, settings=settings)

                session.request = request
                result = collect(session)
                self.assertEqual(result["status"], "partial")
                self.assertTrue(result["errors"][0]["retryable"])
                self.assertTrue(all(gap["retryable"] for gap in result["gaps"]))
                self.assertNotIn(PRIVATE_MARKER, json.dumps(result))

    def test_default_prices_do_not_require_stock_requests_or_claim_orderability(self):
        session = FakeSession()
        result = collect(session, check_availability=None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertFalse(result["coverage"]["availability_check_requested"])
        self.assertEqual(result["coverage"]["account_project_scope"], "api_default_project")
        self.assertFalse(any(action == "DescribeUHostMachineTypeAvailableZones" for action, _ in session.calls))
        for quote in result["prices"]:
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["account_project_scope"], "api_default_project")
            self.assertTrue(any("Current stock was not verified" in note for note in quote["notes"]))
            self.assertFalse(any("Availability was checked" in note for note in quote["notes"]))

    def test_provider_return_codes_survive_all_failed_stages_without_response_messages(self):
        for stage, expected_action in (("image", "DescribeImage"), ("market_image", "DescribeImage"),
                                       ("availability", "DescribeUHostMachineTypeAvailableZones"),
                                       ("quote", "GetUHostInstancePrice")):
            with self.subTest(stage=stage):
                session = FakeSession()
                original = session.request

                def request(action, params=None, *, settings):
                    reject = False
                    if stage in {"image", "market_image"} and action == "DescribeImage" and params["Region"] == "region-us":
                        if stage == "market_image" and params.get("ImageType") != "Business":
                            return {"RetCode": 0, "ImageSet": [], "TotalCount": 0}
                        reject = True
                    if stage == "availability" and action == "DescribeUHostMachineTypeAvailableZones":
                        reject = True
                    if stage == "quote" and action == "GetUHostInstancePrice" and params["Zone"] == "region-cn-02":
                        reject = True
                    if reject:
                        error = UCloudAPIError(action, 9999)
                        # Even a changed exception message is never propagated
                        # into the result; only the explicit diagnostics survive.
                        error.args = (PRIVATE_MARKER,)
                        raise error
                    return original(action, params, settings=settings)

                session.request = request
                result = collect(session)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(len(result["prices"]), 3 if stage == "availability" else 2)
                self.assertGreater(len(result["gaps"]), 0)
                for gap in result["gaps"]:
                    self.assertEqual(gap["provider_retcode"], 9999)
                    self.assertEqual(gap["provider_action"], expected_action)
                    self.assertFalse(gap["retryable"])
                    self.assertNotIn("message", gap)
                self.assertNotIn(PRIVATE_MARKER, json.dumps(result))

    def test_real_zone_conditions_generate_independent_hourly_prices(self):
        session = FakeSession()
        result = collect(session)
        self.assertEqual(result["status"], "ok")
        quotes = {quote["zones"][0]: quote for quote in result["prices"]}
        self.assertEqual({zone: quote["amount"] for zone, quote in quotes.items()},
                         {"region-cn-01": "4.2", "region-cn-02": "6.3", "region-us-01": "10.4"})
        self.assertEqual(quotes["region-cn-01"]["compute_countries"], ["CN"])
        self.assertEqual(quotes["region-us-01"]["compute_countries"], ["US"])
        self.assertEqual(quotes["region-cn-02"]["availability"], "sold_out")
        for quote in quotes.values():
            self.assertEqual(quote["unit"], "gpu_hour")
            self.assertEqual(quote["currency"], "CNY")
            self.assertEqual(quote["billing_mode"], "on_demand")
            self.assertEqual(quote["price_basis"], "instance_total_allocated")
            self.assertEqual(quote["pricing_tier"], "account")
            self.assertEqual(quote["instance_price"]["unit"], "instance_hour")
            self.assertEqual(quote["resources"]["memory_mb"], 32768)
            self.assertEqual(quote["resources"]["net_capability"], "Normal")
            self.assertEqual(quote["network_selection"]["mode"], "Normal")
            self.assertEqual(quote["network_selection"]["catalog_options"], [{"Name": "Normal"}])
            self.assertEqual(quote["network_selection"]["selection_basis"], "catalog_normal_or_only_mode")
            self.assertTrue(quote["region_price_verified"])
            self.assertEqual(quote["location"]["zone"], quote["zones"][0])
        requests = [params for action, params in session.calls if action == "GetUHostInstancePrice"]
        self.assertEqual(len(requests), 3)
        for params in requests:
            self.assertEqual(params["GPU"], 2)
            self.assertEqual(params["Count"], 1)
            self.assertEqual(params["ChargeType"], "Dynamic")
            self.assertEqual(params["Disks.0.Size"], 20)
            self.assertEqual(params["Disks.0.IsBoot"], "True")
            self.assertEqual(params["ShowPriceDetails"], "true")
            self.assertEqual(params["NetCapability"], "Normal")
            self.assertNotIn("Disks", params)
            self.assertNotIn("MinimalCpuPlatform", params)
        availability_calls = [params for action, params in session.calls if action == "DescribeUHostMachineTypeAvailableZones"]
        self.assertEqual(len(availability_calls), 1)
        self.assertEqual(availability_calls[0]["MinimalCpuPlatform"], "Amd/Auto")
        self.assertEqual(result["coverage"]["spot_gpu_catalog_rows"], 1)
        self.assertEqual(result["coverage"]["selected_targets"], 3)
        self.assertNotIn(PRIVATE_MARKER, json.dumps(result))
        self.assertTrue(all(action in {"ListRegions", "ListZones", "DescribeAvailableInstanceTypes", "DescribeImage",
                                     "DescribeUHostMachineTypeAvailableZones", "GetUHostInstancePrice"}
                            for action, _ in session.calls))

    def test_region_and_zone_filters_are_applied_before_price_requests(self):
        for filters, expected in [({"regions": ["region-us"]}, "region-us-01"),
                                  ({"zones": ["region-cn-02"]}, "region-cn-02")]:
            with self.subTest(filters=filters):
                session = FakeSession()
                result = collect(session, **filters)
                self.assertEqual(len(result["prices"]), 1)
                self.assertEqual(result["prices"][0]["zones"], [expected])
                self.assertEqual([params["Zone"] for action, params in session.calls
                                  if action == "GetUHostInstancePrice"], [expected])

    def test_missing_official_country_keeps_exact_quote_without_inference(self):
        session = FakeSession()
        session.regions["Regions"][1].pop("CountryCode")
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 3)
        self.assertIn("country_not_verified", {gap.get("code") for gap in result["gaps"]})
        unknown = next(q for q in result["prices"] if q["regions"] == ["region-us"])
        self.assertEqual(unknown["compute_countries"], [])
        self.assertIsNone(unknown["location"]["country_code"])
        self.assertEqual(unknown["zones"], ["region-us-01"])
        self.assertEqual(unknown["amount"], "10.4")
        self.assertTrue(any(params.get("Region") == "region-us" and params.get("Zone") == "region-us-01"
                            for action, params in session.calls if action == "GetUHostInstancePrice"))
        self.assertTrue(any("country is not verified" in note for note in unknown["notes"]))

    def test_partial_quote_errors_keep_other_zones_and_never_expose_exception(self):
        session = FakeSession()
        session.fail_quote_zones.add("region-cn-02")
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["coverage"]["quote_gap_count"], 1)
        self.assertIn("network_error", {gap.get("status") for gap in result["gaps"]})
        self.assertEqual(result["gaps"][0]["NetCapability"], "Normal")
        self.assertNotIn(PRIVATE_MARKER, json.dumps(result))

    def test_image_read_parse_exception_is_sanitized_and_other_region_survives(self):
        session = FakeSession()
        request = session.request

        def broken_image(action, params=None, *, settings):
            if action == "DescribeImage" and params["Region"] == "region-us":
                raise ValueError(PRIVATE_MARKER)
            return request(action, params, settings=settings)

        session.request = broken_image
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual({q["compute_countries"][0] for q in result["prices"]}, {"CN"})
        self.assertNotIn(PRIVATE_MARKER, json.dumps(result))
        self.assertIn("parse_failed", {gap.get("status") for gap in result["gaps"]})

    def test_bad_price_period_becomes_gap_without_losing_other_zones(self):
        session = FakeSession()
        session.invalid_quote_zones.add("region-cn-02")
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertIn("invalid_hourly_price", {gap.get("status") for gap in result["gaps"]})
        self.assertFalse(result["errors"][0]["retryable"])

    def test_availability_must_match_exact_region_and_zone(self):
        session = FakeSession()
        session.availability[0]["Region"] = "somewhere-else"
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 3)
        quote = next(q for q in result["prices"] if q["zones"] == ["region-cn-01"])
        self.assertEqual(quote["availability"], "unknown")
        self.assertEqual(quote["amount"], "4.2")
        self.assertEqual(result["coverage"]["quote_gap_count"], 0)
        self.assertIn("availability_not_verified", {gap.get("status") for gap in result["gaps"]})
        target, _ = parsed_inputs()
        duplicate = {"Region": target.request["Region"], "Zone": target.request["Zone"], "Status": "Available"}
        with self.assertRaises(ValueError):
            provider.availability_status({"AvailableZones": [duplicate, deepcopy(duplicate)]}, target)

    def test_optional_stock_failure_retains_all_prices_without_disclosing_exception(self):
        session = FakeSession()
        session.fail_availability = True
        result = collect(session)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual({q["availability"] for q in result["prices"]}, {"unknown"})
        self.assertEqual(result["coverage"]["quote_gap_count"], 0)
        self.assertEqual({gap["status"] for gap in result["gaps"]}, {"availability_not_verified"})
        self.assertNotIn(PRIVATE_MARKER, json.dumps(result))

    def test_configured_project_is_forwarded_consistently_and_never_exported(self):
        session = FakeSession()
        project_id = "project-private-do-not-export"
        result = collect(session, project_id=project_id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["coverage"]["account_project_scope"], "configured_project")
        for action, params in session.calls:
            if action in {"ListRegions", "ListZones"}:
                self.assertNotIn("ProjectId", params)
            else:
                self.assertEqual(params["ProjectId"], project_id)
        for quote in result["prices"]:
            self.assertEqual(quote["account_project_scope"], "configured_project")
            self.assertNotIn("ProjectId", quote["requested_configuration"])
        self.assertNotIn(project_id, json.dumps(result))

    def test_quote_rejects_zero_compute_and_ambiguous_period(self):
        target, selected = parsed_inputs()
        cases = [price("0", PriceDetail={"UHost": 0}), price("0.4", PriceDetail={"UHost": 0, "UDisk": "0.4"}),
                 price(ChargeType="Month"), price(ChargeType="Year"), price(ChargeType="Postpay"),
                 price(Price="NaN"), price(Price="-1"), price(Price=True)]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ValueError):
                provider.parse_console_quote(response, target, selected, availability="available", observed_at=OBSERVED)

    def test_quote_components_must_sum_to_configured_total(self):
        target, selected = parsed_inputs()
        for details in [{"UHost": 8}, {"UHost": "8.4", "UDisk": "0.4"}, {"UHost": 8, "Mystery": "0.4"}]:
            with self.subTest(details=details), self.assertRaises(ValueError):
                provider.parse_console_quote(price(PriceDetail=details), target, selected,
                                             availability="available", observed_at=OBSERVED)

    def test_free_linux_minimal_boot_baseline_rejects_paid_image_or_extra_services(self):
        target, selected = parsed_inputs()
        for component in ("UImage", "UMkt", "Snapshot", "Volume"):
            response = price(PriceDetail={"UHost": 8, component: "0.4"})
            with self.subTest(component=component), self.assertRaises(ValueError):
                provider.parse_console_quote(response, target, selected, availability="available", observed_at=OBSERVED)


if __name__ == "__main__":
    unittest.main()
