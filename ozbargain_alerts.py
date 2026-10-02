"""Discord alerts for OzBargain deals that beat our best in-stock price (#34).

A matched, live deal alerts once (``alerted_at``) when its price is below the
product's best in-stock, non-bundle price on its latest snapshot date. With no
in-stock price it alerts too. ``alerted_at`` is set only after a send succeeds.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

import notify_discord
import ozbargain

LOGGER = logging.getLogger(__name__)
MAX_ALERTS_PER_POLL = 5

# Mirrors web/src/lib/server/queries/sql.ts notBundle().
_BEST_SQL = """
SELECT ps.price_aud, l.retailer
FROM price_snapshots ps
JOIN retailer_listings l ON l.id = ps.retailer_listing_id AND l.status = 'active'
JOIN products p ON p.id = l.product_id AND p.tracked = 1
WHERE l.product_id = :pid
  AND ps.snapshot_date = (SELECT MAX(snapshot_date) FROM price_snapshots)
  AND ps.stock_status = 'in_stock'
  AND lower(l.variant_name) NOT LIKE '%bundle%'
  AND lower(l.variant_name) NOT LIKE '%combo%'
  AND lower(l.listing_url) NOT LIKE '%bundle%'
  AND lower(l.listing_url) NOT LIKE '%bdl-%'
ORDER BY ps.price_aud ASC, l.retailer ASC
LIMIT 1
"""


def best_in_stock(conn: sqlite3.Connection, product_id: int) -> Optional[Tuple[float, str]]:
    """(price, retailer) of the cheapest active, in-stock, non-bundle listing on the
    GLOBAL latest snapshot date (as the web's cheapestListingPerProduct), or None."""
    row = conn.execute(_BEST_SQL, {"pid": product_id}).fetchone()
    return (row[0], row[1]) if row else None


def _product_name(conn: sqlite3.Connection, product_id: int) -> str:
    row = conn.execute("SELECT brand, model, vram_gb, category FROM products WHERE id = ?",
                       (product_id,)).fetchone()
    if row is None:
        return f"Product {product_id}"
    brand, model, vram, category = row[0], row[1], row[2], row[3]
    name = f"{brand} {model}"
    if category == "gpu" and vram:
        name += f" {vram}GB"
    return name


def alert_candidates(conn: sqlite3.Connection, now: datetime) -> List[dict]:
    """Deals due an alert, best value first (price / best asc, no-best last), capped."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=ozbargain.MELBOURNE)
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM ozb_deals WHERE product_id IS NOT NULL AND alerted_at IS NULL"
            " AND expired = 0 AND price_aud IS NOT NULL AND votes_pos - votes_neg >= 0"
            " ORDER BY node_id"
        ).fetchall()
        deals = [dict(r) for r in rows]
    finally:
        conn.row_factory = prev
    out: List[dict] = []
    for d in deals:
        if not ozbargain.is_live(d, now):
            continue
        best = best_in_stock(conn, d["product_id"])
        if best is not None and not d["price_aud"] < best[0]:
            continue
        d["best_price"], d["best_retailer"] = best if best else (None, None)
        d["product_name"] = _product_name(conn, d["product_id"])
        d["_ratio"] = d["price_aud"] / best[0] if best else None
        out.append(d)
    out.sort(key=lambda d: (d["_ratio"] is None, d["_ratio"] or 0.0, d["node_id"]))
    return out[:MAX_ALERTS_PER_POLL]


def _price(v: float) -> str:
    """Whole dollars when whole, else cents ($1,198.99 must not read as $1,199)."""
    return f"${v:,.2f}" if v % 1 else f"${v:,.0f}"


def build_embed(candidate: dict, base_url: str) -> dict:
    """One Discord embed for a deal (no emoji, never a /goto/ link)."""
    c = candidate
    title = f"OzBargain: {c['product_name']} {_price(c['price_aud'])}"
    if c.get("retailer"):
        title += f" at {c['retailer']}"
    if c.get("best_price") is not None:
        ours = (f"Our best today: {_price(c['best_price'])} at "
                f"{notify_discord.retailer_label(c['best_retailer'])}")
    else:
        ours = "Not in stock at our retailers"
    votes = f"+{c['votes_pos']} / \u2212{c['votes_neg']} votes"
    links = [f"[OzBargain deal]({c['url']})"]
    if base_url:
        links.append(f"[Trackaroo page]({base_url.rstrip('/')}/product/{c['product_id']})")
    return {
        "title": title,
        "color": notify_discord.DOWN_COLOR,
        "description": "\n".join([ours, votes, " \u00b7 ".join(links)]),
    }


def send_alerts(conn: sqlite3.Connection, now: datetime) -> int:
    """Send due alerts; stamp ``alerted_at`` per successful send. Returns the count sent."""
    notify_discord.load_dotenv()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return 0
    base_url = os.environ.get("TRACKAROO_PUBLIC_BASE_URL", "")
    sent = 0
    stamp = now.isoformat(timespec="seconds")
    for cand in alert_candidates(conn, now):
        try:
            ok = notify_discord.send_embed(webhook, build_embed(cand, base_url))
        except Exception as e:  # noqa: BLE001 - one bad send must not stop the rest
            LOGGER.warning("OzBargain alert for node %s failed: %s", cand["node_id"], type(e).__name__)
            continue
        if not ok:
            LOGGER.warning("OzBargain alert for node %s not delivered; will retry next poll", cand["node_id"])
            continue
        conn.execute("UPDATE ozb_deals SET alerted_at = ? WHERE node_id = ?", (stamp, cand["node_id"]))
        conn.commit()
        sent += 1
    return sent
