"""
Tests for the historical DB migration tool (migrate.py).

Covers:
- check_column_exists / check_table_exists introspection helpers
- get_connection (missing DB -> SystemExit; WAL + FK pragmas applied)
- migrate_add_variant_name (adds column; dry-run no-op; idempotent skip)
- migrate_add_specs_table (creates table + index; dry-run no-op; idempotent skip)
- main() end-to-end on a legacy DB (dry-run vs full run)

The legacy schema below is the pre-12-Aug-2026 shape: retailer_listings
without the variant_name column, and no specs table.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import migrate
from migrate import (
    SPECS_EXTRA_COLUMNS,
    check_column_exists,
    check_table_exists,
    get_connection,
    main,
    migrate_add_specs_columns,
    migrate_add_specs_table,
    migrate_add_variant_name,
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
        finally:
            conn.close()

    def test_full_run_applies_both_migrations(self, tmp_path, monkeypatch):
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
        finally:
            conn.close()
