"""Tests for export_snapshots — rebuilding data/*.json from the database.

The invariant under test: the JSON snapshots in ``data/`` must always be able
to rebuild the DB via ``ingest.py``. A partial scrape used to leave the JSON
short of the DB, which is how 165 snapshots (19-Aug and 21-Aug 2026 PCCG)
ended up existing in the DB alone.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import export_snapshots
from export_snapshots import (
    export_date,
    filename_for,
    json_keys,
    listing_keys,
    rows_for_date,
    run,
    snapshot_dates,
)
from ingest import ingest_file, init_db

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


@pytest.fixture
def conn(tmp_path):
    """A DB holding one CPU and one GPU listing per retailer, snapshotted twice."""
    path = tmp_path / "t.db"
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    c.execute(
        "INSERT INTO products (id, category, brand, model, generation_tier, tracked)"
        " VALUES (1, 'gpu', 'NVIDIA', 'GeForce RTX 5080', 'current', 1)"
    )
    c.execute(
        "INSERT INTO products (id, category, brand, model, generation_tier, tracked)"
        " VALUES (2, 'cpu', 'AMD', 'Ryzen 7 9800X3D', 'current', 1)"
    )
    c.execute(
        "INSERT INTO retailer_listings (id, product_id, retailer, retailer_sku, listing_url, variant_name)"
        " VALUES (1, 1, 'pccg', '68242', 'https://www.pccasegear.com/products/68242/gigabyte-rtx-5080',"
        " 'Gigabyte GeForce RTX 5080 Windforce')"
    )
    c.execute(
        "INSERT INTO retailer_listings (id, product_id, retailer, retailer_sku, listing_url, variant_name)"
        " VALUES (2, 2, 'pccg', '67543', 'https://www.pccasegear.com/products/67543/amd-9800x3d',"
        " 'AMD Ryzen 7 9800X3D Processor')"
    )
    for listing, price in ((1, 2499.0), (2, 649.0)):
        for day in ("2026-08-21", "2026-08-22"):
            c.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
                " VALUES (?, ?, ?, 'in_stock')",
                (listing, day, price),
            )
    c.commit()
    yield c
    c.close()


# ── Naming ────────────────────────────────────────────────────────────────

def test_filename_matches_the_scraper_convention():
    assert filename_for("gpu", "pccg", "2026-08-21") == "gpu_pccg_21_August_2026.json"


def test_exported_filename_round_trips_through_ingest():
    from ingest import parse_date_from_filename

    name = filename_for("cpu", "scorptec", "2026-08-09")
    assert parse_date_from_filename(name) == "2026-08-09"


# ── Grouping ──────────────────────────────────────────────────────────────

def test_rows_are_grouped_one_file_per_category_and_retailer(conn):
    groups = rows_for_date(conn, "2026-08-21")
    assert set(groups) == {("gpu", "pccg"), ("cpu", "pccg")}
    assert len(groups[("gpu", "pccg")]) == 1


def test_exported_products_carry_every_field_ingest_needs(conn):
    product = rows_for_date(conn, "2026-08-21")[("gpu", "pccg")][0]
    # These are exactly the keys ingest_file/find_or_create_product read.
    for key in ("url", "price_aud", "stock_status", "watchlist_model",
                "watchlist_category", "watchlist_brand", "watchlist_gen_tier",
                "scraped_name", "retailer"):
        assert key in product, key
    assert product["price_aud"] == 2499.0
    assert product["scraped_name"] == "Gigabyte GeForce RTX 5080 Windforce"


def test_snapshot_dates_are_sorted(conn):
    assert snapshot_dates(conn) == ["2026-08-21", "2026-08-22"]


# ── Listing keys ──────────────────────────────────────────────────────────

def test_listing_keys_match_on_sku_not_url():
    # The same PCCG listing under an old and a rewritten slug is one listing.
    old = [{"url": "https://www.pccasegear.com/products/68242"}]
    new = [{"url": "https://www.pccasegear.com/products/68242/gigabyte-rtx-5080"}]
    assert listing_keys(old, "pccg") == listing_keys(new, "pccg")


def test_json_keys_of_a_missing_file_is_empty(tmp_path):
    assert json_keys(tmp_path / "absent.json", "pccg") == set()


# ── Exporting ─────────────────────────────────────────────────────────────

def test_export_writes_one_file_per_group(conn, tmp_path):
    stats = export_date(conn, "2026-08-21", data_dir=tmp_path)

    assert stats["written"] == 2
    assert (tmp_path / "gpu_pccg_21_August_2026.json").exists()
    assert (tmp_path / "cpu_pccg_21_August_2026.json").exists()


def test_exported_file_has_the_scraper_envelope(conn, tmp_path):
    export_date(conn, "2026-08-21", data_dir=tmp_path)
    data = json.loads((tmp_path / "gpu_pccg_21_August_2026.json").read_text(encoding="utf-8"))

    assert set(data) == {
        "retailer", "scrape_date", "category", "total_watchlist",
        "matched", "unmatched_count", "unmatched_models", "products",
    }
    assert data["retailer"] == "pccg"
    assert data["scrape_date"] == "21_August_2026"
    assert data["matched"] == 1


def test_dry_run_reports_without_writing(conn, tmp_path):
    stats = export_date(conn, "2026-08-21", data_dir=tmp_path, dry_run=True)

    assert stats["written"] == 2
    assert list(tmp_path.glob("*.json")) == []


def test_repair_skips_groups_json_already_covers(conn, tmp_path):
    export_date(conn, "2026-08-21", data_dir=tmp_path)
    stats = export_date(conn, "2026-08-21", data_dir=tmp_path, repair_only=True)

    assert stats["written"] == 0
    assert stats["skipped"] == 2
    assert stats["recovered"] == 0


def test_repair_rewrites_a_file_that_lost_its_products(conn, tmp_path):
    """The 21-Aug PCCG regression: a good file clobbered by an empty re-run."""
    export_date(conn, "2026-08-21", data_dir=tmp_path)
    target = tmp_path / "gpu_pccg_21_August_2026.json"
    intact = tmp_path / "cpu_pccg_21_August_2026.json"
    target.write_text(json.dumps({
        "retailer": "pccg", "scrape_date": "21_August_2026", "category": "gpu",
        "total_watchlist": 100, "matched": 0, "unmatched_count": 0,
        "unmatched_models": [], "products": [],
    }), encoding="utf-8")

    stats = export_date(conn, "2026-08-21", data_dir=tmp_path, repair_only=True)

    # Only the clobbered file is rewritten; the intact one is left alone.
    assert stats["recovered"] == 1
    assert stats["written"] == 1
    assert stats["skipped"] == 1
    assert json.loads(target.read_text(encoding="utf-8"))["matched"] == 1
    assert json.loads(intact.read_text(encoding="utf-8"))["matched"] == 1


def test_repair_leaves_a_larger_stale_file_replaceable(conn, tmp_path):
    # export_snapshots deliberately bypasses the no-downgrade guard, because
    # the DB is authoritative when repairing.
    target = tmp_path / "gpu_pccg_21_August_2026.json"
    target.write_text(json.dumps({
        "retailer": "pccg", "category": "gpu", "matched": 99,
        "products": [{"url": f"https://www.pccasegear.com/products/{i}"} for i in range(99)],
    }), encoding="utf-8")

    export_date(conn, "2026-08-21", data_dir=tmp_path)

    assert json.loads(target.read_text(encoding="utf-8"))["matched"] == 1


def test_a_failed_write_leaves_no_tmp_debris(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(
        export_snapshots.json, "dump",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        export_date(conn, "2026-08-21", data_dir=tmp_path)

    assert list(tmp_path.glob("*.tmp")) == []


# ── The invariant: exports rebuild the DB ─────────────────────────────────

def test_an_exported_snapshot_ingests_back_into_an_identical_db(conn, tmp_path):
    export_date(conn, "2026-08-21", data_dir=tmp_path)
    export_date(conn, "2026-08-22", data_dir=tmp_path)

    rebuilt_path = tmp_path / "rebuilt.db"
    rebuilt = init_db(rebuilt_path)
    for f in sorted(tmp_path.glob("*_2026.json")):
        ingest_file(rebuilt, f)
    rebuilt.commit()

    original = dict(conn.execute(
        "SELECT snapshot_date, COUNT(*) FROM price_snapshots GROUP BY 1"
    ))
    copy = dict(rebuilt.execute(
        "SELECT snapshot_date, COUNT(*) FROM price_snapshots GROUP BY 1"
    ))
    rebuilt.close()

    assert copy == original


def test_run_exports_every_date_by_default(conn, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    totals = run(db_path=tmp_path / "t.db", data_dir=out)

    assert totals["written"] == 4  # 2 groups x 2 dates
    assert len(list(out.glob("*.json"))) == 4
