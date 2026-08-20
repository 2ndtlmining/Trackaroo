"""
Tests for check_delisted.py — delisted-scoring of stale Scorptec listings.

Covers:
- classify_page (delisted marker, 404/410, active 200, unknown on failure)
- fetch_listing (success, retries then None)
- query_check_listings (stale-set selection, check_all, exclusions)
- run (marks delisted, leaves active/unknown untouched, dry-run, cap, sleep)
"""
import sqlite3
from pathlib import Path

import pytest
import requests

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_delisted import (  # noqa: E402
    classify_page,
    fetch_listing,
    query_check_listings,
    run,
)


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


def _mk_fetch(pages):
    """Build a fake fetch callable. pages maps url -> (status, html)."""

    def fake_fetch(url):
        return pages.get(url, (None, None))

    return fake_fetch


# ── classify_page ────────────────────────────────────────────────────

class TestClassifyPage:
    def test_network_failure_is_unknown(self):
        assert classify_page(None, None) == "unknown"

    def test_404_is_delisted(self):
        assert classify_page(404, "Not Found") == "delisted"

    def test_410_is_delisted(self):
        assert classify_page(410, "") == "delisted"

    def test_200_with_marker_is_delisted_case_insensitive(self):
        html = "<div class='product-promotion-text'>No Longer Available</div>"
        assert classify_page(200, html) == "delisted"

    def test_200_without_marker_is_active(self):
        assert classify_page(200, "<span data-price>1049</span>") == "active"

    def test_other_status_is_unknown(self):
        assert classify_page(500, "oops") == "unknown"

    def test_marker_requires_200(self):
        # A 503 page that happens to contain the text must not delist.
        assert classify_page(503, "No Longer Available") == "unknown"


# ── fetch_listing ────────────────────────────────────────────────────

class TestFetchListing:
    def test_success_returns_status_and_html(self, monkeypatch):
        class R:
            status_code = 200
            text = "<html>ok</html>"

        monkeypatch.setattr("check_delisted.requests.get", lambda *a, **k: R())
        assert fetch_listing("https://x", retries=0) == (200, "<html>ok</html>")

    def test_all_attempts_failed_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise requests.RequestException("down")

        monkeypatch.setattr("check_delisted.requests.get", boom)
        monkeypatch.setattr("check_delisted.time.sleep", lambda s: None)
        assert fetch_listing("https://x", retries=1) == (None, None)

    def test_retries_on_throttling_then_succeeds(self, monkeypatch):
        class R:
            def __init__(self, code, text=""):
                self.status_code = code
                self.text = text

        responses = iter([R(429), R(200, "ok")])
        monkeypatch.setattr("check_delisted.requests.get", lambda *a, **k: next(responses))
        monkeypatch.setattr("check_delisted.time.sleep", lambda s: None)
        assert fetch_listing("https://x", retries=1) == (200, "ok")

    def test_exhausted_retries_return_last_throttling_status(self, monkeypatch):
        class R:
            status_code = 429
            text = "slow down"

        monkeypatch.setattr("check_delisted.requests.get", lambda *a, **k: R())
        monkeypatch.setattr("check_delisted.time.sleep", lambda s: None)
        assert fetch_listing("https://x", retries=1) == (429, "slow down")


# ── query_check_listings ─────────────────────────────────────────────

class TestQueryCheckListings:
    def test_returns_only_stale_scorptec_listings(self, db):
        _seed_listing(db, url="https://s/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(db, url="https://s/2", snapshots=[("2026-08-20", 100, "in_stock")])
        rows = query_check_listings(db, "2026-08-20")
        assert [r[2] for r in rows] == ["https://s/1"]

    def test_excludes_pccg_untracked_and_delisted(self, db):
        _seed_listing(db, retailer="pccg", url="https://p/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(db, tracked=0, url="https://s/2", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(db, status="delisted", url="https://s/3", snapshots=[("2026-08-09", 100, "in_stock")])
        assert query_check_listings(db, "2026-08-20") == []

    def test_check_all_includes_fresh_listings(self, db):
        _seed_listing(db, url="https://s/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(db, url="https://s/2", snapshots=[("2026-08-20", 100, "in_stock")])
        rows = query_check_listings(db, "2026-08-20", check_all=True)
        assert [r[2] for r in rows] == ["https://s/1", "https://s/2"]

    def test_empty_db(self, db):
        assert query_check_listings(db, "2026-08-20") == []


# ── run ──────────────────────────────────────────────────────────────

class TestRun:
    def _run(self, monkeypatch, db_path, pages, **kw):
        monkeypatch.setattr("check_delisted.load_dotenv", lambda *a, **k: None)
        sleep_calls = []
        return run(
            db_path=str(db_path),
            fetch=_mk_fetch(pages),
            sleep=sleep_calls.append,
            today="2026-08-20",
            **kw,
        ), sleep_calls

    def _status(self, db_path, listing_id):
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status FROM retailer_listings WHERE id = ?", (listing_id,)
        ).fetchone()
        conn.close()
        return row[0]

    def test_noop_without_stale_listings(self, monkeypatch, db_path):
        stats, _ = self._run(monkeypatch, db_path, {})
        assert stats["checked"] == 0

    def test_marks_delisted_listing(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _, lid = _seed_listing(conn, snapshots=[("2026-08-09", 1049, "in_stock")])
        conn.close()

        stats, _ = self._run(
            monkeypatch,
            db_path,
            {"https://scorptec.example/1": (200, "<div>No Longer Available</div>")},
        )
        assert stats["checked"] == 1
        assert stats["delisted"] == 1
        assert self._status(db_path, lid) == "delisted"

    def test_leaves_active_listing_untouched(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _, lid = _seed_listing(conn, snapshots=[("2026-08-09", 1049, "in_stock")])
        conn.close()

        stats, _ = self._run(
            monkeypatch,
            db_path,
            {"https://scorptec.example/1": (200, "<span data-price>1049</span>")},
        )
        assert stats["active"] == 1
        assert self._status(db_path, lid) == "active"

    def test_leaves_unverifiable_listing_untouched(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _, lid = _seed_listing(conn, snapshots=[("2026-08-09", 1049, "in_stock")])
        conn.close()

        stats, _ = self._run(monkeypatch, db_path, {})  # fetch fails for every url
        assert stats["unknown"] == 1
        assert self._status(db_path, lid) == "active"

    def test_dry_run_does_not_write(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _, lid = _seed_listing(conn, snapshots=[("2026-08-09", 1049, "in_stock")])
        conn.close()

        stats, _ = self._run(
            monkeypatch,
            db_path,
            {"https://scorptec.example/1": (404, "gone")},
            dry_run=True,
        )
        assert stats["delisted"] == 1
        assert self._status(db_path, lid) == "active"

    def test_makes_a_polite_delay_between_fetches(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(conn, url="https://s/2", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        _, sleep_calls = self._run(monkeypatch, db_path, {})
        assert len(sleep_calls) == 1  # delay before the 2nd fetch only

    def test_cap_limits_fetches(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(conn, url="https://s/2", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(conn, url="https://s/3", snapshots=[("2026-08-09", 100, "in_stock")])
        conn.close()

        monkeypatch.setattr("check_delisted.SCORPTEC_DELIST_CHECK_MAX", 2)
        stats, _ = self._run(monkeypatch, db_path, {})
        assert stats["checked"] == 2
        assert stats["skipped_cap"] == 1

    def test_check_all_includes_fresh_listings(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, url="https://s/1", snapshots=[("2026-08-09", 100, "in_stock")])
        _seed_listing(conn, url="https://s/2", snapshots=[("2026-08-20", 100, "in_stock")])
        conn.close()

        stats, _ = self._run(monkeypatch, db_path, {}, check_all=True)
        assert stats["checked"] == 2
