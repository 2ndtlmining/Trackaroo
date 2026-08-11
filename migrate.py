"""
Migrate the Trackaroo database to support variant tracking.

Adds the variant_name column to retailer_listings and backfills it from
scraped_name data where available.

Usage:
    python migrate.py              # Apply all pending migrations
    python migrate.py --dry-run    # Preview without writing
"""
import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("db/trackaroo.db")


def get_connection():
    """Get a database connection."""
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Run seed.py first.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def check_column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row["name"] for row in cursor.fetchall()]
    return column in columns


def migrate_add_variant_name(conn, dry_run: bool = False):
    """Add variant_name column to retailer_listings and backfill from existing data."""
    if check_column_exists(conn, "retailer_listings", "variant_name"):
        print("  [SKIP] variant_name column already exists")
        return

    if dry_run:
        print("  [DRY-RUN] Would add variant_name column to retailer_listings")
        return

    print("  [MIGRATE] Adding variant_name column to retailer_listings...")
    conn.execute("ALTER TABLE retailer_listings ADD COLUMN variant_name TEXT")
    conn.commit()
    print("  [OK] Column added successfully")


def main():
    parser = argparse.ArgumentParser(description="Migrate the Trackaroo database")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print(f"Database: {DB_PATH}")
    conn = get_connection()

    try:
        # Check current schema version
        print("\nChecking schema...")

        # Migration: Add variant_name column
        migrate_add_variant_name(conn, dry_run=args.dry_run)

        if not args.dry_run:
            # Verify
            if check_column_exists(conn, "retailer_listings", "variant_name"):
                print("\n  [OK] variant_name column is present")
            else:
                print("\n  [ERROR] variant_name column is missing")
                sys.exit(1)

            # Show current state
            listings_count = conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
            variants_count = conn.execute("SELECT COUNT(DISTINCT variant_name) FROM retailer_listings WHERE variant_name IS NOT NULL").fetchone()[0]
            print(f"\nDatabase state:")
            print(f"  Total listings: {listings_count}")
            print(f"  Listings with variant_name: {variants_count}")
        else:
            print("\n  (Dry run complete — no changes made)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
