"""Pipeline bookkeeping tables shared with the dashboard.

- active_retailers: which retailers the pipeline scrapes (R1).

Every helper calls ensure_ops_tables first, so a DB that has not been through
migrate.py yet (a native run straight after `git pull`) still works. The DDL
itself lives in migrate.py and db/schema.sql -- never here.
"""
from __future__ import annotations

import sqlite3
from typing import Sequence

from migrate import check_table_exists, migrate_add_active_retailers_table


def ensure_ops_tables(conn: sqlite3.Connection) -> None:
    """Create any missing bookkeeping table. Idempotent and quiet when present."""
    if not check_table_exists(conn, "active_retailers"):
        migrate_add_active_retailers_table(conn)


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
