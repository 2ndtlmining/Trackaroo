"""
Health checks for the Trackaroo price tracker.

Validates scraped JSON output and database state after each scrape/ingest cycle.
Implements the resilience requirement from SPEC.md §8:

    "each scrape run should validate its own output (e.g. 'did we get a plausible
    number of products for this category?') and log/alert if a retailer returns
    zero results or wildly different data than expected"

Usage:
    python health_checks.py              # Run all checks
    python health_checks.py --json-only  # Only validate JSON files
    python health_checks.py --db-only    # Only validate database state

Exit codes:
    0 — All checks passed (warnings are informational and do not fail the run)
    1 — One or more checks errored
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from config import (
    DATA_DIR,
    DB_DATE_FORMAT,
    DB_PATH,
    DEFAULT_MIN_PER_CATEGORY,
    DEFAULT_MIN_TOTAL,
    FILE_DATE_FORMAT,
    MATCH_THRESHOLDS,
    MIN_HISTORY_FOR_ANOMALY,
    PRICE_ANOMALY_STD_DEVS,
    SPEC_COVERAGE_MIN_PCT,
    SPEC_STALE_THRESHOLD_DAYS,
    STALE_THRESHOLD_DAYS,
)

LOGGER = logging.getLogger(__name__)


# ── Result types ─────────────────────────────────────────────────────

class CheckResult:
    """A single health check result."""
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"

    def __init__(self, check_name: str, status: str, message: str):
        self.check_name = check_name
        self.status = status
        self.message = message

    def __repr__(self):
        return f"[{self.status}] {self.check_name}: {self.message}"


# ── JSON file validation ────────────────────────────────────────────

def check_json_files(target_date: Optional[str] = None) -> list[CheckResult]:
    """Validate scraped JSON files for a given date.

    Checks:
    - File exists for each expected retailer/category combo
    - Match count is above the configured threshold
    - All products have valid prices (> 0)
    - No products have empty URLs
    - Stock status values are recognized

    Args:
        target_date: Date string in DD_Month_YYYY format. Defaults to today.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if target_date is None:
        target_date = date.today().strftime(FILE_DATE_FORMAT)

    expected_retailers = ["scorptec", "pccg"]
    expected_categories = ["cpu", "gpu"]

    for retailer in expected_retailers:
        for category in expected_categories:
            filename = f"{category}_{retailer}_{target_date}.json"
            file_path = DATA_DIR / filename

            if not file_path.exists():
                results.append(CheckResult(
                    f"json_exists_{retailer}_{category}",
                    CheckResult.WARNING,
                    f"Missing: {filename}",
                ))
                continue

            # Parse and validate
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                results.append(CheckResult(
                    f"json_parse_{retailer}_{category}",
                    CheckResult.ERROR,
                    f"Invalid JSON in {filename}: {e}",
                ))
                continue

            # Check match count
            matched = data.get("matched", 0)
            threshold = MATCH_THRESHOLDS.get(retailer, {}).get("min_per_category", DEFAULT_MIN_PER_CATEGORY)
            if matched < threshold:
                results.append(CheckResult(
                    f"json_match_count_{retailer}_{category}",
                    CheckResult.WARNING,
                    f"Low match count: {matched} (threshold: {threshold})",
                ))
            else:
                results.append(CheckResult(
                    f"json_match_count_{retailer}_{category}",
                    CheckResult.OK,
                    f"Match count OK: {matched}",
                ))

            # Validate individual products
            products = data.get("products", [])
            price_issues = 0
            url_issues = 0
            stock_issues = 0
            valid_stock_statuses = {"in_stock", "out_of_stock", "preorder", "unknown"}

            for i, prod in enumerate(products):
                # Price check
                price = prod.get("price_aud")
                if price is None or price <= 0:
                    price_issues += 1

                # URL check
                url = prod.get("url", "")
                if not url or not url.startswith("http"):
                    url_issues += 1

                # Stock status check
                stock = prod.get("stock_status", "unknown")
                if stock not in valid_stock_statuses:
                    stock_issues += 1

            if price_issues:
                results.append(CheckResult(
                    f"json_prices_{retailer}_{category}",
                    CheckResult.ERROR,
                    f"{price_issues} products with invalid prices",
                ))
            if url_issues:
                results.append(CheckResult(
                    f"json_urls_{retailer}_{category}",
                    CheckResult.WARNING,
                    f"{url_issues} products with missing/invalid URLs",
                ))
            if stock_issues:
                results.append(CheckResult(
                    f"json_stock_{retailer}_{category}",
                    CheckResult.WARNING,
                    f"{stock_issues} products with unrecognized stock status",
                ))

    return results


# ── Database freshness checks ───────────────────────────────────────

def check_db_freshness(db_path: Optional[Path] = None) -> list[CheckResult]:
    """Check that each retailer has recent snapshots.

    Flags retailers that haven't been updated within the stale threshold.

    Args:
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if db_path is None:
        db_path = DB_PATH

    if not db_path.exists():
        results.append(CheckResult(
            "db_exists",
            CheckResult.ERROR,
            f"Database not found: {db_path}",
        ))
        return results

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        results.append(CheckResult(
            "db_accessible",
            CheckResult.ERROR,
            f"Cannot open database: {e}",
        ))
        return results

    try:
        # Last snapshot date per retailer
        cursor = conn.execute("""
            SELECT rl.retailer,
                   MAX(ps.snapshot_date) as last_date,
                   COUNT(DISTINCT ps.snapshot_date) as date_count
            FROM price_snapshots ps
            JOIN retailer_listings rl ON ps.retailer_listing_id = rl.id
            GROUP BY rl.retailer
        """)
        retailer_data = cursor.fetchall()

        # Track which retailers have data
        retailers_with_data = {row["retailer"]: row for row in retailer_data}
        expected_retailers = {"scorptec", "pccg"}

        for retailer in expected_retailers:
            if retailer not in retailers_with_data:
                results.append(CheckResult(
                    f"freshness_{retailer}",
                    CheckResult.WARNING,
                    f"No snapshot data for {retailer}",
                ))
                continue

            row = retailers_with_data[retailer]
            last_date = datetime.strptime(row["last_date"], "%Y-%m-%d").date()
            days_since = (date.today() - last_date).days

            if days_since > STALE_THRESHOLD_DAYS:
                results.append(CheckResult(
                    f"freshness_{retailer}",
                    CheckResult.WARNING,
                    f"Stale data: last snapshot was {days_since} days ago ({row['last_date']})",
                ))
            else:
                results.append(CheckResult(
                    f"freshness_{retailer}",
                    CheckResult.OK,
                    f"Fresh: last snapshot {days_since} days ago ({row['last_date']}), "
                    f"{row['date_count']} total dates",
                ))

        # Total snapshot count
        total_snapshots = conn.execute(
            "SELECT COUNT(*) as c FROM price_snapshots"
        ).fetchone()["c"]
        results.append(CheckResult(
            "db_snapshot_count",
            CheckResult.OK,
            f"Total snapshots: {total_snapshots}",
        ))

    except sqlite3.Error as e:
        results.append(CheckResult(
            "db_query",
            CheckResult.ERROR,
            f"Database query error: {e}",
        ))
    finally:
        conn.close()

    return results


# ── Today coverage (per-retailer) ────────────────────────────────────

def check_today_coverage(db_path: Optional[Path] = None) -> list[CheckResult]:
    """Report, per retailer, whether today's date has a snapshot yet.

    Goal: make "Scorptec ingested, PCCG missing for today" a named,
    expected-shape warning instead of something only visible by reading scrape
    logs. Backed by the cooldown mechanism (IMPROVEMENT_16_Aug_V1.md §10.3/10.4):
    a recent PCCG circuit-breaker trip legitimately skips today's PCCG scrape,
    so this check surfaces the gap as a warning rather than an error.

    Args:
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if db_path is None:
        db_path = DB_PATH

    if not db_path.exists():
        return results  # Missing DB is reported by check_db_freshness

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return results  # DB issues handled by check_db_freshness

    try:
        today = date.today().strftime(DB_DATE_FORMAT)
        rows = conn.execute("""
            SELECT rl.retailer,
                   COUNT(DISTINCT rl.id) as today_variants
            FROM price_snapshots ps
            JOIN retailer_listings rl ON ps.retailer_listing_id = rl.id
            WHERE ps.snapshot_date = ?
            GROUP BY rl.retailer
        """, (today,)).fetchall()

        with_today = {row["retailer"]: row["today_variants"] for row in rows}
        for retailer in ("scorptec", "pccg"):
            if retailer in with_today:
                results.append(CheckResult(
                    f"today_coverage_{retailer}",
                    CheckResult.OK,
                    f"{retailer}: {with_today[retailer]} variants captured for today ({today})",
                ))
            else:
                results.append(CheckResult(
                    f"today_coverage_{retailer}",
                    CheckResult.WARNING,
                    f"{retailer}: no snapshot for today ({today}) yet",
                ))
    except sqlite3.Error:
        pass  # Handled by other checks
    finally:
        conn.close()

    return results


# ── Match count anomaly detection ───────────────────────────────────

def check_match_count_anomalies(db_path: Optional[Path] = None) -> list[CheckResult]:
    """Detect sudden drops in match counts per retailer.

    Compares the latest scrape's match count against the historical average.
    Flags if the latest count drops below the configured threshold.

    Args:
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if db_path is None:
        db_path = DB_PATH

    if not db_path.exists():
        results.append(CheckResult(
            "anomaly_db_exists",
            CheckResult.ERROR,
            f"Database not found: {db_path}",
        ))
        return results

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        results.append(CheckResult(
            "anomaly_db_accessible",
            CheckResult.ERROR,
            f"Cannot open database: {e}",
        ))
        return results

    try:
        # Get match counts per date per retailer.
        # We count distinct retailer_listings (variants), not distinct products:
        # a single watchlist product may map to multiple retailer listings
        # (e.g. GIGABYTE / ASUS / Zotac 5090), so counting products would
        # under-report and false-alarm against thresholds calibrated for
        # variant counts (e.g. Scorptec ~194 variants vs ~54 products).
        cursor = conn.execute("""
            SELECT rl.retailer,
                   ps.snapshot_date,
                   COUNT(DISTINCT rl.id) as variant_count
            FROM price_snapshots ps
            JOIN retailer_listings rl ON ps.retailer_listing_id = rl.id
            GROUP BY rl.retailer, ps.snapshot_date
            ORDER BY ps.snapshot_date DESC, rl.retailer
        """)
        date_data = cursor.fetchall()

        # Build per-retailer history
        retailer_history: dict[str, list[tuple[str, int]]] = {}
        for row in date_data:
            retailer = row["retailer"]
            if retailer not in retailer_history:
                retailer_history[retailer] = []
            retailer_history[retailer].append((row["snapshot_date"], row["variant_count"]))

        for retailer, history in retailer_history.items():
            if not history:
                continue

            latest_date, latest_count = history[0]
            threshold = MATCH_THRESHOLDS.get(retailer, {}).get("min_total", DEFAULT_MIN_TOTAL)

            if latest_count < threshold:
                avg_count = sum(c for _, c in history) / len(history)
                results.append(CheckResult(
                    f"match_anomaly_{retailer}",
                    CheckResult.WARNING,
                    f"Match count dropped: {latest_count} (avg: {avg_count:.0f}, "
                    f"threshold: {threshold})",
                ))
            else:
                results.append(CheckResult(
                    f"match_anomaly_{retailer}",
                    CheckResult.OK,
                    f"Match count stable: {latest_count} variants on {latest_date}",
                ))

    except sqlite3.Error as e:
        results.append(CheckResult(
            "match_anomaly_query",
            CheckResult.ERROR,
            f"Database query error: {e}",
        ))
    finally:
        conn.close()

    return results


# ── Price anomaly detection ─────────────────────────────────────────

def check_price_anomalies(db_path: Optional[Path] = None) -> list[CheckResult]:
    """Detect prices that deviate significantly from historical averages.

    For each product+retailer combo with sufficient history, flags prices
    outside N standard deviations from the mean.

    Args:
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if db_path is None:
        db_path = DB_PATH

    if not db_path.exists():
        return results  # Not an error — nothing to check

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return results  # DB issues handled by other checks

    try:
        # Get latest snapshot per listing with historical stats
        # Use a subquery to compute historical stats per listing, then join
        # to the latest snapshot
        cursor = conn.execute("""
            SELECT p.model, rl.retailer, latest.price_aud, latest.snapshot_date,
                   stats.hist_avg, stats.hist_count, stats.variance
            FROM (
                -- Latest snapshot per listing
                SELECT ps1.retailer_listing_id, ps1.price_aud, ps1.snapshot_date
                FROM price_snapshots ps1
                WHERE ps1.snapshot_date = (
                    SELECT MAX(ps2.snapshot_date)
                    FROM price_snapshots ps2
                    WHERE ps2.retailer_listing_id = ps1.retailer_listing_id
                )
            ) latest
            JOIN retailer_listings rl ON latest.retailer_listing_id = rl.id
            JOIN products p ON rl.product_id = p.id
            JOIN (
                -- Historical stats per listing
                SELECT retailer_listing_id,
                       AVG(price_aud) as hist_avg,
                       COUNT(price_aud) as hist_count,
                       (AVG(price_aud * price_aud) - AVG(price_aud) * AVG(price_aud)) as variance
                FROM price_snapshots
                GROUP BY retailer_listing_id
            ) stats ON latest.retailer_listing_id = stats.retailer_listing_id
        """)
        latest_prices = cursor.fetchall()

        anomalies_found = 0
        skipped_no_history = 0

        for row in latest_prices:
            hist_count = row["hist_count"]
            if hist_count < MIN_HISTORY_FOR_ANOMALY:
                skipped_no_history += 1
                continue

            variance = row["variance"] or 0
            std_dev = variance ** 0.5 if variance > 0 else 0

            if std_dev == 0:
                continue  # No variation — nothing to flag

            hist_avg = row["hist_avg"]
            current_price = row["price_aud"]
            deviation = abs(current_price - hist_avg) / std_dev

            if deviation > PRICE_ANOMALY_STD_DEVS:
                anomalies_found += 1
                results.append(CheckResult(
                    f"price_anomaly_{row['retailer']}",
                    CheckResult.WARNING,
                    f"{row['model']} @ {row['retailer']}: ${current_price:.0f} "
                    f"(avg: ${hist_avg:.0f}, {deviation:.1f} std devs)",
                ))

        if anomalies_found == 0:
            results.append(CheckResult(
                "price_anomalies",
                CheckResult.OK,
                f"No price anomalies detected ({skipped_no_history} skipped — insufficient history)",
            ))

    except sqlite3.Error:
        pass  # Handled by other checks
    finally:
        conn.close()

    return results


# ── Spec coverage / staleness ────────────────────────────────────────

def check_spec_coverage(db_path: Optional[Path] = None) -> list[CheckResult]:
    """Report whether tracked products have spec rows and the spec data is fresh.

    Specs are static-ish and refresh on a weekly, best-effort schedule via
    `sync_specs.py` (separate from the daily price pipeline). This check makes
    a silently missing or stale specs table visible:

    - WARNING when the `specs` table is absent (run `python migrate.py` once)
    - WARNING when tracked-product spec coverage drops below
      `SPEC_COVERAGE_MIN_PCT` (real watchlist: 95/100 = 95%; the 5 unmatched
      are known — Radeon RX 9070 XTX not in the GPU dataset, plus four OEM-only
      AMD SKUs with no amd.com page)
    - WARNING when the newest spec sync is older than `SPEC_STALE_THRESHOLD_DAYS`

    Args:
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        List of CheckResult objects.
    """
    results: list[CheckResult] = []

    if db_path is None:
        db_path = DB_PATH

    if not db_path.exists():
        return results  # Missing DB is reported by check_db_freshness

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return results  # DB issues handled by check_db_freshness

    try:
        has_specs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'specs'"
        ).fetchone()
        if not has_specs:
            results.append(CheckResult(
                "specs_table",
                CheckResult.WARNING,
                "specs table missing - run `python migrate.py` (product pages simply show no spec panel)",
            ))
            return results

        total = conn.execute(
            "SELECT COUNT(*) FROM products WHERE tracked = 1"
        ).fetchone()[0]
        with_specs = conn.execute("""
            SELECT COUNT(DISTINCT p.id) FROM products p
            JOIN specs s ON s.product_id = p.id
            WHERE p.tracked = 1
        """).fetchone()[0]

        if total > 0:
            pct = 100.0 * with_specs / total
            missing_rows = conn.execute("""
                SELECT p.model FROM products p
                LEFT JOIN specs s ON s.product_id = p.id
                WHERE p.tracked = 1 AND s.product_id IS NULL
                ORDER BY p.category, p.model
            """).fetchall()
            missing = ", ".join(r["model"] for r in missing_rows[:5])
            if len(missing_rows) > 5:
                missing += f" (+{len(missing_rows) - 5} more)"
            if pct < SPEC_COVERAGE_MIN_PCT:
                results.append(CheckResult(
                    "spec_coverage",
                    CheckResult.WARNING,
                    f"Low spec coverage: {with_specs}/{total} tracked products "
                    f"({pct:.0f}%) - missing: {missing}",
                ))
            else:
                results.append(CheckResult(
                    "spec_coverage",
                    CheckResult.OK,
                    f"Spec coverage OK: {with_specs}/{total} tracked products ({pct:.0f}%)",
                ))

        latest = conn.execute("SELECT MAX(last_synced_at) FROM specs").fetchone()[0]
        if latest is None:
            results.append(CheckResult(
                "spec_staleness",
                CheckResult.WARNING,
                "No spec sync recorded - run `python sync_specs.py`",
            ))
        else:
            last_date = datetime.fromisoformat(latest.replace("Z", "+00:00")).date()
            days_since = (date.today() - last_date).days
            if days_since > SPEC_STALE_THRESHOLD_DAYS:
                results.append(CheckResult(
                    "spec_staleness",
                    CheckResult.WARNING,
                    f"Stale specs: last sync {days_since} days ago ({latest})",
                ))
            else:
                results.append(CheckResult(
                    "spec_staleness",
                    CheckResult.OK,
                    f"Specs fresh: last sync {days_since} days ago ({latest})",
                ))
    except sqlite3.Error:
        pass  # Handled by other checks
    finally:
        conn.close()

    return results


# ── Aggregate runner ────────────────────────────────────────────────

def run_all_checks(
    target_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[CheckResult]:
    """Run all health checks and return combined results.

    Args:
        target_date: Date string for JSON checks. Defaults to today.
        db_path: Path to the SQLite database. Defaults to db/trackaroo.db.

    Returns:
        Combined list of CheckResult objects from all check groups.
    """
    all_results: list[CheckResult] = []

    LOGGER.info("\n%s\nTrackaroo Health Checks\n%s", "=" * 60, "=" * 60)

    # JSON file validation
    LOGGER.info("\n--- JSON File Validation (%s) ---", target_date or "today")
    json_results = check_json_files(target_date)
    all_results.extend(json_results)
    for r in json_results:
        LOGGER.info("  %s", r)

    # DB freshness
    LOGGER.info("\n--- Database Freshness ---")
    freshness_results = check_db_freshness(db_path)
    all_results.extend(freshness_results)
    for r in freshness_results:
        LOGGER.info("  %s", r)

    # Today coverage (per retailer)
    LOGGER.info("\n--- Today Coverage ---")
    coverage_results = check_today_coverage(db_path)
    all_results.extend(coverage_results)
    for r in coverage_results:
        LOGGER.info("  %s", r)

    # Match count anomalies
    LOGGER.info("\n--- Match Count Anomalies ---")
    match_results = check_match_count_anomalies(db_path)
    all_results.extend(match_results)
    for r in match_results:
        LOGGER.info("  %s", r)

    # Price anomalies
    LOGGER.info("\n--- Price Anomalies ---")
    price_results = check_price_anomalies(db_path)
    all_results.extend(price_results)
    for r in price_results:
        LOGGER.info("  %s", r)

    # Spec coverage / staleness
    LOGGER.info("\n--- Spec Coverage / Staleness ---")
    spec_results = check_spec_coverage(db_path)
    all_results.extend(spec_results)
    for r in spec_results:
        LOGGER.info("  %s", r)

    # Summary
    errors = sum(1 for r in all_results if r.status == CheckResult.ERROR)
    warnings = sum(1 for r in all_results if r.status == CheckResult.WARNING)
    ok = sum(1 for r in all_results if r.status == CheckResult.OK)

    LOGGER.info("\n%s\nSummary: %d OK, %d WARNING, %d ERROR\n%s",
                "=" * 60, ok, warnings, errors, "=" * 60)

    return all_results


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Trackaroo health checks")
    parser.add_argument("--json-only", action="store_true",
                        help="Only validate JSON files")
    parser.add_argument("--db-only", action="store_true",
                        help="Only validate database state")
    parser.add_argument("--date", type=str, default=None,
                        help="Date string for JSON checks (DD_Month_YYYY)")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="Path to SQLite database")
    args = parser.parse_args(argv)

    if args.json_only:
        results = check_json_files(args.date)
    elif args.db_only:
        results = (
            check_db_freshness(args.db_path) +
            check_today_coverage(args.db_path) +
            check_match_count_anomalies(args.db_path) +
            check_price_anomalies(args.db_path) +
            check_spec_coverage(args.db_path)
        )
    else:
        results = run_all_checks(args.date, args.db_path)

    for r in results:
        LOGGER.info("  %s", r)

    # Exit code based on results
    errors = sum(1 for r in results if r.status == CheckResult.ERROR)
    warnings = sum(1 for r in results if r.status == CheckResult.WARNING)

    if errors > 0:
        sys.exit(1)
    elif warnings > 0:
        # Warnings are informational — exit 0 so the pipeline continues
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
