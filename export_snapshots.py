"""Rebuild ``data/*.json`` snapshot files from the database.

The JSON files in ``data/`` are meant to be the durable backup: the DB is
regenerable from them via ``ingest.py``. That guarantee was broken because the
scrapers wrote snapshots unconditionally, so a rate-limited re-run could
replace a complete file with an empty one. ``scraper/snapshot_io.py`` stops
that happening again; this tool repairs the damage already done and keeps the
two in step going forward.

It reads ``price_snapshots`` and re-emits the exact envelope the scrapers
produce, so an exported file is indistinguishable from a scraped one and feeds
straight back through ``ingest.py``.

Usage:
    python export_snapshots.py --date 2026-08-21     # one day
    python export_snapshots.py --all                 # every day in the DB
    python export_snapshots.py --repair              # only days JSON under-covers
    python export_snapshots.py --all --dry-run       # report, write nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from config import DATA_DIR, DB_DATE_FORMAT, DB_PATH, FILE_DATE_FORMAT
from ingest import extract_listing_key
from scraper.snapshot_io import build_snapshot, read_snapshot

LOGGER = logging.getLogger(__name__)

# One JSON file per (category, retailer, date), matching the scrapers' layout.
_GROUP_SQL = """
SELECT p.category,
       r.retailer,
       p.brand,
       p.model,
       p.generation_tier,
       r.variant_name,
       r.listing_url,
       s.price_aud,
       s.stock_status
FROM price_snapshots s
JOIN retailer_listings r ON r.id = s.retailer_listing_id
JOIN products p ON p.id = r.product_id
WHERE s.snapshot_date = ?
ORDER BY p.category, r.retailer, p.model, r.listing_url
"""


def snapshot_dates(conn: sqlite3.Connection) -> List[str]:
    """Every distinct snapshot date in the DB, oldest first."""
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT snapshot_date FROM price_snapshots ORDER BY snapshot_date"
        )
    ]


def filename_for(category: str, retailer: str, db_date: str) -> str:
    """Snapshot filename for a group, e.g. 'gpu_pccg_21_August_2026.json'.

    Mirrors ``ingest.parse_date_from_filename``, which is what reads it back.
    """
    stamp = datetime.strptime(db_date, DB_DATE_FORMAT).strftime(FILE_DATE_FORMAT)
    return f"{category}_{retailer}_{stamp}.json"


def rows_for_date(
    conn: sqlite3.Connection, db_date: str
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Group a day's snapshots into scraper-shaped product dicts.

    Keyed by (category, retailer) — one key per output file.
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in conn.execute(_GROUP_SQL, (db_date,)):
        (category, retailer, brand, model, gen_tier,
         variant_name, url, price, stock) = row
        groups.setdefault((category, retailer), []).append({
            "watchlist_model": model,
            "watchlist_category": category,
            "watchlist_brand": brand,
            "watchlist_gen_tier": gen_tier or "current",
            "retailer": retailer,
            "scraped_name": variant_name or "",
            "price_aud": price,
            "stock_status": stock,
            "url": url,
        })
    return groups


def listing_keys(products: List[Dict[str, Any]], retailer: str) -> Set[str]:
    """Stable SKU keys for a list of scraper-shaped products.

    Compares on the SKU rather than the raw URL because retailers rewrite
    slugs, so the same listing can appear under two URLs across files.
    """
    keys: Set[str] = set()
    for product in products:
        url = product.get("url", "")
        keys.add(extract_listing_key(retailer, url) or url)
    return keys


def json_keys(path: Path, retailer: str) -> Set[str]:
    """Stable listing keys already present in a snapshot file on disk."""
    data = read_snapshot(path)
    if not data:
        return set()
    return listing_keys(data.get("products", []), retailer)


def write_snapshot(path: Path, payload: Dict[str, Any]) -> None:
    """Atomic write, same mechanics as snapshot_io but without the size guard.

    The guard is deliberately bypassed: the DB is authoritative here, and a
    repair must be able to replace a file that is larger but stale.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def export_date(
    conn: sqlite3.Connection,
    db_date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
    repair_only: bool = False,
) -> Dict[str, int]:
    """Write (or repair) every snapshot file for one date.

    Args:
        conn: Open SQLite connection.
        db_date: Date as YYYY-MM-DD.
        data_dir: Where snapshot files live.
        dry_run: Report only; write nothing.
        repair_only: Skip groups whose JSON already covers every DB listing.

    Returns:
        Counts of files written, skipped, and snapshots recovered.
    """
    stats = {"written": 0, "skipped": 0, "recovered": 0}
    groups = rows_for_date(conn, db_date)

    # A per-day watchlist total isn't stored, so the count of tracked products
    # is the closest faithful reconstruction of the scraper's field.
    total_watchlist = conn.execute(
        "SELECT COUNT(*) FROM products WHERE tracked = 1"
    ).fetchone()[0]

    for (category, retailer), products in sorted(groups.items()):
        target = data_dir / filename_for(category, retailer, db_date)
        missing = listing_keys(products, retailer) - json_keys(target, retailer)

        if repair_only and not missing:
            stats["skipped"] += 1
            continue

        stats["written"] += 1
        stats["recovered"] += len(missing)

        if dry_run:
            LOGGER.info(
                "[dry-run] %s: %d in DB, %d missing from JSON",
                target.name, len(products), len(missing),
            )
            continue

        payload = build_snapshot(
            retailer=retailer,
            scrape_date=datetime.strptime(db_date, DB_DATE_FORMAT).strftime(FILE_DATE_FORMAT),
            category=category,
            total_watchlist=total_watchlist,
            products=products,
            unmatched_models=[],
        )
        write_snapshot(target, payload)
        LOGGER.info(
            "Wrote %s (%d products, %d recovered)",
            target.name, len(products), len(missing),
        )

    return stats


def run(
    dates: Optional[List[str]] = None,
    db_path: Path = DB_PATH,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
    repair_only: bool = False,
) -> Dict[str, int]:
    """Export the given dates (default: every date in the DB)."""
    totals = {"written": 0, "skipped": 0, "recovered": 0}
    conn = sqlite3.connect(str(db_path))
    try:
        for db_date in dates or snapshot_dates(conn):
            stats = export_date(conn, db_date, data_dir, dry_run, repair_only)
            for key in totals:
                totals[key] += stats[key]
    finally:
        conn.close()
    return totals


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Rebuild data/*.json snapshots from the DB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="Single date to export (YYYY-MM-DD)")
    group.add_argument("--all", action="store_true", help="Export every date in the DB")
    group.add_argument(
        "--repair",
        action="store_true",
        help="Export only where JSON is missing listings the DB has",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args(argv)

    totals = run(
        dates=[args.date] if args.date else None,
        dry_run=args.dry_run,
        repair_only=args.repair,
    )
    LOGGER.info(
        "Done: %d file(s) written, %d up-to-date, %d snapshot(s) recovered",
        totals["written"], totals["skipped"], totals["recovered"],
    )


if __name__ == "__main__":
    main()
