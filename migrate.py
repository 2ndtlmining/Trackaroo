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
- Creates the price_alerts table (user "tell me when to buy" alerts,
  see check_alerts.py).
- Backfills retailer_sku from the URL key and merges duplicate listing rows
  forked by retailer URL slug rewrites (see migrate_merge_duplicate_listings).

Usage:
    python migrate.py              # Apply all pending migrations
    python migrate.py --dry-run    # Preview without writing
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import DB_PATH
from ingest import extract_listing_key

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


PRICE_ALERTS_TABLE_SQL = """
CREATE TABLE price_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id),
    target_price        REAL    NOT NULL,             -- AUD. fires when cheapest in-stock <= this
    channel             TEXT    NOT NULL DEFAULT 'discord'
                        CHECK (channel IN ('discord', 'email', 'webhook')),
    notify_on_restock   INTEGER NOT NULL DEFAULT 0,   -- 0/1. also fire when an OOS product returns
    active              INTEGER NOT NULL DEFAULT 1,   -- 0/1. 0 = paused (kept for history)
    last_notified_at    TEXT,                          -- ISO8601 UTC. set when the alert last fired
    last_notified_price REAL,                          -- price at the last firing (cooldown dedup)
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (product_id, channel)
)
"""


def migrate_add_price_alerts_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create the price_alerts table (additive, create-if-missing).

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    if check_table_exists(conn, "price_alerts"):
        LOGGER.info("  [SKIP] price_alerts table already exists")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create price_alerts table")
        return

    LOGGER.info("  [MIGRATE] Creating price_alerts table...")
    conn.execute(PRICE_ALERTS_TABLE_SQL)
    conn.execute("CREATE INDEX idx_price_alerts_product ON price_alerts (product_id)")
    conn.execute("CREATE INDEX idx_price_alerts_active ON price_alerts (active)")
    conn.commit()
    LOGGER.info("  [OK] price_alerts table created")


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


def migrate_backfill_retailer_sku(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Backfill retailer_listings.retailer_sku from the URL key where it's NULL.

    ``retailer_sku`` is now stored on insert; older rows predate that. Deriving
    it from the stable numeric URL key (Scorptec/PCCG) lets the key-based dedup
    in ``ingest.find_or_create_listing`` identify those rows going forward.
    """
    rows = conn.execute(
        "SELECT id, retailer, listing_url FROM retailer_listings WHERE retailer_sku IS NULL"
    ).fetchall()
    updates = []
    for rid, retailer, url in rows:
        key = extract_listing_key(retailer, url)
        if key:
            updates.append((rid, key))

    if not updates:
        LOGGER.info("  [SKIP] no listings missing retailer_sku")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would backfill retailer_sku on %d listings", len(updates))
        return

    for rid, key in updates:
        conn.execute("UPDATE retailer_listings SET retailer_sku = ? WHERE id = ?", (key, rid))
    conn.commit()
    LOGGER.info("  [OK] Backfilled retailer_sku on %d listings", len(updates))


def _latest_scraped_at(conn: sqlite3.Connection, listing_id: int) -> Optional[str]:
    """Return the most recent snapshot scraped_at for a listing, or None."""
    row = conn.execute(
        "SELECT MAX(scraped_at) FROM price_snapshots WHERE retailer_listing_id = ?",
        (listing_id,),
    ).fetchone()
    return row[0]


# Products deliberately removed from db/watchlist.csv.
#
# seed.py only ever INSERTs — it syncs generation_tier and otherwise leaves
# existing rows alone — so deleting a watchlist row does nothing to a DB that
# already has the product. It stays tracked=1 forever, counting toward the
# dashboard's "N tracked" while never being able to have a listing.
#
# Per the never-delete-product-data rule these are untracked, not removed: the
# row and any price history it accumulated stay put.
#
# Radeon RX 9070 XTX — announced-but-never-released card; no retailer will ever
# stock it (retired 30-Aug-2026).
# Every retailer slug the database will accept. This is deliberately the same
# set `web/src/lib/types.ts:7` already declares, so the schema stops being the
# one layer that has to be rebuilt to add a retailer.
#
# Why widen the CHECK rather than move to a `retailers` lookup table, which
# THIRD_RETAILER.md originally suggested: the lookup table's selling point was
# that a new retailer becomes a row insert instead of a table rebuild, but that
# is not true end to end. types.ts, filters.ts, ingest.py, health_checks.py,
# check_staleness.py, query.py and run_daily.py all enumerate retailers in code
# as well, so a new one is a code change either way. A lookup table would add a
# table and a join to buy nothing; one rebuild covering every remaining
# candidate buys the same thing for less.
PERMITTED_RETAILERS = ("scorptec", "pccg", "mwave", "umart", "centrecom", "ple")

RETIRED_PRODUCTS = ("Radeon RX 9070 XTX",)


def migrate_untrack_retired_products(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Set tracked=0 for products retired from the watchlist.

    Idempotent: a second run finds nothing still tracked.

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    placeholders = ",".join("?" for _ in RETIRED_PRODUCTS)
    still_tracked = [
        row[0]
        for row in conn.execute(
            f"SELECT model FROM products WHERE tracked = 1 AND model IN ({placeholders})",
            RETIRED_PRODUCTS,
        )
    ]

    if not still_tracked:
        LOGGER.info("  [SKIP] no retired products still tracked")
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would untrack %d retired product(s): %s",
                    len(still_tracked), ", ".join(still_tracked))
        return

    conn.execute(
        f"UPDATE products SET tracked = 0 WHERE model IN ({placeholders})",
        RETIRED_PRODUCTS,
    )
    conn.commit()
    for model in still_tracked:
        LOGGER.info("  [MIGRATE] Untracked retired product: %s", model)


def _retailer_check_permits_all(conn: sqlite3.Connection) -> bool:
    """True when retailer_listings' CHECK already lists every permitted slug."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'retailer_listings'"
    ).fetchone()
    if not row or not row[0]:
        return False
    return all(f"'{slug}'" in row[0] for slug in PERMITTED_RETAILERS)


def migrate_widen_retailer_check(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Widen retailer_listings' CHECK to every slug in PERMITTED_RETAILERS.

    SQLite cannot ALTER a CHECK constraint, so this is the full table rebuild:
    create, copy, drop, rename, restore indexes. Three details make it less
    routine than it looks, and each is the reason for a line below.

    * The new DDL is **derived from the live table** rather than written out
      here. Copying the column list into this file would silently rot the first
      time a column is added elsewhere; rewriting only the CHECK clause cannot.
    * ``PRAGMA legacy_alter_table`` is turned **on** for the rename. Modern
      SQLite validates triggers during ALTER TABLE RENAME, and
      ``trg_update_listing_last_snapshot`` (on price_snapshots) references
      retailer_listings, which does not exist between the DROP and the RENAME.
      Without the pragma the rename fails with "no such table".
    * Foreign keys are off for the rebuild and ``PRAGMA foreign_key_check`` runs
      before the commit, so a rebuild that orphaned price_snapshots rolls back
      instead of committing damage. This project has lost data once already.

    Idempotent: it runs on every container start via bootstrap-data.sh.

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    if _retailer_check_permits_all(conn):
        LOGGER.info("  [SKIP] retailer CHECK already permits all %d retailers",
                    len(PERMITTED_RETAILERS))
        return

    if dry_run:
        LOGGER.info("  [DRY-RUN] Would rebuild retailer_listings to permit: %s",
                    ", ".join(PERMITTED_RETAILERS))
        return

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'retailer_listings'"
    ).fetchone()
    if not row or not row[0]:
        LOGGER.info("  [SKIP] no retailer_listings table to widen")
        return

    allowed = ", ".join(f"'{slug}'" for slug in PERMITTED_RETAILERS)
    new_ddl, n = re.subn(
        r"CHECK\s*\(\s*retailer\s+IN\s*\([^)]*\)\s*\)",
        f"CHECK (retailer IN ({allowed}))",
        row[0],
        count=1,
        flags=re.IGNORECASE,
    )
    if n != 1:
        raise RuntimeError(
            "could not find the retailer CHECK clause in retailer_listings; "
            "refusing to rebuild the table blind"
        )
    new_ddl = new_ddl.replace("retailer_listings", "retailer_listings_new", 1)

    indexes = [
        r[0]
        for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'retailer_listings' AND sql IS NOT NULL"
        )
    ]

    conn.commit()
    fk_was_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("BEGIN")
        conn.execute(new_ddl)
        conn.execute("INSERT INTO retailer_listings_new SELECT * FROM retailer_listings")
        conn.execute("DROP TABLE retailer_listings")
        conn.execute("ALTER TABLE retailer_listings_new RENAME TO retailer_listings")
        for index_sql in indexes:
            conn.execute(index_sql)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"rebuild left {len(violations)} foreign key violation(s); rolling back"
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")

    LOGGER.info("  [MIGRATE] retailer_listings rebuilt; CHECK now permits: %s",
                ", ".join(PERMITTED_RETAILERS))


def migrate_merge_duplicate_listings(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Merge duplicate retailer_listings rows forked by retailer URL slug rewrites.

    Retailers rewrite URL slugs over time (Scorptec ``/116356`` vs
    ``/116356-ne63050018je-1072f``; PCCG ``/products/69245`` vs
    ``/products/69245/...``). Ingest versions that keyed only on the exact URL
    created a second listing row for the same physical product. This merges
    each such group into one survivor: price snapshots are moved over (one per
    date), the survivor keeps the most-recently-scraped URL, and the absorbed
    rows are marked ``status='stale'`` (rows are never deleted).

    Idempotent: a second run finds no group with more than one row.

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only preview what would change without writing.
    """
    # The merge reads variant_name, which only exists after the column
    # migration — on a pre-migration DB there is nothing to merge yet.
    if not check_column_exists(conn, "retailer_listings", "variant_name"):
        LOGGER.info("  [SKIP] variant_name column missing (run earlier migrations first)")
        return

    rows = conn.execute(
        "SELECT id, retailer, retailer_sku, listing_url, variant_name, status FROM retailer_listings"
    ).fetchall()

    # Only groups with more than one ACTIVE row need merging. A group with one
    # active row plus retired (stale/delisted) rows was already merged on an
    # earlier run — the absorbed rows stay retired, so a re-run is a true no-op.
    active_by_key: Dict[Tuple[str, str], List[Tuple[int, str, Optional[str]]]] = {}
    for rid, retailer, sku, url, variant, status in rows:
        if status != "active":
            continue
        key = sku or extract_listing_key(retailer, url)
        if not key:
            continue
        active_by_key.setdefault((retailer, key), []).append((rid, url, variant))

    groups = {k: v for k, v in active_by_key.items() if len(v) > 1}
    if not groups:
        LOGGER.info("  [SKIP] no duplicate listings to merge")
        return

    merged_groups = 0
    for (retailer, key), group in sorted(groups.items()):
        if len(group) < 2:
            continue

        def _weight(item: Tuple[int, str, Optional[str]]) -> Tuple[str, int, int]:
            rid, _, _ = item
            return (_latest_scraped_at(conn, rid) or "", rid, 0)

        survivor = max(group, key=_weight)
        survivor_id = survivor[0]
        dupes = [g for g in group if g[0] != survivor_id]

        if dry_run:
            LOGGER.info(
                "  [DRY-RUN] Would merge %d duplicate(s) of %s key %s into listing %d",
                len(dupes), retailer, key, survivor_id,
            )
            continue

        for dup_id, dup_url, dup_variant in dupes:
            # Move snapshots that the survivor doesn't already have (preserving
            # their original scraped_at so the trigger keeps real timestamps).
            conn.execute(
                """INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
                   SELECT ?, snapshot_date, price_aud, stock_status, scraped_at
                   FROM price_snapshots
                   WHERE retailer_listing_id = ? AND snapshot_date NOT IN (
                       SELECT snapshot_date FROM price_snapshots WHERE retailer_listing_id = ?
                   )""",
                (survivor_id, dup_id, survivor_id),
            )
            # Absorb a more recent URL and any missing variant name.
            if (_latest_scraped_at(conn, dup_id) or "") > (_latest_scraped_at(conn, survivor_id) or ""):
                conn.execute(
                    "UPDATE retailer_listings SET listing_url = ? WHERE id = ?",
                    (dup_url, survivor_id),
                )
            if not survivor[2] and dup_variant:
                conn.execute(
                    "UPDATE retailer_listings SET variant_name = ? WHERE id = ?",
                    (dup_variant, survivor_id),
                )
            conn.execute(
                "UPDATE retailer_listings SET status = 'stale' WHERE id = ? AND status != 'stale'",
                (dup_id,),
            )
            LOGGER.info("  [MIGRATE] Merged listing %d into %d (%s key %s)", dup_id, survivor_id, retailer, key)

        # Restore accurate timestamps on the survivor (the merge moves older
        # snapshots too, and the trigger overwrites last_* on each insert).
        latest = _latest_scraped_at(conn, survivor_id)
        if latest:
            conn.execute(
                "UPDATE retailer_listings SET last_snapshot_at = ?, last_seen_at = ? WHERE id = ?",
                (latest, latest, survivor_id),
            )
        conn.execute(
            "UPDATE retailer_listings SET retailer_sku = ? WHERE id = ?",
            (key, survivor_id),
        )
        merged_groups += 1

    conn.commit()
    LOGGER.info("  [OK] Merged %d duplicate listing group(s)", merged_groups)


ACTIVE_RETAILERS_TABLE_SQL = """
CREATE TABLE active_retailers (
    retailer    TEXT    PRIMARY KEY,
    position    INTEGER NOT NULL
)
"""


def migrate_add_active_retailers_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create active_retailers (additive, create-if-missing).

    The dashboard reads it to list a retailer that has never written a row (R1).
    """
    if check_table_exists(conn, "active_retailers"):
        LOGGER.info("  [SKIP] active_retailers table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create active_retailers table")
        return
    LOGGER.info("  [MIGRATE] Creating active_retailers table...")
    conn.execute(ACTIVE_RETAILERS_TABLE_SQL)
    conn.commit()
    LOGGER.info("  [OK] active_retailers table created")


SCRAPE_RUNS_TABLE_SQL = """
CREATE TABLE scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer     TEXT    NOT NULL,
    run_date     TEXT    NOT NULL,   -- YYYY-MM-DD, local: the snapshot_date calendar
    started_at   TEXT    NOT NULL,   -- local 'YYYY-MM-DDTHH:MM:SS'
    finished_at  TEXT    NOT NULL,
    status       TEXT    NOT NULL
                 CHECK (status IN ('ok', 'degraded', 'skipped', 'auth', 'failed', 'timeout')),
    exit_code    INTEGER,
    matched      INTEGER,            -- products matched this run; NULL when unknown
    detail       TEXT
)
"""

RUN_MARKERS_TABLE_SQL = """
CREATE TABLE run_markers (
    name        TEXT    NOT NULL,
    run_date    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (name, run_date)
)
"""


def migrate_add_scrape_runs_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create scrape_runs: one row per scraper run (#8 retry state, R3 freshness)."""
    if check_table_exists(conn, "scrape_runs"):
        LOGGER.info("  [SKIP] scrape_runs table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create scrape_runs table")
        return
    LOGGER.info("  [MIGRATE] Creating scrape_runs table...")
    conn.execute(SCRAPE_RUNS_TABLE_SQL)
    conn.execute("CREATE INDEX idx_scrape_runs_retailer_date ON scrape_runs (retailer, run_date)")
    conn.commit()
    LOGGER.info("  [OK] scrape_runs table created")


def migrate_add_run_markers_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create run_markers: once-per-day claims (digest, identical alerts) (#8)."""
    if check_table_exists(conn, "run_markers"):
        LOGGER.info("  [SKIP] run_markers table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create run_markers table")
        return
    LOGGER.info("  [MIGRATE] Creating run_markers table...")
    conn.execute(RUN_MARKERS_TABLE_SQL)
    conn.commit()
    LOGGER.info("  [OK] run_markers table created")


DISCOVERY_TABLES_SQL = """
CREATE TABLE discovered_parts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT    NOT NULL CHECK (category IN ('cpu', 'gpu')),
    part_key        TEXT    NOT NULL,
    display_name    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'untracked'
                    CHECK (status IN ('untracked', 'ignored', 'requested', 'tracked')),
    first_seen      TEXT    NOT NULL,
    last_seen       TEXT    NOT NULL,
    listing_count   INTEGER NOT NULL DEFAULT 0,
    retailers       TEXT    NOT NULL DEFAULT '',
    min_price       REAL,
    min_price_url   TEXT,
    sample_titles   TEXT    NOT NULL DEFAULT '[]',
    suggested_row   TEXT    NOT NULL,
    notified_at     TEXT,
    decided_at      TEXT,
    UNIQUE (category, part_key)
);
CREATE TABLE discovery_conflicts (
    listing_id        INTEGER PRIMARY KEY REFERENCES retailer_listings(id),
    retailer          TEXT    NOT NULL,
    filed_product_id  INTEGER NOT NULL REFERENCES products(id),
    title_key         TEXT,
    reason            TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    detected_on       TEXT    NOT NULL
);
CREATE TABLE discovery_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date              TEXT    NOT NULL,
    finished_at           TEXT    NOT NULL,
    catalogue_files       INTEGER NOT NULL,
    missing               TEXT    NOT NULL DEFAULT '[]',
    unrecognised_count    INTEGER NOT NULL DEFAULT 0,
    unrecognised_samples  TEXT    NOT NULL DEFAULT '[]'
)
"""


def migrate_add_discovery_tables(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create the discovery tables (#16): additive, create-if-missing per table."""
    statements = [s.strip() for s in DISCOVERY_TABLES_SQL.split(";") if s.strip()]
    for stmt in statements:
        name = stmt.split("CREATE TABLE", 1)[1].split("(", 1)[0].strip()
        if check_table_exists(conn, name):
            LOGGER.info("  [SKIP] %s table already exists", name)
            continue
        if dry_run:
            LOGGER.info("  [DRY-RUN] Would create %s table", name)
            continue
        LOGGER.info("  [MIGRATE] Creating %s table...", name)
        conn.execute(stmt)
        LOGGER.info("  [OK] %s table created", name)
    if not dry_run:
        conn.commit()


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

        # Migration: Create price_alerts table
        migrate_add_price_alerts_table(conn, dry_run=args.dry_run)

        # Migration: Backfill retailer_sku (key-based dedup anchor)
        migrate_backfill_retailer_sku(conn, dry_run=args.dry_run)

        # Migration: Merge duplicate listings forked by URL slug rewrites
        migrate_merge_duplicate_listings(conn, dry_run=args.dry_run)

        # Migration: Untrack products retired from the watchlist
        migrate_untrack_retired_products(conn, dry_run=args.dry_run)

        # Migration: Widen the retailer CHECK so a new retailer needs no rebuild
        migrate_widen_retailer_check(conn, dry_run=args.dry_run)

        # Migration: bookkeeping tables (Phase 3 robustness)
        migrate_add_active_retailers_table(conn, dry_run=args.dry_run)
        migrate_add_scrape_runs_table(conn, dry_run=args.dry_run)
        migrate_add_run_markers_table(conn, dry_run=args.dry_run)

        # Migration: discovery tables (#16)
        migrate_add_discovery_tables(conn, dry_run=args.dry_run)

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

            if check_table_exists(conn, "price_alerts"):
                LOGGER.info("  [OK] price_alerts table is present")
            else:
                LOGGER.error("  [ERROR] price_alerts table is missing")
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