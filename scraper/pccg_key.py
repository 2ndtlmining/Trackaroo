"""Find PCCG's current public Algolia search key (#11b).

PCCG's search runs on Algolia with a public, search-only key. The scraper
ships the key as a default (``scraper/pccg.py``), so if PCCG rotates it every
query gets a 401/403. #11a made that fail loudly (exit 4 + alert, no
cooldown). This module lets the scraper recover by itself: every
pccasegear.com page carries the key in its Algolia Insights init block

    aa('init', {
      appId: 'HPD3DBJ2IO',
      apiKey: '9559cf1a6c7521a30ba0832ec6c38499',
    });

(verified on a category page, 5-Oct-2026), so ONE page fetch, made only after
a rejection, recovers it. The result is cached in ``data/pccg_algolia.json``
so later runs start from the working key.

Precedence: an explicit ``ALGOLIA_API_KEY`` in the environment wins over the
cache (an operator override is deliberate); the cache wins over the code
default. Discovery is best-effort and never raises.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import requests

from config import DATA_DIR

LOGGER = logging.getLogger(__name__)

Credentials = Tuple[str, str]  # (app_id, api_key)

# A category page: the same server-rendered template as every other page.
DISCOVERY_URL = "https://www.pccasegear.com/category/193/graphics-cards"
CACHE_FILE: Path = DATA_DIR / "pccg_algolia.json"
TIMEOUT_SECONDS = 20
# pccasegear.com, like amd.com, serves a browser but not the default requests UA.
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
_INIT_RE = re.compile(
    r"""appId\s*:\s*['"]([A-Za-z0-9]{6,20})['"]\s*,\s*apiKey\s*:\s*['"]([0-9a-fA-F]{32})['"]"""
)


def parse_credentials(html: str) -> Optional[Credentials]:
    """(app_id, api_key) from a PCCG page, or None if the page has none."""
    m = _INIT_RE.search(html or "")
    return (m.group(1), m.group(2).lower()) if m else None


def discover_credentials() -> Optional[Credentials]:
    """Fetch one PCCG page and read the key from it. Never raises."""
    try:
        r = requests.get(DISCOVERY_URL, headers=_UA, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - best effort: the caller still fails loudly
        LOGGER.error("PCCG key discovery: could not fetch %s: %s", DISCOVERY_URL, exc)
        return None
    if r.status_code != 200:
        LOGGER.error("PCCG key discovery: %s returned HTTP %s", DISCOVERY_URL, r.status_code)
        return None
    creds = parse_credentials(r.text)
    if creds is None:
        LOGGER.error("PCCG key discovery: no Algolia appId/apiKey found on %s", DISCOVERY_URL)
    return creds


def load_cached() -> Optional[Credentials]:
    """The cached key, or None when there is none or it is unreadable."""
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        app_id, api_key = str(data["app_id"]), str(data["api_key"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (app_id, api_key) if app_id and api_key else None


def cached_credentials_unless_env() -> Optional[Credentials]:
    """The cached key to start a run with, unless the environment pins one."""
    if os.environ.get("ALGOLIA_API_KEY"):
        return None
    return load_cached()


def save_cached(creds: Credentials) -> None:
    """Write the cache atomically. A failure is logged, never raised."""
    app_id, api_key = creds
    payload = {
        "app_id": app_id,
        "api_key": api_key,
        "discovered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": DISCOVERY_URL,
    }
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, CACHE_FILE)
    except OSError as exc:
        LOGGER.error("PCCG key discovery: could not cache the new key in %s: %s", CACHE_FILE, exc)
