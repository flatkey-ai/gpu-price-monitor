"""Catalog hardware references stay bound to their own price, tier and count."""

from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
import unittest
from unittest.mock import patch

from gpu_price_monitor.filters import apply_filters
from gpu_price_monitor.providers import runpod
from gpu_price_monitor.settings import Settings


OBSERVED = "2026-11-23T03:03:12+00:00"
SKU = "NVIDIA RTX 4000 Ada Generation"


def source():
    # Contract fixture uses the native lowestPrice shape observed 2026-11-23.
    # Test prices/resources are not runtime defaults or live acceptance evidence.
    return {"data": {"gpuTypes": [{
        "id": SKU, "displayName": "RTX 4000 Ada", "memoryInGb": 20,
        "secureCloud": True, "communityCloud": True,
        "securePrice": Decimal("0.28"), "communityPrice": Decimal("0.20"),
        "secureOneGpu": {"uninterruptablePrice": Decimal("0.28"),
                         "stockStatus": "Low", "minVcpu": 8, "minMemory": 50},
        "communityOneGpu": {"uninterruptablePrice": None,
                            "stockStatus": None, "minVcpu": None, "minMemory": None},
    }]}}


def parse(payload):
    return {q["cloud_tier"]: q for q in runpod.parse_catalog(payload, observed_at=OBSERVED)}


class RunpodCatalogResourceTests(unittest.TestCase):
    def test_reference_identity_uses_the_catalogs_existing_whitespace_normalization(self):
        payload = source()
        payload["data"]["gpuTypes"][0]["id"] = "  NVIDIA  RTX 4000 Ada Generation  "
        quote = parse(payload)["secure"]
        self.assertEqual(quote["raw_sku"], SKU)
        self.assertEqual(quote["resources"]["vcpus"], 8)

    def test_available_same_price_reference_does_not_change_catalog_semantics(self):
        payload = source()
        before = deepcopy(payload)
        rows = parse(payload)
        secure, community = rows["secure"], rows["community"]
        self.assertEqual(secure["resources"], {"resource_basis": "minimum", "vcpus": 8, "memory_gb": 50})
        self.assertEqual(secure["gpu_count"], 1)
        self.assertEqual(secure["conditions"]["quote_request"], {"gpuCount": 1, "secureCloud": True})
        self.assertEqual((secure["amount"], secure["price_basis"], secure["quote_status"], secure["availability"]),
                         ("0.28", "advertised_per_gpu", "quoted", "unknown"))
        self.assertEqual((secure["regions"], secure["zones"], secure["observed_at"]), ([], [], OBSERVED))
        self.assertNotIn("storage_gb", secure["resources"])
        self.assertNotIn("instance_price", secure)
        self.assertNotIn("resources", community)
        self.assertIsNone(community["gpu_count"])
        self.assertEqual(community["amount"], "0.20")
        self.assertEqual(payload, before)
        self.assertEqual(apply_filters(list(rows.values()), {"gpu_counts": [2]}), [])

    def test_cloud_tiers_and_native_skus_never_share_minima(self):
        payload = source()
        base = payload["data"]["gpuTypes"][0]
        base["communityOneGpu"] = {"uninterruptablePrice": Decimal("0.20"),
                                   "stockStatus": "High", "minVcpu": 4, "minMemory": 16}
        other = deepcopy(base)
        other.update(id="Other RTX 4000 Ada SKU", securePrice=Decimal("0.40"))
        other["secureOneGpu"].update(uninterruptablePrice=Decimal("0.40"), minVcpu=24, minMemory=128)
        payload["data"]["gpuTypes"].append(other)
        rows = {(q["raw_sku"], q["cloud_tier"]): q for q in runpod.parse_catalog(payload, observed_at=OBSERVED)}
        self.assertEqual(rows[SKU, "secure"]["resources"]["vcpus"], 8)
        self.assertEqual(rows[SKU, "community"]["resources"]["vcpus"], 4)
        self.assertEqual(rows[other["id"], "secure"]["resources"]["vcpus"], 24)
        self.assertFalse(rows[SKU, "community"]["conditions"]["quote_request"]["secureCloud"])

    def test_missing_prices_stock_or_minima_keep_catalog_unenriched(self):
        for changes in ({"uninterruptablePrice": None}, {"uninterruptablePrice": 0},
                        {"uninterruptablePrice": Decimal("0.281")}, {"stockStatus": "None"},
                        {"stockStatus": None}, {"stockStatus": "Unexpected"},
                        {"minVcpu": None, "minMemory": None}):
            payload = source()
            payload["data"]["gpuTypes"][0]["secureOneGpu"].update(changes)
            with self.subTest(changes=changes):
                quote = parse(payload)["secure"]
                self.assertEqual(quote["amount"], "0.28")
                self.assertIsNone(quote["gpu_count"])
                self.assertNotIn("resources", quote)
                self.assertNotIn("quote_request", quote["conditions"])
        for optional in (None, {}):
            payload = source()
            payload["data"]["gpuTypes"][0]["secureOneGpu"] = optional
            self.assertNotIn("resources", parse(payload)["secure"])

    def test_catalog_amount_must_match_without_rounding_or_decimal_context_loss(self):
        payload = source()
        payload["data"]["gpuTypes"][0]["securePrice"] = Decimal("0.280000000000000000000001")
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            quote = parse(payload)["secure"]
        self.assertEqual(quote["amount"], "0.280000000000000000000001")
        self.assertNotIn("resources", quote)

    def test_partial_resources_stay_partial_and_malformed_minima_fail_closed(self):
        payload = source()
        payload["data"]["gpuTypes"][0]["secureOneGpu"]["minVcpu"] = None
        self.assertEqual(parse(payload)["secure"]["resources"], {"resource_basis": "minimum", "memory_gb": 50})
        for field in ("minVcpu", "minMemory"):
            for bad in (True, 0, -1, "8", Decimal("8.5")):
                payload = source()
                payload["data"]["gpuTypes"][0]["secureOneGpu"][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    parse(payload)

    @patch.object(runpod, "request_json")
    def test_complete_collection_does_not_attach_global_minima_to_regional_prices(self, request):
        center = {"data": {"dataCenters": [{"id": "US-KS-2", "name": "US-KS-2", "location": "United States"}]}}
        regional = {"data": {"gpuTypes": [{"id": SKU,
            "secure": {"uninterruptablePrice": Decimal("0.35"), "stockStatus": "High", "minVcpu": 16, "minMemory": 64},
            "community": None}]}}
        request.side_effect = [source(), center, regional]
        result = runpod.collect_result(settings=Settings(providers=("runpod",), catalog_scope="complete"), observed_at=OBSERVED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["coverage"]["catalog_quote_count"], 2)
        self.assertEqual(result["coverage"]["regional_quote_count"], 1)
        catalog = next(q for q in result["prices"] if q["cloud_tier"] == "secure" and not q["regions"])
        quote = next(q for q in result["prices"] if q["regions"])
        self.assertEqual(catalog["resources"]["memory_gb"], 50)
        self.assertNotIn("resources", quote)
        self.assertEqual((quote["amount"], quote["quote_status"], quote["conditions"]["minimum_ram_gb"]),
                         ("0.35", "starting_at", 64))
        self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
