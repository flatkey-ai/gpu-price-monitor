"""Member preference is an opt-in view of exact, contemporaneous tariff pairs."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from decimal import Inexact, ROUND_DOWN, Rounded, localcontext
import csv
import io
import json
import unittest
from unittest.mock import patch

import gpu_price_monitor
from gpu_price_monitor import prefer_member_quotes, prices_to_csv
from gpu_price_monitor.cli import main
from gpu_price_monitor.providers.autodl_market_api import parse_listing

OBSERVED = "2026-10-23T08:30:00+00:00"


def pair():
    identity = {"machine_id": "synthetic-machine-1", "chip_corp": "nvidia",
                "gpu_memory": 24 * 2**30, "gpu_name": "RTX 4090",
                "region_sign": "bj-B1", "region_name": "北京B区"}
    item = {"payg": True, "cpu_per_gpu": 12, "mem_per_gpu": 62 * 2**30,
            "on_line": 2, "gpu_idle_num": 2, "max_instance_num": 10, "binding_instance_num": 1,
            "machine_sku_info": [{"type": "payg", "current_price": 1660,
                                  "level_config": [
                                      {"level_name": "normal_user", "discount": 100, "discounted_price": 1660},
                                      {"level_name": "member_user", "discount": 95, "discounted_price": 1577}]}]}
    quotes = parse_listing(item, identity=identity, observed_at=OBSERVED)
    for quote in quotes:
        quote.update(compute_countries=["CN"], price_scope="regional_quote", region_price_verified=True)
    return quotes


def envelope(quotes):
    return {"schema_version": 1, "status": "success", "collected_at": OBSERVED,
            "prices": quotes, "provider_results": [{"provider": "autodl", "status": "ok", "error": None}]}


def rows(value):
    return list(csv.DictReader(io.StringIO(value.lstrip("\ufeff"))))


def run_cli(arguments, result):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.dict("os.environ", {}, clear=True), \
            patch("gpu_price_monitor.cli.collect_prices", return_value=result) as collector, \
            redirect_stdout(stdout), redirect_stderr(stderr):
        status = main(arguments)
    return status, stdout.getvalue(), stderr.getvalue(), collector


class MemberPriceTests(unittest.TestCase):
    def test_verified_pair_keeps_member_label_exact_amount_order_and_input(self):
        ordinary, member = pair()
        unrelated = {"provider": "runpod", "amount": "0.50", "cloud_tier": "community"}
        quotes = [ordinary, unrelated, member]
        before = deepcopy(quotes)
        result = prefer_member_quotes(quotes)
        self.assertEqual(result, [unrelated, member])
        self.assertEqual(quotes, before)
        self.assertTrue(result[1]["membership_required"])
        self.assertEqual(result[1]["amount"], "1.58")
        self.assertEqual(result[1]["exact_api_hourly_amount"], "1.577")
        result[1]["resources"]["cpu_cores_per_gpu"] = "999"
        self.assertEqual(quotes, before)  # Returned nested records are also copies.
        self.assertIn("prefer_member_quotes", gpu_price_monitor.__all__)

    def test_every_configuration_geography_source_and_snapshot_difference_is_retained(self):
        changes = {
            "raw_sku": "other-machine", "gpu_model": "A100", "gpu_variant": "SXM",
            "vram_gb": 48, "gpu_count": 2, "regions": ["west-B"], "zones": ["zone-2"],
            "compute_countries": ["US"], "location": {"region": "bj-B1", "region_name": "Other location"},
            "currency": "USD", "unit": "gpu_day", "billing_mode": "spot",
            "observed_at": "2026-10-23T08:31:00+00:00", "cloud_tier": "secure",
            "resources": {"allocation_scope": "per_gpu", "cpu_cores_per_gpu": "24"},
            "selected_configuration": {"disk_gb": 100}, "account_scope": "account_quote",
            "effective_until": "2026-10-24T00:00:00+00:00", "promotion": {"only_new_users": True},
            "source_url": "https://www.autodl.com/market/list", "source_type": "authorized_browser",
            "price_scope": "unlocated_catalog", "region_price_verified": False,
            "future_configuration": {"network": "RDMA"},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                quotes = pair()
                quotes[1][field] = value
                self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_duplicate_or_missing_counterparts_are_not_deduplicated(self):
        ordinary, member = pair()
        for quotes in ([ordinary], [member], [ordinary, member, deepcopy(member)],
                       [ordinary, deepcopy(ordinary), member], [ordinary, ordinary], [member, member]):
            with self.subTest(count=len(quotes)):
                self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_unknown_eligibility_and_conditions_never_remove_the_ordinary_rate(self):
        for field, value in (("membership_required", None), ("membership_required", 1),
                             ("pricing_tier", "community"), ("pricing_tier", "unknown"),
                             ("conditions", []), ("conditions", ["Invitation required."])):
            with self.subTest(field=field, value=value):
                quotes = pair()
                quotes[1][field] = value
                self.assertEqual(prefer_member_quotes(quotes), quotes)
        quotes = pair()
        quotes[0]["membership_required"] = 0
        self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_invalid_negative_nonfinite_and_inconsistent_amounts_are_retained(self):
        for value in (None, "-1", "NaN", "Infinity", "1_000", " 1.58", 1.58, True, "1e1000000"):
            for index in (0, 1):
                with self.subTest(value=value, index=index):
                    quotes = pair()
                    quotes[index]["amount"] = value
                    self.assertEqual(prefer_member_quotes(quotes), quotes)
        for field, value in (("exact_api_hourly_amount", "1.579"),
                             ("price_source", {"native_amount_milli_cny": 1577, "field": "unverified"})):
            quotes = pair()
            quotes[1][field] = value
            self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_caller_decimal_context_cannot_round_away_valid_or_more_expensive_tiers(self):
        quotes = pair()
        more_expensive = deepcopy(quotes)
        more_expensive[1].update(amount="1.66", exact_api_hourly_amount="1.661")
        more_expensive[1]["price_source"]["native_amount_milli_cny"] = 1661
        # At precision 1, dividing milli-CNY would lose the meaningful digits;
        # caller rounding traps must not make this otherwise pure helper raise.
        with localcontext() as caller:
            caller.prec = 1
            caller.rounding = ROUND_DOWN
            caller.Emax, caller.Emin = 1, -1
            caller.traps[Inexact] = caller.traps[Rounded] = True
            caller.clear_flags()
            before = caller.copy()
            self.assertEqual(prefer_member_quotes(quotes), [quotes[1]])
            self.assertEqual(prefer_member_quotes(more_expensive), more_expensive)
            self.assertEqual(caller.prec, before.prec)
            self.assertEqual(caller.rounding, before.rounding)
            self.assertEqual((caller.Emin, caller.Emax), (before.Emin, before.Emax))
            self.assertEqual(caller.traps, before.traps)
            self.assertEqual(caller.flags, before.flags)

    def test_higher_member_prices_in_display_or_exact_precision_are_retained(self):
        for exact, displayed, milli in (("1.67", "1.67", 1670), ("1.661", "1.66", 1661)):
            quotes = pair()
            quotes[1].update(amount=displayed, exact_api_hourly_amount=exact)
            quotes[1]["price_source"]["native_amount_milli_cny"] = milli
            self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_equal_and_zero_finite_prices_can_select_explicit_member_tariff(self):
        for amount, milli in (("1.66", 1660), ("0.00", 0)):
            quotes = pair()
            for quote in quotes:
                quote.update(amount=amount, exact_api_hourly_amount=amount)
                quote["price_source"]["native_amount_milli_cny"] = milli
            self.assertEqual(prefer_member_quotes(quotes), [quotes[1]])

    def test_separate_regions_snapshots_and_machine_ids_each_keep_their_member_price(self):
        first, second = pair(), pair()
        for quote in second:
            quote.update(raw_sku="other-machine", regions=["west-B"],
                         location={"region": "west-B", "region_name": "西北B区"},
                         observed_at="2026-10-23T08:31:00+00:00")
        self.assertEqual(prefer_member_quotes(first + second), [first[1], second[1]])

    def test_unsupported_platform_cloud_types_and_page_rates_are_unchanged(self):
        for changes in ({"provider": "runpod"}, {"source_url": "https://www.autodl.com/market/list"},
                        {"source_type": "official_api"}, {"provider": "lambda"}):
            quotes = pair()
            for quote in quotes:
                quote.update(changes)
            quotes[0]["cloud_tier"], quotes[1]["cloud_tier"] = "community", "secure"
            self.assertEqual(prefer_member_quotes(quotes), quotes)

    def test_csv_option_defaults_off_and_never_changes_collection_statistics(self):
        result = envelope(pair())
        original = deepcopy(result)
        for profile in ("market", "compact", "catalog", "full"):
            with self.subTest(profile=profile):
                normal = rows(prices_to_csv(result, bilingual_headers=False, profile=profile))
                selected = rows(prices_to_csv(result, bilingual_headers=False, profile=profile, prefer_member=True))
                self.assertEqual(len(normal), 2)
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["amount"], "1.58")
                if profile == "full":
                    self.assertEqual(selected[0]["membership_required"], "true")
                else:
                    self.assertIn("会员", selected[0]["pricing_conditions"])
        self.assertEqual(result, original)
        with self.assertRaisesRegex(ValueError, "prefer_member must be boolean"):
            prices_to_csv(result, prefer_member=1)

    def test_cli_preference_csv_counts_reflect_export_and_json_remains_complete(self):
        result = envelope(pair())
        before = deepcopy(result)
        for profile, expected in (("market", "CSV market: 1 numeric GPU-hour quotes"),
                                  ("compact", "CSV comparison: 1 verified regional GPU-hour quotes"),
                                  ("catalog", "CSV member preference:"), ("full", "CSV member preference:")):
            with self.subTest(profile=profile):
                code, output, errors, _ = run_cli(["collect", "--format", "csv", "--csv-profile", profile,
                                                   "--prefer-member-prices"], result)
                self.assertEqual(code, 0)
                self.assertEqual(len(rows(output)), 1)
                self.assertIn(expected, errors)
                self.assertIn("1 ordinary rows omitted", errors)
        code, output, errors, _ = run_cli(["collect"], result)
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(json.loads(output), before)
        self.assertEqual(result, before)

    def test_cli_json_with_preference_is_a_configuration_error_before_collection(self):
        code, output, errors, collector = run_cli(["collect", "--prefer-member-prices"], envelope(pair()))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["error"]["code"], "configuration_error")
        self.assertIn("requires --format csv", errors)
        collector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
