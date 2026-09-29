"""Per-retailer hourly retry until a cutoff (#8)."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest
import requests

import run_daily
from config import ACTIVE_RETAILERS
from notify_discord import run as _real_notify_run
from notify_discord import send_alert as _real_send_alert
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


class _OkResponse:
    """A fake `requests.Response` for a successful (204) webhook POST."""
    status_code = 204

    def raise_for_status(self):
        return None


class _ErrorResponse:
    """A fake `requests.Response` for a failed (500) webhook POST -- this is
    what a real Discord outage looks like: `requests.post` returns normally,
    and `raise_for_status()` is what turns it into an exception (fix-round-1
    I1: production never raises out of `notify_discord.send_alert`/`run`
    directly -- it raises out of `raise_for_status()`, which `send_embed`
    already catches and used to just log, without reporting the failure to
    its caller).
    """
    status_code = 500

    def raise_for_status(self):
        raise requests.HTTPError("500 Server Error")


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


class TestRetryOfOneRetailerFailure:
    """Fix-round-1 I2: a --pending-only/--scheduled retry that only reattempts
    a single already-pending retailer (the others already have a complete run
    today) must not be reported as "all scrapers failed" when that one
    retailer fails again -- the other retailers' data from earlier today is
    not "no new data this run".
    """

    def test_a_narrowed_retry_that_fails_again_is_degraded_not_all_failed(self, isolated_pipeline, monkeypatch):
        def flaky_scraper(name, module, label):
            if label == "pccg":
                return run_daily.ScrapeOutcome(label, "failed", 1)
            stamp = run_daily.today_filename()
            product = {
                "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": "cpu",
                "watchlist_brand": "AMD", "watchlist_gen_tier": "current", "retailer": label,
                "price_aud": 599.0, "stock_status": "in_stock",
                "url": f"https://www.{label}.example/product/cpu/1",
            }
            save_snapshot(isolated_pipeline.data_dir / f"cpu_{label}_{stamp}.json",
                          build_snapshot(label, stamp, "cpu", 1, [product], []))
            return run_daily.ScrapeOutcome(label, "ok", 0)

        monkeypatch.setattr(run_daily, "run_scraper", flaky_scraper)

        # 04:00 - scorptec/umart ok, pccg fails. Not all-failed (two of three
        # succeeded), so this hits the ordinary degraded path.
        code = run_daily.run(_args())
        assert code == run_daily.RUN_EXIT_DEGRADED
        alerts_before = len(isolated_pipeline.alerts)
        assert alerts_before == 1

        # 05:00 retry - only PCCG is pending (the other two already have
        # today's data), and it fails again. Before the fix this hit
        # results == {"pccg": failed}, "not any ok/degraded" == True, and
        # posted "All scrapers failed - no new data this run" / exited
        # RUN_EXIT_ALL_FAILED, even though scorptec/umart were fine.
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == ["pccg"]
        code = run_daily.run(_args("--pending-only"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert code != run_daily.RUN_EXIT_ALL_FAILED
        assert len(isolated_pipeline.alerts) == alerts_before + 1
        latest = "\n".join(isolated_pipeline.alerts[-1])
        assert "retry" in latest.lower()
        assert "PCCG" in latest
        assert "all scrapers failed" not in latest.lower()


class TestClaimReleasedOnSendFailure:
    """F2 controller ruling: claim_once must not mark digest/alert as sent before
    the send succeeds. A failed Discord post (e.g. at 04:00) must be retried by
    the next hourly run; a successful one must not be repeated.

    Fix-round-1 I1: exercised through the real `requests.post` boundary (a
    raised `RequestException`, and a non-raising 500), not by monkeypatching
    `notify_discord.send_alert`/`run` themselves with a function that raises --
    production's real `send_alert`/`send_embed` never raise; they catch
    `requests.RequestException` internally and (before this fix) always
    reported success regardless, which is exactly why the claim was never
    released on a real webhook outage.
    """

    def test_a_raising_post_releases_the_alert_claim_and_the_retry_resends(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        monkeypatch.setattr("notify_discord.send_alert", _real_send_alert)
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        posts = {"n": 0}

        def flaky_post(url, json=None, timeout=None):
            posts["n"] += 1
            if posts["n"] == 1:
                raise requests.RequestException("boom")
            return _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", flaky_post)

        run_daily.run(_args())  # 04:00 - POST raises -> claim released
        assert posts["n"] == 1

        run_daily.run(_args())  # 05:00 retry - POST succeeds -> claim kept
        assert posts["n"] == 2

        run_daily.run(_args())  # 06:00 - already sent, not repeated
        assert posts["n"] == 2

    def test_a_500_response_releases_the_alert_claim_and_a_204_keeps_it(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        monkeypatch.setattr("notify_discord.send_alert", _real_send_alert)
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        posts = {"n": 0}

        def flaky_post(url, json=None, timeout=None):
            posts["n"] += 1
            return _ErrorResponse() if posts["n"] == 1 else _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", flaky_post)

        run_daily.run(_args())  # 04:00 - 500 -> claim released
        assert posts["n"] == 1

        run_daily.run(_args())  # 05:00 retry - 204 -> claim kept
        assert posts["n"] == 2

        run_daily.run(_args())  # 06:00 - already sent, not repeated
        assert posts["n"] == 2

    def test_a_204_response_keeps_the_alert_claim_from_the_start(self, isolated_pipeline, monkeypatch):
        """The plain success case, isolated from the retry scenarios above."""
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        monkeypatch.setattr("notify_discord.send_alert", _real_send_alert)
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        posts = {"n": 0}

        def ok_post(url, json=None, timeout=None):
            posts["n"] += 1
            return _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", ok_post)

        run_daily.run(_args())
        run_daily.run(_args())
        assert posts["n"] == 1

    def test_a_500_response_releases_the_digest_claim_and_a_204_keeps_it(self, isolated_pipeline, monkeypatch):
        scraper, _ = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        monkeypatch.setattr("notify_discord.run", _real_notify_run)
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setattr("notify_discord.DB_PATH", isolated_pipeline.db_path)
        monkeypatch.setattr("notify_discord.query_digest_rows", lambda conn: [{
            "product_id": 1, "category": "cpu", "brand": "AMD", "model": "Ryzen 7 9800X3D",
            "retailer": "scorptec", "listing_url": "https://x.com/1",
            "today_price": 599.0, "today_date": TODAY, "prev_price": 549.0, "prev_date": "2000-01-01",
        }])
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/digest")
        posts = {"n": 0}

        def flaky_post(url, json=None, timeout=None):
            posts["n"] += 1
            return _ErrorResponse() if posts["n"] == 1 else _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", flaky_post)

        run_daily.run(_args())  # 04:00 - 500 -> claim released
        assert posts["n"] == 1

        run_daily.run(_args())  # 05:00 retry - 204 -> claim kept
        assert posts["n"] == 2

        run_daily.run(_args())  # 06:00 - already sent, not repeated
        assert posts["n"] == 2


def test_entrypoints_delegate_the_schedule_to_run_daily():
    for name in ("entrypoint-single.sh", "entrypoint.sh"):
        text = (REPO / "deploy" / name).read_text(encoding="utf-8")
        assert "todays_run_done" not in text, name
        assert "run_pipeline --pending-only" in text, name
        assert "run_pipeline --scheduled" in text, name
        assert "export RUN_AT_HOUR RETRY_UNTIL_HOUR" in text, name
