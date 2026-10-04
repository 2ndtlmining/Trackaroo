"""
Tests for seed.py — database seeding from watchlist.csv.
"""
import sqlite3
from pathlib import Path

import pytest

# Import the seed module functions
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seed import init_db, load_watchlist, parse_spec, seed_products


class TestParseSpec:
    """Test spec column parsing."""

    def test_cpu_cores(self):
        result = parse_spec("16c", "cpu")
        assert result["cores"] == 16
        assert result["vram_gb"] is None

    def test_cpu_single_digit(self):
        result = parse_spec("6c", "cpu")
        assert result["cores"] == 6

    def test_gpu_vram(self):
        result = parse_spec("32GB", "gpu")
        assert result["vram_gb"] == 32
        assert result["cores"] is None

    def test_gpu_vram_small(self):
        result = parse_spec("8GB", "gpu")
        assert result["vram_gb"] == 8

    def test_cpu_returns_none_vram(self):
        result = parse_spec("24c", "cpu")
        assert result["vram_gb"] is None

    def test_gpu_returns_none_cores(self):
        result = parse_spec("16GB", "gpu")
        assert result["cores"] is None


# Project root for resolving paths when tests run from unit_testing/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "db" / "watchlist.csv"


class TestLoadWatchlist:
    """Test watchlist CSV loading."""

    # #20: invariants, not exact counts, so adding or retiring a product needs
    # no test edit while a truncated or half-deleted file still fails.
    def test_every_data_line_loads(self):
        """Rows loaded == data lines in the file: nothing silently skipped."""
        lines = [
            line
            for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert len(load_watchlist(WATCHLIST_PATH)) == len(lines) - 1  # minus the header

    def test_truncation_floor(self):
        products = load_watchlist(WATCHLIST_PATH)
        for category in ("cpu", "gpu"):
            assert len([p for p in products if p["category"] == category]) >= 35, category

    def test_every_category_covers_every_tier(self):
        products = load_watchlist(WATCHLIST_PATH)
        for category in ("cpu", "gpu"):
            tiers = {p["generation_tier"] for p in products if p["category"] == category and p["tracked"]}
            assert tiers == {"current", "current-1", "current-2"}, category

    def test_no_duplicate_products(self):
        products = load_watchlist(WATCHLIST_PATH)
        keys = [(p["category"], p["brand"], p["model"]) for p in products]
        assert len(keys) == len(set(keys))

    def test_all_have_brand(self):
        products = load_watchlist(WATCHLIST_PATH)
        for p in products:
            assert p["brand"] in ("AMD", "Intel", "NVIDIA")

    def test_all_have_valid_tier(self):
        products = load_watchlist(WATCHLIST_PATH)
        for p in products:
            assert p["generation_tier"] in ("current", "current-1", "current-2")

    def test_all_cpus_have_cores(self):
        products = load_watchlist(WATCHLIST_PATH)
        for p in products:
            if p["category"] == "cpu":
                assert p["cores"] is not None
                assert p["vram_gb"] is None

    def test_all_gpus_have_vram(self):
        products = load_watchlist(WATCHLIST_PATH)
        for p in products:
            if p["category"] == "gpu":
                assert p["vram_gb"] is not None
                assert p["cores"] is None

    def test_tracked_is_true(self):
        products = load_watchlist(WATCHLIST_PATH)
        for p in products:
            assert p["tracked"] == 1


class TestSeedProducts:
    """Test product seeding into the database."""

    def test_inserts_products(self, db, sample_cpu, sample_gpu):
        stats = seed_products(db, [sample_cpu, sample_gpu])
        assert stats["inserted"] == 2
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

        # Verify in DB
        total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert total == 2

    def test_skips_existing_products(self, db, sample_cpu):
        seed_products(db, [sample_cpu])
        stats = seed_products(db, [sample_cpu])
        assert stats["skipped"] == 1
        assert stats["inserted"] == 0

        # Still only 1 product
        total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert total == 1

    def test_dry_run_no_insert(self, db, sample_cpu):
        stats = seed_products(db, [sample_cpu], dry_run=True)
        assert stats["inserted"] == 0

        # DB should be empty
        total = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert total == 0

    def test_preserves_generation_tier(self, db, sample_cpu):
        seed_products(db, [sample_cpu])
        row = db.execute(
            "SELECT generation_tier FROM products WHERE model = ?",
            (sample_cpu["model"],),
        ).fetchone()
        assert row[0] == "current"

    def test_preserves_tracked_flag(self, db, sample_cpu):
        seed_products(db, [sample_cpu])
        row = db.execute(
            "SELECT tracked FROM products WHERE model = ?",
            (sample_cpu["model"],),
        ).fetchone()
        assert row[0] == 1

    def test_preserves_cores(self, db, sample_cpu):
        seed_products(db, [sample_cpu])
        row = db.execute(
            "SELECT cores FROM products WHERE model = ?",
            (sample_cpu["model"],),
        ).fetchone()
        assert row[0] == 8

    def test_preserves_vram(self, db, sample_gpu):
        seed_products(db, [sample_gpu])
        row = db.execute(
            "SELECT vram_gb FROM products WHERE model = ?",
            (sample_gpu["model"],),
        ).fetchone()
        assert row[0] == 16

    def test_cpu_has_null_vram(self, db, sample_cpu):
        seed_products(db, [sample_cpu])
        row = db.execute(
            "SELECT vram_gb FROM products WHERE model = ?",
            (sample_cpu["model"],),
        ).fetchone()
        assert row[0] is None

    def test_gpu_has_null_cores(self, db, sample_gpu):
        seed_products(db, [sample_gpu])
        row = db.execute(
            "SELECT cores FROM products WHERE model = ?",
            (sample_gpu["model"],),
        ).fetchone()
        assert row[0] is None


class TestInitDb:
    """Test database initialization."""

    def test_creates_tables(self, db):
        # Check all three tables exist
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "products" in table_names
        assert "retailer_listings" in table_names
        assert "price_snapshots" in table_names

    def test_creates_trigger(self, db):
        triggers = db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        trigger_names = [t[0] for t in triggers]
        assert "trg_update_listing_last_snapshot" in trigger_names

    def test_creates_indexes(self, db):
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indexes]
        assert "idx_products_category_tracked" in index_names
        assert "idx_snapshots_listing_date" in index_names


class TestGenerationTierSync:
    """The watchlist calls itself the source of truth, so a corrected
    gen_tier must reach products that already exist.

    Found via Intel Arc: A380/A750/A770 (Alchemist) and B570/B580
    (Battlemage) were both tagged `current`. Retagging the watchlist changed
    nothing, because seeding skipped every existing row outright — so the
    dashboard would have grouped two generations under one heading forever.
    """

    def test_updates_generation_tier_when_the_watchlist_changes(self, db, sample_gpu):
        seed_products(db, [sample_gpu])
        retagged = {**sample_gpu, "generation_tier": "current-1"}

        stats = seed_products(db, [retagged])

        assert stats["updated"] == 1
        assert stats["inserted"] == 0
        tier = db.execute(
            "SELECT generation_tier FROM products WHERE model = ?", (sample_gpu["model"],)
        ).fetchone()[0]
        assert tier == "current-1"

    def test_leaves_an_unchanged_product_alone(self, db, sample_gpu):
        seed_products(db, [sample_gpu])
        stats = seed_products(db, [sample_gpu])
        assert stats["updated"] == 0
        assert stats["skipped"] == 1

    def test_dry_run_reports_but_does_not_write(self, db, sample_gpu):
        seed_products(db, [sample_gpu])
        retagged = {**sample_gpu, "generation_tier": "current-2"}

        stats = seed_products(db, [retagged], dry_run=True)

        assert stats["updated"] == 1
        tier = db.execute(
            "SELECT generation_tier FROM products WHERE model = ?", (sample_gpu["model"],)
        ).fetchone()[0]
        assert tier == sample_gpu["generation_tier"]


class TestSpecSync:
    """The watchlist is the source of truth for vram_gb/cores too, not just
    generation_tier. Arc B570 sat at 12GB in the DB for a month after the CSV
    was corrected to 10GB, because seed_products only ever synced the tier
    (#2). Identity columns (category, brand, model) are never touched.
    """

    def test_existing_product_spec_is_synced_from_csv(self, tmp_path):
        conn = init_db(tmp_path / "t.db")
        seed_products(conn, [{
            "category": "gpu", "brand": "Intel", "model": "Arc B570",
            "vram_gb": 12, "cores": None, "generation_tier": "current", "tracked": 1,
        }])
        stats = seed_products(conn, [{
            "category": "gpu", "brand": "Intel", "model": "Arc B570",
            "vram_gb": 10, "cores": None, "generation_tier": "current", "tracked": 1,
        }])

        assert stats["updated"] == 1
        row = conn.execute(
            "SELECT vram_gb FROM products WHERE model = 'Arc B570'"
        ).fetchone()
        assert row[0] == 10
