"""
Query performance tests.

The frontend will poll "latest prices for all listings" and "biggest movers"
on page load. These tests seed a synthetic bulk DB (~333 listings x 30 days,
close to the real 333-listing DB once history accumulates) and assert the
dashboard queries complete well under a generous wall-clock bound — strict
enough to catch a pathological regression (e.g. an accidental full-cartesian
join), loose enough to never flake on a shared CI box.

Also asserts the per-product history path uses the covering snapshot index
(rather than a scan), which is what "price history for this product" — the
frontend's most common query — rides on.
"""
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

from query import get_connection, show_biggest_movers, show_latest_prices

PRODUCT_COUNT = 60
LISTING_COUNT = 333
HISTORY_DAYS = 30
PERF_BOUND_SECONDS = 2.0


def _build_synthetic_db(db_path: Path) -> None:
    """Populate the temp DB with products, listings, and 30 days of snapshots."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    for i in range(PRODUCT_COUNT):
        category = "gpu" if i % 2 else "cpu"
        brand = "NVIDIA" if category == "gpu" else "AMD"
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 1)",
            (category, brand, f"Synthetic Product {i:03d}"),
        )

    listing_ids = []
    for i in range(LISTING_COUNT):
        product_id = (i % PRODUCT_COUNT) + 1
        cur = conn.execute(
            "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
            "VALUES (?, 'scorptec', ?, ?, 'active')",
            (product_id, f"Variant {i:03d}", f"https://x.com/{i:04d}"),
        )
        listing_ids.append(cur.lastrowid)

    base_date = date(2026, 6, 1)
    rows = []
    for day in range(HISTORY_DAYS):
        date_str = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
        for lid in listing_ids:
            price = 500.0 + (lid % 100) + (day % 5) * 2.0
            rows.append((lid, date_str, price, "in_stock"))

    conn.executemany(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


class TestBulkQueryPerformance:
    def test_latest_prices_under_bound(self, db_path):
        """Latest-prices-for-all query completes quickly at ~10k snapshots."""
        _build_synthetic_db(db_path)
        conn = get_connection(db_path)
        try:
            start = time.perf_counter()
            show_latest_prices(conn)
            elapsed = time.perf_counter() - start
        finally:
            conn.close()
        assert elapsed < PERF_BOUND_SECONDS, (
            f"show_latest_prices took {elapsed:.2f}s (> {PERF_BOUND_SECONDS}s)"
        )

    def test_biggest_movers_under_bound(self, db_path):
        """Biggest-movers query completes quickly at ~10k snapshots."""
        _build_synthetic_db(db_path)
        conn = get_connection(db_path)
        try:
            start = time.perf_counter()
            show_biggest_movers(conn)
            elapsed = time.perf_counter() - start
        finally:
            conn.close()
        assert elapsed < PERF_BOUND_SECONDS, (
            f"show_biggest_movers took {elapsed:.2f}s (> {PERF_BOUND_SECONDS}s)"
        )

    def test_history_query_uses_indexes(self, db_path):
        """The per-product history path must use both indexes, never a scan.

        Guards against a future migration dropping/renaming an index, which
        would silently turn the frontend's most common query into a full scan.
        (Full covering index for price_aud is a documented, measured
        non-issue at this scale — see DECISIONS.md.)
        """
        _build_synthetic_db(db_path)
        conn = get_connection(db_path)
        try:
            plan = conn.execute("EXPLAIN QUERY PLAN " + """
                SELECT s.snapshot_date, s.price_aud
                FROM price_snapshots s
                JOIN retailer_listings l ON s.retailer_listing_id = l.id
                WHERE l.product_id = 1
                ORDER BY s.snapshot_date
            """).fetchall()
        finally:
            conn.close()

        detail = " ".join(row[3] for row in plan)
        assert "USING COVERING INDEX idx_retailer_listings_product" in detail, detail
        assert "USING INDEX idx_snapshots_listing_date" in detail, detail
        assert "SCAN" not in detail, detail