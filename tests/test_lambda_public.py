"""Offline checks for the key-free Lambda public price page parser."""

import json
import unittest
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from gpu_price_monitor.providers import lambda_public

FIXTURE = Path(__file__).parent / "fixtures" / "lambda-public-pricing.html"
OBSERVED = "2026-10-20T06:00:00+00:00"


class LambdaPublicTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text()

    def parse(self, content=None):
        return lambda_public.parse_prices(self.content if content is None else content, observed_at=OBSERVED, as_of=date(2026, 10, 20))

    def test_prices_are_advertised_per_gpu_and_totals_use_explicit_count(self):
        quotes = self.parse()
        self.assertEqual(len(quotes), 9)
        self.assertEqual({q["gpu_count"] for q in quotes}, {8, 4, 2, 1})
        b200 = next(q for q in quotes if q["gpu_model"] == "B200" and q["gpu_count"] == 8)
        self.assertEqual((b200["amount"], b200["instance_price"]["amount"]), ("6.69", "53.52"))
        self.assertEqual(b200["price_basis"], "advertised_per_gpu")
        self.assertEqual(b200["resources"], {
            "vcpus": 208, "memory_gib": 2900,
            "storage": {"amount": "22", "unit": "TiB", "type": "SSD"},
        })
        self.assertNotIn("0.01", [q["amount"] for q in quotes])
        self.assertEqual(json.loads(json.dumps(quotes)), quotes)

    def test_aria_links_preserve_gpu_counts_when_tables_are_reordered(self):
        soup = BeautifulSoup(self.content, "html.parser")
        panel8 = soup.find(id="panel-8")
        panel1 = soup.find(id="panel-1")
        panel8.insert_before(panel1.extract())
        expected = {(q["raw_name"], q["vram_gb"], q["gpu_count"]): q["amount"] for q in self.parse()}
        actual = {(q["raw_name"], q["vram_gb"], q["gpu_count"]): q["amount"] for q in self.parse(str(soup))}
        self.assertEqual(actual, expected)

    def test_a100_variants_and_vram_remain_distinct(self):
        a100 = [q for q in self.parse() if q["gpu_model"] == "A100"]
        self.assertEqual({(q["gpu_count"], q["gpu_variant"], q["vram_gb"]) for q in a100}, {
            (8, "SXM", 80), (8, "SXM", 40), (1, "SXM", 40), (1, "PCIe", 40),
        })
        single = next(q for q in a100 if q["gpu_count"] == 1)
        self.assertEqual(single["resources"]["storage"], {"amount": "512", "unit": "GiB", "type": "SSD"})

    def test_scope_has_no_inferred_region_account_or_capacity(self):
        for quote in self.parse():
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["geographic_scope"], "unspecified")
            self.assertEqual(quote["account_scope"], "public_catalog")
            self.assertEqual(quote["tax_scope"], "excluded")
            self.assertEqual(quote["availability"], "unknown")
            self.assertEqual(quote["currency"], "USD")
            self.assertEqual(quote["currency_source_url"], "https://docs.lambda.ai/api/cloud")
            self.assertEqual(quote["source_type"], "public_page")
            self.assertEqual(quote["source_url"], "https://lambda.ai/pricing")
            self.assertIsNone(quote["raw_sku"])
            self.assertEqual(quote["observed_at"], OBSERVED)
            self.assertIsNone(quote["effective_from"])

    def test_optional_shared_interface_as_of(self):
        self.assertEqual(self.parse(), lambda_public.parse_prices(self.content, observed_at=OBSERVED))

    def test_unrecognized_headers_currency_or_units_fail_whole_catalog(self):
        changes = [
            ("PRICE/GPU/HR*", "PRICE/INSTANCE/HR*"),
            ("VRAM/GPU", "VRAM"),
            ("$6.69", "€6.69"),
            ("$6.69", "US$6.69"),
            ("$6.69", "$6.69 / month"),
            ("$6.69", "from $6.69"),
            ("$6.69", "$0.00"),
            ("180 GB", "180 GiB"),
            ("2900 GiB", "2900 GB"),
            ("22 TiB SSD", "22 TB SSD"),
            ("22 TiB SSD", "22 TiB"),
            ("* plus applicable sales tax/VAT/GST", "tax included"),
        ]
        for before, after in changes:
            with self.subTest(change=(before, after)), self.assertRaises(ValueError):
                self.parse(self.content.replace(before, after, 1))

    def test_missing_ambiguous_or_changed_tab_association_fails(self):
        for mutation in ("no_count", "new_count", "broken_link", "bad_reverse_link", "duplicate_id", "missing_panel", "extra_table"):
            soup = BeautifulSoup(self.content, "html.parser")
            tab = soup.find(id="tab-8")
            panel = soup.find(id="panel-8")
            if mutation == "no_count":
                tab.string = "Multi-GPU"
            elif mutation == "new_count":
                tab.string = "16x"
            elif mutation == "broken_link":
                tab["aria-controls"] = "panel-1"
            elif mutation == "bad_reverse_link":
                panel["aria-labelledby"] = "tab-4"
            elif mutation == "duplicate_id":
                soup.find(id="panel-1")["id"] = "panel-8"
            elif mutation == "missing_panel":
                panel.decompose()
            elif mutation == "extra_table":
                panel.append(soup.new_tag("table"))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.parse(str(soup))

    def test_duplicate_rows_including_conflicting_prices_fail(self):
        for conflicting in (False, True):
            soup = BeautifulSoup(self.content, "html.parser")
            body = soup.find(id="panel-8").find("tbody")
            duplicate = BeautifulSoup(str(body.find("tr")), "html.parser").find("tr")
            if conflicting:
                duplicate.find_all("td")[-1].string = "$99.99"
            body.append(duplicate)
            with self.subTest(conflicting=conflicting), self.assertRaises(ValueError):
                self.parse(str(soup))

    def test_empty_tables_and_unrelated_or_login_pages_fail_without_leaking(self):
        soup = BeautifulSoup(self.content, "html.parser")
        soup.find(id="panel-4").find("tbody").clear()
        for content in (str(soup), "", "<h1>Login private-secret</h1>", "<h2>Pricing</h2><p>$6.69</p>"):
            with self.subTest(content_length=len(content)), self.assertRaises(ValueError) as error:
                self.parse(content)
            self.assertNotIn("private-secret", str(error.exception))

    def test_row_labels_and_plan_must_match_columns_and_name(self):
        for mutation in ("label", "plan", "missing_cell", "span", "extra_header"):
            soup = BeautifulSoup(self.content, "html.parser")
            row = soup.find("tbody").find("tr")
            if mutation == "label":
                row.find_all("td")[0]["data-label"] = "RAM"
            elif mutation == "plan":
                row["data-plan"] = "private-secret"
            elif mutation == "missing_cell":
                row.find_all("td")[-1].decompose()
            elif mutation == "span":
                row.find_all("td")[0]["rowspan"] = "2"
            else:
                soup.find("thead").find("tr").append(soup.new_tag("td"))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError) as error:
                self.parse(str(soup))
            self.assertNotIn("private-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
