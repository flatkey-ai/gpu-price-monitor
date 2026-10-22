"""Offline console catalog parsing retains configuration and tariff limitations."""

from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import lambda_cloud, lambda_console
from gpu_price_monitor.transport import FetchError


FIXTURES = Path(__file__).parent / "fixtures"
CLUSTERS = FIXTURES / "lambda-console-cluster-types-20261022.json"
OBSERVED = "2026-10-22T02:00:00+00:00"
_DEFAULT = object()


class LambdaConsoleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.transport = self.stack.enter_context(patch(
            "gpu_price_monitor.transport._request_text",
            side_effect=AssertionError("Console parsers must not contact a provider"),
        ))
        self.socket = self.stack.enter_context(patch(
            "socket.create_connection",
            side_effect=AssertionError("Console parsers must not open sockets"),
        ))
        self.clusters = json.loads(CLUSTERS.read_text(encoding="utf-8"))
        self.instances = json.loads((FIXTURES / "lambda-instance-types.json").read_text(encoding="utf-8"))
        self.console_instances = json.loads(
            (FIXTURES / "lambda-console-instance-types-20261022.json").read_text(encoding="utf-8"))
        self.console_regions = json.loads(
            (FIXTURES / "lambda-console-regions-20261022.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.transport.assert_not_called()
        self.socket.assert_not_called()

    def parse_clusters(self, payload=_DEFAULT):
        return lambda_console.parse_cluster_prices(
            self.clusters if payload is _DEFAULT else payload, observed_at=OBSERVED)

    def parse_instances(self, payload=_DEFAULT):
        return lambda_console.parse_instance_prices(
            self.instances if payload is _DEFAULT else payload, observed_at=OBSERVED)

    def assert_unlocated_capacity(self, quote, capacity):
        self.assertEqual(quote["capacity_regions"], [item["name"] for item in capacity])
        self.assertEqual(quote["capacity_locations"], capacity)
        self.assertEqual(quote["regions"], [])
        self.assertEqual(quote["zones"], [])
        self.assertEqual(quote["compute_countries"], [])
        self.assertFalse(quote["region_price_verified"])

    def test_real_cluster_fixture_is_a_whitelist_of_quote_and_capacity_fields(self):
        self.assertEqual(set(self.clusters), {"data"})
        self.assertEqual(len(self.clusters["data"]), 14)
        for row in self.clusters["data"]:
            self.assertEqual(set(row), {"cluster_type", "regions_available"})
            cluster = row["cluster_type"]
            self.assertEqual(set(cluster), {
                "worker_instance_type", "num_workers", "num_gpus", "price_cents_per_hour",
                "price_cents_per_gpu_hour", "description",
            })
            worker = cluster["worker_instance_type"]
            self.assertEqual(set(worker), {
                "name", "description", "gpu_description", "price_cents_per_hour", "specs", "architecture",
            })
            self.assertEqual(set(worker["specs"]), {"vcpus", "memory_gib", "storage_gib", "gpus"})
            for location in row["regions_available"]:
                self.assertEqual(set(location), {"name", "description"})

    def test_fourteen_cluster_configurations_preserve_six_reported_gpu_rate_groups(self):
        quotes = self.parse_clusters()
        self.assertEqual(len(quotes), 14)
        self.assertEqual(len({(q["gpu_model"], q["amount"]) for q in quotes}), 6)
        self.assertEqual({q["gpu_model"] for q in quotes}, {"H100", "B200"})
        by_model = {
            model: {q["selected_configuration"]["cluster_gpu_count"]: q["amount"]
                    for q in quotes if q["gpu_model"] == model}
            for model in ("H100", "B200")
        }
        self.assertEqual(by_model, {
            "H100": {16: "6.16", 32: "6.16", 64: "5.85", 128: "5.85", 256: "5.54", 512: "5.54"},
            "B200": {16: "9.86", 32: "9.86", 64: "9.36", 128: "9.36",
                     256: "8.87", 512: "8.87", 1024: "8.87", 1536: "8.87"},
        })
        self.assertEqual(json.loads(json.dumps(quotes, allow_nan=False)), quotes)

    def test_cluster_configuration_is_not_a_node_or_instance_gpu_count(self):
        for row, quote in zip(self.clusters["data"], self.parse_clusters()):
            cluster = row["cluster_type"]
            worker = cluster["worker_instance_type"]
            self.assertEqual(quote["product_type"], "gpu_cluster")
            self.assertEqual(quote["product_line"], "1-Click Clusters")
            self.assertEqual(quote["billing_mode"], "reserved")
            self.assertIsNone(quote["gpu_count"])
            self.assertEqual(quote["selected_configuration"], {
                "worker_instance_type": worker["name"],
                "cluster_gpu_count": cluster["num_gpus"],
                "cluster_gpu_count_relation": "exact",
                "num_workers": cluster["num_workers"],
                "gpus_per_worker": worker["specs"]["gpus"],
            })
            self.assertNotIn("instance_price", quote)
            self.assertNotIn("node_price", quote)
            self.assertNotIn("worker_price", quote)

    def test_gpu_hour_rate_is_authoritative_and_raw_total_conflicts_are_audited(self):
        for row, quote in zip(self.clusters["data"], self.parse_clusters()):
            cluster = row["cluster_type"]
            self.assertEqual(Decimal(quote["amount"]), Decimal(cluster["price_cents_per_gpu_hour"]) / 100)
            self.assertEqual((quote["currency"], quote["unit"]), ("USD", "gpu_hour"))
            self.assertEqual(quote["source_price_fields"], {
                "cluster_type.price_cents_per_gpu_hour": cluster["price_cents_per_gpu_hour"],
                "cluster_type.price_cents_per_hour": cluster["price_cents_per_hour"],
                "cluster_type.worker_instance_type.price_cents_per_hour":
                    cluster["worker_instance_type"]["price_cents_per_hour"],
            })
            self.assertIs(quote["source_field_conflict"], True)
            total = quote["computed_cluster_total"]
            self.assertEqual(Decimal(total["amount"]), Decimal(quote["amount"]) * cluster["num_gpus"])
            self.assertEqual((total["currency"], total["unit"]), ("USD", "cluster_hour"))
            self.assertEqual(total["formula"], "price_cents_per_gpu_hour * num_gpus / 100")
            self.assertIs(total["independent_provider_quote"], False)

    def test_consistent_raw_total_clears_conflict_without_changing_the_gpu_rate(self):
        payload = deepcopy(self.clusters)
        cluster = payload["data"][0]["cluster_type"]
        cluster["price_cents_per_hour"] = cluster["price_cents_per_gpu_hour"] * cluster["num_gpus"]
        self.assertIs(self.parse_clusters(payload)[0]["source_field_conflict"], True)
        worker = cluster["worker_instance_type"]
        worker["price_cents_per_hour"] = cluster["price_cents_per_gpu_hour"] * worker["specs"]["gpus"]
        quote = self.parse_clusters(payload)[0]
        self.assertIs(quote["source_field_conflict"], False)
        self.assertEqual(quote["amount"], "6.16")

    def test_cluster_terms_remain_unverified_without_an_invented_minimum_duration(self):
        for quote in self.parse_clusters():
            self.assertIs(quote["duration_unverified"], True)
            self.assertIs(quote["pricing_terms_unverified"], True)
            self.assertIs(quote["source_conditions"]["duration_unverified"], True)
            self.assertIs(quote["source_conditions"]["pricing_terms_unverified"], True)
            self.assertIsNone(quote["source_conditions"]["reservation_term"])
            self.assertNotIn("minimum_commitment", quote)
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertIsNone(quote["effective_from"])
            self.assertIsNone(quote["effective_until"])

    def test_cluster_currency_and_unit_have_separate_official_evidence(self):
        for quote in self.parse_clusters():
            self.assertEqual(quote["source_url"], lambda_console.RESERVED_CLUSTER_TYPES_URL)
            self.assertEqual(quote["source_type"], "official_internal_api")
            self.assertEqual(quote["auth_kind"], "session")
            self.assertEqual(quote["account_scope"], "authenticated_console_catalog")
            evidence = quote["pricing_evidence"]
            self.assertEqual(evidence["currency"]["value"], "USD")
            self.assertRegex(evidence["currency"]["source_url"], r"^https://(?:[^/]+\.)?lambda\.ai/")
            self.assertEqual(evidence["unit"]["value"], "gpu_hour")
            self.assertIn("price_cents_per_gpu_hour", evidence["unit"]["source_field"])
            self.assertEqual(evidence["unit"]["source_url"], evidence["frontend_source_url"])
            self.assertRegex(evidence["frontend_source_url"], r"^https://cloud\.lambda\.ai/.*\.js(?:\?.*)?$")

    def test_capacity_descriptions_are_retained_without_claiming_regional_prices(self):
        for row, quote in zip(self.clusters["data"], self.parse_clusters()):
            self.assert_unlocated_capacity(quote, row["regions_available"])
        first = self.parse_clusters()[0]
        self.assertIn({"name": "us-east-2", "description": "Washington DC, USA"}, first["capacity_locations"])

    def test_empty_cluster_capacity_does_not_remove_a_catalog_quote(self):
        payload = deepcopy(self.clusters)
        payload["data"][0]["regions_available"] = []
        quotes = self.parse_clusters(payload)
        self.assertEqual(len(quotes), 14)
        self.assertEqual(quotes[0]["amount"], "6.16")
        self.assert_unlocated_capacity(quotes[0], [])

    def test_instance_parser_keeps_official_instance_arithmetic_and_capacity_descriptions(self):
        before = deepcopy(self.instances)
        reference = lambda_cloud.parse_prices(self.instances, observed_at=OBSERVED)
        quotes = self.parse_instances()
        self.assertEqual(len(quotes), len(reference))
        for quote, official in zip(quotes, reference):
            for field in ("amount", "currency", "unit", "gpu_count", "gpu_model", "instance_price",
                          "resources", "raw_sku", "billing_mode"):
                self.assertEqual(quote[field], official[field])
            self.assertEqual(quote["source_url"], lambda_console.INSTANCE_TYPES_URL)
            self.assertEqual(quote["source_type"], "official_internal_api")
            self.assertEqual(quote["auth_kind"], "session")
            capacity = self.instances["data"][quote["raw_sku"]]["regions_with_capacity_available"]
            self.assert_unlocated_capacity(quote, capacity)
        self.assertEqual(self.instances, before)

    def test_real_instance_catalog_excludes_two_cpu_skus_with_explicit_audit_records(self):
        before = deepcopy(self.console_instances)
        outcome = lambda_console.parse_instance_catalog(self.console_instances, observed_at=OBSERVED)
        self.assertEqual(outcome["source_record_count"], 24)
        self.assertEqual(outcome["excluded_non_gpu_record_count"], 2)
        self.assertEqual(len(outcome["prices"]), 22)
        self.assertEqual(outcome["excluded_non_gpu_records"], [
            {"raw_sku": "cpu_4x_general", "product_type": "cpu_instance", "gpu_count": 0,
             "reason": "zero_gpu_instance"},
            {"raw_sku": "cpu_4x_generalx", "product_type": "cpu_instance", "gpu_count": 0,
             "reason": "zero_gpu_instance"},
        ])
        self.assertTrue(all(quote["gpu_count"] > 0 for quote in outcome["prices"]))
        self.assertEqual(self.parse_instances(self.console_instances), outcome["prices"])
        self.assertEqual(self.console_instances, before)

    def test_real_instance_catalog_keeps_both_v100_skus_and_never_adds_public_b200_configuration(self):
        quotes = self.parse_instances(self.console_instances)
        skus = {quote["raw_sku"] for quote in quotes}
        self.assertTrue({"gpu_8x_v100", "gpu_8x_v100_n"}.issubset(skus))
        self.assertNotIn("gpu_4x_b200", skus)
        self.assertEqual(len(skus), 22)
        for quote in quotes:
            capacity = self.console_instances["data"][quote["raw_sku"]]["regions_with_capacity_available"]
            self.assert_unlocated_capacity(quote, capacity)

    def test_invalid_zero_gpu_records_are_not_silently_hidden_as_cpu_exclusions(self):
        for field, value in (("gpus", False), ("gpus", -1), ("price_cents_per_hour", -1),
                             ("price_cents_per_hour", True)):
            payload = deepcopy(self.console_instances)
            instance = payload["data"]["cpu_4x_general"]["instance_type"]
            target = instance["specs"] if field == "gpus" else instance
            target[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                lambda_console.parse_instance_catalog(payload, observed_at=OBSERVED)

    def test_empty_instance_catalog_reports_no_source_or_excluded_records(self):
        outcome = lambda_console.parse_instance_catalog({"data": {}}, observed_at=OBSERVED)
        self.assertEqual(outcome["prices"], [])
        self.assertEqual(outcome["source_record_count"], 0)
        self.assertEqual(outcome["excluded_non_gpu_records"], [])
        self.assertEqual(outcome["excluded_non_gpu_record_count"], 0)

    def test_instance_fixture_contains_only_public_sku_specs_and_capacity_metadata(self):
        self.assertEqual(set(self.console_instances), {"data"})
        for row in self.console_instances["data"].values():
            self.assertEqual(set(row), {"instance_type", "regions_with_capacity_available"})
            self.assertEqual(set(row["instance_type"]), {
                "name", "description", "gpu_description", "price_cents_per_hour", "specs", "architecture",
            })
            self.assertEqual(set(row["instance_type"]["specs"]), {
                "vcpus", "memory_gib", "storage_gib", "gpus",
            })
            for region in row["regions_with_capacity_available"]:
                self.assertTrue({"name", "description"}.issubset(region))
                self.assertTrue(set(region).issubset({"name", "description", "dedicated"}))

    def test_region_parser_retains_eighteen_original_descriptions_without_inferred_countries(self):
        before = deepcopy(self.console_regions)
        regions = lambda_console.parse_regions(self.console_regions)
        self.assertEqual(len(regions), 18)
        self.assertEqual(regions, self.console_regions["data"])
        self.assertIn({"name": "europe-central-1", "description": "Germany"}, regions)
        self.assertIn({"name": "me-west-1", "description": "Israel"}, regions)
        self.assertTrue(all(set(region) == {"name", "description"} for region in regions))
        self.assertEqual(self.console_regions, before)
        self.assertEqual(lambda_console.parse_regions({"data": []}), [])

    def test_region_parser_preserves_explicit_dedicated_boolean_and_rejects_duplicate_names(self):
        payload = {"data": [{"name": "test-region", "description": "Provider supplied location", "dedicated": True}]}
        self.assertEqual(lambda_console.parse_regions(payload), payload["data"])
        payload["data"].append({"name": "test-region", "description": "Changed description"})
        with self.assertRaises(ValueError):
            lambda_console.parse_regions(payload)
        for value in (None, [], {}, {"data": None}, {"data": {}}, {"data": [None]},
                      {"data": [{"name": "region", "description": "Location", "dedicated": "yes"}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lambda_console.parse_regions(value)

    def test_parsers_are_pure_and_preserve_explicit_empty_catalogs(self):
        before = deepcopy(self.clusters)
        first = self.parse_clusters()
        self.assertEqual(self.parse_clusters(), first)
        self.assertEqual(self.clusters, before)
        self.assertEqual(self.parse_clusters({"data": []}), [])
        self.assertEqual(self.parse_instances({"data": {}}), [])

    def test_invalid_top_level_and_entry_schemas_fail_closed(self):
        for payload in (None, [], {}, {"data": None}, {"data": {}}, {"data": [None]},
                        {"data": [{"cluster_type": {}}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.parse_clusters(payload)
        for field in ("worker_instance_type", "num_workers", "num_gpus", "price_cents_per_gpu_hour"):
            payload = deepcopy(self.clusters)
            del payload["data"][0]["cluster_type"][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.parse_clusters(payload)

    def test_changed_units_or_currency_are_rejected_instead_of_relabelled(self):
        for change in ("gpu_month", "cluster_currency", "worker_unit"):
            payload = deepcopy(self.clusters)
            cluster = payload["data"][0]["cluster_type"]
            if change == "gpu_month":
                cluster["price_cents_per_gpu_month"] = cluster.pop("price_cents_per_gpu_hour")
            elif change == "cluster_currency":
                cluster["currency"] = "EUR"
            else:
                cluster["worker_instance_type"]["unit"] = "instance_month"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.parse_clusters(payload)
        payload = deepcopy(self.instances)
        next(iter(payload["data"].values()))["instance_type"]["currency"] = "EUR"
        with self.assertRaises(ValueError):
            self.parse_instances(payload)

    def test_non_integer_negative_and_boolean_price_fields_are_rejected(self):
        for field in ("price_cents_per_gpu_hour", "price_cents_per_hour", "worker_price"):
            for value in (None, True, False, -1, 616.0, Decimal("616"), "616"):
                payload = deepcopy(self.clusters)
                cluster = payload["data"][0]["cluster_type"]
                target = cluster["worker_instance_type"] if field == "worker_price" else cluster
                key = "price_cents_per_hour" if field == "worker_price" else field
                target[key] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.parse_clusters(payload)

    def test_json_price_integers_must_fit_the_frontend_safe_integer_range(self):
        payload = deepcopy(self.clusters)
        payload["data"][0]["cluster_type"]["price_cents_per_gpu_hour"] = 2**53 - 1
        self.assertEqual(self.parse_clusters(payload)[0]["amount"], "90071992547409.91")
        for field in ("price_cents_per_gpu_hour", "price_cents_per_hour", "worker_price"):
            payload = deepcopy(self.clusters)
            cluster = payload["data"][0]["cluster_type"]
            target = cluster["worker_instance_type"] if field == "worker_price" else cluster
            target["price_cents_per_hour" if field == "worker_price" else field] = 2**53
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.parse_clusters(payload)

    def test_caller_decimal_context_cannot_round_console_price_normalization(self):
        payload = deepcopy(self.instances)
        item = payload["data"]["gpu_2x_unknown"]["instance_type"]
        item["specs"]["gpus"] = 3
        item["price_cents_per_hour"] = 200
        expected_instances = self.parse_instances(payload)
        expected_clusters = self.parse_clusters()
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            self.assertEqual(self.parse_instances(payload), expected_instances)
            self.assertEqual(self.parse_clusters(), expected_clusters)
            self.assertEqual(context.prec, 2)
            self.assertTrue(context.traps[Inexact])

    def test_invalid_gpu_counts_and_inconsistent_worker_multiplication_are_rejected(self):
        for field in ("num_workers", "num_gpus", "gpus_per_worker"):
            for value in (None, True, 0, -1, "8", 8.0):
                payload = deepcopy(self.clusters)
                cluster = payload["data"][0]["cluster_type"]
                target = cluster["worker_instance_type"]["specs"] if field == "gpus_per_worker" else cluster
                target["gpus" if field == "gpus_per_worker" else field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.parse_clusters(payload)
        payload = deepcopy(self.clusters)
        payload["data"][0]["cluster_type"]["num_gpus"] = 32
        with self.assertRaises(ValueError):
            self.parse_clusters(payload)

    def test_duplicate_configurations_and_capacity_regions_are_rejected(self):
        payload = deepcopy(self.clusters)
        payload["data"].append(deepcopy(payload["data"][0]))
        with self.assertRaises(ValueError):
            self.parse_clusters(payload)
        for parser, original, capacity_key in (
            (self.parse_clusters, self.clusters, "regions_available"),
            (self.parse_instances, self.instances, "regions_with_capacity_available"),
        ):
            payload = deepcopy(original)
            item = payload["data"][0] if isinstance(payload["data"], list) else next(iter(payload["data"].values()))
            duplicate = deepcopy(item[capacity_key][0])
            duplicate["description"] = "Different description for the same capacity name"
            item[capacity_key].append(duplicate)
            with self.subTest(parser=parser.__name__), self.assertRaises(ValueError):
                parser(payload)

    def test_authentication_errors_do_not_expose_provider_messages_or_secrets(self):
        secret = "synthetic-private-session-token"
        for parser in (self.parse_clusters, self.parse_instances):
            for code in ("global/invalid-authentication", "global/forbidden", "global/invalid-api-key"):
                payload = {"error": {"code": code, "message": secret, "details": {"token": secret}}}
                with self.subTest(parser=parser.__name__, code=code), self.assertRaises(FetchError) as raised:
                    parser(payload)
                self.assertEqual(raised.exception.code, "authentication_error")
                self.assertNotIn(secret, str(raised.exception))

    def test_unknown_provider_error_codes_are_safe_without_guessing_authentication_failures(self):
        secret = "synthetic-private-session-token"
        for parser in (self.parse_clusters, self.parse_instances, lambda_console.parse_regions):
            payload = {"error": {"code": "sessionInvalid", "message": secret}}
            with self.subTest(parser=parser.__name__), self.assertRaises(FetchError) as raised:
                parser(payload)
            self.assertEqual(raised.exception.code, "provider_error")
            self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
