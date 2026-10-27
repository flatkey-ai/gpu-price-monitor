"""Offline official-template projections; authenticated success is not claimed."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gpu_price_monitor.providers import autodl_market as market
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-21T05:00:00+00:00"
HTML = (Path(__file__).parent / "fixtures/autodl-market-template.html").read_text()


def payload():
    return {"code": "Success", "data": {"page_index": 1, "page_size": market.PAGE_SIZE, "result_total": 2, "list": [
        {"machine_id": "test-market-4090", "region_sign": "bj-B1", "region_name": "北京B区", "gpu_name": "RTX 4090", "gpu_memory": 24 * 2**30, "chip_corp": "nvidia", "ssh_password": "never-return-this-field"},
        {"machine_id": "test-market-h20", "region_sign": "west-B", "region_name": "西北B区", "gpu_name": "H20-NVLink", "gpu_memory": 96 * 2**30, "chip_corp": "nvidia"},
    ]}}


def metadata():
    return market.project_market_response(payload(), market.market_query(1))


def public_region_payload():
    return {"code": "Success", "data": [
        {"region_sign": "bj-B1", "region_name": "北京B区", "data_center": "beijingDC2"},
        {"region_sign": "bj-B2", "region_name": "北京B区", "data_center": "beijingDC2"},
        {"region_sign": "west-B", "region_name": "西北B区", "data_center": "westDC3"},
    ]}


class AutoDLMarketTests(unittest.TestCase):
    def test_cancelled_previous_page_body_is_not_read_but_current_page_stays_strict(self):
        cancelled = SimpleNamespace(status=200, body=Mock(side_effect=RuntimeError("cancelled old page")))
        self.assertIsNone(market._read_market_response(cancelled, request_page=1, expected_page=2))
        cancelled.body.assert_not_called()
        current = SimpleNamespace(status=200, body=Mock(return_value=json.dumps(payload()).encode()))
        self.assertEqual(market._read_market_response(current, request_page=1, expected_page=1), metadata())
        # An actual page-2 request returning page-1 data is a protocol failure,
        # not a stale request to silently accept or ignore.
        with self.assertRaises(ValueError):
            market._read_market_response(current, request_page=2, expected_page=2)

    def test_visible_prices_and_exact_source_locations_are_retained(self):
        quotes = market.parse_market_page(HTML, metadata=metadata(), observed_at=OBSERVED)
        regular, ordinary, member = quotes
        self.assertEqual((regular["amount"], regular["regions"], regular["location"]["region_name"]), ("1.98", ["bj-B1"], "北京B区"))
        self.assertEqual(regular["available_gpu_count"], 2)
        self.assertEqual(regular["availability"], "available")
        self.assertEqual(regular["resources"]["cpu_cores_per_gpu"], "8")
        self.assertEqual(regular["resources"]["memory_per_gpu"], {"amount": "64", "unit": "GB"})
        self.assertEqual(member["amount"], "9.50")
        self.assertEqual(member["ordinary_price_amount"], "10.00")
        self.assertEqual(member["membership_discount_badge"], "9.5折")
        self.assertTrue(member["membership_required"])
        self.assertEqual(member["availability"], "unavailable")
        self.assertEqual((ordinary["amount"], ordinary["pricing_tier"], ordinary["membership_required"]), ("10.00", "ordinary", False))
        self.assertEqual(ordinary["availability"], member["availability"])
        self.assertEqual(ordinary["raw_sku"], member["raw_sku"])
        self.assertEqual(ordinary["conditions"], [])
        self.assertNotIn("membership_discount_badge", ordinary)
        self.assertTrue(any("9.5折" in value for value in member["conditions"]))
        for quote in quotes:
            self.assertEqual(quote["account_scope"], "authenticated_catalog")
            self.assertEqual(quote["source_type"], "authorized_browser")
            self.assertEqual(quote["unit"], "gpu_hour")
            self.assertEqual(quote["currency"], "CNY")
            self.assertIsNone(quote["gpu_count"])
            self.assertNotIn("instance_price", quote)
            self.assertNotIn("country_code", quote["location"])
            self.assertEqual(quote["zones"], [])
        self.assertNotIn("never-return", json.dumps(quotes))

    def test_member_and_ordinary_amounts_use_separate_visible_values_not_discount_math(self):
        # Deliberately non-matching discount arithmetic: both explicit source
        # amounts must survive without inferring either from the badge.
        quotes = market.parse_market_page(HTML.replace("￥10.00/时", "￥11.11/时"), metadata=metadata(), observed_at=OBSERVED)
        ordinary, member = quotes[1:]
        self.assertEqual(ordinary["amount"], "11.11")
        self.assertEqual(ordinary["price_source"], {"selector": ".price .money .origin-price", "value_text": "￥11.11/时"})
        self.assertEqual(member["amount"], "9.50")
        self.assertEqual(member["price_source"], {"selector": ".price .money > .num", "value_text": "9.50"})
        self.assertEqual(member["membership_discount_badge"], "9.5折")
        self.assertFalse(ordinary["membership_required"])
        self.assertTrue(member["membership_required"])

    def test_tiers_do_not_duplicate_inventory_or_multiply_prices_by_available_cards(self):
        content = HTML.replace("<button disabled>已租完</button>", "<button>3卡可租</button>")
        quotes = market.parse_market_page(content, metadata=metadata(), observed_at=OBSERVED)
        self.assertEqual(len(quotes), 3)
        self.assertEqual(len({quote["raw_sku"] for quote in quotes}), 2)
        self.assertEqual(len({(quote["raw_sku"], quote["pricing_tier"]) for quote in quotes}), 3)
        self.assertEqual([(quote["amount"], quote["available_gpu_count"]) for quote in quotes], [("1.98", 2), ("10.00", 3), ("9.50", 3)])
        self.assertTrue(all(quote["gpu_count"] is None for quote in quotes))
        self.assertTrue(all(quote["availability"] == "available" for quote in quotes))

    def test_projection_drops_all_non_price_account_or_resource_fields(self):
        projected = metadata()
        self.assertNotIn("ssh", json.dumps(projected))
        self.assertEqual(set(projected["rows"][0]), {"machine_id", "region_sign", "region_name", "gpu_name", "gpu_memory", "chip_corp"})
        self.assertNotIn("会员最低", json.dumps(market.parse_market_page(HTML, metadata=projected, observed_at=OBSERVED), ensure_ascii=False))

    def test_units_currency_memory_identity_and_duplicate_cards_fail_closed(self):
        changes = [HTML.replace("/时", "/月"), HTML.replace("￥", "$"), HTML.replace("24 GB", "48 GB"),
                   HTML.replace("test-market-4090", "unknown-machine"), HTML.replace("2卡可租", "即将上线"),
                   HTML.replace("class=\"num\"", "class=\"changed\"", 1), HTML.replace("1.98", "0"),
                   HTML.replace("class=\"member_level\"", "class=\"changed\""),
                   HTML.replace("￥10.00/时", "￥0/时"), HTML.replace("￥10.00/时", "￥10.00/月"),
                   HTML.replace('<span class="num">1.98</span>', '<span class="num">1.98</span>起')]
        for content in changes:
            with self.subTest(content=content[:60]), self.assertRaises(ValueError):
                market.parse_market_page(content, metadata=metadata(), observed_at=OBSERVED)

    def test_anonymous_or_expired_market_does_not_turn_into_homepage_prices(self):
        with self.assertRaises(FetchError) as caught:
            market.project_market_response({"code": "AuthorizeFailed", "msg": "secret-test-body"}, market.market_query(1))
        self.assertEqual(caught.exception.code, "login_required")
        self.assertNotIn("secret-test", str(caught.exception))
        with self.assertRaises(FetchError) as caught:
            market.collect_quotes(settings=SimpleNamespace(autodl_storage_state_path=None), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "login_required")

    def test_hidden_filters_partial_pages_and_malformed_locations_fail(self):
        for key, value in (("charge_type", "monthly"), ("region_sign_list", ["bj-B1"]), ("gpu_type_name", ["RTX 4090"]), ("page_size", 10)):
            query = market.market_query(1)
            query[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                market.project_market_response(payload(), query)
        for field, value in (("result_total", 3), ("page_index", 2), ("page_size", True)):
            body = payload()
            body["data"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                market.project_market_response(body, market.market_query(1))
        body = payload()
        body["data"]["list"][0]["region_sign"] = ""
        with self.assertRaises(ValueError):
            market.project_market_response(body, market.market_query(1))

    def test_read_request_allowlist_blocks_orders_instances_ssh_and_external_credentials(self):
        allowed = lambda url, method="GET", kind="fetch": market.request_is_allowed(url, method, kind)
        self.assertTrue(allowed("https://www.autodl.com" + market.MARKET_PATH, "POST"))
        self.assertTrue(allowed("https://www.autodl.com/assets/market.js", kind="script"))
        self.assertTrue(allowed("https://www.autodl.com" + market.REGIONS_PATH))
        self.assertFalse(allowed("https://www.autodl.com" + market.REGIONS_PATH, "POST"))
        for path in ("/api/v1/user/detail", "/api/v1/user/level", "/api/v1/user/member/detail"):
            self.assertTrue(allowed("https://www.autodl.com" + path))
            self.assertFalse(allowed("https://www.autodl.com" + path, "POST"))
        for path in ("/api/v1/instance/allocate", "/api/v1/machine/detail", "/api/v1/order/instance/create/payg", "/api/v1/wallet"):
            for method in ("GET", "POST"):
                self.assertFalse(allowed("https://www.autodl.com" + path, method))
        for url in ("http://www.autodl.com/api/v1/common", "https://attacker.invalid/api/v1/common", "https://user@www.autodl.com/api/v1/common", "https://www.autodl.com:444/api/v1/common", "https://www.autodl.com:invalid/api/v1/common"):
            self.assertFalse(allowed(url))

    @patch.object(market, "_render_market_pages")
    def test_collection_checks_complete_pagination_before_returning(self, render):
        render.return_value = [{"metadata": metadata(), "html": HTML}]
        quotes = market.collect_quotes(settings=SimpleNamespace(), observed_at=OBSERVED)
        self.assertEqual(len(quotes), 3)
        self.assertEqual(render.return_value[0]["metadata"]["result_total"], 2)
        truncated = deepcopy(render.return_value)
        truncated[0]["metadata"]["result_total"] = market.PAGE_SIZE + 1
        render.return_value = truncated
        with self.assertRaises(ValueError):
            market.collect_quotes(settings=SimpleNamespace(), observed_at=OBSERVED)

    def test_public_directory_projection_immediately_discards_all_unneeded_fields(self):
        source = public_region_payload()
        source["request_id"] = "discard-request-id"
        source["unrelated_account"] = {"email": "discard-account-field"}
        source["data"][0].update(country_code="not-an-api-country-evidence", unrelated="discard-extra-row")
        projected = market.project_region_response(source)
        self.assertEqual(set(projected), {"code", "data"})
        self.assertEqual(set(projected["data"][0]), {"region_sign", "region_name", "data_center"})
        self.assertNotIn("discard", json.dumps(projected))
        self.assertNotIn("not-an-api-country-evidence", json.dumps(projected))
        for invalid in ({"code": "AuthorizeFailed", "data": []}, {"code": "Success", "data": []},
                        {"code": "Success", "data": [None]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                market.project_region_response(invalid)

    @patch.object(market, "_render_market_pages")
    def test_collection_enriches_official_and_operator_reviewed_country_without_price_changes(self, render):
        render.return_value = [{"metadata": metadata(), "html": HTML,
                                "region_directory_payload": market.project_region_response(public_region_payload())}]
        result = market.collect_result(settings=SimpleNamespace(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual([q["amount"] for q in result["prices"]], ["1.98", "10.00", "9.50"])
        self.assertEqual(result["prices"][0]["compute_countries"], ["CN"])
        self.assertEqual(result["prices"][0]["location_source"]["directory_observed_at"], OBSERVED)
        self.assertEqual([q["compute_countries"] for q in result["prices"][1:]], [["CN"], ["CN"]])
        self.assertTrue(all(q["location_source"]["country_basis"] == "operator_reviewed_provider_region_country_mapping"
                            for q in result["prices"][1:]))
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["coverage"]["market_listing_count"], 2)
        self.assertEqual(result["coverage"]["gpu_listing_count"], 2)
        self.assertEqual(result["coverage"]["returned_price_count"], 3)
        self.assertEqual(result["coverage"]["country_verified_price_count"], 3)
        self.assertEqual(result["errors"], [])
        self.assertTrue(all(q["currency"] == "CNY" and q["unit"] == "gpu_hour" for q in result["prices"]))

    @patch.object(market, "_render_market_pages")
    def test_changed_operator_reviewed_dc_keeps_prices_and_one_country_gap(self, render):
        body = public_region_payload()
        body["data"][2]["data_center"] = "westFutureDC"
        render.return_value = [{"metadata": metadata(), "html": HTML,
                                "region_directory_payload": market.project_region_response(body)}]
        result = market.collect_result(settings=SimpleNamespace(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([q["amount"] for q in result["prices"]], ["1.98", "10.00", "9.50"])
        self.assertEqual([q["compute_countries"] for q in result["prices"]], [["CN"], [], []])
        self.assertEqual(len(result["gaps"]), 1)
        self.assertEqual(result["gaps"][0]["region"], "west-B")
        self.assertEqual(result["coverage"]["country_verified_price_count"], 1)

    @patch.object(market, "_render_market_pages")
    def test_directory_request_or_schema_failure_keeps_real_native_prices_and_explicit_country_gap(self, render):
        for extra in ({"region_directory_payload": None,
                       "region_directory_error": {"retryable": True, "private_body": "never-return"}},
                      {"region_directory_payload": {"code": "Success", "data": [{"bad": "shape"}]}}):
            render.return_value = [{"metadata": metadata(), "html": HTML, **extra}]
            result = market.collect_result(settings=SimpleNamespace(), observed_at=OBSERVED)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["prices"]), 3)
            self.assertTrue(all(q["compute_countries"] == [] for q in result["prices"]))
            self.assertEqual(result["errors"][0]["code"], "region_directory_unavailable")
            self.assertEqual({g["region"] for g in result["gaps"]}, {"bj-B1", "west-B"})
            self.assertNotIn("never-return", json.dumps(result))
            # The compatible list API must also retain real prices on a
            # country-only failure; evidence reasons stay on every quote.
            self.assertEqual(len(market.collect_quotes(settings=SimpleNamespace(), observed_at=OBSERVED)), 3)

    @patch.object(market, "_render_market_pages")
    def test_all_exact_known_regions_can_succeed_without_changing_member_and_ordinary_prices(self, render):
        meta = metadata()
        meta["rows"][1].update(region_sign="bj-B2", region_name="北京B区")
        render.return_value = [{"metadata": meta, "html": HTML,
                                "region_directory_payload": market.project_region_response(public_region_payload())}]
        result = market.collect_result(settings=SimpleNamespace(), observed_at=OBSERVED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["errors"], [])
        self.assertTrue(all(q["compute_countries"] == ["CN"] for q in result["prices"]))
        self.assertEqual([(q["amount"], q["pricing_tier"]) for q in result["prices"]],
                         [("1.98", "authenticated_market"), ("10.00", "ordinary"), ("9.50", "member")])

    def test_query_is_bounded_default_hourly_and_never_a_resource_operation(self):
        query = market.market_query(2)
        self.assertEqual((query["page_index"], query["page_size"], query["charge_type"]), (2, 90, "payg"))
        self.assertFalse(query["region_sign_list"])
        for page in (0, True, market.MAX_PAGES + 1):
            with self.assertRaises(ValueError):
                market.market_query(page)


if __name__ == "__main__":
    unittest.main()
