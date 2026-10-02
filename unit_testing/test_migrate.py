"""
Tests for the historical DB migration tool (migrate.py).

Covers:
- check_column_exists / check_table_exists introspection helpers
- get_connection (missing DB -> SystemExit; WAL + FK pragmas applied)
- migrate_add_variant_name (adds column; dry-run no-op; idempotent skip)
- migrate_add_specs_table (creates table + index; dry-run no-op; idempotent skip)
- migrate_add_price_alerts_table (creates table + indexes; dry-run no-op; idempotent skip)
- main() end-to-end on a legacy DB (dry-run vs full run)

The legacy schema below is the pre-12-Aug-2026 shape: retailer_listings
without the variant_name column, and no specs table.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import migrate
from migrate import (
    RETIRED_PRODUCTS,
    migrate_untrack_retired_products,
    SPECS_EXTRA_COLUMNS,
    check_column_exists,
    check_table_exists,
    get_connection,
    main,
    migrate_add_active_retailers_table,
    migrate_add_price_alerts_table,
    migrate_add_specs_columns,
    migrate_add_specs_table,
    migrate_add_variant_name,
    migrate_add_run_markers_table,
    migrate_add_scrape_runs_table,
    migrate_backfill_retailer_sku,
    migrate_merge_duplicate_listings,
    migrate_widen_retailer_check,
    PERMITTED_RETAILERS,
)

LEGACY_SCHEMA = """
CREATE TABLE products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT    NOT NULL CHECK (category IN ('cpu', 'gpu')),
    brand               TEXT    NOT NULL,
    model               TEXT    NOT NULL,
    variant             TEXT,
    vram_gb             INTEGER,
    cores               INTEGER,
    generation_tier     TEXT    CHECK (generation_tier IN ('current', 'current-1', 'current-2')),
    tracked             INTEGER NOT NULL DEFAULT 1,
    last_snapshot_at    TEXT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE retailer_listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id),
    retailer            TEXT    NOT NULL CHECK (retailer IN ('scorptec', 'pccg', 'mwave')),
    retailer_sku        TEXT,
    listing_url         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'active'
                                  CHECK (status IN ('active', 'delisted', 'stale')),
    first_seen_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at        TEXT,
    last_snapshot_at    TEXT,
    UNIQUE (retailer, listing_url)
);

CREATE TABLE price_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer_listing_id     INTEGER NOT NULL REFERENCES retailer_listings(id),
    snapshot_date           TEXT    NOT NULL,
    price_aud               REAL    NOT NULL,
    stock_status             TEXT    NOT NULL DEFAULT 'unknown'
                                  CHECK (stock_status IN ('in_stock', 'out_of_stock', 'preorder', 'unknown')),
    scraped_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (retailer_listing_id, snapshot_date)
);
"""


def _make_legacy_db(tmp_path):
    """A pre-12-Aug-2026 database: no variant_name column, no specs table."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO products (category, brand, model, generation_tier, tracked) "
        "VALUES ('cpu', 'AMD', 'Ryzen 7 9800X3D', 'current', 1)"
    )
    conn.execute(
        "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
        "VALUES (1, 'scorptec', 'https://scorptec.com.au/products/9800x3d', 'active')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
        "VALUES (1, '2026-08-10', 599.0, 'in_stock')"
    )
    conn.commit()
    conn.close()
    return path


class TestChecks:
    """Schema introspection helpers."""

    def test_check_column_exists(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            assert check_column_exists(conn, "retailer_listings", "variant_name") is False
            assert check_column_exists(conn, "retailer_listings", "listing_url") is True
            assert check_column_exists(conn, "products", "model") is True
        finally:
            conn.close()

    def test_check_table_exists(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            assert check_table_exists(conn, "specs") is False
            assert check_table_exists(conn, "products") is True
            assert check_table_exists(conn, "no_such_table") is False
        finally:
            conn.close()


class TestGetConnection:
    """Connection setup: missing file exits, pragmas applied."""

    def test_missing_db_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            get_connection(tmp_path / "nope.db")

    def test_sets_wal_and_foreign_keys(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()


class TestMigrateVariantName:
    """The variant_name column migration."""

    def test_adds_column(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_variant_name(conn)
            assert check_column_exists(conn, "retailer_listings", "variant_name") is True
            # Existing rows keep working and have NULL variant_name.
            row = conn.execute(
                "SELECT variant_name FROM retailer_listings WHERE id = 1"
            ).fetchone()
            assert row[0] is None
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_variant_name(conn, dry_run=True)
            assert check_column_exists(conn, "retailer_listings", "variant_name") is False
        finally:
            conn.close()

    def test_idempotent_when_column_present(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_variant_name(conn)
            # Second run must skip cleanly, not fail on the existing column.
            migrate_add_variant_name(conn)
            assert check_column_exists(conn, "retailer_listings", "variant_name") is True
        finally:
            conn.close()


class TestMigrateSpecsTable:
    """The specs table migration."""

    def test_creates_table_and_index(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_table(conn)
            assert check_table_exists(conn, "specs") is True
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_specs_product'"
            ).fetchone()
            assert idx is not None
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_table(conn, dry_run=True)
            assert check_table_exists(conn, "specs") is False
        finally:
            conn.close()

    def test_idempotent_when_table_present(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_table(conn)
            # Second run must skip cleanly, not fail on the existing table.
            migrate_add_specs_table(conn)
            assert check_table_exists(conn, "specs") is True
        finally:
            conn.close()


class TestMigrateSpecsColumns:
    """The TechPowerUp-grade spec column migration."""

    def _legacy_specs_db(self, tmp_path):
        """A DB with the pre-detail specs table (21 columns, no extras)."""
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_table(conn)
            # Simulate the pre-migration 21-column table by dropping the extras.
            for col in SPECS_EXTRA_COLUMNS:
                if check_column_exists(conn, "specs", col):
                    conn.execute(f"ALTER TABLE specs DROP COLUMN {col}")
            conn.commit()
        finally:
            conn.close()
        return path

    def test_adds_missing_columns(self, tmp_path):
        path = self._legacy_specs_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_columns(conn)
            for col in SPECS_EXTRA_COLUMNS:
                assert check_column_exists(conn, "specs", col) is True
            # Numeric columns must be REAL (not TEXT) so better-sqlite3 returns
            # numbers — a TEXT column would yield strings to the frontend.
            types = {
                r["name"]: r["type"].upper()
                for r in conn.execute("PRAGMA table_info(specs)").fetchall()
            }
            for col, decl in SPECS_EXTRA_COLUMNS.items():
                assert types[col] == decl.upper(), f"{col} is {types[col]}, want {decl}"
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = self._legacy_specs_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_columns(conn, dry_run=True)
            assert check_column_exists(conn, "specs", "gpu_die") is False
        finally:
            conn.close()

    def test_idempotent_when_columns_present(self, tmp_path):
        path = self._legacy_specs_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_columns(conn)
            migrate_add_specs_columns(conn)  # second run skips cleanly
            assert check_column_exists(conn, "specs", "gpu_die") is True
        finally:
            conn.close()

    def test_existing_rows_keep_null_extras(self, tmp_path):
        path = self._legacy_specs_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_specs_columns(conn)
            row = conn.execute("SELECT gpu_die, bus_interface FROM specs").fetchone()
            assert row is None  # table empty — added columns are nullable
        finally:
            conn.close()


class TestMigratePriceAlertsTable:
    """The price_alerts table migration."""

    def test_creates_table_and_indexes(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_price_alerts_table(conn)
            assert check_table_exists(conn, "price_alerts") is True
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name IN ('idx_price_alerts_product', 'idx_price_alerts_active')"
            ).fetchall()
            assert {r[0] for r in idx} == {"idx_price_alerts_product", "idx_price_alerts_active"}
            # Channel CHECK constraint must reject unknown channels.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO price_alerts (product_id, target_price, channel) "
                    "VALUES (1, 100.0, 'sms')"
                )
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_price_alerts_table(conn, dry_run=True)
            assert check_table_exists(conn, "price_alerts") is False
        finally:
            conn.close()

    def test_idempotent_when_table_present(self, tmp_path):
        path = _make_legacy_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_add_price_alerts_table(conn)
            # Second run must skip cleanly, not fail on the existing table.
            migrate_add_price_alerts_table(conn)
            assert check_table_exists(conn, "price_alerts") is True
        finally:
            conn.close()


def _seed_dup_db(tmp_path):
    """A DB with duplicate listings forked by a Scorptec URL slug rewrite.

    Listing 1 (short URL) has older snapshots; listing 2 (slug URL) has the
    freshest snapshot. Both share the numeric key 116356.
    """
    path = tmp_path / "dup.db"
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(LEGACY_SCHEMA)
    # Emulate the post-migration state the merge expects (variant_name present).
    conn.execute("ALTER TABLE retailer_listings ADD COLUMN variant_name TEXT")
    conn.execute(
        "INSERT INTO products (category, brand, model, generation_tier, tracked) "
        "VALUES ('gpu', 'NVIDIA', 'GeForce RTX 3050', 'current', 1)"
    )
    conn.execute(
        "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
        "VALUES (1, 'scorptec', 'https://www.scorptec.com.au/product/graphics-cards/nvidia/116356', 'active')"
    )
    conn.execute(
        "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
        "VALUES (1, 'scorptec', 'https://www.scorptec.com.au/product/graphics-cards/nvidia/116356-ne63050018je-1072f', 'active')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) "
        "VALUES (1, '2026-08-12', 379.0, 'in_stock', '2026-08-12T18:00:00Z')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) "
        "VALUES (1, '2026-08-13', 379.0, 'in_stock', '2026-08-13T18:00:00Z')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) "
        "VALUES (2, '2026-08-21', 269.0, 'in_stock', '2026-08-21T18:00:00Z')"
    )
    conn.commit()
    conn.close()
    return path


class TestMigrateBackfillSku:
    """retailer_sku backfill from the stable numeric URL key."""

    def test_backfills_matching_rows(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_backfill_retailer_sku(conn)
            rows = {
                r[0]: r[1]
                for r in conn.execute("SELECT id, retailer_sku FROM retailer_listings").fetchall()
            }
            assert rows[1] == "116356"
            assert rows[2] == "116356"
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_backfill_retailer_sku(conn, dry_run=True)
            rows = conn.execute(
                "SELECT retailer_sku FROM retailer_listings"
            ).fetchall()
            assert all(r[0] is None for r in rows)
        finally:
            conn.close()

    def test_skips_rows_without_a_key(self, tmp_path):
        path = _make_legacy_db(tmp_path)  # URL 'products/9800x3d' has no numeric key
        conn = get_connection(path)
        try:
            migrate_backfill_retailer_sku(conn)
            row = conn.execute("SELECT retailer_sku FROM retailer_listings WHERE id = 1").fetchone()
            assert row[0] is None
        finally:
            conn.close()


class TestMigrateMergeDuplicates:
    """Duplicate listing rows (URL slug forks) merge into one survivor."""

    def test_merges_duplicates(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_merge_duplicate_listings(conn)
            rows = conn.execute(
                "SELECT id, status, listing_url FROM retailer_listings ORDER BY id"
            ).fetchall()
            # One row stays active (the freshest — slug URL), one is retired.
            assert len(rows) == 2
            by_id = {r[0]: (r[1], r[2]) for r in rows}
            assert by_id[1][0] == "stale"
            assert by_id[2][0] == "active"
            # All three snapshots now live on the survivor (id 2).
            snaps = conn.execute(
                "SELECT snapshot_date FROM price_snapshots WHERE retailer_listing_id = 2 ORDER BY snapshot_date"
            ).fetchall()
            assert [s[0] for s in snaps] == ["2026-08-12", "2026-08-13", "2026-08-21"]
            # Survivor timestamps restored to the newest snapshot.
            survivor = conn.execute(
                "SELECT last_snapshot_at FROM retailer_listings WHERE id = 2"
            ).fetchone()[0]
            assert survivor == "2026-08-21T18:00:00Z"
        finally:
            conn.close()

    def test_idempotent_second_run(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_merge_duplicate_listings(conn)
            migrate_merge_duplicate_listings(conn)  # second run: no groups left
            active = conn.execute(
                "SELECT COUNT(*) FROM retailer_listings WHERE status = 'active'"
            ).fetchone()[0]
            assert active == 1
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            migrate_merge_duplicate_listings(conn, dry_run=True)
            active = conn.execute(
                "SELECT COUNT(*) FROM retailer_listings WHERE status = 'active'"
            ).fetchone()[0]
            assert active == 2  # nothing merged
            snaps = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
            assert snaps == 3
        finally:
            conn.close()

    def test_distinct_keys_are_left_alone(self, tmp_path):
        path = _seed_dup_db(tmp_path)
        conn = get_connection(path)
        try:
            # Add a second, unrelated listing with its own key.
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, retailer_sku, listing_url, status) "
                "VALUES (1, 'scorptec', NULL, 'https://www.scorptec.com.au/product/graphics-cards/nvidia/117192-ne7506t019p1-gb2062d', 'active')"
            )
            conn.commit()
            migrate_merge_duplicate_listings(conn)
            # The unrelated listing is untouched and still active.
            row = conn.execute(
                "SELECT status FROM retailer_listings WHERE listing_url LIKE '%117192%'"
            ).fetchone()
            assert row[0] == "active"
        finally:
            conn.close()


class TestMain:
    """End-to-end main() on a legacy DB file."""

    def _point_at_legacy_db(self, monkeypatch, tmp_path):
        """Redirect main()'s get_connection() to the legacy DB file.

        get_connection's default db_path is bound at import time, so patching
        migrate.DB_PATH alone is not enough — patch the function itself.
        """
        path = _make_legacy_db(tmp_path)
        monkeypatch.setattr(migrate, "get_connection", lambda: get_connection(path))
        return path

    def test_dry_run_makes_no_changes(self, tmp_path, monkeypatch):
        path = self._point_at_legacy_db(monkeypatch, tmp_path)
        main(["--dry-run"])

        conn = sqlite3.connect(str(path))
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(retailer_listings)")]
            assert "variant_name" not in cols
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )]
            assert "specs" not in tables
            assert "price_alerts" not in tables
        finally:
            conn.close()

    def test_full_run_applies_all_migrations(self, tmp_path, monkeypatch):
        path = self._point_at_legacy_db(monkeypatch, tmp_path)
        main([])

        conn = sqlite3.connect(str(path))
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(retailer_listings)")]
            assert "variant_name" in cols
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )]
            assert "specs" in tables
            assert "price_alerts" in tables
        finally:
            conn.close()


class TestMigrateUntrackRetiredProducts:
    """Products removed from watchlist.csv must also stop being tracked.

    seed.py only ever INSERTs, so deleting a watchlist row leaves the product
    tracked=1 in every existing DB. RX 9070 XTX is the first case: a card that
    was never released, so it can never have a listing and only inflates the
    dashboard's tracked count.
    """

    def _db(self, tmp_path, model="Radeon RX 9070 XTX", tracked=1):
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")
        )
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'AMD', ?, ?)",
            (model, tracked),
        )
        conn.commit()
        return conn

    def test_untracks_a_retired_product(self, tmp_path):
        conn = self._db(tmp_path)
        migrate_untrack_retired_products(conn)
        tracked = conn.execute(
            "SELECT tracked FROM products WHERE model = 'Radeon RX 9070 XTX'"
        ).fetchone()[0]
        assert tracked == 0

    def test_leaves_other_products_alone(self, tmp_path):
        conn = self._db(tmp_path, model="Radeon RX 9070 XT")
        migrate_untrack_retired_products(conn)
        tracked = conn.execute(
            "SELECT tracked FROM products WHERE model = 'Radeon RX 9070 XT'"
        ).fetchone()[0]
        assert tracked == 1

    def test_never_deletes_the_product_row(self, tmp_path):
        conn = self._db(tmp_path)
        migrate_untrack_retired_products(conn)
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1

    def test_dry_run_makes_no_change(self, tmp_path):
        conn = self._db(tmp_path)
        migrate_untrack_retired_products(conn, dry_run=True)
        tracked = conn.execute(
            "SELECT tracked FROM products WHERE model = 'Radeon RX 9070 XTX'"
        ).fetchone()[0]
        assert tracked == 1

    def test_idempotent(self, tmp_path):
        conn = self._db(tmp_path, tracked=0)
        migrate_untrack_retired_products(conn)
        tracked = conn.execute(
            "SELECT tracked FROM products WHERE model = 'Radeon RX 9070 XTX'"
        ).fetchone()[0]
        assert tracked == 0

    def test_missing_product_is_not_an_error(self, tmp_path):
        conn = self._db(tmp_path, model="GeForce RTX 5070")
        migrate_untrack_retired_products(conn)  # must not raise

    def test_retired_list_matches_the_watchlist(self):
        """Anything in RETIRED_PRODUCTS must be gone from watchlist.csv, or the
        next seed run would re-add it and the migration would fight the seed."""
        csv = (Path(__file__).resolve().parent.parent / "db" / "watchlist.csv").read_text(
            encoding="utf-8"
        )
        for model in RETIRED_PRODUCTS:
            assert f",{model}," not in csv, f"{model} is retired but still in watchlist.csv"


# ── Widening the retailer CHECK constraint ──────────────────────────

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


# The CHECK exactly as it shipped before 31-Aug-2026.
NARROW_RETAILER_CHECK = "CHECK (retailer IN ('scorptec', 'pccg', 'mwave'))"


def _current_schema_db(tmp_path):
    """A DB as it existed *before* this migration: the real shipped schema with
    the retailer CHECK wound back to its original three values.

    Built from db/schema.sql rather than LEGACY_SCHEMA because the migration has
    to survive the indexes, the foreign key from price_snapshots and the trigger
    that writes back to retailer_listings -- none of which the legacy fixture
    has. The CHECK is then narrowed again, because schema.sql now ships the wide
    form and a fixture that already permits umart would test nothing.
    """
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    wide = re.search(r"CHECK \(retailer IN \([^)]*\)\)", schema)
    assert wide, "retailer CHECK not found in db/schema.sql"
    schema = schema.replace(wide.group(0), NARROW_RETAILER_CHECK, 1)

    db = tmp_path / "current.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO products (category, brand, model, tracked) "
        "VALUES ('gpu', 'NVIDIA', 'RTX 5070', 1)"
    )
    conn.execute(
        "INSERT INTO retailer_listings (product_id, retailer, variant_name, "
        "retailer_sku, listing_url, status) "
        "VALUES (1, 'scorptec', 'ASUS Dual', 'SKU1', 'https://x/1', 'active')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
        "VALUES (1, '2026-08-30', 999.0, 'in_stock')"
    )
    conn.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
        "VALUES (1, '2026-08-31', 949.0, 'in_stock')"
    )
    conn.commit()
    return conn


class TestMigrateWidenRetailerCheck:
    """SQLite cannot ALTER a CHECK constraint, so this is a table rebuild.

    The constraint shipped as CHECK (retailer IN ('scorptec','pccg','mwave')),
    which rejects an umart INSERT outright. web/src/lib/types.ts:7 already
    declares all six retailers, so the database is the odd one out.
    """

    def test_rejects_umart_before_the_migration(self, tmp_path):
        """Guard: prove the constraint really does block the new retailer."""
        conn = _current_schema_db(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (1, 'umart', 'https://umart/1', 'active')"
            )
        conn.close()

    def test_accepts_every_permitted_retailer_after(self, tmp_path):
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        for i, slug in enumerate(PERMITTED_RETAILERS, start=10):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (1, ?, ?, 'active')",
                (slug, f"https://{slug}/{i}"),
            )
        conn.commit()
        got = {r[0] for r in conn.execute("SELECT DISTINCT retailer FROM retailer_listings")}
        assert set(PERMITTED_RETAILERS) <= got
        conn.close()

    def test_still_rejects_an_unknown_retailer(self, tmp_path):
        """Widening must not become 'anything goes' -- typos still have to fail."""
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (1, 'not-a-retailer', 'https://x/9', 'active')"
            )
        conn.close()

    def test_preserves_rows_and_their_columns(self, tmp_path):
        conn = _current_schema_db(tmp_path)
        before = conn.execute(
            "SELECT id, product_id, retailer, variant_name, retailer_sku, listing_url, status "
            "FROM retailer_listings"
        ).fetchall()
        migrate_widen_retailer_check(conn)
        after = conn.execute(
            "SELECT id, product_id, retailer, variant_name, retailer_sku, listing_url, status "
            "FROM retailer_listings"
        ).fetchall()
        assert after == before
        conn.close()

    def test_keeps_the_snapshots_attached_to_their_listing(self, tmp_path):
        """The rebuild drops and recreates the table the snapshots point at."""
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        rows = conn.execute(
            "SELECT ps.snapshot_date, ps.price_aud FROM price_snapshots ps "
            "JOIN retailer_listings rl ON ps.retailer_listing_id = rl.id "
            "ORDER BY ps.snapshot_date"
        ).fetchall()
        assert rows == [("2026-08-30", 999.0), ("2026-08-31", 949.0)]
        conn.close()

    def test_leaves_no_foreign_key_violations(self, tmp_path):
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.close()

    def test_restores_the_indexes(self, tmp_path):
        """Indexes are dropped with the old table and must be put back."""
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='retailer_listings'"
            )
        }
        assert "idx_retailer_listings_product" in names
        assert "idx_retailer_listings_status" in names
        conn.close()

    def test_is_idempotent(self, tmp_path):
        """It runs on every container start, so a second pass must be a no-op."""
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn)
        migrate_widen_retailer_check(conn)
        conn.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
            "VALUES (1, 'umart', 'https://umart/2', 'active')"
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 2
        conn.close()

    def test_dry_run_changes_nothing(self, tmp_path):
        conn = _current_schema_db(tmp_path)
        migrate_widen_retailer_check(conn, dry_run=True)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (1, 'umart', 'https://umart/1', 'active')"
            )
        conn.close()


class TestMigrateActiveRetailersTable:
    def test_creates_the_table(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            migrate_add_active_retailers_table(conn)
            assert check_table_exists(conn, "active_retailers")
            migrate_add_active_retailers_table(conn)  # idempotent
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            migrate_add_active_retailers_table(conn, dry_run=True)
            assert not check_table_exists(conn, "active_retailers")
        finally:
            conn.close()

    def test_schema_sql_creates_it_too(self, db):
        assert check_table_exists(db, "active_retailers")


class TestMigrateRetryTables:
    def test_creates_both_and_is_idempotent(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            for _ in range(2):
                migrate_add_scrape_runs_table(conn)
                migrate_add_run_markers_table(conn)
            assert check_table_exists(conn, "scrape_runs")
            assert check_table_exists(conn, "run_markers")
        finally:
            conn.close()


class TestDiscoveryTables:
    TABLES = ("discovered_parts", "discovery_conflicts", "discovery_runs")

    def _tables(self, conn):
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_creates_all_three_and_is_idempotent(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn)
        migrate.migrate_add_discovery_tables(conn)
        assert set(self.TABLES) <= self._tables(conn)

    def test_dry_run_creates_nothing(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn, dry_run=True)
        assert not (set(self.TABLES) & self._tables(conn))

    def test_schema_sql_creates_them_too(self, db):
        assert set(self.TABLES) <= self._tables(db)

    def test_status_check_rejects_unknown_status(self):
        import sqlite3
        import migrate
        import pytest
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen, suggested_row)"
                " VALUES ('gpu', 'rtx 5050|8', 'x', 'maybe', '2026-10-02', '2026-10-02', 'r')")


class TestFxRatesTable:
    def _tables(self, conn):
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_creates_and_is_idempotent(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_fx_rates_table(conn)
        migrate.migrate_add_fx_rates_table(conn)
        assert "fx_rates" in self._tables(conn)

    def test_dry_run_creates_nothing(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_fx_rates_table(conn, dry_run=True)
        assert "fx_rates" not in self._tables(conn)

    def test_schema_sql_creates_it_too(self, db):
        assert "fx_rates" in self._tables(db)

    def test_rejects_non_positive_rate(self):
        import sqlite3
        import migrate
        import pytest
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_fx_rates_table(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fx_rates VALUES ('2026-10-01', 0, 'rba', 'x')")
