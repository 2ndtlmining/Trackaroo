"""
Seed the Trackaroo database from db/watchlist.csv.

Usage:
    python seed.py              # Seed (or re-seed) the production DB at db/trackaroo.db
    python seed.py --dry-run    # Preview what would be inserted without writing

Reads db/watchlist.csv and populates the `products` table.
Existing products are NOT overwritten — only new rows are inserted.
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("db/trackaroo.db")
SCHEMA_PATH = Path("db/schema.sql")
WATCHLIST_PATH = Path("db/watchlist.csv")


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create the database and tables if they don't exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

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


def parse_spec(spec: str, category: str):
    """Parse the spec column into cores (CPU) or vram_gb (GPU)."""
    if category == "cpu":
        return {"cores": int(spec.replace("c", "")), "vram_gb": None}
    else:
        return {"cores": None, "vram_gb": int(spec.replace("GB", ""))}


def load_watchlist(path: Path) -> list[dict]:
    """Load watchlist CSV, skipping comment lines."""
    products = []
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f if not line.startswith("#") and line.strip()]
    reader = csv.DictReader(lines)
    for row in reader:
        spec_fields = parse_spec(row["spec"], row["category"])
        products.append({
            "category": row["category"],
            "brand": row["brand"],
            "model": row["model"],
            "vram_gb": spec_fields["vram_gb"],
            "cores": spec_fields["cores"],
            "generation_tier": row["gen_tier"],
            "tracked": 1,  # All watchlist products are tracked by definition
        })
    return products


def seed_products(conn: sqlite3.Connection, products: list[dict], dry_run: bool = False) -> dict:
    """Insert new products into the DB. Returns stats dict."""
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
                print(f"  ERROR inserting {p['model']}: {e}")
                stats["errors"] += 1

    if not dry_run:
        conn.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Seed the Trackaroo database from watchlist.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print(f"Watchlist: {WATCHLIST_PATH}")
    print(f"Database:  {DB_PATH}")
    print(f"Schema:    {SCHEMA_PATH}")

    # Load watchlist
    products = load_watchlist(WATCHLIST_PATH)
    print(f"\n{len(products)} products in watchlist")

    # Init DB
    conn = init_db(DB_PATH)
    print(f"Database initialized at {DB_PATH}")

    # Seed
    stats = seed_products(conn, products, dry_run=args.dry_run)

    print(f"\nResults:")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Skipped (already exists): {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")

    # Verify
    if not args.dry_run:
        total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        tracked = conn.execute("SELECT COUNT(*) FROM products WHERE tracked = 1").fetchone()[0]
        print(f"\nDatabase now has {total} products ({tracked} tracked)")

    conn.close()

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
