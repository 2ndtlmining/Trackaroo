"""Pipeline bookkeeping tables shared with the dashboard.

- active_retailers: which retailers the pipeline scrapes (R1).
- scrape_runs: one row per scraper run (#8 retry state, R3 freshness).
- run_markers: once-per-day claims (#8: no repeated digest or alert).

Every helper calls ensure_ops_tables first, so a DB that has not been through
migrate.py yet (a native run straight after `git pull`) still works. The DDL
itself lives in migrate.py and db/schema.sql -- never here.
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence

from migrate import (
    check_table_exists,
    migrate_add_active_retailers_table,
    migrate_add_run_markers_table,
    migrate_add_scrape_runs_table,
)


def ensure_ops_tables(conn: sqlite3.Connection) -> None:
    """Create any missing bookkeeping table. Idempotent and quiet when present."""
    for table, create in (
        ("active_retailers", migrate_add_active_retailers_table),
        ("scrape_runs", migrate_add_scrape_runs_table),
        ("run_markers", migrate_add_run_markers_table),
    ):
        if not check_table_exists(conn, table):
            create(conn)


def sync_active_retailers(conn: sqlite3.Connection, retailers: Sequence[str]) -> None:
    """Make active_retailers hold exactly ``retailers``, in order.

    Only the bookkeeping rows are replaced; no price data is touched.
    """
    ensure_ops_tables(conn)
    conn.execute("DELETE FROM active_retailers")
    conn.executemany(
        "INSERT INTO active_retailers (retailer, position) VALUES (?, ?)",
        [(r, i) for i, r in enumerate(retailers)],
    )
    conn.commit()


def record_scrape_run(
    conn: sqlite3.Connection,
    *,
    retailer: str,
    run_date: str,
    started_at: str,
    finished_at: str,
    status: str,
    exit_code: Optional[int] = None,
    matched: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Append one scrape_runs row. The caller commits."""
    ensure_ops_tables(conn)
    conn.execute(
        "INSERT INTO scrape_runs (retailer, run_date, started_at, finished_at, status, "
        "exit_code, matched, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (retailer, run_date, started_at, finished_at, status, exit_code, matched, detail),
    )


def retailers_pending(conn: sqlite3.Connection, run_date: str, retailers: Sequence[str]) -> List[str]:
    """Retailers that still need a scrape on ``run_date`` (#8), in the given order.

    A retailer is done when its latest scrape_runs row for the day is 'ok'.
    Any other latest status -- degraded, skipped, auth, failed, timeout --
    leaves it pending. With no row for the day, it is done only if it already
    has snapshots for the day: that is the day a build without scrape_runs
    did the scraping (the Phase 6 deploy day), and re-scraping it would only
    spend retailer goodwill (Review Focus 3).
    """
    ensure_ops_tables(conn)
    pending: List[str] = []
    for retailer in retailers:
        row = conn.execute(
            "SELECT status FROM scrape_runs WHERE retailer = ? AND run_date = ? "
            "ORDER BY id DESC LIMIT 1",
            (retailer, run_date),
        ).fetchone()
        if row is not None:
            if row[0] != "ok":
                pending.append(retailer)
            continue
        has_data = conn.execute(
            "SELECT 1 FROM price_snapshots ps "
            "JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id "
            "WHERE rl.retailer = ? AND ps.snapshot_date = ? LIMIT 1",
            (retailer, run_date),
        ).fetchone()
        if not has_data:
            pending.append(retailer)
    return pending


def claim_marker(conn: sqlite3.Connection, name: str, run_date: str) -> bool:
    """Claim ``name`` for ``run_date``. True only the first time that day."""
    ensure_ops_tables(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO run_markers (name, run_date) VALUES (?, ?)", (name, run_date)
    )
    conn.commit()
    return cur.rowcount == 1


def release_marker(conn: sqlite3.Connection, name: str, run_date: str) -> None:
    """Release a marker claimed for ``name``/``run_date`` (F2 controller ruling).

    Used when a claimed send (digest or pipeline alert) turned out to fail:
    the claim must not stick, or the next hourly retry would silently skip a
    resend of something that was never actually delivered.
    """
    ensure_ops_tables(conn)
    conn.execute("DELETE FROM run_markers WHERE name = ? AND run_date = ?", (name, run_date))
    conn.commit()
