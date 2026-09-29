"""
Discord digest for Trackaroo.

Sends a short daily summary of the biggest GPU/CPU price moves to a single
Discord webhook. Designed to run from run_daily.py after ingest + health
checks pass, or standalone for a manual send / preview.

Embeds mirror the dashboard's two hex tokens (--up #F87171, --down #34D399)
so Discord matches the app's dark theme. Each digest shows the top 3 price
increases and top 3 decreases per category, computed against each listing's
previous available snapshot (same listing, not a fixed window).

Configuration (env, optional — see .env.example):

    DISCORD_WEBHOOK_URL       Webhook URL for the CPU+GPU digest channel
    DISCORD_WEBHOOK_ALERT     Webhook URL for pipeline-failure alerts (optional)
    TRACKAROO_PUBLIC_BASE_URL  Optional public base URL of the web app, used to
                               add a "Trackaroo page" link next to the retailer
                               link. Omit (or leave blank) for retailer links only.
    TRACKAROO_NOTIFY_TIMEOUT_SECONDS  Webhook POST timeout (default: 10)

The webhook is optional; with it unset the module is a no-op. Secrets
never fail the daily run — a webhook error is logged, not raised.

Usage:
    python notify_discord.py             # Send the digest
    python notify_discord.py --dry-run   # Print the embeds without sending
    python notify_discord.py --test      # Send one static sample embed per webhook
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import requests

from config import DB_PATH, NOTIFY_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)


def _safe_host(url: str) -> str:
    """scheme://hostname[:port] only -- a Discord webhook URL's token lives
    in the path, so nothing more specific than this may ever reach a log
    line. Mirrors heartbeat._safe_host (final review M2)."""
    try:
        parts = urlsplit(url)
        if parts.scheme and parts.hostname:
            host = parts.hostname
            if parts.port:
                host = f"{host}:{parts.port}"
            return f"{parts.scheme}://{host}"
    except ValueError:
        pass
    return "<unparseable>"

# ── Brand-agnostic presentational constants ────────────────────────────
# Match the app's dark-theme tokens in web/src/app.css.
UP_COLOR = 0xF87171    # --up   (price increased — coral/red)
DOWN_COLOR = 0x34D399  # --down (price decreased — teal/green)
ALERT_COLOR = 0xFB923C  # orange — pipeline issues

CATEGORY_LABELS = {"cpu": "CPU", "gpu": "GPU"}
# All six planned retailers. A slug missing here prints raw in the digest, so
# labels ship ahead of the scrapers (see docs/ARCHITECTURE.md, six-retailer prep).
RETAILER_LABELS = {
    "scorptec": "Scorptec",
    "pccg": "PCCG",
    "mwave": "MWave",
    "umart": "Umart",
    "centrecom": "Centre Com",
    "ple": "PLE",
}

DIGEST_SQL = """
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
       t.price_aud AS today_price, t.snapshot_date AS today_date,
       prev.price_aud AS prev_price, prev.snapshot_date AS prev_date
FROM ranked t
JOIN retailer_listings l ON l.id = t.retailer_listing_id
JOIN products p ON p.id = l.product_id
JOIN ranked prev ON prev.retailer_listing_id = t.retailer_listing_id AND prev.rn = 2
WHERE t.rn = 1
  AND t.stock_status = 'in_stock'
  AND p.tracked = 1
  AND l.status = 'active'
  AND (l.variant_name IS NULL OR lower(l.variant_name) NOT LIKE '%bundle%')
  AND (l.variant_name IS NULL OR lower(l.variant_name) NOT LIKE '%combo%')
  AND lower(l.listing_url) NOT LIKE '%bundle%'
  AND lower(l.listing_url) NOT LIKE '%bdl-%'
"""

TOP_N = 3


def format_aud(value: float) -> str:
    """Format a price like the dashboard, e.g. 1049.0 -> '$1,049'."""
    return f"${value:,.0f}"


def load_dotenv(path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ if present.

    Real environment variables win over .env (setdefault). Handles the common
    cases: blank lines, comments, and optional surrounding quotes on values.
    """
    env_file = path or Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def query_digest_rows(conn: sqlite3.Connection) -> List[dict]:
    """Fetch (product, retailer, current price, previous price) rows.

    Each row is one listing's current in-stock snapshot paired with that same
    listing's previous snapshot (rn=1 / rn=2). Products whose listing has no
    earlier snapshot are naturally excluded.
    """
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(DIGEST_SQL).fetchall()]


def build_digest(rows: List[dict]) -> Dict[str, List[dict]]:
    """Group rows into per-category top movers.

    For each product keep the listing with the largest price move — a move on a
    pricier variant is more interesting than a flat cheaper one — using the
    cheapest listing as a tie-break. Then keep the top 3 increases and top 3
    decreases per category. Flat (0%) moves are skipped.
    """
    per_product: Dict[int, dict] = {}
    for row in rows:
        prev = row["prev_price"]
        row["pct"] = ((row["today_price"] - prev) / prev * 100.0) if prev else 0.0
        current = per_product.get(row["product_id"])
        if current is None or abs(row["pct"]) > abs(current["pct"]) or (
            abs(row["pct"]) == abs(current["pct"]) and row["today_price"] < current["today_price"]
        ):
            per_product[row["product_id"]] = row

    per_category: Dict[str, Dict[str, List[dict]]] = {"cpu": {"up": [], "down": []}, "gpu": {"up": [], "down": []}}
    for row in per_product.values():
        if row["pct"] == 0:
            continue
        direction = "up" if row["pct"] > 0 else "down"
        per_category[row["category"]][direction].append(row)

    result: Dict[str, List[dict]] = {}
    for category, by_direction in per_category.items():
        ups = sorted(by_direction["up"], key=lambda r: -r["pct"])[:TOP_N]
        downs = sorted(by_direction["down"], key=lambda r: r["pct"])[:TOP_N]
        if ups:
            result[f"{category}:up"] = ups
        if downs:
            result[f"{category}:down"] = downs
    return result


def retailer_label(retailer: str) -> str:
    return RETAILER_LABELS.get(retailer, retailer)


def build_embed(key: str, products: List[dict], public_base_url: str = "") -> dict:
    """Build one Discord embed for a (category, direction) digest."""
    category, direction = key.split(":")
    direction_label = "ups" if direction == "up" else "drops"
    lines: List[str] = []
    for p in products:
        lines.append(f"**{p['brand']} {p['model']}**")
        lines.append(
            f"{format_aud(p['prev_price'])} → {format_aud(p['today_price'])} ({p['pct']:+.1f}%) · "
            f"{retailer_label(p['retailer'])}"
        )
        retailer_link = f"[View on {retailer_label(p['retailer'])}]({p['listing_url']})"
        if public_base_url:
            retailer_link += f" · [Trackaroo page]({public_base_url}/product/{p['product_id']})"
        lines.append(retailer_link)
        lines.append("")
    return {
        "title": f"{CATEGORY_LABELS[category]} price {direction_label}",
        "color": UP_COLOR if direction == "up" else DOWN_COLOR,
        "description": "\n".join(lines).rstrip(),
    }


def send_embed(webhook_url: str, embed: dict) -> bool:
    """POST one embed to a Discord webhook. Never raises.

    Returns:
        True if Discord accepted the embed (2xx). False on any failure —
        a network error/timeout, or a non-2xx response (``raise_for_status``
        turns that into a ``requests.HTTPError``, caught below like any other
        ``RequestException``). Callers use this to tell a real delivery
        failure apart from success, so a claimed "sent once today" marker can
        be released for the next hourly retry instead of silently believed
        (#8 fix-round-1 I1 — this used to always report success even when the
        POST failed, so a webhook outage was never retried).
    """
    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=NOTIFY_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:  # noqa: BLE001 - notify failures must not break the pipeline
        # Never log `e` directly: requests/urllib3 embed the full URL in
        # exception messages (HTTPError's "... for url: ...",
        # ConnectionError/Timeout's MaxRetryError "... with url: ..."), and
        # the webhook URL's path IS the Discord token (final review M2).
        # Only the scheme+host, the exception's class name, and (for an
        # HTTPError with a response) its status code are safe -- same
        # redaction as heartbeat._safe_host (fix-round-1 I1).
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if status is not None else ""
        LOGGER.error("Discord webhook failed: %s%s (%s)", type(e).__name__, detail, _safe_host(webhook_url))
        return False


def send_alert(lines: List[str], dry_run: bool = False) -> bool:
    """Send a pipeline-issue alert to ``DISCORD_WEBHOOK_ALERT``, if configured.

    The daily digest is gated on a clean run (see run_daily.py), so scraper
    failures and health-check errors need their own channel. Never raises —
    a webhook error is logged, not thrown, and with no webhook set it is a
    no-op.

    Args:
        lines: Bullet lines describing what failed.
        dry_run: Print the embed instead of posting it.

    Returns:
        True if the alert was actually delivered (posted successfully, or
        printed under ``dry_run``). False if nothing was delivered: no
        webhook configured (harmless — there was nothing to send) or the POST
        failed. ``run_daily.claim_once``/``release_once`` treat a falsy
        (or exception/None-from-best_effort) result as "not sent", releasing
        a same-day claim so a failed 04:00 alert is retried at 05:00 rather
        than silently marked done (#8 fix-round-1 I1).
    """
    load_dotenv()
    webhook = os.environ.get("DISCORD_WEBHOOK_ALERT")
    if not webhook:
        return False
    embed = {
        "title": "Trackaroo alert — pipeline issue",
        "color": ALERT_COLOR,
        "description": "\n".join(lines).rstrip(),
    }
    if dry_run:
        print(json.dumps(embed, indent=2))
        LOGGER.info("Discord alert sent (dry_run=%s)", dry_run)
        return True
    ok = send_embed(webhook, embed)
    if ok:
        LOGGER.info("Discord alert sent (dry_run=%s)", dry_run)
    return ok


def run(db_path: Optional[str] = None, dry_run: bool = False, test: bool = False) -> int:
    """Load config, build the digest and send it.

    Returns:
        The number of embeds actually delivered (posted successfully, or
        printed under ``dry_run``) — 0 if no webhook is configured, or if
        every send failed. A caller checking "was anything delivered" can
        treat this as a plain falsy/truthy value (#8 fix-round-1 I1: a
        digest that posts to a webhook returning a 5xx used to still report
        success here).
    """
    load_dotenv()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    public_base_url = os.environ.get("TRACKAROO_PUBLIC_BASE_URL", "").rstrip("/")

    if test:
        return _send_test_embed(webhook_url, dry_run)

    if not webhook_url:
        LOGGER.info("No Discord webhook configured — skipping digest.")
        return 0

    conn = sqlite3.connect(db_path or str(DB_PATH))
    try:
        rows = query_digest_rows(conn)
    finally:
        conn.close()

    digests = build_digest(rows)
    sent = 0
    failed = 0
    for key, products in digests.items():
        embed = build_embed(key, products, public_base_url)
        if dry_run:
            print(f"# {key}")
            print(json.dumps(embed, indent=2))
            sent += 1
        elif send_embed(webhook_url, embed):
            sent += 1
        else:
            failed += 1
    LOGGER.info("Discord digest: %d embeds sent, %d failed (dry_run=%s)", sent, failed, dry_run)
    return sent


def _send_test_embed(webhook_url: Optional[str], dry_run: bool) -> int:
    sample = {
        "title": "Test — Trackaroo digest",
        "color": UP_COLOR,
        "description": "**AMD Ryzen 7 9800X3D**\n$549 → $599 (+9.1%) · Scorptec\n[View on Scorptec](https://example.com)",
    }
    if not webhook_url:
        return 0
    if dry_run:
        print(json.dumps(sample, indent=2))
        LOGGER.info("Discord test: 1 sample embed sent (dry_run=%s)", dry_run)
        return 1
    ok = send_embed(webhook_url, sample)
    LOGGER.info("Discord test: 1 sample embed %s (dry_run=%s)", "sent" if ok else "failed", dry_run)
    return 1 if ok else 0


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Send the Trackaroo Discord digest")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: config.DB_PATH)")
    parser.add_argument("--dry-run", action="store_true", help="Print embeds without sending")
    parser.add_argument("--test", action="store_true", help="Send a static sample embed to each configured webhook")
    args = parser.parse_args(argv)
    run(db_path=args.db, dry_run=args.dry_run, test=args.test)


if __name__ == "__main__":
    main()