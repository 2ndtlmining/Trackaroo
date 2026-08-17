"""
Create consistent, timestamped backups of the Trackaroo database.

Uses the SQLite online-backup API (``Connection.backup()``), which produces
a crash-consistent snapshot even while the live database is in WAL mode and
being written by the daily cron job. The reader side only needs a busy-timeout
for the brief window when a WAL checkpoint holds the write lock — it takes no
exclusive lock, so a running scrape can safely continue during a backup.

Backups land in ``db/backups/`` (configurable via ``TRACKAROO_BACKUP_DIR``)
with names like ``trackaroo_2026-08-15_213000.db``. Retention keeps the N
most recent backups and prunes the rest.

Usage:
    python backup_db.py                   # Backup to db/backups/, keep 14
    python backup_db.py --keep 30         # Retain 30 backups
    python backup_db.py --backup-dir /mnt/nas/backups
    python backup_db.py --db-path db/trackaroo.db --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from config import BACKUP_DIR, BACKUP_KEEP, BUSY_TIMEOUT_MS, DB_PATH

LOGGER = logging.getLogger(__name__)

DEFAULT_KEEP = BACKUP_KEEP
BACKUP_SUFFIX = ".db"
BACKUP_PREFIX = "trackaroo_"


def backup_timestamp() -> str:
    """Return the timestamp used in backup filenames (local time)."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def backup_database(
    db_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    keep: int = DEFAULT_KEEP,
) -> Path:
    """Copy ``db_path`` into ``backup_dir`` using the SQLite online-backup API.

    Args:
        db_path: SQLite database file to back up. Defaults to config.DB_PATH.
        backup_dir: Directory to write backups into. Defaults to config.BACKUP_DIR.
        keep: Number of most-recent backups to retain; older ones are pruned.

    Returns:
        Path of the newly created backup file.

    Raises:
        SystemExit: If the source database does not exist or cannot be opened.
    """
    src = Path(db_path or DB_PATH)
    out_dir = Path(backup_dir or BACKUP_DIR)

    if not src.exists():
        LOGGER.error("Database not found at %s", src)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{BACKUP_PREFIX}{backup_timestamp()}{BACKUP_SUFFIX}"

    # Use a dedicated connection with a busy timeout so a running writer does
    # not fault the copy; the online-backup API reads without exclusive locks.
    src_conn = sqlite3.connect(str(src))
    src_conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    size_mb = dest.stat().st_size / (1024 * 1024)
    LOGGER.info("Backup created: %s (%.2f MB)", dest, size_mb)

    pruned = _prune_backups(out_dir, keep)
    if pruned:
        LOGGER.info("Pruned %d old backup(s) (keep=%d)", len(pruned), keep)

    return dest


def _prune_backups(backup_dir: Path, keep: int) -> List[Path]:
    """Delete backups beyond the ``keep`` most recent.

    Only ``trackaroo_*.db`` files in the directory are considered — never other
    files. Returns the list of pruned paths.
    """
    candidates = sorted(
        (p for p in backup_dir.iterdir() if p.name.startswith(BACKUP_PREFIX) and p.suffix == BACKUP_SUFFIX),
        key=lambda p: p.name,  # Filenames sort chronologically (timestamped)
    )
    to_prune = candidates[:-keep] if keep >= 0 else []
    for path in to_prune:
        path.unlink()
    return to_prune


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Backup the Trackaroo database")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="SQLite database to back up (default: config DB path)")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="Directory for backups (default: config backup dir)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help="Number of backups to retain (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs without writing any files")
    args = parser.parse_args(argv)

    src = Path(args.db_path or DB_PATH)
    out_dir = Path(args.backup_dir or BACKUP_DIR)

    if args.dry_run:
        LOGGER.info("DRY-RUN: would back up %s -> %s (keep %d)", src, out_dir, args.keep)
        if not src.exists():
            LOGGER.error("Database not found at %s", src)
            sys.exit(1)
        return

    backup_database(db_path=src, backup_dir=out_dir, keep=args.keep)


if __name__ == "__main__":
    main()