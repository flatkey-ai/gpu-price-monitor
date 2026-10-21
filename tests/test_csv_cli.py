"""Offline CLI CSV contracts: stream format, exit codes and public Python API."""

import csv
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import gpu_price_monitor
from gpu_price_monitor import (
    COMPACT_CSV_COLUMNS, COMPACT_CSV_HEADERS, CSV_COLUMNS, CSV_HEADERS,
    MARKET_CSV_COLUMNS, MARKET_CSV_HEADERS,
    market_eligible_quote, prices_to_csv, publishable_quote,
)
from gpu_price_monitor.cli import main

OBSERVED = "2026-10-21T08:30:00+00:00"


def quote():
    return {
        "provider": "nebius", "product_type": "gpu_instance", "gpu_model": "H100",
        "gpu_variant": "SXM", "raw_name": "H100 中国, 80 GB", "gpu_count": 8,
        "vram_gb": 80, "amount": "4.500000000001", "currency": "USD", "unit": "gpu_hour",
        "billing_mode": "on_demand", "price_basis": "instance_total_allocated",
        "quote_status": "quoted", "availability": "unknown", "membership_required": False,
        "regions": ["eu-north1"], "zones": [], "compute_countries": [],
        "instance_price": {"amount": "36.000000000008", "currency": "USD", "unit": "instance_hour"},
        "source_url": "https://docs.nebius.com/prices", "source_type": "public_page",
        "observed_at": OBSERVED, "notes": ["Synthetic fixture; no provider request."],
    }


def result(status="success"):
    error = {"code": "network_error", "message": "The pricing source could not be reached.", "retryable": True}
    return {
        "schema_version": 1, "collected_at": OBSERVED, "status": status,
        "prices": [] if status == "failed" else [quote()],
        "provider_results": ([{"provider": "nebius", "status": "ok", "error": None}]
                             if status == "success" else
                             [{"provider": "crusoe", "status": "failed", "error": error}]),
    }


def read_csv(text):
    headers_to_ids = {**dict(zip(CSV_HEADERS, CSV_COLUMNS)), **dict(zip(COMPACT_CSV_HEADERS, COMPACT_CSV_COLUMNS)),
                      **dict(zip(MARKET_CSV_HEADERS, MARKET_CSV_COLUMNS))}
    reader = csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline=""))
    return [{headers_to_ids.get(key, key): value for key, value in row.items()} for row in reader]


def csv_header(text):
    return next(csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline="")))


class CsvCliTests(unittest.TestCase):
    def setUp(self):
        transport = patch("gpu_price_monitor.transport._request_text",
                          side_effect=AssertionError("CSV CLI tests must not make network requests"))
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    def run_cli(self, arguments, response=None, environment=None):
        stdout, stderr = io.StringIO(newline=""), io.StringIO()
        with patch.dict("os.environ", environment or {}, clear=True), \
                patch("gpu_price_monitor.cli.collect_prices", return_value=response) as collector, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        self.transport.assert_not_called()
        return code, stdout.getvalue(), stderr.getvalue(), collector

    def test_csv_stdout_is_only_bom_header_and_prices_even_with_pretty_and_coverage(self):
        response = result()
        response["coverage"] = {"not_a_price_row": "coverage-json-must-not-appear"}
        code, stdout, stderr, collector = self.run_cli(
            ["collect", "--provider", "nebius", "--format", "csv", "--csv-profile", "full", "--pretty", "--coverage"], response)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, prices_to_csv(response, profile="full"))
        self.assertTrue(stdout.startswith("\ufeff" + ",".join(CSV_HEADERS) + "\r\n"))
        rows = read_csv(stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), list(CSV_COLUMNS))
        self.assertEqual(rows[0]["amount"], "4.500000000001")
        self.assertEqual(rows[0]["raw_name"], "H100 中国, 80 GB")
        self.assertEqual(rows[0]["collected_at"], OBSERVED)
        self.assertEqual(rows[0]["collection_status"], "success")
        self.assertNotIn("coverage-json-must-not-appear", stdout)
        self.assertNotIn('"schema_version"', stdout)
        self.assertTrue(collector.call_args.kwargs["include_coverage"])

    def test_real_text_stream_is_utf8_and_preserves_one_bom_and_crlf(self):
        output = io.BytesIO()
        # A hostile caller encoding/newline exposes UTF-8 or doubled-CR regressions.
        stdout = io.TextIOWrapper(output, encoding="ascii", newline="\r\n")
        stderr = io.StringIO()
        try:
            with patch.dict("os.environ", {}, clear=True), \
                    patch("gpu_price_monitor.cli.collect_prices", return_value=result()), \
                    patch("sys.stdout", stdout), redirect_stderr(stderr):
                code = main(["collect", "--format", "csv", "--csv-profile", "full"])
                stdout.flush()
            data = output.getvalue()
        finally:
            stdout.detach()
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(data.count(b"\xef\xbb\xbf"), 1)
        self.assertNotIn(b"\r\r\n", data)
        self.assertTrue(data.endswith(b"\r\n"))
        self.assertEqual(read_csv(data.decode("utf-8"))[0]["raw_name"], "H100 中国, 80 GB")
        self.transport.assert_not_called()

    def test_partial_retains_successful_prices_returns_two_and_errors_only_on_stderr(self):
        response = result("partial")
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "full"], response)
        self.assertEqual(code, 2)
        self.assertEqual(len(read_csv(stdout)), 1)
        self.assertEqual(read_csv(stdout)[0]["collection_status"], "partial")
        self.assertIn("crusoe: network_error:", stderr)
        self.assertNotIn("network_error", stdout)
        self.assertEqual(stdout, prices_to_csv(response, profile="full"))

    def test_failed_collection_returns_one_header_only_and_provider_error_on_stderr(self):
        response = result("failed")
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "full"], response)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "\ufeff" + ",".join(CSV_HEADERS) + "\r\n")
        self.assertEqual(read_csv(stdout), [])
        self.assertIn("crusoe: network_error:", stderr)
        self.assertNotIn("network_error", stdout)

    def test_configuration_error_returns_one_header_only_without_collecting_or_secret(self):
        secret = "synthetic-invalid-timeout-secret"
        code, stdout, stderr, collector = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "full"], environment={"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": secret})
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "\ufeff" + ",".join(CSV_HEADERS) + "\r\n")
        self.assertIn("Invalid configuration:", stderr)
        self.assertNotIn(secret, stdout + stderr)
        collector.assert_not_called()

    def test_default_and_explicit_json_remain_machine_readable(self):
        response = result("partial")
        for arguments in (["collect"], ["collect", "--format", "json", "--pretty"],
                          ["collect", "--csv-headers", "english"],
                          ["collect", "--format", "json", "--csv-headers", "bilingual"]):
            with self.subTest(arguments=arguments):
                code, stdout, stderr, _ = self.run_cli(arguments, response)
                self.assertEqual(code, 2)
                self.assertFalse(stdout.startswith("\ufeff"))
                self.assertEqual(json.loads(stdout), response)
                self.assertIn("crusoe: network_error:", stderr)

    def test_public_python_exports_preserve_source_result_and_match_cli(self):
        self.assertIn("prices_to_csv", gpu_price_monitor.__all__)
        self.assertIn("CSV_COLUMNS", gpu_price_monitor.__all__)
        self.assertIn("CSV_HEADERS", gpu_price_monitor.__all__)
        self.assertTrue(callable(prices_to_csv))
        response = result()
        original = deepcopy(response)
        text = prices_to_csv(response, profile="full")
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "full"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(text, stdout)
        self.assertEqual(response, original)
        self.assertEqual(read_csv(text)[0]["instance_amount"], "36.000000000008")


    def test_full_csv_translates_every_header_without_changing_quote_values(self):
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "full"], result())
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(csv_header(stdout), list(CSV_HEADERS))
        self.assertEqual(len(CSV_HEADERS), len(CSV_COLUMNS))
        self.assertEqual(len(set(CSV_HEADERS)), len(CSV_HEADERS))
        for identifier, label in zip(CSV_COLUMNS, CSV_HEADERS):
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, label)
                self.assertTrue(any("\u4e00" <= character <= "\u9fff" for character in label))
        row = read_csv(stdout)[0]
        self.assertEqual(row["provider"], "nebius")
        self.assertEqual(row["unit"], "gpu_hour")
        self.assertEqual(row["billing_mode"], "on_demand")
        self.assertEqual(row["amount"], "4.500000000001")

    def test_explicit_english_headers_keep_machine_readable_ids_and_identical_data(self):
        response = result()
        code, stdout, stderr, _ = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "full", "--csv-headers", "english"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(csv_header(stdout), list(CSV_COLUMNS))
        self.assertEqual(stdout, prices_to_csv(response, bilingual_headers=False, profile="full"))
        self.assertEqual(read_csv(stdout), read_csv(prices_to_csv(response, profile="full")))
        self.assertEqual(response["prices"][0]["amount"], "4.500000000001")

    def test_explicit_bilingual_matches_default_and_empty_english_keeps_exit_codes(self):
        response = result()
        code, stdout, stderr, _ = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "full", "--csv-headers", "bilingual"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(stdout, prices_to_csv(response, profile="full"))
        for env, response in (({}, result("failed")),
                              ({"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": "invalid"}, None)):
            with self.subTest(configuration_error=bool(env)):
                code, stdout, stderr, _ = self.run_cli(
                    ["collect", "--format", "csv", "--csv-profile", "full", "--csv-headers", "english"], response, env)
                self.assertEqual(code, 1)
                self.assertEqual(csv_header(stdout), list(CSV_COLUMNS))
                self.assertEqual(read_csv(stdout), [])
                self.assertTrue(stderr)

    def test_explicit_compact_has_ten_columns_and_only_actual_country_region_hourly_quotes(self):
        regional = {**quote(), "provider": "azure", "compute_countries": ["US"], "regions": ["westus3"],
                    "price_scope": "regional_quote", "region_price_verified": True,
                    "source_url": "https://prices.azure.com/api/retail/prices"}
        response = result()
        response["prices"] = [quote(), regional,
                              {**regional, "unit": "gpu_month", "billing_mode": "monthly"},
                              {**regional, "quote_status": "starting_at", "price_basis": "starting_price"},
                              {**regional, "price_basis": "gpu_component"},
                              {**regional, "availability": "offline"}]
        original = deepcopy(response)
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "compact"], response)
        self.assertEqual(code, 0)
        self.assertIn("CSV comparison: 1 verified regional GPU-hour quotes; 5 collected records excluded.", stderr)
        self.assertEqual(csv_header(stdout), list(COMPACT_CSV_HEADERS))
        self.assertEqual(stdout, prices_to_csv(response, profile="compact"))
        actual = read_csv(stdout)
        self.assertEqual(len(actual), 1)
        self.assertEqual(tuple(actual[0]), COMPACT_CSV_COLUMNS)
        self.assertEqual((actual[0]["provider"], actual[0]["amount"], actual[0]["unit"]),
                         ("azure", regional["amount"], "gpu_hour"))
        self.assertIn("国家=US", actual[0]["location"])
        self.assertIn("地区=westus3", actual[0]["location"])
        self.assertIn(regional["instance_price"]["amount"], actual[0]["pricing_conditions"])
        self.assertTrue(publishable_quote(regional))
        code, english, stderr, _ = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "compact", "--csv-headers", "english"], response)
        self.assertEqual(code, 0)
        self.assertIn("CSV comparison: 1 verified regional GPU-hour quotes; 5 collected records excluded.", stderr)
        self.assertEqual(csv_header(english), list(COMPACT_CSV_COLUMNS))
        self.assertEqual(read_csv(english), actual)
        code, json_text, stderr, _ = self.run_cli(["collect", "--csv-profile", "compact"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(json_text), original)
        self.assertEqual(response, original)

    def test_successful_sources_with_no_comparable_quotes_emit_only_compact_header(self):
        response = result()
        response["prices"] = [quote(), {**quote(), "compute_countries": ["FI"],
                                       "coverage_regions": ["eu-north1"], "price_scope": "platform_coverage",
                                       "region_price_verified": False}]
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "compact"], response)
        self.assertEqual(code, 0)
        self.assertIn("CSV comparison: 0 verified regional GPU-hour quotes; 2 collected records excluded.", stderr)
        self.assertEqual(stdout, "\ufeff" + ",".join(COMPACT_CSV_HEADERS) + "\r\n")
        self.assertEqual(read_csv(stdout), [])
        code, json_text, stderr, _ = self.run_cli(["collect", "--format", "json"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(json_text), response)
        self.assertEqual(json.loads(json_text)["status"], "success")
        code, full, stderr, _ = self.run_cli(["collect", "--format", "csv", "--csv-profile", "full"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(len(read_csv(full)), 2)

    def test_compact_public_exports_and_configuration_error_keep_profile_header(self):
        for symbol in ("COMPACT_CSV_COLUMNS", "COMPACT_CSV_HEADERS", "publishable_quote", "market_eligible_quote"):
            self.assertIn(symbol, gpu_price_monitor.__all__)
        code, stdout, stderr, collector = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "compact"],
            environment={"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": "invalid"})
        self.assertEqual(code, 1)
        self.assertEqual(csv_header(stdout), list(COMPACT_CSV_HEADERS))
        self.assertEqual(read_csv(stdout), [])
        self.assertIn("Invalid configuration:", stderr)
        self.assertNotIn("CSV comparison:", stderr)
        collector.assert_not_called()

    def test_default_market_keeps_catalog_without_claiming_a_price_region(self):
        catalog = {**quote(), "provider": "lambda", "price_scope": "unlocated_catalog",
                   "region_price_verified": False, "regions": [], "price_basis": "advertised_per_gpu",
                   "account_scope": "public_catalog"}
        regional = {**quote(), "compute_countries": ["FI"], "price_scope": "regional_quote",
                    "region_price_verified": True}
        response = result()
        response["prices"] = [catalog, regional, {**catalog, "unit": "gpu_month"},
                              {**catalog, "quote_status": "contact_sales", "amount": None}]
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv"], response)
        self.assertEqual(code, 0)
        self.assertEqual(stdout, prices_to_csv(response, profile="market"))
        self.assertEqual(csv_header(stdout), list(MARKET_CSV_HEADERS))
        self.assertEqual(len(read_csv(stdout)), 2)
        self.assertIn("CSV market: 2 numeric GPU-hour quotes (1 verified regional, 1 catalog)", stderr)
        self.assertIn("Catalog prices do not establish regional or globally uniform pricing.", stderr)
        self.assertIn("公开目录报价", read_csv(stdout)[0]["location"])
        self.assertNotIn("国家=", read_csv(stdout)[0]["location"])
        self.assertTrue(market_eligible_quote(catalog))
        self.assertFalse(publishable_quote(catalog))
        code, explicit, _, _ = self.run_cli(
            ["collect", "--format", "csv", "--csv-profile", "market"], response)
        self.assertEqual((code, explicit), (0, stdout))


if __name__ == "__main__":
    unittest.main()
