"""The restore drill proves the newest backup restores and lost nothing (#10)."""
import sqlite3
from pathlib import Path

import restore_drill
from backup_db import backup_database

SCHEMA = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")


def _db(path, snapshots_on_day):
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'X', 1)")
    for i in range(snapshots_on_day):
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                     "VALUES (1, 'scorptec', ?, 'active')", (f"https://x/{i}",))
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                     "VALUES (?, '2026-09-28', 100, 'in_stock')", (i + 1,))
    conn.commit()
    conn.close()
    return path


def test_a_sound_backup_passes(tmp_path):
    live = _db(tmp_path / "live.db", 3)
    backup = backup_database(db_path=live, backup_dir=tmp_path / "backups", mirror_dir=None)

    assert restore_drill.drill(backup, live) == []
    assert restore_drill.newest_backup(tmp_path / "backups") == backup


def test_a_live_db_with_fewer_rows_than_the_backup_fails(tmp_path):
    backup = backup_database(db_path=_db(tmp_path / "old.db", 3),
                             backup_dir=tmp_path / "backups", mirror_dir=None)
    live = _db(tmp_path / "live.db", 2)

    [problem] = restore_drill.drill(backup, live)
    assert "2026-09-28" in problem


def test_a_corrupt_backup_fails(tmp_path):
    live = _db(tmp_path / "live.db", 1)
    bad = tmp_path / "trackaroo_2026-09-29_040000.db"
    bad.write_bytes(b"not a database")

    [problem] = restore_drill.drill(bad, live)
    assert "quick_check" in problem


def test_main_exits_1_without_backups(tmp_path):
    live = _db(tmp_path / "live.db", 1)
    assert restore_drill.main(["--backup-dir", str(tmp_path / "none"), "--db", str(live)]) == 1


def test_main_exits_0_on_a_sound_backup(tmp_path):
    live = _db(tmp_path / "live.db", 2)
    backup_database(db_path=live, backup_dir=tmp_path / "backups", mirror_dir=None)
    assert restore_drill.main(["--backup-dir", str(tmp_path / "backups"), "--db", str(live)]) == 0
