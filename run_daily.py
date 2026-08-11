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
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

DATA_DIR = Path("data")


def today_filename():
    """Return today's date string for filenames, e.g. '10_August_2026'."""
    return date.today().strftime("%d_%B_%Y")


def run_scraper(name: str, module: str, label: str) -> bool:
    """Run a scraper module and report success/failure.

    Args:
        name: Display name (e.g. 'Scorptec')
        module: Python module path (e.g. 'fetch_test' or 'scraper.pccg')
        label: Short label for summary (e.g. 'scorptec')
    Returns:
        True if the scraper ran successfully, False otherwise.
    """
    print(f"\n{'=' * 60}")
    print(f"Scraping {name}...")
    print(f"{'=' * 60}")
    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=False,
            text=True,
            timeout=300,  # 5 min timeout per scraper
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            print(f"\n{name} completed in {elapsed:.1f}s")
            return True
        else:
            print(f"\n{name} failed (exit code {result.returncode}) after {elapsed:.1f}s")
            return False
    except subprocess.TimeoutExpired:
        print(f"\n{name} timed out after 300s")
        return False
    except Exception as e:
        print(f"\n{name} error: {e}")
        return False


def ingest_today(conn, dry_run: bool = False) -> dict:
    """Ingest all JSON files for today's date.

    Returns a stats dict with inserted/skipped/errors per retailer.
    """
    from ingest import ingest_file

    today = today_filename()
    files = sorted(DATA_DIR.glob(f"*_{today}.json"))

    if not files:
        print(f"\nNo JSON files found for today ({today})")
        return {}

    total_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    for f in files:
        print(f"\n  Ingesting: {f.name}")
        stats = ingest_file(conn, f, dry_run=dry_run)
        total_stats["inserted"] += stats["inserted"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]

    return total_stats


def main():
    parser = argparse.ArgumentParser(description="Daily scrape-and-ingest runner")
    parser.add_argument("--scorptec", action="store_true", help="Only run Scorptec scraper")
    parser.add_argument("--pccg", action="store_true", help="Only run PCCG scraper")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape but don't ingest")
    parser.add_argument("--no-health", action="store_true", help="Skip health checks")
    args = parser.parse_args()

    # Determine which scrapers to run
    run_scorptec = (not args.scorptec and not args.pccg) or args.scorptec
    run_pccg = (not args.scorptec and not args.pccg) or args.pccg

    if not run_scorptec and not run_pccg:
        print("No scrapers selected. Use --scorptec, --pccg, or neither for both.")
        sys.exit(1)

    print(f"Trackaroo daily run — {today_filename()}")
    print(f"Scorptec: {'Yes' if run_scorptec else 'No'}  |  PCCG: {'Yes' if run_pccg else 'No'}")

    # ── Scrape ──────────────────────────────────────────────
    results = {}
    if run_scorptec:
        results["scorptec"] = run_scraper("Scorptec", "fetch_test", "scorptec")
        time.sleep(2)  # Polite delay between scrapers
    if run_pccg:
        results["pccg"] = run_scraper("PCCG", "scraper.pccg", "pccg")

    # Report scrape results
    print(f"\n{'=' * 60}")
    print("Scrape summary:")
    for name, ok in results.items():
        status = "OK" if ok else "FAIL"
        print(f"  {status} {name}")

    if not any(results.values()):
        print("\nAll scrapers failed. Aborting.")
        sys.exit(1)

    # ── Health check: validate JSON before ingestion ───────
    if not args.no_health:
        from health_checks import check_json_files, CheckResult
        json_results = check_json_files(today_filename())
        json_errors = [r for r in json_results if r.status == CheckResult.ERROR]
        json_warnings = [r for r in json_results if r.status == CheckResult.WARNING]
        if json_errors:
            print(f"\nJSON validation errors ({len(json_errors)}):")
            for r in json_errors:
                print(f"  {r}")
        if json_warnings:
            print(f"\nJSON validation warnings ({len(json_warnings)}):")
            for r in json_warnings:
                print(f"  {r}")

    # ── Ingest ──────────────────────────────────────────────
    if args.scrape_only:
        print("\nScrape-only mode — skipping ingestion.")
        print(f"JSON files saved to data/")
        return

    from ingest import init_db

    conn = init_db(Path("db/trackaroo.db"))
    try:
        stats = ingest_today(conn, dry_run=args.dry_run)

        if stats:
            mode = "(DRY RUN)" if args.dry_run else ""
            print(f"\n{'=' * 60}")
            print(f"Ingestion summary {mode}:")
            print(f"  Inserted: {stats['inserted']}")
            print(f"  Skipped:  {stats['skipped']}")
            print(f"  Errors:   {stats['errors']}")
            print(f"{'=' * 60}")
        else:
            print("\nNo new data to ingest.")

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    # ── Health check: validate DB state after ingestion ───
    if not args.no_health and not args.scrape_only:
        from health_checks import check_db_freshness, check_match_count_anomalies, CheckResult

        freshness_results = check_db_freshness(Path("db/trackaroo.db"))
        match_results = check_match_count_anomalies(Path("db/trackaroo.db"))
        db_results = freshness_results + match_results

        db_errors = [r for r in db_results if r.status == CheckResult.ERROR]
        db_warnings = [r for r in db_results if r.status == CheckResult.WARNING]

        if db_errors:
            print(f"\nDB validation errors ({len(db_errors)}):")
            for r in db_errors:
                print(f"  {r}")
        if db_warnings:
            print(f"\nDB validation warnings ({len(db_warnings)}):")
            for r in db_warnings:
                print(f"  {r}")

        ok_count = sum(1 for r in db_results if r.status == CheckResult.OK)
        if not db_errors and not db_warnings:
            print(f"\nDB health: all {ok_count} checks passed")


if __name__ == "__main__":
    main()
