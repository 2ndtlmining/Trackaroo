"""Per-retailer hourly retry until a cutoff (#8)."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import run_daily
from config import ACTIVE_RETAILERS
from pipeline_state import claim_marker, record_scrape_run, retailers_pending
from scraper.snapshot_io import build_snapshot, save_snapshot

TODAY = date.today().isoformat()
REPO = Path(__file__).resolve().parent.parent


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _record(conn, retailer, status, run_date=TODAY):
    record_scrape_run(conn, retailer=retailer, run_date=run_date, started_at=f"{run_date}T04:00:00",
                      finished_at=f"{run_date}T04:05:00", status=status)
    conn.commit()


class TestRetailersPending:
    def test_no_run_and_no_data_is_pending(self, db):
        assert retailers_pending(db, TODAY, ["scorptec", "pccg"]) == ["scorptec", "pccg"]

    @pytest.mark.parametrize("status", ["degraded", "skipped", "auth", "failed", "timeout"])
    def test_a_latest_run_that_is_not_ok_is_pending(self, db, status):
        _record(db, "pccg", status)
        assert retailers_pending(db, TODAY, ["pccg"]) == ["pccg"]

    def test_only_the_latest_run_counts(self, db):
        _record(db, "pccg", "failed")
        _record(db, "pccg", "ok")
        assert retailers_pending(db, TODAY, ["pccg"]) == []

    def test_yesterdays_ok_does_not_count_today(self, db):
        _record(db, "pccg", "ok", run_date="2000-01-01")
        assert retailers_pending(db, TODAY, ["pccg"]) == ["pccg"]

    def test_pre_upgrade_day_with_snapshots_is_not_pending(self, db):
        """Review Focus 3: the deploy day must not re-scrape what the old build already got."""
        db.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'X', 1)")
        db.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                   "VALUES (1, 'scorptec', 'https://x/1', 'active')")
        db.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                   "VALUES (1, ?, 100, 'in_stock')", (TODAY,))
        assert retailers_pending(db, TODAY, ["scorptec", "pccg"]) == ["pccg"]

    @pytest.mark.parametrize("status", run_daily.SCRAPE_STATUSES)
    def test_every_outcome_status_is_accepted_by_the_table(self, db, status):
        """F4: read the row back and assert it, not just that the insert didn't raise."""
        _record(db, "umart", status)
        row = db.execute(
            "SELECT status FROM scrape_runs WHERE retailer = 'umart' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == status


class TestClaimMarker:
    def test_first_claim_wins_per_day(self, db):
        assert claim_marker(db, "digest", TODAY) is True
        assert claim_marker(db, "digest", TODAY) is False
        assert claim_marker(db, "digest", "2000-01-01") is True


class TestRetryWindow:
    @pytest.mark.parametrize("hour,expected", [(3, False), (4, True), (7, True), (9, True), (10, False)])
    def test_window(self, hour, expected):
        assert run_daily.in_retry_window(hour, 4, 9) is expected

    def test_a_cutoff_before_the_run_hour_still_runs_once(self):
        assert run_daily.in_retry_window(4, 4, 2) is True
        assert run_daily.in_retry_window(5, 4, 2) is False


def _writing_scraper(data_dir, fail_first):
    """A fake scraper that writes a real one-product snapshot when it succeeds."""
    attempts = []

    def scraper(name, module, label):
        attempts.append(label)
        if label in fail_first and attempts.count(label) == 1:
            return run_daily.ScrapeOutcome(label, "failed", 1)
        stamp = run_daily.today_filename()
        product = {
            "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": "cpu",
            "watchlist_brand": "AMD", "watchlist_gen_tier": "current", "retailer": label,
            "price_aud": 599.0, "stock_status": "in_stock",
            "url": f"https://www.{label}.example/product/cpu/{len(attempts)}",
        }
        save_snapshot(data_dir / f"cpu_{label}_{stamp}.json",
                      build_snapshot(label, stamp, "cpu", 1, [product], []))
        return run_daily.ScrapeOutcome(label, "ok", 0)

    return scraper, attempts


class TestRetryEndToEnd:
    def test_pccg_fails_at_4_and_succeeds_at_5(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first={"pccg"})
        monkeypatch.setattr(run_daily, "run_scraper", scraper)

        run_daily.run(_args())                               # 04:00
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == ["pccg"]

        run_daily.run(_args("--pending-only"))               # 05:00
        assert attempts == ["scorptec", "pccg", "umart", "pccg"]
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == []

        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        pccg_rows = conn.execute(
            "SELECT COUNT(*) FROM price_snapshots ps JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id "
            "WHERE rl.retailer = 'pccg' AND ps.snapshot_date = ?", (TODAY,)).fetchone()[0]
        conn.close()
        assert pccg_rows == 1

    def test_nothing_pending_means_no_scrape(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        attempts.clear()

        assert run_daily.run(_args("--pending-only")) == run_daily.RUN_EXIT_OK
        assert attempts == []

    def test_scheduled_does_nothing_after_the_cutoff(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        monkeypatch.setattr(run_daily, "_current_hour", lambda: run_daily.RETRY_UNTIL_HOUR + 1)

        assert run_daily.run(_args("--scheduled")) == run_daily.RUN_EXIT_OK
        assert attempts == []

    def test_scheduled_retries_inside_the_window(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        monkeypatch.setattr(run_daily, "_current_hour", lambda: run_daily.RUN_AT_HOUR)

        run_daily.run(_args("--scheduled"))
        assert attempts == list(ACTIVE_RETAILERS)


class TestOncePerDay:
    """Review Focus 2: hourly retries must not repeat the digest or an identical alert."""

    def test_the_digest_is_sent_once_a_day(self, isolated_pipeline, monkeypatch):
        scraper, _ = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        run_daily.run(_args())
        assert isolated_pipeline.digests == 1

    def test_an_identical_alert_is_sent_once_a_day(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        run_daily.run(_args())
        # --pccg too, so the retry is not the all-failed path (a different alert).
        run_daily.run(_args("--pccg", "--umart"))
        assert len(isolated_pipeline.alerts) == 1


class TestClaimReleasedOnSendFailure:
    """F2 controller ruling: claim_once must not mark digest/alert as sent before
    the send succeeds. A failed Discord post (e.g. at 04:00) must be retried by
    the next hourly run; a successful one must not be repeated.
    """

    def test_a_failed_alert_send_is_retried_next_run_but_a_success_is_not(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        attempts = {"n": 0}

        def flaky_send(lines, dry_run=False):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("webhook down")
            return 1

        monkeypatch.setattr("notify_discord.send_alert", flaky_send)

        run_daily.run(_args())  # 04:00 - send raises, must not be claimed
        assert attempts["n"] == 1

        run_daily.run(_args())  # 05:00 retry - same alert, send succeeds this time
        assert attempts["n"] == 2

        run_daily.run(_args())  # 06:00 - already sent successfully, not repeated
        assert attempts["n"] == 2

    def test_a_failed_digest_send_is_retried_next_run_but_a_success_is_not(self, isolated_pipeline, monkeypatch):
        scraper, _ = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        attempts = {"n": 0}

        def flaky_digest(*a, **k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("discord down")

        monkeypatch.setattr("notify_discord.run", flaky_digest)

        run_daily.run(_args())  # digest send raises
        assert attempts["n"] == 1

        run_daily.run(_args())  # retried, succeeds
        assert attempts["n"] == 2

        run_daily.run(_args())  # already sent, not repeated
        assert attempts["n"] == 2


def test_entrypoints_delegate_the_schedule_to_run_daily():
    for name in ("entrypoint-single.sh", "entrypoint.sh"):
        text = (REPO / "deploy" / name).read_text(encoding="utf-8")
        assert "todays_run_done" not in text, name
        assert "run_pipeline --pending-only" in text, name
        assert "run_pipeline --scheduled" in text, name
        assert "export RUN_AT_HOUR RETRY_UNTIL_HOUR" in text, name
