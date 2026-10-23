"""Price boundary and structure checks for Crusoe's public instance table."""

from datetime import date
from pathlib import Path
import unittest

from bs4 import BeautifulSoup

from gpu_price_monitor.providers.crusoe import SOURCE_URL, parse_prices


FIXTURE = Path(__file__).parent / "fixtures" / "crusoe-pricing.html"
CURRENT_FIXTURE = Path(__file__).parent / "fixtures" / "crusoe-pricing-20261021.html"
OBSERVED_AT = "2026-10-15T09:00:00+00:00"


def parse(content):
    return parse_prices(content, observed_at=OBSERVED_AT, as_of=date(2026, 10, 15))


class CrusoeParserTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text(encoding="utf-8")

    def test_extracts_only_gpu_instance_prices_and_preserves_variants(self):
        prices = parse(self.content)
        self.assertEqual(len(prices), 10)
        quoted = [p for p in prices if p["quote_status"] == "quoted"]
        self.assertEqual(
            [(p["gpu_model"], p["gpu_variant"], p["amount"]) for p in quoted],
            [("H200", "HGX", "4.29"), ("H100", "HGX", "3.90"),
             ("A100", "SXM", "2.30"), ("A100", "PCIe", "2.00")],
        )
        for price in quoted:
            self.assertEqual(price["unit"], "gpu_hour")
            self.assertEqual(price["currency"], "USD")
            self.assertEqual(price["billing_mode"], "on_demand")
            self.assertEqual(price["price_basis"], "advertised_per_gpu")
            self.assertNotEqual(price["amount"], "5.50")

    def test_contact_sales_is_explicit_null_not_zero(self):
        prices = parse(self.content)
        contacts = [p for p in prices if p["quote_status"] == "contact_sales"]
        self.assertEqual(len(contacts), 6)
        self.assertTrue(all(p["amount"] is None for p in contacts))
        self.assertEqual({p["billing_mode"] for p in contacts}, {"on_demand", "spot"})
        self.assertEqual(prices[0]["gpu_variant"], "NVL72")
        self.assertEqual(prices[0]["vram_gb"], 186)

    def test_source_does_not_invent_regions_card_counts_dates_or_availability(self):
        for price in parse(self.content):
            self.assertEqual(price["regions"], [])
            self.assertEqual(price["geographic_scope"], "unspecified")
            self.assertIsNone(price["gpu_count"])
            self.assertIsNone(price["effective_from"])
            self.assertIsNone(price["effective_until"])
            self.assertEqual(price["availability"], "unknown")
            self.assertEqual(price["source_url"], SOURCE_URL)
            self.assertEqual(price["source_type"], "official_pricing_page")
            self.assertEqual(price["observed_at"], OBSERVED_AT)
            self.assertIn("orderability were not verified", " ".join(price["notes"]))

    def test_starting_price_is_not_an_unconditional_quote(self):
        prices = parse(self.content.replace("$3.90/GPU-hr", "Starting at $3.90/GPU-hr"))
        price = next(p for p in prices if p["gpu_model"] == "H100" and p["amount"])
        self.assertEqual(price["amount"], "3.90")
        self.assertEqual(price["quote_status"], "starting_at")
        self.assertEqual(price["price_basis"], "starting_price")

    def test_reordered_price_columns_follow_headers(self):
        prices = parse(self.content.replace("On-demand", "TEMP").replace("Current spot", "On-demand").replace("TEMP", "Current spot"))
        h100 = next(p for p in prices if p["gpu_model"] == "H100" and p["amount"])
        self.assertEqual(h100["billing_mode"], "spot")

    def test_current_catalog_preserves_unpriced_new_products_without_losing_numeric_quotes(self):
        prices = parse(CURRENT_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(prices), 24)
        numeric = [price for price in prices if price["amount"] is not None]
        self.assertEqual(len(numeric), 8)
        self.assertEqual(
            [(price["gpu_model"], price["gpu_variant"], price["amount"]) for price in numeric],
            [("B200", "HGX", "8.50"), ("H200", "HGX", "5.40"),
             ("H100", "HGX", "4.50"), ("A100", "SXM", "2.30"),
             ("A100", "PCIe", "2.00"), ("L40S", None, "1.50"),
             ("MI300X", None, "3.45"), ("B300", "HGX", "9.90")],
        )
        unknown_memory = [price for price in prices if price["vram_gb"] is None]
        self.assertEqual(len(unknown_memory), 4)
        self.assertEqual({price["gpu_model"] for price in unknown_memory}, {"GB300", "VERA RUBIN"})
        for price in unknown_memory:
            self.assertEqual(price["quote_status"], "contact_sales")
            self.assertEqual(price["gpu_variant"], "NVL72")
            self.assertIsNone(price["amount"])
            self.assertIsNone(price["gpu_count"])
            self.assertEqual(price["availability"], "unknown")
            self.assertIn("does not specify GPU memory", " ".join(price["notes"]))

    def test_variant_in_heading_and_tag_is_deduplicated(self):
        prices = parse(self.content.replace("NVIDIA H100", "NVIDIA HGX H100"))
        h100 = next(price for price in prices if price["gpu_model"] == "H100")
        self.assertEqual(h100["gpu_variant"], "HGX")
        self.assertEqual(h100["raw_name"], "NVIDIA HGX H100")

    def test_contact_listing_preserves_non_gb_memory_without_inventing_per_gpu_capacity(self):
        content = CURRENT_FIXTURE.read_text(encoding="utf-8")
        # The current CMS can publish NVL72 and a system-level TB label while
        # keeping both pricing cells as Contact sales.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        for row in soup.select(".pricing_gpu-item"):
            if "Vera Rubin" in row.get_text(" "):
                row.select(".pricing-tag")[0].string = "20.7TB"
        prices = parse(str(soup))
        rubin = [price for price in prices if price["gpu_model"] == "VERA RUBIN"]
        self.assertEqual(len(rubin), 2)
        for price in rubin:
            self.assertIsNone(price["vram_gb"])
            self.assertIsNone(price["amount"])
            self.assertEqual(price["gpu_variant"], "NVL72")
            self.assertEqual(price["gpu_memory_description"], "20.7TB")

    def test_numeric_tb_memory_is_rejected_until_per_gpu_unit_is_established(self):
        with self.assertRaises(ValueError):
            parse(self.content.replace("141GB", "20.7TB"))

    def test_october_22_catalog_uses_current_cells_and_new_memory_labels(self):
        prices = parse((FIXTURE.parent / "crusoe-pricing-20261022.html").read_text())
        self.assertEqual(len(prices), 24)
        self.assertEqual(sum(q["amount"] is not None for q in prices), 7)
        h200 = next(q for q in prices if q["gpu_model"] == "H200" and q["billing_mode"] == "on_demand")
        self.assertEqual(h200["amount"], "4.29")
        b200 = [q for q in prices if q["gpu_model"] == "B200"]
        self.assertTrue(all(q["quote_status"] == "contact_sales" for q in b200))
        rubin = next(q for q in prices if q["gpu_model"] == "VERA RUBIN")
        self.assertIsNone(rubin["vram_gb"])
        self.assertEqual(rubin["gpu_memory_description"], "20.7TB")

    def test_october_23_parallel_cms_columns_match_official_gpu_prices(self):
        content = (FIXTURE.parent / "crusoe-pricing-20261023.html").read_text()
        prices = parse(content)
        self.assertEqual(len(prices), 24)
        self.assertEqual(
            [(q["gpu_model"], q["gpu_variant"], q["amount"]) for q in prices if q["amount"] is not None],
            [("B300", "HGX", "8.96"), ("H200", "HGX", "4.29"), ("H100", "HGX", "3.90"),
             ("A100", "SXM", "2.30"), ("A100", "PCIe", "2.00"), ("L40S", None, "1.50"),
             ("MI300X", None, "3.45")],
        )
        self.assertEqual(sum(q["quote_status"] == "contact_sales" for q in prices), 17)
        self.assertTrue(all(q["amount"] is None for q in prices if q["billing_mode"] == "spot"))
        self.assertEqual(next(q for q in prices if q["gpu_model"] == "VERA RUBIN")["vram_gb"], 288)
        self.assertTrue(all(q["observed_at"] == OBSERVED_AT and q["regions"] == [] for q in prices))

    def test_cms_model_column_uses_the_official_explicit_sort_order(self):
        content = (FIXTURE.parent / "crusoe-pricing-20261023.html").read_text()
        expected = parse(content)
        soup = BeautifulSoup(content, "html.parser")
        model_list = soup.select_one(".pricing_gpu-item > .w-dyn-list > .w-dyn-items")
        for item in list(model_list.select(":scope > .w-dyn-item"))[::-1]:
            model_list.append(item.extract())
        self.assertEqual(parse(str(soup)), expected)

    def test_cms_unequal_columns_and_ambiguous_model_order_cannot_shift_prices(self):
        content = (FIXTURE.parent / "crusoe-pricing-20261023.html").read_text()
        for corruption in ("missing_price", "missing_model", "duplicate_order", "missing_order",
                           "changed_name", "sorted_price_column", "extra_price"):
            with self.subTest(corruption=corruption):
                soup = BeautifulSoup(content, "html.parser")
                columns = soup.select(".pricing_gpu-item > .w-dyn-list > .w-dyn-items")
                models = columns[0].select(":scope > .w-dyn-item")
                if corruption == "missing_price":
                    columns[1].select(":scope > .w-dyn-item")[0].decompose()
                elif corruption == "missing_model":
                    models[0].decompose()
                elif corruption == "duplicate_order":
                    models[1]["data-sort-order"] = models[0]["data-sort-order"]
                elif corruption == "missing_order":
                    del models[0]["data-sort-order"]
                elif corruption == "changed_name":
                    models[0]["data-sort-name"] = "Unmatched GPU"
                elif corruption == "sorted_price_column":
                    columns[1].select(":scope > .w-dyn-item")[0]["data-sort-order"] = "20"
                else:
                    soup.select_one(".pricing_gpu-item").append(BeautifulSoup('<div class="pricing-rich">$0.01/GPU-hr</div>', "html.parser"))
                with self.assertRaises(ValueError):
                    parse(str(soup))

    def test_cms_price_columns_use_headers_and_still_reject_wrong_units(self):
        content = (FIXTURE.parent / "crusoe-pricing-20261023.html").read_text()
        swapped = content.replace("On-demand", "TEMP").replace("Current spot", "On-demand").replace("TEMP", "Current spot")
        self.assertTrue(all(q["billing_mode"] == "spot" for q in parse(swapped) if q["amount"] is not None))
        with self.assertRaises(ValueError):
            parse(content.replace("GPU-hr", "GPU-month", 1))

    def test_missing_or_ambiguous_memory_still_rejected_for_numeric_quotes(self):
        variants = [
            self.content.replace("141GB", ""),
            self.content.replace("141GB", "<span>141GB</span><span>80GB</span>"),
            self.content.replace(
                '<div class="pricing-tag">141GB</div>',
                '<div class="pricing-tag">141GB</div><div class="pricing-tag">80GB</div>',
            ),
        ]
        for content in variants:
            with self.subTest(content=content[:100]), self.assertRaises(ValueError):
                parse(content)

    def test_unrecognized_page_or_structure_fails_closed(self):
        cases = [
            "<html><h1>Access denied</h1></html>",
            self.content.replace("GPU instances pricing", "All pricing"),
            self.content.replace("Current spot", "Reserved"),
            self.content.replace("pricing_gpu-item", "changed-item"),
            self.content.replace("$3.90/GPU-hr", "$3.90/token"),
            self.content.replace("$3.90/GPU-hr", "$0/GPU-hr"),
            self.content.replace("141GB", "unknown"),
            self.content.replace("<h4 class=\"pricing-item-heading\">NVIDIA H200</h4>", ""),
        ]
        for content in cases:
            with self.subTest(content=content[:100]):
                with self.assertRaises(ValueError):
                    parse(content)


if __name__ == "__main__":
    unittest.main()
