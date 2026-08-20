"""
Detect Scorptec listings that have been delisted ("No Longer Available").

The Scorptec scraper only reads the category-grid pages. When a product is
delisted it disappears from the grid entirely, so no new snapshot is ever
written and the last one (often in_stock) stays the latest forever — the
dashboard keeps showing a stale "In stock" state.

This module closes that gap: it fetches the product page of every active
Scorptec listing that produced no snapshot for today (i.e. is missing from
the latest grid scrape) and checks for the site's "No Longer Available"
marker (or a 404/410 response). Confirmed delistings are marked via
``retailer_listings.status = 'delisted'``, which the dashboard uses to stop
presenting the listing as buyable.

Only a positive delisting signal marks a listing — a fetch failure or an
unrecognised page leaves the listing untouched, so a transient network issue
can never delist a live product.

Configuration (env, optional — see .env.example):

    TRACKAROO_SCORPTEC_DELIST_CHECK_MAX  Max listing pages to fetch per run
                                         (default: 100)
    TRACKAROO_SCORPTEC_DELIST_PAGE_DELAY Delay between listing fetches in
                                         seconds (default: 1.5 — a burst of
                                         product-page requests gets throttled
                                         by the CDN)

Usage:
    python check_delisted.py             # Check listings missing from today's scrape
    python check_delisted.py --all       # Check every active Scorptec listing
    python check_delisted.py --dry-run   # Print what would be marked, without writing
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

import requests

from config import (
    DB_PATH,
    SCORPTEC_DELIST_CHECK_MAX,
    SCORPTEC_DELIST_PAGE_DELAY,
    SCORPTEC_RETRY_DELAY,
    SCORPTEC_TIMEOUT_SECONDS,
)
from notify_discord import load_dotenv
from scraper.scorptec import HEADERS

LOGGER = logging.getLogger(__name__)

# Scorptec renders delisted product pages with a "No Longer Available"
# promotion banner (and removes the price / buy controls). Matching the text
# case-insensitively is the most robust signal — the surrounding class names
# are mangled (e.g. 'rb-bg-no longer available') and not worth coupling to.
DELISTED_MARKER = "no longer available"

# HTTP responses that mean the product page itself is gone.
GONE_STATUS_CODES = (404, 410)

# Throttling / transient server errors: worth a retry, but never a delisting
# signal. The CDN rate-limits bursts of product-page requests.
RETRYABLE_STATUS_CODES = (403, 429, 500, 502, 503, 504)


def fetch_listing(url: str, retries: int = 2) -> Tuple[Optional[int], Optional[str]]:
    """Fetch a Scorptec product page.

    Args:
        url: Product page URL.
        retries: Number of retry attempts after the initial try.

    Returns:
        (status_code, html) — (None, None) when every attempt failed.
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=SCORPTEC_TIMEOUT_SECONDS)
            if r.status_code in RETRYABLE_STATUS_CODES and attempt < retries:
                LOGGER.warning(
                    "Attempt %d got HTTP %d for %s — retrying", attempt + 1, r.status_code, url
                )
                time.sleep(SCORPTEC_RETRY_DELAY)
                continue
            return r.status_code, r.text
        except requests.RequestException as e:
            LOGGER.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
            time.sleep(SCORPTEC_RETRY_DELAY)
    return None, None


def classify_page(status_code: Optional[int], html: Optional[str]) -> str:
    """Classify a fetched product page.

    Args:
        status_code: HTTP status of the fetch (None on network failure).
        html: Response body (None on network failure).

    Returns:
        'delisted' when the page is gone (404/410) or carries the
        "No Longer Available" marker; 'active' for a normal 200 page;
        'unknown' for anything else (network failure, other status) —
        callers must leave 'unknown' listings untouched.
    """
    if status_code is None or html is None:
        return "unknown"
    if status_code in GONE_STATUS_CODES:
        return "delisted"
    if status_code == 200:
        if DELISTED_MARKER in html.lower():
            return "delisted"
        return "active"
    return "unknown"


def query_check_listings(
    conn: sqlite3.Connection, today: str, check_all: bool = False
) -> List[Tuple[int, str, str]]:
    """List active Scorptec listings to check.

    Args:
        conn: Open SQLite connection.
        today: Snapshot date string ('YYYY-MM-DD') that counts as "present in
            the latest scrape".
        check_all: When False (default), only listings with no snapshot for
            ``today`` are returned — the suspicious set. When True, every
            active Scorptec listing is returned.

    Returns:
        List of (listing_id, variant_name, listing_url) tuples.
    """
    sql = (
        "SELECT l.id, l.variant_name, l.listing_url "
        "FROM retailer_listings l "
        "JOIN products p ON p.id = l.product_id "
        "WHERE l.retailer = 'scorptec' AND l.status = 'active' AND p.tracked = 1"
    )
    if not check_all:
        sql += (
            " AND NOT EXISTS ("
            "  SELECT 1 FROM price_snapshots s "
            "  WHERE s.retailer_listing_id = l.id AND s.snapshot_date = ?"
            ")"
        )
    sql += " ORDER BY l.id"
    params: Tuple = (today,) if not check_all else ()
    return conn.execute(sql, params).fetchall()


def run(
    db_path: Optional[str] = None,
    dry_run: bool = False,
    check_all: bool = False,
    today: Optional[str] = None,
    fetch=fetch_listing,
    sleep=time.sleep,
) -> Dict[str, int]:
    """Check stale Scorptec listings and mark confirmed delistings.

    Args:
        db_path: SQLite DB path (default: config.DB_PATH).
        dry_run: When True, report what would be marked without writing.
        check_all: Check every active Scorptec listing, not just the stale ones.
        today: Snapshot date that counts as "present" (default: real today).
        fetch: (url) -> (status_code, html) callable; injectable for tests.
        sleep: seconds-sleeper; injectable for tests.

    Returns:
        Stats dict: checked / delisted / active / unknown / skipped_cap.
    """
    load_dotenv()
    stats = {"checked": 0, "delisted": 0, "active": 0, "unknown": 0, "skipped_cap": 0}
    if today is None:
        today = date.today().isoformat()

    conn = sqlite3.connect(db_path or str(DB_PATH))
    try:
        rows = query_check_listings(conn, today, check_all=check_all)
        if not rows:
            LOGGER.info("No Scorptec listings to check.")
            return stats

        if len(rows) > SCORPTEC_DELIST_CHECK_MAX:
            stats["skipped_cap"] = len(rows) - SCORPTEC_DELIST_CHECK_MAX
            rows = rows[:SCORPTEC_DELIST_CHECK_MAX]
            LOGGER.warning(
                "Checking %d of %d stale listings (cap TRACKAROO_SCORPTEC_DELIST_CHECK_MAX=%d).",
                len(rows),
                len(rows) + stats["skipped_cap"],
                SCORPTEC_DELIST_CHECK_MAX,
            )

        for i, (listing_id, variant_name, url) in enumerate(rows):
            if i > 0:
                sleep(SCORPTEC_DELIST_PAGE_DELAY)  # Be polite between product pages
            status_code, html = fetch(url)
            verdict = classify_page(status_code, html)
            stats[verdict if verdict in stats else "unknown"] += 1
            stats["checked"] += 1
            label = variant_name or f"listing {listing_id}"
            if verdict == "delisted":
                LOGGER.info("Delisted: %s (%s)", label, url)
                if not dry_run:
                    conn.execute(
                        "UPDATE retailer_listings SET status = 'delisted' WHERE id = ? AND status = 'active'",
                        (listing_id,),
                    )
            elif verdict == "unknown":
                LOGGER.warning("Unverifiable (left untouched): %s (%s)", label, url)

        if not dry_run:
            conn.commit()
        LOGGER.info(
            "Delisted check: %d checked, %d delisted, %d active, %d unknown (dry_run=%s)",
            stats["checked"],
            stats["delisted"],
            stats["active"],
            stats["unknown"],
            dry_run,
        )
        return stats
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Mark delisted Scorptec listings")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: config.DB_PATH)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be marked without writing")
    parser.add_argument("--all", action="store_true", help="Check every active Scorptec listing, not just stale ones")
    args = parser.parse_args(argv)
    run(db_path=args.db, dry_run=args.dry_run, check_all=args.all)


if __name__ == "__main__":
    main()
