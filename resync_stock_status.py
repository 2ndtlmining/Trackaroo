"""
Resync PCCG stock_status values after the _map_stock_label() fix.

The buggy PCCG scraper (before 13-Aug-2026) marked every product as
'in_stock' regardless of actual stock state. The fix introduced
_map_stock_label() which correctly maps "Sold Out", "ETA: ...", and
"Stock at Supplier" labels.

This script compares the buggy and fixed JSON files for a given date,
identifies rows where stock_status was wrong in the DB, and updates them.

Usage:
    python resync_stock_status.py --dry-run          # Preview changes only
    python resync_stock_status.py --date 2026-08-13  # Resync specific date
    python resync_stock_status.py                     # Apply fixes (default: 13-Aug)

Safety:
    - Only affects PCCG rows for the specified date
    - Supports --dry-run to preview without writing
    - Idempotent: safe to re-run on the same data
    - Does NOT touch Scorptec data or other dates
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR, DB_DATE_FORMAT, DB_PATH, FILE_DATE_FORMAT

# Backwards-compatible aliases (module-level names kept for tests/scripts)
DATE_FILE_FORMAT = FILE_DATE_FORMAT
DATE_DB_FORMAT = DB_DATE_FORMAT

LOGGER = logging.getLogger(__name__)


def _date_components(target_date: str) -> tuple[str, str]:
    """Convert a DB date (YYYY-MM-DD) to the filename component (DD_Month_YYYY).

    Returns (db_date, file_date) tuple.
    """
    from datetime import datetime
    dt = datetime.strptime(target_date, DATE_DB_FORMAT)
    file_date = dt.strftime(DATE_FILE_FORMAT)
    return target_date, file_date


def _load_json_pair(category: str, file_date: str) -> tuple[Optional[list], Optional[list]]:
    """Load both buggy and fixed JSON for a category/date.

    Returns (buggy_products, fixed_products) or (None, None) if files missing.
    """
    buggy_path = DATA_DIR / f"{category}_pccg_{file_date}.backup_buggy.json"
    fixed_path = DATA_DIR / f"{category}_pccg_{file_date}.json"

    buggy = None
    fixed = None

    if buggy_path.exists():
        with open(buggy_path, encoding="utf-8") as f:
            buggy = json.load(f).get("products", [])
    else:
        LOGGER.warning("Buggy file not found: %s", buggy_path)

    if fixed_path.exists():
        with open(fixed_path, encoding="utf-8") as f:
            fixed = json.load(f).get("products", [])
    else:
        LOGGER.warning("Fixed file not found: %s", fixed_path)

    return buggy, fixed


def _build_status_diff(
    buggy_products: list[Dict[str, Any]],
    fixed_products: list[Dict[str, Any]],
) -> Dict[str, str]:
    """Compare buggy and fixed JSON, return {url: new_status} for changed rows.

    Only includes products where stock_status actually changed.
    """
    # Build lookup by URL for fixed products
    fixed_by_url: Dict[str, str] = {}
    for p in fixed_products:
        url = p.get("url", "")
        status = p.get("stock_status", "unknown")
        if url:
            fixed_by_url[url] = status

    changed: Dict[str, str] = {}
    for p in buggy_products:
        url = p.get("url", "")
        old_status = p.get("stock_status", "unknown")
        if url and url in fixed_by_url:
            new_status = fixed_by_url[url]
            if old_status != new_status:
                changed[url] = new_status

    return changed


def resync(
    conn: sqlite3.Connection,
    target_date: str,
    dry_run: bool = False,
) -> int:
    """Resync stock_status for PCCG rows on the target date.

    Compares buggy vs fixed JSON for both CPU and GPU, identifies rows
    where stock_status was incorrect, and updates them.

    Returns the number of rows that would be (or were) updated.
    """
    _, file_date = _date_components(target_date)

    total_changes = 0
    all_changes: Dict[str, str] = {}

    for category in ("cpu", "gpu"):
        buggy, fixed = _load_json_pair(category, file_date)
        if buggy is None or fixed is None:
            LOGGER.warning("Skipping %s — JSON pair not found for %s", category, file_date)
            continue

        diff = _build_status_diff(buggy, fixed)
        LOGGER.info("%s: %d products changed stock_status", category.upper(), len(diff))
        all_changes.update(diff)

    if not all_changes:
        LOGGER.info("No stock_status changes detected. Nothing to resync.")
        return 0

    # Now find and update the corresponding DB rows
    cursor = conn.execute("""
        SELECT ps.id, ps.stock_status, rl.listing_url
        FROM price_snapshots ps
        JOIN retailer_listings rl ON ps.retailer_listing_id = rl.id
        WHERE rl.retailer = 'pccg' AND ps.snapshot_date = ?
    """, (target_date,))

    rows_by_url: Dict[str, tuple] = {}
    for row_id, old_status, url in cursor.fetchall():
        if url:
            rows_by_url[url] = (row_id, old_status)

    updates = 0
    for url, new_status in all_changes.items():
        if url in rows_by_url:
            row_id, old_status = rows_by_url[url]
            if old_status == new_status:
                continue  # Already correct (shouldn't happen, but defensive)
            updates += 1
            if dry_run:
                LOGGER.info(
                    "DRY-RUN: Would update snapshot id=%d, url=%s, %s -> %s",
                    row_id, url, old_status, new_status,
                )
            else:
                conn.execute(
                    "UPDATE price_snapshots SET stock_status = ? WHERE id = ?",
                    (new_status, row_id),
                )
                LOGGER.debug(
                    "Updated snapshot id=%d, %s -> %s",
                    row_id, old_status, new_status,
                )
        else:
            LOGGER.warning("No DB row found for URL: %s", url)

    if not dry_run and updates > 0:
        conn.commit()

    LOGGER.info(
        "%s: %d rows %s for date %s",
        "DRY-RUN" if dry_run else "APPLIED",
        updates,
        "would be updated" if dry_run else "updated",
        target_date,
    )

    return updates


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Resync PCCG stock_status after the _map_stock_label() fix",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing to the database",
    )
    parser.add_argument(
        "--date", type=str, default="2026-08-13",
        help="Target date in YYYY-MM-DD format (default: 2026-08-13)",
    )
    args = parser.parse_args(argv)

    LOGGER.info("Database: %s", DB_PATH)
    LOGGER.info("Target date: %s", args.date)
    LOGGER.info("Mode: %s", "DRY-RUN" if args.dry_run else "APPLY")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        changes = resync(conn, args.date, dry_run=args.dry_run)
        if changes == 0:
            LOGGER.info("No changes needed.")
            sys.exit(0)
        else:
            if args.dry_run:
                LOGGER.info("Dry-run complete. %d rows would be updated.", changes)
            else:
                LOGGER.info("Resync complete. %d rows updated.", changes)
    except Exception as e:
        LOGGER.error("Resync failed: %s", e)
        if not args.dry_run:
            conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
