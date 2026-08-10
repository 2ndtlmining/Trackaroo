"""
Tests for the Scorptec scraper (fetch_test.py).

Tests:
- URL fallback when href is empty (JS-populated links)
- Product grid parsing with data attributes
- Category URL path mapping
"""
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch_test import parse_product_grid, CATEGORY_URL_PATHS, BASE


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
        from fetch_test import CATEGORY_URLS
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
