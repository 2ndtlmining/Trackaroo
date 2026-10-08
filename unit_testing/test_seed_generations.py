"""seed.py: series/tracked sync, generations mirror, bulk guard (#17 #18)."""
import sqlite3

import pytest

from config import SCHEMA_PATH
from db.generations import parse_generations
from seed import BULK_FLIP_LIMIT, BulkChangeError, report_missing, seed_products, sync_generations

TOML_TODAY = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)" },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)" },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)" },
]
"""
TOML_ZEN6 = TOML_TODAY.replace('series = [\n', 'series = [\n  { key = "zen6", label = "Ryzen 10000 (Zen 6)" },\n', 1)


def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _rows(toml_text, statuses=None):
    """Products as load_watchlist_products() returns them, for 3 series x N models."""
    g = parse_generations(toml_text)
    models = {"zen5": ["R9 9950X", "R7 9700X"], "zen4": ["R7 7800X3D", "R5 8600G"],
              "zen3": ["R7 5800X", "R7 5700X", "R5 5600", "R5 5500", "R9 5900X", "R9 5950X", "R5 5600X", "R7 5800X3D"]}
    out = []
    for key, names in models.items():
        for m in names:
            status = (statuses or {}).get(m, "active")
            out.append({"category": "cpu", "brand": "AMD", "model": m, "vram_gb": None, "cores": 8,
                        "generation_tier": g.tier(key), "series": key,
                        "tracked": 1 if status == "active" and g.in_scope(key) else 0})
    return out


def _tracked(conn):
    return dict(conn.execute("SELECT model, tracked FROM products"))


def test_bulk_limit_is_flat():
    assert BULK_FLIP_LIMIT == 5


def test_rollover_on_prod_sized_db_needs_allow_bulk():
    """~112 products: the old max(5, 10%) limit was 11, so an 8-flip rollover slipped through."""
    conn = _db()
    for i in range(100):
        conn.execute("INSERT INTO products (category, brand, model, cores, generation_tier, tracked)"
                     " VALUES ('cpu', 'Intel', ?, 8, 'current', 1)", (f"Filler {i}",))
    conn.commit()
    seed_products(conn, _rows(TOML_TODAY))
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 112
    with pytest.raises(BulkChangeError) as exc:
        seed_products(conn, _rows(TOML_ZEN6))
    assert len(exc.value.flips) == 8 and exc.value.limit == 5
    assert all(t == 1 for t in _tracked(conn).values())
    stats = seed_products(conn, _rows(TOML_ZEN6), allow_bulk=True)
    assert len(stats["flips"]) == 8
    assert sum(1 for t in _tracked(conn).values() if t == 0) == 8


def test_zen6_rollover_retags_and_untracks_zen3_with_allow_bulk():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_ZEN6), allow_bulk=True)
    tiers = dict(conn.execute("SELECT model, generation_tier FROM products"))
    assert tiers["R9 9950X"] == "current-1" and tiers["R7 7800X3D"] == "current-2"
    assert tiers["R7 5800X"] == "current-2"  # retired keeps its last tier
    assert {m for m, t in _tracked(conn).items() if t == 0} == {
        "R7 5800X", "R7 5700X", "R5 5600", "R5 5500", "R9 5900X", "R9 5950X", "R5 5600X", "R7 5800X3D"}
    assert len(stats["flips"]) == 8


def test_bulk_change_refused_without_flag_and_nothing_written():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    with pytest.raises(BulkChangeError) as exc:
        seed_products(conn, _rows(TOML_ZEN6))
    assert len(exc.value.flips) == 8
    assert all(t == 1 for t in _tracked(conn).values())
    assert conn.execute("SELECT generation_tier FROM products WHERE model='R9 9950X'").fetchone()[0] == "current"


def test_dry_run_reports_flips_without_raising_or_writing():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_ZEN6), dry_run=True)
    assert len(stats["flips"]) == 8
    assert all(t == 1 for t in _tracked(conn).values())


def test_retire_and_unretire_one_product():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    seed_products(conn, _rows(TOML_TODAY, {"R7 5800X3D": "retired"}))
    assert _tracked(conn)["R7 5800X3D"] == 0
    seed_products(conn, _rows(TOML_TODAY))
    assert _tracked(conn)["R7 5800X3D"] == 1


def test_truncated_csv_is_not_a_retirement():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_TODAY)[:2])
    assert stats["flips"] == []
    assert all(t == 1 for t in _tracked(conn).values())
    assert len(report_missing(conn, _rows(TOML_TODAY)[:2])) == 10


def test_new_retired_row_is_inserted_untracked():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY, {"R5 5500": "retired"}))
    assert _tracked(conn)["R5 5500"] == 0


def test_series_is_written():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    assert conn.execute("SELECT series FROM products WHERE model='R5 8600G'").fetchone()[0] == "zen4"


def test_sync_generations_mirrors_the_toml():
    conn = _db()
    conn.execute("INSERT INTO generations VALUES ('stale', 'amd-cpu', 'Old', 9, 0)")
    sync_generations(conn, parse_generations(TOML_ZEN6))
    rows = conn.execute("SELECT series_key, label, position FROM generations ORDER BY position").fetchall()
    assert rows == [("zen6", "Ryzen 10000 (Zen 6)", 0), ("zen5", "Ryzen 9000 (Zen 5)", 1),
                    ("zen4", "Ryzen 7000 (Zen 4)", 2), ("zen3", "Ryzen 5000 (Zen 3)", 3)]


def test_first_seed_on_old_db_has_zero_flips(tmp_path, monkeypatch):
    """Prod's first boot: DB without products.series/generations; real CSV + toml."""
    import seed
    from db.watchlist import load_watchlist_products
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        brand TEXT NOT NULL, model TEXT NOT NULL, variant TEXT, vram_gb INTEGER, cores INTEGER,
        generation_tier TEXT, tracked INTEGER NOT NULL DEFAULT 1, last_snapshot_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))""")
    for p in load_watchlist_products():
        conn.execute("INSERT INTO products (category, brand, model, vram_gb, cores, generation_tier, tracked)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (p["category"], p["brand"], p["model"], p["vram_gb"], p["cores"],
                      p["generation_tier"] or "current", p["tracked"]))
    conn.commit()
    before = dict(conn.execute("SELECT model, tracked FROM products"))
    conn.close()
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    seed.main([])  # must not raise BulkChangeError / SystemExit
    conn = sqlite3.connect(str(db_path))
    assert dict(conn.execute("SELECT model, tracked FROM products")) == before  # zero flips
    assert conn.execute("SELECT COUNT(*) FROM products WHERE series IS NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] >= 14


def test_main_mirrors_generations_only_when_product_sync_applies(tmp_path, monkeypatch):
    """A refused rollover must leave the OLD generations mirror (labels follow products)."""
    import seed
    db_path = tmp_path / "t.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    seed.seed_products(conn, _rows(TOML_TODAY))
    sync_generations(conn, parse_generations(TOML_TODAY))
    conn.close()
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "load_generations", lambda: parse_generations(TOML_ZEN6))
    monkeypatch.setattr(seed, "load_watchlist", lambda *_a, **_k: _rows(TOML_ZEN6))

    def keys():
        c = sqlite3.connect(str(db_path))
        try:
            return {r[0] for r in c.execute("SELECT series_key FROM generations")}
        finally:
            c.close()

    with pytest.raises(SystemExit) as exc:
        seed.main([])
    assert exc.value.code == 1
    assert keys() == {"zen5", "zen4", "zen3"}
    seed.main(["--dry-run"])
    assert keys() == {"zen5", "zen4", "zen3"}
    seed.main(["--allow-bulk"])
    assert keys() == {"zen6", "zen5", "zen4", "zen3"}


def test_main_syncs_active_retailers_even_when_bulk_change_refused(tmp_path, monkeypatch):
    import seed
    db_path = tmp_path / "t.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    seed.seed_products(conn, _rows(TOML_TODAY))
    conn.close()
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "ACTIVE_RETAILERS", ["alpha", "beta"])
    monkeypatch.setattr(seed, "load_generations", lambda: parse_generations(TOML_ZEN6))
    monkeypatch.setattr(seed, "load_watchlist", lambda *_a, **_k: _rows(TOML_ZEN6))
    with pytest.raises(SystemExit):
        seed.main([])
    c = sqlite3.connect(str(db_path))
    try:
        got = [r[0] for r in c.execute("SELECT retailer FROM active_retailers ORDER BY position")]
    finally:
        c.close()
    assert got == ["alpha", "beta"]


def _db_with_requested_part(tmp_path):
    from ingest import init_db
    from migrate import migrate_add_discovery_tables
    db_path = tmp_path / "d.db"
    conn = init_db(db_path)
    migrate_add_discovery_tables(conn)
    conn.execute(
        """INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen,
               listing_count, retailers, sample_titles, suggested_row)
           VALUES ('cpu', 'ryzen 9850x3d', 'Ryzen 7 9850X3D', 'requested', '2026-10-01', '2026-10-08',
               3, 'scorptec', '["AMD Ryzen 7 9850X3D 8-Core Processor"]', 'x')"""
    )
    conn.commit()
    conn.close()
    return db_path


def _status(db_path):
    conn = sqlite3.connect(str(db_path))
    return conn.execute("SELECT status FROM discovered_parts WHERE part_key = 'ryzen 9850x3d'").fetchone()[0]


def test_main_flips_requested_parts_the_watchlist_now_tracks(tmp_path, monkeypatch):
    """#90: Requested clears when the deploy seeds the part, not at the next daily run."""
    import seed
    db_path = _db_with_requested_part(tmp_path)
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    seed.main(["--dry-run"])
    assert _status(db_path) == "requested"  # a dry run writes nothing
    seed.main([])
    assert _status(db_path) == "tracked"
