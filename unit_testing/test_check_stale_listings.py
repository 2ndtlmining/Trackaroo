"""
Tests for check_stale_listings.py -- ages out listings nobody has seen while
their own retailer keeps reporting fine, without ever mass-mistagging a whole
retailer's catalogue just because that retailer went quiet.

Covers:
- query_stale_candidates (unseen-while-retailer-current selection, the
  mass-mistagging guard, delisted/seen-today exclusions, empty DB)
- run (marks stale, leaves silent-retailer listings untouched, dry-run,
  idempotent, never deletes rows)
"""
import sqlite3
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_stale_listings import query_stale_candidates, run  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────

def _seed_listing(
    db,
    *,
    retailer="scorptec",
    brand="AMD",
    model="Test GPU",
    variant=None,
    url="https://scorptec.example/1",
    tracked=1,
    status="active",
    snapshots,
):
    """Insert a product + listing + snapshots. snapshots = [(date, price, stock)]."""
    cur = db.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, ?)",
        ("gpu", brand, model, tracked),
    )
    product_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, retailer, variant, url, status),
    )
    listing_id = cur.lastrowid
    for snapshot_date, price, stock in snapshots:
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
            "VALUES (?, ?, ?, ?)",
            (listing_id, snapshot_date, price, stock),
        )
    db.commit()
    return product_id, listing_id


def _status(db_path, listing_id):
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status FROM retailer_listings WHERE id = ?", (listing_id,)
    ).fetchone()
    conn.close()
    return row[0]


def _count_listings(db_path):
    conn = sqlite3.connect(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
    conn.close()
    return n


TODAY = "2026-08-20"


# ── query_stale_candidates ──────────────────────────────────────────

class TestQueryStaleCandidates:
    def test_listing_unseen_while_retailer_current_is_a_candidate(self, db):
        # The retailer has a fresh snapshot today (via another listing), but
        # THIS listing hasn't been seen in 11 days -- a genuine candidate.
        _seed_listing(db, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _, lid = _seed_listing(db, url="https://s/stale", snapshots=[("2026-08-09", 100, "in_stock")])
        rows = query_stale_candidates(db, TODAY, stale_days=7)
        assert [r["id"] for r in rows] == [lid]

    def test_retailer_with_no_recent_data_yields_no_candidates(self, db):
        # The mass-mistagging guard. This listing hasn't been seen in ages,
        # but NEITHER has anything else at this retailer -- the retailer is
        # silent (e.g. a cooldown), not the listing gone missing. Must be
        # left alone.
        _seed_listing(db, url="https://s/1", snapshots=[("2026-07-01", 100, "in_stock")])
        rows = query_stale_candidates(db, TODAY, stale_days=7)
        assert rows == []

    def test_delisted_listing_is_never_a_candidate(self, db):
        _seed_listing(db, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _seed_listing(
            db, url="https://s/gone", status="delisted",
            snapshots=[("2026-08-09", 100, "in_stock")],
        )
        rows = query_stale_candidates(db, TODAY, stale_days=7)
        assert rows == []

    def test_listing_seen_today_is_not_a_candidate(self, db):
        _seed_listing(db, url="https://s/1", snapshots=[(TODAY, 100, "in_stock")])
        rows = query_stale_candidates(db, TODAY, stale_days=7)
        assert rows == []

    def test_no_listings_at_all_returns_empty(self, db):
        assert query_stale_candidates(db, TODAY, stale_days=7) == []


# ── run ──────────────────────────────────────────────────────────────

class TestRun:
    def test_marks_stale_candidate(self, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _, lid = _seed_listing(conn, url="https://s/stale", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        stats = run(db_path=str(db_path), today=TODAY, stale_days=7)
        assert stats["stale"] == 1
        assert _status(db_path, lid) == "stale"

    def test_retailer_with_no_recent_data_leaves_listings_active(self, db_path):
        conn = sqlite3.connect(str(db_path))
        _, lid = _seed_listing(conn, url="https://s/1", snapshots=[("2026-07-01", 100, "in_stock")])
        conn.close()

        stats = run(db_path=str(db_path), today=TODAY, stale_days=7)
        assert stats["stale"] == 0
        assert _status(db_path, lid) == "active"

    def test_dry_run_does_not_write(self, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _, lid = _seed_listing(conn, url="https://s/stale", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        stats = run(db_path=str(db_path), today=TODAY, stale_days=7, dry_run=True)
        assert stats["stale"] == 1
        assert _status(db_path, lid) == "active"

    def test_idempotent(self, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _seed_listing(conn, url="https://s/stale", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        run(db_path=str(db_path), today=TODAY, stale_days=7)
        stats2 = run(db_path=str(db_path), today=TODAY, stale_days=7)
        assert stats2["stale"] == 0

    def test_never_deletes_rows(self, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/fresh", snapshots=[(TODAY, 100, "in_stock")])
        _seed_listing(conn, url="https://s/stale", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        before = _count_listings(db_path)
        run(db_path=str(db_path), today=TODAY, stale_days=7)
        after = _count_listings(db_path)
        assert before == after

    def test_noop_on_empty_db(self, db_path):
        stats = run(db_path=str(db_path), today=TODAY, stale_days=7)
        assert stats["stale"] == 0
