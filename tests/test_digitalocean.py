"""Offline semantic checks for DigitalOcean's public GPU price document."""

import json
import unittest
from datetime import date
from decimal import Inexact, localcontext
from pathlib import Path

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import digitalocean

FIXTURE = Path(__file__).parent / "fixtures" / "digitalocean-pricing.html"
OBSERVED = "2026-10-20T07:30:00+00:00"


class DigitalOceanTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text()

    def parse(self, content=None):
        return digitalocean.parse_prices(self.content if content is None else content,
                                          observed_at=OBSERVED, as_of=date(2026, 10, 20))

    def test_complete_plan_prices_divide_by_explicit_eight_gpu_count(self):
        quotes = self.parse()
        self.assertEqual(len(quotes), 19)
        self.assertEqual(sum(q["billing_mode"] == "on_demand" for q in quotes), 11)
        self.assertEqual(sum(q["billing_mode"] == "spot" for q in quotes), 8)
        self.assertEqual({q["gpu_count"] for q in quotes}, {1, 8})
        amd8 = next(q for q in quotes if q["gpu_model"] == "MI325X" and q["gpu_count"] == 8)
        self.assertEqual(amd8["amount"], "3.80")
        self.assertEqual(amd8["instance_price"], {"amount": "30.40", "currency": "USD", "unit": "instance_hour"})
        self.assertEqual(amd8["price_basis"], "instance_total_allocated")
        self.assertEqual(amd8["unit"], "gpu_hour")
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_keeps_cooling_variants_and_does_not_invent_ada_or_vram(self):
        quotes = self.parse()
        b300 = [q for q in quotes if q["gpu_model"] == "B300"]
        self.assertEqual({(q["gpu_variant"], q["gpu_count"]) for q in b300}, {
            ("air-cooled", 1), ("air-cooled", 8), ("liquid-cooled", 1), ("liquid-cooled", 8),
        })
        rtx = next(q for q in quotes if q["gpu_model"] == "RTX 6000")
        self.assertEqual(rtx["raw_name"], "NVIDIA RTX 6000")
        self.assertIsNone(rtx["gpu_variant"])
        self.assertTrue(all(q["vram_gb"] is None for q in quotes))
        self.assertEqual({q["gpu_vendor"] for q in quotes}, {"AMD", "NVIDIA"})

    def test_public_scope_does_not_imply_regions_stock_or_effective_dates(self):
        for quote in self.parse():
            self.assertEqual(quote["provider"], "digitalocean")
            self.assertEqual(quote["source_type"], "public_documentation")
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["zones"], [])
            self.assertEqual(quote["resources"], {})
            self.assertEqual(quote["geographic_scope"], "unspecified")
            self.assertEqual(quote["tax_scope"], "unspecified")
            self.assertEqual(quote["account_scope"], "public_catalog")
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["source_last_verified"], "2026-08-25")
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertIsNone(quote["effective_from"])
            self.assertIsNone(quote["effective_until"])
            self.assertIsNone(quote["raw_sku"])
            self.assertEqual(quote["preview"], quote["billing_mode"] == "spot")
        self.assertTrue(all("may change daily" in q["notes"][-1] for q in self.parse() if q["preview"]))

    def test_tables_are_scoped_by_section_not_position_and_ignore_cpu_contract(self):
        soup = BeautifulSoup(self.content, "html.parser")
        # Put a second unrelated CPU table before both GPU sections.
        extra = BeautifulSoup("<table><thead><tr><th>GPU</th><th>Price</th></tr></thead><tbody><tr><td>NVIDIA B300</td><td>$0.01 per hour</td></tr></tbody></table>", "html.parser").table
        soup.find(id="cpu-droplet-pricing").insert_after(extra)
        self.assertEqual(self.parse(str(soup)), self.parse())
        self.assertNotIn("0.01", [q["amount"] for q in self.parse()])
        self.assertFalse(any(q["gpu_model"] == "MI350X" and q["billing_mode"] == "on_demand" for q in self.parse()))

    def test_source_sections_and_main_must_be_unique_and_nonempty(self):
        for mutation in ("missing_main", "duplicate_main", "missing_section", "duplicate_section", "empty", "two_tables"):
            soup = BeautifulSoup(self.content, "html.parser")
            heading = soup.find(id="on-demand-gpu-droplet-pricing")
            table = heading.find_next("table")
            if mutation == "missing_main":
                soup.main.unwrap()
            elif mutation == "duplicate_main":
                soup.append(soup.new_tag("main"))
            elif mutation == "missing_section":
                heading.decompose()
            elif mutation == "duplicate_section":
                clone = soup.new_tag("h2", id="on-demand-gpu-droplet-pricing")
                heading.insert_before(clone)
            elif mutation == "empty":
                table.tbody.clear()
            elif mutation == "two_tables":
                table.insert_after(BeautifulSoup(str(table), "html.parser").table)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.parse(str(soup))

    def test_headers_row_spans_and_counts_fail_closed(self):
        for before, after in (
            ("<th>GPU</th>", "<th>GPU/Instance</th>"),
            ("<th>Price</th>", "<th>Per GPU</th>"),
            ("<td>AMD MI300X</td>", "<td colspan=\"2\">AMD MI300X</td>"),
            ("AMD MI300X (8x)", "AMD MI300X (4x)"),
            ("AMD MI300X (8x)", "AMD MI300X (0x)"),
            ("AMD MI300X (8x)", "AMD MI300X (1/8 GPU)"),
            ("AMD MI300X", "private-secret"),
        ):
            with self.subTest(change=(before, after)), self.assertRaises(ValueError) as error:
                self.parse(self.content.replace(before, after, 1))
            self.assertNotIn("private-secret", str(error.exception))

    def test_currency_unit_nonpositive_and_non_finite_prices_fail_closed(self):
        for after in ("€2.59 per hour", "$2.59 per month", "from $2.59 per hour", "$0.00 per hour", "$-2.59 per hour", "$NaN per hour", "$Infinity per hour", "$2.59 per GPU hour"):
            with self.subTest(price=after), self.assertRaises(ValueError):
                self.parse(self.content.replace("$2.59 per hour", after, 1))

    def test_duplicate_configurations_even_different_amounts_fail(self):
        for conflicting in (False, True):
            soup = BeautifulSoup(self.content, "html.parser")
            table = soup.find(id="on-demand-gpu-droplet-pricing").find_next("table")
            duplicate = BeautifulSoup(str(table.tbody.tr), "html.parser").tr
            if conflicting:
                duplicate.find_all("td")[1].string = "$999.99 per hour"
            table.tbody.append(duplicate)
            with self.subTest(conflicting=conflicting), self.assertRaises(ValueError):
                self.parse(str(soup))

    def test_decimal_context_of_caller_cannot_round_prices(self):
        content = self.content.replace("$30.40 per hour", "$30.4000000008 per hour")
        with localcontext() as context:
            context.prec = 2
            context.Emax = 0
            context.Emin = 0
            context.traps[Inexact] = True
            quote = next(q for q in self.parse(content) if q["gpu_model"] == "MI325X" and q["gpu_count"] == 8)
        self.assertEqual(quote["amount"], "3.8000000001")

    def test_extreme_price_magnitude_and_precision_fail_before_normalizing(self):
        for amount in ("10000000000000", "0." + "0" * 50 + "1", "1" * 65):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.parse(self.content.replace("$2.59 per hour", "$" + amount + " per hour", 1))

    def test_verification_date_is_optional_and_shared_as_of_has_no_effect(self):
        self.assertEqual(self.parse(), digitalocean.parse_prices(self.content, observed_at=OBSERVED))
        quotes = self.parse(self.content.replace("<p>Last verified 25 Aug 2026</p>", ""))
        self.assertTrue(all(q["source_last_verified"] is None for q in quotes))

    def test_invalid_or_ambiguous_verification_dates_fail(self):
        for after in ("Last verified 32 Aug 2026", "Last verified 25 Xxx 2026", "Last verified 25 Aug 2026</p><p>Last verified 26 Aug 2026"):
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.parse(self.content.replace("Last verified 25 Aug 2026", after, 1))

    def test_unrelated_login_and_empty_content_fail(self):
        for content in ("", "<h1>Login private-secret</h1>", "<main><h2>Pricing</h2><p>$2.59 per hour</p></main>"):
            with self.subTest(length=len(content)), self.assertRaises(ValueError) as error:
                self.parse(content)
            self.assertNotIn("private-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
