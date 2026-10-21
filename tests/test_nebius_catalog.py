"""Fixed-structure website JSON collection, without HTML price interpretation."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import nebius_catalog
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-21T11:00:00+00:00"
ENDPOINT = "https://nebius.com/_next/data/test-build-v2/en/prices.json"


def block():
    # Minimal public page-data projection captured on 2026-10-21. It is test
    # evidence only and is never imported by the live collector.
    return {
        "type": "highlight-table-block", "title": "NVIDIA GPU Instances",
        "table": {"content": [
            ["Item", "vCPUs", "RAM, GB", "Preemptible, GPU-hour\u00a0*", "On-demand, GPU-hour"],
            ["NVIDIA GB300 NVL72", "112", "800", " - ", "[Contact us](#ai-contact-form)"],
            ["NVIDIA HGX B300", "24", "346", "from $0.99", "$9.50"],
            ["NVIDIA GB200 NVL72", "112", "800", " - ", "[Contact us](#ai-contact-form)"],
            ["NVIDIA HGX B200", "20", "224", "from $0.99", "$8.50"],
            ["NVIDIA HGX H200", "16", "200", "from $0.79", "$5.40"],
            ["NVIDIA HGX H100", "16", "200", "from $0.79", "$4.50"],
            ["NVIDIA RTX PRO 6000", "24", "218", "from $0.79", "$1.80 "],
            ["NVIDIA L40S with Intel CPU", "8-40", "32-160", "from $0.74**", "from $1.55"],
            ["NVIDIA L40S with AMD CPU", "16-192", "96-1152", "from $0.90**", "from $1.82"],
        ]},
    }


def payload(table=None):
    blocks = [block() if table is None else table, {
        "type": "questions-block", "items": [{
            "title": "What currency do you accept?", "text": "We accept USD.",
        }],
    }, {"type": "content-layout-block", "textContent": {
        "additionalInfo": "All prices are shown without any applicable taxes, including VAT.",
    }}]
    return {"pageProps": {"__APOLLO_STATE__": {"pages:any-id": {
        "__typename": "pages", "name": "prices", "website": "nebius.com",
        "content": json.dumps({"blocks": blocks}),
    }}}, "__N_SSP": True}


def bootstrap(build="test-build-v2", **overrides):
    data = {"buildId": build, "page": "/[[...slug]]", "locale": "en", "gssp": True}
    data.update(overrides)
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>'


def parse(data=None):
    return nebius_catalog.parse_prices(payload() if data is None else data,
                                       observed_at=OBSERVED, api_endpoint=ENDPOINT)


class NebiusCatalogTests(unittest.TestCase):
    def test_five_exact_on_demand_rates_and_four_nonquotes_are_kept_distinct(self):
        quotes = parse()
        actual = {q["gpu_model"]: q["amount"] for q in quotes if q["quote_status"] == "quoted"}
        self.assertEqual(actual, {"B300": "9.50", "B200": "8.50", "H200": "5.40",
                                  "H100": "4.50", "RTX PRO 6000": "1.80"})
        self.assertEqual(len(quotes), 9)
        contact = [q for q in quotes if q["quote_status"] == "contact_sales"]
        self.assertEqual({q["gpu_model"] for q in contact}, {"GB200", "GB300"})
        self.assertTrue(all(q["amount"] is None for q in contact))
        floors = [q for q in quotes if q["quote_status"] == "starting_at"]
        self.assertEqual([q["amount"] for q in floors], ["1.55", "1.82"])
        self.assertTrue(all(q["price_basis"] == "starting_price" for q in floors))

    def test_units_geography_unknown_configuration_and_origin_are_not_invented(self):
        quotes = parse()
        b200 = next(q for q in quotes if q["gpu_model"] == "B200")
        self.assertEqual(b200["resources"], {"vcpus": 20, "ram_gb": 224})
        for q in quotes:
            self.assertEqual((q["currency"], q["unit"], q["billing_mode"]), ("USD", "gpu_hour", "on_demand"))
            self.assertEqual((q["regions"], q["zones"], q["compute_countries"]), ([], [], []))
            self.assertEqual(q["price_scope"], "unlocated_catalog")
            self.assertIs(q["region_price_verified"], False)
            self.assertIsNone(q["gpu_count"])
            self.assertIsNone(q["vram_gb"])
            self.assertIsNone(q["raw_sku"])
            self.assertIsNone(q["effective_from"])
            self.assertEqual(q["observed_at"], OBSERVED)
            self.assertEqual(q["source_type"], "official_website_json")
            self.assertEqual(q["source_url"], "https://nebius.com/prices")
            self.assertEqual(q["api_endpoint"], ENDPOINT)
            self.assertEqual(q["tax_scope"], "excluded")
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_configuration_ranges_are_retained_without_picking_a_preset(self):
        q = next(q for q in parse() if q["raw_name"] == "NVIDIA L40S with Intel CPU")
        self.assertEqual(q["resources"], {"vcpus_range": [8, 40], "ram_gb_range": [32, 160]})
        self.assertNotIn("instance_price", q)

    def test_changed_columns_units_currency_or_scope_fail_closed(self):
        for cell in ("GPU-month", "On-demand, instance-hour", "On-demand, GPU-hour EUR"):
            changed = block()
            changed["table"]["content"][0][4] = cell
            with self.subTest(header=cell), self.assertRaises(ValueError):
                parse(payload(changed))
        for name in ("CPU only", "NVIDIA L40S GPU component", "AMD MI300X"):
            changed = block()
            changed["table"]["content"][2][0] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse(payload(changed))
        for amount in ("$0", "$-1", "$NaN", "$1e3", "€9.50", "$9.50/hour", 9.5, None):
            changed = block()
            changed["table"]["content"][2][4] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                parse(payload(changed))

    def test_currency_requires_explicit_official_usd_evidence_not_dollar_symbol(self):
        data = payload()
        page = next(iter(data["pageProps"]["__APOLLO_STATE__"].values()))
        content = json.loads(page["content"])
        content["blocks"][1]["items"][0]["text"] = "We accept CAD."
        page["content"] = json.dumps(content)
        with self.assertRaises(ValueError):
            parse(data)

    def test_ambiguous_pages_tables_duplicates_and_malformed_ranges_fail(self):
        data = payload()
        state = data["pageProps"]["__APOLLO_STATE__"]
        state["pages:duplicate"] = deepcopy(next(iter(state.values())))
        with self.assertRaises(ValueError):
            parse(data)
        for value in ("0", "8-8", "40-8", "8 / 40", "unknown"):
            changed = block()
            changed["table"]["content"][2][1] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(payload(changed))
        changed = block()
        changed["table"]["content"].append(changed["table"]["content"][2])
        with self.assertRaises(ValueError):
            parse(payload(changed))
        data = payload()
        page = next(iter(data["pageProps"]["__APOLLO_STATE__"].values()))
        content = json.loads(page["content"])
        content["blocks"].append(block())
        page["content"] = json.dumps(content)
        with self.assertRaises(ValueError):
            parse(data)

    def test_bootstrap_only_supplies_safe_same_origin_routing_metadata(self):
        self.assertEqual(nebius_catalog.data_url(bootstrap()), ENDPOINT)
        self.assertEqual(nebius_catalog.data_url(bootstrap("new_deploy-42")),
                         "https://nebius.com/_next/data/new_deploy-42/en/prices.json")
        for build in ("../other", "https://untrusted.example/", "x?token=secret", "", 42):
            with self.subTest(build=build), self.assertRaises(ValueError):
                nebius_catalog.data_url(bootstrap(build))
        for override in ({"locale": "ru"}, {"page": "/billing"}, {"gssp": False}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                nebius_catalog.data_url(bootstrap(**override))
        with self.assertRaises(ValueError):
            nebius_catalog.data_url(bootstrap() + bootstrap())
        with self.assertRaises(ValueError):
            parse({"props": payload()["pageProps"]})
        with self.assertRaises(ValueError):
            nebius_catalog.parse_prices(payload(), observed_at=OBSERVED,
                                        api_endpoint="https://untrusted.example/prices.json")

    @patch("gpu_price_monitor.providers.nebius_catalog.request_json")
    @patch("gpu_price_monitor.providers.nebius_catalog.fetch_text")
    def test_anonymous_collection_reads_prices_only_from_subsequent_json(self, fetch, request):
        # Deliberately conflicting bootstrap prices prove that HTML amounts are
        # never used as a fallback or confused with the data response.
        fetch.return_value = bootstrap(props={"price": "$0.01"}) + '<p>B200 $0.01</p>'
        request.return_value = payload()
        settings = Settings(nebius_access_token="unused-private-value")
        quotes = nebius_catalog.collect_quotes(settings=settings, observed_at=OBSERVED)
        fetch.assert_called_once_with(nebius_catalog.SOURCE_URL, settings)
        request.assert_called_once_with(ENDPOINT, settings, authenticated=False)
        self.assertEqual(next(q["amount"] for q in quotes if q["gpu_model"] == "B200"), "8.50")
        self.assertNotIn("unused-private-value", json.dumps(quotes))

    @patch("gpu_price_monitor.providers.nebius_catalog.request_json")
    @patch("gpu_price_monitor.providers.nebius_catalog.fetch_text")
    def test_structure_changes_return_parse_failed_without_html_or_history_fallback(self, fetch, request):
        fetch.return_value = bootstrap()
        request.return_value = {"pageProps": {}}
        with self.assertRaises(FetchError) as caught:
            nebius_catalog.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "parse_failed")
        self.assertEqual((fetch.call_count, request.call_count), (1, 1))

    @patch("gpu_price_monitor.providers.nebius_catalog.request_json")
    @patch("gpu_price_monitor.providers.nebius_catalog.fetch_text")
    def test_request_errors_propagate_without_choosing_a_different_source(self, fetch, request):
        fetch.return_value = bootstrap()
        request.side_effect = FetchError("http_error", "HTTP 503", retryable=True)
        with self.assertRaises(FetchError) as caught:
            nebius_catalog.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "http_error")
        self.assertEqual((fetch.call_count, request.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
