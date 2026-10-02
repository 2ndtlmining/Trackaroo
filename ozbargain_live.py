"""The OzBargain "live deal" rule (R8), shared by the poller and the alerts (#34).

Split out of ozbargain.py to keep that module under the 350-line cap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

try:  # naive feed times are Melbourne local (DST-correct when tzdata exists)
    from zoneinfo import ZoneInfo

    MELBOURNE = ZoneInfo("Australia/Melbourne")
except Exception:  # no tzdata (e.g. Windows without the tzdata package)
    MELBOURNE = timezone(timedelta(hours=10))

LIVE_SEEN_DAYS = 7


def _aware(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso.strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=MELBOURNE)


def is_live(d: dict, now: datetime) -> bool:
    """R8: expired=0, started, expiry in the future, seen in the feed within 7 days.

    Unparseable start/expiry count as absent; a missing or unparseable
    ``last_seen_at`` is NOT live.
    """
    if d["expired"]:
        return False
    start = _aware(d["starts_at"]) if d.get("starts_at") else None
    if start is not None and start > now:
        return False
    end = _aware(d["expires_at"]) if d.get("expires_at") else None
    if end is not None and end <= now:
        return False
    seen = _aware(d["last_seen_at"]) if d.get("last_seen_at") else None
    return seen is not None and now - seen <= timedelta(days=LIVE_SEEN_DAYS)
