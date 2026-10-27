"""Concrete offer accounting, geographic evidence and bounded anonymous access."""

from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import vast
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

OBSERVED = "2026-10-23T10:00:00+00:00"
FIXTURE = Path(__file__).parent / "fixtures" / "vast-public-offers.json"


def source():
    return json.loads(FIXTURE.read_text(), parse_float=Decimal)


class VastTests(unittest.TestCase):
    def test_concrete_offer_total_is_split_by_card_count_not_host_fraction(self):
        payload = source()
        rows = vast.parse_result(payload, observed_at=OBSERVED)["prices"]
        for raw, quote in zip(payload["offers"], rows):
            self.assertEqual(quote["gpu_count"], raw["num_gpus"])
            self.assertEqual(Decimal(quote["instance_price"]["amount"]), raw["dph_total"])
            self.assertEqual(Decimal(quote["amount"]) * raw["num_gpus"], raw["dph_total"])
            self.assertEqual(quote["resources"]["vcpus"], float(raw["cpu_cores_effective"]))
            self.assertEqual(quote["resources"]["storage_gb"], 8)
            self.assertEqual(quote["quote_status"], "quoted")
            self.assertEqual(quote["conditions"]["catalog_coverage"], "partial")
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertNotIn("public_ipaddr", json.dumps(quote))
        self.assertEqual(json.loads(json.dumps(rows)), rows)

    def test_country_only_never_becomes_region_or_uniform_national_rate(self):
        for location, code in (("Czechia, CZ", "CZ"), (", US", "US"), ("GB", "GB"),
                               ("Ireland, IE", "IE"), ("California", None),
                               ("Europe", None), ("London, ZZ", None), ("Washington", None)):
            payload = source()
            payload["offers"] = [payload["offers"][0]]
            payload["offers"][0]["geolocation"] = location
            result = vast.parse_result(payload, observed_at=OBSERVED)
            with self.subTest(location=location):
                if code is None:
                    self.assertEqual(result["prices"], [])
                    self.assertEqual(result["coverage"]["excluded_count"], 1)
                else:
                    quote = result["prices"][0]
                    self.assertEqual(quote["compute_countries"], [code])
                    self.assertEqual(quote["regions"], [])
                    self.assertFalse(quote["region_price_verified"])
                    self.assertEqual(quote["location_source"]["raw_location"], location)
                    self.assertEqual(quote["location_source"]["location_granularity"], "country")
                    self.assertFalse(quote["location_source"]["uniform_country_price"])

    def test_subnational_region_is_bound_to_same_offer_and_country(self):
        payload = source()
        payload["offers"] = [payload["offers"][0]]
        payload["offers"][0]["geolocation"] = "California, US"
        quote = vast.parse_result(payload, observed_at=OBSERVED)["prices"][0]
        self.assertEqual(quote["regions"], ["California, US"])
        self.assertEqual(quote["compute_countries"], ["US"])
        self.assertEqual(quote["zones"], [])
        self.assertTrue(quote["region_price_verified"])
        payload["offers"][0]["geolocation"] = "California, CA"
        self.assertEqual(vast.parse_result(payload, observed_at=OBSERVED)["prices"][0]["regions"], [])

    def test_exact_decimal_values_ignore_callers_precision_and_traps(self):
        payload = source()
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.Emax = 2
            ctx.traps[Inexact] = True
            result = vast.parse_result(payload, observed_at=OBSERVED)
        self.assertEqual(result["coverage"]["excluded_count"], 0)

    def test_bad_price_specs_and_unrequested_tiers_are_counted_not_fabricated(self):
        for field, value in (("dph_total", 0), ("dph_total", Decimal("NaN")),
                             ("dph_total", 1.2), ("dph_total", "1.2"),
                             ("dph_total", Decimal("0.0000001")),
                             ("num_gpus", Decimal("0.5")), ("num_gpus", True),
                             ("cpu_cores_effective", -1), ("cpu_ram", 0),
                             ("storage_cost", Decimal("0e-100000")),
                             ("disk_space", 7), ("gpu_frac", Decimal("1.5")),
                             ("is_bid", True), ("rentable", None), ("rented", None),
                             ("verification", "ambiguous"), ("gpu_name", "A100 MIG")):
            payload = source()
            payload["offers"][0][field] = value
            result = vast.parse_result(payload, observed_at=OBSERVED)
            with self.subTest(field=field, value=value):
                self.assertEqual(len(result["prices"]), 2)
                self.assertEqual(result["coverage"]["excluded_count"], 1)
                self.assertEqual(result["coverage"]["source_offer_count"], 3)

    def test_no_false_completeness_even_when_api_truncated_is_false_and_below_limit(self):
        for truncated in (False, True, None):
            payload = source()
            payload["truncated"] = truncated
            result = vast.parse_result(payload, observed_at=OBSERVED)
            self.assertEqual(result["status"], "partial")
            self.assertFalse(result["coverage"]["complete"])
            self.assertIsNone(result["coverage"]["marketplace_total"])
            self.assertEqual(result["coverage"]["api_truncated"], truncated)

    def test_duplicates_malformed_top_level_and_oversized_response_fail_closed(self):
        duplicate = source()
        duplicate["offers"].append(duplicate["offers"][0])
        for payload in ({}, {"offers": {}}, {"offers": [None]}, duplicate,
                        {"offers": [], "truncated": "false"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    vast.parse_result(payload, observed_at=OBSERVED)
        with self.assertRaises(ValueError):
            vast.parse_result(source(), observed_at=OBSERVED, limit=2)
        with self.assertRaises(FetchError):
            vast.parse_result({"error": "private server details"}, observed_at=OBSERVED)

    def test_empty_search_is_partial_not_old_prices_or_full_market_success(self):
        result = vast.parse_result({"offers": [], "truncated": False}, observed_at=OBSERVED)
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["status"], "partial")

    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_directory_and_per_model_read_only_anonymous_requests_have_explicit_storage(self, request):
        names = sorted({r["gpu_name"] for r in source()["offers"]})
        def respond(url, settings, **kwargs):
            if url == vast.GPU_DIRECTORY_URL:
                return {"success": True, "gpu_names": names}
            model = json.loads(kwargs["data"])["gpu_name"]["eq"]
            return {"offers": [r for r in source()["offers"] if r["gpu_name"] == model], "truncated": False}
        request.side_effect = respond
        result = vast.collect_result(settings=Settings(timeout_seconds=300, max_retries=10,
                                                       lambda_api_key="must-never-leave-local-settings"),
                                     observed_at=OBSERVED)
        self.assertEqual(len(result["prices"]), 3)
        self.assertEqual(request.call_count, len(names) + 1)
        args, kwargs = request.call_args_list[-1]
        self.assertEqual(args[0], vast.API_URL)
        self.assertEqual(args[1].timeout_seconds, 20)
        self.assertEqual(args[1].max_retries, 0)
        self.assertFalse(kwargs["authenticated"])
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(kwargs["method"], "POST")
        body = json.loads(kwargs["data"])
        self.assertEqual(body["allocated_storage"], 8)
        self.assertEqual(body["type"], "on-demand")
        self.assertEqual(body["limit"], 1000)
        self.assertIn("gpu_name", body)
        self.assertNotIn("rentable", body)
        self.assertNotIn("rented", body)
        self.assertNotIn("verified", body)
        self.assertNotIn("must-never-leave", str(kwargs))
        self.assertEqual(result["coverage"]["directory_model_count"], len(names))
        self.assertEqual(result["coverage"]["models_queried"], len(names))
        self.assertFalse(result["coverage"]["complete"])

    def test_unavailable_and_unverified_prices_are_retained_without_claiming_stock(self):
        payload = source()
        payload["offers"][0].update(rentable=False, rented=True, verification="unverified", gpu_name="Tesla T4")
        quote = vast.parse_result(payload, observed_at=OBSERVED)["prices"][0]
        self.assertEqual(quote["gpu_model"], "T4")
        self.assertEqual(quote["availability"], "unavailable")
        self.assertEqual(quote["conditions"]["verification"], "unverified")
        self.assertEqual(quote["instance_price"]["amount"], str(payload["offers"][0]["dph_total"]))

    def test_missing_optional_cpu_metadata_does_not_hide_a_real_price(self):
        for cpu in (None, 0, Decimal("0")):
            payload = source()
            payload["offers"][0].update(cpu_cores_effective=cpu, cpu_name="")
            quote = vast.parse_result(payload, observed_at=OBSERVED)["prices"][0]
            self.assertIsNone(quote["resources"]["vcpus"])
            self.assertIsNone(quote["resources"]["cpu_name"])
            self.assertEqual(quote["conditions"]["missing_resource_fields"], ["cpu_cores_effective", "cpu_name"])
            self.assertEqual(quote["instance_price"]["amount"], str(payload["offers"][0]["dph_total"]))

    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_model_search_failure_is_explicit_and_other_model_prices_survive(self, request):
        row = source()["offers"][0]
        def respond(url, settings, **kwargs):
            if url == vast.GPU_DIRECTORY_URL:
                return {"success": True, "gpu_names": [row["gpu_name"], "Tesla T4"]}
            if json.loads(kwargs["data"])["gpu_name"]["eq"] == "Tesla T4":
                raise FetchError("http_error", "pricing request rejected")
            return {"offers": [row], "truncated": False}
        request.side_effect = respond
        result = vast.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(len(result["prices"]), 1)
        self.assertEqual(result["coverage"]["models_queried"], 1)
        self.assertEqual(result["errors"][0]["gpu_name"], "Tesla T4")

    @patch("gpu_price_monitor.providers.vast.time.sleep")
    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_only_failed_models_retry_after_cooldown_and_keep_actual_request_count(self, request, sleep):
        row = source()["offers"][0]
        model = row["gpu_name"]
        attempts = {model: 0, "Tesla T4": 0}
        def respond(url, settings, **kwargs):
            if url == vast.GPU_DIRECTORY_URL:
                return {"gpu_names": [model, "Tesla T4"]}
            name = json.loads(kwargs["data"])["gpu_name"]["eq"]
            attempts[name] += 1
            if name == "Tesla T4" and attempts[name] == 1:
                raise FetchError("rate_limited", "The public source is temporarily rate limited.", True)
            copy = dict(row, gpu_name=name, id=row["id"] + (1 if name == "Tesla T4" else 0))
            return {"offers": [copy], "truncated": False}
        request.side_effect = respond
        result = vast.collect_result(settings=Settings(max_retries=2), observed_at=OBSERVED)
        self.assertEqual(attempts, {model: 1, "Tesla T4": 2})
        self.assertEqual(result["coverage"]["request_count"], 4)
        self.assertEqual(result["coverage"]["retry_request_count"], 1)
        self.assertEqual(result["coverage"]["models_queried"], 2)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["coverage"]["complete"])
        sleep.assert_called_once_with(60)
        self.assertTrue(all(q["observed_at"] != OBSERVED for q in result["prices"]))

    @patch("gpu_price_monitor.providers.vast.time.sleep")
    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_persistent_limit_is_bounded_and_zero_retry_setting_is_honored(self, request, sleep):
        def respond(url, settings, **kwargs):
            if url == vast.GPU_DIRECTORY_URL:
                return {"gpu_names": ["Tesla T4"]}
            raise FetchError("rate_limited", "The public source remains limited.", True)
        request.side_effect = respond
        for budget, expected in ((0, 2), (2, 4), (10, 4)):
            request.reset_mock()
            sleep.reset_mock()
            result = vast.collect_result(settings=Settings(max_retries=budget), observed_at=OBSERVED)
            self.assertEqual(request.call_count, expected)
            self.assertEqual(result["coverage"]["request_count"], expected)
            self.assertEqual(result["coverage"]["models_queried"], 0)
            self.assertEqual(result["errors"][0]["code"], "rate_limited")
            self.assertEqual(sleep.call_count, min(budget, 2))

    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_directory_invalid_or_cross_model_response_never_claims_coverage(self, request):
        for directory in ({"gpu_names": ["Tesla T4", "Tesla T4"]}, {"gpu_names": []}, {"success": False, "gpu_names": ["T4"]}):
            request.return_value = directory
            with self.assertRaises(ValueError):
                vast.collect_result(settings=Settings(), observed_at=OBSERVED)
        request.side_effect = [{"gpu_names": ["Tesla T4"]}, source()]
        result = vast.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(result["prices"], [])
        self.assertEqual(result["errors"][0]["code"], "invalid_model_response")

    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_denied_anonymous_access_surfaces_without_auth_or_cache_fallback(self, request):
        request.side_effect = FetchError("http_error", "The pricing source returned HTTP 403.")
        with self.assertRaises(FetchError) as raised:
            vast.collect_result(settings=Settings(), observed_at=OBSERVED)
        self.assertEqual(raised.exception.code, "http_error")
        request.assert_called_once()

    @patch("gpu_price_monitor.providers.vast.request_json")
    def test_invalid_limit_never_makes_request(self, request):
        for limit in (0, -1, 1001, True, "100"):
            with self.assertRaises(ValueError):
                vast.collect_result(settings=Settings(), observed_at=OBSERVED, limit=limit)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
