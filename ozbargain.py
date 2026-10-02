"""OzBargain RSS deal parser (#34).

Pure parsing of the tag feeds (video-card, cpu). Best effort: odd or missing
fields become None/0 and never raise; only an unparseable feed raises
``ValueError``. The ``/goto/`` redirect URL is never read or stored; the deal
URL is always the ``/node/<id>`` page.

``run()`` makes one poll: two GETs (one per tag feed), match each item to a
tracked product, upsert into ``ozb_deals`` and log an ``ozb_polls`` row.
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from config import DB_PATH
from discover_rules import is_excluded_title
from migrate import migrate_add_ozbargain_tables
from ozbargain_live import LIVE_SEEN_DAYS, MELBOURNE, _aware, is_live  # noqa: F401 (re-exported)
from scraper.chip_key import Matcher

LOGGER = logging.getLogger(__name__)
TIMEOUT = 10
DEALS_RETENTION_DAYS = 180
POLLS_RETENTION_DAYS = 30
RESTART_GUARD_MINUTES = 90  # a restart/crash loop must not burn the 18 polls/day budget
# discover_rules.is_excluded_title misses prebuilt PCs ("Gaming PC with RTX 5070"):
# a whole-PC deal is not a card or CPU price, so it is never matched.
_PREBUILT_RE = re.compile(
    r"\b(?:gaming|desktop|custom|office)\s+(?:pc|computer|desktop|system)s?\b"
    r"|\bpre-?built\b|\ball[ -]in[ -]one\b|\bmini pc\b|\bpc with\b", re.I)

FEEDS: Tuple[Tuple[str, str], ...] = (
    ("gpu", "https://www.ozbargain.com.au/tag/video-card/feed"),
    ("cpu", "https://www.ozbargain.com.au/tag/cpu/feed"),
)
USER_AGENT = "Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)"

NODE_URL = "https://www.ozbargain.com.au/node/{}"
EXPIRED_MSGS = {"expired", "sold out", "out of stock"}

_PRICE_RE = re.compile(r"([A-Za-z]*)\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
_AUD_PREFIXES = {"", "A", "AU"}
_SAVING_AFTER_RE = re.compile(r"\s*(off|cashback|back|credit|gift|voucher|rebate)\b", re.I)
_SAVING_BEFORE_RE = re.compile(r"\b(save|saving)\s+$", re.I)
_NODE_RE = re.compile(r"/node/(\d+)")
_GUID_RE = re.compile(r"^\s*(\d+)")


@dataclass
class FeedItem:
    node_id: int
    category: str  # 'gpu' | 'cpu'
    title: str
    url: str  # https://www.ozbargain.com.au/node/<id>
    price_aud: Optional[float]
    retailer: Optional[str]
    votes_pos: int
    votes_neg: int
    comment_count: int
    posted_at: Optional[str]  # ISO 8601 with offset
    starts_at: Optional[str]
    expires_at: Optional[str]
    expired: bool
    product_slugs: List[str] = field(default_factory=list)


def parse_price(title: str) -> Optional[float]:
    """First AUD ``$`` amount that is a deal price (R4).

    Skips savings/coupons ("$50 off", "Save $100", "$20 gift card") and
    amounts with a non-AUD currency prefix (US$, NZ$); non-positive is not a
    price.
    """
    title = title or ""
    for m in _PRICE_RE.finditer(title):
        if m.group(1).upper() not in _AUD_PREFIXES:
            continue
        if _SAVING_AFTER_RE.match(title, m.end()):
            continue
        if _SAVING_BEFORE_RE.search(title, 0, m.start()):
            continue
        whole = m.group(2).replace(",", "")
        price = float(f"{whole}.{m.group(3)}" if m.group(3) else whole)
        if price > 0:
            return price
    return None


def parse_retailer(title: str) -> Optional[str]:
    """Text after the last ' @ ' (spaces required), trimmed."""
    if " @ " not in (title or ""):
        return None
    return title.rsplit(" @ ", 1)[1].strip() or None


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _int(value: Optional[str]) -> int:
    try:
        return int(value) if value is not None else 0
    except ValueError:
        return 0


def _node_id(item: ET.Element) -> Optional[int]:
    link = (item.findtext("link") or "").strip()
    m = _NODE_RE.search(link)
    if not m:
        m = _GUID_RE.match(item.findtext("guid") or "")
    return int(m.group(1)) if m else None


def _pub_date(item: ET.Element) -> Optional[str]:
    raw = (item.findtext("pubDate") or "").strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_item(item: ET.Element, category: str, now: datetime) -> Optional[FeedItem]:
    node_id = _node_id(item)
    if node_id is None:
        return None
    title = (item.findtext("title") or "").strip()
    meta: Dict[str, str] = {}
    expired = False
    slugs: List[str] = []
    for el in item:
        name = _local(el.tag)
        if name == "meta":
            meta = dict(el.attrib)
        elif name == "title-msg":
            if (el.get("type") or "").strip().lower() in EXPIRED_MSGS:
                expired = True
        elif name == "category":
            domain = el.get("domain") or ""
            if "/product/" in domain:
                slug = domain.rstrip("/").rsplit("/", 1)[-1]
                if slug and slug not in slugs:
                    slugs.append(slug)
    expires_at = (meta.get("expiry") or "").strip() or None
    starts_at = (meta.get("starting") or "").strip() or None
    if not expired and expires_at:
        exp = _aware(expires_at)
        if exp is not None and exp < now:
            expired = True
    return FeedItem(
        node_id=node_id,
        category=category,
        title=title,
        url=NODE_URL.format(node_id),
        price_aud=parse_price(title),
        retailer=parse_retailer(title),
        votes_pos=_int(meta.get("votes-pos")),
        votes_neg=_int(meta.get("votes-neg")),
        comment_count=_int(meta.get("comment-count")),
        posted_at=_pub_date(item),
        starts_at=starts_at,
        expires_at=expires_at,
        expired=expired,
        product_slugs=slugs,
    )


def parse_feed(xml_text: str, category: str, now: datetime) -> List[FeedItem]:
    """Parse one RSS feed. Raises ``ValueError`` naming the category if it is
    not a parseable RSS document (blocked page, truncated body)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=MELBOURNE)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"{category} feed: {e}") from e
    if _local(root.tag) != "rss":
        raise ValueError(f"{category} feed: not an RSS document (<{_local(root.tag)}>)")
    items: List[FeedItem] = []
    for el in root.iter("item"):
        parsed = _parse_item(el, category, now)
        if parsed is not None:
            items.append(parsed)
    return items


# ------------------------------------------------------------------ matching
def build_matchers(conn: sqlite3.Connection) -> Dict[str, Tuple[Matcher, List[dict]]]:
    """One Matcher per category over the tracked products; rows[i] maps back to an id."""
    rows: Dict[str, List[dict]] = {}
    for r in conn.execute("SELECT id, category, brand, model, vram_gb FROM products WHERE tracked = 1"):
        d = {"id": r[0], "category": r[1], "brand": r[2], "model": r[3], "vram_gb": r[4]}
        rows.setdefault(d["category"], []).append(d)
    return {cat: (Matcher(lst), lst) for cat, lst in rows.items()}


def match_item(item: FeedItem, matchers: Dict[str, Tuple[Matcher, List[dict]]]) -> Optional[int]:
    """Tracked product id for a feed item, or None (bundles, ambiguous VRAM, untracked)."""
    if item.category not in matchers or is_excluded_title(item.title) or _PREBUILT_RE.search(item.title):
        return None
    matcher, rows = matchers[item.category]
    idx = matcher.resolve(item.title, item.category)
    for slug in item.product_slugs:
        if idx is not None:
            break
        idx = matcher.resolve(slug.replace("-", " "), item.category, extra_text=item.title)
    return rows[idx]["id"] if idx is not None else None


# ------------------------------------------------------------------- storage
_UPSERT_SQL = """
INSERT INTO ozb_deals (node_id, category, title, url, price_aud, retailer, votes_pos, votes_neg,
    comment_count, posted_at, starts_at, expires_at, expired, product_id, first_seen_at, last_seen_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(node_id) DO UPDATE SET
    category = excluded.category, title = excluded.title, url = excluded.url,
    price_aud = excluded.price_aud, retailer = excluded.retailer,
    votes_pos = excluded.votes_pos, votes_neg = excluded.votes_neg,
    comment_count = excluded.comment_count, posted_at = excluded.posted_at,
    starts_at = excluded.starts_at, expires_at = excluded.expires_at, expired = excluded.expired,
    product_id = COALESCE(excluded.product_id, ozb_deals.product_id),
    last_seen_at = excluded.last_seen_at
"""


def upsert_items(conn: sqlite3.Connection, items: Sequence[FeedItem],
                 product_ids: Sequence[Optional[int]], seen_at: str) -> None:
    """Upsert on node_id. first_seen_at, alerted_at and a non-null product_id are kept
    (a re-match to another product wins; a null re-match does not clear it)."""
    conn.executemany(_UPSERT_SQL, [
        (i.node_id, i.category, i.title, i.url, i.price_aud, i.retailer, i.votes_pos, i.votes_neg,
         i.comment_count, i.posted_at, i.starts_at, i.expires_at, int(i.expired), pid, seen_at, seen_at)
        for i, pid in zip(items, product_ids)
    ])
    conn.commit()


def prune(conn: sqlite3.Connection, now: datetime) -> None:
    """Drop deals not seen for 180 days and poll log rows older than 30 days."""
    deals_cut = (now - timedelta(days=DEALS_RETENTION_DAYS)).isoformat(timespec="seconds")
    polls_cut = (now - timedelta(days=POLLS_RETENTION_DAYS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM ozb_deals WHERE last_seen_at < ?", (deals_cut,))
    conn.execute("DELETE FROM ozb_polls WHERE polled_at < ?", (polls_cut,))
    conn.commit()


# ---------------------------------------------------------------------- poll
def _fetch(category: str, url: str, now: datetime) -> List[FeedItem]:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_feed(resp.text, category, now)


def poll(conn: sqlite3.Connection, now: datetime, dry_run: bool = False) -> Dict[str, Any]:
    """Fetch both feeds, match and store. ok when at least one feed parsed."""
    items: List[FeedItem] = []
    errors: List[str] = []
    for category, url in FEEDS:
        try:
            items.extend(_fetch(category, url, now))
        except Exception as e:  # noqa: BLE001 - one feed down must not stop the other
            LOGGER.warning("OzBargain %s feed failed: %s", category, e)
            errors.append(f"{category}: {e}")
    result: Dict[str, Any] = {"ok": len(errors) < len(FEEDS), "items": len(items), "matched": 0,
                              "errors": errors, "matches": []}
    if not result["ok"]:
        return result
    matchers = build_matchers(conn)
    pids = [match_item(i, matchers) for i in items]
    result["matched"] = sum(p is not None for p in pids)
    result["matches"] = [(i, p) for i, p in zip(items, pids) if p is not None]
    if not dry_run:
        upsert_items(conn, items, pids, now.isoformat(timespec="seconds"))
    return result


def _polled_recently(conn: sqlite3.Connection, now: datetime) -> bool:
    cut = now - timedelta(minutes=RESTART_GUARD_MINUTES)
    for (raw,) in conn.execute("SELECT polled_at FROM ozb_polls"):
        ts = _aware(raw) if raw else None
        if ts is not None and cut < ts <= now + timedelta(minutes=RESTART_GUARD_MINUTES):
            return True
    return False


def run(db_path: Optional[Path] = None, dry_run: bool = False,
        now: Optional[datetime] = None) -> Dict[str, Any]:
    """One poll against the DB. A dry run writes nothing (no tables, no poll row)."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    now = now or datetime.now(MELBOURNE)
    conn = sqlite3.connect(str(db_path))
    try:
        if not dry_run:
            migrate_add_ozbargain_tables(conn)
            if _polled_recently(conn, now):
                LOGGER.info("OzBargain poll skipped: last poll under %d minutes ago", RESTART_GUARD_MINUTES)
                return {"ok": False, "skipped": True, "items": 0, "matched": 0, "errors": [], "matches": []}
        result = poll(conn, now, dry_run=dry_run)
        if not dry_run:
            prune(conn, now)
            conn.execute(
                "INSERT OR REPLACE INTO ozb_polls (polled_at, ok, items, error) VALUES (?, ?, ?, ?)",
                (now.isoformat(timespec="seconds"), int(result["ok"]), result["items"],
                 "; ".join(result["errors"]) or None),
            )
            conn.commit()
            if result["ok"]:
                try:
                    import ozbargain_alerts
                    ozbargain_alerts.send_alerts(conn, now)
                except Exception as e:  # noqa: BLE001 - alerts never fail the poll
                    LOGGER.warning("OzBargain alerts failed: %s", type(e).__name__)
    finally:
        conn.close()
    LOGGER.info("OzBargain poll: ok=%s items=%d matched=%d errors=%d",
                result["ok"], result["items"], result["matched"], len(result["errors"]))
    return result


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Poll the OzBargain GPU/CPU deal feeds")
    parser.add_argument("--dry-run", action="store_true", help="Parse and match, write nothing")
    args = parser.parse_args(argv)
    import config
    config.setup_logging()
    result = run(dry_run=args.dry_run)
    if args.dry_run:
        for item, pid in result["matches"]:
            price = f"${item.price_aud:,.2f}" if item.price_aud is not None else "-"
            print(f"{item.node_id} {pid} {item.title} {price}")
    print({k: v for k, v in result.items() if k != "matches"})


if __name__ == "__main__":
    main()
