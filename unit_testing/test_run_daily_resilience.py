"""run_daily must finish its best-effort steps whatever one of them does (#12, R4)."""
import json
import sqlite3

import pytest

import run_daily
from health_checks import CheckResult
from ingest import ingest_file


def _outcome(status):
    code = {"ok": 0, "skipped": 3}.get(status, 1)
    return lambda name, module, label: run_daily.ScrapeOutcome(label, status, code)


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _today_file(data_dir, retailer, category, body):
    path = data_dir / f"{category}_{retailer}_{run_daily.today_filename()}.json"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = {
    "retailer": "scorptec", "category": "cpu", "matched": 1,
    "products": [{
        "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": "cpu",
        "watchlist_brand": "AMD", "watchlist_gen_tier": "current",
        "retailer": "scorptec", "price_aud": 599.0, "stock_status": "in_stock",
        "url": "https://www.scorptec.com.au/product/cpu/amd-socket-am5/111111",
    }],
}


def _boom(*a, **k):
    raise sqlite3.OperationalError("no such table: products")


class TestBestEffortSteps:
    def test_digest_crash_still_runs_price_alerts_and_backup(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("notify_discord.run", _boom)
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.price_alert_runs == 1
        assert isolated_pipeline.backups == 1

    def test_alert_delivery_crash_still_backs_up(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("notify_discord.send_alert", _boom)
        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed" if label == "umart" else "ok", 1),
        )

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert isolated_pipeline.backups == 1

    def test_backup_crash_does_not_raise(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("backup_db.backup_database", _boom)
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        assert run_daily.run(_args()) == run_daily.RUN_EXIT_OK

    def test_a_crashing_health_check_is_reported_as_an_error(self, monkeypatch):
        def crashes():
            raise ValueError("bad date")

        monkeypatch.setattr(run_daily, "_db_checks", lambda: [
            ("check_fine", lambda: [CheckResult("fine", CheckResult.OK, "ok")]),
            ("check_price_anomalies", crashes),
        ])

        results = run_daily.run_db_checks()

        assert [(r.check_name, r.status) for r in results] == [
            ("fine", CheckResult.OK),
            ("check_price_anomalies_crashed", CheckResult.ERROR),
        ]
        assert "ValueError: bad date" in results[1].message


class TestAllScrapersFailed:
    def test_sends_an_alert_before_exiting_non_zero(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("failed"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_ALL_FAILED
        assert len(isolated_pipeline.alerts) == 1
        text = "\n".join(isolated_pipeline.alerts[0])
        assert "All scrapers failed" in text
        for label in ("Scorptec", "PCCG", "Umart"):
            assert label in text
        assert isolated_pipeline.backups == 0  # nothing new was written

    def test_main_exits_1(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("failed"))
        with pytest.raises(SystemExit) as exc:
            run_daily.main([])
        assert exc.value.code == 1

    def test_a_cooldown_skip_alone_is_not_a_failure(self, isolated_pipeline, monkeypatch):
        """Review Focus 1: a --pccg retry skipped by the cooldown must not page."""
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("skipped"))

        assert run_daily.run(_args("--pccg")) == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.alerts == []

    def test_a_crash_inside_the_run_still_alerts(self, isolated_pipeline, monkeypatch):
        def crash(args):
            raise RuntimeError("disk full")

        monkeypatch.setattr(run_daily, "run", crash)
        with pytest.raises(SystemExit) as exc:
            run_daily.main([])
        assert exc.value.code == 1
        assert "crashed" in "\n".join(isolated_pipeline.alerts[0])


class TestBadJsonFile:
    def test_ingest_file_reports_instead_of_raising(self, db, tmp_path):
        path = tmp_path / f"gpu_pccg_{run_daily.today_filename()}.json"
        path.write_text("{not json", encoding="utf-8")

        stats = ingest_file(db, path)

        assert stats["unreadable"] == 1
        assert stats["errors"] == 1

    def test_a_non_object_file_is_unreadable_too(self, db, tmp_path):
        path = tmp_path / f"gpu_pccg_{run_daily.today_filename()}.json"
        path.write_text("[]", encoding="utf-8")

        assert ingest_file(db, path)["unreadable"] == 1

    def test_one_corrupt_file_does_not_stop_the_others(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
        bad = _today_file(tmp_path, "pccg", "cpu", "{not json")  # sorts first
        _today_file(tmp_path, "scorptec", "cpu", json.dumps(GOOD))

        stats = run_daily.ingest_today(db)

        assert stats["inserted"] == 1
        assert stats["bad_files"] == [bad.name]

    def test_the_run_reports_it_as_an_error_and_alerts(self, isolated_pipeline, monkeypatch):
        _today_file(isolated_pipeline.data_dir, "pccg", "cpu", "{not json")
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert any("unreadable" in line for line in isolated_pipeline.alerts[0])
        assert isolated_pipeline.digests == 0
        assert isolated_pipeline.backups == 1


class TestAlertsIndependentOfNotify:
    """Controller ruling F1: the pipeline alert lives under ``alerts_enabled``,
    not ``notify_enabled`` -- a --no-health or --scrape-only run must still
    page on a scraper failure even though its digest/price-alerts stay off.
    """

    def test_no_health_run_still_sends_a_scraper_failure_alert(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed" if label == "umart" else "ok", 1),
        )

        code = run_daily.run(_args("--no-health"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert len(isolated_pipeline.alerts) == 1
        assert "Umart" in "\n".join(isolated_pipeline.alerts[0])
        # notify_enabled is False under --no-health, so neither of these ran.
        assert isolated_pipeline.digests == 0
        assert isolated_pipeline.price_alert_runs == 0

    def test_scrape_only_run_still_sends_a_scraper_failure_alert(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed" if label == "umart" else "ok", 1),
        )

        code = run_daily.run(_args("--scrape-only"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert len(isolated_pipeline.alerts) == 1
        assert "Umart" in "\n".join(isolated_pipeline.alerts[0])
        assert isolated_pipeline.backups == 0  # scrape-only never ingests or backs up

    def test_no_notify_run_stays_silent(self, isolated_pipeline, monkeypatch):
        """--no-notify is the one flag that also turns the pipeline alert off."""
        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed" if label == "umart" else "ok", 1),
        )

        code = run_daily.run(_args("--no-notify"))

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert isolated_pipeline.alerts == []
