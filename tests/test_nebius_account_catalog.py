"""Synthetic authenticated catalog tests; these do not claim live API success."""

from copy import deepcopy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from gpu_price_monitor.providers import nebius_account_catalog as account, nebius_regions
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-22T03:40:00Z"
SECRET = "test-synthetic-bearer-token"
DIRECTORY = """## Public regions
* `us-central1`: Kansas City, Missouri, US
* `eu-north1`: Finland
## Private regions
* `eu-north2`: Iceland
"""


def platforms():
    return {"gpu-b400-sxm": {"platform_id": "gpu-b400-sxm", "gpu_model": "B400", "form_factor": "SXM",
                              "vram_gb": 400, "coverage_regions": ["us-central1", "eu-north1"],
                              "presets": [{"preset": "8gpu-160vcpu-1792gb", "gpu_count": 8,
                                           "vcpus": 160, "memory_gib": 1792,
                                           "coverage_regions": ["us-central1", "eu-north1"]}]}}


def api_platform():
    return {"metadata": {"id": "platform-example", "name": "gpu-b400-sxm"},
            "spec": {"humanReadableName": "Synthetic B400", "presets": [
                {"name": "8gpu-160vcpu-1792gb", "resources": {"gpuCount": 8, "vcpuCount": 160, "memoryGibibytes": 1792}}]}}


def project(region="us-central1"):
    return {"project_id": "project-private-" + region, "region": region,
            "country_code": "US" if region == "us-central1" else "FI"}


def estimate(amount="68.1"):
    total = {"cost": amount, "skuCosts": [{"skuId": "sku-synthetic-compute-and-boot", "quantity": "1", "cost": amount}]}
    unit = {"unit": "hour", "unitType": "UNIT_TYPE_TIME_BASED"}
    return {"currency": "usd", "resourceCosts": [{"metadata": {"name": "catalog-price-0"},
             "aggregationUnit": unit, "general": {"total": total}}],
            "totalCosts": [{"aggregationUnit": unit, "general": {"total": total}}]}


class NebiusAccountCatalogTests(unittest.TestCase):
    def test_dynamic_fresh_catalog_identity_can_price_a_new_model_without_code_whitelist(self):
        rows = [api_platform()]
        discovery = account.discover_targets(rows, project(), platforms(), boot_disk_gib=40, currency="usd")
        target = discovery["targets"][0]
        self.assertEqual(discovery["discovered_gpu_preset_count"], 1)
        self.assertEqual(discovery["gaps"], [])
        self.assertEqual(target["gpu_model"], "B400")
        self.assertEqual(target["resource_specs"][0]["spec"]["spec"]["bootDisk"]["managedDisk"]["spec"]["sizeGibibytes"], "40")
        quote = account.nebius_quote.parse_quote(estimate(), target, observed_at=OBSERVED,
                    project_region_verified=True, identity_catalog=account.identity_catalog(platforms()),
                    region_countries={"us-central1": "US"})[0]
        self.assertEqual(quote["amount"], "8.5125")
        self.assertEqual(quote["compute_countries"], ["US"])
        self.assertEqual(quote["regions"], ["us-central1"])
        self.assertNotIn("project-private", json.dumps(quote))

    def test_unknown_platform_and_conflicting_quantities_are_explicit_gaps(self):
        unknown = api_platform()
        unknown["metadata"]["name"] = "gpu-future999"
        conflict = api_platform()
        conflict["spec"]["presets"][0]["resources"]["gpuCount"] = 1
        for row, status in ((unknown, "identity_not_verified"), (conflict, "preset_resource_conflict")):
            discovery = account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")
            self.assertEqual(discovery["targets"], [])
            self.assertEqual(discovery["gaps"][0]["status"], status)
            self.assertEqual(discovery["discovered_gpu_preset_count"], 1)

    def test_cpu_presets_counted_apart_and_duplicate_gpu_presets_rejected(self):
        cpu = {"metadata": {"name": "cpu-amd"}, "spec": {"presets": [{"name": "4vcpu-16gb", "resources": {"gpuCount": 0}}]}}
        discovery = account.discover_targets([cpu, api_platform()], project(), platforms(), boot_disk_gib=40, currency="usd")
        self.assertEqual(discovery["excluded_cpu_preset_count"], 1)
        self.assertEqual(len(discovery["targets"]), 1)
        with self.assertRaises(ValueError):
            account.discover_targets([api_platform(), api_platform()], project(), platforms(), boot_disk_gib=40, currency="usd")

    def test_explicit_api_gb_memory_must_match_documented_gpu_and_gib_is_not_compared_as_gb(self):
        for memory in (399, "400", True, None, 0):
            row = api_platform()
            row["spec"]["gpuMemoryGigabytes"] = memory
            result = account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")
            self.assertEqual(result["targets"], [])
            self.assertEqual(result["gaps"][0]["status"], "gpu_memory_gb_conflict")
        row = api_platform()
        row["spec"].update(gpuMemoryGigabytes=400, gpuMemoryGibibytes=372)
        self.assertEqual(len(account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")["targets"]), 1)
        del row["spec"]["gpuMemoryGigabytes"]
        # Missing same-unit GB is not evidence of a conflicting identity. GiB
        # is not silently equated or converted to documented advertised GB.
        self.assertEqual(len(account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")["targets"]), 1)

    def test_gpu_platform_zero_or_missing_gpu_count_is_a_gap_and_keeps_other_good_presets(self):
        for count in (0, None):
            row = api_platform()
            broken = deepcopy(row["spec"]["presets"][0])
            broken["name"] = "1gpu-20vcpu-224gb"
            if count is None:
                broken["resources"].pop("gpuCount")
            else:
                broken["resources"]["gpuCount"] = count
            row["spec"]["presets"].append(broken)
            result = account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")
            self.assertEqual(len(result["targets"]), 1)
            self.assertEqual(result["excluded_cpu_preset_count"], 0)
            self.assertEqual(result["discovered_gpu_preset_count"], 2)
            self.assertEqual(result["gaps"][0]["status"], "preset_resource_conflict")

    @patch.object(account, "collect_result", return_value={"status": "partial", "prices": [{"amount": "1"}], "errors": [], "gaps": [{"status": "unverified"}]})
    def test_list_only_wrapper_does_not_drop_gap_only_partial_status(self, collect):
        with self.assertRaises(FetchError) as captured:
            account.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "partial_collection")

    @patch.object(account, "fetch_text", return_value="unused-doc")
    @patch.object(account.nebius_catalog_expanded, "parse_regions")
    @patch.object(account.nebius_catalog_expanded, "parse_platforms")
    @patch.object(account, "request_json")
    def test_collect_discovers_two_region_projects_and_only_posts_readonly_estimates(self, request, parse_platforms, parse_regions, fetch):
        parse_regions.return_value = nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED)
        parse_platforms.return_value = platforms()
        calls = []
        def handler(url, settings, **kwargs):
            calls.append((url, kwargs))
            if url.startswith(account.TENANTS_URL + "?"):
                return {"items": [{"metadata": {"id": "tenant-private-example"}}]}
            if url.startswith(account.PROJECTS_URL + "?"):
                return {"items": [{"metadata": {"id": "project-private-" + r}, "spec": {"region": r}}
                                  for r in ("us-central1", "eu-north1")]}
            if url.startswith(account.PLATFORMS_URL + "?"):
                return {"items": [api_platform()]}
            if url == account.SOURCE_URL:
                body = json.loads(kwargs["data"])
                region = body["resourceSpecs"][0]["spec"]["metadata"]["parentId"]
                return estimate("68.1" if region.endswith("us-central1") else "72.1")
            raise AssertionError(url)
        request.side_effect = handler
        result = account.collect_result(settings=Settings(nebius_access_token=SECRET), observed_at=OBSERVED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual({tuple(q["compute_countries"]) for q in result["prices"]}, {("US",), ("FI",)})
        self.assertEqual({q["amount"] for q in result["prices"]}, {"8.5125", "9.0125"})
        self.assertEqual(result["coverage"]["successful_estimate_count"], 2)
        self.assertFalse(result["coverage"]["all_account_prices_complete"])
        self.assertEqual(len([c for c in calls if c[1].get("method") == "POST"]), 2)
        self.assertTrue(all(c[0] == account.SOURCE_URL for c in calls if c[1].get("method") == "POST"))
        self.assertTrue(all(c[1]["authenticated"] is True for c in calls))
        output = json.dumps(result)
        self.assertNotIn(SECRET, output)
        self.assertNotIn("project-private", output)
        self.assertNotIn("tenant-private", output)
        self.assertTrue(all(q["selected_configuration"]["boot_disk_gib"] == 40 for q in result["prices"]))

    @patch.object(account, "fetch_text", return_value="unused-doc")
    @patch.object(account.nebius_catalog_expanded, "parse_regions")
    @patch.object(account.nebius_catalog_expanded, "parse_platforms")
    @patch.object(account, "request_json")
    def test_one_estimate_failure_preserves_other_region_and_does_not_fallback_to_public_price(self, request, parse_platforms, parse_regions, fetch):
        parse_regions.return_value = nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED)
        parse_platforms.return_value = platforms()
        request.side_effect = [
            {"items": [{"metadata": {"id": "tenant-private-test"}}]},
            {"items": [{"metadata": {"id": "project-private-us"}, "spec": {"region": "us-central1"}},
                       {"metadata": {"id": "project-private-fi"}, "spec": {"region": "eu-north1"}}]},
            {"items": [api_platform()]}, FetchError("http_403", "private project denied", False),
            {"items": [api_platform()]}, estimate(),
        ]
        result = account.collect_result(settings=Settings(nebius_access_token=SECRET), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["prices"][0]["regions"], ["eu-north1"])
        self.assertEqual(result["errors"][0]["code"], "http_403")
        self.assertNotIn("private project denied", json.dumps(result))
        self.assertEqual(result["coverage"]["successful_estimate_count"], 1)

    @patch.object(account, "request_json")
    def test_bounded_pagination_uses_fixed_origin_and_opaque_tokens(self, request):
        request.side_effect = [{"items": [{"metadata": {"id": "tenant-first"}}], "nextPageToken": "https://evil.invalid?a=1&b=2"},
                               {"items": [{"metadata": {"id": "tenant-second"}}]}]
        rows = account._list(account.TENANTS_URL, Settings(), {"Authorization": "Bearer synthetic"})
        self.assertEqual(len(rows), 2)
        second = urlsplit(request.call_args_list[1].args[0])
        self.assertEqual(second.netloc, "api.nebius.cloud")
        self.assertEqual(parse_qs(second.query)["pageToken"], ["https://evil.invalid?a=1&b=2"])
        request.side_effect = None
        request.return_value = {"items": [{"metadata": {"id": "tenant-repeat"}}], "nextPageToken": "repeat"}
        with self.assertRaises(ValueError):
            account._list(account.TENANTS_URL, Settings(), {})

    @patch.object(account, "fetch_text", return_value="unused-doc")
    @patch.object(account.nebius_catalog_expanded, "parse_regions")
    @patch.object(account.nebius_catalog_expanded, "parse_platforms")
    @patch.object(account, "request_json")
    def test_missing_public_region_project_is_a_gap_without_manufactured_country_price(self, request, parse_platforms, parse_regions, fetch):
        parse_regions.return_value = nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED)
        parse_platforms.return_value = platforms()
        request.side_effect = [
            {"items": [{"metadata": {"id": "tenant-private-test"}}]},
            {"items": [{"metadata": {"id": "project-private-us"}, "spec": {"region": "us-central1"}}]},
            {"items": [api_platform()]}, estimate(),
        ]
        result = account.collect_result(settings=Settings(nebius_access_token=SECRET), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        absent = [g for g in result["gaps"] if g["status"] == "no_accessible_project"]
        self.assertEqual([(g["region"], g["country_code"]) for g in absent], [("eu-north1", "FI")])
        self.assertEqual([q["regions"] for q in result["prices"]], [["us-central1"]])
        self.assertNotIn("eu-north2", [g.get("region") for g in result["gaps"]])

    @patch.object(account, "fetch_text")
    @patch.object(account, "request_json")
    def test_missing_or_malformed_credentials_fail_before_network(self, request, fetch):
        for token, code in ((None, "missing_credentials"), ("bad\nheader", "invalid_credentials")):
            with self.subTest(token=token), self.assertRaises(FetchError) as captured:
                account.collect_result(settings=Settings(nebius_access_token=token), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, code)
        fetch.assert_not_called()
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
