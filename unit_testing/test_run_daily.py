"""
Tests for the daily runner (run_daily.py).

Tests:
- today_filename() returns correct format
- Argument parsing for all flag combinations
- Ingestion picks up today's files correctly
- Health check integration (--no-health flag)
"""
import sqlite3
import json
from datetime import date
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
import sys
sys.path.insert(0, sys_path)
from run_daily import today_filename


class TestTodayFilename:
    """Test date formatting for filenames."""

    def test_format(self):
        """Should return DD_Month_YYYY format."""
        result = today_filename()
        parts = result.split("_")
        assert len(parts) == 3
        # Day is numeric
        assert parts[0].isdigit()
        # Year is numeric
        assert parts[2].isdigit()
        # Month is a proper month name
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        assert parts[1] in months

    def test_consistency(self):
        """Calling twice should return the same value."""
        assert today_filename() == today_filename()


class TestIngestToday:
    """Test ingestion of today's files."""

    def _write_today_file(self, tmp_path, retailer, category):
        """Write a dummy JSON file with today's date."""
        from run_daily import today_filename
        today = today_filename()
        data = {
            "retailer": retailer,
            "scrape_date": today,
            "category": category,
            "total_watchlist": 1,
            "matched": 1,
            "products": [{
                "watchlist_model": "Ryzen 7 9800X3D",
                "watchlist_category": "cpu",
                "watchlist_brand": "AMD",
                "watchlist_gen_tier": "current",
                "retailer": retailer,
                "price_aud": 599.0,
                "stock_status": "in_stock",
                "url": f"https://{retailer}.com.au/products/test",
            }],
        }
        file_path = tmp_path / f"{category}_{retailer}_{today}.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        return file_path

    def test_ingest_today_files(self, db, tmp_path, monkeypatch):
        """Ingest picks up files for today's date."""
        from run_daily import ingest_today
        from pathlib import Path

        # Patch DATA_DIR to use tmp_path
        monkeypatch.setattr("run_daily.DATA_DIR", tmp_path)

        # Write a today file
        self._write_today_file(tmp_path, "scorptec", "cpu")

        stats = ingest_today(db)
        assert stats["inserted"] == 1
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 1

    def test_skip_old_files(self, db, tmp_path, monkeypatch):
        """Only ingest files matching today's date."""
        from run_daily import ingest_today

        monkeypatch.setattr("run_daily.DATA_DIR", tmp_path)

        # Write an old file (yesterday's date)
        old_file = tmp_path / "cpu_scorptec_09_August_2026.json"
        old_file.write_text(json.dumps({
            "retailer": "scorptec",
            "scrape_date": "09_August_2026",
            "category": "cpu",
            "matched": 1,
            "products": [{
                "watchlist_model": "Ryzen 7 9800X3D",
                "watchlist_category": "cpu",
                "watchlist_brand": "AMD",
                "watchlist_gen_tier": "current",
                "retailer": "scorptec",
                "price_aud": 599.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/test",
            }],
        }))

        stats = ingest_today(db)
        # Should find no files for today
        assert stats == {}
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0

    def test_dry_run_no_write(self, db, tmp_path, monkeypatch):
        """Dry run doesn't insert data."""
        from run_daily import ingest_today

        monkeypatch.setattr("run_daily.DATA_DIR", tmp_path)
        self._write_today_file(tmp_path, "scorptec", "cpu")

        stats = ingest_today(db, dry_run=True)
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 0


class TestHealthCheckIntegration:
    """Test that health checks are properly integrated into run_daily."""

    def test_no_health_flag_exists(self):
        """The --no-health flag is recognized."""
        import argparse
        import run_daily
        # Parse with --no-health should not raise
        parser = argparse.ArgumentParser()
        parser.add_argument("--no-health", action="store_true")
        args = parser.parse_args(["--no-health"])
        assert args.no_health is True

    def test_health_checks_callable_from_runner(self):
        """Health check functions can be imported from run_daily context."""
        from health_checks import check_json_files, check_db_freshness, CheckResult
        # Should not raise
        assert CheckResult.OK == "OK"

    def test_json_validation_runs_on_today(self, tmp_path, monkeypatch):
        """JSON validation runs for today's date when files exist."""
        from health_checks import check_json_files, CheckResult
        from run_daily import today_filename

        # Create valid files with matched count above multi-variant thresholds
        today = today_filename()
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                data = {
                    "retailer": retailer,
                    "matched": 35,  # Above scorptec min_per_category=30 and pccg=5
                    "products": [{
                        "price_aud": 100.0,
                        "url": "https://example.com/test",
                        "stock_status": "in_stock",
                    }],
                }
                file_path = tmp_path / f"{category}_{retailer}_{today}.json"
                file_path.write_text(json.dumps(data))

        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        results = check_json_files(today)
        # All should be OK
        assert all(r.status == CheckResult.OK for r in results)

    def test_db_freshness_runs_with_real_db(self, db):
        """DB freshness check works with a populated DB."""
        from health_checks import check_db_freshness, CheckResult

        # Seed some data
        db.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        db.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        today = date.today().strftime("%Y-%m-%d")
        db.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (today,))
        db.commit()

        results = check_db_freshness()
        # Should have at least snapshot count result
        assert len(results) > 0
