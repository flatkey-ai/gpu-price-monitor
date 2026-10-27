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
        invalid_features = [None, [], [{"Name": "NetCapability"}],
            [{"Name": "NetCapability", "Modes": "Normal"}],
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

    def test_explicit_null_or_empty_modes_follow_console_normal_default(self):
        for modes in (None, []):
            with self.subTest(modes=modes):
                inputs = fixture()
                row = inputs[2]["AvailableInstanceTypes"][0]
                row["Name"] = "P40"
                row["Features"][0]["Modes"] = modes
                result = build_catalog_targets(*inputs)
                self.assertEqual(len(result.targets), 4)
                for target in result.targets:
                    self.assertEqual(target.request["NetCapability"], "Normal")
                    self.assertEqual(target.metadata["network_mode_options"], [])
                    self.assertEqual(target.metadata["network_mode_required_image_features"], [])
                    self.assertEqual(target.metadata["network_mode_selection_basis"],
                                     "official_console_empty_modes_normal")
                    self.assertTrue(target.metadata["network_mode_selection_source"].startswith("https://console-s2.ucloud.cn/"))

    def test_small_a800_and_h20_use_normal_but_eight_gpus_keep_enhancement(self):
        for model, mode in (("A800", "Extreme"), ("H20", "Infiniband")):
            with self.subTest(model=model):
                inputs = fixture()
                row = inputs[2]["AvailableInstanceTypes"][0]
                row["Name"] = model
                row["Features"][0]["Modes"] = [{"Name": mode, "RelatedToImageFeature": ["NetEnhanced_" + mode]}]
                row["MachineSizes"] = [{"Gpu": count, "Collection": [{"Cpu": count * 16, "Memory": [count * 128],
                                          "MinimalCpuPlatform": ["Intel/IceLake"]}]} for count in (1, 2, 4, 8)]
                result = build_catalog_targets(*inputs)
                self.assertEqual(len(result.targets), 4)
                self.assertFalse(result.gaps)
                for target in result.targets:
                    expected = mode if target.gpu_count == 8 else "Normal"
                    self.assertEqual(target.request["NetCapability"], expected)
                    self.assertEqual(target.metadata["network_mode_required_image_features"],
                                     ["NetEnhanced_" + mode] if target.gpu_count == 8 else [])
                    self.assertEqual(target.metadata["network_mode_options"], row["Features"][0]["Modes"])

    def test_eight_gpu_console_rule_does_not_select_disabled_normal(self):
        inputs = fixture()
        row = inputs[2]["AvailableInstanceTypes"][0]
        row["Name"] = "A800"
        row["MachineSizes"][0]["Gpu"] = 8
        row["Features"][0]["Modes"] = [{"Name": "Normal"}, {"Name": "Extreme"}]
        result = build_catalog_targets(*inputs)
        self.assertEqual({t.request["NetCapability"] for t in result.targets}, {"Extreme"})

    def test_page_excluded_catalog_rows_are_audited_separately_from_failed_prices(self):
        inputs = fixture()
        soldout = {"Name": "T4", "Zone": "example-a-01", "ParentType": "G", "InstanceType": "uhost", "Status": "Soldout"}
        outside = deepcopy(inputs[2]["AvailableInstanceTypes"][0])
        outside["Zone"] = "outside-current-directory-01"
        inputs[2]["AvailableInstanceTypes"].extend([soldout, outside])
        result = build_catalog_targets(*inputs)
        self.assertEqual(len(result.targets), 4)
        self.assertFalse(result.gaps)
        self.assertEqual(result.counts["uhost_gpu_rows_outside_console_scope"], 2)
        self.assertEqual({item["code"] for item in result.exclusions},
                         {"soldout_catalog_without_configurations", "outside_current_console_zone_directory"})
        self.assertTrue(all("amount" not in item for item in result.exclusions))

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
                self.assertEqual(len(result.targets), 4)
                self.assertTrue(all(t.country_code is None and t.location["country_code"] is None for t in result.targets))
                self.assertTrue(all(t.request["Region"] == "example-a" and t.request["Zone"] == "example-a-01" for t in result.targets))
                self.assertTrue(all(t.metadata["country_basis"] is None for t in result.targets))
                self.assertEqual(result.gaps[0]["code"], "country_not_verified")
                self.assertEqual(result.counts["uhost_gpu_rows_excluded"], 0)
        inputs = fixture()
        inputs[1]["Zones"][0]["Region"] = "missing"
        self.assertFalse(build_catalog_targets(*inputs).targets)

    def test_missing_display_names_do_not_erase_exact_price_request_locations(self):
        inputs = fixture()
        inputs[0]["Regions"][0].pop("LocalName")
        inputs[1]["Zones"][0].pop("LocalName")
        result = build_catalog_targets(*inputs)
        self.assertEqual(len(result.targets), 4)
        self.assertFalse(result.gaps)
        self.assertTrue(all(t.country_code == "US" and t.region_name is None and t.zone_name is None for t in result.targets))

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
