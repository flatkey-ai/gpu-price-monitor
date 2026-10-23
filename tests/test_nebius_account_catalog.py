"""Synthetic authenticated catalog tests; these do not claim live API success."""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
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


def real_platform(name):
    return json.loads((Path(__file__).parent / "fixtures/nebius-account-platforms-public-20261022.json").read_text())["platforms"][name]


def published_platform(name, model, form, memory, preset_rows, region):
    return {name: {"platform_id": name, "gpu_model": model, "form_factor": form, "vram_gb": memory,
                   "coverage_regions": [region], "presets": [{"preset": preset, "gpu_count": count,
                       "vcpus": cpus, "memory_gib": ram, "coverage_regions": [region]}
                       for preset, count, cpus, ram in preset_rows]}}


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
    vm = {"cost": amount, "skuCosts": [{"skuId": "sku-synthetic-compute", "quantity": "1", "cost": amount}]}
    disk = {"cost": "0.00388888", "skuCosts": [{"skuId": "sku-synthetic-ssd", "quantity": "40", "cost": "0.00388888"}]}
    total = {"cost": format(Decimal(amount) + Decimal(disk["cost"]), "f"),
             "skuCosts": deepcopy(vm["skuCosts"] + disk["skuCosts"])}
    unit = {"unit": "hour", "unitType": "UNIT_TYPE_TIME_BASED"}
    return {"currency": "usd", "resourceCosts": [{"metadata": {"name": "catalog-price-0"},
             "aggregationUnit": unit, "general": {"total": vm}},
             {"metadata": {"name": "catalog-boot-estimate-0"}, "aggregationUnit": unit, "general": {"total": disk}}],
            "totalCosts": [{"aggregationUnit": unit, "general": {"total": total}}]}


class NebiusAccountCatalogTests(unittest.TestCase):
    def test_live_b300_sm_variant_uses_api_resources_without_inheriting_old_docs(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/nebius-b300-sm-platform-public-20261023.json").read_text())
        context = {"project_id": "project-private-example", "region": "eu-south1", "country_code": "ES"}
        old_docs = published_platform("gpu-b300-sxm", "B300", "SXM", 288,
            [("1gpu-24vcpu-346gb", 1, 24, 346), ("8gpu-192vcpu-2768gb", 8, 192, 2768)], "eu-west2")
        result = account.discover_targets([fixture["platform"]], context, old_docs, boot_disk_gib=40, currency="usd")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(len(result["targets"]), 2)
        self.assertEqual({t["region"] for t in result["targets"]}, {"eu-south1"})
        self.assertEqual({t["vram_gb"] for t in result["targets"]}, {270})
        for index, (target, evidence) in enumerate(zip(result["targets"], result["target_evidence"])):
            account.nebius_quote.validate_targets(json.dumps([target]), identity_catalog=result["identity_catalog"],
                                                 region_countries={"eu-south1": "ES"})
            raw = estimate("9.5" if index == 0 else "76")
            for component in raw["resourceCosts"]:
                component["metadata"]["name"] = component["metadata"]["name"].removesuffix("0") + str(index)
            quote = account.split_compute_storage(raw, target, observed_at=OBSERVED,
                identities=result["identity_catalog"], country_codes={"eu-south1": "ES"})[0]
            self.assertEqual(quote["amount"], "9.5")
            self.assertEqual(quote["resources"]["memory_gib"], 464 if index == 0 else 3712)
            self.assertEqual(evidence["identity_basis"], "official_project_platform_api")
            self.assertEqual(evidence["documentation_status"], "platform_variant_not_listed")
            self.assertIsNone(evidence["documented_gpu_memory_gb"])
            self.assertEqual(evidence["source_urls"], [account.PLATFORMS_URL])

    def test_b300_sm_rejects_conflicting_model_vram_or_preset_resources(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/nebius-b300-sm-platform-public-20261023.json").read_text())
        context = {"project_id": "project-private-example", "region": "eu-south1", "country_code": "ES"}
        mutations = [lambda row: row["spec"].update(shortHumanReadableName="NVIDIA B200 NVLink SM"),
                     lambda row: row["spec"].update(gpuMemoryGigabytes=288),
                     lambda row: row["spec"]["presets"][0]["resources"].update(memoryGibibytes=346),
                     lambda row: row["spec"]["presets"][0]["resources"].update(gpuCount=True)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                row = deepcopy(fixture["platform"])
                mutate(row)
                result = account.discover_targets([row], context, {}, boot_disk_gib=40, currency="usd")
                self.assertEqual(result["targets"], [])
                self.assertTrue(result["gaps"])

    def test_real_b300_api_memory_matches_product_pages_and_retains_vm_table_discrepancy(self):
        docs = published_platform("gpu-b300-sxm", "B300", "SXM", 288,
            [("1gpu-24vcpu-346gb", 1, 24, 346), ("8gpu-192vcpu-2768gb", 8, 192, 2768)], "eu-west2")
        context = {"project_id": "project-private-example", "region": "eu-west2", "country_code": "FR"}
        row = real_platform("gpu-b300-sxm")
        result = account.discover_targets([row], context, docs, boot_disk_gib=40, currency="usd")
        self.assertEqual(len(result["targets"]), 2)
        self.assertEqual(result["gaps"], [])
        self.assertEqual({t["vram_gb"] for t in result["targets"]}, {270})
        self.assertEqual(result["target_evidence"][0]["documentation_discrepancy"]["vm_types_table"], 288)
        self.assertIn("https://nebius.com/self-service", result["target_evidence"][0]["source_urls"])
        for target in result["targets"]:
            account.nebius_quote.validate_targets(json.dumps([target]), identity_catalog=result["identity_catalog"],
                                                   region_countries={"eu-west2": "FR"})
        row["spec"]["gpuMemoryGigabytes"] = 271
        conflict = account.discover_targets([row], context, docs, boot_disk_gib=40, currency="usd")
        self.assertEqual(conflict["targets"], [])
        self.assertEqual({g["status"] for g in conflict["gaps"]}, {"gpu_memory_gb_conflict"})

    def test_real_rtx_pcie_generation_label_requires_exact_current_identity(self):
        docs = published_platform("gpu-rtx6000", "RTX PRO 6000", "PCIe Gen5", 96,
            [("1gpu-24vcpu-218gb", 1, 24, 218), ("8gpu-192vcpu-1744gb", 8, 192, 1744)], "us-central1")
        result = account.discover_targets([real_platform("gpu-rtx6000")], project(), docs, boot_disk_gib=40, currency="usd")
        target = result["targets"][0]
        self.assertEqual(target["gpu_variant"], "PCIe Gen5")
        account.nebius_quote.validate_targets(json.dumps([target]), identity_catalog=result["identity_catalog"],
                                               region_countries={"us-central1": "US"})
        target["gpu_variant"] = "PCIe Gen6"
        with self.assertRaises(FetchError):
            account.nebius_quote.validate_targets(json.dumps([target]), identity_catalog=result["identity_catalog"],
                                                   region_countries={"us-central1": "US"})

    def test_real_gb300_exact_provider_example_identity_is_not_b300_sxm(self):
        context = project("eu-north1")
        row = real_platform("gpu-gb300")
        result = account.discover_targets([row], context, {}, boot_disk_gib=40, currency="usd")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(len(result["targets"]), 1)
        target = result["targets"][0]
        self.assertEqual((target["gpu_model"], target["gpu_variant"], target["vram_gb"], target["gpu_count"]),
                         ("GB300", "NVL72", 279, 4))
        account.nebius_quote.validate_targets(json.dumps([target]), identity_catalog=result["identity_catalog"],
                                               region_countries={"eu-north1": "FI"})
        row["spec"]["shortHumanReadableName"] = "NVIDIA GB200 NVL72"
        self.assertEqual(account.discover_targets([row], context, {}, boot_disk_gib=40, currency="usd")["targets"], [])

    def test_storage_projection_rejects_missing_duplicate_or_zero_compute_prices(self):
        result = account.discover_targets([api_platform()], project(), platforms(), boot_disk_gib=40, currency="usd")
        target = result["targets"][0]
        def split(raw):
            return account.split_compute_storage(raw, target, observed_at=OBSERVED,
                identities=result["identity_catalog"], country_codes={"us-central1": "US"})
        missing = estimate()
        missing["resourceCosts"].pop()
        with self.assertRaises(ValueError):
            split(missing)
        with self.assertRaises(FetchError) as unpriced:
            split(estimate("0"))
        self.assertEqual(unpriced.exception.code, "compute_tariff_unavailable")
        duplicate = estimate()
        extra = deepcopy(duplicate["resourceCosts"][1])
        extra["metadata"]["name"] = "catalog-boot-0"
        duplicate["resourceCosts"].append(extra)
        total = duplicate["totalCosts"][0]["general"]["total"]
        total["cost"] = format(Decimal(total["cost"]) + Decimal(extra["general"]["total"]["cost"]), "f")
        total["skuCosts"].extend(deepcopy(extra["general"]["total"]["skuCosts"]))
        with self.assertRaises(FetchError) as captured:
            split(duplicate)
        self.assertEqual(captured.exception.code, "nested_storage_pricing_changed")
        no_disk_skus = estimate()
        no_disk_skus["resourceCosts"][1]["general"]["total"]["skuCosts"] = []
        with self.assertRaises(ValueError):
            split(no_disk_skus)
        overlap = estimate()
        overlap["resourceCosts"][0]["general"]["total"]["skuCosts"][0]["skuId"] = "sku-synthetic-ssd"
        overlap["totalCosts"][0]["general"]["total"]["skuCosts"][0]["skuId"] = "sku-synthetic-ssd"
        with self.assertRaises(FetchError) as embedded:
            split(overlap)
        self.assertEqual(embedded.exception.code, "embedded_storage_pricing_changed")

    def test_dynamic_fresh_catalog_identity_can_price_a_new_model_without_code_whitelist(self):
        rows = [api_platform()]
        discovery = account.discover_targets(rows, project(), platforms(), boot_disk_gib=40, currency="usd")
        target = discovery["targets"][0]
        self.assertEqual(discovery["discovered_gpu_preset_count"], 1)
        self.assertEqual(discovery["gaps"], [])
        self.assertEqual(target["gpu_model"], "B400")
        self.assertEqual(target["resource_specs"][0]["spec"]["spec"]["bootDisk"]["managedDisk"]["spec"]["sizeGibibytes"], "40")
        quote = account.split_compute_storage(estimate(), target, observed_at=OBSERVED,
                    identities=account.identity_catalog(platforms()), country_codes={"us-central1": "US"})[0]
        self.assertEqual(quote["amount"], "8.5125")
        self.assertEqual(quote["compute_countries"], ["US"])
        self.assertEqual(quote["regions"], ["us-central1"])
        self.assertEqual(quote["storage_quote"]["amount"], "0.00388888")
        self.assertEqual(quote["full_configuration_price"]["amount"], "68.10388888")
        self.assertEqual(quote["full_configuration_price"]["per_gpu_amount"], "8.51298611")
        self.assertEqual(quote["instance_price"]["scope"], "compute_resources_only")
        self.assertFalse(quote["storage_quote"]["included_in_main_gpu_price"])
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

    def test_protojson_omitted_cpu_gpu_count_does_not_create_a_false_gap(self):
        cpu = {"metadata": {"name": "cpu-amd"}, "spec": {"presets": [
            {"name": "4vcpu-16gb", "resources": {"vcpuCount": 4, "memoryGibibytes": 16}}]}}
        discovery = account.discover_targets([cpu, api_platform()], project(), platforms(), boot_disk_gib=40, currency="usd")
        self.assertEqual(discovery["excluded_cpu_preset_count"], 1)
        self.assertEqual(discovery["discovered_gpu_preset_count"], 1)
        self.assertEqual(len(discovery["targets"]), 1)
        self.assertEqual(discovery["gaps"], [])

        # The omitted-zero exception is based on CPU identity, not the absence
        # of a field: unfamiliar/GPU platforms must remain explicit gaps.
        for name in ("gpu-b400-sxm", "accelerator-future"):
            row = api_platform()
            row["metadata"]["name"] = name
            row["spec"]["presets"][0]["resources"].pop("gpuCount")
            with self.subTest(platform=name):
                result = account.discover_targets([row], project(), platforms(), boot_disk_gib=40, currency="usd")
                self.assertEqual(result["targets"], [])
                self.assertEqual(result["excluded_cpu_preset_count"], 0)
                self.assertEqual(result["gaps"][0]["status"], "preset_resource_conflict")

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

    @patch.object(account, "fetch_text", return_value="unused-doc")
    @patch.object(account.nebius_catalog_expanded, "parse_regions")
    @patch.object(account.nebius_catalog_expanded, "parse_platforms")
    @patch.object(account, "request_json")
    def test_zero_gb300_compute_with_positive_ssd_is_an_explicit_gap_not_a_gpu_price(self, request, parse_platforms, parse_regions, fetch):
        parse_regions.return_value = nebius_regions.parse_directory(DIRECTORY, observed_at=OBSERVED)
        parse_platforms.return_value = platforms()
        zero = estimate("0")
        zero["resourceCosts"][0]["metadata"]["name"] = "catalog-price-1"
        zero["resourceCosts"][1]["metadata"]["name"] = "catalog-boot-estimate-1"
        request.side_effect = [
            {"items": [{"metadata": {"id": "tenant-private-test"}}]},
            {"items": [{"metadata": {"id": "project-private-fi"}, "spec": {"region": "eu-north1"}}]},
            {"items": [api_platform(), real_platform("gpu-gb300")]}, estimate(), zero,
        ]
        result = account.collect_result(settings=Settings(nebius_access_token=SECRET), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([q["gpu_model"] for q in result["prices"]], ["B400"])
        self.assertEqual(result["errors"][0]["code"], "compute_tariff_unavailable")
        entry = result["catalog_coverage"]["unpriced_configurations"][0]
        self.assertEqual((entry["gpu_model"], entry["vram_gb"], entry["gpu_count"]), ("GB300", 279, 4))
        self.assertEqual(entry["status"], "compute_tariff_unavailable")
        self.assertTrue(any(g.get("scope") == "regional_compute_tariff" for g in result["gaps"]))
        self.assertEqual(result["prices"][0]["configuration_source"], account.PLATFORMS_URL)
        self.assertFalse(any(note.startswith("GPU model, form factor, VRAM") for note in result["prices"][0]["notes"]))
        self.assertNotIn(SECRET, json.dumps(result))

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
