"""
Tests for backfill_msrp — curated launch-MSRP backfill for the specs table.

Covers:
- load_mapping validation (structure, price types)
- apply_mapping: sets MSRP, idempotency, unmatched keys, unset leftovers
- main: dry-run no-writes, real run writes
"""
import json
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backfill_msrp as bm


def _insert_product(db, category, brand, model):
    cur = db.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 1)",
        (category, brand, model),
    )
    return cur.lastrowid


def _insert_spec(db, product_id, source="amd-com"):
    db.execute(
        "INSERT INTO specs (product_id, source, source_record_key, category, "
        "raw_json, last_synced_at) VALUES (?, ?, ?, 'cpu', '{}', '2026-08-19T00:00:00Z')",
        (product_id, source, f"record-{product_id}"),
    )


def _spec_msrp(db, product_id):
    return db.execute(
        "SELECT launch_msrp_usd FROM specs WHERE product_id = ?", (product_id,)
    ).fetchone()[0]


def _write_mapping(tmp_path, data):
    path = tmp_path / "msrp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── load_mapping ─────────────────────────────────────────────────────

def test_load_mapping_returns_numbers(tmp_path):
    path = _write_mapping(tmp_path, {"Ryzen 7 9800X3D": 479, "RTX 5090": 1999.0})
    mapping = bm.load_mapping(path)
    assert mapping == {"Ryzen 7 9800X3D": 479.0, "RTX 5090": 1999.0}


def test_load_mapping_rejects_non_object(tmp_path):
    path = _write_mapping(tmp_path, [1, 2, 3])
    with pytest.raises(ValueError):
        bm.load_mapping(path)


def test_load_mapping_rejects_non_positive_prices(tmp_path):
    path = _write_mapping(tmp_path, {"RTX 5090": 0})
    with pytest.raises(ValueError):
        bm.load_mapping(path)


def test_load_mapping_rejects_non_numeric_price(tmp_path):
    path = _write_mapping(tmp_path, {"RTX 5090": "free"})
    with pytest.raises(ValueError):
        bm.load_mapping(path)


# ── apply_mapping ────────────────────────────────────────────────────

def test_sets_msrp_for_matching_products(db):
    pid = _insert_product(db, "cpu", "AMD", "Ryzen 7 9800X3D")
    _insert_spec(db, pid)
    updated, unmatched, unset = bm.apply_mapping(db, {"Ryzen 7 9800X3D": 479})
    assert updated == 1
    assert _spec_msrp(db, pid) == 479.0
    assert unmatched == set()
    assert unset == set()


def test_is_idempotent_on_rerun(db):
    pid = _insert_product(db, "cpu", "AMD", "Ryzen 7 9800X3D")
    _insert_spec(db, pid)
    bm.apply_mapping(db, {"Ryzen 7 9800X3D": 479})
    updated, _, _ = bm.apply_mapping(db, {"Ryzen 7 9800X3D": 479})
    assert updated == 0
    assert _spec_msrp(db, pid) == 479.0


def test_reports_unmatched_keys(db):
    _insert_product(db, "cpu", "AMD", "Ryzen 7 9800X3D")
    _insert_spec(db, db.execute("SELECT id FROM products").fetchone()[0])
    updated, unmatched, _ = bm.apply_mapping(db, {"Ryzen 7 9800X3D": 479, "No Such CPU": 1})
    assert updated == 1
    assert unmatched == {"No Such CPU"}


def test_reports_models_still_missing_msrp(db):
    pid = _insert_product(db, "cpu", "AMD", "Ryzen 7 9800X3D")
    _insert_spec(db, pid)
    updated, _, unset = bm.apply_mapping(db, {})
    assert updated == 0
    assert unset == {"Ryzen 7 9800X3D"}


def test_leaves_untouched_products_without_spec_rows(db):
    pid = _insert_product(db, "cpu", "AMD", "Ryzen 7 9800X3D")
    updated, _, _ = bm.apply_mapping(db, {"Ryzen 7 9800X3D": 479})
    assert updated == 0
    assert db.execute("SELECT spec_id FROM specs").fetchone() is None


# ── main ─────────────────────────────────────────────────────────────

def _specs_count_msrp(db_path):
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute(
            "SELECT COUNT(*) FROM specs WHERE launch_msrp_usd IS NOT NULL"
        ).fetchone()[0]
    finally:
        con.close()


def test_main_dry_run_writes_nothing(db_path, tmp_path):
    con = sqlite3.connect(str(db_path))
    pid = con.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Ryzen 7 9800X3D', 1)"
    ).lastrowid
    con.execute(
        "INSERT INTO specs (product_id, source, source_record_key, category, "
        "raw_json, last_synced_at) VALUES (?, 'amd-com', 'x', 'cpu', '{}', '2026-08-19T00:00:00Z')",
        (pid,),
    )
    con.commit()
    con.close()
    mapping = _write_mapping(tmp_path, {"Ryzen 7 9800X3D": 479})

    with mock.patch.object(bm, "DB_PATH", db_path):
        bm.main(["--dry-run", "--json", str(mapping)])

    assert _specs_count_msrp(db_path) == 0


def test_main_writes_msrp(db_path, tmp_path):
    con = sqlite3.connect(str(db_path))
    pid = con.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Ryzen 7 9800X3D', 1)"
    ).lastrowid
    con.execute(
        "INSERT INTO specs (product_id, source, source_record_key, category, "
        "raw_json, last_synced_at) VALUES (?, 'amd-com', 'x', 'cpu', '{}', '2026-08-19T00:00:00Z')",
        (pid,),
    )
    con.commit()
    con.close()
    mapping = _write_mapping(tmp_path, {"Ryzen 7 9800X3D": 479})

    with mock.patch.object(bm, "DB_PATH", db_path):
        bm.main(["--json", str(mapping)])

    assert _specs_count_msrp(db_path) == 1
    con = sqlite3.connect(str(db_path))
    assert con.execute("SELECT launch_msrp_usd FROM specs").fetchone()[0] == 479.0
    con.close()


def test_main_exits_on_missing_mapping_file(db_path, tmp_path):
    with mock.patch.object(bm, "DB_PATH", db_path):
        with pytest.raises(SystemExit):
            bm.main(["--json", str(tmp_path / "missing.json")])