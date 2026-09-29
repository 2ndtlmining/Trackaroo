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

import requests

from config import NOTIFY_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)

HEARTBEAT_ENV = "TRACKAROO_HEARTBEAT_URL"


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
        LOGGER.warning("Heartbeat ping failed: %s", e)
        return False
    LOGGER.info("Heartbeat pinged")
    return True
