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
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = Path("db/trackaroo.db")
SCHEMA_PATH = Path("db/schema.sql")
DATA_DIR = Path("data")


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create the database and tables if they don't exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

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

    Returns a YYYY-MM-DD string, or empty string if parsing fails.
    """
    stem = Path(filename).stem  # e.g., "cpu_scorptec_10_August_2026"
    parts = stem.split("_")  # ["cpu", "scorptec", "10", "August", "2026"]
    if len(parts) >= 3:
        date_str = "_".join(parts[-3:])  # "10_August_2026"
        try:
            dt = datetime.strptime(date_str, "%d_%B_%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def find_or_create_product(conn: sqlite3.Connection, product_data: dict, dry_run: bool = False) -> int:
    """Find existing product or create new one. Returns product_id (or None in dry_run if new)."""
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


def find_or_create_listing(conn: sqlite3.Connection, product_id: int, retailer: str, url: str,
                           variant_name: str = None, dry_run: bool = False) -> int:
    """Find existing retailer listing or create new one. Returns listing_id (or None in dry_run if new).

    Each unique URL at a retailer gets its own listing. This allows tracking
    multiple variants of the same product (e.g., GIGABYTE, ASUS, Zotac 5090).
    """
    # Check by retailer + URL (each URL = one listing, regardless of product mapping)
    cursor = conn.execute(
        "SELECT id FROM retailer_listings WHERE retailer = ? AND listing_url = ?",
        (retailer, url),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    if dry_run:
        return None  # Don't create in dry-run mode

    conn.execute(
        """INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
           VALUES (?, ?, ?, ?, 'active')""",
        (product_id, retailer, variant_name, url),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def ingest_file(conn: sqlite3.Connection, file_path: Path, dry_run: bool = False) -> dict:
    """Ingest a single JSON file. Returns stats dict."""
    stats = {"inserted": 0, "skipped": 0, "errors": 0, "new_products": 0, "new_listings": 0}

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", [])
    snapshot_date = parse_date_from_filename(file_path.name)

    if not snapshot_date:
        print(f"  WARNING: Could not parse date from filename {file_path.name}, skipping")
        stats["errors"] += 1
        return stats

    retailer = data.get("retailer", "unknown")

    for product_data in products:
        url = product_data.get("url", "")
        price = product_data.get("price_aud")
        stock_status = product_data.get("stock_status", "unknown")

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
            model = product_data.get("watchlist_model", "unknown")

            # Step 2: Find or create retailer listing (with variant name)
            variant_name = product_data.get("scraped_name", "")
            listing_id = find_or_create_listing(conn, product_id, retailer, url,
                                                variant_name=variant_name, dry_run=dry_run)
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

        except sqlite3.IntegrityError as e:
            print(f"  ERROR processing {model}: {e}")
            stats["errors"] += 1

    if not dry_run:
        conn.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Ingest scraped JSON files into the Trackaroo database")
    parser.add_argument("--file", type=Path, help="Single file to ingest (default: all files in data/)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--date", type=str, help="Only ingest files matching this date (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"Database: {DB_PATH}")

    # Collect files to process
    if args.file:
        files = [args.file]
    else:
        files = sorted(DATA_DIR.glob("*.json"))

    if not files:
        print("No JSON files found to ingest.")
        return

    # Filter by date if specified
    if args.date:
        files = [f for f in files if parse_date_from_filename(f.name) == args.date]
        if not files:
            print(f"No files matching date {args.date}")
            return

    print(f"Files to process: {len(files)}")

    # Init DB
    conn = init_db(DB_PATH)

    total_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    for file_path in files:
        date_str = parse_date_from_filename(file_path.name)
        print(f"\nProcessing: {file_path.name} (date: {date_str})")
        stats = ingest_file(conn, file_path, dry_run=args.dry_run)
        print(f"  Inserted: {stats['inserted']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
        total_stats["inserted"] += stats["inserted"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]

    print(f"\n{'=' * 50}")
    print(f"Total: {total_stats['inserted']} inserted, {total_stats['skipped']} skipped, {total_stats['errors']} errors")

    # Verify
    if not args.dry_run:
        products_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        listings_count = conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0]
        snapshots_count = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        print(f"\nDatabase state:")
        print(f"  Products: {products_count}")
        print(f"  Retailer listings: {listings_count}")
        print(f"  Price snapshots: {snapshots_count}")

    conn.close()

    if total_stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
