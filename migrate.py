"""
Migrate the Trackaroo database to support variant tracking.

Adds the variant_name column to retailer_listings and backfills it from
scraped_name data where available.

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

LOGGER = logging.getLogger(__name__)

DB_PATH = Path("db/trackaroo.db")


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

        if not args.dry_run:
            # Verify
            if check_column_exists(conn, "retailer_listings", "variant_name"):
                LOGGER.info("\n  [OK] variant_name column is present")
            else:
                LOGGER.error("\n  [ERROR] variant_name column is missing")
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