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
    TRACKAROO_STALE_LISTING_DAYS        Days a listing may go unseen while its
                                         retailer stays current (default: 7)
    TRACKAROO_MATCH_THRESHOLDS_JSON     Per-retailer match thresholds (JSON object)
    TRACKAROO_PRICE_ANOMALY_STD_DEVS    Price-anomaly sigma gate      (default: 3.0)
    TRACKAROO_MIN_HISTORY_FOR_ANOMALY   Min PRIOR points for the sigma test (default: 10)
    TRACKAROO_PRICE_MOVE_PCT            Day-over-day move flagged on its own (default: 0.10)

    TRACKAROO_SCRAPER_TIMEOUT_SECONDS   Per-scraper subprocess timeout (default: 300)
    TRACKAROO_ALGOLIA_TIMEOUT_SECONDS   Algolia HTTP timeout          (default: 15)
    TRACKAROO_ALGOLIA_MAX_RETRIES       Algolia request retries        (default: 3)
    TRACKAROO_ALGOLIA_BACKOFF_MAX       Upper bound for exponential backoff (default: 20)
    TRACKAROO_ALGOLIA_RATE_LIMIT_WAIT   Base wait on 429 (seconds)     (default: 5)
    TRACKAROO_PCCG_COOLDOWN_HOURS       Cooldown window after breaker trips (default: 4)
    TRACKAROO_PCCG_COOLDOWN_FILE        Breaker cooldown state file   (default: <data>/pccg_cooldown.json)
    TRACKAROO_CATEGORY_PASS_DELAY       Delay between CPU/GPU passes  (default: 2.0)
    TRACKAROO_BUSY_TIMEOUT_MS           SQLite busy timeout (ms)       (default: 5000)

    TRACKAROO_BACKUP_KEEP                Days of backups to retain (newest per day) (default: 14)
    TRACKAROO_BACKUP_MIRROR_DIR          Off-host copy of each backup  (default: unset = off)
    TRACKAROO_BACKUP_MAX_AGE_HOURS       Backup-age warning threshold  (default: 36)
    TRACKAROO_SCRAPER_GAP_SECONDS       Delay between the two scrapers (default: 2.0)

    RUN_AT_HOUR                         Daily run hour, local 0-23      (default: 4)
    RETRY_UNTIL_HOUR                    Last hourly retry, local 0-23   (default: 9)

    TRACKAROO_SCORPTEC_TIMEOUT_SECONDS  Scorptec HTTP timeout          (default: 15)
    TRACKAROO_SCORPTEC_MAX_RETRIES      Scorptec fetch retries         (default: 2)
    TRACKAROO_SCORPTEC_RETRY_DELAY      Delay between Scorptec retries (default: 2.0)
    TRACKAROO_SCORPTEC_PAGE_DELAY       Delay between Scorptec pages   (default: 0.5)
    TRACKAROO_SCORPTEC_MAX_PAGES        Scorptec pagination safety cap (default: 20)

    TRACKAROO_UMART_TIMEOUT_SECONDS     Umart HTTP timeout             (default: 15)
    TRACKAROO_UMART_MAX_RETRIES         Umart fetch retries            (default: 2)
    TRACKAROO_UMART_RETRY_DELAY         Delay between Umart retries    (default: 2.0)
    TRACKAROO_UMART_PAGE_DELAY          Delay between Umart pages      (default: 1.0)
    TRACKAROO_UMART_MAX_PAGES           Umart pagination safety cap    (default: 30)

    TRACKAROO_ALGOLIA_HITS_PER_PAGE     Algolia hits per page          (default: 20)
    TRACKAROO_ALGOLIA_MAX_PAGES         Algolia pagination safety cap  (default: 10)
    TRACKAROO_ALGOLIA_PAGE_DELAY        Delay between Algolia pages    (default: 0.3)
    TRACKAROO_ALGOLIA_CATALOGUE_HITS    Hits per catalogue page        (default: 1000)
    TRACKAROO_ALGOLIA_CATALOGUE_PAGES   Catalogue pagination cap       (default: 10)

    TRACKAROO_SPEC_FETCH_TIMEOUT        Spec-source fetch timeout      (default: 20)
    TRACKAROO_SPEC_RETRY_BACKOFF        Delay between spec fetch retries (default: 2.0)
    TRACKAROO_AMD_FETCH_DELAY           Delay between AMD page fetches (default: 1.0)

    TRACKAROO_SPEC_COVERAGE_MIN_PCT     Spec coverage threshold %      (default: 80.0)
    TRACKAROO_SPEC_STALE_THRESHOLD_DAYS Spec staleness threshold days  (default: 14)

    TRACKAROO_DEFAULT_MIN_PER_CATEGORY  Match-count fallback threshold (default: 5)
    TRACKAROO_DEFAULT_MIN_TOTAL         Match-count fallback threshold (default: 10)
    TRACKAROO_MATCH_DROP_RATIO          Relative match-drop alert ratio (default: 0.6)
    TRACKAROO_MATCH_DROP_WINDOW_DAYS    Match-drop trailing window (days)  (default: 7)
    TRACKAROO_MATCH_DROP_MIN_HISTORY    Match-drop min prior days needed   (default: 3)
    TRACKAROO_NOTIFY_TIMEOUT_SECONDS    Alert delivery HTTP/SMTP timeout (default: 10)
    TRACKAROO_RESTOCK_COOLDOWN_HOURS    Restock-alert re-fire cooldown (default: 24)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

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


def _env_optional_path(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


# ── File paths ────────────────────────────────────────────────────────
DATA_DIR = _env_path("TRACKAROO_DATA_DIR", BASE_DIR / "data")
DB_PATH = _env_path("TRACKAROO_DB", BASE_DIR / "db" / "trackaroo.db")
SCHEMA_PATH = _env_path("TRACKAROO_SCHEMA", BASE_DIR / "db" / "schema.sql")
WATCHLIST_PATH = _env_path("TRACKAROO_WATCHLIST", BASE_DIR / "db" / "watchlist.csv")
GENERATIONS_PATH = WATCHLIST_PATH.parent / "generations.toml"
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
# baseline, to avoid false alarms from normal stock-level variation. Umart
# added 29-Sep-2026 from 31-Aug: 27 CPU + 155 GPU = 182 (#7, #15); the per-
# category floor is set by its small CPU side.
DEFAULT_MATCH_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "scorptec": {"min_total": 90, "min_per_category": 30},
    "pccg": {"min_total": 20, "min_per_category": 5},
    "umart": {"min_total": 90, "min_per_category": 10},
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

# Days a listing may go unseen -- while its own retailer IS being scraped --
# before it is marked stale. Compared against the retailer's latest snapshot,
# never against now: a retailer in cooldown is silent but healthy, and
# comparing against now would mark its whole catalogue stale in one pass.
STALE_LISTING_DAYS = _env_int("TRACKAROO_STALE_LISTING_DAYS", 7)

# Price anomaly: flag if a price deviates more than this many standard
# deviations from the historical mean for that product+retailer combo
PRICE_ANOMALY_STD_DEVS = _env_float("TRACKAROO_PRICE_ANOMALY_STD_DEVS", 3.0)

# Minimum number of PRIOR data points needed before the sigma test can fire.
# With N points the largest z-score reachable by any single value is about
# sqrt(N), so a 3-sigma trip is not merely unlikely below N=10 -- it is
# impossible. A lower gate walks listings through a check that can never flag
# them, which reads as coverage the check does not have.
MIN_HISTORY_FOR_ANOMALY = _env_int("TRACKAROO_MIN_HISTORY_FOR_ANOMALY", 10)

# Day-over-day fractional price move flagged on its own, independent of the
# sigma test. It needs only two points, so it covers the listings the sigma
# test structurally cannot -- most importantly a flat price history, where the
# prior standard deviation is exactly 0 and no jump is reachable at any N.
# 0.10 rather than 0.20 because the real steps this is meant to catch have been
# +10.5% and +12.1%; at 0.20 both were missed on the day they happened.
PRICE_MOVE_PCT = _env_float("TRACKAROO_PRICE_MOVE_PCT", 0.10)

# Fallback thresholds applied to any retailer NOT in MATCH_THRESHOLDS
DEFAULT_MIN_PER_CATEGORY = _env_int("TRACKAROO_DEFAULT_MIN_PER_CATEGORY", 5)
DEFAULT_MIN_TOTAL = _env_int("TRACKAROO_DEFAULT_MIN_TOTAL", 10)

# Relative drop rule (#7b, #14): today's listings per retailer and category
# below MATCH_DROP_RATIO of the trailing MATCH_DROP_WINDOW_DAYS median is an
# ERROR. Needs MATCH_DROP_MIN_HISTORY prior days; below that the static
# MATCH_THRESHOLDS are the cold-start fallback. PCCG had 54 against ~121 on
# 25-Aug and passed the static floor of 20.
MATCH_DROP_RATIO = _env_float("TRACKAROO_MATCH_DROP_RATIO", 0.6)
MATCH_DROP_WINDOW_DAYS = _env_int("TRACKAROO_MATCH_DROP_WINDOW_DAYS", 7)
MATCH_DROP_MIN_HISTORY = _env_int("TRACKAROO_MATCH_DROP_MIN_HISTORY", 3)

# ── Scraper tuning ────────────────────────────────────────────────────
# Per-scraper subprocess timeout in the daily runner
SCRAPER_TIMEOUT_SECONDS = _env_int("TRACKAROO_SCRAPER_TIMEOUT_SECONDS", 300)

# Algolia request tuning (PCCG rate-limits aggressively on 429s)
ALGOLIA_TIMEOUT_SECONDS = _env_int("TRACKAROO_ALGOLIA_TIMEOUT_SECONDS", 15)
ALGOLIA_MAX_RETRIES = _env_int("TRACKAROO_ALGOLIA_MAX_RETRIES", 3)
ALGOLIA_BACKOFF_MAX_SECONDS = _env_float("TRACKAROO_ALGOLIA_BACKOFF_MAX", 20.0)
ALGOLIA_RATE_LIMIT_WAIT_SECONDS = _env_float("TRACKAROO_ALGOLIA_RATE_LIMIT_WAIT", 5.0)
PCCG_COOLDOWN_HOURS = _env_float("TRACKAROO_PCCG_COOLDOWN_HOURS", 4.0)
PCCG_COOLDOWN_FILE = _env_path("TRACKAROO_PCCG_COOLDOWN_FILE", DATA_DIR / "pccg_cooldown.json")
# Short pause between the CPU and GPU category passes (same Algolia index/IP).
CATEGORY_PASS_DELAY = _env_float("TRACKAROO_CATEGORY_PASS_DELAY", 2.0)

# ── Backup retention and integrity (backup_db.py, #10) ────────────────
# Keep the newest backup of each of the last BACKUP_KEEP *days* (plus the 3
# newest overall). Age-based since 29-Sep-2026: hourly retries and manual runs
# made several backups a day, and keep-the-newest-14 then covered ~11 days.
BACKUP_KEEP = _env_int("TRACKAROO_BACKUP_KEEP", 14)
# Optional off-host copy of every backup (a NAS mount). None = no mirror.
BACKUP_MIRROR_DIR = _env_optional_path("TRACKAROO_BACKUP_MIRROR_DIR")
# check_backups warns when the newest backup is older than this.
BACKUP_MAX_AGE_HOURS = _env_int("TRACKAROO_BACKUP_MAX_AGE_HOURS", 36)

# Polite gap between the two scrapers in the daily runner.
SCRAPER_GAP_SECONDS = _env_float("TRACKAROO_SCRAPER_GAP_SECONDS", 2.0)

# ── Scheduling (deploy/entrypoint*.sh -> run_daily.py --scheduled) ─────
# Same env names the entrypoints always used (no TRACKAROO_ prefix), so one
# setting drives both. The daily run starts at RUN_AT_HOUR; a retailer that
# failed or came back incomplete is retried hourly up to and including
# RETRY_UNTIL_HOUR (#8). Keep RETRY_UNTIL_HOUR < STALENESS_CHECK_HOUR (10) so
# the staleness monitor judges a finished day.
RUN_AT_HOUR = _env_int("RUN_AT_HOUR", 4)
RETRY_UNTIL_HOUR = _env_int("RETRY_UNTIL_HOUR", 9)

# ── Scorptec scraper tuning ───────────────────────────────────────────
SCORPTEC_TIMEOUT_SECONDS = _env_int("TRACKAROO_SCORPTEC_TIMEOUT_SECONDS", 15)
SCORPTEC_MAX_RETRIES = _env_int("TRACKAROO_SCORPTEC_MAX_RETRIES", 2)
SCORPTEC_RETRY_DELAY = _env_float("TRACKAROO_SCORPTEC_RETRY_DELAY", 2.0)
SCORPTEC_PAGE_DELAY = _env_float("TRACKAROO_SCORPTEC_PAGE_DELAY", 0.5)
# Safety cap on pagination per category (avoids infinite loops on a
# misbehaving pagination link).
SCORPTEC_MAX_PAGES = _env_int("TRACKAROO_SCORPTEC_MAX_PAGES", 20)
# Per-run cap on how many stale listing pages check_delisted.py will fetch.
# Retailers we actively scrape. This is the one list that ingest, the health
# checks, the staleness monitor and the query CLI read, so adding retailer four
# is a line here rather than the nine-site hunt THIRD_RETAILER.md warned about.
#
# Deliberately narrower than migrate.PERMITTED_RETAILERS, which is what the
# database will *accept*: the schema tolerates six so its CHECK never needs
# another table rebuild, but a health check that expected all six would alarm
# every morning about retailers that have no scraper.
ACTIVE_RETAILERS = ("scorptec", "pccg", "umart")

# ── Umart ─────────────────────────────────────────────────────────────
# Umart has no WAF and a permissive robots.txt, so these are ordinary
# politeness settings rather than a budget: 20 products per page means roughly
# 11 GPU pages and 3 CPU pages, i.e. ~14 requests once a day.
UMART_TIMEOUT_SECONDS = _env_int("TRACKAROO_UMART_TIMEOUT_SECONDS", 15)
UMART_MAX_RETRIES = _env_int("TRACKAROO_UMART_MAX_RETRIES", 2)
UMART_RETRY_DELAY = _env_float("TRACKAROO_UMART_RETRY_DELAY", 2.0)
UMART_PAGE_DELAY = _env_float("TRACKAROO_UMART_PAGE_DELAY", 1.0)
UMART_MAX_PAGES = _env_int("TRACKAROO_UMART_MAX_PAGES", 30)

SCORPTEC_DELIST_CHECK_MAX = _env_int("TRACKAROO_SCORPTEC_DELIST_CHECK_MAX", 100)
# Slower gap between delisted-check fetches than grid scraping: a burst of
# product-page requests gets throttled (403/429) by the CDN.
SCORPTEC_DELIST_PAGE_DELAY = _env_float("TRACKAROO_SCORPTEC_DELIST_PAGE_DELAY", 1.5)

# ── Algolia pagination tuning (PCCG) ──────────────────────────────────
ALGOLIA_HITS_PER_PAGE = _env_int("TRACKAROO_ALGOLIA_HITS_PER_PAGE", 20)
ALGOLIA_MAX_PAGES = _env_int("TRACKAROO_ALGOLIA_MAX_PAGES", 10)
ALGOLIA_PAGE_DELAY = _env_float("TRACKAROO_ALGOLIA_PAGE_DELAY", 0.3)

# Catalogue fetch — PCCG's public search key is capped at 100 queries per IP
# per hour, so the scraper pulls each category whole (empty query, one page)
# instead of querying once per watchlist product. 1000 is Algolia's maximum
# hitsPerPage; the page cap only matters if a category ever outgrows it.
ALGOLIA_CATALOGUE_HITS_PER_PAGE = _env_int("TRACKAROO_ALGOLIA_CATALOGUE_HITS", 1000)
ALGOLIA_CATALOGUE_MAX_PAGES = _env_int("TRACKAROO_ALGOLIA_CATALOGUE_PAGES", 10)

# ── Spec sync tuning (sync_specs.py) ──────────────────────────────────
SPEC_FETCH_TIMEOUT_SECONDS = _env_int("TRACKAROO_SPEC_FETCH_TIMEOUT", 20)
SPEC_RETRY_BACKOFF = _env_float("TRACKAROO_SPEC_RETRY_BACKOFF", 2.0)
AMD_FETCH_DELAY_SECONDS = _env_float("TRACKAROO_AMD_FETCH_DELAY", 1.0)

# amd.com product pages live under a per-series path. Keyed by the model
# number without its last three digits ("9950" -> "9", "10700" -> "10"), so a
# new Ryzen generation is one line here, not a code change (#20). A series not
# listed gets no URL and the product is reported, never guessed.
AMD_SERIES_PATHS = {
    "5": "5000-series",
    "7": "7000-series",
    "8": "8000-series",
    "9": "9000-series",
    "10": "10000-series",
}

# The Intel spec dataset (toUpperCase78/intel-processors) puts a version in
# each file name, so a dataset update used to need a code change (#20).
# TRACKAROO_INTEL_SPEC_URLS (comma separated) replaces the whole list.
INTEL_SPEC_SOURCE_URLS = [
    u.strip() for u in os.environ.get(
        "TRACKAROO_INTEL_SPEC_URLS",
        "https://raw.githubusercontent.com/toUpperCase78/intel-processors/master/"
        "intel_core_processors_v1_8.csv,"
        "https://raw.githubusercontent.com/toUpperCase78/intel-processors/master/"
        "Intel_Core_Ultra_Processors_v1_10.csv",
    ).split(",") if u.strip()
]

# A product added within this many days that matches no spec record is
# reported as pending (specs usually lag a launch), not unmatched (#20).
SPEC_PENDING_DAYS = _env_int("TRACKAROO_SPEC_PENDING_DAYS", 7)

# ── Spec coverage tuning (health_checks.py check_spec_coverage) ──────
SPEC_COVERAGE_MIN_PCT = _env_float("TRACKAROO_SPEC_COVERAGE_MIN_PCT", 80.0)
SPEC_STALE_THRESHOLD_DAYS = _env_int("TRACKAROO_SPEC_STALE_THRESHOLD_DAYS", 14)

# ── Notifications (check_alerts.py, notify_discord.py) ────────────────
# Shared HTTP/SMTP timeout for outbound alert delivery (Discord webhooks,
# generic webhooks, SMTP). These are best-effort, never-raise calls, so the
# timeout only bounds how long a slow endpoint can hold up the run.
NOTIFY_TIMEOUT_SECONDS = _env_int("TRACKAROO_NOTIFY_TIMEOUT_SECONDS", 10)

# A restock alert may fire at most once per this window per listing -- guards
# against a double run on the same day re-announcing the same
# out-of-stock -> in-stock transition.
RESTOCK_COOLDOWN_HOURS = _env_int("TRACKAROO_RESTOCK_COOLDOWN_HOURS", 24)


# ── Logging ───────────────────────────────────────────────────────────
# Every entry point used to configure logging to stdout only, so a native run
# left no trace once the terminal closed and a failed overnight scrape could
# not be diagnosed after the fact. setup_logging() adds a date-stamped file
# alongside the console output.
#
# A plain FileHandler in append mode (not RotatingFileHandler) is deliberate:
# run_daily.py launches the scrapers as separate processes that log to the same
# file, and concurrent rotation from several processes corrupts the log. Old
# files are pruned by date instead.
LOG_DIR = _env_path("TRACKAROO_LOG_DIR", BASE_DIR / "logs")
LOG_KEEP_DAYS = _env_int("TRACKAROO_LOG_KEEP_DAYS", 30)
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def prune_logs(log_dir=None, keep_days=None):
    """Delete log files older than ``keep_days``. Never raises."""
    import time

    log_dir = log_dir or LOG_DIR
    keep_days = LOG_KEEP_DAYS if keep_days is None else keep_days
    cutoff = time.time() - keep_days * 86400
    try:
        for path in log_dir.glob("trackaroo-*.log"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def setup_logging(level=None, log_dir=None):
    """Configure console + file logging for a Trackaroo entry point.

    Safe to call from any process and more than once: handlers are only added
    to a root logger that doesn't have them yet, so a subprocess scraper and
    its parent both log to the same daily file without duplicating output.

    Args:
        level: Logging level (default INFO).
        log_dir: Directory for log files (default TRACKAROO_LOG_DIR or ./logs).

    Returns:
        The path being logged to, or None if the file could not be opened.
    """
    import logging
    from datetime import date

    level = logging.INFO if level is None else level
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)

    if not any(isinstance(h, logging.StreamHandler)
               and not isinstance(h, logging.FileHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return None  # Already attached (repeat call)

    target = (log_dir or LOG_DIR) / f"trackaroo-{date.today().isoformat()}.log"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target, encoding="utf-8")
    except OSError:
        # A read-only or missing volume must never stop the pipeline running.
        return None

    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    prune_logs(log_dir or LOG_DIR)
    return target
