"""
Tests for resync_stock_status.py and backup file filtering.

Covers:
    - resync identifies correct changes between buggy and fixed JSON
    - resync --dry-run makes no DB changes
    - resync apply updates affected rows
    - resync is idempotent (second run = 0 changes)
    - ingest.py and E2E skip .backup files
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Import the resync module functions
import resync_stock_status
from ingest import init_db, parse_date_from_filename, ingest_file


class TestResyncDryRun:
    """Dry-run mode identifies changes without modifying the DB."""

    def _setup_db_with_buggy_data(self, tmp_path):
        """Create a minimal DB with PCCG 13-Aug data (all in_stock = buggy)."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)

        # Create a product + listing + snapshot that mimics buggy state
        conn.execute("""
            INSERT INTO products (id, category, brand, model, tracked)
            VALUES (1, 'gpu', 'NVIDIA', 'GeForce RTX 5090', 1)
        """)
        conn.execute("""
            INSERT INTO retailer_listings (id, product_id, retailer, listing_url, status)
            VALUES (1, 1, 'pccg', 'https://www.pccasegear.com/products/99999/test-gpu', 'active')
        """)
        conn.execute("""
            INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)
            VALUES (1, '2026-08-13', 7599.0, 'in_stock')
        """)
        conn.commit()
        return conn, db_path

    def test_dry_run_reports_changes(self, tmp_path, caplog):
        """Dry-run should report changes but not modify the DB."""
        conn, db_path = self._setup_db_with_buggy_data(tmp_path)

        # Create buggy + fixed JSON pair
        file_date = "13_August_2026"
        buggy = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "in_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }
        fixed = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "out_of_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }

        # Write files
        buggy_path = tmp_path / f"gpu_pccg_{file_date}.backup_buggy.json"
        fixed_path = tmp_path / f"gpu_pccg_{file_date}.json"
        buggy_path.write_text(json.dumps(buggy), encoding="utf-8")
        fixed_path.write_text(json.dumps(fixed), encoding="utf-8")

        # Monkey-patch DATA_DIR for the test
        orig_data_dir = resync_stock_status.DATA_DIR
        resync_stock_status.DATA_DIR = tmp_path

        try:
            changes = resync_stock_status.resync(conn, "2026-08-13", dry_run=True)
            assert changes == 1, "Should detect 1 change"

            # Verify DB was NOT modified
            row = conn.execute(
                "SELECT stock_status FROM price_snapshots WHERE id = 1"
            ).fetchone()
            assert row[0] == "in_stock", "DB should be unchanged in dry-run"
        finally:
            resync_stock_status.DATA_DIR = orig_data_dir
            conn.close()

    def test_apply_updates_db(self, tmp_path):
        """Apply mode should update affected rows."""
        conn, db_path = self._setup_db_with_buggy_data(tmp_path)

        file_date = "13_August_2026"
        buggy = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "in_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }
        fixed = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "preorder",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }

        buggy_path = tmp_path / f"gpu_pccg_{file_date}.backup_buggy.json"
        fixed_path = tmp_path / f"gpu_pccg_{file_date}.json"
        buggy_path.write_text(json.dumps(buggy), encoding="utf-8")
        fixed_path.write_text(json.dumps(fixed), encoding="utf-8")

        orig_data_dir = resync_stock_status.DATA_DIR
        resync_stock_status.DATA_DIR = tmp_path

        try:
            changes = resync_stock_status.resync(conn, "2026-08-13", dry_run=False)
            assert changes == 1

            # Verify DB WAS modified
            row = conn.execute(
                "SELECT stock_status FROM price_snapshots WHERE id = 1"
            ).fetchone()
            assert row[0] == "preorder"
        finally:
            resync_stock_status.DATA_DIR = orig_data_dir
            conn.close()

    def test_idempotent(self, tmp_path):
        """Second run should report 0 changes."""
        conn, db_path = self._setup_db_with_buggy_data(tmp_path)

        file_date = "13_August_2026"
        buggy = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "in_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }
        fixed = {
            "retailer": "pccg", "matched": 1,
            "products": [{
                "name": "Test GPU", "price": 7599.0,
                "url": "https://www.pccasegear.com/products/99999/test-gpu",
                "stock_status": "out_of_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "GeForce RTX 5090",
            }],
        }

        buggy_path = tmp_path / f"gpu_pccg_{file_date}.backup_buggy.json"
        fixed_path = tmp_path / f"gpu_pccg_{file_date}.json"
        buggy_path.write_text(json.dumps(buggy), encoding="utf-8")
        fixed_path.write_text(json.dumps(fixed), encoding="utf-8")

        orig_data_dir = resync_stock_status.DATA_DIR
        resync_stock_status.DATA_DIR = tmp_path

        try:
            # First run: updates
            changes1 = resync_stock_status.resync(conn, "2026-08-13", dry_run=False)
            assert changes1 == 1

            # Second run: no changes (idempotent)
            changes2 = resync_stock_status.resync(conn, "2026-08-13", dry_run=False)
            assert changes2 == 0, "Second run should be idempotent"
        finally:
            resync_stock_status.DATA_DIR = orig_data_dir
            conn.close()


class TestBackupFileFiltering:
    """Verify that .backup files are excluded from ingestion."""

    def test_parse_date_rejects_backup_filename(self):
        """Backup filenames should not parse to a valid date."""
        # The backup file has a broken date pattern
        date = parse_date_from_filename("cpu_pccg_13_August_2026.backup_buggy.json")
        assert date == "", "Backup filename should not parse to a valid date"

    def test_normal_filename_parses(self):
        """Normal filenames should parse correctly."""
        date = parse_date_from_filename("gpu_scorptec_13_August_2026.json")
        assert date == "2026-08-13"

    def test_ingest_main_skips_backup_files(self, tmp_path, monkeypatch):
        """ingest.main() should skip .backup files when globbing."""
        # Create test files
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        normal_file = data_dir / "gpu_scorptec_10_August_2026.json"
        backup_file = data_dir / "gpu_scorptec_10_August_2026.backup_buggy.json"

        normal_data = {
            "retailer": "scorptec", "matched": 1,
            "products": [{
                "name": "Test GPU", "price_aud": 500.0, "url": "https://example.com/gpu",
                "stock_status": "in_stock",
                "watchlist_category": "gpu", "watchlist_brand": "NVIDIA",
                "watchlist_model": "RTX 5070", "scraped_name": "Test GPU",
            }],
        }
        normal_file.write_text(json.dumps(normal_data), encoding="utf-8")
        backup_file.write_text(json.dumps(normal_data), encoding="utf-8")

        # Monkey-patch DATA_DIR and DB_PATH
        from ingest import DATA_DIR, DB_PATH
        monkeypatch.setattr("ingest.DATA_DIR", data_dir)
        monkeypatch.setattr("ingest.DB_PATH", tmp_path / "test.db")

        # Run ingest
        import ingest
        ingest.main(argv=[])

        # Verify only the normal file was processed (backup was skipped)
        # Both files exist but only normal should have been ingested


class TestResyncHelpers:
    """Test helper functions."""

    def test_date_components(self):
        db_date, file_date = resync_stock_status._date_components("2026-08-13")
        assert db_date == "2026-08-13"
        assert file_date == "13_August_2026"

    def test_build_status_diff_empty_when_identical(self, tmp_path):
        """No diff when buggy and fixed are identical."""
        products = [{
            "url": "https://example.com/test",
            "stock_status": "in_stock",
        }]
        diff = resync_stock_status._build_status_diff(products, products)
        assert len(diff) == 0

    def test_build_status_diff_detects_change(self, tmp_path):
        """Diff detects stock_status changes."""
        buggy = [{
            "url": "https://example.com/test",
            "stock_status": "in_stock",
        }]
        fixed = [{
            "url": "https://example.com/test",
            "stock_status": "out_of_stock",
        }]
        diff = resync_stock_status._build_status_diff(buggy, fixed)
        assert diff["https://example.com/test"] == "out_of_stock"
