"""Restore drill: prove the newest backup restores, and that nothing was lost (#10).

Copies the newest db/backups/trackaroo_*.db to a temp file -- the live DB is
only ever opened read-only -- and checks:
  1. PRAGMA quick_check on the restored copy says ok;
  2. products, retailer_listings and price_snapshots are not empty;
  3. for every snapshot_date in the backup, the live DB holds at least as many
     snapshots (Trackaroo never deletes price data, so fewer means loss).
Exit 0 when all hold, 1 otherwise. Run it monthly; DEPLOYMENT.md -> Backups.

    python restore_drill.py
    python restore_drill.py --backup db/backups/trackaroo_2026-09-28_040512.db
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from backup_db import BACKUP_NAME_RE, quick_check
from config import BACKUP_DIR, DB_PATH, setup_logging

LOGGER = logging.getLogger(__name__)

TABLES = ("products", "retailer_listings", "price_snapshots")


def newest_backup(backup_dir: Path) -> Optional[Path]:
    if not backup_dir.is_dir():
        return None
    names = sorted(p.name for p in backup_dir.iterdir() if BACKUP_NAME_RE.match(p.name))
    return backup_dir / names[-1] if names else None


def _per_day(conn: sqlite3.Connection) -> Dict[str, int]:
    return dict(conn.execute(
        "SELECT snapshot_date, COUNT(*) FROM price_snapshots GROUP BY snapshot_date").fetchall())


def drill(backup: Path, live_db: Path) -> List[str]:
    """Restore ``backup`` to a temp file and compare it with ``live_db``.

    Returns:
        Problems found; an empty list means the drill passed.
    """
    problems: List[str] = []
    with tempfile.TemporaryDirectory(prefix="trackaroo-drill-") as tmp:
        restored = Path(tmp) / "restored.db"
        shutil.copy2(backup, restored)
        verdict = quick_check(restored)
        if verdict != "ok":
            return [f"quick_check failed on the restored copy of {backup.name}: {verdict}"]
        conn = sqlite3.connect(str(restored))
        try:
            for table in TABLES:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                LOGGER.info("  %-18s %d rows", table, n)
                if n == 0:
                    problems.append(f"{table} is empty in {backup.name}")
            restored_days = _per_day(conn)
        finally:
            conn.close()

    live = sqlite3.connect(f"file:{live_db.as_posix()}?mode=ro", uri=True)
    try:
        live_days = _per_day(live)
    finally:
        live.close()

    short = [d for d, n in sorted(restored_days.items()) if live_days.get(d, 0) < n]
    if short:
        problems.append(
            f"the live DB holds fewer snapshots than {backup.name} on {len(short)} day(s): "
            f"{', '.join(short[:5])}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Restore the newest backup to a temp file and verify it")
    parser.add_argument("--backup", type=Path, default=None, help="A specific backup file")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Default: config BACKUP_DIR")
    parser.add_argument("--db", type=Path, default=None, help="Live DB (read-only). Default: config DB_PATH")
    args = parser.parse_args(argv)

    backup = args.backup or newest_backup(Path(args.backup_dir or BACKUP_DIR))
    if backup is None:
        LOGGER.error("No backups found in %s", args.backup_dir or BACKUP_DIR)
        return 1
    live = Path(args.db or DB_PATH)
    if not live.exists():
        LOGGER.error("Live DB not found at %s", live)
        return 1

    LOGGER.info("Restore drill: %s", backup)
    problems = drill(Path(backup), live)
    for p in problems:
        LOGGER.error("  FAIL: %s", p)
    if problems:
        return 1
    LOGGER.info("Restore drill passed: %s restores cleanly and the live DB has lost nothing since.",
                Path(backup).name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
