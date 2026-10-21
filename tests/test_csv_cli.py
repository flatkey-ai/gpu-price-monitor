"""Offline CLI CSV contracts: stream format, exit codes and public Python API."""

import csv
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import gpu_price_monitor
from gpu_price_monitor import CSV_COLUMNS, prices_to_csv
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
    return list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline="")))


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
            ["collect", "--provider", "nebius", "--format", "csv", "--pretty", "--coverage"], response)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, prices_to_csv(response))
        self.assertTrue(stdout.startswith("\ufeff" + ",".join(CSV_COLUMNS) + "\r\n"))
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
                code = main(["collect", "--format", "csv"])
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
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv"], response)
        self.assertEqual(code, 2)
        self.assertEqual(len(read_csv(stdout)), 1)
        self.assertEqual(read_csv(stdout)[0]["collection_status"], "partial")
        self.assertIn("crusoe: network_error:", stderr)
        self.assertNotIn("network_error", stdout)
        self.assertEqual(stdout, prices_to_csv(response))

    def test_failed_collection_returns_one_header_only_and_provider_error_on_stderr(self):
        response = result("failed")
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv"], response)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "\ufeff" + ",".join(CSV_COLUMNS) + "\r\n")
        self.assertEqual(read_csv(stdout), [])
        self.assertIn("crusoe: network_error:", stderr)
        self.assertNotIn("network_error", stdout)

    def test_configuration_error_returns_one_header_only_without_collecting_or_secret(self):
        secret = "synthetic-invalid-timeout-secret"
        code, stdout, stderr, collector = self.run_cli(
            ["collect", "--format", "csv"], environment={"GPU_PRICE_MONITOR_TIMEOUT_SECONDS": secret})
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "\ufeff" + ",".join(CSV_COLUMNS) + "\r\n")
        self.assertIn("Invalid configuration:", stderr)
        self.assertNotIn(secret, stdout + stderr)
        collector.assert_not_called()

    def test_default_and_explicit_json_remain_machine_readable(self):
        response = result("partial")
        for arguments in (["collect"], ["collect", "--format", "json", "--pretty"]):
            with self.subTest(arguments=arguments):
                code, stdout, stderr, _ = self.run_cli(arguments, response)
                self.assertEqual(code, 2)
                self.assertFalse(stdout.startswith("\ufeff"))
                self.assertEqual(json.loads(stdout), response)
                self.assertIn("crusoe: network_error:", stderr)

    def test_public_python_exports_preserve_source_result_and_match_cli(self):
        self.assertIn("prices_to_csv", gpu_price_monitor.__all__)
        self.assertIn("CSV_COLUMNS", gpu_price_monitor.__all__)
        self.assertTrue(callable(prices_to_csv))
        response = result()
        original = deepcopy(response)
        text = prices_to_csv(response)
        code, stdout, stderr, _ = self.run_cli(["collect", "--format", "csv"], response)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(text, stdout)
        self.assertEqual(response, original)
        self.assertEqual(read_csv(text)[0]["instance_amount"], "36.000000000008")


if __name__ == "__main__":
    unittest.main()
