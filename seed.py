"""
Seed the Trackaroo database from db/watchlist.csv.

Usage:
    python seed.py              # Seed (or re-seed) the production DB at db/trackaroo.db
    python seed.py --dry-run    # Preview what would be inserted without writing

Reads db/watchlist.csv and populates the `products` table.
Existing products are NOT overwritten — only new rows are inserted.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_PATH, SCHEMA_PATH, WATCHLIST_PATH
from db.watchlist import load_watchlist_products, parse_spec

LOGGER = logging.getLogger(__name__)

Product = Dict[str, Any]


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

    # Check if tables already exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
    )
    if cursor.fetchone():
        # Tables exist — DB already initialized
        return conn

    # Read and execute schema
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    return conn


def load_watchlist(path: Path = WATCHLIST_PATH) -> List[Product]:
    """Load the watchlist CSV into product records for seeding.

    Args:
        path: Path to the watchlist CSV.

    Returns:
        List of product dicts shaped for the ``products`` table.
    """
    return load_watchlist_products(str(path))


def seed_products(
    conn: sqlite3.Connection,
    products: List[Product],
    dry_run: bool = False,
) -> Dict[str, int]:
    """Insert new products into the DB.

    Args:
        conn: Open SQLite connection.
        products: List of product dicts to seed.
        dry_run: When True, only report what would happen without writing.

    Returns:
        Stats dict with inserted/skipped/errors counts.
    """
    stats = {"inserted": 0, "skipped": 0, "errors": 0}

    for p in products:
        # Check if already exists (by category + brand + model)
        cursor = conn.execute(
            "SELECT id FROM products WHERE category = ? AND brand = ? AND model = ?",
            (p["category"], p["brand"], p["model"]),
        )
        if cursor.fetchone():
            stats["skipped"] += 1
            continue

        if not dry_run:
            try:
                conn.execute(
                    """INSERT INTO products
                       (category, brand, model, vram_gb, cores, generation_tier, tracked)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        p["category"],
                        p["brand"],
                        p["model"],
                        p["vram_gb"],
                        p["cores"],
                        p["generation_tier"],
                        p["tracked"],
                    ),
                )
                stats["inserted"] += 1
            except sqlite3.IntegrityError as e:
                LOGGER.error("ERROR inserting %s: %s", p["model"], e)
                stats["errors"] += 1

    if not dry_run:
        conn.commit()

    return stats


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Seed the Trackaroo database from watchlist.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args(argv)

    LOGGER.info("Watchlist: %s", WATCHLIST_PATH)
    LOGGER.info("Database:  %s", DB_PATH)
    LOGGER.info("Schema:    %s", SCHEMA_PATH)

    # Load watchlist
    products = load_watchlist(WATCHLIST_PATH)
    LOGGER.info("\n%d products in watchlist", len(products))

    # Init DB
    conn = init_db(DB_PATH)
    LOGGER.info("Database initialized at %s", DB_PATH)

    # Seed
    stats = seed_products(conn, products, dry_run=args.dry_run)

    LOGGER.info("\nResults:")
    LOGGER.info("  Inserted: %d", stats["inserted"])
    LOGGER.info("  Skipped (already exists): %d", stats["skipped"])
    LOGGER.info("  Errors: %d", stats["errors"])

    # Verify
    if not args.dry_run:
        total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        tracked = conn.execute("SELECT COUNT(*) FROM products WHERE tracked = 1").fetchone()[0]
        LOGGER.info("\nDatabase now has %d products (%d tracked)", total, tracked)

    conn.close()

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
