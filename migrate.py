"""
Migrate the Trackaroo database.

IMPORTANT: historical-upgrade tool only. `db/schema.sql` already creates
tables with `variant_name` + the `specs` table from scratch, so a fresh
database never needs this. It exists solely to upgrade databases created
before 12-Aug-2026 (pre-`variant_name`, pre-`specs`).

Applies additive migrations:
- Adds the variant_name column to retailer_listings (backfilled from
  scraped_name data where available).
- Creates the specs table (external product spec data, see sync_specs.py).

Usage:
    python migrate.py              # Apply all pending migrations
    python migrate.py --dry-run    # Preview without writing
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

from config import DB_PATH

LOGGER = logging.getLogger(__name__)


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get a database connection.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        An open connection with foreign keys enabled and row access by name.

    Raises:
        SystemExit: If the database file does not exist.
    """
    if not db_path.exists():
        LOGGER.error("Database not found at %s. Run seed.py first.", db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def check_column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table.

    Args:
        conn: Open SQLite connection.
        table: Table name.
        column: Column name to look for.

    Returns:
        True if the column exists, False otherwise.
    """
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row["name"] for row in cursor.fetchall()]
    return column in columns


def check_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists in the database.

    Args:
        conn: Open SQLite connection.
        table: Table name.

    Returns:
        True if the table exists, False otherwise.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    )
    return cursor.fetchone() is not None


SPECS_TABLE_SQL = """
CREATE TABLE specs (
    spec_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        INTEGER NOT NULL REFERENCES products(id),
    source            TEXT    NOT NULL,               -- 'rightnow-gpu-db' | 'intel-processors-csv' | 'amd-com'
    source_record_key TEXT    NOT NULL,               -- identifying name from the source dataset, kept for traceability
    category          TEXT    NOT NULL CHECK (category IN ('cpu', 'gpu')),   -- matches products.category
    architecture      TEXT,                           -- e.g. 'Blackwell', 'RDNA 4', 'Zen 5', 'Arrow Lake'
    generation        TEXT,                           -- e.g. 'RTX 50', 'Ryzen 9000'
    launch_date       TEXT,                           -- ISO date, nullable if unknown
    launch_msrp_usd   REAL,                           -- as published in source; convert currency at display time
    vram_gb             REAL,
    memory_bus_width_bit  INTEGER,
    memory_type           TEXT,                       -- e.g. 'GDDR7'
    tdp_watts             INTEGER,
    core_count            INTEGER,                    -- shader units for GPU, physical cores for CPU
    thread_count       INTEGER,
    base_clock_mhz     INTEGER,
    boost_clock_mhz    INTEGER,
    socket             TEXT,
    cache_l3_mb        REAL,
    -- TechPowerUp-grade detail (extracted from the verbatim source record)
    gpu_die            TEXT,
    bus_interface      TEXT,
    memory_bandwidth_gbps REAL,
    memory_clock_mhz   REAL,
    process_nm         REAL,
    foundry            TEXT,
    codename           TEXT,
    l1_cache_kb        REAL,
    l2_cache_mb        REAL,
    memory_speed_mhz   REAL,
    memory_channels    REAL,
    memory_types       TEXT,
    integrated_graphics TEXT,
    raw_json          TEXT    NOT NULL,               -- full original source record, verbatim
    last_synced_at    TEXT    NOT NULL,               -- ISO timestamp, set by sync job
    UNIQUE (product_id, source)
)
"""


# Extra spec columns added after the initial table creation (backfilled from
# each row's verbatim raw_json by sync_specs.backfill_specs_extra).
# Types must mirror db/schema.sql — numeric fields are REAL so better-sqlite3
# returns numbers (a TEXT-affinity column would come back as strings).
SPECS_EXTRA_COLUMNS = {
    "gpu_die": "TEXT",
    "bus_interface": "TEXT",
    "memory_bandwidth_gbps": "REAL",
    "memory_clock_mhz": "REAL",
    "process_nm": "REAL",
    "foundry": "TEXT",
    "codename": "TEXT",
    "l1_cache_kb": "REAL",
    "l2_cache_mb": "REAL",
    "memory_speed_mhz": "REAL",
    "memory_channels": "REAL",
    "memory_types": "TEXT",
    "integrated_graphics": "TEXT",
}


def migrate_add_specs_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create the specs table (additive, create-if-missing).

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    if check_table_exists(conn, "specs"):
        LOGGER.info("  [SKIP] specs table already exists")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create specs table")
        return

    LOGGER.info("  [MIGRATE] Creating specs table...")
    conn.execute(SPECS_TABLE_SQL)
    conn.execute("CREATE INDEX idx_specs_product ON specs (product_id)")
    conn.commit()
    LOGGER.info("  [OK] specs table created")


def migrate_add_variant_name(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Add variant_name column to retailer_listings and backfill from existing data.

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    if check_column_exists(conn, "retailer_listings", "variant_name"):
        LOGGER.info("  [SKIP] variant_name column already exists")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would add variant_name column to retailer_listings")
        return

    LOGGER.info("  [MIGRATE] Adding variant_name column to retailer_listings...")
    conn.execute("ALTER TABLE retailer_listings ADD COLUMN variant_name TEXT")
    conn.commit()
    LOGGER.info("  [OK] Column added successfully")


def migrate_add_specs_columns(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Add the TechPowerUp-grade spec columns to specs (additive, per-column
    create-if-missing). Values are backfilled from each row's raw_json by
    sync_specs.backfill_specs_extra — this migration only widens the schema.
    """
    missing = [
        col
        for col in SPECS_EXTRA_COLUMNS
        if not check_column_exists(conn, "specs", col)
    ]
    if not missing:
        LOGGER.info("  [SKIP] all specs extra columns already present")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would add specs columns: %s", ", ".join(missing))
        return

    for col in missing:
        LOGGER.info("  [MIGRATE] Adding specs.%s %s ...", col, SPECS_EXTRA_COLUMNS[col])
        conn.execute(f"ALTER TABLE specs ADD COLUMN {col} {SPECS_EXTRA_COLUMNS[col]}")
    conn.commit()
    LOGGER.info("  [OK] specs columns added: %s", ", ".join(missing))


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Migrate the Trackaroo database")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args(argv)

    LOGGER.info("Database: %s", DB_PATH)
    conn = get_connection()

    try:
        # Check current schema version
        LOGGER.info("\nChecking schema...")

        # Migration: Add variant_name column
        migrate_add_variant_name(conn, dry_run=args.dry_run)

        # Migration: Create specs table
        migrate_add_specs_table(conn, dry_run=args.dry_run)

        # Migration: Widen specs with TechPowerUp-grade columns
        migrate_add_specs_columns(conn, dry_run=args.dry_run)

        if not args.dry_run:
            # Verify
            if check_column_exists(conn, "retailer_listings", "variant_name"):
                LOGGER.info("\n  [OK] variant_name column is present")
            else:
                LOGGER.error("\n  [ERROR] variant_name column is missing")
                sys.exit(1)

            if check_table_exists(conn, "specs"):
                LOGGER.info("  [OK] specs table is present")
            else:
                LOGGER.error("  [ERROR] specs table is missing")
                sys.exit(1)

            # Show current state
            listings_count = conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
            variants_count = conn.execute(
                "SELECT COUNT(DISTINCT variant_name) FROM retailer_listings WHERE variant_name IS NOT NULL"
            ).fetchone()[0]
            LOGGER.info("\nDatabase state:")
            LOGGER.info("  Total listings: %d", listings_count)
            LOGGER.info("  Listings with variant_name: %d", variants_count)
        else:
            LOGGER.info("\n  (Dry run complete — no changes made)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()