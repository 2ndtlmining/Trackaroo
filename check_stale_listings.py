"""
Age out listings nobody has seen -- the retailer-agnostic net beneath
check_delisted.py.

check_delisted.py only watches Scorptec, and only marks 'delisted' on a
*positive* signal (a fetched product page returning 404/410, or the site's
own "No Longer Available" marker). Nothing ages out a PCCG or Umart listing
that simply stops appearing in its retailer's daily grid scrape -- it keeps
reading 'active', with whatever stock/price it last had, forever. Measured
31-Aug-2026: 13 active listings (8 pccg, 5 scorptec) had gone unseen for 7+
days and would stay 'active' indefinitely -- inflating the dashboard's
"N of M tracked" headline, exactly the overstatement that headline was built
to fix. Umart drifts fastest of the three: its category grid lists only
purchasable items, so listings churn in and out with ordinary stock changes.

This is the weaker net underneath, deliberately: no network fetch, no
positive confirmation of anything -- just "this listing stopped appearing
while its own retailer kept reporting other listings just fine."
`status = 'stale'` means exactly that ("we stopped seeing it"), distinct
from `status = 'delisted'` ("confirmed gone"). The two are never merged --
check_delisted.py stays exactly as it is.

The one rule that keeps this safe: a listing is judged against ITS OWN
RETAILER'S most recent snapshot, never against today's real-world date. If a
retailer goes quiet for a week -- PCCG's circuit-breaker cooldown is a normal
operating state, not an outage -- comparing against `today` would mark that
retailer's entire catalogue stale in one pass, a mass mistagging worse than
the problem this fixes. A listing only becomes a candidate when its own
retailer has a snapshot within STALE_LISTING_DAYS of today AND this listing
specifically was not part of it.

Configuration (env, optional -- see .env.example):

    TRACKAROO_STALE_LISTING_DAYS  Days a listing may go unseen -- while its
                                  own retailer IS being scraped -- before it
                                  is marked stale (default: 7)

Usage:
    python check_stale_listings.py             # Mark stale listings
    python check_stale_listings.py --dry-run   # Print what would be marked
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date
from typing import Dict, List, Optional, Tuple

from config import DB_PATH, STALE_LISTING_DAYS, setup_logging

LOGGER = logging.getLogger(__name__)

# A listing is a candidate only when its own retailer's latest snapshot is
# recent (the retailer is being scraped) and the listing's own latest
# snapshot is not (it has gone unseen). Both sides of that comparison use the
# same window, and both are computed in SQL via julianday() so no date
# parsing can silently disagree with what SQLite itself considers a day.
_CANDIDATES_SQL = """
    WITH retailer_latest AS (
        SELECT rl.retailer AS retailer, MAX(ps.snapshot_date) AS last_date
        FROM price_snapshots ps
        JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id
        GROUP BY rl.retailer
    ),
    listing_latest AS (
        SELECT retailer_listing_id, MAX(snapshot_date) AS last_date
        FROM price_snapshots
        GROUP BY retailer_listing_id
    )
    SELECT l.id, l.retailer, l.variant_name, l.listing_url, ll.last_date AS listing_last_seen
    FROM retailer_listings l
    JOIN products p ON p.id = l.product_id
    JOIN retailer_latest rt ON rt.retailer = l.retailer
    LEFT JOIN listing_latest ll ON ll.retailer_listing_id = l.id
    WHERE l.status = 'active' AND p.tracked = 1
      AND julianday(:today) - julianday(rt.last_date) <= :stale_days
      AND (ll.last_date IS NULL OR julianday(:today) - julianday(ll.last_date) > :stale_days)
    ORDER BY l.id
"""


def query_stale_candidates(
    conn: sqlite3.Connection, today: str, stale_days: int
) -> List[Tuple[int, str, Optional[str], str, Optional[str]]]:
    """List active listings whose retailer is current but which have gone
    unseen for more than ``stale_days``.

    A listing is a candidate only when its OWN retailer has a snapshot within
    ``stale_days`` of ``today`` -- a retailer with no recent data at all
    contributes zero candidates, however long its listings have been quiet.
    That is the guard against mass-mistagging a whole catalogue stale just
    because its retailer is in a cooldown or a scraper broke.

    Args:
        conn: Open SQLite connection (row_factory=sqlite3.Row expected).
        today: Reference date 'YYYY-MM-DD'.
        stale_days: Days a listing may go unseen before it qualifies.

    Returns:
        Rows with columns (id, retailer, variant_name, listing_url,
        listing_last_seen) -- ``listing_last_seen`` is ``None`` for a listing
        with no snapshot at all.
    """
    return conn.execute(
        _CANDIDATES_SQL, {"today": today, "stale_days": stale_days}
    ).fetchall()


def run(
    db_path: Optional[str] = None,
    today: Optional[str] = None,
    stale_days: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Mark listings stale that have gone unseen while their own retailer
    stayed current. Never raises -- this is a best-effort post-ingest step.

    Args:
        db_path: SQLite DB path (default: config.DB_PATH).
        today: Reference date 'YYYY-MM-DD' (default: real today), injectable
            for tests.
        stale_days: Days a listing may go unseen (default:
            config.STALE_LISTING_DAYS).
        dry_run: When True, report what would be marked without writing.

    Returns:
        Stats dict: {"stale": N} -- listings marked (or, under dry_run, that
        would have been marked).
    """
    stats = {"stale": 0}
    if today is None:
        today = date.today().isoformat()
    if stale_days is None:
        stale_days = STALE_LISTING_DAYS

    try:
        conn = sqlite3.connect(str(db_path or DB_PATH))
    except sqlite3.Error as e:
        LOGGER.error("Stale-listing check could not open the database: %s", e)
        return stats
    conn.row_factory = sqlite3.Row

    try:
        try:
            rows = query_stale_candidates(conn, today, stale_days)
        except sqlite3.Error as e:
            LOGGER.error("Stale-listing check could not read the database: %s", e)
            return stats

        for row in rows:
            label = row["variant_name"] or f"listing {row['id']}"
            LOGGER.info(
                "Stale: %s (%s @ %s) -- last seen %s",
                label, row["retailer"], row["listing_url"],
                row["listing_last_seen"] or "never",
            )
            if not dry_run:
                conn.execute(
                    "UPDATE retailer_listings SET status = 'stale' WHERE id = ? AND status = 'active'",
                    (row["id"],),
                )
            stats["stale"] += 1

        if not dry_run:
            conn.commit()
        LOGGER.info(
            "Stale-listing check: %d marked stale (dry_run=%s, stale_days=%d)",
            stats["stale"], dry_run, stale_days,
        )
        return stats
    except Exception as e:  # noqa: BLE001 - defensive: must never break the caller
        LOGGER.error("Stale-listing check failed: %s", e)
        return stats
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Mark listings stale that have gone unseen while their retailer stayed current")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: config.DB_PATH)")
    parser.add_argument("--stale-days", type=int, default=None,
                        help=f"Days a listing may go unseen (default: {STALE_LISTING_DAYS})")
    parser.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD), for testing")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be marked without writing")
    args = parser.parse_args(argv)
    run(db_path=args.db, today=args.today, stale_days=args.stale_days, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
