"""OzBargain RSS deal parser (#34).

Pure parsing of the tag feeds (video-card, cpu). Best effort: odd or missing
fields become None/0 and never raise; only an unparseable feed raises
``ValueError``. The ``/goto/`` redirect URL is never read or stored; the deal
URL is always the ``/node/<id>`` page.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

FEEDS: Tuple[Tuple[str, str], ...] = (
    ("gpu", "https://www.ozbargain.com.au/tag/video-card/feed"),
    ("cpu", "https://www.ozbargain.com.au/tag/cpu/feed"),
)
USER_AGENT = "Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)"

NODE_URL = "https://www.ozbargain.com.au/node/{}"
try:  # naive feed times are Melbourne local (DST-correct when tzdata exists)
    from zoneinfo import ZoneInfo

    MELBOURNE = ZoneInfo("Australia/Melbourne")
except Exception:  # no tzdata (e.g. Windows without the tzdata package)
    MELBOURNE = timezone(timedelta(hours=10))
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


def _aware(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso.strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MELBOURNE)


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
