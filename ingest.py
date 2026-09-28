"""
Ingest scraped JSON snapshots into the Trackaroo database.

Usage:
    python ingest.py                          # Ingest all JSON files in data/
    python ingest.py --file data/cpu_scorptec_10_August_2026.json  # Single file
    python ingest.py --dry-run                # Preview without writing
    python ingest.py --date 2026-08-10        # Only files matching this date

Reads scraped JSON files from data/ and writes retailer_listings + price_snapshots
into the SQLite DB. Products are matched by (category, brand, model) against the
existing products table. If a product doesn't exist, it's created automatically.

Idempotent: re-running on the same file skips duplicate snapshots.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    ACTIVE_RETAILERS,
    DATA_DIR,
    DB_DATE_FORMAT,
    DB_PATH,
    FILE_DATE_FORMAT,
    SCHEMA_PATH,
    setup_logging,
)

LOGGER = logging.getLogger(__name__)

Stats = Dict[str, int]

# Snapshot files follow '{cpu|gpu}_{retailer}_{day}_{Month}_{year}.json', for
# the retailers we actually scrape -- a file naming a retailer with no scraper
# is malformed, not something to ingest.
# data/ also holds non-snapshot JSON (spec_sync_report.json, pccg_cooldown.json,
# *.backup*.json archives) — those must never be ingested.
_SNAPSHOT_FILENAME_RE = re.compile(
    r"^(?:cpu|gpu)_(?:" + "|".join(ACTIVE_RETAILERS) + r")_\d{1,2}_\w+_\d{4}\.json$"
)


def is_snapshot_file(filename: str) -> bool:
    """True if the filename follows the snapshot naming convention."""
    return bool(_SNAPSHOT_FILENAME_RE.match(filename))


# Retailers rewrite URL slugs over time (Scorptec: '/{sku}' vs
# '/{sku}-{model-slug}'; PCCG: '/products/{id}' vs '/products/{id}/{slug}').
# The numeric SKU/id at the end of the path is stable across those rewrites,
# so it is the reliable identity for a listing — matching on it stops a slug
# change from forking a duplicate listing row. Scorptec SKUs are 5-6 digits
# (a shorter digit run is a model number, not a listing key); PCCG ids are 5+.
_LISTING_KEY_PATTERNS: Dict[str, str] = {
    "scorptec": r"/(\d{5,7})(?:-[^/]*)?$",
    "pccg": r"/products/(\d+)(?:/|$)",
    # Umart product URLs end in the numeric id that the grid also exposes as
    # `data-id`, e.g. /product/asus-dual-geforce-rtx-5060-...-95655
    "umart": r"/product/.*-(\d+)$",
}


def extract_listing_key(retailer: str, url: str) -> Optional[str]:
    """Extract a retailer's stable numeric listing key from a product URL.

    Args:
        retailer: Retailer name, e.g. 'scorptec', 'pccg' or 'umart'.
        url: Full listing URL.

    Returns:
        The stable numeric SKU/id, or None when the URL carries no extractable
        key (then the listing can only be identified by its exact URL).
    """
    pattern = _LISTING_KEY_PATTERNS.get(retailer)
    if not pattern:
        return None
    m = re.search(pattern, url)
    return m.group(1) if m else None


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create the database and tables if they don't exist.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open connection with foreign keys enabled.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
    )
    if not cursor.fetchone():
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()

    return conn


def parse_date_from_filename(filename: str) -> str:
    """Extract the snapshot date from a filename like cpu_scorptec_10_August_2026.json.

    Args:
        filename: JSON filename to parse.

    Returns:
        A YYYY-MM-DD string, or empty string if parsing fails.
    """
    stem = Path(filename).stem  # e.g., "cpu_scorptec_10_August_2026"
    parts = stem.split("_")  # ["cpu", "scorptec", "10", "August", "2026"]
    if len(parts) >= 3:
        date_str = "_".join(parts[-3:])  # "10_August_2026"
        try:
            dt = datetime.strptime(date_str, FILE_DATE_FORMAT)
            return dt.strftime(DB_DATE_FORMAT)
        except ValueError:
            pass
    return ""


def find_or_create_product(
    conn: sqlite3.Connection,
    product_data: Dict[str, Any],
    dry_run: bool = False,
) -> Optional[int]:
    """Find existing product or create new one.

    Args:
        conn: Open SQLite connection.
        product_data: Scraped product dict.
        dry_run: When True, don't write new products.

    Returns:
        product_id, or None in dry_run mode if the product doesn't exist.
    """
    category = product_data.get("watchlist_category", "")
    brand = product_data.get("watchlist_brand", "")
    model = product_data.get("watchlist_model", "")

    cursor = conn.execute(
        "SELECT id FROM products WHERE category = ? AND brand = ? AND model = ?",
        (category, brand, model),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    if dry_run:
        return None  # Don't create in dry-run mode

    # Product doesn't exist — create it from watchlist data
    gen_tier = product_data.get("watchlist_gen_tier", "current")
    # Try to get cores/vram from the product data if available
    cores = None
    vram_gb = None
    if category == "cpu":
        cores = product_data.get("cores")
    elif category == "gpu":
        vram_gb = product_data.get("vram_gb")

    conn.execute(
        """INSERT INTO products (category, brand, model, vram_gb, cores, generation_tier, tracked)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (category, brand, model, vram_gb, cores, gen_tier, 1),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _find_listing_by_key(
    conn: sqlite3.Connection,
    retailer: str,
    key: str,
    active_only: bool = False,
) -> Optional[Tuple[int, str]]:
    """Find an existing listing row for ``key``.

    New rows store ``retailer_sku`` (= the key); older rows predate that and
    are matched by extracting the key from their URL. ``active_only`` prefers
    live rows so a previously-merged duplicate isn't resurrected by a slug
    rewrite.

    Args:
        conn: Open SQLite connection.
        retailer: Retailer name.
        key: Stable numeric listing key.
        active_only: When True, only consider active listings.

    Returns:
        (listing_id, variant_name) tuple, or None.
    """
    status_sql = " AND status = 'active'" if active_only else ""
    row = conn.execute(
        f"SELECT id, variant_name FROM retailer_listings WHERE retailer = ? AND retailer_sku = ?{status_sql}",
        (retailer, key),
    ).fetchone()
    if row:
        return (row[0], row[1])

    rows = conn.execute(
        f"SELECT id, variant_name, listing_url FROM retailer_listings WHERE retailer = ? AND retailer_sku IS NULL{status_sql}",
        (retailer,),
    ).fetchall()
    for rid, rname, rurl in rows:
        if extract_listing_key(retailer, rurl) == key:
            return (rid, rname)
    return None


def _snapshot_is_current(
    conn: sqlite3.Connection, listing_id: int, snapshot_date: Optional[str]
) -> bool:
    """True when `snapshot_date` is at least as new as this listing's newest data.

    An unknown date is treated as current, so callers that do not pass one keep
    the previous behaviour rather than silently never reactivating.
    """
    if snapshot_date is None:
        return True
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM price_snapshots WHERE retailer_listing_id = ?",
        (listing_id,),
    ).fetchone()
    latest = row[0] if row else None
    return latest is None or snapshot_date >= latest


def find_or_create_listing(
    conn: sqlite3.Connection,
    product_id: int,
    retailer: str,
    url: str,
    variant_name: Optional[str] = None,
    dry_run: bool = False,
    snapshot_date: Optional[str] = None,
) -> Optional[int]:
    """Find existing retailer listing or create new one.

    Each unique URL at a retailer gets its own listing. This allows tracking
    multiple variants of the same product (e.g., GIGABYTE, ASUS, Zotac 5090).

    When the exact URL is new but an existing listing for the same retailer
    carries the same stable numeric key (Scorptec/PCCG rewrite URL slugs over
    time, e.g. '/116356' vs '/116356-ne63050018je-1072f'), the existing row is
    reused and adopts the new URL rather than forking a duplicate listing.

    Args:
        conn: Open SQLite connection.
        product_id: ID of the product the listing belongs to.
        retailer: Retailer name.
        url: Listing URL (unique per listing).
        variant_name: Display name of the variant.
        dry_run: When True, don't write new listings.

    Returns:
        listing_id, or None in dry_run mode if the listing doesn't exist.
    """
    # Check by retailer + URL (each URL = one listing, regardless of product mapping)
    cursor = conn.execute(
        "SELECT id, variant_name FROM retailer_listings WHERE retailer = ? AND listing_url = ?",
        (retailer, url),
    )
    row = cursor.fetchone()
    if row:
        # If variant_name is missing, backfill it from the scraped data
        if not row[1] and variant_name:
            if not dry_run:
                conn.execute(
                    "UPDATE retailer_listings SET variant_name = ? WHERE id = ?",
                    (variant_name, row[0]),
                )
        # This URL appears in the snapshot being ingested, so if the listing had
        # been retired (a delisted listing that was relisted) bring it back --
        # but only when the snapshot is not older than what we already hold.
        #
        # Without that guard an old file undoes a delisting, and a full
        # re-ingest is a supported operation (CLAUDE.md: "the DB must be
        # rebuildable from them via ingest.py"). Measured on 31-Aug-2026: a bare
        # `python ingest.py` over the whole history flipped all 12 delisted and
        # 11 stale Scorptec listings back to active, because every one of them
        # still appears in the JSON from the days before it was delisted.
        if not dry_run and _snapshot_is_current(conn, row[0], snapshot_date):
            conn.execute(
                "UPDATE retailer_listings SET status = 'active' WHERE id = ? AND status != 'active'",
                (row[0],),
            )
            # Make the scraper authoritative over the matcher's current call:
            # repair_listings.py (or the previous scrape) may have filed this
            # listing under a stale product, and the matcher can also change
            # its mind as new watchlist variants are added (#1, #2). Reusing
            # the same current-snapshot guard as the reactivation above means
            # re-ingesting OLD JSON can never move a listing away from a
            # correction made after that file was written.
            conn.execute(
                "UPDATE retailer_listings SET product_id = ? WHERE id = ? AND product_id != ?",
                (product_id, row[0], product_id),
            )
        return row[0]

    # Fallback: reuse an existing listing whose URL key matches (a slug
    # rewrite of a listing we already track). Prefer an active row so a
    # merged duplicate isn't resurrected.
    key = extract_listing_key(retailer, url)
    if key:
        key_row = _find_listing_by_key(conn, retailer, key, active_only=True)
        if not key_row:
            key_row = _find_listing_by_key(conn, retailer, key)
        if key_row:
            if not dry_run:
                conn.execute(
                    "UPDATE retailer_listings SET listing_url = ?, retailer_sku = ?, status = 'active' WHERE id = ?",
                    (url, key, key_row[0]),
                )
                if variant_name and not key_row[1]:
                    conn.execute(
                        "UPDATE retailer_listings SET variant_name = ? WHERE id = ?",
                        (variant_name, key_row[0]),
                    )
                # Same re-pointing rule as the exact-URL match above, gated on
                # the same current-snapshot guard (#1, #2).
                if _snapshot_is_current(conn, key_row[0], snapshot_date):
                    conn.execute(
                        "UPDATE retailer_listings SET product_id = ? WHERE id = ? AND product_id != ?",
                        (product_id, key_row[0], product_id),
                    )
            return key_row[0]

    if dry_run:
        return None  # Don't create in dry-run mode

    conn.execute(
        """INSERT INTO retailer_listings (product_id, retailer, variant_name, retailer_sku, listing_url, status)
           VALUES (?, ?, ?, ?, ?, 'active')""",
        (product_id, retailer, variant_name, key, url),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def ingest_file(conn: sqlite3.Connection, file_path: Path, dry_run: bool = False) -> Stats:
    """Ingest a single JSON file.

    Args:
        conn: Open SQLite connection.
        file_path: Path to the JSON snapshot file.
        dry_run: When True, only report what would happen without writing.

    Returns:
        Stats dict with inserted/skipped/errors/new_products/new_listings counts.
    """
    stats = {"inserted": 0, "skipped": 0, "errors": 0, "new_products": 0, "new_listings": 0}

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", [])
    snapshot_date = parse_date_from_filename(file_path.name)

    if not snapshot_date:
        LOGGER.warning("Could not parse date from filename %s, skipping", file_path.name)
        stats["errors"] += 1
        return stats

    retailer = data.get("retailer", "unknown")

    for product_data in products:
        url = product_data.get("url", "")
        price = product_data.get("price_aud")
        stock_status = product_data.get("stock_status", "unknown")
        model = product_data.get("watchlist_model", "unknown")

        # Skip entries without essential data
        if not url or price is None:
            stats["skipped"] += 1
            continue

        try:
            # Step 1: Find or create product
            product_id = find_or_create_product(conn, product_data, dry_run=dry_run)
            if product_id is None:
                stats["skipped"] += 1
                continue

            # Step 2: Find or create retailer listing (with variant name)
            variant_name = product_data.get("scraped_name", "")
            listing_id = find_or_create_listing(conn, product_id, retailer, url,
                                                variant_name=variant_name, dry_run=dry_run,
                                                snapshot_date=snapshot_date)
            if listing_id is None:
                stats["skipped"] += 1
                continue

            # Step 3: Insert price snapshot (skip if already exists for this date)
            cursor = conn.execute(
                "SELECT id FROM price_snapshots WHERE retailer_listing_id = ? AND snapshot_date = ?",
                (listing_id, snapshot_date),
            )
            if cursor.fetchone():
                stats["skipped"] += 1
                continue

            if not dry_run:
                conn.execute(
                    """INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)
                       VALUES (?, ?, ?, ?)""",
                    (listing_id, snapshot_date, price, stock_status),
                )
                stats["inserted"] += 1

        except (sqlite3.Error, KeyError, TypeError, ValueError) as e:
            # A malformed record used to propagate and abort the whole file,
            # discarding every product after it. Count it and keep going --
            # the rest of the snapshot is still good data.
            LOGGER.error("ERROR processing %s: %s", model, e)
            stats["errors"] += 1

    if not dry_run:
        conn.commit()

    return stats


def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Ingest scraped JSON files into the Trackaroo database")
    parser.add_argument("--file", type=Path, help="Single file to ingest (default: all files in data/)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--date", type=str, help="Only ingest files matching this date (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    LOGGER.info("Database: %s", DB_PATH)

    # Collect files to process
    if args.file:
        files: List[Path] = [args.file]
    else:
        files = sorted(f for f in DATA_DIR.glob("*.json") if is_snapshot_file(f.name))

    if not files:
        LOGGER.info("No JSON files found to ingest.")
        return

    # Filter by date if specified
    if args.date:
        files = [f for f in files if parse_date_from_filename(f.name) == args.date]
        if not files:
            LOGGER.info("No files matching date %s", args.date)
            return

    LOGGER.info("Files to process: %d", len(files))

    # Init DB
    conn = init_db(DB_PATH)

    total_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    for file_path in files:
        date_str = parse_date_from_filename(file_path.name)
        LOGGER.info("\nProcessing: %s (date: %s)", file_path.name, date_str)
        stats = ingest_file(conn, file_path, dry_run=args.dry_run)
        LOGGER.info(
            "  Inserted: %d, Skipped: %d, Errors: %d",
            stats["inserted"],
            stats["skipped"],
            stats["errors"],
        )
        total_stats["inserted"] += stats["inserted"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]

    LOGGER.info("\n%s\nTotal: %d inserted, %d skipped, %d errors", "=" * 50,
                total_stats["inserted"], total_stats["skipped"], total_stats["errors"])

    # Verify
    if not args.dry_run:
        products_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        listings_count = conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
        snapshots_count = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        LOGGER.info("\nDatabase state:")
        LOGGER.info("  Products: %d", products_count)
        LOGGER.info("  Retailer listings: %d", listings_count)
        LOGGER.info("  Price snapshots: %d", snapshots_count)

    conn.close()

    if total_stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

