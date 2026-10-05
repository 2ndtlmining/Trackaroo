"""
Seed the Trackaroo database from db/watchlist.csv and db/generations.toml.

Usage:
    python seed.py                # Seed (or re-seed) the production DB at db/trackaroo.db
    python seed.py --dry-run      # Preview what would change without writing
    python seed.py --allow-bulk   # Permit a rollover/retirement flipping many `tracked`

Syncs the `products` and `generations` tables. The watchlist is the source of
truth: tier, spec facts, series and `tracked` (both ways) follow it. Products
missing from the CSV are reported, never retired. Changing `tracked` on more
than max(5, 10%) of the products at once is refused unless --allow-bulk is given.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import ACTIVE_RETAILERS, DB_PATH, GENERATIONS_PATH, SCHEMA_PATH, WATCHLIST_PATH
from db.generations import Generations, GenerationsError, load_generations
from db.watchlist import load_watchlist_products, parse_spec
from migrate import migrate_add_generations
from pipeline_state import sync_active_retailers

LOGGER = logging.getLogger(__name__)

Product = Dict[str, Any]

HOLDING_BRAND = "Unmatched"  # repair_listings.HOLDING_BRAND


class BulkChangeError(RuntimeError):
    """seed would flip `tracked` on too many products at once (#18)."""

    def __init__(self, flips, limit):
        self.flips = flips
        self.limit = limit
        names = ", ".join(f"{m} ({o}->{n})" for m, o, n in flips)
        super().__init__(
            f"Refusing to change tracked on {len(flips)} products (limit {limit}): {names}. "
            "If this is an intended rollover/retirement, re-run with --allow-bulk."
        )


def bulk_limit(total_products: int) -> int:
    return max(5, total_products // 10)


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


def load_watchlist(path: Path = WATCHLIST_PATH, generations_path: Path = GENERATIONS_PATH) -> List[Product]:
    """Load the watchlist CSV into product records for seeding.

    Args:
        path: Path to the watchlist CSV.
        generations_path: Path to generations.toml.

    Returns:
        List of product dicts shaped for the ``products`` table.
    """
    return load_watchlist_products(str(path), generations_path=str(generations_path))


def sync_generations(conn: sqlite3.Connection, gens: Generations, dry_run: bool = False) -> None:
    """Mirror generations.toml into the generations table (the web reads labels there)."""
    if dry_run:
        return
    conn.execute("DELETE FROM generations")
    conn.executemany(
        "INSERT INTO generations (series_key, line_id, label, position, keep_all) VALUES (?, ?, ?, ?, ?)",
        [(s.key, s.line_id, s.label, s.position, int(gens.lines[s.line_id].keep_all)) for s in gens.series.values()],
    )
    conn.commit()


def seed_products(
    conn: sqlite3.Connection,
    products: List[Product],
    dry_run: bool = False,
    allow_bulk: bool = False,
) -> Dict[str, Any]:
    """Sync products from the watchlist: insert new rows, update existing ones.

    The watchlist (CSV + generations.toml) is the source of truth for tier,
    spec facts, series AND ``tracked``, so a retirement or un-retirement in the
    CSV reaches the DB. Plan first, write after: a refused bulk change leaves
    ``products`` untouched.

    Args:
        conn: Open SQLite connection.
        products: Product dicts from ``load_watchlist_products``.
        dry_run: When True, only report what would happen without writing.
        allow_bulk: Permit more than ``bulk_limit`` tracked flips (a rollover).

    Returns:
        Stats dict: inserted/skipped/updated/errors counts and ``flips`` (a list
        of (model, old, new) tracked changes).

    Raises:
        BulkChangeError: Too many tracked flips, not dry_run, not allow_bulk.
    """
    stats: Dict[str, Any] = {"inserted": 0, "skipped": 0, "updated": 0, "errors": 0, "flips": []}
    updates: List[tuple] = []
    inserts: List[Product] = []
    for p in products:
        existing = conn.execute(
            "SELECT id, generation_tier, vram_gb, cores, tracked, series FROM products"
            " WHERE category = ? AND brand = ? AND model = ?",
            (p["category"], p["brand"], p["model"]),
        ).fetchone()
        if existing is None:
            inserts.append(p)
            continue
        pid, tier, vram, cores, tracked, series = existing
        # A tracked row takes its derived tier; an untracked one keeps where it last sat.
        new_tier = p["generation_tier"] if p["tracked"] and p["generation_tier"] else tier
        wanted = (new_tier, p["vram_gb"], p["cores"], p["tracked"], p["series"])
        if (tier, vram, cores, tracked, series) == wanted:
            stats["skipped"] += 1
            continue
        if tracked != p["tracked"]:
            stats["flips"].append((p["model"], tracked, p["tracked"]))
        updates.append((*wanted, pid))

    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    limit = bulk_limit(total)
    if len(stats["flips"]) > limit and not allow_bulk and not dry_run:
        raise BulkChangeError(stats["flips"], limit)

    stats["updated"] = len(updates)
    if dry_run:
        stats["inserted"] = len(inserts)
        return stats
    conn.executemany(
        "UPDATE products SET generation_tier = ?, vram_gb = ?, cores = ?, tracked = ?, series = ? WHERE id = ?",
        updates,
    )
    for p in inserts:
        try:
            conn.execute(
                """INSERT INTO products (category, brand, model, vram_gb, cores, generation_tier, tracked, series)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["category"], p["brand"], p["model"], p["vram_gb"], p["cores"],
                 p["generation_tier"] or "current-2", p["tracked"], p["series"]),
            )
            stats["inserted"] += 1
        except sqlite3.IntegrityError as e:
            LOGGER.error("ERROR inserting %s: %s", p["model"], e)
            stats["errors"] += 1
    conn.commit()
    return stats


def report_missing(conn: sqlite3.Connection, products: List[Product]) -> List[str]:
    """DB models (not the holding brand) absent from the CSV: reported, never retired."""
    wanted = {(p["category"], p["brand"], p["model"]) for p in products}
    return [
        model for category, brand, model in conn.execute(
            "SELECT category, brand, model FROM products WHERE brand != ? ORDER BY model", (HOLDING_BRAND,))
        if (category, brand, model) not in wanted
    ]


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Seed the Trackaroo database from watchlist.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--allow-bulk", action="store_true", help="Allow changing tracked on many products (a rollover)")
    args = parser.parse_args(argv)

    LOGGER.info("Watchlist: %s", WATCHLIST_PATH)
    LOGGER.info("Database:  %s", DB_PATH)
    LOGGER.info("Schema:    %s", SCHEMA_PATH)

    # Load watchlist + generations; a broken toml stops here, before any write.
    try:
        gens = load_generations()
        products = load_watchlist(WATCHLIST_PATH)
    except GenerationsError as e:
        LOGGER.error("%s", e)
        sys.exit(1)
    LOGGER.info("\n%d products in watchlist", len(products))

    # Init DB. At boot seed runs before migrate.py, so add series/generations here.
    conn = init_db(DB_PATH)
    LOGGER.info("Database initialized at %s", DB_PATH)
    conn.row_factory = sqlite3.Row  # migrate's check_* helpers read columns by name
    migrate_add_generations(conn, dry_run=args.dry_run)
    conn.row_factory = None

    if args.dry_run and not any(r[1] == "series" for r in conn.execute("PRAGMA table_info(products)")):
        LOGGER.info("Dry run on a DB without products.series: run without --dry-run to migrate first; product sync skipped")
        conn.close()
        return

    try:
        stats = seed_products(conn, products, dry_run=args.dry_run, allow_bulk=args.allow_bulk)
    except BulkChangeError as e:
        LOGGER.error("%s", e)
        conn.close()
        sys.exit(1)

    # Mirror labels only once the product sync is applied: the web joins
    # generations to products, so a refused rollover must keep the OLD mirror.
    sync_generations(conn, gens, dry_run=args.dry_run)

    # The container runs seed.py on every boot, so this keeps the dashboard's
    # retailer list (active_retailers) equal to config even before the first
    # daily run on a new build (R1). Wrapped: this runs under `set -e` at
    # boot, so a sync failure must log a WARNING and let the boot continue,
    # never crash-loop the container (F20).
    if not args.dry_run:
        try:
            sync_active_retailers(conn, ACTIVE_RETAILERS)
        except Exception as e:  # noqa: BLE001 - best-effort, boot must not crash-loop
            LOGGER.warning("Active-retailer sync failed (best-effort; boot continues): %s", e)

    LOGGER.info("\nResults:")
    LOGGER.info("  Inserted: %d", stats["inserted"])
    LOGGER.info("  Skipped (already exists): %d", stats["skipped"])
    LOGGER.info("  Updated (tier/vram_gb/cores/series/tracked): %d", stats["updated"])
    for model, old, new in stats["flips"]:
        LOGGER.info("  tracked %s -> %s: %s", old, new, model)
    LOGGER.info("  Tracked changes: %d", len(stats["flips"]))
    LOGGER.info("  Errors: %d", stats["errors"])
    for model in report_missing(conn, products):
        LOGGER.warning("In the DB but not in watchlist.csv (left unchanged): %s", model)

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
