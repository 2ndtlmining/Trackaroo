"""
Tests for the Umart scraper (scraper/umart.py).

The fixtures below are trimmed from a real
`/pc-parts/computer-parts/graphics-cards-gpu-610` response captured 31-Aug-2026.
Umart's grid is microdata-rich, which is why the parser reads attributes rather
than text: `data-id` is the SKU, `.goods-price[content]` carries the price as a
number, and stock comes from `link[itemprop=availability]`.

That matters for one specific reason recorded in THIRD_RETAILER.md: the *visible*
price renders as `$&nbsp;579.00`, so a naive dollar-sign regex over the raw HTML
matches nothing and the page looks client-rendered. It is not. Reading the
`content` attribute sidesteps the entity entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.umart import (  # noqa: E402
    BASE,
    CATEGORY_URLS,
    HEADERS,
    fetch_page,
    get_max_page,
    parse_product_grid,
    scrape_umart,
)


def _card(sku: str, brand: str, name: str, price: str, availability: str, slug: str) -> str:
    stock_text = "In Stock" if availability == "InStock" else "Out Of Stock"
    return f"""
<div class="row goods-item" data-brand="{brand}" data-id="{sku}" data-position="1">
  <div class="goods_name">
    <a href="/product/{slug}-{sku}" title="{name}"><span itemprop="name">{name}</span></a>
  </div>
  <div class="goods_price_stock goods_price_section clearfix">
    <span hidden="" itemprop="brand">{brand}</span>
    <span class="goods_price graphik-bold" itemprop="offers" itemscope=""
          itemtype="http://schema.org/Offer">
      <span content="AUD" itemprop="priceCurrency">$</span><span
        class="goods-price ele-goods-price" content="{price}"
        itemprop="price">{price}</span>
      <link href="http://schema.org/{availability}" itemprop="availability"/>
    </span>
    <span class="goods_stock graphik-bold"><span>{stock_text}</span></span>
  </div>
</div>"""


GRID_HTML = """
<html><body>
{c1}
{c2}
{c3}
<ul class="pagination">
  <li><a href="/pc-parts/computer-parts/graphics-cards-gpu-610?page=1">1</a></li>
  <li><a href="/pc-parts/computer-parts/graphics-cards-gpu-610?page=2">2</a></li>
  <li><a href="/pc-parts/computer-parts/graphics-cards-gpu-610?page=11">11</a></li>
</ul>
</body></html>""".format(
    c1=_card(
        "95655",
        "Asus",
        "Asus Dual GeForce RTX 5060 8G OC Advanced Graphics Card (DUAL-RTX5060-O8G-A)",
        "579.00",
        "InStock",
        "asus-dual-geforce-rtx-5060-8g-oc-advanced-graphics-card-dual-rtx5060-o8g-a",
    ),
    c2=_card(
        "90401",
        "Asus",
        "Asus Dual Radeon RX 9060 XT 16G Graphics Card (DUAL-RX9060XT-16G)",
        "749.00",
        "OutOfStock",
        "asus-dual-radeon-rx-9060-xt-16g-graphics-card-dual-rx9060xt-16g",
    ),
    c3=_card(
        "59529",
        "Asus",
        "Asus GeForce RTX 3060 Dual V2 OC 12G LHR Graphics Card (DUAL-RTX3060-O12G-V2)",
        "1,499.00",
        "InStock",
        "asus-geforce-rtx-3060-dual-v2-oc-12g-lhr-graphics-card",
    ),
)

EMPTY_HTML = "<html><body><p>No products found.</p></body></html>"


class TestParseProductGrid:
    def test_finds_every_card(self):
        assert len(parse_product_grid(GRID_HTML)) == 3

    def test_reads_the_name(self):
        first = parse_product_grid(GRID_HTML)[0]
        assert first["name"] == (
            "Asus Dual GeForce RTX 5060 8G OC Advanced Graphics Card (DUAL-RTX5060-O8G-A)"
        )

    def test_reads_the_price_from_the_content_attribute(self):
        """Not from the text: the visible price renders as `$&nbsp;579.00`."""
        assert parse_product_grid(GRID_HTML)[0]["price_aud"] == 579.00

    def test_handles_a_thousands_separator(self):
        assert parse_product_grid(GRID_HTML)[2]["price_aud"] == 1499.00

    def test_reads_stock_from_schema_org_availability(self):
        cards = parse_product_grid(GRID_HTML)
        assert cards[0]["stock_status"] == "in_stock"
        assert cards[1]["stock_status"] == "out_of_stock"

    def test_uses_data_id_as_the_retailer_sku(self):
        """Listings are keyed by SKU, never by URL -- retailers rewrite slugs."""
        assert [c["retailer_sku"] for c in parse_product_grid(GRID_HTML)] == [
            "95655",
            "90401",
            "59529",
        ]

    def test_builds_an_absolute_product_url(self):
        url = parse_product_grid(GRID_HTML)[0]["url"]
        assert url.startswith(BASE)
        assert url.endswith("-95655")

    def test_empty_page_yields_nothing_and_does_not_raise(self):
        assert parse_product_grid(EMPTY_HTML) == []

    def test_a_card_missing_its_price_is_skipped_not_fatal(self):
        broken = (
            '<div class="row goods-item" data-id="1">'
            '<div class="goods_name"><a href="/product/x-1">X</a></div></div>'
        )
        assert parse_product_grid(broken) == []


class TestGetMaxPage:
    def test_reads_the_highest_page_number(self):
        assert get_max_page(GRID_HTML) == 11

    def test_a_single_page_category_reports_one(self):
        assert get_max_page(EMPTY_HTML) == 1


class TestFetchPage:
    def test_returns_html_on_success(self):
        with patch("scraper.umart.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.text = "<html>ok</html>"
            assert fetch_page(BASE + "/x") == "<html>ok</html>"

    def test_returns_none_on_http_error(self):
        with patch("scraper.umart.requests.get") as get:
            get.return_value.status_code = 500
            get.return_value.text = ""
            with patch("scraper.umart.time.sleep"):
                assert fetch_page(BASE + "/x") is None

    def test_identifies_itself_honestly(self):
        """A personal tracker should say what it is, as the other scrapers do."""
        assert "Trackaroo" in HEADERS["User-Agent"]


class TestCategoryUrls:
    def test_covers_both_categories(self):
        assert set(CATEGORY_URLS) == {"cpu", "gpu"}

    def test_uses_the_discovered_path_scheme(self):
        """The old `_1350G.html` guess was the *goods* form and bounced to the
        homepage; categories are path-based with a trailing numeric id."""
        assert CATEGORY_URLS["gpu"].endswith("graphics-cards-gpu-610")
        assert CATEGORY_URLS["cpu"].endswith("cpu-processors-611")


class TestScrapeUmart:
    def _watchlist(self):
        return [
            {
                "model": "GeForce RTX 5060",
                "category": "gpu",
                "brand": "NVIDIA",
                "gen_tier": "current",
                "vram_gb": 8,
                "cores": None,
            },
            {
                "model": "Radeon RX 9060 XT",
                "category": "gpu",
                "brand": "AMD",
                "gen_tier": "current",
                "vram_gb": 16,
                "cores": None,
            },
        ]

    def test_matches_watchlist_products_and_records_the_retailer(self):
        with patch("scraper.umart.fetch_page", return_value=GRID_HTML), patch(
            "scraper.umart.time.sleep"
        ), patch("scraper.umart.get_max_page", return_value=1):
            results, matched, _ = scrape_umart(self._watchlist())
        models = {r["watchlist_model"] for r in results}
        assert "GeForce RTX 5060" in models
        assert "Radeon RX 9060 XT" in models
        assert all(r["retailer"] == "umart" for r in results)
        assert matched

    def test_carries_the_sku_and_stock_through_to_the_result(self):
        with patch("scraper.umart.fetch_page", return_value=GRID_HTML), patch(
            "scraper.umart.time.sleep"
        ), patch("scraper.umart.get_max_page", return_value=1):
            results, _, _ = scrape_umart(self._watchlist())
        by_model = {r["watchlist_model"]: r for r in results}
        assert by_model["GeForce RTX 5060"]["retailer_sku"] == "95655"
        assert by_model["Radeon RX 9060 XT"]["stock_status"] == "out_of_stock"

    def test_an_unreachable_category_does_not_raise(self):
        with patch("scraper.umart.fetch_page", return_value=None), patch(
            "scraper.umart.time.sleep"
        ):
            results, matched, _ = scrape_umart(self._watchlist())
        assert results == []
        assert matched == set()
