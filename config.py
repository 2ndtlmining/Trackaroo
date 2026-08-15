"""
Central configuration for the Trackaroo backend.

Single source of truth for file paths, health-check thresholds, scraper
tuning, and timeouts. Every value can be overridden via environment
variables so Docker / cron / test deployments can tune behaviour without
editing code.

All default paths resolve relative to this file's directory (the repo
root) rather than the process CWD, so scripts work regardless of where
they are invoked from.

Environment variables (all optional):

    TRACKAROO_DATA_DIR    Scraped JSON snapshot directory   (default: <root>/data)
    TRACKAROO_DB          SQLite database file             (default: <root>/db/trackaroo.db)
    TRACKAROO_SCHEMA      Schema SQL file                  (default: <root>/db/schema.sql)
    TRACKAROO_WATCHLIST   Watchlist CSV                    (default: <root>/db/watchlist.csv)
    TRACKAROO_BACKUP_DIR  Database backup directory        (default: <root>/db/backups)

    TRACKAROO_STALE_THRESHOLD_DAYS      Freshness threshold in days   (default: 3)
    TRACKAROO_MATCH_THRESHOLDS_JSON     Per-retailer match thresholds (JSON object)
    TRACKAROO_PRICE_ANOMALY_STD_DEVS    Price-anomaly sigma gate      (default: 3.0)
    TRACKAROO_MIN_HISTORY_FOR_ANOMALY   Min history points for anomaly detection (default: 3)

    TRACKAROO_SCRAPER_TIMEOUT_SECONDS   Per-scraper subprocess timeout (default: 300)
    TRACKAROO_BATCH_SIZE                Algolia batch size            (default: 16)
    TRACKAROO_BATCH_DELAY               Seconds between Algolia batches (default: 1.0)
    TRACKAROO_ALGOLIA_TIMEOUT_SECONDS   Algolia HTTP timeout          (default: 15)
    TRACKAROO_ALGOLIA_MAX_RETRIES       Algolia request retries        (default: 3)
    TRACKAROO_ALGOLIA_BACKOFF_MAX       Upper bound for exponential backoff (default: 20)
    TRACKAROO_ALGOLIA_RATE_LIMIT_WAIT   Base wait on 429 (seconds)     (default: 5)
    TRACKAROO_BUSY_TIMEOUT_MS           SQLite busy timeout (ms)       (default: 5000)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

# ── Base directory ────────────────────────────────────────────────────
# config.py lives at the repo root, so the repo root is simply its directory.
BASE_DIR = Path(__file__).resolve().parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# ── File paths ────────────────────────────────────────────────────────
DATA_DIR = _env_path("TRACKAROO_DATA_DIR", BASE_DIR / "data")
DB_PATH = _env_path("TRACKAROO_DB", BASE_DIR / "db" / "trackaroo.db")
SCHEMA_PATH = _env_path("TRACKAROO_SCHEMA", BASE_DIR / "db" / "schema.sql")
WATCHLIST_PATH = _env_path("TRACKAROO_WATCHLIST", BASE_DIR / "db" / "watchlist.csv")
BACKUP_DIR = _env_path("TRACKAROO_BACKUP_DIR", BASE_DIR / "db" / "backups")

# ── Date / filename formats ───────────────────────────────────────────
# Snapshot filenames look like cpu_scorptec_10_August_2026.json
FILE_DATE_FORMAT = "%d_%B_%Y"
# Snapshot dates are stored in the DB as YYYY-MM-DD
DB_DATE_FORMAT = "%Y-%m-%d"

# ── Database connection tuning ────────────────────────────────────────
BUSY_TIMEOUT_MS = _env_int("TRACKAROO_BUSY_TIMEOUT_MS", 5000)

# ── Health-check thresholds ───────────────────────────────────────────
# Expected match counts per retailer per scrape (multi-variant). Calibrated
# 11-Aug-2026 to ~194 Scorptec / ~41 PCCG matched variants at ~50% of
# baseline, to avoid false alarms from normal stock-level variation.
DEFAULT_MATCH_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "scorptec": {"min_total": 90, "min_per_category": 30},
    "pccg": {"min_total": 20, "min_per_category": 5},
}


def _match_thresholds() -> Dict[str, Dict[str, int]]:
    raw = os.environ.get("TRACKAROO_MATCH_THRESHOLDS_JSON")
    if raw:
        try:
            loaded = json.loads(raw)
            return {k: {ck: int(cv) for ck, cv in v.items()} for k, v in loaded.items()}
        except (ValueError, TypeError, KeyError):
            pass  # Malformed override — fall back to defaults
    return DEFAULT_MATCH_THRESHOLDS


MATCH_THRESHOLDS = _match_thresholds()

# How many days without a snapshot before flagging a retailer as stale
STALE_THRESHOLD_DAYS = _env_int("TRACKAROO_STALE_THRESHOLD_DAYS", 3)

# Price anomaly: flag if a price deviates more than this many standard
# deviations from the historical mean for that product+retailer combo
PRICE_ANOMALY_STD_DEVS = _env_float("TRACKAROO_PRICE_ANOMALY_STD_DEVS", 3.0)

# Minimum number of historical data points needed before anomaly detection
# is meaningful (with fewer points, std dev is unreliable)
MIN_HISTORY_FOR_ANOMALY = _env_int("TRACKAROO_MIN_HISTORY_FOR_ANOMALY", 3)

# Fallback thresholds applied to any retailer NOT in MATCH_THRESHOLDS
DEFAULT_MIN_PER_CATEGORY = 5
DEFAULT_MIN_TOTAL = 10

# ── Scraper tuning ────────────────────────────────────────────────────
# Per-scraper subprocess timeout in the daily runner
SCRAPER_TIMEOUT_SECONDS = _env_int("TRACKAROO_SCRAPER_TIMEOUT_SECONDS", 300)

# Algolia batch tuning (PCCG rate-limits aggressively on 429s)
BATCH_SIZE = _env_int("TRACKAROO_BATCH_SIZE", 16)
BATCH_DELAY = _env_float("TRACKAROO_BATCH_DELAY", 1.0)
ALGOLIA_TIMEOUT_SECONDS = _env_int("TRACKAROO_ALGOLIA_TIMEOUT_SECONDS", 15)
ALGOLIA_MAX_RETRIES = _env_int("TRACKAROO_ALGOLIA_MAX_RETRIES", 3)
ALGOLIA_BACKOFF_MAX_SECONDS = _env_float("TRACKAROO_ALGOLIA_BACKOFF_MAX", 20.0)
ALGOLIA_RATE_LIMIT_WAIT_SECONDS = _env_float("TRACKAROO_ALGOLIA_RATE_LIMIT_WAIT", 5.0)