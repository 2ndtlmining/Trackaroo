# unit_testing/test_discover.py
"""discover.run end to end against a temp DB and temp catalogues (#16)."""
import json
import sqlite3
from datetime import date

import pytest

import discover
from ingest import init_db
from scraper.catalogue_io import catalogue_item, save_catalogue

TODAY = date(2026, 10, 2)
FD = "02_October_2026"

WATCHLIST = [
    {"category": "gpu", "brand": "AMD", "model": "Radeon RX 9070", "gen_tier": "current", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti", "gen_tier": "current", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti 8GB", "gen_tier": "current", "vram_gb": 8, "cores": None},
    {"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5600", "gen_tier": "current-2", "vram_gb": None, "cores": 6},
]


def _item(title, price=500.0, url=None):
    return catalogue_item(title, url or f"https://shop/{abs(hash(title))}", price, "in_stock", None)


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    conn.close()
    save_catalogue(tmp_path, "scorptec", "gpu", FD, [
        _item("Made Up RTX 6070 12GB", 999.0),
        _item("Sapphire Pulse RX 9070 GRE 12GB", 849.0),
        _item("Sapphire Pulse RX 9070 GRE 12GB OC", 869.0),
        _item("ASUS Prime RX 9070 16GB", 899.0),          # tracked
        _item("MSI RTX 5060 Ti 8G Ventus", 599.0),         # tracked (8GB row)
        _item("Gigabyte RTX 5060 Ti Eagle OC", 650.0),     # tracked chip, no VRAM in title
        _item("Gigabyte RTX 2060 6GB", 299.0),             # out of scope
        _item("Gigabyte Aorus RTX 5090 AI Box", 9999.0),   # excluded
        _item("Arctic MX-6 thermal paste", 12.0),          # unrecognised
    ])
    save_catalogue(tmp_path, "pccg", "gpu", FD, [_item("PowerColor Reaper RX 9070 GRE 12GB", 829.0)])
    save_catalogue(tmp_path, "scorptec", "cpu", FD, [_item("AMD Ryzen 5 5600GT", 189.0)])
    return tmp_path, db_path


def _run(env, **kw):
    data_dir, db_path = env
    return discover.run(db_path=db_path, data_dir=data_dir, today=kw.pop("today", TODAY),
                        watchlist=WATCHLIST, **kw)


def _parts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return {r["part_key"]: dict(r) for r in conn.execute("SELECT * FROM discovered_parts")}


def test_fixture_yields_made_up_and_real_parts(env):
    summary = _run(env)
    parts = _parts(env[1])
    assert set(parts) == {"rtx 6070|12", "rx 9070 gre|12", "ryzen 5600gt"}
    gre = parts["rx 9070 gre|12"]
    assert gre["display_name"] == "Radeon RX 9070 GRE 12GB"
    assert gre["listing_count"] == 3 and gre["retailers"] == "pccg,scorptec"
    assert gre["min_price"] == 829.0
    assert gre["first_seen"] == "2026-10-02" and gre["status"] == "untracked"
    assert len(json.loads(gre["sample_titles"])) == 3
    assert summary["untracked"] == 3 and summary["new_today"] == 3


def test_tracked_products_never_appear(env):
    _run(env)
    keys = set(_parts(env[1]))
    assert "rx 9070|16" not in keys
    assert not any(k.startswith("rtx 5060 ti") for k in keys)


def test_run_records_missing_and_unrecognised(env):
    summary = _run(env)
    conn = sqlite3.connect(env[1])
    row = conn.execute("SELECT catalogue_files, missing, unrecognised_count, unrecognised_samples FROM discovery_runs").fetchone()
    assert row[0] == 3
    assert "umart/gpu" in json.loads(row[1]) and "pccg/cpu" in json.loads(row[1])
    assert row[2] == 1 and json.loads(row[3]) == ["Arctic MX-6 thermal paste"]
    assert "umart/cpu" in summary["missing"]


def test_upsert_keeps_decisions(env):
    _run(env)
    conn = sqlite3.connect(env[1])
    conn.execute("UPDATE discovered_parts SET status='ignored', decided_at='2026-10-02T09:00:00', notified_at='x'"
                 " WHERE part_key='ryzen 5600gt'")
    conn.commit()
    _run(env, today=date(2026, 10, 3))  # no catalogues for the 3rd: no upsert
    data_dir, _ = env
    save_catalogue(data_dir, "scorptec", "cpu", "03_October_2026", [_item("AMD Ryzen 5 5600GT", 179.0)])
    _run(env, today=date(2026, 10, 3))
    row = _parts(env[1])["ryzen 5600gt"]
    assert (row["status"], row["decided_at"], row["notified_at"]) == ("ignored", "2026-10-02T09:00:00", "x")
    assert row["last_seen"] == "2026-10-03" and row["min_price"] == 179.0 and row["first_seen"] == "2026-10-02"


def test_requested_part_flips_to_tracked_once_watchlist_has_it(env):
    _run(env)
    conn = sqlite3.connect(env[1])
    conn.execute("UPDATE discovered_parts SET status='requested' WHERE part_key='ryzen 5600gt'")
    conn.commit()
    wl = WATCHLIST + [{"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5600GT", "gen_tier": "current-2",
                       "vram_gb": None, "cores": 6}]
    discover.run(db_path=env[1], data_dir=env[0], today=TODAY, watchlist=wl)
    assert _parts(env[1])["ryzen 5600gt"]["status"] == "tracked"


def test_no_catalogues_keeps_previous_results(env, tmp_path):
    _run(env)
    summary = discover.run(db_path=env[1], data_dir=tmp_path / "empty", today=date(2026, 10, 3), watchlist=WATCHLIST)
    assert summary["catalogue_files"] == 0
    assert len(_parts(env[1])) == 3


def _add_listing(db_path, model, title, vram=None, brand="AMD", category="gpu"):
    conn = sqlite3.connect(db_path)
    pid = conn.execute("INSERT INTO products (category, brand, model, vram_gb, generation_tier) VALUES (?,?,?,?,?)",
                       (category, brand, model, vram, "current")).lastrowid
    lid = conn.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?,?,?,?)",
                       (pid, "scorptec", title, f"https://s/{pid}")).lastrowid
    conn.commit()
    return lid


def test_misfiled_listing_is_a_conflict(env):
    lid = _add_listing(env[1], "Radeon RX 9070", "Sapphire Pulse RX 9070 GRE 12GB", vram=16)
    _run(env)
    rows = sqlite3.connect(env[1]).execute("SELECT listing_id, title_key, reason FROM discovery_conflicts").fetchall()
    assert rows == [(lid, "rx 9070 gre", "title names rx 9070 gre, product is rx 9070")]


def test_vram_mismatch_is_a_conflict(env):
    _add_listing(env[1], "GeForce RTX 5060 Ti", "MSI RTX 5060 Ti 8G Ventus", vram=16, brand="NVIDIA")
    _run(env)
    reason = sqlite3.connect(env[1]).execute("SELECT reason FROM discovery_conflicts").fetchone()[0]
    assert reason == "title says 8GB, product is 16GB"


def test_conflict_ignores_title_without_vram(env):
    _add_listing(env[1], "GeForce RTX 5060 Ti", "Gigabyte RTX 5060 Ti Eagle OC", vram=16, brand="NVIDIA")
    _run(env)
    assert sqlite3.connect(env[1]).execute("SELECT COUNT(*) FROM discovery_conflicts").fetchone()[0] == 0


def test_unmatched_placeholders_are_not_conflicts_and_seed_first_seen(env):
    conn = sqlite3.connect(env[1])
    pid = conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu','Unmatched','Unmatched CPU listing',0)").lastrowid
    lid = conn.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?, 'scorptec', 'amd ryzen 5 5600gt desktop processor', 'https://s/gt')", (pid,)).lastrowid
    conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, '2026-08-09', 199.0, 'in_stock')", (lid,))
    conn.commit()
    _run(env)
    assert sqlite3.connect(env[1]).execute("SELECT COUNT(*) FROM discovery_conflicts").fetchone()[0] == 0
    assert _parts(env[1])["ryzen 5600gt"]["first_seen"] == "2026-08-09"


def test_creates_its_tables_on_an_old_db(tmp_path):
    db_path = tmp_path / "old.db"
    conn = init_db(db_path)
    for t in ("discovered_parts", "discovery_conflicts", "discovery_runs"):
        conn.execute(f"DROP TABLE {t}")
    conn.commit(); conn.close()
    discover.run(db_path=db_path, data_dir=tmp_path, today=TODAY, watchlist=WATCHLIST)
    names = {r[0] for r in sqlite3.connect(db_path).execute("SELECT name FROM sqlite_master")}
    assert "discovered_parts" in names


def test_prunes_old_catalogues(env):
    data_dir, _ = env
    save_catalogue(data_dir, "umart", "gpu", "01_August_2026", [])
    _run(env)
    assert not (data_dir / "catalogue" / "umart_gpu_01_August_2026.json").exists()
