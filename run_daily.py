"""
Daily scrape-and-ingest runner for Trackaroo.

Runs all configured scrapers, saves JSON snapshots to data/, then ingests
everything into the SQLite database. Health checks validate output at each
stage. One command to collect a full day's data.

Usage:
    python run_daily.py              # Run all scrapers + ingest + health checks
    python run_daily.py --scorptec   # Only Scorptec
    python run_daily.py --pccg       # Only PCCG
    python run_daily.py --dry-run    # Preview without writing to DB
    python run_daily.py --scrape-only  # Scrape but don't ingest (just save JSON)
    python run_daily.py --no-health  # Skip health checks
    python run_daily.py --no-notify  # Skip the Discord digest
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import date
from typing import Any, Dict, List, Optional

from config import (
    BACKUP_KEEP,
    DATA_DIR,
    DB_DATE_FORMAT,
    DB_PATH,
    FILE_DATE_FORMAT,
    SCRAPER_GAP_SECONDS,
    SCRAPER_TIMEOUT_SECONDS,
    setup_logging,
)
from health_checks import (
    CheckResult,
    check_db_freshness,
    check_json_db_parity,
    check_json_files,
    check_match_count_anomalies,
    check_missing_days,
    check_scraper_cooldown,
    check_price_anomalies,
    check_spec_coverage,
    check_today_coverage,
)
from ingest import init_db

LOGGER = logging.getLogger(__name__)


def today_filename() -> str:
    """Return today's date string for filenames, e.g. '10_August_2026'."""
    return date.today().strftime(FILE_DATE_FORMAT)


def run_scraper(name: str, module: str, label: str) -> bool:
    """Run a scraper module and report success/failure.

    Args:
        name: Display name (e.g. 'Scorptec')
        module: Python module path (e.g. 'scraper.scorptec' or 'scraper.pccg')
        label: Short label for summary (e.g. 'scorptec')

    Returns:
        True if the scraper ran successfully, False otherwise.
    """
    LOGGER.info("\n%s\nScraping %s...\n%s", "=" * 60, name, "=" * 60)
    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=False,
            text=True,
            timeout=SCRAPER_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            LOGGER.info("\n%s completed in %.1fs", name, elapsed)
            return True
        LOGGER.error(
            "\n%s failed (exit code %s) after %.1fs",
            name,
            result.returncode,
            elapsed,
        )
        return False
    except subprocess.TimeoutExpired:
        LOGGER.error("\n%s timed out after %ds", name, SCRAPER_TIMEOUT_SECONDS)
        return False
    except Exception as e:  # noqa: BLE001 - CLI wrapper reports any failure
        LOGGER.error("\n%s error: %s", name, e)
        return False


def ingest_today(conn: Any, dry_run: bool = False) -> Dict[str, int]:
    """Ingest all JSON files for today's date.

    Args:
        conn: Open SQLite connection.
        dry_run: When True, only report what would happen without writing.

    Returns:
        Stats dict with inserted/skipped/errors counts.
    """
    from ingest import ingest_file

    today = today_filename()
    files = sorted(DATA_DIR.glob(f"*_{today}.json"))

    if not files:
        LOGGER.info("\nNo JSON files found for today (%s)", today)
        return {}

    total_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    for f in files:
        LOGGER.info("\n  Ingesting: %s", f.name)
        stats = ingest_file(conn, f, dry_run=dry_run)
        total_stats["inserted"] += stats["inserted"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]

    return total_stats


def _report_results(results: List[CheckResult], label: str) -> None:
    """Log health check results grouped by status.

    Args:
        results: List of CheckResult objects.
        label: Human-readable label (e.g. 'JSON validation').
    """
    errors = [r for r in results if r.status == CheckResult.ERROR]
    warnings = [r for r in results if r.status == CheckResult.WARNING]

    if errors:
        LOGGER.error("\n%s errors (%d):", label, len(errors))
        for r in errors:
            LOGGER.error("  %s", r)
    if warnings:
        LOGGER.warning("\n%s warnings (%d):", label, len(warnings))
        for r in warnings:
            LOGGER.warning("  %s", r)


def health_errors(*result_groups: List[CheckResult]) -> List[CheckResult]:
    """Flatten one or more check result lists down to their ERROR entries.

    Used to gate the Discord digest: a run with any ERROR-level health result
    should not celebrate moves built from partial/garbage data.
    """
    return [r for r in sum(result_groups, []) if r.status == CheckResult.ERROR]


def notify_enabled(args: argparse.Namespace) -> bool:
    """True when the Discord digest should be attempted.

    Digest only fires on a real, full run with health checks on — dry runs,
    scrape-only, skipped health checks, or an explicit --no-notify all disable it.
    """
    return not (args.dry_run or args.scrape_only or args.no_health or args.no_notify)


def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Daily scrape-and-ingest runner")
    parser.add_argument("--scorptec", action="store_true", help="Only run Scorptec scraper")
    parser.add_argument("--pccg", action="store_true", help="Only run PCCG scraper")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape but don't ingest")
    parser.add_argument("--no-health", action="store_true", help="Skip health checks")
    parser.add_argument("--no-notify", action="store_true", help="Skip the Discord digest")
    parser.add_argument("--no-backup", action="store_true", help="Skip the automatic DB backup")
    args = parser.parse_args(argv)

    # Determine which scrapers to run
    run_scorptec = (not args.scorptec and not args.pccg) or args.scorptec
    run_pccg = (not args.scorptec and not args.pccg) or args.pccg

    if not run_scorptec and not run_pccg:
        LOGGER.error("No scrapers selected. Use --scorptec, --pccg, or neither for both.")
        sys.exit(1)

    LOGGER.info("Trackaroo daily run — %s", today_filename())
    LOGGER.info("Scorptec: %s  |  PCCG: %s", "Yes" if run_scorptec else "No", "Yes" if run_pccg else "No")

    # ── Scrape ──────────────────────────────────────────────
    results: Dict[str, bool] = {}
    if run_scorptec:
        results["scorptec"] = run_scraper("Scorptec", "scraper.scorptec", "scorptec")
        time.sleep(SCRAPER_GAP_SECONDS)  # Polite delay between scrapers
    if run_pccg:
        results["pccg"] = run_scraper("PCCG", "scraper.pccg", "pccg")

    # Report scrape results
    LOGGER.info("\n%s\nScrape summary:\n%s", "=" * 60, "=" * 60)
    for name, ok in results.items():
        status = "OK" if ok else "FAIL"
        LOGGER.info("  %s %s", status, name)

    if not any(results.values()):
        LOGGER.error("\nAll scrapers failed. Aborting.")
        sys.exit(1)

    # ── Health check: validate JSON before ingestion ───────
    json_results: List[CheckResult] = []
    if not args.no_health:
        json_results = check_json_files(today_filename())
        _report_results(json_results, "JSON validation")

    # ── Ingest ──────────────────────────────────────────────
    if args.scrape_only:
        LOGGER.info("\nScrape-only mode — skipping ingestion.")
        LOGGER.info("JSON files saved to data/")
        return

    conn = init_db(DB_PATH)
    try:
        stats = ingest_today(conn, dry_run=args.dry_run)

        if stats:
            mode = "(DRY RUN)" if args.dry_run else ""
            LOGGER.info("\n%s\nIngestion summary %s:\n%s", "=" * 60, mode, "=" * 60)
            LOGGER.info("  Inserted: %d", stats["inserted"])
            LOGGER.info("  Skipped:  %d", stats["skipped"])
            LOGGER.info("  Errors:   %d", stats["errors"])
            LOGGER.info("%s", "=" * 60)
        else:
            LOGGER.info("\nNo new data to ingest.")

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    # ── Mirror the DB back out to JSON ──────────────────────────────
    # data/*.json is the backup the DB is rebuilt from, so it must hold every
    # snapshot the DB does. A scrape that partially fails (or one whose result
    # was diverted by the no-downgrade guard in scraper/snapshot_io.py) leaves
    # JSON short. Re-exporting today's date from the DB closes that gap on
    # every run, so the invariant "JSON can rebuild the DB" always holds.
    # Best-effort: a mirror failure must never break the daily run.
    if not args.dry_run:
        try:
            from export_snapshots import run as run_export
            totals = run_export(dates=[date.today().strftime(DB_DATE_FORMAT)],
                                repair_only=True)
            if totals["recovered"]:
                LOGGER.warning(
                    "JSON backup was short by %d snapshot(s) — repaired %d file(s).",
                    totals["recovered"], totals["written"],
                )
        except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
            LOGGER.error("JSON mirror failed: %s", e)


    # ── Health check: validate DB state after ingestion ───
    db_results: List[CheckResult] = []
    if not args.no_health and not args.scrape_only:
        db_results = (
            check_db_freshness(DB_PATH)
            + check_today_coverage(DB_PATH)
            + check_match_count_anomalies(DB_PATH)
            + check_price_anomalies(DB_PATH)
            + check_spec_coverage(DB_PATH)
            + check_json_db_parity(db_path=DB_PATH)
            + check_missing_days(DB_PATH)
            + check_scraper_cooldown()
        )
        _report_results(db_results, "DB validation")

        ok_count = sum(1 for r in db_results if r.status == CheckResult.OK)
        errors = [r for r in db_results if r.status == CheckResult.ERROR]
        warnings = [r for r in db_results if r.status == CheckResult.WARNING]
        if not errors and not warnings:
            LOGGER.info("\nDB health: all %d checks passed", ok_count)

    # ── Delisted listing check (Scorptec) ───────────────────
    # Products delisted from the Scorptec grid never get a new snapshot, so
    # their last (often in_stock) one stays latest forever. Fetch the product
    # pages of listings missing from today's scrape and mark confirmed
    # delistings. Gated on a successful Scorptec scrape (a failed scrape would
    # make every listing look stale). Best-effort: never breaks the run.
    if results.get("scorptec") and not args.dry_run:
        try:
            from check_delisted import run as run_delisted
            run_delisted()
        except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
            LOGGER.error("Delisted check failed: %s", e)

    # ── Discord digest (optional) ──────────────────────────────────────
    # Only on a real full run with passing health checks: a partial or
    # unchecked scrape shouldn't celebrate moves that may be artifacts.
    if notify_enabled(args):
        failed = health_errors(json_results, db_results)
        if failed:
            LOGGER.warning("Skipping Discord digest — %d health check error(s).", len(failed))
        else:
            from notify_discord import run as run_notify
            run_notify()

        # Pipeline-issue alert: the digest is gated on a clean run, so any
        # scraper failure or health error gets its own Discord message.
        from notify_discord import send_alert
        alert_lines = [
            f"- Scraper **{name.title()}** failed" for name, ok in results.items() if not ok
        ]
        alert_lines += [f"- Health check error: {r}" for r in failed]
        # A missed run leaves no other trace, so surface calendar gaps too.
        alert_lines += [
            f"- {r.message}"
            for r in db_results
            if r.check_name == "missing_days" and r.status == CheckResult.WARNING
        ]
        if alert_lines:
            send_alert(alert_lines)

        # ── Price-drop & restock alerts (optional) ────────────────────
        # Same clean-run gating as the digest: a partial or unhealthy scrape
        # shouldn't fire "buy now" alerts built on garbage data. Best-effort:
        # a missing price_alerts table or delivery failure must never break
        # the daily run (matching the delisted-check pattern).
        if not failed:
            try:
                from check_alerts import run as run_alerts
                run_alerts()
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("Price alerts check failed: %s", e)

    # ── Backup (automatic) ──────────────────────────────────────────
    # A real full run always snapshots the DB first (keeps the last
    # BACKUP_KEEP days) so today's data is never lost. Opt out via
    # --no-backup. Skips on dry-run / scrape-only (nothing was written).
    if not args.no_backup and not args.dry_run and not args.scrape_only:
        from backup_db import backup_database
        LOGGER.info("\n%s\nBacking up database:\n%s", "=" * 60, "=" * 60)
        backup_database(keep=BACKUP_KEEP)


if __name__ == "__main__":
    main()
