"""Boot/image selection must not silently turn an incompatible target into a quote."""

from copy import deepcopy
from decimal import Decimal
import unittest

from gpu_price_monitor.providers.ucloud_console_catalog import ConsoleQuoteTarget
from gpu_price_monitor.providers.ucloud_console_image import select_image_and_disk


def target(model="5090Pro"):
    return ConsoleQuoteTarget(
        request={"Region": "region-a", "Zone": "region-a-02", "CpuPlatform": "Amd"}, gpu_model=model,
        gpu_count=1, gpu_memory_gb=32, memory_gb=96, cpu_platform_options=["Amd/Epyc5"],
        country_code="CN", region_name="Region A", zone_name="Zone 2", catalog_status="Normal",
        disk_options=[{"Name": "cloudDisk", "BootDisk": [{"Name": "CLOUD_SSD", "InstantResize": True,
                                                          "MaximalSize": 500}]}])


def image(image_id="image-a", **changes):
    row = {"ImageId": image_id, "ImageName": "Linux Base", "OsName": "Linux Base", "OsType": "Linux",
           "ImageType": "Base", "State": "Available", "Zone": "region-a-01", "ImageSize": 20,
           "Features": ["StandardKernel", "RssdAttachable"], "CreateTime": 10}
    row.update(changes)
    return row


def payload(*images):
    return {"RetCode": 0, "ImageSet": list(images), "TotalCount": len(images)}


class UCloudConsoleImageTests(unittest.TestCase):
    def test_minimal_boot_disk_is_source_derived_and_input_not_mutated(self):
        config = target()
        config.disk_options[0]["BootDisk"][0]["MinimalSize"] = 40
        images = payload(image(ImageSize=Decimal("20")))
        before = deepcopy((config, images))
        result = select_image_and_disk(config, images)
        self.assertEqual(result.request, {"ImageId": "image-a", "Disks": [
            {"IsBoot": "True", "Type": "CLOUD_SSD", "Size": 40, "BackupType": "NONE"}]})
        self.assertEqual(result.metadata["image_home_zone"], "region-a-01")
        self.assertEqual(result.metadata["configuration_scope"], "one_compatible_base_linux_image_and_minimal_boot_disk")
        self.assertFalse(result.metadata["image_license_price_verified"])
        self.assertEqual((config, images), before)

    def test_only_available_base_linux_and_correct_region_can_be_selected(self):
        for changes in [{"ImageType": "Business"}, {"ImageType": "Custom"}, {"ImageType": "Shared"},
                        {"OsType": "Windows"}, {"State": "Unavailable"}, {"Zone": "region-b-01"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                select_image_and_disk(target(), payload(image(**changes)))

    def test_normal_gpu_requires_generic_kernel_and_excludes_special_network_arm_vgpu(self):
        for feature in ["NetEnhanced_Extreme", "NetEnhanced_Infiniband", "Aarch64_Type", "Vgpu_AMD", "Vgpu_NVIDIA"]:
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                select_image_and_disk(target(), payload(image(Features=["StandardKernel", feature])))
        with self.assertRaises(ValueError):
            select_image_and_disk(target(), payload(image(Features=["CloudInit"])))

    def test_selected_network_mode_image_requirements_are_enforced(self):
        config = target("V100")
        config.request["NetCapability"] = "Super"
        config.metadata["network_mode_required_image_features"] = ["NetEnhanced"]
        with self.assertRaises(ValueError):
            select_image_and_disk(config, payload(image()))
        selected = select_image_and_disk(config, payload(
            image("compatible", Features=["StandardKernel", "NetEnhanced"])))
        self.assertEqual(selected.request["ImageId"], "compatible")
        for mode, model in [("Extreme", "A800"), ("Infiniband", "H20")]:
            config = target(model)
            config.request["NetCapability"] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                select_image_and_disk(config, payload(image()))

    def test_high_end_gpu_uses_its_official_network_feature(self):
        for model, feature in [("A800", "NetEnhanced_Extreme"), ("H200", "NetEnhanced_Extreme"),
                               ("B200", "NetEnhanced_Extreme"), ("H20", "NetEnhanced_Infiniband"),
                               ("H100", "NetEnhanced_Infiniband"), ("H800", "NetEnhanced_Infiniband"),
                               ("MetaX-C500", "NetEnhanced_Infiniband")]:
            with self.subTest(model=model):
                selected = select_image_and_disk(target(model), payload(image("generic"), image("special", Features=[feature])))
                self.assertEqual(selected.request["ImageId"], "special")
                with self.assertRaises(ValueError):
                    select_image_and_disk(target(model), payload(image()))

    def test_gpu_market_selects_only_explicitly_supported_business_linux(self):
        for model, feature in [("A800", "NetEnhanced_Extreme"),
                               ("H20", "NetEnhanced_Infiniband"),
                               ("H800", "NetEnhanced_Infiniband")]:
            with self.subTest(model=model):
                business = image("gpu-market", ImageType="Business", ImageName="Linux GPU driver",
                                 ImageSize=40, SupportedGPUTypes=[model], Features=[feature])
                selected = select_image_and_disk(target(model), payload(business), gpu_market=True)
                self.assertEqual(selected.request["ImageId"], "gpu-market")
                self.assertEqual(selected.request["Disks"][0]["Size"], 40)
                self.assertEqual(selected.metadata["image_type"], "Business")
                self.assertEqual(selected.metadata["image_name"], "Linux GPU driver")
                self.assertEqual(selected.metadata["image_supported_gpu_types"], [model])
                self.assertEqual(selected.metadata["configuration_scope"],
                                 "one_compatible_gpu_market_linux_image_and_minimal_boot_disk")
                self.assertFalse(selected.metadata["image_license_price_verified"])
                with self.assertRaises(ValueError):
                    select_image_and_disk(target(model), payload(business))
        for changes in [{"ImageType": "Base"}, {"ImageType": "Custom"}, {"ImageType": "Shared"},
                        {"OsType": "Windows"}, {"State": "Unavailable"}, {"Zone": "region-b-01"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                row = image(ImageType="Business", SupportedGPUTypes=["A800"],
                            Features=["NetEnhanced_Extreme"])
                row.update(changes)
                select_image_and_disk(target("A800"), payload(row), gpu_market=True)

    def test_gpu_market_requires_exact_supported_gpu_catalog_membership(self):
        for supported in [None, [], ["A100"], ["A800-compatible"], "A800", ["A800", None]]:
            with self.subTest(supported=supported), self.assertRaises(ValueError):
                row = image(ImageType="Business", SupportedGPUTypes=supported,
                            Features=["NetEnhanced_Extreme"])
                select_image_and_disk(target("A800"), payload(row), gpu_market=True)

    def test_gpu_market_still_requires_compatible_network_features(self):
        for model, features in [("A800", ["StandardKernel", "NetEnhanced_Infiniband"]),
                                ("H20", ["StandardKernel", "NetEnhanced_Extreme"]),
                                ("H800", ["StandardKernel"]),
                                ("A800", ["NetEnhanced_Extreme", "Vgpu_NVIDIA"])]:
            with self.subTest(model=model, features=features), self.assertRaises(ValueError):
                row = image(ImageType="Business", SupportedGPUTypes=[model], Features=features)
                select_image_and_disk(target(model), payload(row), gpu_market=True)

    def test_openclaw_is_excluded_when_compatible_generic_pair_exists(self):
        selected = select_image_and_disk(target(), payload(
            image("openclaw", ImageName="Linux OpenClaw", CreateTime=100), image("generic", ImageSize=40)))
        self.assertEqual(selected.request["ImageId"], "generic")

    def test_disk_limits_and_image_size_fail_closed(self):
        for value in [0, True, -1, 1.5, float("nan")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_image_and_disk(target(), payload(image(ImageSize=value)))
        config = target()
        config.disk_options[0]["BootDisk"][0]["MaximalSize"] = 10
        with self.assertRaises(ValueError):
            select_image_and_disk(config, payload(image()))
        config = target()
        config.disk_options[0]["BootDisk"][0]["Name"] = "CLOUD_RSSD"
        with self.assertRaises(ValueError):
            select_image_and_disk(config, payload(image(Features=["StandardKernel"])))

    def test_incomplete_catalog_and_ambiguous_image_id_are_rejected(self):
        data = payload(image())
        data["TotalCount"] = 10
        with self.assertRaises(ValueError):
            select_image_and_disk(target(), data)
        with self.assertRaises(ValueError):
            select_image_and_disk(target(), payload(image(), image(ImageSize=40)))

    def test_deterministic_selection_prioritizes_size_then_current_image(self):
        rows = [image("large", ImageSize=40, CreateTime=100), image("older", CreateTime=20),
                image("newer", CreateTime=30)]
        first = select_image_and_disk(target(), payload(*rows))
        second = select_image_and_disk(target(), payload(*reversed(rows)))
        self.assertEqual(first.request, second.request)
        self.assertEqual(first.request["ImageId"], "newer")


if __name__ == "__main__":
    unittest.main()
