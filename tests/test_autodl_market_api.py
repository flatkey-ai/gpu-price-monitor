"""Offline protocol checks; credentials and source prices are synthetic."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from gpu_price_monitor import collect_prices
from gpu_price_monitor.csv_export import market_eligible_quote, prices_to_csv
from gpu_price_monitor.providers import autodl_market as browser, autodl_market_api as api
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-22T09:00:00+00:00"


def listing(identity="synthetic-gpu-1", region="bj-B1"):
    return {"machine_id": identity, "region_sign": region, "region_name": "北京B区" if region == "bj-B1" else "西北B区",
            "gpu_name": "RTX 4090", "gpu_memory": 24 * 2**30, "chip_corp": "nvidia", "payg": True,
            "cpu_per_gpu": 12, "mem_per_gpu": 62 * 2**30, "on_line": 2, "gpu_idle_num": 2,
            "max_instance_num": 10, "binding_instance_num": 1,
            "machine_sku_info": [{"type": "payg", "current_price": 1660, "origin_price": 9999,
                                  "level_config": [{"level_name": "normal_user", "discount": 100, "discounted_price": 1660},
                                                   {"level_name": "member_user", "discount": 95, "discounted_price": 1577}]}],
            "ssh_password": "synthetic-private-field-never-return"}


def body(rows, *, page=1, size=5000, total=None):
    return {"code": "Success", "data": {"page_index": page, "page_size": size,
            "result_total": len(rows) if total is None else total, "list": rows}}


def directory():
    return {"code": "Success", "data": [{"region_sign": "bj-B1", "region_name": "北京B区", "data_center": "beijingDC2"},
                                         {"region_sign": "west-B", "region_name": "西北B区", "data_center": "westDC3"}]}


def parse(item):
    identity = browser.project_market_response(body([item]), browser.market_query(1, page_size=5000))["rows"][0]
    return api.parse_listing(item, identity=identity, observed_at=OBSERVED)


class AutoDLMarketApiTests(TestCase):
    def test_actual_tariff_fields_round_like_site_and_preserve_exact_values(self):
        ordinary, member = parse(listing())
        self.assertEqual((ordinary["amount"], member["amount"]), ("1.66", "1.58"))
        self.assertEqual(member["exact_api_hourly_amount"], "1.577")
        self.assertEqual(ordinary["exact_api_hourly_amount"], "1.66")
        self.assertEqual(ordinary["price_source"]["native_amount_milli_cny"], 1660)
        self.assertEqual(member["price_source"]["native_amount_milli_cny"], 1577)
        self.assertEqual(member["membership_discount_badge"], "9.5折")
        self.assertFalse(ordinary["membership_required"])
        self.assertTrue(member["membership_required"])
        self.assertTrue(all(q["unit"] == "gpu_hour" and q["source_type"] == "official_internal_api" for q in (ordinary, member)))
        self.assertNotIn("synthetic-private-field", json.dumps([ordinary, member]))

    def test_member_amount_is_not_back_calculated_from_discount(self):
        item = listing()
        item["machine_sku_info"][0]["level_config"][1]["discounted_price"] = 1531
        self.assertEqual(parse(item)[1]["amount"], "1.53")

    def test_fully_rented_is_not_product_offline_and_stays_in_price_output(self):
        item = listing()
        item["gpu_idle_num"] = 0
        for quote in parse(item):
            self.assertEqual(quote["availability"], "out_of_stock")
            self.assertEqual(quote["inventory_label"], "已租完")
            self.assertTrue(market_eligible_quote(quote))
        item["gpu_idle_num"] = 2
        item["on_line"] = 6
        self.assertTrue(all(q["availability"] == "out_of_stock" for q in parse(item)))

    def test_wrong_units_tiers_and_configurations_cannot_create_prices(self):
        for change in ("monthly", "missing_member", "duplicate_level", "inconsistent_normal", "zero_price", "bad_ram"):
            item = listing()
            sku = item["machine_sku_info"][0]
            if change == "monthly": sku["type"] = "monthly"
            elif change == "missing_member": sku["level_config"].pop()
            elif change == "duplicate_level": sku["level_config"].append(deepcopy(sku["level_config"][0]))
            elif change == "inconsistent_normal": sku["current_price"] = 7777
            elif change == "zero_price": sku["level_config"][1]["discounted_price"] = 0
            elif change == "bad_ram": item["mem_per_gpu"] = None
            with self.subTest(change=change), self.assertRaises(ValueError): parse(item)

    def test_explicit_local_session_is_minimal_and_errors_never_echo_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            token = "synthetic-token-only"
            state = {"cookies": [], "origins": [{"origin": "https://www.autodl.com", "localStorage": [{"name": "token", "value": token}]}]}
            path.write_text(json.dumps(state))
            self.assertEqual(api._token(str(path)), token)
            state["cookies"] = [{"name": "extra"}]
            path.write_text(json.dumps(state))
            with self.assertRaises(FetchError) as caught: api._token(str(path))
            self.assertNotIn(token, str(caught.exception))

    @patch.object(api, "_token", return_value="synthetic-token-only")
    @patch.object(api, "request_json")
    def test_api_policy_collects_full_batch_with_country_evidence_and_no_browser(self, request, _token):
        request.side_effect = [body([listing(), listing("synthetic-gpu-2", "west-B")]), directory()]
        result = collect_prices(["autodl"], settings=Settings(autodl_source="market", source_policy="api_only"))
        self.assertEqual(result["status"], "partial")  # The west-B country remains unverified.
        self.assertEqual(len(result["prices"]), 4)
        source = result["provider_results"][0]
        self.assertEqual(source["source_type"], "official_internal_api")
        self.assertEqual(source["collection_method"], "authenticated_http_json")
        self.assertEqual(source["selection_reason"], "explicit_market_session_catalog")
        self.assertEqual(source["api_endpoint"], api.SOURCE_URL)
        self.assertNotIn("lambda", json.dumps(source["additional_source_urls"]))
        rows = list(csv.DictReader(io.StringIO(prices_to_csv(result, bilingual_headers=False).lstrip("\ufeff"))))
        self.assertEqual(rows[0]["source_url"], api.PRICING_PAGE)
        self.assertEqual(result["prices"][0]["source_url"], api.SOURCE_URL)  # JSON retains the actual API.
        self.assertTrue(all(q["compute_countries"] == ["CN"] for q in result["prices"][:2]))
        self.assertTrue(all(q["compute_countries"] == [] for q in result["prices"][2:]))
        self.assertEqual(request.call_args_list[0].kwargs["data"], json.dumps(browser.market_query(1, page_size=5000)).encode())
        self.assertTrue(request.call_args_list[0].kwargs["authenticated"])

    @patch.object(api, "_token", return_value="synthetic-token-only")
    @patch.object(api, "request_json")
    def test_overlapping_pages_are_detected_not_silently_deduplicated(self, request, _token):
        request.side_effect = [body([listing(), listing("synthetic-gpu-2")], size=2, total=3),
                               body([listing()], page=2, size=2, total=3)]
        with patch.object(api, "BULK_PAGE_SIZE", 2), self.assertRaises(FetchError) as caught:
            api.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "market_changed")
