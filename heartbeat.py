"""Outbound heartbeat for an external dead-man's switch (#9).

After a run that leaves every active retailer with a complete scrape today,
run_daily GETs TRACKAROO_HEARTBEAT_URL -- for example a healthchecks.io check
or an Uptime Kuma "push" monitor set to alert after ~26h of silence. A dead
container, a dead host and a silently partial day all look the same from
outside: no ping. Unset (the default until Phase 6), this does nothing.
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlsplit

import requests

from config import NOTIFY_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)

HEARTBEAT_ENV = "TRACKAROO_HEARTBEAT_URL"


def _safe_host(url: str) -> str:
    """scheme://host only -- a healthchecks.io-style ping URL's secret lives
    in the path (its check UUID/token), so nothing more specific than this
    may ever reach a log line (fix-round-1 I1)."""
    try:
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except ValueError:
        pass
    return "<unparseable>"


def ping(url: Optional[str] = None, timeout: int = NOTIFY_TIMEOUT_SECONDS) -> bool:
    """GET the heartbeat URL. True on a 2xx; never raises.

    Args:
        url: Override for tests; defaults to $TRACKAROO_HEARTBEAT_URL.
        timeout: Seconds before giving up.
    """
    target = url if url is not None else os.environ.get(HEARTBEAT_ENV, "").strip()
    if not target:
        return False
    try:
        r = requests.get(target, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        # Never log `e` or `target` directly: requests/urllib3 embed the full
        # URL in exception messages (HTTPError's "... for url: ...",
        # ConnectionError/Timeout's MaxRetryError "... with url: ..."), and
        # the ping URL's path IS the healthchecks.io/Uptime Kuma secret
        # (fix-round-1 I1). Only the scheme+host, the exception's class name,
        # and (for an HTTPError with a response) its status code are safe.
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if status is not None else ""
        LOGGER.warning("Heartbeat ping to %s failed: %s%s", _safe_host(target), type(e).__name__, detail)
        return False
    LOGGER.info("Heartbeat pinged")
    return True
