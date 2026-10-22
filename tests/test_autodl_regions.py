"""Official region names/DCs establish country only for eleven reviewed cases."""

from copy import deepcopy
import unittest

from gpu_price_monitor.providers import autodl_regions as regions


OBSERVED = "2026-10-22T08:00:00Z"
PUBLIC_ROWS = [
    ("west-B", "西北B区", "westDC3"),
    ("bj-B1", "北京B区", "beijingDC2"),
    ("west-C", "西北B区", "westDC3"),
    ("west-D", "西北B区", "westDC3"),
    ("west-E", "西北B区", "westDC3"),
    ("bj-B2", "北京B区", "beijingDC2"),
    ("bj-B3", "北京B区", "beijingDC2"),
    ("cq-A1", "重庆A区", "chongqingDC1"),
    ("nm-B1", "内蒙B区", "neimengDC3"),
    ("nm-B2", "内蒙B区", "neimengDC3"),
    ("beijing-A", "北京A区", "beijingDC1"),
    ("foshan-A", "佛山区", "foshanDC1"),
    ("beijing-C", "V100专区", "beijingDC3"),
    ("beijing-B", "北京A区", "beijingDC1"),
    ("beijing-D", "北京A区", "beijingDC1"),
    ("nm-A1", "A800专区", "neimengDC2"),
    ("beijing-E", "北京A区", "beijingDC1"),
    ("west-X", "西北企业区", "westDC2"),
    ("sh-A1", "摩尔线程专区", "shanghaiDC1"),
]
VERIFIED = {"bj-B1", "bj-B2", "bj-B3", "cq-A1", "nm-B1", "nm-B2",
            "beijing-A", "beijing-B", "beijing-D", "beijing-E", "foshan-A"}


def payload():
    return {"code": "Success", "data": [dict(region_sign=code, region_name=name, data_center=dc,
                                             country_code="untrusted-extra-country", setting={"unused": True})
                                         for code, name, dc in PUBLIC_ROWS], "request_id": "unrelated-do-not-return"}


def directory():
    return regions.parse_region_directory(payload(), observed_at=OBSERVED)


def market_quote(code="bj-B1", name="北京B区"):
    return {"provider": "autodl", "product_type": "gpu_container", "gpu_model": "RTX 4090",
            "amount": "1.98", "currency": "CNY", "unit": "gpu_hour", "billing_mode": "on_demand",
            "pricing_tier": "ordinary", "membership_required": False,
            "source_url": regions.MARKET_URL, "source_type": "authorized_browser",
            "regions": [code], "zones": [], "geographic_scope": "regions", "price_scope": "regional_quote",
            "region_price_verified": True, "location": {"region": code, "region_name": name},
            "availability": "available", "observed_at": OBSERVED}


class AutoDLRegionsTests(unittest.TestCase):
    def test_exact_public_identities_enrich_eleven_rows_and_leave_eight_unverified(self):
        metadata = directory()
        supplied = [market_quote(code, name) for code, name, _ in PUBLIC_ROWS]
        output, gaps = regions.enrich_market_quotes(supplied, region_directory=metadata)
        self.assertEqual(len(output), 19)
        self.assertEqual(len(gaps), 8)
        verified = {q["regions"][0] for q in output if q["compute_countries"]}
        self.assertEqual(verified, VERIFIED)
        self.assertEqual(len(verified), 11)
        for quote in output:
            with self.subTest(code=quote["regions"][0]):
                if quote["regions"][0] in VERIFIED:
                    self.assertEqual(quote["compute_countries"], ["CN"])
                    self.assertEqual(quote["location"]["country_name_zh"], "中国")
                    self.assertEqual(quote["location_source"]["country_basis"], "official_named_place_and_data_center_crossreference")
                    self.assertFalse(quote["location_source"]["country_field_provided_by_api"])
                    self.assertEqual(quote["location_source"]["documentation_url"], regions.DOCUMENTATION_URL)
                    self.assertEqual(quote["location_source"]["directory_observed_at"], OBSERVED)
                else:
                    self.assertEqual(quote["compute_countries"], [])
                    self.assertNotIn("country_code", quote["location"])
                    self.assertEqual(quote["location_source"]["country_status"], "not_verified")

    def test_prices_tiers_region_scope_and_source_records_do_not_change(self):
        original = market_quote()
        before = deepcopy(original)
        output = regions.enrich_market_quote(original, region_directory=directory())
        self.assertEqual(original, before)
        for field in ("amount", "currency", "unit", "billing_mode", "pricing_tier", "membership_required",
                      "regions", "zones", "geographic_scope", "price_scope", "region_price_verified",
                      "availability", "source_url", "source_type"):
            self.assertEqual(output[field], before[field])
        self.assertNotIn("统一", str(output))

    def test_region_code_prefixes_and_special_gpu_zones_never_determine_country(self):
        for code, name in (("beijing-C", "V100专区"), ("nm-A1", "A800专区"),
                           ("sh-A1", "摩尔线程专区"), ("west-B", "西北B区")):
            with self.subTest(code=code):
                output = regions.enrich_market_quote(market_quote(code, name), region_directory=directory())
                self.assertEqual(output["compute_countries"], [])
                self.assertNotIn("country_code", output["location"])
                self.assertIn("No reviewed explicit country evidence", output["location_source"]["reason"])
                self.assertEqual(output["location"]["region_name"], name)

    def test_changed_dc_name_or_market_directory_mismatch_clears_stale_country(self):
        for changed in ("data_center", "region_name", "market_name"):
            metadata, quote = directory(), market_quote()
            quote["compute_countries"] = ["US"]
            quote["location"].update(country_code="US", country_name="United States", country_name_zh="美国", country_source="old-static")
            if changed == "market_name":
                quote["location"]["region_name"] = "北京B区（改名）"
            else:
                metadata["bj-B1"][changed] = "changed"
            output = regions.enrich_market_quote(quote, region_directory=metadata)
            self.assertEqual(output["compute_countries"], [])
            self.assertNotIn("country_code", output["location"])
            self.assertNotIn("country_name", output["location"])
            self.assertNotIn("country_name_zh", output["location"])
            self.assertNotIn("country_source", output["location"])

    def test_missing_directory_or_new_unreviewed_region_does_not_reuse_a_known_place(self):
        quote = market_quote()
        output = regions.enrich_market_quote(quote, region_directory={})
        self.assertEqual(output["compute_countries"], [])
        self.assertIn("absent", output["location_source"]["reason"])
        body = payload()
        body["data"].append(dict(region_sign="beijing-future", region_name="北京A区", data_center="beijingDC1"))
        metadata = regions.parse_region_directory(body, observed_at=OBSERVED)
        output = regions.enrich_market_quote(market_quote("beijing-future", "北京A区"), region_directory=metadata)
        self.assertEqual(output["compute_countries"], [])

    def test_unlocated_homepage_or_multi_region_country_inference_is_rejected(self):
        for change in ({"source_url": "https://www.autodl.com/home"},
                       {"source_type": "public_page"}, {"geographic_scope": "platform_coverage"},
                       {"regions": ["bj-B1", "nm-B1"]}, {"provider": "other"},
                       {"product_type": "gpu_instance"}, {"unit": "gpu_month"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                regions.enrich_market_quote({**market_quote(), **change}, region_directory=directory())
        inconsistent = market_quote()
        inconsistent["location"]["region"] = "nm-B1"
        with self.assertRaises(ValueError):
            regions.enrich_market_quote(inconsistent, region_directory=directory())

    def test_public_metadata_projection_drops_extras_and_rejects_ambiguous_shapes(self):
        metadata = directory()
        self.assertEqual(set(metadata["bj-B1"]), {"region_sign", "region_name", "data_center", "source_url", "observed_at"})
        self.assertNotIn("untrusted-extra-country", str(metadata))
        self.assertNotIn("unrelated-do-not-return", str(metadata))
        for body in ({"code": "AuthorizeFailed", "data": []}, {"code": "Success", "data": []},
                     {"code": "Success", "data": [payload()["data"][0]] * 2}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                regions.parse_region_directory(body, observed_at=OBSERVED)
        for when in ("2026-10-22", "2026-10-22T08:00:00", None):
            with self.subTest(when=when), self.assertRaises(ValueError):
                regions.parse_region_directory(payload(), observed_at=when)


if __name__ == "__main__":
    unittest.main()
