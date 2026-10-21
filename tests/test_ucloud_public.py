"""Anonymous promotion API checks with a historical, reduced public fixture."""

from decimal import Decimal, Inexact, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from gpu_price_monitor.providers import ucloud_public
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURE = Path(__file__).parent / "fixtures" / "ucloud-public-catalog.json"
OBSERVED = "2026-10-20T10:00:00+00:00"


def source():
    data = json.loads(FIXTURE.read_text(), parse_float=Decimal)
    data.pop("_fixture_note")
    return data


def parse(data=None, observed_at=OBSERVED):
    return ucloud_public.parse_catalog(**(data or source()), observed_at=observed_at)


class UCloudPublicTests(unittest.TestCase):
    def test_monthly_configuration_prices_locations_and_eligibility(self):
        quotes = parse()
        self.assertEqual(len(quotes), 4)
        first, second = quotes[:2]
        self.assertEqual(first["unit"], "gpu_month")
        self.assertEqual(second["instance_price"]["amount"], "2877.24")
        self.assertEqual(second["amount"], "1438.62")
        self.assertEqual(second["gpu_count"], 2)
        self.assertEqual(second["resources"]["memory_mb"], 131072)
        self.assertEqual(second["resources"]["bandwidth_mbps"], 2)
        self.assertEqual(second["regions"], ["cn-sh2"])
        self.assertEqual(second["zones"], ["cn-sh2-02"])
        self.assertEqual(second["location"]["country_code"], "CN")
        for quote in quotes:
            self.assertEqual(quote["compute_countries"], [quote["location"]["country_code"]])
            self.assertEqual(quote["location_source"], {
                "api_url": "https://api.ucloud.cn/", "source_type": "official_public_api",
                "region_action": "ListAllRegions", "zone_action": "ListAllZones",
                "country_field": "CountryCode", "price_location_basis": "package_zones",
            })
            self.assertEqual(quote["billing_mode"], "monthly")
            self.assertEqual(quote["account_scope"], "public_promotion")
            self.assertEqual(quote["availability"], "offline")
            self.assertEqual(quote["source_type"], "official_public_api")
            self.assertEqual(quote["instance_price"]["unit"], "instance_month")
            self.assertFalse(quote["promotion"]["only_new_users"])
            self.assertFalse(quote["promotion"]["eligibility_verified"])
            self.assertIsNone(quote["effective_from"])
            self.assertIsNone(quote["effective_until"])
            self.assertIn("activity_end_at", quote["promotion"])
        self.assertEqual([q["promotion"]["purchase_limit"] for q in quotes], [3, 5, 5, 5])
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_modern_public_campaign_preserves_both_gpu_models_and_offline_state(self):
        modern = [q for q in parse() if q["promotion"]["activity_id"] == "10248"]
        self.assertEqual({q["gpu_model"] for q in modern}, {"4090_48G", "5090"})
        for quote in modern:
            self.assertEqual(quote["regions"], ["cn-wlcb"])
            self.assertEqual(quote["zones"], ["cn-wlcb-01"])
            self.assertEqual(quote["availability"], "offline")
            self.assertEqual(quote["promotion"]["activity_status"], "published")
            self.assertFalse(quote["promotion"]["eligibility_verified"])
            self.assertFalse(quote["promotion"]["only_new_users"])
        self.assertIn("5090", modern[1]["promotion"]["title"])

    def test_cents_and_gpu_allocation_do_not_use_callers_decimal_precision(self):
        data = source()
        package = data["packages"]["10204"]["Data"][0]
        package["CurPrice"] = Decimal("100")
        detail = json.loads(package["PackageDetails"])
        detail["Gpu"] = "3"
        package["PackageDetails"] = json.dumps(detail)
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.Emax = 2
            quote = parse(data)[0]
        self.assertEqual(quote["instance_price"]["amount"], "1")
        self.assertEqual(quote["amount"], "0.333333333333")

    def test_no_offline_flag_does_not_prove_availability(self):
        data = source()
        data["flags"]["10204"]["Data"] = []
        self.assertEqual(parse(data)[0]["availability"], "unknown")

    def test_ended_upcoming_and_unpublished_activity_is_explicit(self):
        for begin, end, state, expected in ((1, 2, "published", "ended"),
                                            (2000000000, 2100000000, "published", "upcoming"),
                                            (1, 2100000000, "freezed", "offline")):
            data = source()
            metadata = next(r for r in data["activities"]["Data"] if r["ActivityId"] == "10204")
            metadata.update(BeginTime=begin, EndTime=end, State=state)
            quote = parse(data)[0]
            self.assertEqual(quote["availability"], expected)
            self.assertEqual(quote["promotion"]["activity_status"], expected)

    def test_multiple_zones_produce_one_record_per_explicit_location(self):
        data = source()
        row = data["packages"]["10204"]["Data"][0]
        row["Zones"] = ["cn-bj2-02", "cn-wlcb-01"]
        quotes = parse(data)
        self.assertEqual(len(quotes), 5)
        self.assertEqual([q["regions"] for q in quotes[:2]], [["cn-bj2"], ["cn-wlcb"]])
        self.assertTrue(all(len(q["zones"]) == len(q["regions"]) == 1 for q in quotes))

    def test_country_is_bound_to_each_package_zone_not_the_catalog_or_prefix(self):
        data = source()
        # Synthetic multi-country package; the historical fixture does not
        # assert that this promotion was offered in the additional zones.
        data["packages"]["10204"]["Data"][0]["Zones"] = ["us-ca-01", "sg-01"]
        quotes = parse(data)
        self.assertEqual([q["compute_countries"] for q in quotes[:2]], [["US"], ["SG"]])
        self.assertEqual([q["regions"] for q in quotes[:2]], [["us-ca"], ["sg"]])
        # Preserve the provider's CountryCode classification rather than
        # infer a different country from HK/TW region names.
        catalog = ucloud_public.parse_location_catalog(data["regions"], data["zones"])
        self.assertEqual(catalog["hk-02"]["country_code"], "CN")
        self.assertEqual(catalog["tw-tp-01"]["country_code"], "CN")

    def test_location_catalog_and_lookup_return_only_public_location_fields(self):
        data = source()
        data["regions"]["Regions"][0]["unrelated"] = "not-for-output"
        data["zones"]["Zones"][0]["unrelated"] = "not-for-output"
        catalog = ucloud_public.parse_location_catalog(data["regions"], data["zones"])
        location = ucloud_public.resolve_location(catalog, region="cn-bj1", zone="cn-bj1-01")
        self.assertEqual(set(location), {"region", "zone", "country_code", "region_name", "zone_name"})
        self.assertNotIn("not-for-output", json.dumps(catalog))
        # A caller-supplied parsed map cannot leak arbitrary fields either.
        catalog["cn-bj1-01"]["unrelated"] = "not-for-output"
        self.assertNotIn("not-for-output", json.dumps(
            ucloud_public.resolve_location(catalog, region="cn-bj1", zone="cn-bj1-01")))

    def test_location_catalog_rejects_missing_country_duplicate_or_orphan_mapping(self):
        invalid = []
        for country in (None, "", "Europe", "cn", 1):
            data = source()
            data["regions"]["Regions"][0]["CountryCode"] = country
            invalid.append(data)
        data = source()
        data["regions"]["Regions"].append(dict(data["regions"]["Regions"][0]))
        invalid.append(data)
        data = source()
        data["zones"]["Zones"][0]["Region"] = "unknown-region"
        invalid.append(data)
        data = source()
        data["zones"]["Zones"].append(dict(data["zones"]["Zones"][0]))
        invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                ucloud_public.parse_location_catalog(data["regions"], data["zones"])

    def test_location_lookup_never_borrows_a_country_for_an_unverified_pair(self):
        data = source()
        catalog = ucloud_public.parse_location_catalog(data["regions"], data["zones"])
        for region, zone in (("cn-bj2", "us-ca-01"), ("cn-bj2", "cn-bj2-unknown")):
            with self.subTest(region=region, zone=zone), self.assertRaises(FetchError) as captured:
                ucloud_public.resolve_location(catalog, region=region, zone=zone)
            self.assertEqual(captured.exception.code, "unverifiable_geography")

    @patch("gpu_price_monitor.providers.ucloud_public.request_json")
    def test_location_loader_makes_only_two_anonymous_directory_queries(self, request):
        data = source()
        request.side_effect = [data["regions"], data["zones"]]
        settings = Settings(ucloud_public_key="unused-public", ucloud_private_key="unused-private")
        catalog = ucloud_public.load_location_catalog(settings=settings)
        self.assertEqual(request.call_count, 2)
        for call, action in zip(request.call_args_list, ("ListAllRegions", "ListAllZones")):
            self.assertEqual(call.args, ("https://api.ucloud.cn/", settings))
            self.assertFalse(call.kwargs["authenticated"])
            self.assertEqual(call.kwargs["method"], "POST")
            self.assertEqual(parse_qs(call.kwargs["data"].decode()), {"Action": [action]})
            self.assertNotIn("Authorization", call.kwargs["headers"])
        self.assertNotIn("unused-", json.dumps(catalog))

    def test_bad_units_partial_results_duplicate_packages_and_unknown_zones_fail(self):
        mutations = []
        for update in ({"DurationUnit": "hour", "Durations": [24]}, {"Durations": [1, 3]},
                       {"Durations": [True]}, {"CurPrice": -1}, {"CurPrice": 1.5},
                       {"CurPrice": Decimal("NaN")}, {"OriginalPrice": "61041"},
                       {"Zones": ["unknown-zone"]}, {"Zones": ["cn-bj2-02", "cn-bj2-02"]},
                       {"PackageType": "uphost"}, {"DiscountAllowRenew": True}):
            data = source()
            data["packages"]["10204"]["Data"][0].update(update)
            mutations.append(data)
        data = source()
        data["packages"]["10204"]["TotalCount"] = 2
        mutations.append(data)
        data = source()
        data["packages"]["10204"]["Data"] *= 2
        data["packages"]["10204"]["TotalCount"] = 2
        mutations.append(data)
        for data in mutations:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse(data)

    def test_fractional_gpu_or_nonunique_detail_json_is_rejected(self):
        for raw in ('{"MachineType":"G","MachineType":"N"}', "[" * 1500 + "]" * 1500,
                    json.dumps({**json.loads(source()["packages"]["10204"]["Data"][0]["PackageDetails"]), "gpu_type": "T4/4"})):
            data = source()
            data["packages"]["10204"]["Data"][0]["PackageDetails"] = raw
            with self.assertRaises(ValueError):
                parse(data)

    def test_api_error_message_is_never_echoed(self):
        data = source()
        data["packages"]["10204"] = {"RetCode": 170, "Message": "test-secret"}
        with self.assertRaises(FetchError) as captured:
            parse(data)
        self.assertEqual(captured.exception.code, "public_api_error")
        self.assertNotIn("test-secret", str(captured.exception))

    @patch("gpu_price_monitor.providers.ucloud_public.request_json")
    def test_collection_is_only_nine_anonymous_readonly_requests(self, request):
        data = source()
        def respond(url, settings, **kwargs):
            self.assertEqual(url, "https://api.ucloud.cn/")
            self.assertFalse(kwargs["authenticated"])
            self.assertEqual(kwargs["method"], "POST")
            fields = {k: v[0] for k, v in parse_qs(kwargs["data"].decode()).items()}
            self.assertNotIn("PublicKey", fields)
            self.assertNotIn("Signature", fields)
            self.assertNotIn("Authorization", kwargs["headers"])
            action = fields["Action"]
            if action == "ListActivity":
                return data["activities"]
            if action == "ListAllRegions":
                return data["regions"]
            if action == "ListAllZones":
                return data["zones"]
            if action in ("ListPackage", "GetActivityFlags"):
                return data["packages" if action == "ListPackage" else "flags"][fields["ActivityId"]]
            self.fail("Unexpected API action")
        request.side_effect = respond
        settings = Settings(providers=("ucloud",), ucloud_public_key="unused-public", ucloud_private_key="unused-private")
        quotes = ucloud_public.collect_quotes(settings=settings, observed_at=OBSERVED)
        self.assertEqual(request.call_count, 9)
        self.assertNotIn("unused-", json.dumps(quotes))


if __name__ == "__main__":
    unittest.main()
