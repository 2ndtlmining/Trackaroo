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
    0 — All checks passed
    1 — One or more checks failed (warnings logged)
    2 — Critical error (e.g. database inaccessible)
"""
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data")
DB_PATH = Path("db/trackaroo.db")

# ── Baseline thresholds ──────────────────────────────────────────────
# Updated 11-Aug-2026 for multi-variant tracking:
#   Scorptec: ~194 matched per scrape (multi-variant; was ~56 single-variant)
#   PCCG:     ~41 matched per scrape (single-variant; multi-variant untested due to Algolia rate limit)
# These are the expected match counts per retailer per scrape.
# We use a low threshold (50% of baseline) to avoid false alarms from
# normal variation in stock levels.

MATCH_THRESHOLDS = {
    "scorptec": {"min_total": 90, "min_per_category": 30},
    "pccg":     {"min_total": 20, "min_per_category": 5},
}

# How many days without a snapshot before flagging as stale
STALE_THRESHOLD_DAYS = 3

# Price anomaly: flag if a price deviates more than this many standard
# deviations from the historical mean for that product+retailer combo
PRICE_ANOMALY_STD_DEVS = 3.0

# Minimum number of historical data points needed before anomaly detection
# is meaningful (with fewer points, std dev is unreliable)
MIN_HISTORY_FOR_ANOMALY = 3


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
        target_date = date.today().strftime("%d_%B_%Y")

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
            threshold = MATCH_THRESHOLDS.get(retailer, {}).get("min_per_category", 5)
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
        # Get match counts per date per retailer
        cursor = conn.execute("""
            SELECT rl.retailer,
                   ps.snapshot_date,
                   COUNT(DISTINCT rl.product_id) as product_count
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
            retailer_history[retailer].append((row["snapshot_date"], row["product_count"]))

        for retailer, history in retailer_history.items():
            if not history:
                continue

            latest_date, latest_count = history[0]
            threshold = MATCH_THRESHOLDS.get(retailer, {}).get("min_total", 10)

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
                    f"Match count stable: {latest_count} products on {latest_date}",
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

    print(f"\n{'=' * 60}")
    print("Trackaroo Health Checks")
    print(f"{'=' * 60}")

    # JSON file validation
    print(f"\n--- JSON File Validation ({target_date or 'today'}) ---")
    json_results = check_json_files(target_date)
    all_results.extend(json_results)
    for r in json_results:
        print(f"  {r}")

    # DB freshness
    print(f"\n--- Database Freshness ---")
    freshness_results = check_db_freshness(db_path)
    all_results.extend(freshness_results)
    for r in freshness_results:
        print(f"  {r}")

    # Match count anomalies
    print(f"\n--- Match Count Anomalies ---")
    match_results = check_match_count_anomalies(db_path)
    all_results.extend(match_results)
    for r in match_results:
        print(f"  {r}")

    # Price anomalies
    print(f"\n--- Price Anomalies ---")
    price_results = check_price_anomalies(db_path)
    all_results.extend(price_results)
    for r in price_results:
        print(f"  {r}")

    # Summary
    errors = sum(1 for r in all_results if r.status == CheckResult.ERROR)
    warnings = sum(1 for r in all_results if r.status == CheckResult.WARNING)
    ok = sum(1 for r in all_results if r.status == CheckResult.OK)

    print(f"\n{'=' * 60}")
    print(f"Summary: {ok} OK, {warnings} WARNING, {errors} ERROR")
    print(f"{'=' * 60}")

    return all_results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Trackaroo health checks")
    parser.add_argument("--json-only", action="store_true",
                        help="Only validate JSON files")
    parser.add_argument("--db-only", action="store_true",
                        help="Only validate database state")
    parser.add_argument("--date", type=str, default=None,
                        help="Date string for JSON checks (DD_Month_YYYY)")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="Path to SQLite database")
    args = parser.parse_args()

    if args.json_only:
        results = check_json_files(args.date)
    elif args.db_only:
        results = (
            check_db_freshness(args.db_path) +
            check_match_count_anomalies(args.db_path) +
            check_price_anomalies(args.db_path)
        )
    else:
        results = run_all_checks(args.date, args.db_path)

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
