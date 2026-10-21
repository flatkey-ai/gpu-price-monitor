"""Nebius effective dates, resource scope and fail-closed parsing."""

from datetime import date
from pathlib import Path
import unittest

from gpu_price_monitor.providers.nebius import parse_prices


OBSERVED = "2026-10-15T00:00:00+00:00"
FIXTURE = Path(__file__).parent / "fixtures" / "nebius-pricing.md"
EXPANDED_FIXTURE = Path(__file__).parent / "fixtures" / "nebius-pricing-expanded.md"


class NebiusParserTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text(encoding="utf-8")

    def parse(self, *, as_of=date(2026, 10, 15), content=None):
        return parse_prices(
            self.content if content is None else content,
            observed_at=OBSERVED, as_of=as_of,
        )

    def rate(self, rows, *, model="H100", currency="USD", mode="on_demand"):
        return next(row for row in rows if row["gpu_model"] == model
                    and row["currency"] == currency and row["billing_mode"] == mode)

    def test_current_rates_exclude_history_cpu_and_storage(self):
        rows = self.parse()
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["gpu_model"] for row in rows}, {"H100", "B200", "L40S"})
        current = self.rate(rows)
        self.assertEqual(current["amount"], "4.50")
        self.assertEqual(current["effective_from"], "2026-10-08")
        self.assertIsNone(current["effective_until"])
        self.assertEqual(current["tax_scope"], "excluded")
        self.assertEqual(current["observed_at"], OBSERVED)
        self.assertIsNone(current["gpu_count"])
        self.assertIsNone(current["vram_gb"])

    def test_spot_from_price_is_a_floor_not_current_dynamic_quote(self):
        spot = self.rate(self.parse(), mode="spot")
        self.assertEqual(spot["amount"], "0.79")
        self.assertEqual(spot["quote_status"], "starting_at")
        self.assertEqual(spot["price_basis"], "starting_price")
        self.assertTrue(any("dynamic" in note for note in spot["notes"]))

    def test_effective_boundaries_are_exclusive_at_end(self):
        before = self.rate(self.parse(as_of=date(2026, 9, 30)))
        middle = self.rate(self.parse(as_of=date(2026, 10, 1)), mode="spot")
        after = self.rate(self.parse(as_of=date(2026, 10, 8)), mode="spot")
        self.assertEqual(before["amount"], "3.85")
        self.assertEqual(before["effective_until"], "2026-10-01")
        self.assertEqual(middle["amount"], "2.15")
        self.assertEqual(middle["effective_until"], "2026-10-08")
        self.assertEqual(after["amount"], "0.79")

    def test_future_table_does_not_replace_current_price(self):
        content = self.content.replace(
            '| **Item — from October 8, 2026** | **Price** | **Per** |',
            '| **Item — from January 1, 2027** | **Price** | **Per** |\n'
            '| NVIDIA® H100 NVLink | $99.00 | 1 GPU hour |\n'
            '| **Item — from October 8, 2026** | **Price** | **Per** |',
            1,
        )
        self.assertEqual(self.rate(self.parse(content=content))["amount"], "4.50")

    def test_future_only_platform_is_skipped(self):
        content = self.content.replace(
            '| **Item** | **Price** | **Per** |',
            '| **Item — from January 1, 2027** | **Price** | **Per** |',
            1,
        )
        rows = self.parse(content=content)
        self.assertEqual({row["gpu_model"] for row in rows}, {"H100", "L40S"})

    def test_component_prices_preserve_separate_cpu_and_ram_rates(self):
        rows = self.parse()
        gpu = self.rate(rows, model="L40S")
        spot = self.rate(rows, model="L40S", mode="spot")
        self.assertEqual(gpu["price_basis"], "gpu_component")
        self.assertEqual(gpu["gpu_variant"], "Intel")
        self.assertEqual(gpu["regions"], ["eu-north1", "eu-west1"])
        self.assertEqual([item["amount"] for item in gpu["components"]], ["0.012", "0.0032"])
        self.assertEqual([item["amount"] for item in spot["components"]], ["0.006", "0.0016"])

    def test_customer_currency_is_not_compute_region(self):
        rows = self.parse()
        self.assertEqual(self.rate(rows, currency="ILS")["regions"], ["eu-north1"])
        b200 = self.rate(rows, model="B200")
        self.assertEqual(b200["regions"], ["me-west1"])
        self.assertEqual(b200["raw_sku"], "gpu-b200-sxm-a")
        self.assertEqual(b200["gpu_variant"], "NVLink")

    def test_unrecognizable_pages_fail_instead_of_returning_empty_success(self):
        for value in ("<html>Access denied</html>", "", "### Virtual machines\nNo pricing"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.parse(content=value)

    def test_unsupported_units_dates_and_prices_fail(self):
        replacements = [
            ("1 GPU hour", "1 GPU day"),
            ("from October 8, 2026", "starting tomorrow"),
            (r"\$4.50", "$???"),
        ]
        for old, new in replacements:
            with self.subTest(new=new):
                with self.assertRaises(ValueError):
                    self.parse(content=self.content.replace(old, new, 1))

    def test_overlapping_effective_rates_fail(self):
        content = self.content.replace("until October 8, 2026", "until October 20, 2026")
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.parse(content=content)

    def test_current_markdown_export_with_expanded_currency_headings(self):
        content = EXPANDED_FIXTURE.read_text(encoding="utf-8")
        rows = self.parse(content=content, as_of=date(2026, 10, 21))
        self.assertEqual(len(rows), 12)
        self.assertEqual({row["gpu_model"] for row in rows}, {"H100", "RTX PRO 6000", "L40S"})
        self.assertEqual({row["currency"] for row in rows}, {"USD", "ILS"})
        h100 = self.rate(rows)
        self.assertEqual(h100["amount"], "4.50")
        self.assertEqual(h100["effective_from"], "2026-10-08")
        self.assertEqual(h100["regions"], ["eu-north1"])
        self.assertEqual(h100["tax_scope"], "excluded")
        self.assertEqual(self.rate(rows, currency="ILS")["amount"], "13.95")
        spot = self.rate(rows, mode="spot")
        self.assertEqual((spot["amount"], spot["quote_status"]), ("0.79", "starting_at"))
        rtx = self.rate(rows, model="RTX PRO 6000")
        self.assertEqual((rtx["amount"], rtx["raw_sku"]), ("1.80", "gpu-rtx6000"))
        l40s = self.rate(rows, model="L40S")
        self.assertEqual(l40s["price_basis"], "gpu_component")
        self.assertEqual([component["amount"] for component in l40s["components"]], ["0.012", "0.0032"])

    def test_expanded_markdown_preserves_effective_date_boundaries(self):
        content = EXPANDED_FIXTURE.read_text(encoding="utf-8")
        before = self.rate(self.parse(content=content, as_of=date(2026, 9, 30)))
        middle = self.rate(self.parse(content=content, as_of=date(2026, 10, 1)), mode="spot")
        after = self.rate(self.parse(content=content, as_of=date(2026, 10, 8)), mode="spot")
        self.assertEqual((before["amount"], before["effective_until"]), ("3.85", "2026-10-01"))
        self.assertEqual((middle["amount"], middle["effective_until"]), ("2.15", "2026-10-08"))
        self.assertEqual((after["amount"], after["effective_from"]), ("0.79", "2026-10-08"))

    def test_expanded_currency_order_is_explicit_and_not_positional(self):
        content = EXPANDED_FIXTURE.read_text(encoding="utf-8")
        changed = content.replace("**USD**", "**TEMP**").replace("**ILS**", "**USD**").replace("**TEMP**", "**ILS**")
        changed = changed.replace("\\$", "TEMP_CURRENCY").replace("₪", "\\$").replace("TEMP_CURRENCY", "₪")
        rows = self.parse(content=changed)
        self.assertEqual(self.rate(rows, currency="ILS")["amount"], "4.50")
        self.assertEqual(self.rate(rows, currency="USD")["amount"], "13.95")

    def test_ambiguous_missing_or_unsupported_currency_sections_fail_closed(self):
        content = EXPANDED_FIXTURE.read_text(encoding="utf-8")
        cases = [
            content.replace("**ILS**", "**USD**", 1),
            content.replace("**ILS**", "**EUR**", 1),
            content.replace("**USD**", "", 1),
            content.replace("**USD**", '<Tab title="USD">', 1),
            content.replace("**USD**", '<Tab title="USD">**USD**</Tab>\n\n**USD**', 1),
            self.content.replace('title="USD"', 'title="EUR"', 1),
        ]
        for changed in cases:
            with self.subTest(content=changed[:100]):
                with self.assertRaises(ValueError):
                    self.parse(content=changed)


if __name__ == "__main__":
    unittest.main()
