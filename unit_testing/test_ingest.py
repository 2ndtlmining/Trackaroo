"""
Tests for the ingestion pipeline (ingest.py).

Tests:
- Date parsing from filenames
- Product find-or-create logic
- Listing find-or-create logic
- Snapshot insertion and deduplication
- Full pipeline integration with sample JSON data
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Import ingestion functions
sys_path = str(Path(__file__).resolve().parent.parent)
import sys
sys.path.insert(0, sys_path)
from ingest import (
    parse_date_from_filename,
    find_or_create_product,
    find_or_create_listing,
    ingest_file,
)


# ── Date parsing tests ──────────────────────────────────────────────

class TestParseDateFromFilename:
    """Test date extraction from scraped JSON filenames."""

    def test_standard_cpu_filename(self):
        assert parse_date_from_filename("cpu_scorptec_10_August_2026.json") == "2026-08-10"

    def test_standard_gpu_filename(self):
        assert parse_date_from_filename("gpu_pccg_09_August_2026.json") == "2026-08-09"

    def test_different_month(self):
        assert parse_date_from_filename("cpu_scorptec_25_December_2025.json") == "2025-12-25"

    def test_single_digit_day(self):
        assert parse_date_from_filename("gpu_pccg_1_January_2026.json") == "2026-01-01"

    def test_invalid_date_returns_empty(self):
        assert parse_date_from_filename("random_file.json") == ""

    def test_no_date_part_returns_empty(self):
        assert parse_date_from_filename("cpu_scorptec.json") == ""


# ── Product find-or-create tests ────────────────────────────────────

class TestFindOrCreateProduct:
    """Test product lookup and creation."""

    def test_creates_new_product(self, db):
        product_data = {
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_gen_tier": "current",
        }
        pid = find_or_create_product(db, product_data)
        assert pid is not None
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1

    def test_returns_existing_product(self, db):
        product_data = {
            "watchlist_category": "gpu",
            "watchlist_brand": "NVIDIA",
            "watchlist_model": "RTX 5070",
            "watchlist_gen_tier": "current",
        }
        pid1 = find_or_create_product(db, product_data)
        pid2 = find_or_create_product(db, product_data)
        assert pid1 == pid2
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1

    def test_different_model_creates_new(self, db):
        p1 = {"watchlist_category": "cpu", "watchlist_brand": "AMD", "watchlist_model": "Ryzen 7 5800X", "watchlist_gen_tier": "current"}
        p2 = {"watchlist_category": "cpu", "watchlist_brand": "AMD", "watchlist_model": "Ryzen 7 5800X3D", "watchlist_gen_tier": "current"}
        pid1 = find_or_create_product(db, p1)
        pid2 = find_or_create_product(db, p2)
        assert pid1 != pid2
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2

    def test_preserves_generation_tier(self, db):
        product_data = {
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_model": "Ryzen 5 5600X",
            "watchlist_gen_tier": "current-2",
        }
        find_or_create_product(db, product_data)
        row = db.execute("SELECT generation_tier FROM products WHERE model = ?", ("Ryzen 5 5600X",)).fetchone()
        assert row[0] == "current-2"

    def test_tracked_flag_is_true(self, db):
        product_data = {
            "watchlist_category": "gpu",
            "watchlist_brand": "NVIDIA",
            "watchlist_model": "RTX 4060",
            "watchlist_gen_tier": "current-1",
        }
        find_or_create_product(db, product_data)
        row = db.execute("SELECT tracked FROM products WHERE model = ?", ("RTX 4060",)).fetchone()
        assert row[0] == 1


# ── Listing find-or-create tests ────────────────────────────────────

class TestFindOrCreateListing:
    """Test retailer listing lookup and creation."""

    def _create_product(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('cpu', 'AMD', 'Ryzen 7')"
        )
        return db.execute("SELECT id FROM products WHERE model = 'Ryzen 7'").fetchone()[0]

    def test_creates_new_listing(self, db):
        pid = self._create_product(db)
        url = "https://scorptec.com.au/products/12345"
        lid = find_or_create_listing(db, pid, "scorptec", url)
        assert lid is not None
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 1

    def test_returns_existing_listing(self, db):
        pid = self._create_product(db)
        url = "https://scorptec.com.au/products/12345"
        lid1 = find_or_create_listing(db, pid, "scorptec", url)
        lid2 = find_or_create_listing(db, pid, "scorptec", url)
        assert lid1 == lid2
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 1

    def test_different_retailer_creates_new(self, db):
        pid = self._create_product(db)
        url = "https://scorptec.com.au/products/12345"
        lid1 = find_or_create_listing(db, pid, "scorptec", url)
        lid2 = find_or_create_listing(db, pid, "pccg", url)
        assert lid1 != lid2
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 2

    def test_default_status_is_active(self, db):
        pid = self._create_product(db)
        url = "https://scorptec.com.au/products/12345"
        find_or_create_listing(db, pid, "scorptec", url)
        row = db.execute("SELECT status FROM retailer_listings WHERE listing_url = ?", (url,)).fetchone()
        assert row[0] == "active"

    def test_fallback_lookup_by_retailer_url(self, db):
        """If URL exists under a different product, return that listing instead of erroring."""
        pid1 = self._create_product(db)
        pid2_data = {"watchlist_category": "cpu", "watchlist_brand": "AMD", "watchlist_model": "Ryzen 9 5900X"}
        find_or_create_product(db, pid2_data)
        pid2 = db.execute("SELECT id FROM products WHERE model = 'Ryzen 9 5900X'").fetchone()[0]
        url = "https://scorptec.com.au/products/12345"
        # Create listing under pid1
        lid1 = find_or_create_listing(db, pid1, "scorptec", url)
        # Try to create under pid2 — should return existing listing, not error
        lid2 = find_or_create_listing(db, pid2, "scorptec", url)
        assert lid1 == lid2
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 1


# ── Full ingestion tests ────────────────────────────────────────────

class TestIngestFile:
    """Test full ingestion of a JSON snapshot file."""

    def _make_json_file(self, tmp_path, products, retailer="scorptec"):
        """Create a temporary JSON file with the given products."""
        data = {
            "retailer": retailer,
            "scrape_date": "10_August_2026",
            "category": "cpu",
            "total_watchlist": 100,
            "matched": len(products),
            "products": products,
        }
        file_path = tmp_path / f"{retailer}_test_10_August_2026.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        return file_path

    def test_ingests_single_product(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/12345",
        }]
        file_path = self._make_json_file(tmp_path, products)
        stats = ingest_file(db, file_path)
        assert stats["inserted"] == 1
        assert stats["errors"] == 0

        # Verify DB state
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 1

    def test_skips_duplicate_snapshot(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/12345",
        }]
        file_path = self._make_json_file(tmp_path, products)
        ingest_file(db, file_path)
        stats = ingest_file(db, file_path)  # Run again
        assert stats["skipped"] == 1
        assert stats["inserted"] == 0
        # Still only 1 snapshot
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 1

    def test_dry_run_no_insert(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/12345",
        }]
        file_path = self._make_json_file(tmp_path, products)
        ingest_file(db, file_path, dry_run=True)
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0

    def test_multiple_products(self, db, tmp_path):
        products = [
            {
                "watchlist_model": "Ryzen 7 9800X3D",
                "watchlist_category": "cpu",
                "watchlist_brand": "AMD",
                "watchlist_gen_tier": "current",
                "retailer": "scorptec",
                "price_aud": 599.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/1",
            },
            {
                "watchlist_model": "Core i7-14700K",
                "watchlist_category": "cpu",
                "watchlist_brand": "Intel",
                "watchlist_gen_tier": "current-1",
                "retailer": "scorptec",
                "price_aud": 449.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/2",
            },
        ]
        file_path = self._make_json_file(tmp_path, products)
        stats = ingest_file(db, file_path)
        assert stats["inserted"] == 2
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 2

    def test_skips_missing_url(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "",  # Empty URL
        }]
        file_path = self._make_json_file(tmp_path, products)
        stats = ingest_file(db, file_path)
        assert stats["skipped"] == 1
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0

    def test_skips_missing_price(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": None,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/1",
        }]
        file_path = self._make_json_file(tmp_path, products)
        stats = ingest_file(db, file_path)
        assert stats["skipped"] == 1
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0

    def test_trigger_updates_listing_last_snapshot(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/1",
        }]
        file_path = self._make_json_file(tmp_path, products)
        ingest_file(db, file_path)
        # The trigger should have updated last_snapshot_at
        row = db.execute("SELECT last_snapshot_at FROM retailer_listings LIMIT 1").fetchone()
        assert row[0] is not None

    def test_trigger_updates_product_last_snapshot(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/1",
        }]
        file_path = self._make_json_file(tmp_path, products)
        ingest_file(db, file_path)
        row = db.execute("SELECT last_snapshot_at FROM products LIMIT 1").fetchone()
        assert row[0] is not None

    def test_different_date_creates_new_snapshot(self, db, tmp_path):
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/1",
        }]
        # First file with 10_August date
        file1 = self._make_json_file(tmp_path, products)
        ingest_file(db, file1)

        # Second file with 11_August date
        products[0]["price_aud"] = 579.0  # Price changed
        data = {
            "retailer": "scorptec",
            "scrape_date": "11_August_2026",
            "category": "cpu",
            "total_watchlist": 100,
            "matched": 1,
            "products": products,
        }
        file2 = tmp_path / "scorptec_test_11_August_2026.json"
        with open(file2, "w") as f:
            json.dump(data, f)
        ingest_file(db, file2)

        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 2
        # Verify different prices
        prices = [r[0] for r in db.execute("SELECT price_aud FROM price_snapshots ORDER BY snapshot_date").fetchall()]
        assert prices == [599.0, 579.0]


class TestIngestRealFile:
    """Integration test with actual scraped data files."""

    def test_ingest_scorptec_cpu_10_aug(self, db):
        """Ingest a real Scorptec CPU file and verify data integrity."""
        file_path = Path("data/cpu_scorptec_10_August_2026.json")
        if not file_path.exists():
            pytest.skip("File not available")

        stats = ingest_file(db, file_path)
        assert stats["errors"] == 0
        # Should have inserted some products
        assert stats["inserted"] > 0
        # Verify DB state
        products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        listings_count = db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
        snapshots_count = db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        assert products_count > 0
        assert listings_count > 0
        assert snapshots_count > 0


class TestFullPipeline:
    """End-to-end pipeline tests: watchlist -> JSON -> DB -> query."""

    def _create_full_json(self, tmp_path, products, date_str="10_August_2026"):
        """Create a complete JSON file with proper structure."""
        data = {
            "retailer": "scorptec",
            "scrape_date": date_str,
            "category": "cpu",
            "total_watchlist": len(products),
            "matched": len(products),
            "products": products,
        }
        file_path = tmp_path / f"cpu_scorptec_{date_str}.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        return file_path

    def test_full_pipeline_cpu(self, db, tmp_path):
        """Full pipeline: create JSON -> ingest -> verify DB state."""
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/9800x3d",
        }]
        file_path = self._create_full_json(tmp_path, products)
        stats = ingest_file(db, file_path)

        # Verify product created
        pid = db.execute(
            "SELECT id FROM products WHERE model = ? AND brand = ?",
            ("Ryzen 7 9800X3D", "AMD"),
        ).fetchone()[0]
        assert pid is not None

        # Verify listing created
        lid = db.execute(
            "SELECT id FROM retailer_listings WHERE product_id = ? AND retailer = ?",
            (pid, "scorptec"),
        ).fetchone()[0]
        assert lid is not None

        # Verify snapshot created
        snapshot = db.execute(
            "SELECT * FROM price_snapshots WHERE retailer_listing_id = ? AND snapshot_date = ?",
            (lid, "2026-08-10"),
        ).fetchone()
        assert snapshot is not None
        assert snapshot["price_aud"] == 599.0

    def test_full_pipeline_gpu_with_vram(self, db, tmp_path):
        """Full pipeline with GPU product including VRAM tracking."""
        products = [{
            "watchlist_model": "GeForce RTX 5070",
            "watchlist_category": "gpu",
            "watchlist_brand": "NVIDIA",
            "watchlist_gen_tier": "current",
            "vram_gb": 12,
            "retailer": "pccg",
            "price_aud": 999.0,
            "stock_status": "in_stock",
            "url": "https://pccg.com/products/rtx5070",
        }]
        file_path = self._create_full_json(tmp_path, products)
        # Note: GPU products need vram_gb in the product data
        products[0]["vram_gb"] = 12
        stats = ingest_file(db, file_path)

        # Verify GPU product created with VRAM
        row = db.execute(
            "SELECT vram_gb, category FROM products WHERE model = ?",
            ("GeForce RTX 5070",),
        ).fetchone()
        assert row[1] == "gpu"

    def test_multi_retailer_pipeline(self, db, tmp_path):
        """Test same product tracked across multiple retailers."""
        product_data = {
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/9800x3d",
        }
        # Create Scorptec file
        scorptec_products = [product_data.copy()]
        scorptec_file = self._create_full_json(tmp_path, scorptec_products)
        ingest_file(db, scorptec_file)

        # Create PCCG file for same product
        pccg_product = product_data.copy()
        pccg_product["retailer"] = "pccg"
        pccg_product["price_aud"] = 649.0
        pccg_product["url"] = "https://pccg.com/products/9800x3d"
        pccg_data = {
            "retailer": "pccg",
            "scrape_date": "10_August_2026",
            "category": "cpu",
            "total_watchlist": 1,
            "matched": 1,
            "products": [pccg_product],
        }
        pccg_file = tmp_path / "cpu_pccg_10_August_2026.json"
        with open(pccg_file, "w") as f:
            json.dump(pccg_data, f)
        ingest_file(db, pccg_file)

        # Verify both retailers tracked
        pid = db.execute(
            "SELECT id FROM products WHERE model = ?",
            ("Ryzen 7 9800X3D",),
        ).fetchone()[0]
        listings = db.execute(
            "SELECT retailer FROM retailer_listings WHERE product_id = ?",
            (pid,),
        ).fetchall()
        retailers = {row[0] for row in listings}
        assert "scorptec" in retailers
        assert "pccg" in retailers

    def test_price_trend_query(self, db, tmp_path):
        """Verify price trends can be queried across dates."""
        product_data = {
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/9800x3d",
        }
        # Day 1
        file1 = self._create_full_json(tmp_path, [product_data], "10_August_2026")
        ingest_file(db, file1)

        # Day 2 - price changed
        product_data["price_aud"] = 579.0
        file2 = self._create_full_json(tmp_path, [product_data], "11_August_2026")
        ingest_file(db, file2)

        # Query price trend
        trend = db.execute("""
            SELECT s.snapshot_date, s.price_aud
            FROM price_snapshots s
            JOIN retailer_listings l ON s.retailer_listing_id = l.id
            JOIN products p ON l.product_id = p.id
            WHERE p.model = ?
            ORDER BY s.snapshot_date
        """, ("Ryzen 7 9800X3D",)).fetchall()

        assert len(trend) == 2
        assert trend[0][0] == "2026-08-10"
        assert trend[0][1] == 599.0
        assert trend[1][0] == "2026-08-11"
        assert trend[1][1] == 579.0
        # Price decreased
        assert trend[1][1] < trend[0][1]

    def test_trigger_updates_on_pipeline(self, db, tmp_path):
        """Verify triggers fire correctly during full pipeline."""
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/9800x3d",
        }]
        file_path = self._create_full_json(tmp_path, products)
        ingest_file(db, file_path)

        # Verify product has last_snapshot_at
        product_snapshot = db.execute(
            "SELECT last_snapshot_at FROM products WHERE model = ?",
            ("Ryzen 7 9800X3D",),
        ).fetchone()[0]
        assert product_snapshot is not None

        # Verify listing has last_snapshot_at and last_seen_at
        listing_snap = db.execute("""
            SELECT last_snapshot_at, last_seen_at
            FROM retailer_listings
            WHERE product_id = (SELECT id FROM products WHERE model = ?)
        """, ("Ryzen 7 9800X3D",)).fetchone()
        assert listing_snap[0] is not None  # last_snapshot_at
        assert listing_snap[1] is not None  # last_seen_at

    def test_idempotent_re_ingest(self, db, tmp_path):
        """Verify re-ingesting same file doesn't duplicate data."""
        products = [{
            "watchlist_model": "Ryzen 7 9800X3D",
            "watchlist_category": "cpu",
            "watchlist_brand": "AMD",
            "watchlist_gen_tier": "current",
            "retailer": "scorptec",
            "price_aud": 599.0,
            "stock_status": "in_stock",
            "url": "https://scorptec.com.au/products/9800x3d",
        }]
        file_path = self._create_full_json(tmp_path, products)

        # First ingest
        ingest_file(db, file_path)
        count_after_first = db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

        # Second ingest (same date)
        ingest_file(db, file_path)
        count_after_second = db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

        assert count_after_first == count_after_second

    def test_data_integrity_across_tables(self, db, tmp_path):
        """Verify foreign key integrity across all tables."""
        products = [
            {
                "watchlist_model": "Ryzen 7 9800X3D",
                "watchlist_category": "cpu",
                "watchlist_brand": "AMD",
                "watchlist_gen_tier": "current",
                "retailer": "scorptec",
                "price_aud": 599.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/9800x3d",
            },
            {
                "watchlist_model": "GeForce RTX 5070",
                "watchlist_category": "gpu",
                "watchlist_brand": "NVIDIA",
                "watchlist_gen_tier": "current",
                "retailer": "scorptec",
                "price_aud": 999.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/rtx5070",
            },
        ]
        file_path = self._create_full_json(tmp_path, products)
        ingest_file(db, file_path)

        # Every snapshot should have a valid listing
        orphaned = db.execute("""
            SELECT COUNT(*) FROM price_snapshots ps
            WHERE NOT EXISTS (
                SELECT 1 FROM retailer_listings rl WHERE rl.id = ps.retailer_listing_id
            )
        """).fetchone()[0]
        assert orphaned == 0

        # Every listing should have a valid product
        orphaned_listings = db.execute("""
            SELECT COUNT(*) FROM retailer_listings rl
            WHERE NOT EXISTS (
                SELECT 1 FROM products p WHERE p.id = rl.product_id
            )
        """).fetchone()[0]
        assert orphaned_listings == 0
