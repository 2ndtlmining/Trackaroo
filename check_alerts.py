"""
Price-drop & restock alerts for Trackaroo.

Evaluates the user-configured rows in the ``price_alerts`` table against the
fresh prices just ingested, and notifies when a product's cheapest in-stock
price drops to or below the user's target (and optionally when an
out-of-stock product returns). Designed to run from run_daily.py after ingest,
or standalone for a manual check / preview.

An alert fires on a *price* signal when the product's cheapest in-stock price
is <= target_price. A cooldown prevents spam: an alert only re-fires when the
price is strictly lower than the price it last notified at (a sustained breach
at the same price is not re-announced; a further drop is). An alert fires on a
*restock* signal (notify_on_restock = 1) when a listing transitions from
out-of-stock to in-stock, rate-limited to at most once per RESTOCK_COOLDOWN_HOURS.
Price takes precedence over restock when both are true in the same run.

Delivery is all-stdlib and best-effort — a delivery failure is logged, never
raised, so a bad webhook can never break the daily pipeline. Each alert row's
``channel`` selects the mechanism, and every channel is env-gated: an
unconfigured channel is silently skipped.

Configuration (env, optional — see .env.example):

    TRACKAROO_DISCORD_WEBHOOK_URL   Discord webhook for channel='discord' alerts
    TRACKAROO_SMTP_HOST             SMTP host for channel='email' alerts
    TRACKAROO_SMTP_PORT             SMTP port (default: 587)
    TRACKAROO_SMTP_USERNAME         SMTP username (blank = no auth)
    TRACKAROO_SMTP_PASSWORD         SMTP password
    TRACKAROO_SMTP_FROM             From: address
    TRACKAROO_SMTP_TO               To: address
    TRACKAROO_ALERT_WEBHOOK_URL     Generic JSON webhook for channel='webhook'
    TRACKAROO_RESTOCK_COOLDOWN_HOURS  Minimum hours between restock re-fires (default: 24)
    TRACKAROO_NOTIFY_TIMEOUT_SECONDS  HTTP/SMTP delivery timeout (default: 10)

Usage:
    python check_alerts.py             # Evaluate + notify
    python check_alerts.py --dry-run   # Print what would fire without sending
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Dict, List, Optional

from config import DB_PATH, NOTIFY_TIMEOUT_SECONDS, RESTOCK_COOLDOWN_HOURS
from notify_discord import load_dotenv

LOGGER = logging.getLogger(__name__)

# Mirrors the dashboard's "cheapest in-stock variant" definition: the latest
# snapshot per active, non-bundle listing, across tracked products.
LATEST_SQL = """
WITH ranked AS (
    SELECT s.retailer_listing_id, s.snapshot_date, s.price_aud, s.stock_status,
           ROW_NUMBER() OVER (
               PARTITION BY s.retailer_listing_id
               ORDER BY s.snapshot_date DESC, s.id DESC
           ) AS rn
    FROM price_snapshots s
)
SELECT p.id AS product_id, p.category, p.brand, p.model,
       l.retailer, l.listing_url,
       cur.price_aud AS cur_price, cur.stock_status AS cur_status,
       prev.price_aud AS prev_price, prev.stock_status AS prev_status
FROM ranked cur
JOIN retailer_listings l ON l.id = cur.retailer_listing_id
JOIN products p ON p.id = l.product_id
LEFT JOIN ranked prev
       ON prev.retailer_listing_id = cur.retailer_listing_id AND prev.rn = 2
WHERE cur.rn = 1
  AND l.status = 'active'
  AND p.tracked = 1
  AND (l.variant_name IS NULL OR lower(l.variant_name) NOT LIKE '%bundle%')
  AND (l.variant_name IS NULL OR lower(l.variant_name) NOT LIKE '%combo%')
  AND lower(l.listing_url) NOT LIKE '%bundle%'
  AND lower(l.listing_url) NOT LIKE '%bdl-%'
"""

DOWN_COLOR = 0x34D399  # --down (teal/green) — a price drop is good news


def format_aud(value: float) -> str:
    """Format a price like the dashboard, e.g. 1049.0 -> '$1,049'."""
    return f"${value:,.0f}"


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, treating a missing offset as UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def query_active_alerts(conn: sqlite3.Connection) -> List[dict]:
    """Fetch every active alert row as a dict."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, product_id, target_price, channel, notify_on_restock, "
        "last_notified_at, last_notified_price "
        "FROM price_alerts WHERE active = 1"
    ).fetchall()
    return [dict(r) for r in rows]


def query_latest_rows(conn: sqlite3.Connection) -> List[dict]:
    """Fetch the latest (and previous) snapshot per active non-bundle listing."""
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(LATEST_SQL).fetchall()]


def aggregate_product_prices(rows: List[dict]) -> Dict[int, dict]:
    """Collapse per-listing rows into per-product current state.

    For each product computes the cheapest in-stock price (and the retailer /
    URL of that listing) plus whether any listing just restocked (latest
    in-stock with a previous out-of-stock snapshot).
    """
    products: Dict[int, dict] = {}
    for row in rows:
        pid = row["product_id"]
        prod = products.setdefault(
            pid,
            {
                "product_id": pid,
                "category": row["category"],
                "brand": row["brand"],
                "model": row["model"],
                "in_stock_price": None,
                "in_stock_retailer": None,
                "in_stock_url": None,
                "restock": False,
            },
        )
        if row["cur_status"] == "in_stock" and row["cur_price"] is not None:
            if prod["in_stock_price"] is None or row["cur_price"] < prod["in_stock_price"]:
                prod["in_stock_price"] = row["cur_price"]
                prod["in_stock_retailer"] = row["retailer"]
                prod["in_stock_url"] = row["listing_url"]
        if row["cur_status"] == "in_stock" and row["prev_status"] == "out_of_stock":
            prod["restock"] = True
    return products


def evaluate(
    alerts: List[dict], products: Dict[int, dict], now: datetime
) -> List[dict]:
    """Decide which alerts fire right now.

    Returns one entry per firing alert: ``{"alert", "product", "reason",
    "price", "restock"}`` where reason is "price" (preferred) or "restock".
    """
    fired: List[dict] = []
    for a in alerts:
        prod = products.get(a["product_id"])
        if prod is None:
            continue
        price = prod["in_stock_price"]

        price_fire = (
            price is not None
            and price <= a["target_price"]
            and (a["last_notified_price"] is None or price < a["last_notified_price"])
        )

        restock_fire = False
        if a["notify_on_restock"] and prod["restock"]:
            last = a["last_notified_at"]
            if last is None or _parse_iso(last) < now - timedelta(hours=RESTOCK_COOLDOWN_HOURS):
                restock_fire = True

        if price_fire:
            fired.append(
                {
                    "alert": a,
                    "product": prod,
                    "reason": "price",
                    "price": price,
                    "restock": prod["restock"],
                }
            )
        elif restock_fire:
            fired.append(
                {
                    "alert": a,
                    "product": prod,
                    "reason": "restock",
                    "price": price,
                    "restock": True,
                }
            )
    return fired


def build_message(entry: dict) -> tuple:
    """Build (title, body) for a firing alert entry."""
    a = entry["alert"]
    prod = entry["product"]
    price = entry["price"]
    name = f"{prod['brand']} {prod['model']}"

    if entry["reason"] == "price":
        title = f"Price alert: {name} at {format_aud(price)}"
        body = f"{name} is now {format_aud(price)} (your target: {format_aud(a['target_price'])})."
        if entry["restock"]:
            body += " It just restocked."
    else:
        title = f"Restock: {name}"
        body = f"{name} is back in stock."
        if price is not None:
            body += f" Current price {format_aud(price)}."

    if prod.get("in_stock_url"):
        body += f"\n{prod['in_stock_url']}"
    return title, body


def send_discord(webhook_url: str, title: str, body: str) -> None:
    """POST one embed to a Discord webhook. Never raises on failure."""
    payload = json.dumps({"embeds": [{"title": title, "description": body, "color": DOWN_COLOR}]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_SECONDS) as resp:
            resp.read()
    except Exception as e:  # noqa: BLE001 - alert delivery must not break the pipeline
        LOGGER.error("Discord alert delivery failed: %s", e)


def send_webhook(url: str, title: str, body: str) -> None:
    """POST a small JSON body to a generic webhook. Never raises on failure."""
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_SECONDS) as resp:
            resp.read()
    except Exception as e:  # noqa: BLE001 - alert delivery must not break the pipeline
        LOGGER.error("Webhook alert delivery failed: %s", e)


def send_email(
    host: str,
    port: int,
    username: str,
    password: str,
    sender: str,
    recipient: str,
    title: str,
    body: str,
) -> None:
    """Send one plain-text email over SMTP. Never raises on failure."""
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=NOTIFY_TIMEOUT_SECONDS) as server:
            server.starttls()
            if username:
                server.login(username, password)
            server.send_message(msg)
    except Exception as e:  # noqa: BLE001 - alert delivery must not break the pipeline
        LOGGER.error("Email alert delivery failed: %s", e)


def deliver(entry: dict) -> bool:
    """Deliver one firing alert via its channel. Returns True if sent.

    An unconfigured channel is skipped (logged) and returns False so the
    caller does not advance the cooldown for a notification that was not sent.
    """
    a = entry["alert"]
    title, body = build_message(entry)
    channel = a["channel"]

    if channel == "discord":
        url = os.environ.get("TRACKAROO_DISCORD_WEBHOOK_URL")
        if not url:
            LOGGER.info("Discord alert skipped — TRACKAROO_DISCORD_WEBHOOK_URL not set.")
            return False
        send_discord(url, title, body)
        return True

    if channel == "email":
        host = os.environ.get("TRACKAROO_SMTP_HOST")
        if not host:
            LOGGER.info("Email alert skipped — TRACKAROO_SMTP_HOST not set.")
            return False
        send_email(
            host,
            int(os.environ.get("TRACKAROO_SMTP_PORT", "587")),
            os.environ.get("TRACKAROO_SMTP_USERNAME", ""),
            os.environ.get("TRACKAROO_SMTP_PASSWORD", ""),
            os.environ.get("TRACKAROO_SMTP_FROM", ""),
            os.environ.get("TRACKAROO_SMTP_TO", ""),
            title,
            body,
        )
        return True

    if channel == "webhook":
        url = os.environ.get("TRACKAROO_ALERT_WEBHOOK_URL")
        if not url:
            LOGGER.info("Webhook alert skipped — TRACKAROO_ALERT_WEBHOOK_URL not set.")
            return False
        send_webhook(url, title, body)
        return True

    LOGGER.warning("Alert %s skipped — unknown channel %r.", a["id"], channel)
    return False


def run(db_path: Optional[str] = None, dry_run: bool = False) -> int:
    """Evaluate all active alerts and notify. Returns the number fired."""
    load_dotenv()
    conn = sqlite3.connect(db_path or str(DB_PATH))
    try:
        alerts = query_active_alerts(conn)
        if not alerts:
            LOGGER.info("No active price alerts — nothing to check.")
            return 0

        products = aggregate_product_prices(query_latest_rows(conn))
        now = datetime.now(timezone.utc)
        fired = evaluate(alerts, products, now)

        count = 0
        for entry in fired:
            a = entry["alert"]
            title, body = build_message(entry)
            if dry_run:
                print(f"[DRY-RUN] {a['channel']} product={a['product_id']} {entry['reason']}: {title}")
                print(f"    {body}")
                continue
            if not deliver(entry):
                continue
            # Advance the cooldown only for a notification that was actually sent.
            new_price = entry["price"] if entry["reason"] == "price" else a["last_notified_price"]
            conn.execute(
                "UPDATE price_alerts SET last_notified_at = ?, last_notified_price = ? WHERE id = ?",
                (now.isoformat(), new_price, a["id"]),
            )
            count += 1

        if not dry_run:
            conn.commit()
        LOGGER.info("Price alerts: %d fired (dry_run=%s)", count, dry_run)
        return count
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Evaluate Trackaroo price alerts")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: config.DB_PATH)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would fire without sending")
    args = parser.parse_args(argv)
    run(db_path=args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
