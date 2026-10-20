"""Public homepage prices keep membership and geography distinctions."""

from decimal import Inexact, localcontext
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from bs4 import BeautifulSoup

from gpu_price_monitor.providers.autodl import SOURCE_URL, collect_quotes, parse_prices
from gpu_price_monitor.settings import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "autodl-public-pricing.html"
OBSERVED_AT = "2026-10-20T02:00:00+00:00"


def snapshots(content):
    return [str(section) for section in BeautifulSoup(content, "html.parser").select(".display-module")]


def parse(content):
    return parse_prices(content, observed_at=OBSERVED_AT)


class AutoDLPublicTests(TestCase):
    def setUp(self):
        self.content = FIXTURE.read_text(encoding="utf-8")
        self.pages = snapshots(self.content)

    def test_parses_displayed_tiers_without_mixing_prices(self):
        ordinary, member = [parse(page) for page in self.pages]
        self.assertEqual({q["pricing_tier"] for q in ordinary}, {"ordinary"})
        self.assertEqual({q["pricing_tier"] for q in member}, {"member"})
        h800 = next(q for q in ordinary if q["gpu_model"] == "H800")
        discounted = next(q for q in member if q["gpu_model"] == "H800")
        self.assertEqual(h800["amount"], "10.50")
        self.assertEqual(discounted["amount"], "9.98")
        self.assertFalse(h800["membership_required"])
        self.assertIsNone(h800["membership_discount"])
        self.assertTrue(discounted["membership_required"])
        self.assertEqual(discounted["membership_discount"], "0.95")
        self.assertTrue(all(q["currency"] == "CNY" and q["unit"] == "gpu_hour" for q in ordinary + member))

    def test_model_memory_and_non_nvidia_gpu_are_retained(self):
        quotes = parse(self.pages[0])
        self.assertIn(("A800", 80), {(q["gpu_model"], q["vram_gb"]) for q in quotes})
        self.assertIn(("RTX 4090", 24), {(q["gpu_model"], q["vram_gb"]) for q in quotes})
        self.assertIn(("MTT S4000", 48), {(q["gpu_model"], q["vram_gb"]) for q in quotes})

    def test_homepage_does_not_invent_marketplace_or_account_details(self):
        for quote in parse(self.pages[0]) + parse(self.pages[1]):
            self.assertEqual(quote["regions"], [])
            self.assertEqual(quote["geographic_scope"], "unspecified")
            self.assertEqual(quote["account_scope"], "public_catalog")
            self.assertEqual(quote["tax_scope"], "unspecified")
            self.assertEqual(quote["availability"], "unknown")
            self.assertIsNone(quote["gpu_count"])
            self.assertIsNone(quote["gpu_variant"])
            self.assertIsNone(quote["raw_sku"])
            self.assertIsNone(quote["effective_from"])
            self.assertIsNone(quote["effective_until"])
            self.assertEqual(quote["observed_at"], OBSERVED_AT)
            self.assertEqual(quote["source_url"], SOURCE_URL)
            self.assertEqual(quote["source_type"], "public_page")
            self.assertIn("not a region-specific marketplace quote", " ".join(quote["notes"]))

    def test_browser_collection_validates_both_tabs_and_rounding(self):
        with patch("gpu_price_monitor.browser.fetch_autodl_pages", return_value=self.pages) as render:
            quotes = collect_quotes(settings=Settings(), observed_at=OBSERVED_AT)
        self.assertEqual(len(quotes), len(parse(self.pages[0])) * 2)
        render.assert_called_once()

    def test_callers_decimal_precision_does_not_change_prices(self):
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            with patch("gpu_price_monitor.browser.fetch_autodl_pages", return_value=self.pages):
                quotes = collect_quotes(settings=Settings(), observed_at=OBSERVED_AT)
        h800 = next(q for q in quotes if q["gpu_model"] == "H800" and q["pricing_tier"] == "member")
        self.assertEqual((h800["amount"], h800["membership_discount"]), ("9.98", "0.95"))

    def test_browser_collection_rejects_duplicate_missing_or_inconsistent_tabs(self):
        soup = BeautifulSoup(self.pages[1], "html.parser")
        soup.select_one(".gpu-item").decompose()
        cases = [
            [], [self.pages[0]], [self.pages[0], self.pages[0]],
            self.pages[::-1], [self.pages[0], str(soup)],
            [self.pages[0], self.pages[1].replace("9.98", "9.97")],
        ]
        for pages in cases:
            with self.subTest(pages=str(pages)[:80]):
                with patch("gpu_price_monitor.browser.fetch_autodl_pages", return_value=pages):
                    with self.assertRaises(ValueError):
                        collect_quotes(settings=Settings(), observed_at=OBSERVED_AT)

    def test_unknown_units_discounts_memory_or_page_structure_fail_closed(self):
        ordinary, member = self.pages
        cases = [
            "<html><body>AutoDL网站需要使用JavaScript实现功能</body></html>",
            ordinary.replace("炼丹会员及租用价格", "Pricing"),
            ordinary.replace("member-gpu-price", "new-price-list"),
            ordinary.replace("普通用户", "Enterprise"),
            ordinary.replace("class=\"active\"", "class=\"inactive\""),
            ordinary.replace("/时", "/天"),
            ordinary.replace("￥", "$"),
            ordinary.replace("10.50", "0"),
            ordinary.replace("80GB", "unknown"),
            member.replace("会员95折", "会员价"),
            member.replace("会员95折", "会员0折"),
            member.replace("会员95折", "会员200折"),
            self.content,
        ]
        for content in cases:
            with self.subTest(content=content[:100]):
                with self.assertRaises(ValueError):
                    parse(content)

    def test_incomplete_or_duplicate_card_does_not_produce_partial_success(self):
        for mutation in ("missing_name", "missing_price", "duplicate", "unknown_card"):
            soup = BeautifulSoup(self.pages[0], "html.parser")
            cards = soup.select_one(".member-gpu-price")
            if mutation == "missing_name":
                cards.select_one(".gpu-item .name").decompose()
            elif mutation == "missing_price":
                cards.select_one(".gpu-item .price").decompose()
            elif mutation == "duplicate":
                cards.append(BeautifulSoup(str(cards.select_one(".gpu-item")), "html.parser"))
            else:
                cards.append(BeautifulSoup("<div>Unrecognized GPU</div>", "html.parser"))
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    parse(str(soup))

    def test_chinese_nine_discount_notation_is_supported(self):
        member = self.pages[1].replace("会员95折", "会员9折")
        self.assertTrue(all(q["membership_discount"] == "0.9" for q in parse(member)))
