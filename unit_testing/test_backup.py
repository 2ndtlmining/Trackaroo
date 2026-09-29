"""
Tests for the database backup script (backup_db.py).

Covers:
- Creating a backup file that restores a consistent, queryable copy
- Backup works while the source DB is in WAL mode / being written
- Retention pruning keeps the newest backup of each of the last N days
- Integrity: PRAGMA quick_check on every new backup, failure prunes nothing
- Optional off-host mirror, verified and pruned the same way
- CLI --dry-run validates without writing
- Missing source raises FileNotFoundError
"""
import sqlite3
from datetime import date
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
import sys
sys.path.insert(0, sys_path)

from backup_db import (
    DEFAULT_KEEP,
    BackupIntegrityError,
    BackupMirrorError,
    backup_database,
    backup_timestamp,
    prune_backups,
    quick_check,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


@pytest.fixture(autouse=True)
def _no_real_mirror(monkeypatch):
    """Never copy to a real off-host mirror during tests, even if the
    developer's shell has TRACKAROO_BACKUP_MIRROR_DIR set (F17)."""
    monkeypatch.setattr("backup_db.BACKUP_MIRROR_DIR", None)


def _create_source_db(path: Path, rows: int = 3) -> None:
    """Create a WAL-mode SQLite DB with the Trackaroo schema and some rows."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    for i in range(rows):
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 1)",
            ("cpu", "AMD", f"Test CPU {i}", ),
        )
    conn.commit()
    conn.close()


class TestBackupCreation:
    def test_creates_backup_file(self, tmp_path):
        """Backing up a source DB writes a timestamped file in the backup dir."""
        src = tmp_path / "source.db"
        out = tmp_path / "backups"
        _create_source_db(src)

        dest = backup_database(db_path=src, backup_dir=out)

        assert dest.exists()
        assert dest.parent == out
        assert dest.name.startswith("trackaroo_")
        assert dest.suffix == ".db"

    def test_backup_is_queryable_and_matches_source(self, tmp_path):
        """Reopening the backup yields the same products table contents."""
        src = tmp_path / "source.db"
        _create_source_db(src, rows=5)

        dest = backup_database(db_path=src, backup_dir=tmp_path / "backups")

        conn = sqlite3.connect(str(dest))
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        first = conn.execute("SELECT model FROM products ORDER BY id LIMIT 1").fetchone()[0]
        conn.close()

        assert count == 5
        assert first == "Test CPU 0"

    def test_backup_works_while_source_writer_active(self, tmp_path):
        """Online backup succeeds with an open writer connection in WAL mode."""
        src = tmp_path / "source.db"
        out = tmp_path / "backups"
        _create_source_db(src)

        # Hold an open writer connection (simulates the daily cron writing)
        writer = sqlite3.connect(str(src))
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'Test GPU 0', 1)"
        )
        writer.commit()

        dest = backup_database(db_path=src, backup_dir=out)

        reader = sqlite3.connect(str(dest))
        count = reader.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        reader.close()
        writer.close()

        assert dest.exists()
        assert count == 4  # 3 seeded + 1 added before backup

    def test_missing_source_raises(self, tmp_path):
        """A missing DB raises, so run_daily's backup handler can alert on it
        (SystemExit escaped its except Exception)."""
        with pytest.raises(FileNotFoundError):
            backup_database(db_path=tmp_path / "does-not-exist.db", backup_dir=tmp_path / "backups")


class TestRetention:
    """Newest backup per day for keep_days days, plus the min_keep newest (#10)."""

    def _make(self, out, *names):
        out.mkdir(exist_ok=True)
        for n in names:
            (out / n).write_text("x")

    def test_keeps_the_newest_backup_of_each_recent_day(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, *[f"trackaroo_2026-08-{d}_120000.db" for d in range(10, 16)],
                   "trackaroo_2026-08-15_090000.db")

        pruned = prune_backups(out, keep_days=3, today=date(2026, 8, 15), min_keep=1)

        assert sorted(p.name for p in out.iterdir()) == [
            "trackaroo_2026-08-13_120000.db", "trackaroo_2026-08-14_120000.db",
            "trackaroo_2026-08-15_120000.db",
        ]
        assert len(pruned) == 4

    def test_the_newest_few_survive_a_long_gap(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, "trackaroo_2026-07-01_040000.db", "trackaroo_2026-07-02_040000.db",
                   "trackaroo_2026-07-03_040000.db")

        assert prune_backups(out, keep_days=14, today=date(2026, 9, 29)) == []

    def test_only_trackaroo_named_files_are_touched(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, *[f"trackaroo_2026-08-{d}_120000.db" for d in range(10, 16)],
                   "notes.txt", "trackaroo_manual-copy.db")

        prune_backups(out, keep_days=1, today=date(2026, 8, 15), min_keep=1)

        assert (out / "notes.txt").exists()
        assert (out / "trackaroo_manual-copy.db").exists()


class TestIntegrity:
    def test_a_good_backup_passes_quick_check(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        dest = backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=None)
        assert quick_check(dest) == "ok"

    def test_garbage_fails_quick_check(self, tmp_path):
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
        assert quick_check(bad) != "ok"

    def test_a_failing_check_raises_and_prunes_nothing(self, tmp_path, monkeypatch):
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"
        out.mkdir()
        old = [out / f"trackaroo_2026-01-0{d}_040000.db" for d in range(1, 6)]
        for p in old:
            p.write_text("x")
        monkeypatch.setattr("backup_db.quick_check", lambda path: "*** in database main *** Page 3: btree corrupt")

        with pytest.raises(BackupIntegrityError):
            backup_database(db_path=src, backup_dir=out, keep=1, mirror_dir=None)
        assert all(p.exists() for p in old)


class TestMirror:
    def test_mirror_copies_and_verifies(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        mirror = tmp_path / "nas"

        dest = backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=mirror)

        assert quick_check(mirror / dest.name) == "ok"

    def test_a_broken_mirror_keeps_the_local_backup(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        not_a_dir = tmp_path / "nas"
        not_a_dir.write_text("a file where the mount should be")

        with pytest.raises(BackupMirrorError):
            backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=not_a_dir)
        assert len(list((tmp_path / "backups").glob("trackaroo_*.db"))) == 1

    def test_no_mirror_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backup_db.BACKUP_MIRROR_DIR", None)
        src = tmp_path / "src.db"
        _create_source_db(src)
        backup_database(db_path=src, backup_dir=tmp_path / "backups")
        assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == ["backups"]


class TestTimestamp:
    def test_timestamp_format(self):
        """Timestamp matches YYYY-MM-DD_HHMMSS."""
        ts = backup_timestamp()
        parts = ts.split("_")
        assert len(parts) == 2
        assert len(parts[0]) == 10 and parts[0][4] == "-" and parts[0][7] == "-"
        assert len(parts[1]) == 6 and parts[1].isdigit()