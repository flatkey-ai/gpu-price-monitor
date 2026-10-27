"""Signed API discovery with synthetic official response schemas; no live keys."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from gpu_price_monitor.providers import ucloud_api_catalog as provider
from gpu_price_monitor.providers import ucloud, ucloud_public
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-27T04:00:00+00:00"
PUBLIC_KEY, PRIVATE_KEY = "synthetic-public-key", "synthetic-private-key"
PRIVATE_MESSAGE = "synthetic-private-provider-message-must-not-leak"
FIXTURE = Path(__file__).parent / "fixtures" / "ucloud-signed-api-catalog.synthetic.json"


class FakeAPI:
    def __init__(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.calls = []
        self.image_count = 1
        self.fail_regions = set()
        self.fail_price_zones = set()
        self.incomplete_images = False
        self.duplicate_images = False
        self.quote_totals = {"region-cn-01": "8.4", "region-cn-02": "12.6", "region-us-01": "20.8"}

    def request(self, url, settings, *, method, authenticated, headers, data):
        self.assert_request(url, method, authenticated, headers)
        params = {key: values[0] for key, values in parse_qs(data.decode()).items()}
        signature = params.pop("Signature")
        if signature != ucloud.sign_parameters(params, PRIVATE_KEY):
            raise AssertionError("Every read must carry the official signature.")
        if params.pop("PublicKey") != PUBLIC_KEY:
            raise AssertionError("Wrong synthetic public key.")
        action = params.pop("Action")
        self.calls.append((action, deepcopy(params)))
        if action == "GetRegion":
            return deepcopy(self.fixture["account_regions"])
        if action == "DescribeAvailableInstanceTypes":
            if params["Region"] in self.fail_regions:
                return {"Action": action + "Response", "RetCode": 299, "Message": PRIVATE_MESSAGE}
            return deepcopy(self.fixture["instance_catalogs"][params["Region"]])
        if action == "DescribeImage":
            if params["ImageType"] != "Base" or params["OsType"] != "Linux" or params["PriceSet"] != "1":
                raise AssertionError("Read only the official Linux baseline images, with explicit price metadata.")
            offset, limit = int(params["Offset"]), int(params["Limit"])
            indexes = range(offset, min(offset + limit, self.image_count))
            if self.incomplete_images and offset:
                indexes = []
            rows = []
            for index in indexes:
                row = deepcopy(self.fixture["image_template"])
                row["ImageId"] = "base-" + params["Region"] + "-" + str(0 if self.duplicate_images else index)
                row["Zone"] = params["Region"] + "-01"
                rows.append(row)
            return {"Action": action + "Response", "RetCode": 0, "ImageSet": rows, "TotalCount": self.image_count}
        if action == "GetUHostInstancePrice":
            if params["Zone"] in self.fail_price_zones:
                return {"Action": action + "Response", "RetCode": 171, "Message": PRIVATE_MESSAGE}
            payload = deepcopy(self.fixture["quote"])
            total = self.quote_totals[params["Zone"]]
            payload["PriceSet"][0].update(Price=total, PriceDetail={"UHost": total, "UDisk": 0})
            payload["irrelevant_private_field"] = PRIVATE_MESSAGE
            return payload
        raise AssertionError("Unexpected API action: " + action)

    @staticmethod
    def assert_request(url, method, authenticated, headers):
        if (url != provider.API_URL or method != "POST" or authenticated is not True
                or headers != {"Content-Type": "application/x-www-form-urlencoded"}):
            raise AssertionError("No cookies, query-string credentials or unreviewed destination are permitted.")

    def locations(self, *, settings):
        return ucloud_public.parse_location_catalog(self.fixture["public_regions"], self.fixture["public_zones"])


def collect(api, **options):
    settings = Settings(providers=("ucloud",), ucloud_source="api", catalog_scope="complete",
                        ucloud_public_key=PUBLIC_KEY, ucloud_private_key=PRIVATE_KEY,
                        ucloud_project_id="org-synthetic", max_retries=0, **options)
    with patch.object(provider, "request_json", side_effect=api.request), \
            patch.object(ucloud_public, "load_location_catalog", side_effect=api.locations), \
            patch.object(provider.ucloud_console.UCloudConsoleSession, "from_settings", side_effect=AssertionError("No browser session")):
        return provider.collect_result(settings=settings, observed_at=OBSERVED)


class UCloudSignedCatalogTests(unittest.TestCase):
    def test_complete_api_dispatch_uses_signed_discovery_without_cookie_or_explicit_targets(self):
        from gpu_price_monitor import collect_prices
        from gpu_price_monitor.collector import _selected_module, provider_source
        settings = Settings(ucloud_source="api", catalog_scope="complete", ucloud_public_key=PUBLIC_KEY,
                            ucloud_private_key=PRIVATE_KEY, ucloud_project_id="org-synthetic", max_retries=0)
        self.assertIs(_selected_module("ucloud", settings), provider)
        self.assertEqual(provider_source("ucloud", settings), "official_quote_api")
        api = FakeAPI()
        with patch.object(provider, "request_json", side_effect=api.request), \
                patch.object(ucloud_public, "load_location_catalog", side_effect=api.locations), \
                patch.object(provider.ucloud_console.UCloudConsoleSession, "from_settings", side_effect=AssertionError("No browser session")):
            result = collect_prices(["ucloud"], {"regions": ["region-cn"]}, settings=settings)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["prices"]), 2)
        self.assertTrue(all(q["regions"] == ["region-cn"] for q in result["prices"]))
        self.assertFalse(any(params.get("Region") == "region-us" for action, params in api.calls if action in {"DescribeImage", "GetUHostInstancePrice"}))

    def test_selected_scope_keeps_the_explicit_target_quote_adapter(self):
        from gpu_price_monitor.collector import _selected_module
        self.assertIs(_selected_module("ucloud", Settings(ucloud_source="api", catalog_scope="standard")), ucloud)

    def test_each_account_region_is_rediscovered_and_exact_zone_is_separately_priced(self):
        api = FakeAPI()
        result = collect(api)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual(result["authentication_method"], provider.AUTHENTICATION_METHOD)
        self.assertEqual(result["coverage"]["discovery_regions_attempted"], ["region-cn", "region-us"])
        self.assertEqual(result["coverage"]["discovery_regions_succeeded"], ["region-cn", "region-us"])
        self.assertFalse(result["coverage"]["uses_cached_catalog"])
        self.assertEqual(result["coverage"]["signed_request_counts"]["GetRegion"], 1)
        self.assertEqual(result["coverage"]["signed_request_counts"]["DescribeAvailableInstanceTypes"], 2)
        quotes = {q["zones"][0]: q for q in result["prices"]}
        self.assertEqual({z: q["amount"] for z, q in quotes.items()},
                         {"region-cn-01": "4.2", "region-cn-02": "6.3", "region-us-01": "10.4"})
        self.assertEqual(quotes["region-us-01"]["compute_countries"], ["US"])
        self.assertEqual(quotes["region-cn-01"]["compute_countries"], ["CN"])
        # 5090Pro was omitted by the older explicit-target API model allowlist.
        self.assertIn("5090Pro", result["coverage"]["gpu_models"])
        self.assertIn("T4", result["coverage"]["gpu_models"])
        for action, params in api.calls:
            if action != "GetRegion":
                self.assertEqual(params["ProjectId"], "org-synthetic")
        output = json.dumps(result)
        for secret in (PUBLIC_KEY, PRIVATE_KEY, PRIVATE_MESSAGE, "org-synthetic"):
            self.assertNotIn(secret, output)
        self.assertTrue(all(q["source_type"] == "official_quote_api" and q["availability"] == "unknown" for q in quotes.values()))

    def test_next_run_uses_fresh_catalog_not_cached_targets_or_model_allowlist(self):
        api = FakeAPI()
        first = collect(api)
        extra = deepcopy(api.fixture["instance_catalogs"]["region-us"]["AvailableInstanceTypes"][0])
        extra["Name"] = "Future-GPU-9000"
        api.fixture["instance_catalogs"]["region-us"]["AvailableInstanceTypes"].append(extra)
        second = collect(api)
        self.assertEqual(len(first["prices"]), 3)
        self.assertEqual(len(second["prices"]), 4)
        self.assertIn("Future-GPU-9000", second["coverage"]["gpu_models"])
        self.assertEqual(sum(a == "GetRegion" for a, _ in api.calls), 2)

    def test_image_pages_are_complete_before_configuration_prices_are_requested(self):
        api = FakeAPI()
        api.image_count = 101
        result = collect(api)
        self.assertEqual(result["status"], "ok")
        for region in ("region-cn", "region-us"):
            offsets = [int(p["Offset"]) for a, p in api.calls if a == "DescribeImage" and p["Region"] == region]
            self.assertEqual(offsets, [0, 100])
        self.assertEqual(len(result["prices"]), 3)

    def test_incomplete_or_duplicate_image_pages_do_not_produce_prices(self):
        for defect in ("incomplete_images", "duplicate_images"):
            api = FakeAPI()
            api.image_count = 101
            setattr(api, defect, True)
            result = collect(api)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["prices"])
            self.assertFalse(any(a == "GetUHostInstancePrice" for a, _ in api.calls))

    def test_denied_region_is_a_gap_and_never_copied_from_another_region(self):
        api = FakeAPI()
        api.fail_regions.add("region-us")
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["coverage"]["discovery_regions_succeeded"], ["region-cn"])
        self.assertEqual(result["gaps"][0]["region"], "region-us")
        self.assertEqual(result["gaps"][0]["provider_retcode"], 299)
        self.assertNotIn(PRIVATE_MESSAGE, json.dumps(result))

    def test_failed_price_preserves_other_exact_zone_prices_and_protocol_diagnostic(self):
        api = FakeAPI()
        api.fail_price_zones.add("region-cn-02")
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["gaps"][0]["Zone"], "region-cn-02")
        self.assertEqual(result["gaps"][0]["provider_retcode"], 171)
        self.assertNotIn(PRIVATE_MESSAGE, json.dumps(result))

    def test_unmapped_region_zone_is_priced_without_a_country_from_its_prefix(self):
        api = FakeAPI()
        api.fixture["account_regions"]["Regions"].append({"Region": "us-mystery", "Zone": "us-mystery-01"})
        extra = deepcopy(api.fixture["instance_catalogs"]["region-us"])
        extra["AvailableInstanceTypes"][0]["Zone"] = "us-mystery-01"
        api.fixture["instance_catalogs"]["us-mystery"] = extra
        api.quote_totals["us-mystery-01"] = "31.6"
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertIn("us-mystery", result["coverage"]["discovery_regions_attempted"])
        self.assertIn("us-mystery", result["coverage"]["discovery_regions_succeeded"])
        self.assertEqual(len(result["prices"]), 4)
        unknown = next(q for q in result["prices"] if q["regions"] == ["us-mystery"])
        self.assertEqual(unknown["zones"], ["us-mystery-01"])
        self.assertEqual(unknown["amount"], "15.8")
        self.assertEqual(unknown["compute_countries"], [])
        self.assertIsNone(unknown["location"]["country_code"])
        self.assertEqual(unknown["price_scope"], "requested_zone_quote")
        self.assertTrue(unknown["region_price_verified"])
        self.assertEqual(unknown["location_source"]["country_status"], "not_verified")
        self.assertNotIn("country_mapping", unknown["location_source"])
        self.assertEqual(result["coverage"]["quote_gap_count"], 0)
        self.assertEqual({error["code"] for error in result["errors"]}, {"incomplete_catalog"})
        self.assertEqual({(gap["scope"], gap.get("status", gap.get("code"))) for gap in result["gaps"]},
                         {("catalog_region_country", "country_not_verified"), ("region_country_binding", "country_not_verified")})
        from gpu_price_monitor.csv_export import publishable_quote
        self.assertFalse(publishable_quote(unknown))

    def test_unmapped_zone_does_not_borrow_a_known_sibling_zones_country(self):
        api = FakeAPI()
        api.fixture["public_zones"]["Zones"] = [
            row for row in api.fixture["public_zones"]["Zones"] if row["Zone"] != "region-cn-02"]
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 3)
        quotes = {q["zones"][0]: q for q in result["prices"]}
        self.assertEqual(quotes["region-cn-01"]["compute_countries"], ["CN"])
        self.assertEqual(quotes["region-cn-02"]["compute_countries"], [])
        self.assertIsNone(quotes["region-cn-02"]["location"]["country_code"])
        self.assertEqual(quotes["region-cn-02"]["amount"], "6.3")
        self.assertEqual(quotes["region-us-01"]["compute_countries"], ["US"])

    def test_conflicting_signed_zone_region_pairs_are_rejected(self):
        api = FakeAPI()
        api.fixture["account_regions"]["Regions"].append({"Region": "other-region", "Zone": "region-cn-01"})
        with self.assertRaises(FetchError) as caught:
            collect(api)
        self.assertEqual(caught.exception.code, "invalid_region_directory")
        self.assertFalse(any(action == "GetUHostInstancePrice" for action, _ in api.calls))

    def test_cross_region_catalog_rows_are_rejected_before_pricing(self):
        api = FakeAPI()
        api.fixture["instance_catalogs"]["region-us"]["AvailableInstanceTypes"][0]["Zone"] = "region-cn-01"
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["gaps"][0]["status"], "region_catalog_mismatch")
        self.assertFalse(any(q["compute_countries"] == ["US"] for q in result["prices"]))

    def test_missing_keys_and_mutation_attempts_fail_before_network(self):
        with patch.object(provider, "request_json", side_effect=AssertionError("No network")) as request:
            with self.assertRaises(FetchError) as caught:
                provider.SignedCatalogReader(Settings(ucloud_session_path="not-read.json"))
            self.assertEqual(caught.exception.code, "missing_credentials")
            settings = Settings(ucloud_public_key=PUBLIC_KEY, ucloud_private_key=PRIVATE_KEY)
            reader = provider.SignedCatalogReader(settings)
            with self.assertRaises(FetchError):
                reader.request("CreateUHostInstance", {}, settings=settings)
            self.assertNotIn(PRIVATE_KEY, repr(reader))
            request.assert_not_called()
