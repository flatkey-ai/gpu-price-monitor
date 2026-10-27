"""Azure anonymous retail scope, exact allocation, dates and safe pagination."""

from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from gpu_price_monitor.collector import collect_prices
from gpu_price_monitor.providers import azure
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "azure-public-retail.json"
T4 = "Standard_NC4as_T4_v3"
GB200 = "Standard_ND128isr_NDR_GB200_v6"
H100 = "Standard_NC40ads_H100_v5"
A100 = "Standard_NC24ads_A100_v4"
OBSERVED = "2026-10-23T10:00:00+00:00"


def source():
    original = json.loads(FIXTURE.read_text(), parse_float=Decimal)["skus"]
    extra = FIXTURE.with_name("azure-h100-a100-public-retail.json")
    expanded = FIXTURE.with_name("azure-expanded-public-retail.json")
    additional = FIXTURE.with_name("azure-additional-whole-gpu-20261027.json")
    return {**original, **json.loads(extra.read_text(), parse_float=Decimal)["skus"],
            **json.loads(expanded.read_text(), parse_float=Decimal)["skus"],
            **json.loads(additional.read_text(), parse_float=Decimal)["skus"]}


def parse(items=None, arm_sku=T4):
    return azure.parse_items(source()[arm_sku]["Items"] if items is None else items,
                             arm_sku=arm_sku, observed_at=OBSERVED)


def page(items, next_page=None):
    return {"BillingCurrency": "USD", "CustomerEntityType": "Retail", "Count": len(items),
            "Items": items, "NextPageLink": next_page}


class AzureTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0.0
        self.delays = []
        for name, effect in (("monotonic", lambda: self.elapsed), ("sleep", self.advance)):
            replacement = patch.object(azure, name, side_effect=effect)
            replacement.start()
            self.addCleanup(replacement.stop)

    def advance(self, seconds):
        self.delays.append(seconds)
        self.elapsed += seconds

    def test_t4_and_gb200_retail_instance_allocation_region_and_conditions(self):
        t4, gb200 = parse(), parse(arm_sku=GB200)
        self.assertEqual([q["billing_mode"] for q in t4], ["on_demand", "spot"])
        self.assertEqual([q["amount"] for q in t4], ["0.526", "0.149174"])
        self.assertEqual(gb200[0]["instance_price"]["amount"], "108.16")
        self.assertEqual(gb200[0]["amount"], "27.04")
        self.assertEqual((t4[0]["gpu_model"], t4[0]["gpu_count"], t4[0]["vram_gb"]), ("T4", 1, 16))
        self.assertEqual((gb200[0]["gpu_model"], gb200[0]["gpu_count"], gb200[0]["vram_gb"]), ("GB200", 4, 192))
        self.assertEqual(t4[0]["resources"], {"vcpus": 4, "memory_gib": 28})
        self.assertEqual(gb200[0]["resources"], {"vcpus": 128, "memory_gib": 900})
        for q in t4 + gb200:
            self.assertEqual(q["regions"], ["westus3"])
            self.assertEqual(q["zones"], [])
            self.assertEqual(q["geographic_scope"], "regions")
            self.assertNotIn("country_code", q["location"])
            self.assertEqual(q["currency"], "USD")
            self.assertEqual(q["unit"], "gpu_hour")
            self.assertEqual(q["price_basis"], "instance_total_allocated")
            self.assertEqual(q["availability"], "unknown")
            self.assertEqual(q["account_scope"], "public_catalog")
            self.assertEqual(q["conditions"]["product_scope"], "base_vm_without_windows_license")
            self.assertEqual(q["conditions"]["purchase_option"], q["billing_mode"])
            self.assertEqual(q["source_type"], "official_public_api")
            self.assertTrue(q["hardware_source_url"].startswith("https://learn.microsoft.com/"))
            self.assertIsNone(q["effective_until"])
        self.assertEqual(json.loads(json.dumps(t4 + gb200)), t4 + gb200)

    def test_low_priority_is_excluded_instead_of_labeled_spot(self):
        items = source()[T4]["Items"]
        self.assertEqual(len(items), 3)
        self.assertTrue(any(r["meterName"].endswith("Low Priority") for r in items))
        self.assertEqual(len(parse(items)), 2)

    def test_h100_nvl_and_a100_pcie_have_exact_documented_specs_and_base_products(self):
        for sku, model, variant, memory, cpu, ram in ((H100, "H100", "NVL", 94, 40, 320),
                                                     (A100, "A100", "PCIe", 80, 24, 220)):
            quotes = parse(arm_sku=sku)
            self.assertEqual(len(quotes), 2)
            self.assertEqual({q["billing_mode"] for q in quotes}, {"on_demand", "spot"})
            for quote in quotes:
                self.assertEqual((quote["gpu_model"], quote["gpu_variant"], quote["vram_gb"]),
                                 (model, variant, memory))
                self.assertEqual(quote["gpu_count"], 1)
                self.assertEqual(quote["resources"], {"vcpus": cpu, "memory_gib": ram})
                self.assertEqual(quote["amount"], quote["instance_price"]["amount"])
                self.assertNotIn("Windows", quote["azure_meter"]["product_name"])

    def test_expanded_whole_gpu_sizes_preserve_exact_specs_and_independent_retail_totals(self):
        # Values are the Microsoft hardware tables, not formulas based on a
        # GPU name or CPU count. Every input price is a captured public API row.
        cases = (
            ("Standard_NC8as_T4_v3", "T4", 1, 16, 8, 56),
            ("Standard_NC16as_T4_v3", "T4", 1, 16, 16, 110),
            ("Standard_NC64as_T4_v3", "T4", 4, 16, 64, 440),
            ("Standard_NC48ads_A100_v4", "A100", 2, 80, 48, 440),
            ("Standard_NC96ads_A100_v4", "A100", 4, 80, 96, 880),
            ("Standard_NC80adis_H100_v5", "H100", 2, 94, 80, 640),
            ("Standard_ND96asr_v4", "A100", 8, 40, 96, 900),
            ("Standard_ND96amsr_A100_v4", "A100", 8, 80, 96, 1900),
            ("Standard_ND96isr_H100_v5", "H100", 8, 80, 96, 1900),
            ("Standard_ND96isr_MI300X_v5", "MI300X", 8, 192, 96, 1850),
            ("Standard_NV36ads_A10_v5", "A10", 1, 24, 36, 440),
            ("Standard_NV36adms_A10_v5", "A10", 1, 24, 36, 880),
            ("Standard_NV72ads_A10_v5", "A10", 2, 24, 72, 880),
        )
        for sku, model, count, vram, cpu, ram in cases:
            with self.subTest(sku=sku):
                quotes = parse(arm_sku=sku)
                self.assertEqual(len(quotes), 2)
                by_meter = {r["meterId"]: r for r in source()[sku]["Items"]}
                for quote in quotes:
                    self.assertEqual((quote["gpu_model"], quote["gpu_count"], quote["vram_gb"]),
                                     (model, count, vram))
                    self.assertEqual(quote["resources"], {"vcpus": cpu, "memory_gib": ram})
                    raw = by_meter[quote["azure_meter"]["meter_id"]]
                    self.assertEqual(Decimal(quote["instance_price"]["amount"]), raw["retailPrice"])
                    self.assertEqual(Decimal(quote["amount"]) * count, raw["retailPrice"])
                    self.assertEqual(quote["regions"], [raw["armRegionName"]])
                    self.assertEqual(quote["compute_countries"], ["US"])
                    self.assertEqual(quote["gpu_vendor"], "AMD" if model == "MI300X" else "NVIDIA")
                    if model == "A10":
                        self.assertEqual(quote["conditions"]["included_license"], "NVIDIA GRID")
        # The two 36-vCPU A10 sizes have distinct RAM and independently quoted
        # totals. They must never collapse into one GPU-model-only record.
        normal = next(q for q in parse(arm_sku="Standard_NV36ads_A10_v5") if q["billing_mode"] == "on_demand")
        large = next(q for q in parse(arm_sku="Standard_NV36adms_A10_v5") if q["billing_mode"] == "on_demand")
        self.assertNotEqual(normal["raw_sku"], large["raw_sku"])
        self.assertNotEqual(normal["amount"], large["amount"])

    def test_fractional_a10_and_unverified_b200_are_not_fabricated(self):
        for sku in ("Standard_NV6ads_A10_v5", "Standard_NV12ads_A10_v5", "Standard_NV18ads_A10_v5",
                    "Standard_ND_B200_v6", "Standard_ND128isr_GB300_v6", "Standard_ND128isrG5_GB300_v6",
                    "Standard_NC72ds_xl_RTXPRO6000BSE_v6", "Standard_NV12ads_V710_v5"):
            with self.subTest(sku=sku), self.assertRaises(ValueError):
                azure.parse_items([], arm_sku=sku, observed_at=OBSERVED)

    def test_additional_priced_whole_gpu_families_keep_documented_specs_and_raw_rates(self):
        # Hardware values were reviewed in the exact Microsoft size tables.
        # Tariffs are reduced real retail rows captured 2026-10-27, not prices
        # calculated from another size or provider.
        cases = (
            ("Standard_ND96isr_H200_v5", "H200", None, "NVIDIA", 8, 141, 96, 1850),
            ("Standard_NCC40ads_H100_v5", "H100", "NVL", "NVIDIA", 1, 94, 40, 320),
            ("Standard_ND40rs_v2", "V100", "NVLink", "NVIDIA", 8, 32, 40, 672),
            ("Standard_NC144ds_xl_RTXPRO6000BSE_v6", "RTX PRO 6000", "Blackwell Server Edition", "NVIDIA", 1, 96, 144, 516),
            ("Standard_NC288ds_xl_RTXPRO6000BSE_v6", "RTX PRO 6000", "Blackwell Server Edition", "NVIDIA", 2, 96, 288, 1032),
            ("Standard_NC144lds_xl_RTXPRO6000BSE_v6", "RTX PRO 6000", "Blackwell Server Edition", "NVIDIA", 1, 96, 144, 264),
            ("Standard_NC288lds_xl_RTXPRO6000BSE_v6", "RTX PRO 6000", "Blackwell Server Edition", "NVIDIA", 2, 96, 288, 516),
            ("Standard_NV24ads_V710_v5", "RADEON PRO V710", None, "AMD", 1, 24, 24, 128),
            ("Standard_NV28adms_V710_v5", "RADEON PRO V710", None, "AMD", 1, 24, 28, 160),
        )
        for sku, model, variant, vendor, count, memory, cpu, ram in cases:
            with self.subTest(sku=sku):
                quotes = parse(arm_sku=sku)
                self.assertEqual({q["billing_mode"] for q in quotes}, {"on_demand", "spot"})
                self.assertEqual(len(quotes), 2)
                by_meter = {row["meterId"]: row for row in source()[sku]["Items"]}
                for quote in quotes:
                    self.assertEqual((quote["gpu_model"], quote["gpu_variant"], quote["gpu_vendor"],
                                      quote["gpu_count"], quote["vram_gb"]), (model, variant, vendor, count, memory))
                    self.assertEqual(quote["resources"], {"vcpus": cpu, "memory_gib": ram})
                    original = by_meter[quote["azure_meter"]["meter_id"]]
                    self.assertEqual(Decimal(quote["instance_price"]["amount"]), original["retailPrice"])
                    self.assertEqual(Decimal(quote["amount"]) * count, original["retailPrice"])
                    self.assertEqual(quote["regions"], [original["armRegionName"]])
                    self.assertEqual(quote["availability"], "unknown")
                    self.assertEqual(quote["conditions"].get("confidential_vm"), True if sku.startswith("Standard_NCC") else None)
        h200 = next(q for q in parse(arm_sku=cases[0][0]) if q["billing_mode"] == "on_demand")
        self.assertEqual(h200["amount"], "15.37")
        # Same GPU and CPU, different RAM: preserve separate instance SKUs.
        normal = parse(arm_sku="Standard_NC144ds_xl_RTXPRO6000BSE_v6")[0]
        optimized = parse(arm_sku="Standard_NC144lds_xl_RTXPRO6000BSE_v6")[0]
        self.assertNotEqual(normal["raw_sku"], optimized["raw_sku"])
        self.assertNotEqual(normal["resources"], optimized["resources"])

    def test_countries_use_only_explicit_official_region_directory_mapping(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        for region, countries in (("westus3", ["US"]), ("westeurope", ["NL"]),
                                  ("northeurope", ["IE"]), ("southeastasia", ["SG"]),
                                  ("eastasia", ["HK"])):
            quote = parse([{**base, "armRegionName": region}])[0]
            self.assertEqual(quote["compute_countries"], countries)
            self.assertEqual(quote["location_source"]["url"], azure.REGIONS_DOCUMENTATION_URL)
            self.assertEqual(quote["location_source"]["verified_on"], "2026-10-21")
            self.assertEqual(quote["regions"], [region])
            self.assertEqual(quote["zones"], [])

    def test_additional_country_mappings_keep_region_specific_official_evidence(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        expected = (
            ("attatlanta1", "US", azure.MEC_REGIONS_DOCUMENTATION_URL, "Edge Zone ID"),
            ("attdallas1", "US", azure.MEC_REGIONS_DOCUMENTATION_URL, "Edge Zone ID"),
            ("jioindiacentral", "IN", azure.SENTINEL_GEOGRAPHY_DOCUMENTATION_URL, "SIEM supported region"),
            ("jioindiawest", "IN", azure.SENTINEL_GEOGRAPHY_DOCUMENTATION_URL, "SIEM supported region"),
            ("usgovarizona", "US", azure.GOVERNMENT_REGIONS_DOCUMENTATION_URL, "Programmatic name"),
            ("usgovvirginia", "US", azure.GOVERNMENT_REGIONS_DOCUMENTATION_URL, "Programmatic name"),
        )
        original = parse([base])[0]
        for region, country, url, field in expected:
            with self.subTest(region=region):
                # The country depends on the exact official identifier, never the
                # untrusted retail display name or a name-prefix heuristic.
                quote = parse([{**base, "armRegionName": region, "location": "Untrusted display name"}])[0]
                self.assertEqual(quote["compute_countries"], [country])
                self.assertEqual(quote["location_source"]["url"], url)
                self.assertEqual(quote["location_source"]["verified_on"], "2026-10-21")
                self.assertEqual(quote["location_source"]["region_field"], field)
                self.assertEqual(quote["regions"], [region])
                for key in ("amount", "instance_price", "raw_sku", "gpu_model", "gpu_count",
                            "billing_mode", "conditions", "availability", "source_url"):
                    self.assertEqual(quote[key], original[key])
                if region.startswith("jio"):
                    self.assertEqual(quote["location_source"]["region_name_source_url"],
                                     azure.REGION_NAMES_DOCUMENTATION_URL)
                if region.startswith("att"):
                    self.assertIs(quote["location_source"]["archived"], True)
                    self.assertEqual(quote["location_source"]["physical_location_source_url"],
                                     azure.MEC_LOCATIONS_DOCUMENTATION_URL)

    def test_unverified_regions_keep_unknown_country_and_no_verified_evidence(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        for region in ("unmappedregion", "sgxsingapore1", "attatlanta99", "jioindiafuture", "usgovfuture"):
            with self.subTest(region=region):
                quote = parse([{**base, "armRegionName": region, "location": "US Gov Virginia"}])[0]
                self.assertEqual(quote["compute_countries"], [])
                self.assertIsNone(quote["location_source"]["url"])
                self.assertIsNone(quote["location_source"]["verified_on"])
                self.assertEqual(quote["location_source"]["country_basis"], "unverified_region")

    def test_eastus3_country_uses_microsoft_explicit_geography_list(self):
        row = next(r for r in source()["Standard_NC144ds_xl_RTXPRO6000BSE_v6"]["Items"]
                   if r["meterName"] == "NC144dsxlRTX6kv6")
        quote = parse([{**row, "armRegionName": "eastus3"}], arm_sku=row["armSkuName"])[0]
        self.assertEqual(quote["regions"], ["eastus3"])
        self.assertEqual(quote["compute_countries"], ["US"])
        self.assertEqual(quote["location_source"]["url"], azure.PIPELINES_GEOGRAPHY_DOCUMENTATION_URL)
        self.assertEqual(quote["location_source"]["region_field"], "USGeographyRegions")
        self.assertEqual(quote["location_source"]["verified_on"], "2026-10-27")

    def test_country_filter_uses_verified_mappings_and_preserves_unknown_failure(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        quotes = [parse([{**base, "armRegionName": region}])[0]
                  for region in ("jioindiacentral", "usgovvirginia", "sgxsingapore1")]
        with patch.object(azure, "collect_quotes", return_value=quotes[:2]):
            result = collect_prices(["azure"], {"compute_countries": ["IN"]}, settings=Settings())
        self.assertEqual([q["regions"] for q in result["prices"]], [["jioindiacentral"]])
        self.assertEqual(result["provider_results"][0]["filters"]["compute_countries"]["status"], "applied_locally")
        with patch.object(azure, "collect_quotes", return_value=quotes):
            result = collect_prices(["azure"], {"compute_countries": ["US"]}, settings=Settings())
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["error"]["code"], "unverifiable_filter")
        self.assertEqual(result["provider_results"][0]["filters"]["compute_countries"]["status"], "unverifiable")
        # An explicit region constraint can remove the unrelated unknown quote
        # before checking whether the requested country can be verified.
        with patch.object(azure, "collect_quotes", return_value=quotes):
            result = collect_prices(["azure"], {"compute_countries": ["US"], "regions": ["usgovvirginia"]},
                                    settings=Settings())
        self.assertEqual([q["regions"] for q in result["prices"]], [["usgovvirginia"]])

    def test_current_revision_wins_older_and_future_rates_do_not_become_current(self):
        row = deepcopy(next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3"))
        old, current, future = deepcopy(row), deepcopy(row), deepcopy(row)
        old.update(effectiveStartDate="2020-01-01T00:00:00Z", retailPrice=Decimal("1.5"), unitPrice=Decimal("1.5"))
        current.update(effectiveStartDate="2026-01-01T00:00:00Z", retailPrice=Decimal("0.6"), unitPrice=Decimal("0.6"))
        future.update(effectiveStartDate="2030-01-01T00:00:00Z", retailPrice=Decimal("0.01"), unitPrice=Decimal("0.01"))
        quotes = parse([future, current, old, row])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["amount"], "0.6")
        self.assertEqual(quotes[0]["effective_from"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(parse([future]), [])

    def test_gb200_allocation_is_exact_under_callers_restricted_decimal_context(self):
        items = source()[GB200]["Items"]
        for item in items:
            item["retailPrice"] = item["unitPrice"] = Decimal("1.000000000000000000000000000001")
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.traps[Inexact] = True
            quotes = parse(items, arm_sku=GB200)
        self.assertEqual(quotes[0]["amount"], "0.25000000000000000000000000000025")

    def test_scope_unit_zero_tier_price_date_and_region_drift_fail_closed(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        changes = (
            {"productName": "Virtual Machines NCasT4 v3 Series Windows"},
            {"productName": "Virtual Machines NCasT4 v3 Series Red Hat"},
            {"armSkuName": GB200}, {"type": "Reservation"}, {"type": "DevTestConsumption"},
            {"serviceName": "Storage"}, {"serviceFamily": "Storage"}, {"currencyCode": "EUR"},
            {"isPrimaryMeterRegion": False}, {"isPrimaryMeterRegion": 1},
            {"unitOfMeasure": "100 Hours"}, {"tierMinimumUnits": 10}, {"tierMinimumUnits": True},
            {"retailPrice": 0}, {"retailPrice": -1}, {"retailPrice": "0.526"}, {"retailPrice": 0.526},
            {"retailPrice": Decimal("NaN")}, {"retailPrice": Decimal("1e1000000")},
            {"retailPrice": Decimal("1e-1000000")}, {"unitPrice": Decimal("0.527")},
            {"effectiveStartDate": "2026-01-01"}, {"effectiveStartDate": "2026-01-01T00:00:00"},
            {"effectiveStartDate": "invalid-date"}, {"effectiveStartDate": None},
            {"armRegionName": ""}, {"armRegionName": "global" + "x" * 80},
            {"armRegionName": "US West 3"}, {"reservationTerm": "1 Year"},
            {"skuName": "NC4as T4 v3 Spot"}, {"meterName": "NC4as T4 v3 unknown"},
            {"meterId": "private-test\nunsafe"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse([{**base, **change}])

    def test_duplicate_and_conflicting_current_meters_are_rejected(self):
        base = next(r for r in source()[T4]["Items"] if r["meterName"] == "NC4as T4 v3")
        for duplicate in (deepcopy(base), {**base, "meterId": "other-public-meter"}):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                parse([base, duplicate])

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_collection_is_twenty_six_fixed_anonymous_get_queries(self, request):
        pages = source()
        def respond(url, settings, **kwargs):
            self.assertEqual(kwargs, {"authenticated": False})
            self.assertEqual(settings.max_retries, 0)
            self.assertLessEqual(settings.timeout_seconds, 30)
            self.assertEqual(urlsplit(url).netloc, "prices.azure.com")
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["currencyCode"], ["USD"])
            self.assertEqual(query["meterRegion"], ["'primary'"])
            self.assertEqual(query["api-version"], [azure.API_VERSION])
            self.assertNotIn("api_key", query)
            sku = next(s for s in pages if "armSkuName eq '" + s + "'" in query["$filter"][0])
            self.assertIn("priceType eq 'Consumption'", query["$filter"][0])
            self.assertIn("productName eq '", query["$filter"][0])
            self.assertNotIn("Windows", query["$filter"][0])
            return pages[sku]
        request.side_effect = respond
        settings = Settings(lambda_api_key="unused-private-test-key")
        result = azure.collect_quotes(settings=settings, observed_at=OBSERVED)
        self.assertEqual(request.call_count, 26)
        self.assertEqual(len(result), 52)
        self.assertEqual({q["raw_sku"] for q in result}, set(pages))
        self.assertNotIn("unused-private-test-key", json.dumps(result))
        self.assertEqual(self.delays, [1.0] * 25)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_default_http_timeout_does_not_become_the_whole_collection_budget(self, request):
        pages = source()
        def respond(url, settings, **kwargs):
            self.assertEqual(settings.timeout_seconds, 30)
            # Simulate a one-second response for every SKU. Together with the
            # 25 inter-SKU waits, the batch legitimately takes >30 seconds.
            self.elapsed += 1
            return next(pages[sku] for sku in pages if url == azure.query_url(sku))
        request.side_effect = respond
        result = azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(len(result), 52)
        self.assertEqual(self.elapsed, 51)
        self.assertEqual(request.call_count, 26)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_rate_limit_cools_down_and_retries_only_failed_page_without_replaying_successful_skus(self, request):
        pages = source()
        items = pages[GB200]["Items"]
        retry_url = azure.query_url(GB200, skip=1)
        request.side_effect = [pages[T4], page(items[:1], retry_url),
                               FetchError("rate_limited", "HTTP 429", True),
                               FetchError("rate_limited", "HTTP 429", True),
                               page(items[1:]), pages[H100]]
        with patch.object(azure, "_SPECS", {sku: azure._SPECS[sku] for sku in (T4, GB200, H100)}):
            result = azure.collect_quotes(settings=Settings(max_retries=5), observed_at=OBSERVED)
        self.assertEqual([call.args[0] for call in request.call_args_list],
                         [azure.query_url(T4), azure.query_url(GB200), retry_url, retry_url,
                          retry_url, azure.query_url(H100)])
        self.assertEqual(self.delays, [1.0, 60.0, 60.0, 1.0])
        self.assertEqual(len(result), 6)
        self.assertEqual(len({(q["raw_sku"], q["billing_mode"]) for q in result}), 6)
        self.assertTrue(all(call.args[1].max_retries == 0 for call in request.call_args_list))

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_rate_limit_retries_are_capped_and_respect_disabled_caller_retries(self, request):
        for configured_retries, calls, waits in ((5, 3, [60.0, 60.0]), (0, 1, [])):
            with self.subTest(configured_retries=configured_retries):
                self.elapsed, self.delays = 0.0, []
                request.reset_mock()
                request.side_effect = FetchError("rate_limited", "HTTP 429", True)
                with self.assertRaises(FetchError) as captured:
                    azure._fetch_items(T4, Settings(max_retries=configured_retries))
                self.assertEqual(captured.exception.code, "rate_limited")
                self.assertEqual(request.call_count, calls)
                self.assertEqual(self.delays, waits)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_short_batch_budget_does_not_shorten_cooldown_or_return_partial_catalog(self, request):
        pages = source()
        request.side_effect = [pages[T4], FetchError("rate_limited", "HTTP 429", True)]
        with patch.object(azure, "_SPECS", {sku: azure._SPECS[sku] for sku in (T4, GB200)}):
            with self.assertRaises(FetchError) as captured:
                azure.collect_quotes(settings=Settings(), observed_at=OBSERVED, budget_seconds=61)
        self.assertEqual(captured.exception.code, "timeout")
        self.assertTrue(captured.exception.retryable)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.delays, [1.0])

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_http_timeout_is_capped_by_explicit_remaining_batch_budget(self, request):
        request.return_value = source()[T4]
        with patch.object(azure, "_SPECS", {T4: azure._SPECS[T4]}):
            result = azure.collect_quotes(settings=Settings(), observed_at=OBSERVED, budget_seconds=5)
        self.assertEqual(len(result), 2)
        self.assertEqual(request.call_args.args[1].timeout_seconds, 5)
        self.assertEqual(request.call_args.args[1].max_retries, 0)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_budget_failure_remains_provider_failure_for_snapshot_hold(self, request):
        pages = source()
        def respond(url, settings, **kwargs):
            if url == azure.query_url(T4):
                return pages[T4]
            self.elapsed = azure.MAX_COLLECTION_SECONDS
            return pages[GB200]
        request.side_effect = respond
        result = collect_prices(["azure"], settings=Settings())
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["provider_results"][0]["status"], "failed")
        self.assertEqual(result["provider_results"][0]["error"]["code"], "timeout")
        self.assertEqual(request.call_count, 2)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_network_retries_keep_short_backoff_and_http_timeout_without_hidden_transport_retries(self, request):
        request.side_effect = [FetchError("timeout", "timeout", True),
                               FetchError("network_error", "network", True), source()[T4]]
        result = azure._fetch_items(T4, Settings(timeout_seconds=5, max_retries=2))
        self.assertEqual(result, source()[T4]["Items"])
        self.assertEqual(self.delays, [1, 2])
        self.assertEqual(request.call_count, 3)
        for call in request.call_args_list:
            self.assertEqual(call.args[1].max_retries, 0)
            self.assertEqual(call.args[1].timeout_seconds, 5)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_schema_and_price_failures_are_not_retried_after_cooldown(self, request):
        request.side_effect = [FetchError("rate_limited", "HTTP 429", True),
                               {**source()[T4], "Count": True}]
        with self.assertRaises(FetchError) as captured:
            azure._fetch_items(T4, Settings())
        self.assertEqual(captured.exception.code, "invalid_public_catalog")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.delays, [60.0])
        self.elapsed, self.delays = 0.0, []
        request.reset_mock()
        invalid = deepcopy(source()[T4])
        invalid["Items"][0]["retailPrice"] = -1
        request.side_effect = None
        request.return_value = invalid
        with self.assertRaises(ValueError):
            azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.delays, [])

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_invalid_batch_budgets_fail_before_network_or_sleep(self, request):
        for value in (0, -1, 301, 10 ** 400, True, "60", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(FetchError) as captured:
                azure.collect_quotes(settings=Settings(), observed_at=OBSERVED, budget_seconds=value)
            self.assertEqual(captured.exception.code, "invalid_request")
        request.assert_not_called()
        self.assertEqual(self.delays, [])

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_contiguous_pagination_finishes_before_parsing_and_preserves_fixed_scope(self, request):
        pages = source()
        items = pages[T4]["Items"]
        # The documented continuation may omit non-filter query parameters;
        # the collector reinstates its own fixed version, currency and scope.
        continuation = "https://prices.azure.com:443/api/retail/prices?" + urlencode({
            "$filter": parse_qs(urlsplit(azure.query_url(T4)).query)["$filter"][0], "$skip": "1",
        })
        request.side_effect = [page(items[:1], continuation), page(items[1:]),
                               *(pages[sku] for sku in azure._SPECS if sku != T4)]
        result = azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(len(result), 52)
        self.assertEqual(request.call_count, 27)
        self.assertEqual(request.call_args_list[1].args[0], azure.query_url(T4, skip=1))

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_external_or_changed_continuations_are_never_requested(self, request):
        one = source()[T4]["Items"][:1]
        valid = azure.query_url(T4, skip=1)
        changed = (
            valid.replace("https://prices.azure.com", "https://example.invalid"),
            valid.replace("https://", "http://"), valid.replace("prices.azure.com", "user@prices.azure.com"),
            valid.replace("prices.azure.com", "prices.azure.com:444"), valid.replace("/api/retail/prices", "/other"),
            valid + "#fragment", valid.split("?", 1)[1], valid.replace("%24skip=1", "%24skip=0"),
            valid.replace("%24skip=1", "%24skip=6000"), valid + "&api_key=test-untrusted",
            valid.replace("%24filter=", "different="), valid.replace("Standard_NC4as_T4_v3", "Standard_other"),
            valid + "&%24skip=2", valid.replace("currencyCode=USD", "currencyCode=EUR"),
            valid.replace("api-version=" + azure.API_VERSION, "api-version=other"), "",
        )
        for continuation in changed:
            request.reset_mock()
            request.return_value = page(one, continuation)
            with self.subTest(continuation=continuation), self.assertRaises(FetchError) as captured:
                azure._fetch_items(T4, Settings())
            self.assertEqual(captured.exception.code, "invalid_pagination")
            self.assertEqual(request.call_count, 1)

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_bad_counts_missing_continuation_and_incomplete_pages_fail(self, request):
        first = page(source()[T4]["Items"][:1])
        mutations = ({**first, "Count": 2}, {**first, "Count": True}, {**first, "Items": {}},
                     {**first, "BillingCurrency": "EUR"}, {**first, "CustomerEntityType": "Other"},
                     {key: value for key, value in first.items() if key != "NextPageLink"})
        for payload in mutations:
            request.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(FetchError) as captured:
                azure._fetch_items(T4, Settings())
            self.assertEqual(captured.exception.code, "invalid_public_catalog")
        request.return_value = page(first["Items"], azure.query_url(T4, skip=2))
        with self.assertRaises(FetchError) as captured:
            azure._fetch_items(T4, Settings())
        self.assertEqual(captured.exception.code, "invalid_pagination")

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_pagination_limit_and_repeated_offsets_do_not_return_partial_data(self, request):
        items = source()[T4]["Items"][:1]
        request.side_effect = [page(items, azure.query_url(T4, skip=1)), page(items, azure.query_url(T4, skip=2))]
        with patch.object(azure, "MAX_PAGES_PER_SKU", 2), self.assertRaises(FetchError) as captured:
            azure._fetch_items(T4, Settings())
        self.assertEqual(captured.exception.code, "pagination_limit")
        request.side_effect = [page(items, azure.query_url(T4, skip=1))] * 2
        with self.assertRaises(FetchError) as captured:
            azure._fetch_items(T4, Settings())
        self.assertEqual(captured.exception.code, "invalid_pagination")

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_empty_current_sku_and_provider_errors_have_safe_diagnostics(self, request):
        request.return_value = page([])
        with self.assertRaises(FetchError) as captured:
            azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "empty_public_catalog")
        request.return_value = {"Message": "private-test-provider-response"}
        with self.assertRaises(FetchError) as captured:
            azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertNotIn("private-test-provider-response", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
