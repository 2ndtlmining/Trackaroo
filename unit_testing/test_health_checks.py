"""
Tests for health_checks.py — Trackaroo health check module.

Tests:
- JSON file validation (missing files, low match counts, invalid prices/URLs)
- Database freshness checks (stale data, missing retailers)
- Match count anomaly detection
- Price anomaly detection
- Aggregate runner
- Edge cases (empty DB, no history, zero std dev)
"""
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

from health_checks import (
    CheckResult,
    check_json_files,
    check_db_freshness,
    check_match_count_anomalies,
    check_price_anomalies,
    run_all_checks,
    MATCH_THRESHOLDS,
    STALE_THRESHOLD_DAYS,
    PRICE_ANOMALY_STD_DEVS,
    MIN_HISTORY_FOR_ANOMALY,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_json_file(tmp_path, retailer, category, matched_count, extra_products=None):
    """Create a test JSON file with the right naming convention."""
    today = date.today().strftime("%d_%B_%Y")
    filename = f"{category}_{retailer}_{today}.json"
    products = []
    for i in range(matched_count):
        products.append({
            "watchlist_model": f"Test Product {i}",
            "watchlist_category": category,
            "watchlist_brand": "TestBrand",
            "watchlist_gen_tier": "current",
            "retailer": retailer,
            "price_aud": 100.0 + i * 10,
            "stock_status": "in_stock",
            "url": f"https://example.com/product/{i}",
        })
    if extra_products:
        products.extend(extra_products)
    data = {
        "retailer": retailer,
        "scrape_date": today,
        "category": category,
        "matched": matched_count + len(extra_products or []),
        "products": products,
    }
    file_path = tmp_path / filename
    file_path.write_text(json.dumps(data))
    return file_path


# ── JSON file validation ────────────────────────────────────────────

class TestCheckJsonFiles:
    """Test JSON file validation."""

    def test_all_files_present(self, tmp_path, monkeypatch):
        """All expected files exist and are valid."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        # Use counts above the new multi-variant thresholds (scorptec min_per_category=30, pccg=5)
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 35)

        results = check_json_files(today)
        # All should be OK
        assert all(r.status == CheckResult.OK for r in results)

    def test_missing_file(self, tmp_path, monkeypatch):
        """Missing JSON file produces a warning."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        # Only create one file with enough matches — others are missing
        _make_json_file(tmp_path, "scorptec", "cpu", 35)

        results = check_json_files(today)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        # Should have 3 warnings for missing files (scorptec_gpu, pccg_cpu, pccg_gpu)
        assert len(warnings) == 3
        assert any("Missing" in r.message for r in warnings)

    def test_low_match_count(self, tmp_path, monkeypatch):
        """Match count below threshold produces a warning."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        # Create files with very low match counts
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 1)

        results = check_json_files(today)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("Low match count" in r.message for r in warnings)

    def test_invalid_price(self, tmp_path, monkeypatch):
        """Products with invalid prices produce an error."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        bad_products = [
            {"price_aud": None, "url": "https://x.com/1", "stock_status": "in_stock"},
            {"price_aud": -50, "url": "https://x.com/2", "stock_status": "in_stock"},
            {"price_aud": 0, "url": "https://x.com/3", "stock_status": "in_stock"},
        ]
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 20, extra_products=bad_products)

        results = check_json_files(today)
        errors = [r for r in results if r.status == CheckResult.ERROR]
        assert any("invalid prices" in r.message for r in errors)

    def test_invalid_url(self, tmp_path, monkeypatch):
        """Products with empty/invalid URLs produce a warning."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        bad_products = [
            {"price_aud": 100, "url": "", "stock_status": "in_stock"},
            {"price_aud": 100, "url": "not-a-url", "stock_status": "in_stock"},
        ]
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 20, extra_products=bad_products)

        results = check_json_files(today)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("URL" in r.message for r in warnings)

    def test_invalid_stock_status(self, tmp_path, monkeypatch):
        """Unrecognized stock status produces a warning."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        bad_products = [
            {"price_aud": 100, "url": "https://x.com/1", "stock_status": "bogus_status"},
        ]
        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 20, extra_products=bad_products)

        results = check_json_files(today)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("stock status" in r.message for r in warnings)

    def test_invalid_json_file(self, tmp_path, monkeypatch):
        """Corrupted JSON file produces an error."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        # Write invalid JSON
        filename = f"cpu_scorptec_{today}.json"
        (tmp_path / filename).write_text("{invalid json}")

        results = check_json_files(today)
        errors = [r for r in results if r.status == CheckResult.ERROR]
        assert any("Invalid JSON" in r.message for r in errors)

    def test_defaults_to_today(self, tmp_path, monkeypatch):
        """Without target_date, defaults to today."""
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")

        for retailer in ["scorptec", "pccg"]:
            for category in ["cpu", "gpu"]:
                _make_json_file(tmp_path, retailer, category, 20)

        results = check_json_files()  # No date argument
        assert len(results) > 0


# ── Database freshness checks ───────────────────────────────────────

class TestCheckDbFreshness:
    """Test database freshness checks."""

    def test_fresh_data(self, db_path):
        """Recent snapshots produce OK status."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Insert a snapshot for today
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'pccg', 'https://x.com/2', 'active')")
        today = date.today().strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (today,))
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (2, ?, 110, 'in_stock')", (today,))
        conn.commit()
        conn.close()

        results = check_db_freshness(db_path)
        # Should have OK results for both retailers
        ok_results = [r for r in results if r.status == CheckResult.OK]
        assert len(ok_results) >= 3  # scorptec, pccg, snapshot_count

    def test_stale_data(self, db_path):
        """Old snapshots produce a warning."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Insert a snapshot from 10 days ago
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (old_date,))
        conn.commit()
        conn.close()

        results = check_db_freshness(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("Stale" in r.message for r in warnings)

    def test_missing_retailer(self, db_path):
        """Retailer with no data produces a warning."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Only insert Scorptec data — PCCG is missing
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        today = date.today().strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (today,))
        conn.commit()
        conn.close()

        results = check_db_freshness(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("pccg" in r.message.lower() for r in warnings)

    def test_db_not_found(self, tmp_path):
        """Missing database produces an error."""
        results = check_db_freshness(tmp_path / "nonexistent.db")
        errors = [r for r in results if r.status == CheckResult.ERROR]
        assert len(errors) == 1
        assert "not found" in errors[0].message

    def test_snapshot_count(self, db_path):
        """Total snapshot count is reported."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        today = date.today().strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (today,))
        conn.commit()
        conn.close()

        results = check_db_freshness(db_path)
        count_results = [r for r in results if "snapshot_count" in r.check_name]
        assert len(count_results) == 1
        assert "Total snapshots" in count_results[0].message


# ── Match count anomaly detection ───────────────────────────────────

class TestCheckMatchCountAnomalies:
    """Test match count anomaly detection."""

    def _seed_history(self, conn, retailer, base_count=50):
        """Insert historical match data for a retailer."""
        for i in range(base_count):
            conn.execute(
                "INSERT OR IGNORE INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', ?, 1)",
                (f"CPU {i}",),
            )
        for i in range(base_count):
            pid = conn.execute("SELECT id FROM products WHERE model = ?", (f"CPU {i}",)).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (?, ?, ?, 'active')",
                (pid, retailer, f"https://x.com/{i}"),
            )

    def test_stable_match_count(self, db_path):
        """Normal match counts produce OK status."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Use base_count above the new multi-variant threshold (scorptec min_total=90)
        self._seed_history(conn, "scorptec", base_count=95)
        for i in range(95):
            lid = conn.execute(
                "SELECT id FROM retailer_listings WHERE retailer = 'scorptec' AND listing_url = ?",
                (f"https://x.com/{i}",),
            ).fetchone()[0]
            today = date.today().strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, ?, 100, 'in_stock')",
                (lid, today),
            )
        conn.commit()
        conn.close()

        results = check_match_count_anomalies(db_path)
        ok_results = [r for r in results if r.status == CheckResult.OK and "scorptec" in r.check_name]
        assert len(ok_results) >= 1

    def test_low_match_count(self, db_path):
        """Sudden drop in match count produces a warning."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed_history(conn, "scorptec", base_count=5)  # Below threshold (scorptec min_total=90)
        for i in range(5):
            pid = conn.execute("SELECT id FROM products WHERE model = ?", (f"CPU {i}",)).fetchone()[0]
            lid = conn.execute(
                "SELECT id FROM retailer_listings WHERE product_id = ? AND retailer = 'scorptec'",
                (pid,),
            ).fetchone()[0]
            today = date.today().strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, ?, 100, 'in_stock')",
                (lid, today),
            )
        conn.commit()
        conn.close()

        results = check_match_count_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING and "scorptec" in r.check_name]
        assert len(warnings) >= 1

    def test_db_not_found(self, tmp_path):
        """Missing database produces an error."""
        results = check_match_count_anomalies(tmp_path / "nonexistent.db")
        errors = [r for r in results if r.status == CheckResult.ERROR]
        assert len(errors) == 1

    def test_multiple_variants_not_counted_as_products(self, db_path):
        """Multi-variant listings must be counted per listing, not per product.

        Regression test: the anomaly check previously counted
        COUNT(DISTINCT product_id), so a retailer with 2 products across
        192 variant listings reported 2 and false-flagged a drop against
        thresholds calibrated for variants.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Two watchlist products
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5070', 1)")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5080', 1)")
        today = date.today().strftime("%Y-%m-%d")

        # Many variant listings per product, all snapshotted today
        listing_count = 0
        for product_id in (1, 2):
            for i in range(100):
                listing_count += 1
                conn.execute(
                    "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
                    "VALUES (?, 'scorptec', ?, ?, 'active')",
                    (product_id, f"Variant {i}", f"https://x.com/{listing_count}"),
                )
                lid = conn.execute(
                    "SELECT id FROM retailer_listings WHERE listing_url = ?",
                    (f"https://x.com/{listing_count}",),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                    "VALUES (?, ?, 100, 'in_stock')",
                    (lid, today),
                )
        conn.commit()
        conn.close()

        results = check_match_count_anomalies(db_path)
        # Variant count (200) is far above scorptec min_total=90, so OK
        ok_results = [r for r in results if r.status == CheckResult.OK and "scorptec" in r.check_name]
        assert len(ok_results) >= 1
        # Must NOT report a drop based on the 2 distinct products
        warnings = [r for r in results if r.status == CheckResult.WARNING and "scorptec" in r.check_name]
        assert len(warnings) == 0


# ── Price anomaly detection ─────────────────────────────────────────

class TestCheckPriceAnomalies:
    """Test price anomaly detection."""

    def _seed_product_with_history(self, conn, model, retailer, prices):
        """Insert a product with multiple price snapshots."""
        conn.execute(
            "INSERT OR IGNORE INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', ?, 1)",
            (model,),
        )
        pid = conn.execute("SELECT id FROM products WHERE model = ?", (model,)).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (?, ?, ?, 'active')",
            (pid, retailer, f"https://x.com/{model}"),
        )
        lid = conn.execute(
            "SELECT id FROM retailer_listings WHERE product_id = ? AND retailer = ?",
            (pid, retailer),
        ).fetchone()[0]

        for i, price in enumerate(prices):
            snapshot_date = (date.today() - timedelta(days=len(prices) - i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, ?, ?, 'in_stock')",
                (lid, snapshot_date, price),
            )
        conn.commit()
        return lid

    def test_normal_prices(self, db_path):
        """Consistent prices produce no anomalies."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed_product_with_history(conn, "RTX 5070", "scorptec", [500, 510, 495, 505, 500])
        conn.close()

        results = check_price_anomalies(db_path)
        # Should be OK — no anomalies
        ok_results = [r for r in results if r.status == CheckResult.OK]
        assert any("No price anomalies" in r.message for r in ok_results)

    def test_price_spike(self, db_path):
        """A sudden price spike produces a warning."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Normal price ~500 for 20 days, then spikes to 2000 (3x = clear anomaly)
        prices = [500, 510, 495, 505, 500, 510, 490, 505, 500, 508, 498, 502, 510, 495, 500, 505, 498, 502, 500, 505, 2000]
        self._seed_product_with_history(conn, "RTX 5090", "scorptec", prices)
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any("RTX 5090" in r.message for r in warnings)

    def test_insufficient_history(self, db_path):
        """Products with insufficient history are skipped."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Only 2 data points — below MIN_HISTORY_FOR_ANOMALY (3)
        self._seed_product_with_history(conn, "RTX 5060", "scorptec", [500, 510])
        conn.close()

        results = check_price_anomalies(db_path)
        # Should be OK with skipped message
        ok_results = [r for r in results if r.status == CheckResult.OK]
        assert any("insufficient history" in r.message for r in ok_results)

    def test_zero_variance(self, db_path):
        """Products with identical prices don't cause division errors."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed_product_with_history(conn, "RTX 5080", "scorptec", [500, 500, 500, 500])
        conn.close()

        results = check_price_anomalies(db_path)
        # Should be OK — no crash from zero std dev
        assert not any(r.status == CheckResult.ERROR for r in results)

    def test_empty_db(self, db_path):
        """Empty database produces no results (not an error)."""
        results = check_price_anomalies(db_path)
        # Empty DB has no products, so the check returns an OK with skipped message
        ok_results = [r for r in results if r.status == CheckResult.OK]
        assert any("No price anomalies" in r.message for r in ok_results)

    def test_db_not_found(self, tmp_path):
        """Missing database returns empty results (not an error)."""
        results = check_price_anomalies(tmp_path / "nonexistent.db")
        assert len(results) == 0


# ── CheckResult class ────────────────────────────────────────────────

class TestCheckResult:
    """Test the CheckResult data class."""

    def test_repr_ok(self):
        r = CheckResult("test_check", CheckResult.OK, "All good")
        assert "[OK]" in repr(r)
        assert "test_check" in repr(r)

    def test_repr_warning(self):
        r = CheckResult("test_check", CheckResult.WARNING, "Something off")
        assert "[WARNING]" in repr(r)

    def test_repr_error(self):
        r = CheckResult("test_check", CheckResult.ERROR, "Broken")
        assert "[ERROR]" in repr(r)


# ── Threshold constants ─────────────────────────────────────────────

class TestThresholds:
    """Test that threshold constants are reasonable."""

    def test_scorptec_thresholds_exist(self):
        assert "scorptec" in MATCH_THRESHOLDS
        assert MATCH_THRESHOLDS["scorptec"]["min_total"] > 0
        assert MATCH_THRESHOLDS["scorptec"]["min_per_category"] > 0

    def test_pccg_thresholds_exist(self):
        assert "pccg" in MATCH_THRESHOLDS
        assert MATCH_THRESHOLDS["pccg"]["min_total"] > 0
        assert MATCH_THRESHOLDS["pccg"]["min_per_category"] > 0

    def test_stale_threshold_positive(self):
        assert STALE_THRESHOLD_DAYS > 0

    def test_price_anomaly_threshold_positive(self):
        assert PRICE_ANOMALY_STD_DEVS > 0

    def test_min_history_positive(self):
        assert MIN_HISTORY_FOR_ANOMALY > 0
