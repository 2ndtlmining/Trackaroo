"""
Tests for query.py — price querying of the Trackaroo database.

Tests:
- get_connection (existing DB, missing DB exits)
- show_latest_prices (filters by model/category/retailer, latest date only)
- show_trends (grouped by product over dates)
- show_biggest_movers (price changes between the two most recent dates)
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

from query import (
    get_connection,
    show_latest_prices,
    show_trends,
    show_biggest_movers,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _seed(db, snapshots):
    """Insert a product + retailer listing + snapshots.

    snapshots is a list of (date_str, price) tuples.
    Returns (product_id, listing_id).
    """
    cur = db.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
    product_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
        "VALUES (?, 'scorptec', 'Variant A', 'https://x.com/1', 'active')",
        (product_id,),
    )
    listing_id = cur.lastrowid
    for date_str, price in snapshots:
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
            "VALUES (?, ?, ?, 'in_stock')",
            (listing_id, date_str, price),
        )
    db.commit()
    return product_id, listing_id


# ── get_connection ───────────────────────────────────────────────────

class TestGetConnection:
    def test_returns_connection(self, db_path):
        conn = get_connection(db_path)
        assert conn is not None
        conn.close()

    def test_missing_db_exits(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            get_connection(tmp_path / "missing.db")


# ── show_latest_prices ──────────────────────────────────────────────

class TestShowLatestPrices:
    def test_latest_only(self, db, capsys):
        """Only the latest snapshot per listing is shown."""
        _seed(db, [("2026-08-09", 100.0), ("2026-08-10", 110.0)])
        show_latest_prices(db)
        out = capsys.readouterr().out
        assert "110.00" in out
        assert "100.00" not in out
        assert "1 results" in out

    def test_filter_by_model(self, db, capsys):
        _seed(db, [("2026-08-10", 110.0)])
        show_latest_prices(db, model="Test CPU")
        out = capsys.readouterr().out
        assert "Test CPU" in out

    def test_filter_no_match(self, db, capsys):
        _seed(db, [("2026-08-10", 110.0)])
        show_latest_prices(db, model="Nonexistent")
        assert "No data found." in capsys.readouterr().out

    def test_empty_db(self, db, capsys):
        show_latest_prices(db)
        assert "No data found." in capsys.readouterr().out


# ── show_trends ─────────────────────────────────────────────────────

class TestShowTrends:
    def test_lists_all_dates(self, db, capsys):
        """All snapshots are listed across dates."""
        _seed(db, [("2026-08-09", 100.0), ("2026-08-10", 110.0)])
        show_trends(db)
        out = capsys.readouterr().out
        assert "2 snapshots" in out
        assert "2026-08-09" in out
        assert "2026-08-10" in out

    def test_no_data(self, db, capsys):
        show_trends(db)
        assert "No data found." in capsys.readouterr().out


# ── show_biggest_movers ─────────────────────────────────────────────

class TestShowBiggestMovers:
    def test_highlights_change(self, db, capsys):
        _seed(db, [("2026-08-09", 100.0), ("2026-08-10", 150.0)])
        show_biggest_movers(db)
        out = capsys.readouterr().out
        assert "+50.00" in out
        assert "1 products with price changes" in out

    def test_no_change(self, db, capsys):
        _seed(db, [("2026-08-09", 100.0), ("2026-08-10", 100.0)])
        show_biggest_movers(db)
        assert "No price changes between" in capsys.readouterr().out

    def test_insufficient_dates(self, db, capsys):
        _seed(db, [("2026-08-10", 100.0)])
        show_biggest_movers(db)
        assert "Need at least 2 dates" in capsys.readouterr().out

    def test_empty_db(self, db, capsys):
        show_biggest_movers(db)
        assert "Need at least 2 dates" in capsys.readouterr().out
