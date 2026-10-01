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

from config import ACTIVE_RETAILERS
from health_checks import (
    CheckResult,
    check_backups,
    check_json_files,
    check_db_freshness,
    check_today_coverage,
    check_match_count_anomalies,
    check_match_count_drop,
    check_run_report,
    check_price_anomalies,
    check_spec_coverage,
    run_all_checks,
    MATCH_THRESHOLDS,
    STALE_THRESHOLD_DAYS,
    PRICE_ANOMALY_STD_DEVS,
    MIN_HISTORY_FOR_ANOMALY,
    PRICE_MOVE_PCT,
    SPEC_COVERAGE_MIN_PCT,
    SPEC_STALE_THRESHOLD_DAYS,
)
from health_checks import cooldown_explains, pccg_cooldown_remaining_hours


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
        for retailer in ACTIVE_RETAILERS:
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
        # One warning per missing retailer/category file: every combination
        # except the single scorptec_cpu file created above.
        assert len(warnings) == len(ACTIVE_RETAILERS) * 2 - 1
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


class TestZeroMatchIsAnError:
    def test_a_category_that_matched_nothing_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")
        _make_json_file(tmp_path, "umart", "gpu", 0)

        results = check_json_files(today)

        [r] = [r for r in results if r.check_name == "json_match_count_umart_gpu"]
        assert r.status == CheckResult.ERROR
        assert "0 matched" in r.message


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
        # 12 identical prior prices then a move: past MIN_HISTORY_FOR_ANOMALY
        # and past the changed-since-previous gate, so this still reaches the
        # std-dev arithmetic with a prior sigma of exactly 0.
        self._seed_product_with_history(conn, "RTX 5080", "scorptec", [500] * 12 + [520])
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

    def test_appearing_disappearing_variants_no_false_positive(self, db_path):
        """Stock changes (variant appears/disappears) must not false-positive.

        Regression test for the scenario once real multi-day history exists:
        - a genuine price jump on a long-lived variant   -> WARNING
        - a variant that vanishes (no latest snapshot)    -> NO warning
        - a variant that just appeared (insufficient history) -> NO warning
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5070 Ti Multi', 1)"
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE model = 'RTX 5070 Ti Multi'"
        ).fetchone()[0]

        listing_ids = {}
        for variant in ["JUMPER", "VANISHER", "NEWCOMER"]:
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
                "VALUES (?, 'scorptec', ?, ?, 'active')",
                (product_id, variant, f"https://x.com/{variant}"),
            )
            listing_ids[variant] = conn.execute(
                "SELECT id FROM retailer_listings WHERE listing_url = ?",
                (f"https://x.com/{variant}",),
            ).fetchone()[0]

        def _snap(lid, offset_days, price):
            d = (date.today() - timedelta(days=offset_days)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                "VALUES (?, ?, ?, 'in_stock')",
                (lid, d, price),
            )

        # Stable ~$1000 history over 12 prior days for the settled variants.
        # (A 1-in-N jump is only detectable once N >= ~10 prior points: max
        # deviation of a jump is roughly sqrt(N) sigma. 12 days is comfortably
        # past the 3-sigma PRICE_ANOMALY_STD_DEVS threshold.)
        # NEWCOMER (just appeared) gets no prior history — below MIN_HISTORY_FOR_ANOMALY.
        for variant in ["JUMPER", "VANISHER"]:
            for off in range(12, 0, -1):
                _snap(listing_ids[variant], off, 1000.0)

        # Latest day (offset 0):
        #  - JUMPER: genuine 4x jump -> must flag
        #  - VANISHER: no snapshot today (delisted/disappeared) -> must NOT flag
        #  - NEWCOMER: a single fresh price today (below MIN_HISTORY_FOR_ANOMALY) -> must NOT flag
        _snap(listing_ids["JUMPER"], 0, 4000.0)
        _snap(listing_ids["NEWCOMER"], 0, 1050.0)
        conn.commit()
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]

        # Exactly one anomaly: the real price jump.
        assert len(warnings) == 1, warnings
        assert "4000" in warnings[0].message or "5070 Ti Multi" in warnings[0].message

        # The stock-only changes must not be flagged, and the check must not crash.
        assert not any(
            "VANISHER" in r.message or "NEWCOMER" in r.message for r in results
        )
        assert not any(r.status == CheckResult.ERROR for r in results)


class TestPriceAnomalyBaseline:
    """The sigma test compares today against PRIOR days, gated at N >= 10.

    Two defects motivated this: MIN_HISTORY_FOR_ANOMALY was 3 against a
    3-sigma gate (with N points the largest reachable z-score is about
    sqrt(N), so a 3-sigma trip is impossible below N=10), and the baseline
    included the very point being tested, damping the deviation it measured.
    """

    def _seed(self, conn, model, retailer, prices):
        """Insert one listing with `prices` on consecutive days, oldest first."""
        conn.execute(
            "INSERT OR IGNORE INTO products (category, brand, model, tracked) "
            "VALUES ('gpu', 'NVIDIA', ?, 1)",
            (model,),
        )
        pid = conn.execute("SELECT id FROM products WHERE model = ?", (model,)).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO retailer_listings (product_id, retailer, listing_url, status) "
            "VALUES (?, ?, ?, 'active')",
            (pid, retailer, f"https://x.com/{model}"),
        )
        lid = conn.execute(
            "SELECT id FROM retailer_listings WHERE product_id = ? AND retailer = ?",
            (pid, retailer),
        ).fetchone()[0]
        for i, price in enumerate(prices):
            d = (date.today() - timedelta(days=len(prices) - 1 - i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                "VALUES (?, ?, ?, 'in_stock')",
                (lid, d, price),
            )
        conn.commit()
        return lid

    def test_baseline_excludes_todays_price(self, db_path):
        """The reported average is the mean of prior days only.

        Priors alternate 990/1010, so the prior mean is exactly $1000. Today is
        $1300. If today were still in the baseline the mean would be ~$1023,
        so the reported figure distinguishes the two implementations.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        priors = [990, 1010] * 6          # 12 prior points, mean exactly 1000
        self._seed(conn, "RTX 5070 Baseline", "scorptec", priors + [1300])
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "avg: $1000" in warnings[0].message, warnings[0].message

    def test_nine_prior_points_are_below_the_sigma_gate(self, db_path):
        """N=9 prior points cannot reach 3 sigma, so the sigma test must not run.

        Under the old gate of 3 this listing was walked through the check every
        day and could never be flagged by it.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        priors = [990, 1010] * 4 + [1000]   # 9 prior points
        self._seed(conn, "RTX 5070 Nine", "scorptec", priors + [1005])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results
        # The count must say so: 9 priors is one short, so this listing is the
        # one skipped. Asserting on the number, not just the phrase, is what
        # distinguishes "gated out" from "checked and found clean".
        ok = [r for r in results if r.status == CheckResult.OK]
        assert any("(1 skipped" in r.message for r in ok), ok


class TestPriceMoveRule:
    """A plain day-over-day percentage rule, alongside the sigma test.

    It needs only two points, so it covers the listings the sigma test
    structurally cannot -- including a perfectly flat history, where the prior
    standard deviation is 0 and no jump is reachable at any N.
    """

    _seed = TestPriceAnomalyBaseline._seed

    def test_flags_a_large_move_on_a_flat_history(self, db_path):
        """The RTX 5070's +45.0% on 28-Aug: flat priors, so sigma is blind.

        This is the case excluding today's point from the baseline creates:
        12 identical prior days give a prior sigma of exactly 0, so the z-test
        divides by nothing and skips. Only the move rule can catch it.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Flat", "scorptec", [1000] * 12 + [1450])
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "45.0%" in warnings[0].message, warnings[0].message

    def test_ignores_a_move_under_the_threshold(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Small", "scorptec", [1000] * 12 + [1050])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results

    def test_fires_on_only_two_points(self, db_path):
        """Two points is all the rule needs -- the sigma test needs ten."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Pair", "scorptec", [1000, 1500])
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "50.0%" in warnings[0].message, warnings[0].message

    def test_flags_a_large_drop_as_well_as_a_rise(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Drop", "scorptec", [1000] * 12 + [600])
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "-40.0%" in warnings[0].message, warnings[0].message

    def test_a_listing_is_reported_once_not_by_both_rules(self, db_path):
        """A jump on a jittery history trips both tests; it must warn once."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        priors = [990, 1010] * 6          # sigma > 0, so the z-test can fire
        self._seed(conn, "RTX 5070 Both", "scorptec", priors + [4000])
        conn.close()

        results = check_price_anomalies(db_path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "std devs" in warnings[0].message, warnings[0].message

    def test_a_single_snapshot_has_nothing_to_compare(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Lonely", "scorptec", [1000])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results

    def test_a_trivial_move_on_a_flat_history_is_not_an_anomaly(self, db_path):
        """The defect that actually motivated excluding today from the baseline.

        With today's point inside the baseline, a flat prior history makes the
        z-score exactly sqrt(N) for ANY move -- a $1 change and a $5000 change
        both score identically, because the only variance in the sample is the
        one the tested point contributes. On the real DB on 31-Aug, four of the
        five warnings were this artefact, including a +1.3% move ($7599 ->
        $7699 over 16 flat days) reported as "4.0 std devs".

        Here 18 flat prior days and a $1 move scored 4.24 sigma under the old
        implementation. It must now be silent: sigma is 0 so the z-test cannot
        run, and $1 is far under the move threshold.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5070 Trivial", "scorptec", [1000] * 18 + [1001])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results

    def test_a_step_is_flagged_on_the_day_and_then_goes_quiet(self, db_path):
        """An anomaly check for a price EVENT requires a price event.

        Real case from 31-Aug: RTX 5060 @ scorptec held $579 for 18 days, moved
        to $649 on 30-Aug and stayed there. Without a changed-since-previous
        gate the sigma test reports it every single day afterwards, because
        today's price stays far from a trailing mean still dominated by $579 --
        five such echoes were in that morning's digest, every one of them
        +0.0% on the day. Alarms that repeat for weeks train the reader to
        ignore the digest.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Day of the step: flat history, then +12.1%.
        self._seed(conn, "RTX 5060 Step", "scorptec", [579] * 18 + [649])
        conn.close()
        day_of = check_price_anomalies(db_path)
        warnings = [r for r in day_of if r.status == CheckResult.WARNING]
        assert len(warnings) == 1, warnings
        assert "12.1%" in warnings[0].message, warnings[0].message

    def test_the_day_after_a_step_is_silent(self, db_path):
        """Same listing, one day later, price unchanged -- must say nothing."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5060 Held", "scorptec", [579] * 18 + [649, 649])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results

    def test_an_unchanged_price_far_from_the_mean_is_not_flagged(self, db_path):
        """The exact 31-Aug shape: 4.0 sigma from the mean, 0.0% on the day."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._seed(conn, "RTX 5090 Echo", "pccg", [7599] * 16 + [7699, 7699])
        conn.close()

        results = check_price_anomalies(db_path)
        assert not any(r.status == CheckResult.WARNING for r in results), results

    def test_threshold_is_a_sane_fraction(self):
        """PRICE_MOVE_PCT is a fraction (0.10), not a percentage (10)."""
        assert 0 < PRICE_MOVE_PCT < 1


# ── Today coverage ──────────────────────────────────────────────────

class TestCheckTodayCoverage:
    """Test per-retailer "today has a snapshot" reporting."""

    def test_reports_ok_for_retailer_with_today_data(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        today = date.today().strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (today,))
        conn.commit()
        conn.close()

        results = check_today_coverage(db_path)
        scorptec = [r for r in results if r.check_name == "today_coverage_scorptec"][0]
        assert scorptec.status == CheckResult.OK

    def _yesterday_only(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (yesterday,))
        conn.commit()
        conn.close()

    def test_a_retailer_missing_today_is_an_error(self, db_path, monkeypatch):
        """#7(c): silence from an active retailer pages someone, unless a cooldown explains it."""
        monkeypatch.setattr("health_checks.cooldown_explains", lambda retailer: False)
        self._yesterday_only(db_path)

        by_name = {r.check_name: r for r in check_today_coverage(db_path)}

        assert by_name["today_coverage_pccg"].status == CheckResult.ERROR
        assert "no snapshot for today" in by_name["today_coverage_pccg"].message
        assert by_name["today_coverage_umart"].status == CheckResult.ERROR

    def test_a_cooldown_turns_the_missing_retailer_into_a_warning(self, db_path, monkeypatch):
        monkeypatch.setattr("health_checks.cooldown_explains", lambda retailer: retailer == "pccg")
        self._yesterday_only(db_path)

        by_name = {r.check_name: r for r in check_today_coverage(db_path)}

        assert by_name["today_coverage_pccg"].status == CheckResult.WARNING
        assert "cooldown" in by_name["today_coverage_pccg"].message
        assert by_name["today_coverage_umart"].status == CheckResult.ERROR

    def test_every_active_retailer_reported(self, db_path):
        """One result per retailer we scrape -- not per retailer with data.

        A retailer that reported nothing today has to appear saying so; if it
        were simply absent from the results, a scraper that died would look the
        same as a scraper that is fine.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        today = date.today().strftime("%Y-%m-%d")
        for i, retailer in enumerate(ACTIVE_RETAILERS, start=1):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, ?, ?, 'active')",
                (retailer, f"https://x.com/{i}"),
            )
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, ?, 100, 'in_stock')",
                (i, today),
            )
        conn.commit()
        conn.close()

        results = check_today_coverage(db_path)
        assert {r.check_name for r in results} == {
            f"today_coverage_{r}" for r in ACTIVE_RETAILERS
        }
        assert all(r.status == CheckResult.OK for r in results)


class TestCooldownExplains:
    def test_an_active_pccg_cooldown_explains_pccg_only(self, tmp_path, monkeypatch):
        cooldown = tmp_path / "pccg_cooldown.json"
        cooldown.write_text(json.dumps({"tripped_at": datetime.now().astimezone().isoformat(),
                                        "reason": "empty catalogue"}), encoding="utf-8")
        monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", cooldown)

        assert pccg_cooldown_remaining_hours() > 0
        assert cooldown_explains("pccg") is True
        assert cooldown_explains("umart") is False

    def test_no_cooldown_file_explains_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", tmp_path / "absent.json")
        assert cooldown_explains("pccg") is False


# ── Spec coverage / staleness ────────────────────────────────────────

class TestCheckSpecCoverage:
    """Test spec coverage + staleness reporting."""

    def _insert_product(self, conn, model):
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', ?, 1)",
            (model,),
        )
        return conn.execute(
            "SELECT id FROM products WHERE model = ?", (model,)
        ).fetchone()[0]

    def _insert_spec(self, conn, product_id, last_synced):
        conn.execute(
            "INSERT INTO specs (product_id, source, source_record_key, category, raw_json, last_synced_at) "
            "VALUES (?, 'amd-com', ?, 'cpu', '{}', ?)",
            (product_id, f"record-{product_id}", last_synced),
        )

    def test_full_coverage_ok(self, db_path):
        """Tracked product with a fresh spec row reports OK for both checks."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        pid = self._insert_product(conn, "Ryzen 7 9800X3D")
        fresh = date.today().strftime("%Y-%m-%dT04:21:36Z")
        self._insert_spec(conn, pid, fresh)
        conn.commit()
        conn.close()

        results = check_spec_coverage(db_path)
        by_name = {r.check_name: r for r in results}
        assert by_name["spec_coverage"].status == CheckResult.OK
        assert "1/1" in by_name["spec_coverage"].message
        assert by_name["spec_staleness"].status == CheckResult.OK
        assert "days ago" in by_name["spec_staleness"].message

    def test_low_coverage_warns(self, db_path):
        """Tracked products without a spec row produce a WARNING naming them."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        matched = self._insert_product(conn, "Ryzen 7 9800X3D")
        fresh = date.today().strftime("%Y-%m-%dT04:21:36Z")
        self._insert_spec(conn, matched, fresh)
        self._insert_product(conn, "Ryzen 5 5500")
        self._insert_product(conn, "Ryzen 9 9900")
        conn.commit()
        conn.close()

        results = check_spec_coverage(db_path)
        by_name = {r.check_name: r for r in results}
        assert by_name["spec_coverage"].status == CheckResult.WARNING
        assert "1/3" in by_name["spec_coverage"].message
        assert "Ryzen 5 5500" in by_name["spec_coverage"].message
        assert "Ryzen 9 9900" in by_name["spec_coverage"].message

    def test_missing_specs_table_warns(self, tmp_path):
        """A DB without the specs table is a named warning, not a crash."""
        path = tmp_path / "no_specs.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, brand TEXT, model TEXT, tracked INTEGER)")
        conn.commit()
        conn.close()

        results = check_spec_coverage(path)
        warnings = [r for r in results if r.status == CheckResult.WARNING]
        assert any(r.check_name == "specs_table" for r in warnings)
        assert any("migrate" in r.message for r in warnings)

    def test_no_spec_sync_recorded_warns(self, db_path):
        """A specs table with no rows reports no-sync, not coverage maths."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        self._insert_product(conn, "Ryzen 7 9800X3D")
        conn.commit()
        conn.close()

        results = check_spec_coverage(db_path)
        by_name = {r.check_name: r for r in results}
        assert by_name["spec_coverage"].status == CheckResult.WARNING
        assert by_name["spec_staleness"].status == CheckResult.WARNING
        assert "No spec sync recorded" in by_name["spec_staleness"].message

    def test_stale_spec_data_warns(self, db_path):
        """Spec sync older than SPEC_STALE_THRESHOLD_DAYS produces a WARNING."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        pid = self._insert_product(conn, "Ryzen 7 9800X3D")
        old = (date.today() - timedelta(days=SPEC_STALE_THRESHOLD_DAYS + 1)).strftime("%Y-%m-%dT04:21:36Z")
        self._insert_spec(conn, pid, old)
        conn.commit()
        conn.close()

        results = check_spec_coverage(db_path)
        by_name = {r.check_name: r for r in results}
        assert by_name["spec_staleness"].status == CheckResult.WARNING
        assert "Stale specs" in by_name["spec_staleness"].message

    def test_db_not_found(self, tmp_path):
        """Missing database returns no results (not an error)."""
        results = check_spec_coverage(tmp_path / "nonexistent.db")
        assert len(results) == 0

    def test_thresholds_positive(self):
        assert SPEC_COVERAGE_MIN_PCT > 0
        assert SPEC_COVERAGE_MIN_PCT <= 100
        assert SPEC_STALE_THRESHOLD_DAYS > 0


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


# ── Scraper telemetry -> health results (#14) ────────────────────────

class TestCheckRunReport:
    def test_a_clean_report_says_nothing(self):
        c = {"pages_attempted": 3, "pages_fetched": 3, "cards_seen": 60, "cards_dropped": 1}
        assert check_run_report({"retailer": "umart", "categories": {"gpu": c}}) == []

    def test_many_unparseable_cards_is_an_error(self):
        c = {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 20, "cards_dropped": 5}
        [r] = check_run_report({"retailer": "umart", "categories": {"gpu": c}})
        assert r.status == CheckResult.ERROR
        assert "5 of 20" in r.message

    def test_pccg_selector_drift_is_skipped(self):
        """F14: an empty PCCG Algolia catalogue is already a block/credentials
        error caught upstream (circuit breaker / AlgoliaAuthError) -- this
        rule must not double-alert on it."""
        c = {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 0, "cards_dropped": 0}
        assert check_run_report({"retailer": "pccg", "categories": {"gpu": c}}) == []

    def test_pccg_unparsed_cards_still_fires(self):
        """Fix round 1: unparsed_cards is NOT part of the F14 pccg skip -- it
        catches partial field-shape drift (e.g. an Algolia hit schema rename
        dropping products_name on some hits) that the empty-catalogue circuit
        breaker cannot see, since the catalogue here isn't empty."""
        c = {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 20, "cards_dropped": 5}
        [r] = check_run_report({"retailer": "pccg", "categories": {"gpu": c}})
        assert r.check_name == "unparsed_cards_pccg_gpu"
        assert r.status == CheckResult.ERROR
        assert "5 of 20" in r.message


def _drop_db(db_path, series):
    """series: {date: listing count} for pccg/gpu."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5070', 1)")
    most = max(series.values())
    for i in range(1, most + 1):
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                     "VALUES (1, 'pccg', ?, 'active')", (f"https://x/{i}",))
    for day, n in series.items():
        for i in range(1, n + 1):
            conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                         "VALUES (?, ?, 100, 'in_stock')", (i, day))
    conn.commit()
    conn.close()


class TestMatchCountDrop:
    PRIOR = {f"2026-09-{d:02d}": 100 for d in range(22, 29)}

    def test_45_percent_of_the_median_is_an_error(self, db_path):
        """#7 acceptance: a PCCG day at 45% of its 7-day median produces an ERROR."""
        _drop_db(db_path, {**self.PRIOR, "2026-09-29": 45})
        [r] = check_match_count_drop(db_path, today=date(2026, 9, 29))
        assert (r.check_name, r.status) == ("match_drop_pccg_gpu", CheckResult.ERROR)
        assert "45 listings today" in r.message

    def test_90_percent_is_fine(self, db_path):
        _drop_db(db_path, {**self.PRIOR, "2026-09-29": 90})
        [r] = check_match_count_drop(db_path, today=date(2026, 9, 29))
        assert r.status == CheckResult.OK

    def test_too_little_history_is_not_judged(self, db_path):
        _drop_db(db_path, {"2026-09-27": 100, "2026-09-28": 100, "2026-09-29": 10})
        assert check_match_count_drop(db_path, today=date(2026, 9, 29)) == []

    def test_a_missing_day_is_left_to_today_coverage(self, db_path):
        _drop_db(db_path, self.PRIOR)
        assert check_match_count_drop(db_path, today=date(2026, 9, 29)) == []


class TestCheckBackups:
    def test_a_recent_backup_is_ok(self, tmp_path):
        (tmp_path / "trackaroo_2026-09-29_040512.db").write_text("x")
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.OK

    def test_an_old_backup_warns(self, tmp_path):
        (tmp_path / "trackaroo_2026-09-26_040512.db").write_text("x")
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING
        assert "trackaroo_2026-09-26_040512.db" in r.message

    def test_no_backups_warns(self, tmp_path):
        [r] = check_backups(tmp_path / "absent", now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING

    def test_an_impossible_date_is_skipped_not_raised(self, tmp_path):
        """A name matching BACKUP_NAME_RE but not a real calendar date (e.g. a
        corrupted or hand-edited filename) must be skipped, not crash the
        check (#10 minor)."""
        (tmp_path / "trackaroo_2026-09-31_040512.db").write_text("x")  # September has 30 days
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING
        assert "No database backups" in r.message

    def test_a_future_dated_newest_backup_warns(self, tmp_path):
        """A future timestamp must not be trusted as fresh forever (#10 minor)."""
        (tmp_path / "trackaroo_2026-10-05_040512.db").write_text("x")
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING
        assert "future" in r.message.lower()
