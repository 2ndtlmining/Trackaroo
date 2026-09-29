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
    mirror_backup,
    prune_backups,
    quick_check,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

# The autouse fixture that keeps every test off a real off-host mirror (even
# if the developer's shell has TRACKAROO_BACKUP_MIRROR_DIR set) now lives in
# conftest.py (_no_real_backup_mirror) so it covers every test file, not just
# this one (#10 F17/I4).


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

    def test_backup_leaves_no_wal_or_shm_sidecars(self, tmp_path):
        """The online-backup API copies the source's WAL flag into the
        destination header; without forcing it back to a rollback journal the
        backup dir would fill with -wal/-shm files BACKUP_NAME_RE never sees
        or prunes (#10 I1)."""
        src = tmp_path / "source.db"
        out = tmp_path / "backups"
        _create_source_db(src)

        backup_database(db_path=src, backup_dir=out, mirror_dir=None)

        names = sorted(p.name for p in out.iterdir())
        assert names, "expected at least the one backup file"
        assert all(n.startswith("trackaroo_") and n.endswith(".db") for n in names)
        assert all(not n.endswith(("-wal", "-shm")) for n in names)


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

    def test_a_failing_check_is_quarantined_not_left_under_a_valid_name(self, tmp_path, monkeypatch):
        """A corrupt backup must not sit under a name BACKUP_NAME_RE still
        matches: it would be reported OK by check_backups, picked by
        restore_drill, and counted (displacing a good same-day backup) by
        retention (#10 I2)."""
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"
        monkeypatch.setattr("backup_db.quick_check", lambda path: "*** in database main *** Page 3: btree corrupt")

        with pytest.raises(BackupIntegrityError) as exc:
            backup_database(db_path=src, backup_dir=out, mirror_dir=None)

        assert list(out.glob("trackaroo_*.db")) == []  # dropped out of BACKUP_NAME_RE
        [corrupt] = list(out.glob("trackaroo_*.db.corrupt"))
        assert corrupt.exists()  # kept on disk for forensics
        assert corrupt.name in str(exc.value)


class TestPartialBackupNeverKeepsAValidName:
    """final review M3: a backup that fails mid-copy (src_conn.backup() or
    the journal_mode pragma raises -- disk full, I/O error) must not leave
    the half-written file under a valid trackaroo_*.db name."""

    def _fake_connect_for_call(self, n, raising_conn_cls):
        """sqlite3.connect() is called twice inside backup_database: once for
        the source (call 1), once for the destination (call 2). sqlite3.
        Connection is an immutable C type -- individual methods can't be
        monkeypatched on the class or an instance -- so the target call is
        given a real on-disk connection through a subclass with the target
        method overridden (via connect's own `factory` param), which still
        creates the real file on disk exactly like production does."""
        real_connect = sqlite3.connect
        calls = {"n": 0}

        def fake_connect(path, *a, **k):
            calls["n"] += 1
            if calls["n"] == n:
                return real_connect(path, *a, factory=raising_conn_cls, **k)
            return real_connect(path, *a, **k)

        return fake_connect

    def test_a_raising_backup_call_leaves_no_file_under_a_valid_name(self, tmp_path, monkeypatch):
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"

        # Connection.backup(target) is a method of the SOURCE connection (the
        # one whose data is being copied) -- it is call 1, not the
        # destination's call 2.
        class _RaisingOnBackup(sqlite3.Connection):
            def backup(self, *a, **k):
                raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(
            "backup_db.sqlite3.connect", self._fake_connect_for_call(1, _RaisingOnBackup)
        )

        with pytest.raises(sqlite3.OperationalError):
            backup_database(db_path=src, backup_dir=out, mirror_dir=None)

        assert list(out.glob("trackaroo_*.db")) == []
        assert [p for p in out.iterdir() if p.is_file()] == []  # the partial was removed too

    def test_a_raising_journal_mode_pragma_leaves_no_file_under_a_valid_name(self, tmp_path, monkeypatch):
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"

        class _RaisingOnJournalMode(sqlite3.Connection):
            def execute(self, sql, *a, **k):
                if "journal_mode" in sql:
                    raise sqlite3.OperationalError("disk I/O error")
                return super().execute(sql, *a, **k)

        monkeypatch.setattr(
            "backup_db.sqlite3.connect", self._fake_connect_for_call(2, _RaisingOnJournalMode)
        )

        with pytest.raises(sqlite3.OperationalError):
            backup_database(db_path=src, backup_dir=out, mirror_dir=None)

        assert list(out.glob("trackaroo_*.db")) == []
        assert [p for p in out.iterdir() if p.is_file()] == []

    def test_a_successful_backup_is_still_findable_under_its_final_name(self, tmp_path):
        """The happy path must be unaffected by routing through a partial file."""
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"

        dest = backup_database(db_path=src, backup_dir=out, mirror_dir=None)

        assert dest.exists()
        assert dest.name in {p.name for p in out.iterdir()}
        assert [p for p in out.iterdir() if p.name.startswith(".")] == []  # no leftover partial


class TestMirror:
    def test_mirror_copies_and_verifies(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        mirror = tmp_path / "nas"
        mirror.mkdir()  # simulates the NAS mount already being in place (#10 I3)

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

    def test_mirror_dir_must_already_exist(self, tmp_path):
        """An unmounted NAS mount point is just an empty (or absent) local
        directory to the filesystem -- Trackaroo must never mkdir it, or the
        "off-host" copy silently lands on local disk instead (#10 I3)."""
        src = tmp_path / "src.db"
        _create_source_db(src)
        mirror = tmp_path / "unmounted-nas"  # deliberately never created

        with pytest.raises(BackupMirrorError) as exc:
            backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=mirror)

        assert not mirror.exists()  # never created as a side effect
        assert "does not exist" in str(exc.value)
        assert len(list((tmp_path / "backups").glob("trackaroo_*.db"))) == 1  # local backup kept

    def test_a_failing_mirror_check_is_quarantined(self, tmp_path, monkeypatch):
        """Same quarantine rule as the local backup (#10 I2), applied to the
        mirror copy: it must not sit under a name check_backups/restore_drill
        would treat as a real backup."""
        src = tmp_path / "src.db"
        _create_source_db(src)
        mirror = tmp_path / "nas"
        mirror.mkdir()

        real_quick_check = quick_check

        def fake_quick_check(path):
            # The local backup is real and must pass; only the mirror copy
            # should look corrupt, so the local-backup assertions below still
            # make sense.
            if Path(path).parent == mirror:
                return "*** in database main *** Page 1: btree corrupt"
            return real_quick_check(path)

        monkeypatch.setattr("backup_db.quick_check", fake_quick_check)

        with pytest.raises(BackupMirrorError):
            backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=mirror)

        assert list(mirror.glob("trackaroo_*.db")) == []  # dropped out of BACKUP_NAME_RE
        assert len(list(mirror.glob("trackaroo_*.db.corrupt"))) == 1  # kept for forensics
        assert len(list((tmp_path / "backups").glob("trackaroo_*.db"))) == 1  # local backup kept

    def test_a_failed_copy_cleans_up_the_partial_file(self, tmp_path):
        """A copy that fails partway (e.g. the NAS drops the connection) must
        not leave a stray .partial file behind (#10 minor). Calls
        mirror_backup directly so the failure (os.replace onto an existing
        directory) is real, not a monkeypatch of the shared os module."""
        src = tmp_path / "src.db"
        _create_source_db(src)
        backup = backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=None)
        mirror = tmp_path / "nas"
        mirror.mkdir()
        (mirror / backup.name).mkdir()  # occupies the target path so the copy must fail

        with pytest.raises(OSError):
            mirror_backup(backup, mirror)

        assert list(mirror.glob(f".{backup.name}.partial")) == []

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