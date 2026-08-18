"""
Tests for the specs table — creation, columns, constraints.

Verifies that:
- The table exists with the expected 34 columns
- The idx_specs_product index exists
- The category CHECK constraint rejects invalid values
- UNIQUE (product_id, source) prevents duplicate rows per source
- The product_id foreign key is enforced
"""
import sqlite3

import pytest

EXPECTED_COLUMNS = {
    "spec_id", "product_id", "source", "source_record_key", "category",
    "architecture", "generation", "launch_date", "launch_msrp_usd",
    "vram_gb", "memory_bus_width_bit", "memory_type", "tdp_watts",
    "core_count", "thread_count", "base_clock_mhz", "boost_clock_mhz",
    "socket", "cache_l3_mb",
    "gpu_die", "bus_interface", "memory_bandwidth_gbps", "memory_clock_mhz",
    "process_nm", "foundry", "codename", "l1_cache_kb", "l2_cache_mb",
    "memory_speed_mhz", "memory_channels", "memory_types",
    "integrated_graphics",
    "raw_json", "last_synced_at",
}


def _insert_product(db, model="RTX 5070", category="gpu", brand="NVIDIA"):
    db.execute(
        "INSERT INTO products (category, brand, model) VALUES (?, ?, ?)",
        (category, brand, model),
    )
    return db.execute("SELECT id FROM products WHERE model = ?", (model,)).fetchone()[0]


def _insert_spec(db, product_id, source="rightnow-gpu-db", category="gpu"):
    db.execute(
        "INSERT INTO specs (product_id, source, source_record_key, category, raw_json, last_synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (product_id, source, "GeForce RTX 5070", category, "{}", "2026-08-16T00:00:00Z"),
    )


class TestSpecsTable:
    """Test specs table structure."""

    def test_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'specs'"
        ).fetchone()
        assert row is not None

    def test_expected_columns(self, db):
        columns = {r["name"] for r in db.execute("PRAGMA table_info(specs)").fetchall()}
        assert columns == EXPECTED_COLUMNS

    def test_index_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_specs_product'"
        ).fetchone()
        assert row is not None

    def test_valid_insert(self, db):
        pid = _insert_product(db)
        _insert_spec(db, pid)
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 1

    def test_gpu_row_with_gpu_fields(self, db):
        pid = _insert_product(db)
        db.execute(
            "INSERT INTO specs (product_id, source, source_record_key, category, "
            "vram_gb, memory_bus_width_bit, memory_type, tdp_watts, core_count, "
            "raw_json, last_synced_at) "
            "VALUES (?, 'rightnow-gpu-db', 'GeForce RTX 5070', 'gpu', 16, 256, 'GDDR7', "
            "300, 8960, '{}', '2026-08-16T00:00:00Z')",
            (pid,),
        )
        row = db.execute("SELECT * FROM specs WHERE product_id = ?", (pid,)).fetchone()
        assert row["vram_gb"] == 16
        assert row["memory_bus_width_bit"] == 256
        assert row["memory_type"] == "GDDR7"
        assert row["tdp_watts"] == 300
        assert row["core_count"] == 8960
        assert row["thread_count"] is None  # CPU-only field stays NULL on GPU rows


class TestSpecsConstraints:
    """Test specs table constraints."""

    def test_invalid_category_rejected(self, db):
        pid = _insert_product(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO specs (product_id, source, source_record_key, category, "
                "raw_json, last_synced_at) VALUES (?, 'rightnow-gpu-db', 'x', 'ram', '{}', "
                "'2026-08-16T00:00:00Z')",
                (pid,),
            )

    def test_duplicate_product_source_rejected(self, db):
        pid = _insert_product(db)
        _insert_spec(db, pid)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_spec(db, pid)

    def test_same_product_different_source_allowed(self, db):
        pid = _insert_product(db, model="Ryzen 7 9800X3D", category="cpu", brand="AMD")
        _insert_spec(db, pid, source="amd-com", category="cpu")
        _insert_spec(db, pid, source="intel-processors-csv", category="cpu")
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 2

    def test_raw_json_required(self, db):
        pid = _insert_product(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO specs (product_id, source, source_record_key, category, "
                "last_synced_at) VALUES (?, 'rightnow-gpu-db', 'x', 'gpu', "
                "'2026-08-16T00:00:00Z')",
                (pid,),
            )

    def test_last_synced_at_required(self, db):
        pid = _insert_product(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO specs (product_id, source, source_record_key, category, "
                "raw_json) VALUES (?, 'rightnow-gpu-db', 'x', 'gpu', '{}')",
                (pid,),
            )

    def test_fk_product_must_exist(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO specs (product_id, source, source_record_key, category, "
                "raw_json, last_synced_at) VALUES (99999, 'rightnow-gpu-db', 'x', 'gpu', "
                "'{}', '2026-08-16T00:00:00Z')"
            )
