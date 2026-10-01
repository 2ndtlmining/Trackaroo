"""Staleness monitor — detects the run that never happened.

Every other health check in this repo runs *inside* `run_daily.py`, which means
none of them can fire when the pipeline does not run at all. That is not a
theoretical gap: on 27-Aug-2026 the daily run simply had not happened, and a
human noticed before the system did.

This monitor closes it. It reads only the database — no scraping, no network,
no writes — so it is cheap and safe to run on any schedule, independently of
the pipeline it is watching.

Severity (29-Sep-2026, #8):

- **ERROR** -- nothing in the DB, the DB is missing/unreadable, the newest
  snapshot is older than today, or any active retailer has nothing today
  (including one that has never reported, R1). The monitor runs at
  STALENESS_CHECK_HOUR, after the last retry (RETRY_UNTIL_HOUR), so by then a
  missing day is an outage, not "not yet".
- **WARNING** -- a retailer missing today while its scraper cooldown is
  active (PCCG's circuit breaker): expected, reported, never paged.

Exit code is 1 on ERROR and 0 otherwise, so a scheduler with no Discord
configured still has a usable signal.

Usage:
    python check_staleness.py
    python check_staleness.py --threshold-days 1 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from config import ACTIVE_RETAILERS, DB_PATH, setup_logging
from health_checks import CheckResult, cooldown_explains
from notify_discord import send_alert

LOGGER = logging.getLogger(__name__)

# The monitor runs at STALENESS_CHECK_HOUR (10), after the last hourly retry
# (RETRY_UNTIL_HOUR, 9). By then anything older than today means the day was
# missed. The old default of 1 read yesterday's data as fresh at 10:00 and only
# alerted on day 2 (#8).
DEFAULT_THRESHOLD_DAYS = 0

# Retailers the pipeline is expected to cover. A retailer absent from the DB
# entirely (including one that has never reported at all, R1) is an error by
# STALENESS_CHECK_HOUR unless an active scraper cooldown explains it (#8).
# Sourced from config so a new scraper cannot be added without the monitor
# learning to miss it.
EXPECTED_RETAILERS = ACTIVE_RETAILERS

_STATUS_RANK = {CheckResult.OK: 0, CheckResult.WARNING: 1, CheckResult.ERROR: 2}


def worst_status(results: List[CheckResult]) -> str:
    """Return the most severe status in ``results`` (OK when empty)."""
    if not results:
        return CheckResult.OK
    return max((r.status for r in results), key=lambda s: _STATUS_RANK.get(s, 0))


def evaluate(
    db_path: Optional[Path] = None,
    today: Optional[date] = None,
    threshold_days: Optional[int] = None,
) -> List[CheckResult]:
    """Assess how old the newest price data is. Never raises.

    Args:
        db_path: SQLite database. Defaults to ``config.DB_PATH``.
        today: Reference date, injectable so the tests are not clock-dependent.
        threshold_days: Days of silence tolerated before ERROR.

    Returns:
        List of CheckResult. Always contains at least one entry.
    """
    if db_path is None:
        db_path = DB_PATH
    db_path = Path(db_path)
    if today is None:
        today = date.today()
    if threshold_days is None:
        threshold_days = DEFAULT_THRESHOLD_DAYS

    results: List[CheckResult] = []

    if not db_path.exists():
        return [CheckResult("db_exists", CheckResult.ERROR,
                            f"Database not found: {db_path}")]

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return [CheckResult("db_accessible", CheckResult.ERROR,
                            f"Cannot open database: {e}")]

    try:
        try:
            overall = conn.execute(
                "SELECT MAX(snapshot_date) AS last_date, COUNT(*) AS n FROM price_snapshots"
            ).fetchone()
        except sqlite3.Error as e:
            return [CheckResult("db_readable", CheckResult.ERROR,
                                f"Cannot read price_snapshots: {e}")]

        if not overall or not overall["n"] or not overall["last_date"]:
            return [CheckResult("snapshot_staleness", CheckResult.ERROR,
                                "No price snapshots in the database at all")]

        try:
            last_date = datetime.strptime(overall["last_date"], "%Y-%m-%d").date()
        except ValueError:
            return [CheckResult("snapshot_staleness", CheckResult.ERROR,
                                f"Unparseable snapshot_date: {overall['last_date']!r}")]

        days_since = (today - last_date).days
        if days_since > threshold_days:
            results.append(CheckResult(
                "snapshot_staleness", CheckResult.ERROR,
                f"No price data for {days_since} days — newest snapshot is {last_date} "
                f"(threshold: {threshold_days}). The pipeline has not run.",
            ))
        else:
            results.append(CheckResult(
                "snapshot_staleness", CheckResult.OK,
                f"Newest snapshot {last_date} ({days_since} day(s) ago)",
            ))

        # Per-retailer lag — degraded coverage while the pipeline still runs.
        try:
            rows = conn.execute("""
                SELECT rl.retailer AS retailer, MAX(ps.snapshot_date) AS last_date
                FROM price_snapshots ps
                JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id
                GROUP BY rl.retailer
            """).fetchall()
        except sqlite3.Error as e:
            results.append(CheckResult("retailer_staleness", CheckResult.WARNING,
                                       f"Could not break down by retailer: {e}"))
            return results

        seen = {r["retailer"]: r["last_date"] for r in rows}
        for retailer in EXPECTED_RETAILERS:
            name = f"retailer_staleness_{retailer}"
            try:
                r_last = datetime.strptime(seen[retailer], "%Y-%m-%d").date() if retailer in seen else None
            except (ValueError, TypeError):
                results.append(CheckResult(
                    name, CheckResult.WARNING,
                    f"Unparseable snapshot_date for {retailer}: {seen[retailer]!r}"))
                continue
            r_days = (today - r_last).days if r_last else None
            if r_days is not None and r_days <= threshold_days:
                results.append(CheckResult(name, CheckResult.OK, f"{retailer} current as of {r_last}"))
                continue
            what = (f"{retailer} last seen {r_last} ({r_days} day(s) ago)" if r_last
                    else f"No snapshot data for {retailer} at all")
            if cooldown_explains(retailer):
                results.append(CheckResult(name, CheckResult.WARNING,
                                           f"{what} - scraper cooldown active, expected"))
            else:
                results.append(CheckResult(name, CheckResult.ERROR,
                                           f"{what} - the scraper is failing or not running"))

        return results
    finally:
        conn.close()


def run(
    db_path: Optional[str] = None,
    today: Optional[date] = None,
    threshold_days: Optional[int] = None,
    dry_run: bool = False,
) -> int:
    """Evaluate staleness, alert on ERROR, and return an exit code.

    Never raises — a monitor that crashes is a monitor that is silently off.

    Returns:
        1 if any check errored, 0 otherwise.
    """
    try:
        results = evaluate(
            db_path=Path(db_path) if db_path else None,
            today=today,
            threshold_days=threshold_days,
        )
    except Exception as e:  # defensive: the monitor must always report something
        LOGGER.error("Staleness check itself failed: %s", e)
        results = [CheckResult("staleness_check", CheckResult.ERROR,
                               f"Staleness check failed: {e}")]

    for r in results:
        log = LOGGER.error if r.status == CheckResult.ERROR else (
            LOGGER.warning if r.status == CheckResult.WARNING else LOGGER.info)
        log("  %s", r)

    errors = [r for r in results if r.status == CheckResult.ERROR]
    if not errors:
        LOGGER.info("Staleness check: OK (%d checks)", len(results))
        return 0

    lines = [f"- {r.check_name}: {r.message}" for r in errors]
    try:
        send_alert(["**Trackaroo data is stale**"] + lines, dry_run=dry_run)
    except Exception as e:
        # Alerting is best-effort; the exit code still carries the signal.
        LOGGER.error("Could not send staleness alert: %s", e)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Alert when Trackaroo's price data has gone stale (a run never happened)")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: config.DB_PATH)")
    parser.add_argument("--threshold-days", type=int, default=None,
                        help="Days of silence tolerated before ERROR (default: 0 = today must have data)")
    parser.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD), for testing")
    parser.add_argument("--dry-run", action="store_true", help="Print the alert instead of posting it")
    args = parser.parse_args(argv)

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    return run(db_path=args.db, today=today,
               threshold_days=args.threshold_days, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
