"""
Create consistent, verified, timestamped backups of the Trackaroo database.

Uses the SQLite online-backup API (``Connection.backup()``), which produces a
crash-consistent snapshot even while the live database is in WAL mode and
being written. Every new backup is then checked with ``PRAGMA quick_check``;
a failure raises BackupIntegrityError and prunes nothing, so a silently
corrupted DB cannot rotate the good backups out (#10). The online-backup API
copies pages 1:1, so a corrupt live DB yields a failing backup: checking the
backup covers both.

Every backup is forced back to a self-contained rollback-journal file (not
WAL) before it is checked: the online-backup API copies the source's WAL flag
into the destination header, and without this fix-up every backup would leave
``-wal``/``-shm`` sidecars behind that ``BACKUP_NAME_RE`` never sees or prunes
(and WAL can fail outright on some network filesystems a mirror might sit on).

A backup that fails ``PRAGMA quick_check`` is renamed to ``<name>.db.corrupt``
-- kept on disk for forensics, but the ``.corrupt`` suffix drops it out of
``BACKUP_NAME_RE`` so it is never counted as a real backup, never mirrored,
never restored from, and never displaces a good same-day backup in retention.

Backups land in ``db/backups/`` (TRACKAROO_BACKUP_DIR) as
``trackaroo_2026-08-15_213000.db``. Retention is by age: the newest backup of
each of the last TRACKAROO_BACKUP_KEEP days, plus the 3 newest overall.
With TRACKAROO_BACKUP_MIRROR_DIR set (a NAS mount), each backup is also
copied there, verified, and pruned by the same rule; unset, nothing leaves
the host. The mirror directory must already exist (e.g. already mounted) --
Trackaroo never creates it, so an unmounted mount point fails loudly with
BackupMirrorError instead of silently receiving the "off-host" copy into a
plain local directory.

Usage:
    python backup_db.py                   # Backup to db/backups/, keep 14 days
    python backup_db.py --keep 30         # Keep 30 days
    python backup_db.py --mirror-dir /mnt/nas/trackaroo
    python backup_db.py --db-path db/trackaroo.db --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from config import BACKUP_DIR, BACKUP_KEEP, BACKUP_MIRROR_DIR, BUSY_TIMEOUT_MS, DB_PATH, setup_logging

LOGGER = logging.getLogger(__name__)

DEFAULT_KEEP = BACKUP_KEEP
BACKUP_SUFFIX = ".db"
BACKUP_PREFIX = "trackaroo_"
BACKUP_NAME_RE = re.compile(r"^trackaroo_(\d{4}-\d{2}-\d{2})_(\d{6})\.db$")
MIN_KEEP = 3


class BackupIntegrityError(RuntimeError):
    """A backup failed PRAGMA quick_check. Nothing was pruned (#10)."""


class BackupMirrorError(RuntimeError):
    """The off-host copy failed. The local backup is fine and was kept (#10)."""


def backup_timestamp() -> str:
    """Return the timestamp used in backup filenames (local time)."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def quick_check(path: Path) -> str:
    """``"ok"``, or SQLite's first complaints about ``path``. Opens read-only."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return f"cannot be read: {e}"
    if rows and rows[0][0] == "ok":
        return "ok"
    return "; ".join(str(r[0]) for r in rows[:5]) or "no result"


def list_backups(directory: Path) -> List[Path]:
    """Every ``trackaroo_*.db`` backup in ``directory``, oldest first.

    The one place that lists backups by name (#10 F11) -- ``prune_backups``,
    ``health_checks.check_backups`` and ``restore_drill.newest_backup`` all
    call this instead of each re-globbing and re-filtering the directory.
    Names sort chronologically, so this is also the newest-last order.
    A ``.corrupt``-quarantined file never matches ``BACKUP_NAME_RE`` and so is
    never returned. Returns ``[]`` if ``directory`` doesn't exist.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if BACKUP_NAME_RE.match(p.name)),
        key=lambda p: p.name,
    )


def _quarantine_corrupt(path: Path) -> Path:
    """Rename a backup that failed quick_check to ``<name>.corrupt``.

    Keeps it on disk for forensics while dropping it out of BACKUP_NAME_RE, so
    it can never again be counted as a real backup, mirrored, restored from,
    or allowed to displace a good same-day backup in retention (#10 I2).
    Returns the new path, or the original path if the rename itself failed.
    """
    corrupt = path.with_name(path.name + ".corrupt")
    try:
        path.rename(corrupt)
    except OSError:
        LOGGER.warning("Could not rename corrupt backup %s to %s - left in place", path, corrupt)
        return path
    return corrupt


def prune_backups(
    backup_dir: Path,
    keep_days: int,
    today: Optional[date] = None,
    min_keep: int = MIN_KEEP,
) -> List[Path]:
    """Keep the newest backup of each of the last ``keep_days`` days, plus the
    ``min_keep`` newest overall; delete every other ``trackaroo_*.db``.

    Files that don't match ``trackaroo_YYYY-MM-DD_HHMMSS.db`` are never touched.
    Returns the deleted paths.
    """
    today = today or date.today()
    dated = []
    for p in list_backups(backup_dir):
        m = BACKUP_NAME_RE.match(p.name)
        try:
            dated.append((p.name, date.fromisoformat(m.group(1)), p))
        except ValueError:
            continue  # regex-matched but not a real calendar date - never touched

    keep = {name for name, _, _ in dated[-min_keep:]} if min_keep > 0 else set()
    newest_per_day = {}
    for name, day, _ in dated:
        newest_per_day[day] = name  # later names overwrite: the newest wins
    cutoff = today - timedelta(days=keep_days)
    keep |= {name for day, name in newest_per_day.items() if day > cutoff}

    pruned = []
    for name, _, path in dated:
        if name not in keep:
            path.unlink()
            pruned.append(path)
    return pruned


def mirror_backup(
    backup: Path,
    mirror_dir: Path,
    keep_days: int = DEFAULT_KEEP,
    today: Optional[date] = None,
) -> Path:
    """Copy ``backup`` into ``mirror_dir`` (atomically), verify it, prune there.

    ``mirror_dir`` must already exist (#10 I3): an unmounted NAS mount point is
    just an empty local directory to the filesystem, so this never creates it
    -- creating it would let a backup silently land on local disk while an
    operator believes it went off-host.
    """
    if not mirror_dir.is_dir():
        raise BackupMirrorError(
            f"Mirror directory {mirror_dir} does not exist. Trackaroo never creates it -- "
            f"mount it (or create it) yourself first, so an unmounted NAS path fails loudly "
            f"instead of silently receiving the \"off-host\" copy on local disk.")
    target = mirror_dir / backup.name
    tmp = mirror_dir / f".{backup.name}.partial"
    try:
        shutil.copy2(backup, tmp)
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    verdict = quick_check(target)
    if verdict != "ok":
        corrupt = _quarantine_corrupt(target)
        raise BackupIntegrityError(
            f"mirror copy {target.name} failed quick_check: {verdict} - renamed to {corrupt.name} "
            f"(kept for forensics)")
    prune_backups(mirror_dir, keep_days, today=today)
    LOGGER.info("Backup mirrored to %s", target)
    return target


def backup_database(
    db_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    keep: int = DEFAULT_KEEP,
    mirror_dir: Optional[Path] = None,
    today: Optional[date] = None,
) -> Path:
    """Back up ``db_path`` into ``backup_dir``, verify it, prune, and mirror.

    Args:
        keep: Days of backups to retain (newest per day).
        mirror_dir: Off-host copy target; defaults to config.BACKUP_MIRROR_DIR
            (None = no mirror).

    Returns:
        Path of the new local backup.

    Raises:
        FileNotFoundError: the source DB does not exist.
        BackupIntegrityError: the new backup failed quick_check (nothing pruned).
        BackupMirrorError: the off-host copy failed (the local backup is kept).
    """
    src = Path(db_path or DB_PATH)
    out_dir = Path(backup_dir or BACKUP_DIR)

    if not src.exists():
        raise FileNotFoundError(f"Database not found at {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{BACKUP_PREFIX}{backup_timestamp()}{BACKUP_SUFFIX}"

    # A dedicated connection with a busy timeout, so a running writer does
    # not fault the copy; the online-backup API reads without exclusive locks.
    src_conn = sqlite3.connect(str(src))
    src_conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
            # The online-backup API copies the source's WAL flag into the
            # destination's header, so without this the backup would start in
            # WAL mode and leave -wal/-shm sidecars next to it that
            # BACKUP_NAME_RE never sees or prunes (#10 I1). Forcing a
            # rollback journal here checkpoints and removes them, leaving a
            # single self-contained .db file -- also safer to copy onto a
            # mirror filesystem that may not support WAL at all.
            dest_conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    verdict = quick_check(dest)
    if verdict != "ok":
        corrupt = _quarantine_corrupt(dest)
        LOGGER.error("Backup %s FAILED quick_check: %s - renamed to %s, nothing pruned",
                     dest, verdict, corrupt.name)
        raise BackupIntegrityError(
            f"{dest.name} failed PRAGMA quick_check: {verdict} - renamed to {corrupt.name} "
            f"(kept for forensics), older backups kept (nothing pruned)")

    size_mb = dest.stat().st_size / (1024 * 1024)
    LOGGER.info("Backup created: %s (%.2f MB, quick_check ok)", dest, size_mb)

    pruned = prune_backups(out_dir, keep, today=today)
    if pruned:
        LOGGER.info("Pruned %d old backup(s) (keep %d days)", len(pruned), keep)

    target = mirror_dir if mirror_dir is not None else BACKUP_MIRROR_DIR
    if target is not None:
        try:
            mirror_backup(dest, Path(target), keep_days=keep, today=today)
        except (OSError, BackupIntegrityError) as e:
            raise BackupMirrorError(f"Off-host copy to {target} failed: {e}") from e

    return dest


def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Backup the Trackaroo database")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="SQLite database to back up (default: config DB path)")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="Directory for backups (default: config backup dir)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help="Days of backups to retain (default: %(default)s)")
    parser.add_argument("--mirror-dir", type=Path, default=None,
                        help="Also copy the backup here (default: TRACKAROO_BACKUP_MIRROR_DIR)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs without writing any files")
    args = parser.parse_args(argv)

    src = Path(args.db_path or DB_PATH)
    out_dir = Path(args.backup_dir or BACKUP_DIR)

    if args.dry_run:
        LOGGER.info("DRY-RUN: would back up %s -> %s (keep %d days)", src, out_dir, args.keep)
        if not src.exists():
            LOGGER.error("Database not found at %s", src)
            sys.exit(1)
        return

    try:
        backup_database(db_path=src, backup_dir=out_dir, keep=args.keep, mirror_dir=args.mirror_dir)
    except (FileNotFoundError, BackupIntegrityError, BackupMirrorError) as e:
        LOGGER.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
