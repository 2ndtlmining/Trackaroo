"""Ready-to-retire list (#17): tracked products no retailer has listed lately.

Suggests only. Nothing here untracks a product; retirement stays a CSV change
(Retire on the Discover page writes a request, the owner edits the watchlist).
Any snapshot counts as "listed", out-of-stock included: the retailer still
carries the part.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_PATH, RETIRE_STALE_DAYS

LOGGER = logging.getLogger(__name__)

EMBED_MAX_LINES = 25

_STALE_SQL = """
WITH last AS (
  SELECT l.product_id, s.snapshot_date, l.retailer,
         ROW_NUMBER() OVER (PARTITION BY l.product_id ORDER BY s.snapshot_date DESC, l.retailer) AS rn
  FROM retailer_listings l JOIN price_snapshots s ON s.retailer_listing_id = l.id
)
SELECT p.id AS product_id, p.model, last.snapshot_date AS last_seen, last.retailer AS last_seen_retailer
FROM products p LEFT JOIN last ON last.product_id = p.id AND last.rn = 1
WHERE p.tracked = 1 AND p.brand != 'Unmatched'
  AND date(p.created_at) <= date(:today, '-' || :days || ' days')
  AND (last.snapshot_date IS NULL OR last.snapshot_date < date(:today, '-' || :days || ' days'))
ORDER BY p.model
"""


def find_stale(conn: sqlite3.Connection, today: date, stale_days: int) -> List[Dict[str, Any]]:
    """Tracked products whose newest snapshot (any retailer) is older than stale_days."""
    cur = conn.execute(_STALE_SQL, {"today": today.isoformat(), "days": stale_days})
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def update(conn: sqlite3.Connection, today: date, stale_days: int = RETIRE_STALE_DAYS) -> List[int]:
    """Sync retire_suggestions with the stale set; return the newly flagged product ids."""
    today_iso = today.isoformat()
    stale = find_stale(conn, today, stale_days)
    stale_ids = {r["product_id"] for r in stale}
    existing = {r[0] for r in conn.execute("SELECT product_id FROM retire_suggestions")}
    new_ids: List[int] = []
    try:
        # Retired products drop out whatever the decision was.
        conn.execute(
            "DELETE FROM retire_suggestions WHERE product_id IN (SELECT id FROM products WHERE tracked = 0)"
        )
        # Listed again: pending and kept clear; 'requested' stays until the CSV change lands.
        gone = [(pid,) for pid in existing if pid not in stale_ids]
        conn.executemany(
            "DELETE FROM retire_suggestions WHERE product_id = ? AND decision IN ('pending', 'kept')", gone
        )
        # A Keep expires: reopen without re-notifying (notified is left alone).
        conn.execute(
            "UPDATE retire_suggestions SET decision = 'pending', keep_until = NULL"
            " WHERE decision = 'kept' AND keep_until <= ?",
            (today_iso,),
        )
        for r in stale:
            if r["product_id"] in existing:
                conn.execute(
                    "UPDATE retire_suggestions SET last_seen = ?, last_seen_retailer = ? WHERE product_id = ?",
                    (r["last_seen"], r["last_seen_retailer"], r["product_id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO retire_suggestions (product_id, first_flagged, last_seen, last_seen_retailer)"
                    " VALUES (?, ?, ?, ?)",
                    (r["product_id"], today_iso, r["last_seen"], r["last_seen_retailer"]),
                )
                new_ids.append(r["product_id"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return new_ids


def _line(row) -> str:
    if not row["last_seen"]:
        return f"**{row['model']}**: never listed"
    from notify_discord import retailer_label

    d = datetime.strptime(row["last_seen"], "%Y-%m-%d")
    retailer = row["last_seen_retailer"] or ""
    shown = retailer_label(retailer) if retailer else "?"
    return f"**{row['model']}**: last seen {d.day} {d.strftime('%b')} at {shown}"


def build_embed(rows, base_url: str) -> dict:
    lines = [_line(r) for r in rows[:EMBED_MAX_LINES]]
    if len(rows) > EMBED_MAX_LINES:
        lines.append(f"...and {len(rows) - EMBED_MAX_LINES} more on the Discover page")
    embed = {
        "title": "Ready to retire",
        "description": "\n".join(lines) + "\n\nRetire or Keep each one on the Discover page.",
        "color": 0x64748B,
    }
    if base_url:
        embed["url"] = f"{base_url.rstrip('/')}/discover"
    return embed


def notify_new(conn: sqlite3.Connection) -> int:
    """Send pending suggestions never notified before; stamp them only on success."""
    import os
    import notify_discord

    notify_discord.load_dotenv()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return 0
    prior_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT r.product_id, p.model, r.last_seen, r.last_seen_retailer"
            " FROM retire_suggestions r JOIN products p ON p.id = r.product_id"
            " WHERE r.decision = 'pending' AND r.notified = 0 ORDER BY p.model"
        ).fetchall()
    finally:
        conn.row_factory = prior_factory
    if not rows:
        return 0
    base_url = os.environ.get("TRACKAROO_PUBLIC_BASE_URL", "")
    if not notify_discord.send_embed(webhook, build_embed(rows, base_url)):
        LOGGER.warning("Retire notice not delivered; it will be retried on the next run")
        return 0
    conn.executemany(
        "UPDATE retire_suggestions SET notified = 1 WHERE product_id = ?", [(r["product_id"],) for r in rows]
    )
    conn.commit()
    return len(rows)


def run(notify: bool = False, db_path: Optional[Path] = None, today: Optional[date] = None) -> Dict[str, Any]:
    db_path = Path(db_path) if db_path is not None else DB_PATH
    today = today or date.today()
    conn = sqlite3.connect(str(db_path))
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'retire_suggestions'"
        ).fetchone()
        if not has_table:
            return {"skipped": "no table"}
        flagged = update(conn, today)
        pending = conn.execute("SELECT COUNT(*) FROM retire_suggestions WHERE decision = 'pending'").fetchone()[0]
        notified = notify_new(conn) if notify else 0
    finally:
        conn.close()
    summary = {"flagged": len(flagged), "pending": pending, "notified": notified}
    LOGGER.info("Retire suggestions: %s", summary)
    return summary


if __name__ == "__main__":
    import json
    from config import setup_logging

    setup_logging()
    print(json.dumps(run(), indent=2))
