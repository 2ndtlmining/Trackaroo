"""repair_listings: re-point mis-filed listings, never delete a snapshot (#1, #2)."""
import sqlite3
from pathlib import Path

import pytest

import repair_listings as rl
from scraper.chip_key import Matcher  # noqa: F401  (import check)

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

WATCHLIST = [
    {"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5500", "vram_gb": None, "cores": 6},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti 8GB", "vram_gb": 8, "cores": None},
]


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    for wp in WATCHLIST:
        c.execute("INSERT INTO products (category, brand, model, vram_gb, cores) VALUES (?,?,?,?,?)",
                  (wp["category"], wp["brand"], wp["model"], wp["vram_gb"], wp["cores"]))
    pid = {m: i for i, m in c.execute("SELECT id, model FROM products")}
    rows = [
        (pid["Ryzen 5 5500"], "amd ryzen 5 5500 desktop processor"),     # correct
        (pid["Ryzen 5 5500"], "amd ryzen 5 5500gt desktop processor"),   # untracked sibling
        (pid["GeForce RTX 5060 Ti"], "palit geforce rtx 5060 ti dual 8g"),  # wrong variant
    ]
    for n, (product_id, title) in enumerate(rows):
        c.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?,?,?,?)",
                  (product_id, "scorptec", title, f"https://x/{n}"))
        c.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud) VALUES (last_insert_rowid(), '2026-09-01', 100)")
    c.commit()
    return c


def test_plan_finds_both_misfiles(conn):
    plan = rl.plan_repairs(conn, WATCHLIST)
    assert {(r.title, r.to_model) for r in plan} == {
        ("amd ryzen 5 5500gt desktop processor", None),
        ("palit geforce rtx 5060 ti dual 8g", "GeForce RTX 5060 Ti 8GB"),
    }


def test_apply_moves_listings_and_keeps_snapshots(conn):
    before = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    rl.apply_repairs(conn, rl.plan_repairs(conn, WATCHLIST))
    assert conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == before
    moved = dict(conn.execute(
        "SELECT l.variant_name, p.model FROM retailer_listings l JOIN products p ON p.id = l.product_id"))
    assert moved["palit geforce rtx 5060 ti dual 8g"] == "GeForce RTX 5060 Ti 8GB"
    assert moved["amd ryzen 5 5500gt desktop processor"] == "Unmatched CPU listing"
    status, tracked = conn.execute(
        "SELECT l.status, p.tracked FROM retailer_listings l JOIN products p ON p.id=l.product_id "
        "WHERE l.variant_name LIKE '%5500gt%'").fetchone()
    assert (status, tracked) == ("stale", 0)


def test_second_run_is_a_no_op(conn):
    rl.apply_repairs(conn, rl.plan_repairs(conn, WATCHLIST))
    assert rl.plan_repairs(conn, WATCHLIST) == []


def test_cli_defaults_to_dry_run(conn, tmp_path, capsys):
    conn.close()
    rl.main(["--db", str(tmp_path / "t.db")])
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "5500gt" in out
    c = sqlite3.connect(tmp_path / "t.db")
    assert c.execute("SELECT COUNT(*) FROM products WHERE brand='Unmatched'").fetchone()[0] == 0


def test_apply_repairs_preserves_delisted_status(conn):
    """M4 (28-Sep finding): parking a mis-filed listing must not erase that
    it was independently confirmed removed from the retailer's site --
    'delisted' carries real information 'stale' does not."""
    conn.execute(
        "UPDATE retailer_listings SET status = 'delisted' WHERE variant_name LIKE '%5500gt%'"
    )
    conn.commit()
    rl.apply_repairs(conn, rl.plan_repairs(conn, WATCHLIST))
    status = conn.execute(
        "SELECT status FROM retailer_listings WHERE variant_name LIKE '%5500gt%'"
    ).fetchone()[0]
    assert status == "delisted"


def test_product_id_forces_existing_holding_row_untracked(conn):
    """M2 (28-Sep finding): a holding product rebuilt from exported JSON via
    ingest.py's find_or_create_product could end up tracked=1 (a pre-fix bug).
    _product_id(holding=True) must correct that back to 0 on an existing row,
    not just on rows it creates itself."""
    conn.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'Unmatched', 'Unmatched CPU listing', 1)"
    )
    conn.commit()
    pid = rl._product_id(conn, "cpu", "Unmatched CPU listing", holding=True)
    tracked = conn.execute("SELECT tracked FROM products WHERE id = ?", (pid,)).fetchone()[0]
    assert tracked == 0
