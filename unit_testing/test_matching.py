"""
Tests for product matching logic in the scrapers.

Ensures that:
- Correct products match their watchlist entry
- Similar-but-different products do NOT match (e.g. 5800X ≠ 5800X3D)
- GPU VRAM guard works to prevent false matches
"""
import sys
from pathlib import Path

import pytest

# Import matching functions from each scraper
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper.pccg import match_product as pccg_match
from scraper.pccg import _parse_price as pccg_parse_price
from scraper.pccg import _is_bundle_product as pccg_is_bundle
from scraper.scorptec import match_product as scorptec_match
from scraper.scorptec import _is_bundle_product as scorptec_is_bundle


# ── Watchlist product fixtures for matching tests ────────────────────

def _make_watchlist_cpu(model, search_terms, cores=8):
    return {
        "category": "cpu",
        "brand": "AMD",
        "model": model,
        "cores": cores,
        "vram_gb": None,
        "search_terms": search_terms,
    }


def _make_watchlist_gpu(model, search_terms, vram_gb=16):
    return {
        "category": "gpu",
        "brand": "NVIDIA",
        "model": model,
        "cores": None,
        "vram_gb": vram_gb,
        "search_terms": search_terms,
    }


# ── CPU matching tests ──────────────────────────────────────────────

class TestPCCGCPUMatching:
    """Test CPU product matching for PCCG scraper."""

    def test_exact_match(self):
        wp = _make_watchlist_cpu("Ryzen 7 9800X3D", ["ryzen 7 9800x3d"])
        assert pccg_match("AMD Ryzen 7 9800X3D Processor", wp)

    def test_5800x_does_not_match_5800x3d(self):
        """Critical: 5800X search term should NOT match 5800X3D product."""
        wp = _make_watchlist_cpu("Ryzen 7 5800X", ["ryzen 7 5800x"])
        assert not pccg_match("AMD Ryzen 7 5800X3D Processor", wp)

    def test_9900_does_not_match_9900x(self):
        """9900 search term should NOT match 9900X product."""
        wp = _make_watchlist_cpu("Ryzen 9 9900", ["ryzen 9 9900"])
        assert not pccg_match("AMD Ryzen 9 9900X Processor", wp)

    def test_9900x_matches_9900x(self):
        wp = _make_watchlist_cpu("Ryzen 9 9900X", ["ryzen 9 9900x"])
        assert pccg_match("AMD Ryzen 9 9900X Processor", wp)

    def test_9900x3d_matches_9900x3d(self):
        wp = _make_watchlist_cpu("Ryzen 9 9950X3D", ["ryzen 9 9950x3d"])
        assert pccg_match("AMD Ryzen 9 9950X3D Processor", wp)

    def test_intel_14700k_matches(self):
        wp = _make_watchlist_cpu("Core i7-14700K", ["core i7 14700k"])
        assert pccg_match("Intel Core i7 14700K Processor", wp)

    def test_intel_14700k_does_not_match_14700kf(self):
        """14700K should not match 14700KF."""
        wp = _make_watchlist_cpu("Core i7-14700K", ["core i7 14700k"])
        assert not pccg_match("Intel Core i7 14700KF Processor", wp)

    def test_ultra_7_265k_matches(self):
        wp = _make_watchlist_cpu("Core Ultra 7 265K", ["core ultra 7 265k"])
        assert pccg_match("Intel Core Ultra 7 265K Processor", wp)

    def test_no_match_for_completely_different_product(self):
        wp = _make_watchlist_cpu("Ryzen 7 9800X3D", ["ryzen 7 9800x3d"])
        assert not pccg_match("Intel Core i9-14900K Processor", wp)

    def test_empty_search_terms_no_match(self):
        wp = _make_watchlist_cpu("Ryzen 7 9800X3D", [])
        assert not pccg_match("AMD Ryzen 7 9800X3D Processor", wp)


# ── GPU matching tests ──────────────────────────────────────────────

class TestPCCGGPUMatching:
    """Test GPU product matching for PCCG scraper."""

    def test_rtx_5070_ti_matches(self):
        wp = _make_watchlist_gpu("GeForce RTX 5070 Ti", ["rtx 5070 ti"], vram_gb=16)
        assert pccg_match("Gigabyte GeForce RTX 5070 Ti Windforce OC GDDR7 16GB", wp)

    def test_rtx_4060_ti_does_not_match_rtx_4060(self):
        """4060 Ti should not match plain 4060."""
        wp = _make_watchlist_gpu("GeForce RTX 4060 Ti", ["rtx 4060 ti"], vram_gb=8)
        assert not pccg_match("ASUS Dual GeForce RTX 4060 8GB", wp)

    def test_rx_7800_xt_matches(self):
        wp = _make_watchlist_gpu("Radeon RX 7800 XT", ["rx 7800 xt"], vram_gb=16)
        assert pccg_match("Sapphire Radeon RX 7800 XT Nitro+", wp)

    def test_vram_guard_prevents_false_match(self):
        """RTX 5070 (12GB) should not match RTX 5070 Ti (16GB)."""
        wp = _make_watchlist_gpu("GeForce RTX 5070", ["rtx 5070"], vram_gb=12)
        assert not pccg_match("Gigabyte GeForce RTX 5070 Ti Windforce OC GDDR7 16GB", wp)

    def test_vram_guard_allows_correct_match(self):
        wp = _make_watchlist_gpu("GeForce RTX 5070", ["rtx 5070"], vram_gb=12)
        assert pccg_match("Gigabyte GeForce RTX 5070 Windforce OC GDDR7 12GB", wp)

    def test_rx_9060_xt_matches(self):
        wp = _make_watchlist_gpu("Radeon RX 9060 XT", ["rx 9060 xt"], vram_gb=16)
        assert pccg_match("Gigabyte Radeon RX 9060 XT Gaming OC GDDR6 16GB", wp)

    def test_no_match_for_different_brand(self):
        wp = _make_watchlist_gpu("GeForce RTX 5070", ["rtx 5070"], vram_gb=12)
        assert not pccg_match("AMD Radeon RX 7800 XT", wp)


# ── Bundle deals (CPU + motherboard combos) ─────────────────────────

class TestBundleDetection:
    """Component bundles must never match a single-component watchlist product."""

    def test_pccg_bundle_name_detected(self):
        assert pccg_is_bundle("Gigabyte Z890 Ultra 5 Power Bundle")

    def test_pccg_normal_cpu_not_bundle(self):
        assert not pccg_is_bundle("AMD Ryzen 7 9800X3D Processor")

    def test_pccg_bundle_url_detected(self):
        assert pccg_is_bundle("ASUS Z890 Core Ultra 9", "https://www.pccasegear.com/some-bundle-deal")
        assert pccg_is_bundle("ASUS Z890 Core Ultra 9", "https://www.scorptec.com.au/bundle/cpu/1-bdl-1")

    def test_scorptec_bundle_name_detected(self):
        assert scorptec_is_bundle("gigabyte z890 ultra 5 power bundle")

    def test_scorptec_bundle_url_detected(self):
        assert scorptec_is_bundle("some combo", "", "https://www.scorptec.com.au/bundle/cpu/intel-socket-1851/9327-bdl-9327")

    def test_scorptec_normal_cpu_not_bundle(self):
        assert not scorptec_is_bundle("intel core ultra 5 245k desktop processor")

    def test_pccg_cpu_bundle_does_not_match_watchlist(self):
        """A CPU+motherboard bundle must NOT match the CPU-only watchlist product."""
        wp = _make_watchlist_cpu("Core Ultra 5 245", ["core ultra 5 245"])
        assert not pccg_match("Gigabyte Z890 Ultra 5 Power Bundle", wp)

    def test_scorptec_cpu_bundle_does_not_match_watchlist(self):
        wp = _make_watchlist_cpu("Core Ultra 5 245", ["core ultra 5 245"])
        assert not scorptec_match("gigabyte z890 ultra 5 power bundle", "Intel Core Ultra 5 245 CPU + Z890 motherboard combo", wp)

    def test_scorptec_normal_cpu_still_matches(self):
        wp = _make_watchlist_cpu("Core Ultra 5 245", ["core ultra 5 245"])
        assert scorptec_match("intel core ultra 5 245k desktop processor", "Intel Core Ultra 5 245 desktop CPU", wp)


# ── Price parsing tests ─────────────────────────────────────────────

class TestParsePrice:
    """Test price text parsing."""

    def test_plain_float(self):
        assert pccg_parse_price(899.0) == 899.0

    def test_integer_price(self):
        assert pccg_parse_price(549) == 549.0

    def test_none_returns_none(self):
        assert pccg_parse_price(None) is None

    def test_string_with_comma(self):
        assert pccg_parse_price("1,299.00") == 1299.0

    def test_string_plain(self):
        assert pccg_parse_price("429") == 429.0

    def test_empty_string_returns_none(self):
        assert pccg_parse_price("") is None

    def test_non_numeric_returns_none(self):
        assert pccg_parse_price("Out of stock") is None
