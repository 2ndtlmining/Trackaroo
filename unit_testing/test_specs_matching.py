"""
Tests for spec_matching — name normalization and source-record matching.

Ensures that:
- normalize_name / strip_brand behave as documented
- GPU exact and VRAM-variant prefix matching work
- The VRAM guard prevents false matches between memory variants
- CPU exact and brand-stripped matching work
- Similar-but-different models do NOT match (guards against false positives)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spec_matching import normalize_name, strip_brand, match_gpu, match_cpu


# ── Normalization ─────────────────────────────────────────────────────

class TestNormalizeName:
    def test_lowercase_and_punctuation(self):
        assert normalize_name("GeForce RTX 4070 Ti SUPER") == "geforce rtx 4070 ti super"

    def test_punctuation_replaced_with_space(self):
        assert normalize_name("Core i5-13400") == "core i5 13400"

    def test_whitespace_collapsed(self):
        assert normalize_name("  Ryzen   7   9800X3D  ") == "ryzen 7 9800x3d"

    def test_symbols_dropped(self):
        # amd.com serves a ™/® symbol in names; it must not affect matching
        assert normalize_name("AMD Ryzen™ 9 9950X3D") == "amd ryzen 9 9950x3d"


class TestStripBrand:
    def test_leading_amd_stripped(self):
        assert strip_brand("amd ryzen 9 9950x3d") == "ryzen 9 9950x3d"

    def test_leading_intel_stripped(self):
        assert strip_brand("intel core i5 13400") == "core i5 13400"

    def test_no_brand_unchanged(self):
        assert strip_brand("ryzen 9 9950x3d") == "ryzen 9 9950x3d"

    def test_leading_nvidia_stripped(self):
        assert strip_brand("nvidia geforce rtx 5070") == "geforce rtx 5070"

    def test_brand_mid_name_unchanged(self):
        # brand token is only stripped when LEADING
        assert strip_brand("geforce nvidia rtx 5070") == "geforce nvidia rtx 5070"


# ── GPU matching ──────────────────────────────────────────────────────

class TestMatchGpu:
    def test_exact_match(self):
        records = [{"name": "GeForce RTX 4070 SUPER", "memorySize": 12.0}]
        assert match_gpu("GeForce RTX 4070 Super", 12, records) is not None

    def test_exact_match_case_insensitive(self):
        records = [{"name": "geforce rtx 4070 super", "memorySize": 12.0}]
        assert match_gpu("GeForce RTX 4070 Super", 12, records) is not None

    def test_vram_variant_prefix_match(self):
        records = [
            {"name": "Radeon RX 9070 16 GB", "memorySize": 16.0},
            {"name": "Radeon RX 9070 8 GB", "memorySize": 8.0},
        ]
        rec = match_gpu("Radeon RX 9070", 16, records)
        assert rec is not None
        assert rec["name"] == "Radeon RX 9070 16 GB"

    def test_vram_guard_drops_wrong_variant(self):
        records = [
            {"name": "Radeon RX 9070 16 GB", "memorySize": 16.0},
            {"name": "Radeon RX 9070 8 GB", "memorySize": 8.0},
        ]
        # Watchlist says 12GB — neither variant fits, so no confident match
        assert match_gpu("Radeon RX 9070", 12, records) is None

    def test_ambiguous_without_vram_no_match(self):
        records = [
            {"name": "Radeon RX 9070 16 GB", "memorySize": 16.0},
            {"name": "Radeon RX 9070 8 GB", "memorySize": 8.0},
        ]
        assert match_gpu("Radeon RX 9070", None, records) is None

    def test_super_suffix_is_not_vram_variant(self):
        """'SUPER' is a model suffix, not a '<digits> gb' VRAM variant —
        RTX 4070 must not prefix-match RTX 4070 SUPER."""
        records = [
            {"name": "GeForce RTX 4070 SUPER", "memorySize": 12.0},
        ]
        assert match_gpu("GeForce RTX 4070", 12, records) is None

    def test_no_match_for_different_model(self):
        records = [{"name": "Arc B580", "memorySize": 12.0}]
        assert match_gpu("Arc B570", 12, records) is None

    def test_no_match_at_all(self):
        records = [{"name": "GeForce RTX 3050", "memorySize": 8.0}]
        assert match_gpu("Radeon RX 7900 XTX", 24, records) is None


class TestMatchGpuNormalizedRecords:
    """sync_specs.py passes parse_gpu_records() output, where VRAM lives
    under 'vram_gb' (not 'memorySize'). VRAM-variant prefix matching must
    work on that shape — regression for the 2026-08-16 live-sync bug where
    six VRAM-variant GPUs (RTX 3050/3060/4060 Ti/5060 Ti, RX 9060 XT)
    came back unmatched because the guard filtered on the wrong key."""

    def test_vram_variant_prefix_match_normalized(self):
        records = [
            {"name": "GeForce RTX 5060 Ti 16 GB", "vram_gb": 16.0},
            {"name": "GeForce RTX 5060 Ti 8 GB", "vram_gb": 8.0},
        ]
        rec = match_gpu("GeForce RTX 5060 Ti", 16, records)
        assert rec is not None
        assert rec["name"] == "GeForce RTX 5060 Ti 16 GB"

    def test_vram_guard_drops_wrong_variant_normalized(self):
        records = [
            {"name": "Radeon RX 9060 XT 16 GB", "vram_gb": 16.0},
            {"name": "Radeon RX 9060 XT 8 GB", "vram_gb": 8.0},
        ]
        # Watchlist says 12GB — neither variant fits, so no confident match
        assert match_gpu("Radeon RX 9060 XT", 12, records) is None

    def test_ambiguous_without_vram_no_match_normalized(self):
        records = [
            {"name": "GeForce RTX 3050 8 GB", "vram_gb": 8.0},
            {"name": "GeForce RTX 3050 6 GB", "vram_gb": 6.0},
        ]
        assert match_gpu("GeForce RTX 3050", None, records) is None


# ── CPU matching ──────────────────────────────────────────────────────

class TestMatchCpu:
    def test_exact_match_intel(self):
        records = [{"name": "Core i5-13400"}]
        assert match_cpu("Core i5-13400", records) is not None

    def test_brand_stripped_match_amd(self):
        """Watchlist 'Ryzen 9 9950X3D' vs amd.com 'AMD Ryzen™ 9 9950X3D'."""
        records = [{"name": "AMD Ryzen™ 9 9950X3D"}]
        assert match_cpu("Ryzen 9 9950X3D", records) is not None

    def test_5800x_does_not_match_5800x3d(self):
        records = [{"name": "AMD Ryzen 7 5800X3D"}]
        assert match_cpu("Ryzen 7 5800X", records) is None

    def test_9900_does_not_match_9900x(self):
        records = [{"name": "AMD Ryzen 9 9900X"}]
        assert match_cpu("Ryzen 9 9900", records) is None

    def test_13400_does_not_match_13400f(self):
        """KF/F suffixes are different SKUs — must not match."""
        records = [{"name": "Core i5-13400F"}]
        assert match_cpu("Core i5-13400", records) is None

    def test_no_match_for_completely_different_product(self):
        records = [{"name": "Core i9-14900K"}]
        assert match_cpu("Ryzen 7 9800X3D", records) is None

    def test_no_match_at_all(self):
        records = [{"name": "Core i5-13400"}]
        assert match_cpu("Ryzen 9 9950X3D", records) is None
