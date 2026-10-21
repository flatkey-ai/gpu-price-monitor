"""Public document snapshots are test evidence, never runtime price fallbacks."""

from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import nebius_catalog_expanded as expanded
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError


OBSERVED = "2026-10-21T12:00:00+00:00"
H = ("1gpu-16vcpu-200gb", "8gpu-128vcpu-1600gb")
B = ("1gpu-20vcpu-224gb", "8gpu-160vcpu-1792gb")
R = ("1gpu-24vcpu-218gb", "8gpu-192vcpu-1744gb")
PLATFORMS = (
    ("gpu-b300-sxm", "B300", "Intel", ("uk-south1", "eu-west2", "us-north1"), ("1gpu-24vcpu-346gb", "8gpu-192vcpu-2768gb"), 288),
    ("gpu-b200-sxm", "B200", "Intel", ("us-central1",), B, 180),
    ("gpu-b200-sxm-a", "B200", "Intel", ("me-west1",), B, 180),
    ("gpu-rtx6000", "RTX PRO 6000", "Intel", ("us-central1",), R, 96),
    ("gpu-rtx6000-a", "RTX PRO 6000", "Intel", ("uk-south2", "eu-south1"), R, 96),
    ("gpu-h200-sxm", "H200", "Intel", ("eu-north1", "eu-north2", "eu-west1", "us-central1"), H, 141),
    ("gpu-h100-sxm", "H100", "Intel", ("eu-north1",), H, 80),
    ("gpu-l40s-a", "L40S", "Intel", ("eu-north1",), ("1gpu-8vcpu-32gb", "1gpu-16vcpu-64gb", "1gpu-24vcpu-96gb", "1gpu-32vcpu-128gb", "1gpu-40vcpu-160gb"), 48),
    ("gpu-l40s-d", "L40S", "AMD", ("eu-north1",), ("1gpu-16vcpu-96gb", "1gpu-32vcpu-192gb", "1gpu-48vcpu-288gb", "2gpu-64vcpu-384gb", "2gpu-96vcpu-576gb", "4gpu-128vcpu-768gb", "4gpu-192vcpu-1152gb"), 48),
)
REGIONS = """## Public regions
* `eu-north1`: Finland
* `eu-south1`: Madrid, Spain
* `eu-west1`: France
* `eu-west2`: France
* `me-west1`: Israel
* `us-central1`: Kansas City, Missouri, US
* `us-north1`: Woodbury, Minnesota, US
* `uk-south1`: United Kingdom
* `uk-south2`: United Kingdom
## Private regions
* `eu-north2`: Iceland
## Availability
"""


def table(columns, rows):
    return "| " + " | ".join(columns) + " |\n| " + " | ".join("-" for _ in columns) + " |\n" + "\n".join(
        "| " + " | ".join(map(str, row)) + " |" for row in rows) + "\n"


def types():
    text = table(("Platform name", "Platform ID", "CPU", "Regions"), [
        ("NVIDIA " + model + " with " + cpu, identity, cpu, ", ".join("`" + r + "`" for r in regions))
        for identity, model, cpu, regions, presets, memory in PLATFORMS])
    gpu_rows = []
    for model in dict.fromkeys(row[1] for row in PLATFORMS):
        matching = [row for row in PLATFORMS if row[1] == model]
        gpu_rows.append(("NVIDIA " + model, "Architecture", "PCIe" if model in ("L40S", "RTX PRO 6000") else "SXM",
                         str(matching[0][-1]) + " GB HBM", "bandwidth", "interconnect", "network",
                         ", ".join(row[0] for row in matching), matching[0][2]))
    text += "\n## GPU types\n" + table(("GPU", "Architecture", "Form factor", "GPU memory", "Memory bandwidth", "InfiniBand interconnect", "Network adapter", "Platform", "CPU"), gpu_rows)
    text += "\n## Presets for GPU platforms\n"
    for identity, model, cpu, regions, presets, memory in PLATFORMS:
        text += "\n* NVIDIA " + model + " (`" + identity + "`):\n\n"
        rows = []
        for preset in presets:
            match = expanded._PRESET.fullmatch(preset)
            rows.append(("`" + preset + "`", *match.groups()))
        text += table(("Preset name", "Number of GPUs", "Number of vCPUs", "RAM, GiB"), rows)
    return text + "\n### Presets compatible with GPU clusters\n"


def pricing():
    text = "Prices in US dollars (USD, $) apply to all customers except for companies from Israel. All prices are shown without any applicable taxes.\n### Virtual machines (GPUs, vCPUs, RAM)\n"
    ordinary = {"B300": ("9.50", "29.45"), "B200": ("8.50", "26.35"), "RTX PRO 6000": ("1.80", "5.58"),
                "H200": ("5.40", "16.74"), "H100": ("4.50", "13.95")}
    for identity, model, cpu, regions, presets, memory in PLATFORMS:
        text += "\n#### NVIDIA " + model + (" " + cpu if model == "L40S" else "") + ", " + identity + "\n"
        text += "The platform is available in " + ", ".join("`" + r + "`" for r in regions) + ".\n"
        for index, currency, symbol in ((0, "USD", "$"), (1, "ILS", "₪")):
            text += "\n**" + currency + "**\n\n"
            if model == "L40S":
                amounts = (("1.35", "0.012" if cpu == "Intel" else "0.01", "0.0032", "0.65", "0.006" if cpu == "Intel" else "0.005", "0.0016")
                           if currency == "USD" else ("4.185", "0.0372" if cpu == "Intel" else "0.031", "0.00992", "2.015", "0.0186" if cpu == "Intel" else "0.0155", "0.00496"))
                rows = [(f"NVIDIA L40S {cpu}. {resource}", symbol + amount, unit)
                        for resource, amount, unit in zip(("GPU", "CPU", "RAM"), amounts[:3], ("1 GPU hour", "1 CPU hour", "1 GiB hour"))]
                rows += [(f"Preemptible NVIDIA L40S {cpu}. {resource}", symbol + amount, unit)
                         for resource, amount, unit in zip(("GPU", "CPU", "RAM"), amounts[3:], ("1 GPU hour", "1 CPU hour", "1 GiB hour"))]
            else:
                rows = [("NVIDIA " + model, symbol + ordinary[model][index], "1 GPU hour"),
                        ("Preemptible NVIDIA " + model, "From " + symbol + ("0.99" if currency == "USD" else "3.069"), "1 GPU hour")]
            text += table(("Item", "Price", "Per"), rows)
    return text + "\n### Volumes\n"


def catalog():
    return expanded.calculate_catalog(pricing(), types(), REGIONS, observed_at=OBSERVED)


def spot(region="us-central1"):
    return {"provider": "nebius", "product_type": "gpu_instance", "gpu_model": "B200", "raw_sku": "gpu-b200-sxm",
            "gpu_count": None, "amount": "1.90", "currency": "USD", "unit": "gpu_hour", "billing_mode": "spot",
            "quote_status": "quoted", "source_type": "official_public_api", "regions": [region], "zones": [],
            "compute_countries": ["US"], "source_url": nebius_spot_url(), "source_snapshot_at": OBSERVED,
            "observed_at": OBSERVED, "effective_from": "2026-10-21T11:45:00Z"}


def nebius_spot_url():
    return "https://api.nebius.cloud/billing/v1alpha1/spot-price"


class ExpandedNebiusTests(unittest.TestCase):
    def test_all_platforms_presets_currencies_and_fixed_spot_are_calculated(self):
        data = catalog()
        self.assertEqual(len(data["platforms"]), 9)
        self.assertEqual(sum(len(p["presets"]) for p in data["platforms"].values()), 26)
        self.assertEqual(len(data["prices"]), 76)
        self.assertEqual(len(data["published_minimums"]), 14)
        self.assertEqual({q["currency"] for q in data["prices"]}, {"USD", "ILS"})
        self.assertEqual(sum(q["billing_mode"] == "on_demand" for q in data["prices"]), 52)
        self.assertTrue(all(q["gpu_model"] == "L40S" for q in data["prices"] if q["billing_mode"] == "spot"))
        self.assertEqual(sum(len(r["rows"]) for r in data["source_rate_groups"]), 38)

    def test_l40s_components_use_instance_vcpu_and_gib_not_gpu_rate_alone(self):
        prices = catalog()["prices"]
        q = next(q for q in prices if q["raw_sku"] == "gpu-l40s-a" and q["selected_configuration"]["preset"] == "1gpu-8vcpu-32gb"
                 and q["currency"] == "USD" and q["billing_mode"] == "on_demand")
        self.assertEqual(q["amount"], "1.5484")
        self.assertEqual(q["instance_price"]["amount"], "1.5484")
        self.assertEqual([r["quantity"] for r in q["components"]], [1, 8, 32])
        self.assertEqual(q["components"][2]["unit"], "gib_hour")
        self.assertEqual(q["rate_derivation"]["method"], "computed_from_official_tariff")
        self.assertFalse(q["rate_derivation"]["independent_provider_quote"])
        q = next(q for q in prices if q["raw_sku"] == "gpu-l40s-d" and q["selected_configuration"]["preset"] == "2gpu-64vcpu-384gb"
                 and q["currency"] == "USD" and q["billing_mode"] == "on_demand")
        self.assertEqual(q["amount"], "2.2844")
        self.assertEqual(q["instance_price"]["amount"], "4.5688")
        self.assertEqual(sum(Decimal(row["amount"]) for row in q["components"]), Decimal("4.5688"))

    def test_document_coverage_never_becomes_regional_price_or_billing_country(self):
        prices = catalog()["prices"]
        self.assertTrue(all(q["regions"] == [] and q["compute_countries"] == [] for q in prices))
        self.assertTrue(all(q["region_price_verified"] is False and q["price_scope"] == "platform_coverage" for q in prices))
        b200 = next(q for q in prices if q["raw_sku"] == "gpu-b200-sxm-a" and q["currency"] == "USD")
        self.assertEqual(b200["coverage_regions"], ["me-west1"])
        self.assertEqual(b200["coverage_countries"], ["IL"])
        self.assertIn("USD适用于以色列公司以外客户", " ".join(b200["conditions"]))
        h200 = next(q for q in prices if q["gpu_model"] == "H200")
        self.assertIn("私有地区", " ".join(h200["conditions"]))

    def test_presets_quantities_units_and_country_evidence_are_required(self):
        for changed_types, changed_regions in ((types().replace("| 1 | 20 | 224 |", "| 8 | 20 | 224 |", 1), REGIONS),
                                                (types().replace("RAM, GiB", "RAM, GB"), REGIONS),
                                                (types(), REGIONS.replace("Finland", "Unknownland"))):
            with self.subTest(), self.assertRaises(ValueError):
                expanded.calculate_catalog(pricing(), changed_types, changed_regions, observed_at=OBSERVED)
        with self.assertRaises(ValueError):
            expanded.calculate_catalog(pricing().replace("1 CPU hour", "1 CPU month", 1), types(), REGIONS, observed_at=OBSERVED)

    def test_live_spot_binds_only_original_region_platform_and_preserves_time(self):
        original = spot()
        before = deepcopy(original)
        quotes, excluded = expanded.expand_spot([original], catalog())
        self.assertEqual(excluded, [])
        self.assertEqual([q["gpu_count"] for q in quotes], [1, 8])
        self.assertEqual([q["instance_price"]["amount"] for q in quotes], ["1.90", "15.20"])
        self.assertEqual({q["amount"] for q in quotes}, {"1.90"})
        self.assertTrue(all(q["regions"] == ["us-central1"] and q["compute_countries"] == ["US"] for q in quotes))
        self.assertTrue(all(q["effective_from"] == original["effective_from"] for q in quotes))
        self.assertEqual(original, before)

    def test_new_spot_region_keeps_api_rate_without_inventing_preset_coverage(self):
        quotes, excluded = expanded.expand_spot([spot("us-north1")], catalog())
        self.assertEqual(len(quotes), 1)
        self.assertIsNone(quotes[0]["gpu_count"])
        self.assertEqual(quotes[0]["regions"], ["us-north1"])
        self.assertEqual(excluded[0]["reason"], "preset_region_not_in_documented_platform_catalog")

    def test_new_spot_platform_preserves_authentic_api_quote_without_assuming_configuration(self):
        supplied = {**spot(), "raw_sku": "gpu-future-sxm", "gpu_model": "FUTURE"}
        quotes, excluded = expanded.expand_spot([supplied], catalog())
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["quote_origin"], "reported_regional_spot_rate")
        self.assertNotIn("selected_configuration", quotes[0])
        self.assertEqual(quotes[0]["amount"], supplied["amount"])
        self.assertEqual(excluded[0]["reason"], "platform_not_in_documented_preset_catalog")
        with self.assertRaises(ValueError):
            expanded.expand_spot([{**supplied, "unit": "gpu_month"}], catalog())

    def test_partial_spot_error_keeps_tariff_calculations_and_contact_rows(self):
        contact = {"provider": "nebius", "gpu_model": "GB300", "raw_name": "NVIDIA GB300 NVL72", "amount": None,
                   "quote_status": "contact_sales", "source_url": "https://nebius.com/prices"}
        with patch.object(expanded, "fetch_text", side_effect=[pricing(), types(), REGIONS]), \
                patch.object(expanded.nebius_spot, "collect_quotes", side_effect=FetchError("http_error", "HTTP 503", True)):
            result = expanded.collect_result(settings=Settings(), observed_at=OBSERVED, website_quotes=[contact])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 77)
        self.assertEqual(result["coverage"]["reported_spot_api_quote_count"], 0)
        self.assertEqual(result["coverage"]["catalog_calculation_count"], 76)
        self.assertEqual(result["coverage"]["contact_sales_row_count"], 1)
        self.assertEqual(result["prices"][-1]["amount"], None)
        self.assertEqual(result["errors"][0]["source"], "regional_spot_api")

    def test_document_failure_preserves_independent_raw_spot_api_and_website_prices(self):
        website = {"provider": "nebius", "gpu_model": "H100", "amount": "4.50", "source_type": "official_website_json",
                   "quote_status": "quoted", "source_url": "https://nebius.com/prices"}
        with patch.object(expanded, "fetch_text", side_effect=FetchError("http_error", "HTTP 503", True)), \
                patch.object(expanded.nebius_spot, "collect_quotes", return_value=[spot()]) as get_spot:
            result = expanded.collect_result(settings=Settings(), observed_at=OBSERVED, website_quotes=[website])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["prices"]), 2)
        self.assertEqual(result["coverage"]["reported_spot_api_quote_count"], 1)
        self.assertEqual(result["coverage"]["unexpanded_spot_api_quote_count"], 1)
        self.assertEqual(result["coverage"]["catalog_calculation_count"], 0)
        self.assertIsNone(result["prices"][0]["gpu_count"])
        self.assertNotIn("instance_price", result["prices"][0])
        self.assertEqual(result["errors"][0]["source"], "public_preset_catalog")
        get_spot.assert_called_once()

    def test_all_failed_sources_are_failed_with_individual_diagnostics(self):
        error = FetchError("http_error", "HTTP 503", True)
        with patch.object(expanded, "fetch_text", side_effect=error), \
                patch.object(expanded.nebius_spot, "collect_quotes", side_effect=error), \
                patch.object(expanded.nebius_catalog, "collect_quotes", side_effect=error):
            result = expanded.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["prices"], [])
        self.assertEqual({e["source"] for e in result["errors"]}, {"public_preset_catalog", "regional_spot_api", "website_catalog"})

    def test_website_failure_does_not_discard_tariffs_or_live_spot(self):
        with patch.object(expanded, "fetch_text", side_effect=[pricing(), types(), REGIONS]) as documents, \
                patch.object(expanded.nebius_spot, "collect_quotes", return_value=[spot()]) as get_spot, \
                patch.object(expanded.nebius_catalog, "collect_quotes", side_effect=FetchError("http_error", "HTTP 503", True)):
            result = expanded.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["catalog_calculation_count"], 76)
        self.assertEqual(result["coverage"]["reported_spot_api_quote_count"], 1)
        self.assertEqual(result["coverage"]["regional_spot_calculation_count"], 2)
        self.assertEqual(result["coverage"]["raw_exact_gpu_rate_count"], 22)
        self.assertEqual(result["coverage"]["raw_exact_resource_rate_count"], 38)
        self.assertEqual(result["errors"][0]["source"], "website_catalog")
        self.assertEqual([c.args[0] for c in documents.call_args_list], [expanded.SOURCE_URL, expanded.TYPES_URL, expanded.REGIONS_URL])
        get_spot.assert_called_once()

    def test_account_targets_require_explicit_real_project_scopes_and_boot_disk(self):
        batches = expanded.build_account_target_batches(catalog(), [
            {"project_id": "project-test-finland", "region": "eu-north1", "country_code": "FI"},
            {"project_id": "project-test-usa", "region": "us-central1", "country_code": "US"},
        ], currency="usd", boot_disk_gib=40, aggregation_units=("hour", "month"))
        self.assertEqual(list(map(len, batches)), [20, 2])
        target = batches[0][0]
        self.assertEqual(target["aggregation_units"], ["hour", "month"])
        self.assertEqual(target["resource_specs"][0]["spec"]["spec"]["bootDisk"]["managedDisk"]["spec"]["sizeGibibytes"], "40")
        with self.assertRaises(ValueError):
            expanded.build_account_target_batches(catalog(), [{"project_id": "project-test", "region": "me-west1", "country_code": "US"}],
                                                   currency="usd", boot_disk_gib=40)

    def test_account_targets_cover_only_caller_authorized_platform_region_presets(self):
        data = catalog()
        projects = [{"project_id": "project-test-" + region, "region": region, "country_code": info["country_code"]}
                    for region, info in data["regions"].items()]
        batches = expanded.build_account_target_batches(data, projects, currency="ils", boot_disk_gib=60, contract=True)
        self.assertEqual(list(map(len, batches)), [20, 18])
        targets = [target for batch in batches for target in batch]
        self.assertEqual(len({(t["region"], t["resource_specs"][0]["spec"]["spec"]["resources"]["platform"],
                              t["resource_specs"][0]["spec"]["spec"]["resources"]["preset"]) for t in targets}), 38)
        self.assertTrue(all(t["currency"] == "ils" and t["aggregation_units"] == ["hour"] for t in targets))
        self.assertTrue(all(t["offer_types"] == ["OFFER_TYPE_CONTRACT_PRICE"] for t in targets))
        self.assertTrue(all(t["project_id"] == "project-test-" + t["region"] for t in targets))


if __name__ == "__main__":
    unittest.main()
