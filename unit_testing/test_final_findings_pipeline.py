"""Regression tests for the final whole-branch review of Phase 3 (#I1, #I2, #M7, #T5).

.superpowers/sdd/2026-09-29-robustness/final-findings.md
"""
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import run_daily
from config import ACTIVE_RETAILERS
from pipeline_state import record_scrape_run, retailers_pending
from scraper.snapshot_io import build_snapshot, save_snapshot

TODAY = date.today().isoformat()


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _record(conn, retailer, status, run_date=TODAY):
    record_scrape_run(conn, retailer=retailer, run_date=run_date, started_at=f"{run_date}T04:00:00",
                      finished_at=f"{run_date}T04:05:00", status=status)
    conn.commit()


def _write_snapshot(data_dir, retailer, category="cpu"):
    stamp = run_daily.today_filename()
    product = {
        "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": category,
        "watchlist_brand": "AMD", "watchlist_gen_tier": "current", "retailer": retailer,
        "price_aud": 599.0, "stock_status": "in_stock",
        "url": f"https://www.{retailer}.example/product/{category}/1",
    }
    save_snapshot(data_dir / f"{category}_{retailer}_{stamp}.json",
                  build_snapshot(retailer, stamp, category, 1, [product], []))


class TestI1PartialDataFromAFailedScraperIsIngested:
    """A timeout/failed/auth scraper that already saved a category (matched >
    0 in its report) must still be ingested, not treated as "nothing to
    ingest"."""

    def test_single_retailer_timeout_with_partial_save_is_ingested(self, isolated_pipeline, monkeypatch):
        _write_snapshot(isolated_pipeline.data_dir, "scorptec")

        def scraper(name, module, label):
            return run_daily.ScrapeOutcome(label, "timeout", None, matched=1)

        monkeypatch.setattr(run_daily, "run_scraper", scraper)

        code = run_daily.run(_args("--scorptec"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert len(isolated_pipeline.alerts) == 1
        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        conn.close()
        assert n == 1

    def test_narrowed_retry_timeout_with_partial_save_is_ingested(self, isolated_pipeline, monkeypatch):
        """The 05:00 narrowed retry scenario from the finding: Scorptec alone
        saves CPU then times out."""
        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        _record(conn, "pccg", "ok")
        _record(conn, "umart", "ok")
        conn.close()
        _write_snapshot(isolated_pipeline.data_dir, "scorptec")

        def scraper(name, module, label):
            return run_daily.ScrapeOutcome(label, "timeout", None, matched=1)

        monkeypatch.setattr(run_daily, "run_scraper", scraper)

        code = run_daily.run(_args("--pending-only"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        conn.close()
        assert n == 1

    def test_a_full_run_where_everyone_times_out_after_partial_saves_is_ingested(
        self, isolated_pipeline, monkeypatch
    ):
        for retailer in ACTIVE_RETAILERS:
            _write_snapshot(isolated_pipeline.data_dir, retailer)

        def scraper(name, module, label):
            return run_daily.ScrapeOutcome(label, "timeout", None, matched=1)

        monkeypatch.setattr(run_daily, "run_scraper", scraper)

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        conn.close()
        assert n == len(ACTIVE_RETAILERS)

    def test_a_real_all_fail_with_no_data_still_takes_the_all_failed_path(self, isolated_pipeline, monkeypatch):
        """Nothing saved anywhere -- must still hit RUN_EXIT_ALL_FAILED, not
        silently "succeed" with zero ingested rows."""
        monkeypatch.setattr(run_daily, "run_scraper",
                            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed", 1))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_ALL_FAILED


class TestI2RetailerNotDoneUntilDataIsInTheDb:
    def test_scrape_only_does_not_record_a_done_row(self, isolated_pipeline, monkeypatch):
        """(a): --scrape-only must not write scrape_runs rows, or a later
        --scheduled run believes everything is already done."""
        monkeypatch.setattr(run_daily, "run_scraper",
                            lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))

        run_daily.run(_args("--scrape-only"))

        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        rows = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
        conn.close()
        assert rows == 0
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == list(ACTIVE_RETAILERS)

    def test_an_ok_row_with_no_snapshots_is_still_pending(self, db):
        """(b): a crash between record_scrape_run and the ingest commit leaves
        an 'ok' row with nothing in price_snapshots -- that retailer must
        still be retried."""
        _record(db, "scorptec", "ok")
        assert retailers_pending(db, TODAY, ["scorptec"]) == ["scorptec"]

    def test_an_ok_row_with_snapshots_is_not_pending(self, db):
        """The ordinary, healthy case must be unaffected."""
        db.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'X', 1)")
        db.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                   "VALUES (1, 'scorptec', 'https://x/1', 'active')")
        db.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                   "VALUES (1, ?, 100, 'in_stock')", (TODAY,))
        _record(db, "scorptec", "ok")
        assert retailers_pending(db, TODAY, ["scorptec"]) == []


class TestM7RunDateIsComputedOnceAtStart:
    def test_a_run_that_crosses_midnight_ingests_the_start_dates_files(
        self, isolated_pipeline, monkeypatch
    ):
        """Freeze the filename clock at start = D; midway through the run the
        clock ticks to D+1. ingest_today must still ingest D's files, not glob
        for D+1's (which don't exist)."""
        _write_snapshot(isolated_pipeline.data_dir, "scorptec")

        real_today = date.today

        class _FakeDate(date):
            _calls = {"n": 0}

            @classmethod
            def today(cls):
                cls._calls["n"] += 1
                # First call (inside run(), capturing the run date) sees D;
                # every later call (e.g. inside ingest_today if it re-derives
                # "today") sees D+1.
                if cls._calls["n"] == 1:
                    return real_today()
                from datetime import timedelta
                return real_today() + timedelta(days=1)

        monkeypatch.setattr(run_daily, "date", _FakeDate)
        monkeypatch.setattr(run_daily, "run_scraper",
                            lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))

        code = run_daily.run(_args("--scorptec"))

        assert code == run_daily.RUN_EXIT_OK
        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        conn.close()
        assert n == 1


class TestT5LeftoverReportTempFile:
    def test_the_json_tmp_sibling_is_cleaned_up(self, monkeypatch, tmp_path):
        """RunReport.flush() writes <path>.tmp then os.replace()s it onto
        <path>; if the scraper is killed mid-write the .tmp sibling survives.
        run_scraper's own cleanup must also unlink it."""
        import subprocess as subprocess_module

        from scraper.run_report import REPORT_ENV

        captured_report_path = {}

        def fake_run(cmd, capture_output, text, timeout, env):
            report_path = Path(env[REPORT_ENV])
            captured_report_path["path"] = report_path
            report_path.write_text('{"matched": 1}', encoding="utf-8")
            # Simulate a leftover .tmp sibling from a killed flush().
            report_path.with_name(report_path.name + ".tmp").write_text("{}", encoding="utf-8")

            class _Result:
                returncode = 0

            return _Result()

        monkeypatch.setattr(run_daily.subprocess, "run", fake_run)

        run_daily.run_scraper("Scorptec", "scraper.scorptec", "scorptec")

        report_path = captured_report_path["path"]
        assert not report_path.exists()
        assert not report_path.with_name(report_path.name + ".tmp").exists()
