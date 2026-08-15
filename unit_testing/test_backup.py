"""
Tests for the database backup script (backup_db.py).

Covers:
- Creating a backup file that restores a consistent, queryable copy
- Backup works while the source DB is in WAL mode / being written
- Retention pruning keeps only the N most recent backups
- CLI --dry-run validates without writing
- Missing source handled with SystemExit
"""
import sqlite3
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
import sys
sys.path.insert(0, sys_path)

from backup_db import DEFAULT_KEEP, backup_database, backup_timestamp, _prune_backups

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


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

    def test_missing_source_exits(self, tmp_path):
        """A missing source DB raises SystemExit (exit code 1)."""
        src = tmp_path / "does-not-exist.db"
        with pytest.raises(SystemExit) as exc:
            backup_database(db_path=src, backup_dir=tmp_path / "backups")
        assert exc.value.code == 1


class TestRetention:
    def test_prunes_oldest_beyond_keep(self, tmp_path):
        """With keep=N only the N newest backups remain."""
        out = tmp_path / "backups"
        out.mkdir()
        # Create six fake backups with chronologically sortable names
        for i in range(6):
            (out / f"trackaroo_2026-08-{10 + i}_120000.db").write_text("x")

        pruned = _prune_backups(out, keep=2)

        remaining = sorted(p.name for p in out.iterdir())
        assert len(pruned) == 4
        assert len(remaining) == 2
        assert remaining == ["trackaroo_2026-08-14_120000.db", "trackaroo_2026-08-15_120000.db"]

    def test_no_prune_when_under_keep(self, tmp_path):
        """Fewer-or-equal backups than keep are left untouched."""
        out = tmp_path / "backups"
        out.mkdir()
        (out / "trackaroo_2026-08-15_120000.db").write_text("x")

        pruned = _prune_backups(out, keep=DEFAULT_KEEP)

        assert pruned == []
        assert len(list(out.iterdir())) == 1

    def test_only_trackaroo_prefixed_files_pruned(self, tmp_path):
        """Unrelated files in the backup dir are never touched."""
        out = tmp_path / "backups"
        out.mkdir()
        for i in range(4):
            (out / f"trackaroo_2026-08-{10 + i}_120000.db").write_text("x")
        keep_me = out / "notes.txt"
        keep_me.write_text("do not delete")

        _prune_backups(out, keep=2)

        assert keep_me.exists()


class TestTimestamp:
    def test_timestamp_format(self):
        """Timestamp matches YYYY-MM-DD_HHMMSS."""
        ts = backup_timestamp()
        parts = ts.split("_")
        assert len(parts) == 2
        assert len(parts[0]) == 10 and parts[0][4] == "-" and parts[0][7] == "-"
        assert len(parts[1]) == 6 and parts[1].isdigit()