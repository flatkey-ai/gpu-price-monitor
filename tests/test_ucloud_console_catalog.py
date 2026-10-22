"""Catalog-derived configurations keep zone, CPU compatibility and source units."""

from copy import deepcopy
import unittest

from gpu_price_monitor.providers.ucloud_console_catalog import build_catalog_targets


def fixture():
    regions = {"Regions": [{"Region": "example-a", "LocalName": "Example A", "CountryCode": "US"},
                           {"Region": "example-b", "LocalName": "Example B", "CountryCode": "SG"}]}
    zones = {"Zones": [{"Zone": "example-a-01", "Region": "example-a", "LocalName": "A zone 1", "Permission": "not-returned"},
                       {"Zone": "example-b-01", "Region": "example-b", "LocalName": "B zone 1"}]}
    row = {"Name": "New-GPU-123", "Zone": "example-a-01", "ParentType": "G", "InstanceType": "uhost",
           "Status": "Normal", "CpuPlatforms": {"Intel": ["Intel/IceLake"], "Amd": ["Amd/Epyc5"]},
           "GraphicsMemory": {"Value": 48},
           "Features": [{"Name": "NetCapability", "Modes": [{"Name": "Normal"},
                        {"Name": "Super", "RelatedToImageFeature": ["NetEnhanced"]}]}],
           "MachineSizes": [{"Gpu": 1, "Collection": [{"Cpu": 8, "Memory": [32, 64],
                "MinimalCpuPlatform": ["Intel/IceLake", "Intel/SapphireRapids", "Amd/Epyc5"]}]}],
           "Disks": [{"Name": "cloudDisk", "BootDisk": [{"Name": "CLOUD_SSD", "MinimalSize": 20, "MaximalSize": 500,
                       "InstantResize": True, "Features": ["SNAPSHOT"], "unrelated": "not-returned"}]}]}
    return regions, zones, {"AvailableInstanceTypes": [row]}


class UCloudConsoleCatalogTests(unittest.TestCase):
    def test_all_explicit_shapes_vendor_dedup_and_source_options(self):
        inputs = fixture()
        before = deepcopy(inputs)
        result = build_catalog_targets(*inputs)
        self.assertEqual(len(result.targets), 4)
        target = next(t for t in result.targets if t.request["CpuPlatform"] == "Intel")
        self.assertEqual(target.cpu_platform_options, ["Intel/IceLake", "Intel/SapphireRapids"])
        self.assertEqual(target.request, {"Region": "example-a", "Zone": "example-a-01", "MachineType": "G",
            "GpuType": "New-GPU-123", "GPU": 1, "CPU": 8, "Memory": 32768, "CpuPlatform": "Intel",
            "NetCapability": "Normal",
            "ChargeType": "Dynamic", "Count": 1, "ShowPriceDetails": True})
        self.assertEqual(target.gpu_memory_gb, 48)
        self.assertEqual(target.location["country_code"], "US")
        self.assertFalse(target.metadata["availability_verified"])
        self.assertNotIn("Permission", str(result))
        self.assertNotIn("not-returned", str(result))
        self.assertEqual(inputs, before)

    def test_network_baseline_prefers_normal_and_retains_source_modes(self):
        inputs = fixture()
        modes = inputs[2]["AvailableInstanceTypes"][0]["Features"][0]["Modes"]
        modes.reverse()
        result = build_catalog_targets(*inputs)
        self.assertEqual({t.request["NetCapability"] for t in result.targets}, {"Normal"})
        for item in result.targets:
            self.assertEqual(item.metadata["network_mode_options"], modes)
            self.assertEqual(item.metadata["network_mode"], "Normal")
            self.assertEqual(item.metadata["network_mode_required_image_features"], [])

    def test_network_baseline_uses_only_explicit_mode_and_image_requirement(self):
        for mode in ["Super", "Ultra", "Extreme", "Infiniband"]:
            with self.subTest(mode=mode):
                inputs = fixture()
                modes = [{"Name": mode, "RelatedToImageFeature": ["NetEnhanced"]}]
                inputs[2]["AvailableInstanceTypes"][0]["Features"][0]["Modes"] = modes
                result = build_catalog_targets(*inputs)
                self.assertEqual(len(result.targets), 4)
                self.assertEqual({t.request["NetCapability"] for t in result.targets}, {mode})
                self.assertEqual(result.targets[0].metadata["network_mode_required_image_features"], ["NetEnhanced"])

    def test_missing_ambiguous_or_unverifiable_network_mode_excludes_row(self):
        invalid_features = [None, [], [{"Name": "NetCapability", "Modes": None}],
            [{"Name": "NetCapability", "Modes": []}],
            [{"Name": "NetCapability", "Modes": [{"Name": "Super"}, {"Name": "Ultra"}]}],
            [{"Name": "NetCapability", "Modes": [{"Name": "FutureMode"}]}],
            [{"Name": "NetCapability", "Modes": [{"Name": "Normal"}, {"Name": "Normal"}]}],
            [{"Name": "NetCapability", "Modes": [{"Name": "Normal", "RelatedToImageFeature": "NetEnhanced"}]}],
            [{"Name": "NetCapability", "Modes": [{"Name": "Normal", "MinimalCpuPlatform": ["Intel/IceLake"]}]}]]
        for features in invalid_features:
            with self.subTest(features=features):
                inputs = fixture()
                inputs[2]["AvailableInstanceTypes"][0]["Features"] = features
                result = build_catalog_targets(*inputs)
                self.assertEqual(result.targets, [])
                self.assertEqual(result.counts["uhost_gpu_rows_excluded"], 1)
                self.assertEqual(result.gaps[0]["code"], "invalid_gpu_configuration")

    def test_never_crossproduct_specs_between_zones(self):
        regions, zones, data = fixture()
        second = deepcopy(data["AvailableInstanceTypes"][0])
        second.update(Zone="example-b-01", Status="Soldout",
                      MachineSizes=[{"Gpu": 8, "Collection": [{"Cpu": 128, "Memory": [512],
                                       "MinimalCpuPlatform": ["Amd/Epyc5"]}]}])
        data["AvailableInstanceTypes"].append(second)
        result = build_catalog_targets(regions, zones, data)
        self.assertEqual(len(result.targets), 5)
        target = next(t for t in result.targets if t.country_code == "SG")
        self.assertEqual((target.gpu_count, target.request["CPU"], target.request["Memory"]), (8, 128, 524288))
        self.assertEqual(target.catalog_status, "Soldout")
        self.assertFalse(target.metadata["availability_verified"])

    def test_nested_gpu_shape_and_row_platform_fallback(self):
        regions, zones, data = fixture()
        row = data["AvailableInstanceTypes"][0]
        row["GpuType"] = {"Name": "Raw-new-model", "GraphicsMemory": {"Value": 96}}
        del row["MachineSizes"][0]["Collection"][0]["MinimalCpuPlatform"]
        result = build_catalog_targets(regions, zones, data)
        self.assertEqual({t.gpu_model for t in result.targets}, {"Raw-new-model"})
        self.assertEqual({t.gpu_memory_gb for t in result.targets}, {96})
        self.assertEqual({tuple(t.cpu_platform_options) for t in result.targets}, {("Intel/IceLake",), ("Amd/Epyc5",)})

    def test_explicit_empty_restrictions_and_malformed_specs_fail_closed(self):
        for field, value in [("MinimalCpuPlatform", []), ("Memory", [True]), ("Cpu", 0),
                             ("Memory", [float("nan")]), ("Memory", [0.0001])]:
            with self.subTest(field=field, value=value):
                inputs = fixture()
                inputs[2]["AvailableInstanceTypes"][0]["MachineSizes"][0]["Collection"][0][field] = value
                result = build_catalog_targets(*inputs)
                self.assertEqual(result.targets, [])
                self.assertEqual(result.gaps[0]["code"], "invalid_gpu_configuration")

    def test_country_is_taken_only_from_exact_official_directory(self):
        for country in [None, "", "China", "cn"]:
            with self.subTest(country=country):
                inputs = fixture()
                inputs[0]["Regions"][0]["CountryCode"] = country
                result = build_catalog_targets(*inputs)
                self.assertEqual(result.targets, [])
                self.assertEqual(result.gaps[0]["code"], "unverified_country_or_region")
        inputs = fixture()
        inputs[1]["Zones"][0]["Region"] = "missing"
        self.assertFalse(build_catalog_targets(*inputs).targets)

    def test_scope_counts_exclude_spot_and_cpu_and_report_no_shapes(self):
        inputs = fixture()
        rows = inputs[2]["AvailableInstanceTypes"]
        spot = deepcopy(rows[0]); spot["InstanceType"] = "spot"
        cpu = {"Name": "cpu", "InstanceType": "uhost"}
        missing = deepcopy(rows[0]); missing["Name"] = "No-shapes"; missing.pop("MachineSizes")
        rows.extend([spot, cpu, missing])
        result = build_catalog_targets(*inputs)
        self.assertEqual(result.counts["catalog_rows"], 4)
        self.assertEqual(result.counts["uhost_gpu_catalog_rows"], 2)
        self.assertEqual(result.counts["spot_gpu_catalog_rows"], 1)
        self.assertEqual(result.counts["uhost_gpu_rows_excluded"], 1)
        self.assertEqual(result.counts["quote_targets"], 4)
        self.assertEqual(result.gaps[0]["name"], "No-shapes")

    def test_repeated_vendor_shapes_merge_generation_options(self):
        inputs = fixture()
        collection = inputs[2]["AvailableInstanceTypes"][0]["MachineSizes"][0]["Collection"]
        collection[:] = [{"Cpu": 8, "Memory": [32], "MinimalCpuPlatform": ["Intel/IceLake"]},
                         {"Cpu": 8, "Memory": [32], "MinimalCpuPlatform": ["Intel/SapphireRapids"]}]
        result = build_catalog_targets(*inputs)
        self.assertEqual(len(result.targets), 1)
        self.assertEqual(result.targets[0].cpu_platform_options, ["Intel/IceLake", "Intel/SapphireRapids"])

    def test_bad_top_level_and_duplicate_region_identities_rejected(self):
        inputs = fixture()
        inputs[0]["Regions"].append(deepcopy(inputs[0]["Regions"][0]))
        with self.assertRaises(ValueError):
            build_catalog_targets(*inputs)
        for retcode in (170, False, "0"):
            inputs = fixture()
            inputs[2]["RetCode"] = retcode
            with self.assertRaises(ValueError):
                build_catalog_targets(*inputs)

    def test_duplicate_catalog_rows_do_not_duplicate_prices_or_claim_a_gap(self):
        inputs = fixture()
        inputs[2]["AvailableInstanceTypes"].append(deepcopy(inputs[2]["AvailableInstanceTypes"][0]))
        result = build_catalog_targets(*inputs)
        self.assertEqual(len(result.targets), 4)
        self.assertFalse(result.gaps)
        self.assertEqual(result.counts["duplicate_gpu_catalog_rows"], 1)

    def test_conflicting_same_configuration_is_excluded(self):
        inputs = fixture()
        second = deepcopy(inputs[2]["AvailableInstanceTypes"][0])
        second["GraphicsMemory"]["Value"] = 96
        inputs[2]["AvailableInstanceTypes"].append(second)
        result = build_catalog_targets(*inputs)
        self.assertFalse(result.targets)
        self.assertEqual({g["code"] for g in result.gaps}, {"conflicting_gpu_configuration"})


if __name__ == "__main__":
    unittest.main()
