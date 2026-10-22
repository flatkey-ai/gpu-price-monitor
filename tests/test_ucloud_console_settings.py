"""Optional stock probes are explicit and distinct from price collection."""
from pathlib import Path
import tempfile
from unittest import TestCase

from gpu_price_monitor.settings import ConfigurationError, Settings


class UCloudConsoleSettingsTests(TestCase):
    def test_stock_checks_are_disabled_by_default(self):
        self.assertIs(Settings().ucloud_check_availability, False)
        self.assertIs(Settings.from_env({}).ucloud_check_availability, False)

    def test_env_boolean_is_case_insensitive_and_explicit(self):
        for value, expected in (("true", True), ("TRUE", True), ("TrUe", True),
                                ("false", False), ("FALSE", False), ("FaLsE", False)):
            with self.subTest(value=value):
                self.assertIs(Settings.from_env({"UCLOUD_CHECK_AVAILABILITY": value}).ucloud_check_availability, expected)

    def test_invalid_values_are_rejected_without_echoing_them(self):
        for value in ("1", "0", "", "yes", " true ", "private-invalid"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as caught:
                Settings.from_env({"UCLOUD_CHECK_AVAILABILITY": value})
            self.assertEqual(str(caught.exception), "UCLOUD_CHECK_AVAILABILITY must be true or false")
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                Settings(ucloud_check_availability=value)

    def test_process_env_overrides_file_without_network_or_session_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.env"
            path.write_text("UCLOUD_SOURCE=console\nUCLOUD_CHECK_AVAILABILITY=true\n")
            self.assertIs(Settings.from_env({}, env_file=path).ucloud_check_availability, True)
            self.assertIs(Settings.from_env({"UCLOUD_CHECK_AVAILABILITY": "false"}, env_file=path).ucloud_check_availability, False)
