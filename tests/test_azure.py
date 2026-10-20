"""Azure anonymous retail scope, exact allocation, dates and safe pagination."""

from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from gpu_price_monitor.providers import azure
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "azure-public-retail.json"
T4 = "Standard_NC4as_T4_v3"
GB200 = "Standard_ND128isr_NDR_GB200_v6"
OBSERVED = "2026-10-20T10:00:00+00:00"


def source():
    return json.loads(FIXTURE.read_text(), parse_float=Decimal)["skus"]


def parse(items=None, arm_sku=T4):
    return azure.parse_items(source()[arm_sku]["Items"] if items is None else items,
                             arm_sku=arm_sku, observed_at=OBSERVED)


def page(items, next_page=None):
    return {"BillingCurrency": "USD", "CustomerEntityType": "Retail", "Count": len(items),
            "Items": items, "NextPageLink": next_page}


class AzureTests(unittest.TestCase):
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
    def test_collection_is_two_fixed_anonymous_get_queries(self, request):
        pages = source()
        def respond(url, settings, **kwargs):
            self.assertEqual(kwargs, {"authenticated": False})
            self.assertEqual(urlsplit(url).netloc, "prices.azure.com")
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["currencyCode"], ["USD"])
            self.assertEqual(query["meterRegion"], ["'primary'"])
            self.assertEqual(query["api-version"], [azure.API_VERSION])
            self.assertNotIn("api_key", query)
            sku = T4 if T4 in query["$filter"][0] else GB200
            self.assertIn("priceType eq 'Consumption'", query["$filter"][0])
            self.assertIn("productName eq '", query["$filter"][0])
            self.assertNotIn("Windows", query["$filter"][0])
            return pages[sku]
        request.side_effect = respond
        settings = Settings(lambda_api_key="unused-private-test-key")
        result = azure.collect_quotes(settings=settings, observed_at=OBSERVED)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result), 4)
        self.assertNotIn("unused-private-test-key", json.dumps(result))

    @patch("gpu_price_monitor.providers.azure.request_json")
    def test_contiguous_pagination_finishes_before_parsing_and_preserves_fixed_scope(self, request):
        pages = source()
        items = pages[T4]["Items"]
        # The documented continuation may omit non-filter query parameters;
        # the collector reinstates its own fixed version, currency and scope.
        continuation = "https://prices.azure.com:443/api/retail/prices?" + urlencode({
            "$filter": parse_qs(urlsplit(azure.query_url(T4)).query)["$filter"][0], "$skip": "1",
        })
        request.side_effect = [page(items[:1], continuation), page(items[1:]), pages[GB200]]
        result = azure.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(len(result), 4)
        self.assertEqual(request.call_count, 3)
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
