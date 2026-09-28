"""Re-point listings the old substring matcher filed under the wrong product.

Fixing the matcher (scraper/chip_key.py) only affects new scrapes:
ingest.find_or_create_listing never changes an existing listing's product. This
applies the same matcher to every listing already in the DB.

  * resolves to a different tracked product -> re-pointed there;
  * resolves to nothing (an untracked part such as a 5500GT, or an eGPU box)
    -> moved to a tracked=0 "Unmatched <CAT> listing" holding product and
       marked stale, so its prices leave the wrong product's history.

Snapshots are never deleted: they are correct prices for the real part.
Dry run by default; --apply takes a backup first.

    python repair_listings.py            # show what would change
    python repair_listings.py --apply    # back up, then change it
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from backup_db import backup_database
from config import DB_PATH
from db.watchlist import WatchlistProduct, load_watchlist
from scraper.chip_key import Matcher

LOGGER = logging.getLogger(__name__)
HOLDING_BRAND = "Unmatched"


@dataclass(frozen=True)
class Repair:
    listing_id: int
    retailer: str
    title: str
    from_model: str
    to_model: Optional[str]  # None -> holding product


def _holding_model(category: str) -> str:
    return f"Unmatched {category.upper()} listing"


def plan_repairs(conn: sqlite3.Connection, watchlist: Sequence[WatchlistProduct]) -> List[Repair]:
    matcher = Matcher(watchlist)
    rows = conn.execute(
        """SELECT l.id, l.retailer, l.variant_name, p.category, p.model
           FROM retailer_listings l JOIN products p ON p.id = l.product_id
           WHERE p.tracked = 1 AND l.variant_name IS NOT NULL
           ORDER BY l.id"""
    ).fetchall()
    repairs: List[Repair] = []
    for listing_id, retailer, title, category, model in rows:
        idx = matcher.resolve(title, category)
        target = matcher.watchlist[idx]["model"] if idx is not None else None
        if target != model:
            repairs.append(Repair(listing_id, retailer, title, model, target))
    return repairs


def _product_id(conn: sqlite3.Connection, category: str, model: str, holding: bool) -> int:
    row = conn.execute(
        "SELECT id FROM products WHERE category = ? AND model = ?", (category, model)
    ).fetchone()
    if row:
        return row[0]
    if not holding:
        raise LookupError(f"{model!r} is in the watchlist but not the DB: run seed.py first")
    cur = conn.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 0)",
        (category, HOLDING_BRAND, model),
    )
    return cur.lastrowid


def apply_repairs(conn: sqlite3.Connection, repairs: Sequence[Repair]) -> int:
    for r in repairs:
        category = conn.execute(
            "SELECT p.category FROM retailer_listings l JOIN products p ON p.id = l.product_id WHERE l.id = ?",
            (r.listing_id,),
        ).fetchone()[0]
        if r.to_model is None:
            pid = _product_id(conn, category, _holding_model(category), holding=True)
            conn.execute(
                "UPDATE retailer_listings SET product_id = ?, status = 'stale' WHERE id = ?",
                (pid, r.listing_id),
            )
        else:
            pid = _product_id(conn, category, r.to_model, holding=False)
            conn.execute("UPDATE retailer_listings SET product_id = ? WHERE id = ?", (pid, r.listing_id))
    conn.commit()
    return len(repairs)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="back up, then write the changes")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = sqlite3.connect(str(args.db))
    repairs = plan_repairs(conn, load_watchlist(strict=True))
    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(repairs)} listing(s) to re-point")
    for r in repairs:
        print(f"  [{r.retailer:8}] {r.from_model!r} -> {r.to_model or 'UNMATCHED (stale)'!r}  {r.title}")
    if args.apply and repairs:
        conn.close()
        backup = backup_database(db_path=args.db)
        print(f"Backup written: {backup}")
        conn = sqlite3.connect(str(args.db))
        print(f"Re-pointed {apply_repairs(conn, repairs)} listing(s)")
    conn.close()


if __name__ == "__main__":
    main()
