"""
Query the Trackaroo database for price data.

Usage:
    python query.py                          # Show all tracked products with latest prices
    python query.py --model "RTX 5070"       # Search by model (partial match)
    python query.py --category gpu           # Filter by category
    python query.py --retailer scorptec      # Filter by retailer
    python query.py --trends                 # Show price trends across dates
    python query.py --biggest-movers         # Show biggest price changes between latest dates
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


def show_latest_prices(conn, model=None, category=None, retailer=None):
    """Show latest prices for all tracked products and variants."""
    query = """
        SELECT p.model, p.category, p.brand, l.retailer, l.variant_name, s.snapshot_date,
               s.price_aud, s.stock_status, l.listing_url
        FROM price_snapshots s
        JOIN retailer_listings l ON s.retailer_listing_id = l.id
        JOIN products p ON l.product_id = p.id
        WHERE p.tracked = 1
          AND s.snapshot_date = (
              SELECT MAX(s2.snapshot_date)
              FROM price_snapshots s2
              JOIN retailer_listings l2 ON s2.retailer_listing_id = l2.id
              WHERE l2.product_id = l.product_id
                AND l2.retailer = l.retailer
          )
    """
    params = []

    if model:
        query += " AND p.model LIKE ?"
        params.append(f"%{model}%")
    if category:
        query += " AND p.category = ?"
        params.append(category)
    if retailer:
        query += " AND l.retailer = ?"
        params.append(retailer)

    query += " ORDER BY p.category, p.model, l.retailer, s.price_aud"

    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No data found.")
        return

    print(f"\nLatest prices ({len(rows)} results):")
    print("-" * 100)
    for row in rows:
        variant = (row['variant_name'] or "").split(",")[0][:30]  # Short variant for display
        print(f"  {row['category'].upper():3} | {row['model']:25} | {row['retailer']:10} | ${row['price_aud']:>8.2f} | {variant}")
    print("-" * 100)


def show_trends(conn, model=None, category=None):
    """Show price trends across dates."""
    query = """
        SELECT p.model, p.category, l.retailer, s.snapshot_date,
               s.price_aud, s.stock_status
        FROM price_snapshots s
        JOIN retailer_listings l ON s.retailer_listing_id = l.id
        JOIN products p ON l.product_id = p.id
        WHERE p.tracked = 1
    """
    params = []

    if model:
        query += " AND p.model LIKE ?"
        params.append(f"%{model}%")
    if category:
        query += " AND p.category = ?"
        params.append(category)

    query += " ORDER BY p.model, l.retailer, s.snapshot_date"

    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No data found.")
        return

    # Group by product + retailer
    current_product = None
    print(f"\nPrice trends ({len(rows)} snapshots):")
    print("-" * 80)
    for row in rows:
        if row['model'] != current_product:
            current_product = row['model']
            print(f"\n  {row['model']} ({row['category'].upper()})")
        print(f"    {row['retailer']:10} | {row['snapshot_date']} | ${row['price_aud']:>8.2f} | {row['stock_status']}")


def show_biggest_movers(conn):
    """Show biggest price changes between the two most recent dates."""
    # Get the two most recent dates
    dates = conn.execute("""
        SELECT DISTINCT snapshot_date FROM price_snapshots
        ORDER BY snapshot_date DESC LIMIT 2
    """).fetchall()

    if len(dates) < 2:
        print("Need at least 2 dates to calculate price changes.")
        return

    date_old = dates[1]['snapshot_date']
    date_new = dates[0]['snapshot_date']

    query = """
        WITH old_prices AS (
            SELECT l.product_id, l.retailer, s.price_aud
            FROM price_snapshots s
            JOIN retailer_listings l ON s.retailer_listing_id = l.id
            WHERE s.snapshot_date = ?
        ),
        new_prices AS (
            SELECT l.product_id, l.retailer, s.price_aud
            FROM price_snapshots s
            JOIN retailer_listings l ON s.retailer_listing_id = l.id
            WHERE s.snapshot_date = ?
        )
        SELECT p.model, p.category, o.retailer,
               o.price_aud as old_price, n.price_aud as new_price,
               ROUND(n.price_aud - o.price_aud, 2) as change,
               ROUND((n.price_aud - o.price_aud) / o.price_aud * 100, 1) as pct_change
        FROM old_prices o
        JOIN new_prices n ON o.product_id = n.product_id AND o.retailer = n.retailer
        JOIN products p ON p.id = o.product_id
        WHERE p.tracked = 1
          AND o.price_aud != n.price_aud
        ORDER BY ABS(change) DESC
    """

    rows = conn.execute(query, (date_old, date_new)).fetchall()

    if not rows:
        print(f"No price changes between {date_old} and {date_new}.")
        return

    print(f"\nBiggest movers ({date_old} -> {date_new}):")
    print("-" * 80)
    for row in rows:
        direction = "-" if row['change'] < 0 else "+"
        print(f"  {direction} {row['model']:25} | {row['retailer']:10} | ${row['old_price']:>8.2f} -> ${row['new_price']:>8.2f} | {row['change']:>+7.2f} ({row['pct_change']:+.1f}%)")
    print("-" * 80)
    print(f"  {len(rows)} products with price changes")


def main():
    parser = argparse.ArgumentParser(description="Query the Trackaroo price database")
    parser.add_argument("--model", type=str, help="Search by model (partial match)")
    parser.add_argument("--category", type=str, choices=['cpu', 'gpu'], help="Filter by category")
    parser.add_argument("--retailer", type=str, choices=['scorptec', 'pccg', 'mwave'], help="Filter by retailer")
    parser.add_argument("--trends", action="store_true", help="Show price trends across dates")
    parser.add_argument("--biggest-movers", action="store_true", help="Show biggest price changes")
    args = parser.parse_args()

    conn = get_connection()

    try:
        if args.biggest_movers:
            show_biggest_movers(conn)
        elif args.trends:
            show_trends(conn, model=args.model, category=args.category)
        else:
            show_latest_prices(conn, model=args.model, category=args.category, retailer=args.retailer)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
