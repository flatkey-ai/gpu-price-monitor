"""Offline official-template projections; authenticated success is not claimed."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


class AutoDLMarketTests(unittest.TestCase):
    def test_visible_prices_and_exact_source_locations_are_retained(self):
        quotes = market.parse_market_page(HTML, metadata=metadata(), observed_at=OBSERVED)
        regular, member = quotes
        self.assertEqual((regular["amount"], regular["regions"], regular["location"]["region_name"]), ("1.98", ["bj-B1"], "北京B区"))
        self.assertEqual(regular["available_gpu_count"], 2)
        self.assertEqual(regular["availability"], "available")
        self.assertEqual(regular["resources"]["cpu_cores_per_gpu"], "8")
        self.assertEqual(regular["resources"]["memory_per_gpu"], {"amount": "64", "unit": "GB"})
        self.assertEqual(member["amount"], "9.50")
        self.assertEqual(member["ordinary_price_amount"], "10.00")
        self.assertTrue(member["membership_required"])
        self.assertEqual(member["availability"], "unavailable")
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
        for path in ("/api/v1/instance/allocate", "/api/v1/machine/detail", "/api/v1/order/instance/create/payg", "/api/v1/user/detail", "/api/v1/wallet"):
            for method in ("GET", "POST"):
                self.assertFalse(allowed("https://www.autodl.com" + path, method))
        for url in ("http://www.autodl.com/api/v1/common", "https://attacker.invalid/api/v1/common", "https://user@www.autodl.com/api/v1/common", "https://www.autodl.com:444/api/v1/common", "https://www.autodl.com:invalid/api/v1/common"):
            self.assertFalse(allowed(url))

    @patch.object(market, "_render_market_pages")
    def test_collection_checks_complete_pagination_before_returning(self, render):
        render.return_value = [{"metadata": metadata(), "html": HTML}]
        quotes = market.collect_quotes(settings=SimpleNamespace(), observed_at=OBSERVED)
        self.assertEqual(len(quotes), 2)
        truncated = deepcopy(render.return_value)
        truncated[0]["metadata"]["result_total"] = market.PAGE_SIZE + 1
        render.return_value = truncated
        with self.assertRaises(ValueError):
            market.collect_quotes(settings=SimpleNamespace(), observed_at=OBSERVED)

    def test_query_is_bounded_default_hourly_and_never_a_resource_operation(self):
        query = market.market_query(2)
        self.assertEqual((query["page_index"], query["page_size"], query["charge_type"]), (2, 90, "payg"))
        self.assertFalse(query["region_sign_list"])
        for page in (0, True, market.MAX_PAGES + 1):
            with self.assertRaises(ValueError):
                market.market_query(page)


if __name__ == "__main__":
    unittest.main()
