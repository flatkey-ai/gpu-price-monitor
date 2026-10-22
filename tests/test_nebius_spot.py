"""Current anonymous regional spot prices, separate from minima and history."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from gpu_price_monitor.providers import nebius_spot
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "nebius-current-spot.json"
HISTORY = FIXTURE.with_name("nebius-spot-history-b200-2026-10-21T0800Z.json")
OBSERVED = "2026-10-21T08:33:00+00:00"


def source():
    return json.loads(FIXTURE.read_text())


def parse(payload=None):
    return nebius_spot.parse_prices(source() if payload is None else payload, observed_at=OBSERVED)


def page(items, token=None):
    result = {"items": items, "snapshotTime": source()["snapshotTime"]}
    if token is not None:
        result["nextPageToken"] = token
    return result


class NebiusSpotTests(unittest.TestCase):
    def test_live_api_has_exact_regional_current_spot_quotes_and_source_times(self):
        quotes = parse()
        self.assertEqual(len(quotes), 12)
        self.assertEqual({q["gpu_model"] for q in quotes}, {"B300", "B200", "H200", "H100", "RTX PRO 6000"})
        b200 = {q["regions"][0]: q for q in quotes if q["gpu_model"] == "B200"}
        self.assertEqual(b200["me-west1"]["amount"], "3.8")
        self.assertEqual(b200["me-west1"]["compute_countries"], ["IL"])
        self.assertEqual(b200["me-west1"]["raw_sku"], "gpu-b200-sxm-a")
        self.assertEqual(b200["me-west1"]["effective_from"], "2026-10-21T08:21:00+00:00")
        self.assertEqual(b200["us-central1"]["amount"], "1.6")
        self.assertEqual(b200["us-central1"]["compute_countries"], ["US"])
        self.assertEqual(b200["us-central1"]["raw_sku"], "gpu-b200-sxm")
        self.assertEqual(b200["us-central1"]["effective_from"], "2026-10-21T08:16:00+00:00")
        for quote in quotes:
            self.assertEqual(quote["source_snapshot_at"], "2026-10-21T08:32:12.346841+00:00")
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertEqual((quote["currency"], quote["unit"], quote["billing_mode"]), ("USD", "gpu_hour", "spot"))
            self.assertEqual(quote["price_basis"], "advertised_per_gpu")
            self.assertEqual(quote["quote_status"], "quoted")
            self.assertEqual(quote["source_type"], "official_public_api")
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["tax_scope"], "excluded")
            self.assertEqual(quote["price_scope"], "regional_quote")
            self.assertIs(quote["region_price_verified"], True)
            self.assertEqual(quote["conditions"]["capacity_type"], "preemptible")
            self.assertEqual(quote["location_source"]["url"], nebius_spot.REGIONS_URL)
            self.assertEqual(quote["location_source"]["verified_on"], "2026-10-21")
            self.assertEqual(len(quote["regions"]), 1)
            self.assertEqual(len(quote["compute_countries"]), 1)
            self.assertIsNone(quote["gpu_count"])
            self.assertIsNone(quote["vram_gb"])
            self.assertIsNone(quote["effective_until"])
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_historical_screenshot_fixture_explains_interval_end_and_is_not_current(self):
        evidence = json.loads(HISTORY.read_text())
        self.assertEqual(evidence["request"]["aggregation.method"], "METHOD_LAST_PRICE")
        self.assertEqual(evidence["request"]["filters.startTime"], "2026-10-21T07:00:00Z")
        self.assertEqual(evidence["request"]["filters.endTime"], "2026-10-21T08:00:00Z")
        history = evidence["response"]
        amounts = {item["region"]: item["points"][0] for item in history["items"]}
        self.assertEqual(amounts["me-west1"], {"timestamp": "2026-10-21T08:00:00Z", "value": "4.1"})
        self.assertEqual(amounts["us-central1"], {"timestamp": "2026-10-21T08:00:00Z", "value": "1.9"})
        with self.assertRaises(ValueError):
            parse(history)

    def test_unknown_country_is_not_guessed_from_region_or_currency(self):
        payload = source()
        payload["items"] = [payload["items"][0]]
        payload["items"][0]["region"] = "us-future1"
        quote = parse(payload)[0]
        self.assertEqual(quote["compute_countries"], [])
        self.assertEqual(quote["regions"], ["us-future1"])
        self.assertIsNone(quote["location_source"]["url"])
        self.assertIsNone(quote["location_source"]["verified_on"])

    def test_new_model_and_platform_are_read_from_matching_api_identity_not_fixed_whitelist(self):
        payload = source()
        payload["items"] = [payload["items"][0]]
        payload["items"][0].update(productTitle="Preemptible NVIDIA® B400 NVLink",
                                   computeInstance={"platform": "gpu-b400-sxm-b"})
        quote = parse(payload)[0]
        self.assertEqual(quote["gpu_model"], "B400")
        self.assertEqual(quote["raw_sku"], "gpu-b400-sxm-b")
        self.assertEqual(quote["amount"], payload["items"][0]["price"]["value"])
        payload["items"][0]["computeInstance"]["platform"] = "gpu-b300-sxm-b"
        with self.assertRaises(ValueError):
            parse(payload)

    def test_price_unit_currency_product_and_platform_drift_fail_closed(self):
        base = source()["items"][0]
        mutations = (
            {"productTitle": "NVIDIA® H200 NVLink"}, {"productTitle": "Preemptible NVIDIA® B200 NVLink"},
            {"computeInstance": {"platform": "gpu-l40s"}}, {"computeInstance": None},
            {"skuId": "https://untrusted.example"}, {"region": "US Central"},
            {"price": {"value": "0.79", "currency": "usd", "unitTitle": "GPU month"}},
            {"price": {"value": "0.79", "currency": "unspecified", "unitTitle": "GPU hour"}},
        )
        for value in (0.79, True, "0", "-1", "NaN", "Infinity", "1e3", "0.123456789012345678901"):
            mutations += ({"price": {"value": value, "currency": "usd", "unitTitle": "GPU hour"}},)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse(page([{**base, **mutation}]))

    def test_timestamps_require_timezone_current_snapshot_and_effective_event(self):
        payload = source()
        payload["items"] = [payload["items"][0]]
        for snapshot in ("2026-10-21T08:00:00Z", "2026-10-21T10:00:00Z", "2026-10-21", None):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                parse({**payload, "snapshotTime": snapshot})
        for effective in ("2026-10-22T00:00:00Z", "2026-10-21T08:00:00", "2026-10-21", None):
            changed = deepcopy(payload)
            changed["items"][0]["effectiveTime"] = effective
            with self.subTest(effective=effective), self.assertRaises(ValueError):
                parse(changed)
        # An unchanged price can have an old effective event while its API
        # snapshot is current; freshness is not inferred from price changes.
        h100 = next(q for q in parse() if q["gpu_model"] == "H100")
        self.assertEqual(h100["effective_from"], "2026-10-09T17:01:00+00:00")

    def test_earliest_snapshot_is_not_an_upper_bound_on_every_sku_effective_event(self):
        payload = source()
        payload["items"] = [payload["items"][0]]
        payload["items"][0]["effectiveTime"] = "2026-10-21T08:32:30Z"
        quote = parse(payload)[0]
        self.assertEqual(quote["source_snapshot_at"], "2026-10-21T08:32:12.346841+00:00")
        self.assertEqual(quote["effective_from"], "2026-10-21T08:32:30+00:00")
        self.assertEqual(quote["source_snapshot_basis"], "earliest_per_sku_snapshot")

    def test_duplicate_current_skus_and_region_platform_entries_are_rejected(self):
        row = source()["items"][0]
        for duplicate in (row, {**row, "skuId": "sku-another"}):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                parse(page([row, duplicate]))

    @patch("gpu_price_monitor.providers.nebius_spot.request_json")
    def test_collection_is_anonymous_bounded_fixed_endpoint_get(self, request):
        payload = source()
        request.return_value = payload
        settings = Settings(lambda_api_key="unused-private-key")
        quotes = nebius_spot.collect_quotes(settings=settings, observed_at=OBSERVED)
        request.assert_called_once_with(nebius_spot.query_url(), settings, authenticated=False)
        self.assertEqual(len(quotes), 12)
        self.assertNotIn("unused-private-key", json.dumps(quotes))

    @patch("gpu_price_monitor.providers.nebius_spot.request_json")
    def test_pagination_keeps_opaque_token_in_query_and_finishes_before_returning(self, request):
        rows = source()["items"]
        token = "https://untrusted.invalid/?a=1&b=2"
        request.side_effect = [page(rows[:6], token), page(rows[6:])]
        quotes = nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(len(quotes), 12)
        url = urlsplit(request.call_args_list[1].args[0])
        self.assertEqual((url.scheme, url.netloc, url.path),
                         ("https", "api.nebius.cloud", "/billing/v1alpha1/spot-price"))
        self.assertEqual(parse_qs(url.query), {"pageSize": ["100"], "pageToken": [token]})
        self.assertTrue(all(call.kwargs == {"authenticated": False} for call in request.call_args_list))

    @patch("gpu_price_monitor.providers.nebius_spot.request_json")
    def test_invalid_repeated_or_unbounded_pagination_never_returns_partial_quotes(self, request):
        rows = source()["items"]
        for token in (False, [], "x" * 4097, "token\nunsafe"):
            request.side_effect = None
            request.return_value = page(rows[:1], token)
            with self.subTest(token=token), self.assertRaises(FetchError) as captured:
                nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, "invalid_pagination")
        request.side_effect = [page(rows[:6], "same"), page(rows[6:], "same")]
        with self.assertRaises(FetchError) as captured:
            nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "invalid_pagination")
        request.side_effect = None
        request.return_value = page(rows[:1], "more")
        with patch.object(nebius_spot, "MAX_PAGES", 1), self.assertRaises(FetchError) as captured:
            nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "pagination_limit")

    @patch("gpu_price_monitor.providers.nebius_spot.request_json")
    def test_empty_and_cross_page_duplicate_catalogs_do_not_return_partial_data(self, request):
        request.return_value = page([])
        with self.assertRaises(FetchError) as captured:
            nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "empty_public_catalog")
        row = source()["items"][0]
        request.side_effect = [page([row], "more"), page([row])]
        with self.assertRaises(FetchError) as captured:
            nebius_spot.collect_quotes(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "invalid_public_catalog")


if __name__ == "__main__":
    unittest.main()
