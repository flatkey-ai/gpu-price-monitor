"""Platform CSV CLI writes separate, non-clobbering files, never mixed tables."""

import csv
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from gpu_price_monitor.cli import main
from gpu_price_monitor.cli import _write_provider_csvs
from gpu_price_monitor.settings import ConfigurationError


def result():
    return {"status": "success", "prices": [], "provider_results": [
        {"provider": "lambda", "error": None}, {"provider": "ucloud", "error": None}]}


class ProviderCsvCliTests(unittest.TestCase):
    def run_cli(self, args, response):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {}, clear=True), patch(
            "gpu_price_monitor.cli.collect_prices", return_value=response
        ) as collect, redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue(), collect

    def test_multiple_providers_have_different_header_only_files(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err, collect = self.run_cli([
                "collect", "--providers", "lambda,ucloud", "--format", "csv",
                "--csv-profile", "provider", "--output-dir", folder], result())
            self.assertEqual(code, 0)
            self.assertEqual(out, "")
            self.assertIn("header-only", err)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["lambda.csv", "ucloud.csv"])
            headers = []
            for provider in ("lambda", "ucloud"):
                path = Path(folder, provider + ".csv")
                self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
                rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
                self.assertEqual(len(rows), 1)
                headers.append(rows[0])
            self.assertNotEqual(*headers)
            collect.assert_called_once()

    def test_single_provider_still_supports_shell_redirection(self):
        response = result()
        response["provider_results"] = response["provider_results"][:1]
        code, out, _, collect = self.run_cli([
            "collect", "--providers", "lambda", "--format", "csv", "--csv-profile", "provider"], response)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("\ufeff"))
        self.assertEqual(len(list(csv.reader(io.StringIO(out)))), 1)
        collect.assert_called_once()

    def test_multiple_csvs_require_directory_before_any_collection(self):
        code, out, err, collect = self.run_cli([
            "collect", "--providers", "lambda,ucloud", "--format", "csv", "--csv-profile", "provider"], result())
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("--output-dir", err)
        collect.assert_not_called()

    def test_existing_file_is_never_overwritten_and_blocks_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "lambda.csv")
            path.write_text("keep this export")
            code, _, err, collect = self.run_cli([
                "collect", "--providers", "lambda,ucloud", "--format", "csv",
                "--csv-profile", "provider", "--output-dir", folder], result())
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
            self.assertEqual(path.read_text(), "keep this export")
            self.assertFalse(Path(folder, "ucloud.csv").exists())
            collect.assert_not_called()

    def test_output_dir_rejected_for_other_formats_before_collection(self):
        for options in ([], ["--format", "csv"], ["--format", "csv", "--csv-profile", "full"]):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder:
                code, _, err, collect = self.run_cli(["collect", "--output-dir", folder, *options], result())
                self.assertEqual(code, 1)
                self.assertIn("requires --format csv --csv-profile provider", err)
                self.assertFalse(list(Path(folder).iterdir()))
                collect.assert_not_called()

    def test_write_failure_cleans_only_files_created_by_this_export(self):
        with tempfile.TemporaryDirectory() as folder:
            keep = Path(folder, "other.csv")
            keep.write_text("older batch")
            original_open = Path.open
            def open_file(path, *args, **kwargs):
                if path.name == "ucloud.csv":
                    raise PermissionError("private OS diagnostic")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", open_file), self.assertRaises(ConfigurationError):
                _write_provider_csvs(result(), Path(folder), bilingual_headers=True)
            self.assertEqual(keep.read_text(), "older batch")
            self.assertFalse(Path(folder, "lambda.csv").exists())

    def test_cleanup_failure_reports_partial_files_without_raw_os_error(self):
        with tempfile.TemporaryDirectory() as folder:
            original_open = Path.open
            def open_file(path, *args, **kwargs):
                if path.name == "ucloud.csv":
                    raise PermissionError("private OS diagnostic")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", open_file), patch.object(Path, "unlink", side_effect=PermissionError("private path")), self.assertRaises(ConfigurationError) as caught:
                _write_provider_csvs(result(), Path(folder), bilingual_headers=True)
            self.assertIn("partial files", str(caught.exception))
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
