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
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import (
    ACTIVE_RETAILERS,
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
from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED

LOGGER = logging.getLogger(__name__)


def today_filename() -> str:
    """Return today's date string for filenames, e.g. '10_August_2026'."""
    return date.today().strftime(FILE_DATE_FORMAT)


# Process exit codes for run_daily itself. The entrypoints log any non-zero as
# "finished with errors" and carry on; DEPLOYMENT.md documents these.
RUN_EXIT_OK = 0
RUN_EXIT_ALL_FAILED = 1   # nothing was scraped, or the run crashed
RUN_EXIT_DEGRADED = 2     # a scraper or health check failed; good data was kept

# What one scraper run can end as. scrape_runs.status (Task 4) uses the same set.
SCRAPE_STATUSES = ("ok", "degraded", "skipped", "auth", "failed", "timeout")

_OUTCOME_TEXT = {
    "degraded": "returned an incomplete result",
    "skipped": "was skipped (cooldown active - expected)",
    "auth": "was refused by the retailer (credentials rejected) - needs a human",
    "failed": "failed",
    "timeout": f"timed out after {SCRAPER_TIMEOUT_SECONDS}s",
}


@dataclass
class ScrapeOutcome:
    """What one scraper subprocess did (#7, #8, R3)."""
    retailer: str
    status: str                        # one of SCRAPE_STATUSES
    exit_code: Optional[int] = None
    started_at: str = ""               # local ISO8601, seconds
    finished_at: str = ""
    matched: Optional[int] = None      # products matched (from the run report)
    detail: str = ""
    report: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def needs_alert(self) -> bool:
        """Everything except success and an expected cooldown skip pages someone."""
        return self.status not in ("ok", "skipped")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_STATUS_BY_EXIT = {EXIT_OK: "ok", EXIT_DEGRADED: "degraded",
                   EXIT_SKIPPED: "skipped", EXIT_AUTH: "auth"}


def status_for_exit(code: int) -> str:
    """Map a scraper's exit code to a ScrapeOutcome status (see scraper/run_report.py).

    1 (an uncaught exception) and a negative code (killed by a signal) are
    both plain failures.
    """
    return _STATUS_BY_EXIT.get(code, "failed")


def outcome_alert_line(o: ScrapeOutcome) -> str:
    """One Discord bullet describing a scraper problem."""
    label = SCRAPERS[o.retailer][0] if o.retailer in SCRAPERS else o.retailer.title()
    text = _OUTCOME_TEXT.get(o.status, o.status)
    if o.status == "failed" and o.exit_code is not None:
        text += f" (exit code {o.exit_code})"
    if o.detail:
        text += f": {o.detail}"
    return f"- Scraper **{label}** {text}"


def run_scraper(name: str, module: str, label: str) -> ScrapeOutcome:
    """Run a scraper module as a subprocess and classify what happened.

    Args:
        name: Display name (e.g. 'Scorptec')
        module: Python module path (e.g. 'scraper.scorptec')
        label: Retailer slug (e.g. 'scorptec')
    """
    LOGGER.info("\n%s\nScraping %s...\n%s", "=" * 60, name, "=" * 60)
    started = _now()
    start = time.time()
    status, exit_code = "failed", None
    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=False,
            text=True,
            timeout=SCRAPER_TIMEOUT_SECONDS,
        )
        exit_code = result.returncode
        status = status_for_exit(exit_code)
    except subprocess.TimeoutExpired:
        status = "timeout"
    except Exception as e:  # noqa: BLE001 - CLI wrapper reports any failure
        LOGGER.error("\n%s error: %s", name, e)

    outcome = ScrapeOutcome(label, status, exit_code, started_at=started, finished_at=_now())
    elapsed = time.time() - start
    if outcome.ok:
        LOGGER.info("\n%s completed in %.1fs", name, elapsed)
    else:
        LOGGER.error("\n%s %s (exit code %s) after %.1fs", name, status, exit_code, elapsed)
    return outcome


def ingest_today(conn: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Ingest all JSON files for today's date.

    A file that cannot be read is skipped and named in ``bad_files`` rather
    than aborting the rest (#12).

    Returns:
        Stats dict with inserted/skipped/errors counts and ``bad_files``, or
        {} when there are no files for today.
    """
    from ingest import ingest_file

    today = today_filename()
    files = sorted(DATA_DIR.glob(f"*_{today}.json"))

    if not files:
        LOGGER.info("\nNo JSON files found for today (%s)", today)
        return {}

    total_stats: Dict[str, Any] = {"inserted": 0, "skipped": 0, "errors": 0, "bad_files": []}

    for f in files:
        LOGGER.info("\n  Ingesting: %s", f.name)
        try:
            stats = ingest_file(conn, f, dry_run=dry_run)
        except Exception:  # noqa: BLE001 - one file must never stop the rest
            LOGGER.exception("Ingest of %s crashed - skipping it", f.name)
            # ingest_file() only commits once, at the very end of its own
            # loop (ingest.py) -- a crash partway through a file (e.g. a
            # non-dict entry in "products") leaves whatever it already
            # inserted uncommitted on this shared connection. Every earlier
            # file already committed its own work via that same call, so the
            # pending transaction at this point belongs entirely to the file
            # that just crashed; rolling it back is exactly "this file wrote
            # nothing" without touching any prior file's committed rows.
            # Without this, those rows ride along on the next successful
            # file's commit() (or this run's own final commit) even though
            # the file is reported in bad_files (I1).
            conn.rollback()
            total_stats["errors"] += 1
            total_stats["bad_files"].append(f.name)
            continue
        if stats.get("unreadable"):
            total_stats["bad_files"].append(f.name)
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


def alerts_enabled(args: argparse.Namespace) -> bool:
    """True when pipeline-issue alerts may be sent.

    Every real run alerts, including --no-health and --scrape-only ones; only a
    dry run or an explicit --no-notify stays silent.
    """
    return not (args.dry_run or args.no_notify)


def best_effort(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one best-effort pipeline step (#12, R4).

    CLAUDE.md: steps after ingest must never break a run that already
    collected good data. Any exception is logged with its traceback and
    swallowed.

    Returns:
        ``fn``'s return value, or None when it raised.
    """
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 - best-effort by contract
        LOGGER.exception("%s failed (best-effort; the run continues)", label)
        return None


def guarded_check(name: str, check: Callable[[], List[CheckResult]]) -> List[CheckResult]:
    """Run one health check; a crash becomes an ERROR result, never an exception (R4)."""
    try:
        return list(check())
    except Exception as e:  # noqa: BLE001 - a broken check must still be reported
        LOGGER.exception("Health check %s crashed", name)
        return [CheckResult(f"{name}_crashed", CheckResult.ERROR,
                            f"{name} raised {type(e).__name__}: {e}")]


def _db_checks() -> List[Tuple[str, Callable[[], List[CheckResult]]]]:
    """The post-ingest DB checks, in report order.

    Lambdas look the check functions up at call time, so tests can patch them
    on this module.
    """
    return [
        ("check_db_freshness", lambda: check_db_freshness(DB_PATH)),
        ("check_today_coverage", lambda: check_today_coverage(DB_PATH)),
        ("check_match_count_anomalies", lambda: check_match_count_anomalies(DB_PATH)),
        ("check_price_anomalies", lambda: check_price_anomalies(DB_PATH)),
        ("check_spec_coverage", lambda: check_spec_coverage(DB_PATH)),
        ("check_json_db_parity", lambda: check_json_db_parity(db_path=DB_PATH)),
        ("check_missing_days", lambda: check_missing_days(DB_PATH)),
        ("check_scraper_cooldown", lambda: check_scraper_cooldown()),
    ]


def run_db_checks() -> List[CheckResult]:
    """Every DB health check; one crashing check no longer skips the rest (R4)."""
    results: List[CheckResult] = []
    for name, check in _db_checks():
        results.extend(guarded_check(name, check))
    return results


def send_pipeline_alert(lines: List[str]) -> None:
    """Post a pipeline-issue alert to DISCORD_WEBHOOK_ALERT; never raises."""
    def _send() -> None:
        from notify_discord import send_alert
        send_alert(lines)

    # The import lives inside the guarded callable (not above this call) so
    # an import failure is caught by best_effort too, same as a delivery
    # failure -- otherwise it escapes send_pipeline_alert entirely and (from
    # the all-failed/scrape-only/final-alert call sites) can trip main()'s
    # outer crash handler into sending a second, redundant "crashed" alert
    # (M2).
    best_effort("Pipeline alert", _send)


# Display label and module path per retailer, keyed by ACTIVE_RETAILERS. A
# retailer added to that list without a scraper module raises a KeyError here
# rather than being quietly skipped for a run.
SCRAPERS: Dict[str, Tuple[str, str]] = {
    "scorptec": ("Scorptec", "scraper.scorptec"),
    "pccg": ("PCCG", "scraper.pccg"),
    "umart": ("Umart", "scraper.umart"),
}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI.

    The per-retailer flags are generated from ACTIVE_RETAILERS rather than
    written out, so a fourth retailer cannot end up unselectable.
    """
    parser = argparse.ArgumentParser(description="Daily scrape-and-ingest runner")
    for retailer in ACTIVE_RETAILERS:
        parser.add_argument(
            f"--{retailer}",
            action="store_true",
            help=f"Only run the {SCRAPERS[retailer][0]} scraper",
        )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape but don't ingest")
    parser.add_argument("--no-health", action="store_true", help="Skip health checks")
    parser.add_argument("--no-notify", action="store_true", help="Skip the Discord digest")
    parser.add_argument("--no-backup", action="store_true", help="Skip the automatic DB backup")
    return parser


def selected_retailers(args: argparse.Namespace) -> List[str]:
    """Retailers to scrape this run, in ACTIVE_RETAILERS order.

    No retailer flag means all of them, so the scheduled run is unchanged.
    """
    chosen = [r for r in ACTIVE_RETAILERS if getattr(args, r, False)]
    return chosen or list(ACTIVE_RETAILERS)


def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    args = build_parser().parse_args(argv)
    try:
        code = run(args)
    except Exception:  # noqa: BLE001 - last line of defence: a crash must still page
        LOGGER.exception("Daily run crashed")
        if alerts_enabled(args):
            send_pipeline_alert(["- **Daily run crashed** - see the log for the traceback."])
        code = RUN_EXIT_ALL_FAILED
    if code:
        sys.exit(code)


def run(args: argparse.Namespace) -> int:
    """One pipeline run. Returns the process exit code (RUN_EXIT_*)."""
    to_run = selected_retailers(args)

    LOGGER.info("Trackaroo daily run - %s", today_filename())
    LOGGER.info("Scraping: %s", "  |  ".join(SCRAPERS[r][0] for r in to_run))

    # ── Scrape ──────────────────────────────────────────────
    results: Dict[str, ScrapeOutcome] = {}
    for i, retailer in enumerate(to_run):
        if i:
            time.sleep(SCRAPER_GAP_SECONDS)  # Polite delay between scrapers
        label, module = SCRAPERS[retailer]
        results[retailer] = run_scraper(label, module, retailer)

    LOGGER.info("\n%s\nScrape summary:\n%s", "=" * 60, "=" * 60)
    for name, outcome in results.items():
        LOGGER.info("  %s %s", outcome.status.upper(), name)

    scraper_lines = [outcome_alert_line(o) for o in results.values() if o.needs_alert]

    if not any(o.ok for o in results.values()):
        if not scraper_lines:
            # Every selected scraper was deliberately skipped (a --pccg retry
            # during its cooldown): expected, and nothing new to ingest.
            LOGGER.info("\nEvery selected scraper was skipped - nothing to ingest.")
            return RUN_EXIT_OK
        # Nothing new to ingest or back up -- but this is the run that most
        # needs to page someone, and it used to exit before any alert (#12).
        LOGGER.error("\nAll scrapers failed. Aborting.")
        if alerts_enabled(args):
            send_pipeline_alert(["- **All scrapers failed** - no new data this run."] + scraper_lines)
        return RUN_EXIT_ALL_FAILED

    # ── Health check: validate JSON before ingestion ───────
    json_results: List[CheckResult] = []
    if not args.no_health:
        json_results = guarded_check("check_json_files", lambda: check_json_files(today_filename()))
        _report_results(json_results, "JSON validation")

    # ── Ingest ──────────────────────────────────────────────
    if args.scrape_only:
        LOGGER.info("\nScrape-only mode - skipping ingestion.")
        LOGGER.info("JSON files saved to data/")
        # Controller ruling F1: alerts_enabled(args), not notify_enabled(args)
        # -- a scrape-only run must still page on a scraper/JSON problem even
        # though it never reaches the digest.
        if alerts_enabled(args):
            alert_lines = list(scraper_lines)
            alert_lines += [
                f"- Health check error: {r}" for r in json_results if r.status == CheckResult.ERROR
            ]
            if alert_lines:
                send_pipeline_alert(alert_lines)
        return RUN_EXIT_DEGRADED if scraper_lines else RUN_EXIT_OK

    ingest_results: List[CheckResult] = []
    db_results: List[CheckResult] = []
    failed: List[CheckResult] = []
    try:
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
                if stats.get("bad_files"):
                    ingest_results.append(CheckResult(
                        "ingest_unreadable_json", CheckResult.ERROR,
                        "Skipped unreadable snapshot file(s): " + ", ".join(stats["bad_files"]),
                    ))
            else:
                LOGGER.info("\nNo new data to ingest.")

            if not args.dry_run:
                conn.commit()
        finally:
            conn.close()
        _report_results(ingest_results, "Ingest")

        # ── Mirror the DB back out to JSON ──────────────────────────────
        # data/*.json is the backup the DB is rebuilt from, so it must hold
        # every snapshot the DB does. Best-effort: never breaks the run.
        if not args.dry_run:
            try:
                from export_snapshots import run as run_export
                totals = run_export(dates=[date.today().strftime(DB_DATE_FORMAT)],
                                    repair_only=True)
                if totals["recovered"]:
                    LOGGER.warning(
                        "JSON backup was short by %d snapshot(s) - repaired %d file(s).",
                        totals["recovered"], totals["written"],
                    )
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("JSON mirror failed: %s", e)

        # ── Health check: validate DB state after ingestion ───
        if not args.no_health:
            db_results = run_db_checks()
            _report_results(db_results, "DB validation")
            ok_count = sum(1 for r in db_results if r.status == CheckResult.OK)
            if not any(r.status != CheckResult.OK for r in db_results):
                LOGGER.info("\nDB health: all %d checks passed", ok_count)

        # ── Delisted listing check (Scorptec) ───────────────────
        # Gated on a successful Scorptec scrape: a failed or empty one would
        # make every listing look delisted (#7d). Best-effort.
        scorptec = results.get("scorptec")
        if scorptec is not None and scorptec.ok and not args.dry_run:
            try:
                from check_delisted import run as run_delisted
                run_delisted()
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("Delisted check failed: %s", e)

        # ── Stale-listing check (all retailers) ─────────────────────────
        if not args.dry_run:
            try:
                from check_stale_listings import run as run_stale_listings
                run_stale_listings()
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("Stale-listing check failed: %s", e)

        failed = health_errors(json_results, ingest_results, db_results)

        # ── Discord digest ───────────────────────────────────────────────
        # Only on a real, full run with health checks on and a clean result:
        # a partial or unchecked scrape shouldn't celebrate moves that may be
        # artifacts.
        if notify_enabled(args):
            if failed or scraper_lines:
                # A clean-looking digest over a failed or empty scrape is the
                # silent failure #7 describes.
                LOGGER.warning("Skipping Discord digest - %d health check error(s), %d scraper problem(s).",
                               len(failed), len(scraper_lines))
            else:
                def _run_digest() -> None:
                    from notify_discord import run as run_notify
                    run_notify()

                # Import inside the guarded callable (M2): a notify_discord
                # import failure must be caught by best_effort, not escape
                # into the finally block and beyond.
                best_effort("Discord digest", _run_digest)

            # ── Price-drop & restock alerts ───────────────────────────
            # Same clean-run gating as the digest: no "buy now" built on
            # garbage data. Controller ruling F1: these stay under
            # notify_enabled (unlike the pipeline alert below), so --no-health
            # / --scrape-only keep them off along with the digest.
            if not failed:
                try:
                    from check_alerts import run as run_alerts
                    run_alerts()
                except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                    LOGGER.error("Price alerts check failed: %s", e)

        # ── Pipeline-issue alert ──────────────────────────────────────────
        # Controller ruling F1: gated on alerts_enabled(args), not
        # notify_enabled(args) -- a --no-health or --scrape-only run must
        # still page someone on a scraper or health-check problem even though
        # its digest stays off. Only a dry run or an explicit --no-notify
        # stays silent (a later task's backup alert also relies on this).
        if alerts_enabled(args):
            alert_lines = list(scraper_lines)
            alert_lines += [f"- Health check error: {r}" for r in failed]
            # A missed run leaves no other trace, so surface calendar gaps too.
            alert_lines += [
                f"- {r.message}"
                for r in db_results
                if r.check_name == "missing_days" and r.status == CheckResult.WARNING
            ]
            if alert_lines:
                send_pipeline_alert(alert_lines)
    finally:
        # ── Backup (automatic) ──────────────────────────────────────────
        # In a finally so that nothing above -- a crashed digest, a broken
        # health check -- can skip it (#12). Scrape-only and dry runs wrote
        # nothing and returned earlier / are excluded here.
        if not args.no_backup and not args.dry_run:
            def _backup() -> None:
                from backup_db import backup_database
                backup_database(keep=BACKUP_KEEP)

            LOGGER.info("\n%s\nBacking up database:\n%s", "=" * 60, "=" * 60)
            # Import inside the guarded callable (M2): this runs in a
            # finally, so an import failure here must not escape it either.
            best_effort("Database backup", _backup)

    return RUN_EXIT_DEGRADED if (scraper_lines or failed) else RUN_EXIT_OK


if __name__ == "__main__":
    main()
