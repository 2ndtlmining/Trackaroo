"""
Tests for the Scorptec scraper (scraper.scorptec.py).

Tests:
- URL fallback when href is empty (JS-populated links)
- Product grid parsing with data attributes
- Category URL path mapping
- Pagination detection (get_next_page_url)
- fetch_page retry behaviour (200, non-200, exceptions)
- Full pagination loop (scrape_all_pages)
"""
import unittest.mock
from pathlib import Path

import requests
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper.scorptec import parse_product_grid, CATEGORY_URL_PATHS, BASE


# ── HTML fixtures ───────────────────────────────────────────────────

HTML_WITH_EMPTY_HREF = """
<html>
<body>
<div class="product-grid"
     data-shortintro="intel core i7 14700k desktop processor"
     data-intro="Intel Core i7-14700K Desktop Processor"
     data-price="625"
     data-instock="1"
     data-sku="105935">
  <div class="grid-product-title"><a href="">intel core i7 14700k</a></div>
</div>
<div class="product-grid"
     data-shortintro="intel core i5 14500 desktop processor"
     data-intro="Intel Core i5-14500 Desktop Processor"
     data-price="479"
     data-instock="0"
     data-sku="107529">
  <div class="grid-product-title"><a href="">intel core i5 14500</a></div>
</div>
</body>
</html>
"""

HTML_WITH_VALID_HREF = """
<html>
<body>
<div class="product-grid"
     data-shortintro="amd ryzen 5 5600x desktop processor"
     data-intro="AMD Ryzen 5 5600X Desktop Processor"
     data-price="249"
     data-instock="1"
     data-sku="86005">
  <div class="grid-product-title"><a href="/product/cpu/amd-socket-am4/86005">amd ryzen 5 5600x</a></div>
</div>
</body>
</html>
"""

HTML_GPU_EMPTY_HREF = """
<html>
<body>
<div class="product-grid"
     data-shortintro="asus geforce rtx 4070 ti 12gb"
     data-intro="ASUS GeForce RTX 4070 Ti 12GB"
     data-price="1349"
     data-instock="1"
     data-sku="101470">
  <div class="grid-product-title"><a href="">asus geforce rtx 4070 ti</a></div>
</div>
<div class="product-grid"
     data-shortintro="sapphire radeon rx 7900 xtx 24gb"
     data-intro="Sapphire Radeon RX 7900 XTX 24GB"
     data-price="1699"
     data-instock="0"
     data-sku="101630">
  <div class="grid-product-title"><a href="">sapphire radeon rx 7900 xtx</a></div>
</div>
</body>
</html>
"""


# ── Category path mapping tests ────────────────────────────────────

class TestCategoryUrlPaths:
    """Test that all category keys have a corresponding URL path."""

    def test_all_categories_have_path(self):
        from scraper.scorptec import CATEGORY_URLS
        for key in CATEGORY_URLS:
            assert key in CATEGORY_URL_PATHS, f"Missing path for {key}"

    def test_cpu_intel_path(self):
        assert CATEGORY_URL_PATHS["cpu_intel_all"] == "cpu/intel"

    def test_gpu_nvidia_path(self):
        assert CATEGORY_URL_PATHS["gpu_nvidia"] == "graphics-cards/nvidia"

    def test_gpu_amd_path(self):
        assert CATEGORY_URL_PATHS["gpu_amd"] == "graphics-cards/amd"

    def test_amd_am5_paths_use_am5_socket(self):
        assert CATEGORY_URL_PATHS["cpu_amd_am5_7000"] == "cpu/amd-socket-am5"
        assert CATEGORY_URL_PATHS["cpu_amd_am5_8000"] == "cpu/amd-socket-am5"
        assert CATEGORY_URL_PATHS["cpu_amd_am5_9000"] == "cpu/amd-socket-am5"

    def test_amd_am4_path(self):
        assert CATEGORY_URL_PATHS["cpu_amd_am4"] == "cpu/amd-socket-am4"


# ── URL fallback tests ─────────────────────────────────────────────

class TestEmptyUrlFallback:
    """Test that empty href attributes get fallback URLs constructed from SKU."""

    def test_intel_cpu_empty_href_gets_fallback(self):
        products = parse_product_grid(HTML_WITH_EMPTY_HREF, category_path="cpu/intel")
        assert len(products) == 2
        # Both products should have constructed URLs
        for p in products:
            assert p["url"].startswith(f"{BASE}/product/cpu/intel/")
            assert p["retailer_sku"] in p["url"]

    def test_fallback_url_includes_sku(self):
        products = parse_product_grid(HTML_WITH_EMPTY_HREF, category_path="cpu/intel")
        i7_product = [p for p in products if "14700k" in p["name"].lower()][0]
        assert "105935" in i7_product["url"]

        i5_product = [p for p in products if "14500" in p["name"].lower()][0]
        assert "107529" in i5_product["url"]

    def test_gpu_empty_href_gets_fallback(self):
        products = parse_product_grid(HTML_GPU_EMPTY_HREF, category_path="graphics-cards/nvidia")
        assert len(products) == 2
        for p in products:
            assert p["url"].startswith(f"{BASE}/product/graphics-cards/nvidia/")
            assert p["retailer_sku"] in p["url"]

    def test_no_category_path_means_no_fallback(self):
        """When category_path is not provided, empty href stays empty."""
        products = parse_product_grid(HTML_WITH_EMPTY_HREF, category_path="")
        for p in products:
            assert p["url"] == ""

    def test_valid_href_not_overwritten(self):
        """When href is present, it is used as-is (not overwritten by fallback)."""
        products = parse_product_grid(HTML_WITH_VALID_HREF, category_path="cpu/intel")
        assert len(products) == 1
        p = products[0]
        # Should use the original href, not the fallback
        assert "/product/cpu/amd-socket-am4/86005" in p["url"]

    def test_stock_status_parsed_correctly(self):
        products = parse_product_grid(HTML_WITH_EMPTY_HREF, category_path="cpu/intel")
        i7 = [p for p in products if "14700k" in p["name"].lower()][0]
        assert i7["stock_status"] == "in_stock"
        i5 = [p for p in products if "14500" in p["name"].lower()][0]
        assert i5["stock_status"] == "out_of_stock"

    def test_price_parsed_from_empty_href_product(self):
        products = parse_product_grid(HTML_WITH_EMPTY_HREF, category_path="cpu/intel")
        i7 = [p for p in products if "14700k" in p["name"].lower()][0]
        assert i7["price_aud"] == 625.0


# ── Integration: full scrape produces no empty URLs ────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestScorptecDataQuality:
    """Verify that actual scraped data files have no empty URLs."""

    def test_cpu_file_no_empty_urls(self):
        import json
        import glob
        cpu_files = glob.glob(str(PROJECT_ROOT / "data" / "cpu_scorptec_*.json"))
        assert len(cpu_files) > 0, "No CPU data files found"
        for fpath in cpu_files:
            with open(fpath) as f:
                data = json.load(f)
            for p in data["products"]:
                assert p.get("url"), f"Empty URL for {p['watchlist_model']} in {fpath}"

    def test_gpu_file_no_empty_urls(self):
        import json
        import glob
        gpu_files = glob.glob(str(PROJECT_ROOT / "data" / "gpu_scorptec_*.json"))
        assert len(gpu_files) > 0, "No GPU data files found"
        for fpath in gpu_files:
            with open(fpath) as f:
                data = json.load(f)
            for p in data["products"]:
                assert p.get("url"), f"Empty URL for {p['watchlist_model']} in {fpath}"


# ── Stock label mapping tests ──────────────────────────────────────


def test_map_stock_label_in_stock():
    from scraper.pccg import _map_stock_label
    assert _map_stock_label("In stock") == "in_stock"


def test_map_stock_label_sold_out():
    from scraper.pccg import _map_stock_label
    assert _map_stock_label("Sold Out") == "out_of_stock"


def test_map_stock_label_eta():
    from scraper.pccg import _map_stock_label
    assert _map_stock_label("ETA: 01/01/26") == "preorder"


def test_map_stock_label_preorder():
    from scraper.pccg import _map_stock_label
    assert _map_stock_label("Stock at Supplier") == "preorder"


def test_map_stock_label_unknown():
    from scraper.pccg import _map_stock_label
    assert _map_stock_label("") == "unknown"
    assert _map_stock_label("Discontinued") == "unknown"


# ── _extract_products sold-out retention & is_ETA_TBA guard ─────


def test_extract_products_retains_sold_out():
    """Sold-out products are kept — their price history still matters."""
    from scraper.pccg import _extract_products
    hits = [
        {
            "products_name": "RTX 5090 Founders Edition",
            "products_price": 2499,
            "Product_URL": "/products/geforce-rtx-5090/123456",
            "manufacturers_name": "NVIDIA",
            "indicator": {"label": "Sold Out"},
        },
    ]
    products = _extract_products(hits)
    assert len(products) == 1
    assert products[0]["stock_status"] == "out_of_stock"
    assert products[0]["price"] == 2499


def test_extract_products_uses_is_eta_tba_fallback():
    """When indicator.label is missing, is_ETA_TBA = '1' maps to preorder."""
    from scraper.pccg import _extract_products
    hits = [
        {
            "products_name": "RTX 5080 Model",
            "products_price": 1299,
            "Product_URL": "/products/rtx-5080/789012",
            "manufacturers_name": "MSI",
            "indicator": None,
            "is_ETA_TBA": "1",
        },
    ]
    products = _extract_products(hits)
    assert len(products) == 1
    assert products[0]["stock_status"] == "preorder"


def test_extract_products_indicator_wins_over_is_eta_tba():
    """If indicator.label is present it takes precedence over is_ETA_TBA."""
    from scraper.pccg import _extract_products
    hits = [
        {
            "products_name": "RTX 5070 Model",
            "products_price": 899,
            "Product_URL": "/products/rtx-5070/345678",
            "manufacturers_name": "ASRock",
            "indicator": {"label": "In stock"},
            "is_ETA_TBA": "1",
        },
    ]
    products = _extract_products(hits)
    assert len(products) == 1
    assert products[0]["stock_status"] == "in_stock"


def test_extract_products_unknown_when_no_signals():
    """Both indicator and is_ETA_TBA absent → unknown."""
    from scraper.pccg import _extract_products
    hits = [
        {
            "products_name": "RTX 5060 Model",
            "products_price": 499,
            "Product_URL": "/products/rtx-5060/901234",
            "manufacturers_name": "Gigabyte",
        },
    ]
    products = _extract_products(hits)
    assert len(products) == 1
    assert products[0]["stock_status"] == "unknown"


# ── STOCK_ATTRS guard ──────────────────────────────────────────────


def test_stock_attrs_includes_indicator_and_is_eta_tba():
    """STOCK_ATTRS must request indicator and is_ETA_TBA so status parsing works."""
    from scraper.pccg import STOCK_ATTRS
    assert "indicator" in STOCK_ATTRS
    assert "is_ETA_TBA" in STOCK_ATTRS


# ── Pagination tests ───────────────────────────────────────────────

HTML_WITH_NEXT_PAGE = """
<html>
<body>
<div class="product-grid"
     data-shortintro="test gpu" data-intro="Test GPU"
     data-price="500" data-instock="1" data-sku="111111">
  <div class="grid-product-title"><a href="/product/graphics-cards/nvidia/111111">test gpu</a></div>
</div>
<nav class="pagination">
  <a href="/product/graphics-cards/nvidia?paged=2" class="next">Next</a>
</nav>
</body>
</html>
"""

HTML_NO_NEXT_PAGE = """
<html>
<body>
<div class="product-grid"
     data-shortintro="last gpu" data-intro="Last GPU"
     data-price="600" data-instock="1" data-sku="222222">
  <div class="grid-product-title"><a href="/product/graphics-cards/nvidia/222222">last gpu</a></div>
</div>
<nav class="pagination">
  <span class="disabled">Next</span>
</nav>
</body>
</html>
"""

HTML_EMPTY_PAGE = """
<html><body></body></html>
"""


class TestGetNextPageUrl:
    """Test pagination link detection."""

    def test_finds_next_page_link(self):
        from scraper.scorptec import get_next_page_url
        url = get_next_page_url(HTML_WITH_NEXT_PAGE, "https://www.scorptec.com.au")
        assert url is not None
        assert "paged=2" in url

    def test_returns_none_when_no_next_page(self):
        from scraper.scorptec import get_next_page_url
        url = get_next_page_url(HTML_NO_NEXT_PAGE, "https://www.scorptec.com.au")
        assert url is None

    def test_returns_none_when_no_pagination(self):
        from scraper.scorptec import get_next_page_url
        url = get_next_page_url(HTML_EMPTY_PAGE, "https://www.scorptec.com.au")
        assert url is None

    def test_handles_absolute_url(self):
        from scraper.scorptec import get_next_page_url
        html = '<a href="https://www.scorptec.com.au/product/graphics-cards/nvidia?paged=2" class="next">Next</a>'
        url = get_next_page_url(html, "https://www.scorptec.com.au")
        assert url == "https://www.scorptec.com.au/product/graphics-cards/nvidia?paged=2"


class TestFetchPage:
    """Functional tests for fetch_page retry behaviour (network mocked)."""

    @staticmethod
    def _resp(status_code, text=""):
        resp = unittest.mock.Mock()
        resp.status_code = status_code
        resp.text = text
        return resp

    def test_200_returns_text(self, monkeypatch):
        from scraper.scorptec import fetch_page
        calls = []

        def _get(url, headers=None, timeout=None):
            calls.append(url)
            return self._resp(200, "<html>ok</html>")

        monkeypatch.setattr("scraper.scorptec.requests.get", _get)
        assert fetch_page("https://example.com") == "<html>ok</html>"
        assert len(calls) == 1  # No retry on first success

    def test_non_200_then_200_retries(self, monkeypatch):
        from scraper.scorptec import fetch_page
        responses = [self._resp(503), self._resp(200, "recovered")]

        def _get(url, headers=None, timeout=None):
            return responses.pop(0)

        monkeypatch.setattr("scraper.scorptec.requests.get", _get)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)
        assert fetch_page("https://example.com") == "recovered"

    def test_all_attempts_fail_returns_none(self, monkeypatch):
        from scraper.scorptec import fetch_page

        def _get(url, headers=None, timeout=None):
            return self._resp(500)

        monkeypatch.setattr("scraper.scorptec.requests.get", _get)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)
        assert fetch_page("https://example.com", retries=1) is None

    def test_exception_returns_none(self, monkeypatch):
        from scraper.scorptec import fetch_page

        def _get(url, headers=None, timeout=None):
            raise requests.RequestException("boom")

        monkeypatch.setattr("scraper.scorptec.requests.get", _get)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)
        assert fetch_page("https://example.com", retries=1) is None


class TestScrapeAllPages:
    """Functional tests for the pagination loop (fetch -> parse -> follow next)."""

    START_URL = "https://www.scorptec.com.au/product/graphics-cards/nvidia"

    def test_collects_products_from_multiple_pages(self, monkeypatch):
        from scraper.scorptec import scrape_all_pages

        def _fetch(url, retries=2):
            if "paged=2" in url:
                return HTML_NO_NEXT_PAGE
            return HTML_WITH_NEXT_PAGE

        monkeypatch.setattr("scraper.scorptec.fetch_page", _fetch)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)

        products = scrape_all_pages(self.START_URL, category_path="graphics-cards/nvidia")
        assert len(products) == 2
        assert {p["name"] for p in products} == {"test gpu", "last gpu"}

    def test_stops_at_max_pages(self, monkeypatch):
        from scraper.scorptec import scrape_all_pages
        calls = []

        def _fetch(url, retries=2):
            calls.append(url)
            return HTML_WITH_NEXT_PAGE  # Every page claims there is a next one.

        monkeypatch.setattr("scraper.scorptec.fetch_page", _fetch)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)

        products = scrape_all_pages(self.START_URL, category_path="graphics-cards/nvidia", max_pages=3)
        assert len(calls) == 3  # max_pages caps the loop
        assert len(products) == 3

    def test_stops_on_fetch_failure(self, monkeypatch):
        """A failed fetch mid-pagination stops the loop and keeps prior pages."""
        from scraper.scorptec import scrape_all_pages

        def _fetch(url, retries=2):
            if "paged=2" in url:
                return None
            return HTML_WITH_NEXT_PAGE

        monkeypatch.setattr("scraper.scorptec.fetch_page", _fetch)
        monkeypatch.setattr("scraper.scorptec.time.sleep", lambda s: None)

        products = scrape_all_pages(self.START_URL, category_path="graphics-cards/nvidia")
        assert len(products) == 1
        assert products[0]["name"] == "test gpu"

    def test_max_pages_default_is_config_value(self):
        """The pagination safety cap defaults to config.SCORPTEC_MAX_PAGES."""
        import config
        from scraper.scorptec import scrape_all_pages
        import inspect
        sig = inspect.signature(scrape_all_pages)
        assert sig.parameters["max_pages"].default == config.SCORPTEC_MAX_PAGES


class TestPCCGPagination:
    """Test PCCG Algolia pagination."""

    def test_extract_products_from_hits(self):
        from scraper.pccg import _extract_products
        hits = [
            {"products_name": "Test GPU", "products_price": 500, "Product_URL": "/products/123", "manufacturers_name": "NVIDIA"},
        ]
        products = _extract_products(hits)
        assert len(products) == 1
        assert products[0]["name"] == "Test GPU"
        assert products[0]["price"] == 500
        assert "pccasegear.com" in products[0]["url"]

    def test_extract_products_skips_empty_name(self):
        from scraper.pccg import _extract_products
        hits = [
            {"products_name": "", "products_price": 500, "Product_URL": "/products/123", "manufacturers_name": "NVIDIA"},
        ]
        products = _extract_products(hits)
        assert len(products) == 0

    def test_extract_products_handles_none_price(self):
        from scraper.pccg import _extract_products
        hits = [
            {"products_name": "Test GPU", "products_price": None, "Product_URL": "/products/123", "manufacturers_name": "NVIDIA"},
        ]
        products = _extract_products(hits)
        assert len(products) == 1
        assert products[0]["price"] is None

    def test_algolia_single_search_callable(self):
        from scraper.pccg import algolia_single_search
        import inspect
        sig = inspect.signature(algolia_single_search)
        assert "query" in sig.parameters
        assert "category_filter" in sig.parameters
        assert "hits_per_page" in sig.parameters
        assert "max_pages" in sig.parameters

    def test_algolia_batch_search_delegates(self):
        from scraper.pccg import algolia_batch_search
        import inspect
        sig = inspect.signature(algolia_batch_search)
        assert "queries" in sig.parameters
        assert "category_filter" in sig.parameters
