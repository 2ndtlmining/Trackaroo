"""The external heartbeat (#9): opt-in, best-effort, only after a complete day."""
import unittest.mock

import requests

import heartbeat
import run_daily


class TestPing:
    def test_unset_is_a_no_op(self, monkeypatch):
        monkeypatch.delenv(heartbeat.HEARTBEAT_ENV, raising=False)
        called = []
        monkeypatch.setattr(heartbeat.requests, "get", lambda *a, **k: called.append(a))
        assert heartbeat.ping() is False
        assert called == []

    def test_a_configured_url_is_pinged(self, monkeypatch):
        resp = unittest.mock.Mock(status_code=200)
        get = unittest.mock.Mock(return_value=resp)
        monkeypatch.setattr(heartbeat.requests, "get", get)
        assert heartbeat.ping("https://hc-ping.example/uuid") is True
        get.assert_called_once()
        assert get.call_args.args[0] == "https://hc-ping.example/uuid"

    def test_a_failing_endpoint_never_raises(self, monkeypatch):
        def boom(*a, **k):
            raise requests.ConnectionError("down")
        monkeypatch.setattr(heartbeat.requests, "get", boom)
        assert heartbeat.ping("https://hc-ping.example/uuid") is False


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


class TestRunDailyPings:
    def test_a_complete_clean_day_pings(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 1

    def test_a_run_with_a_missing_retailer_does_not_ping(self, isolated_pipeline, monkeypatch):
        """#9 acceptance."""
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 0

    def test_the_retry_that_completes_the_day_pings(self, isolated_pipeline, monkeypatch):
        attempts = []

        def scraper(n, m, label):
            attempts.append(label)
            failed = label == "umart" and attempts.count("umart") == 1
            return run_daily.ScrapeOutcome(label, "failed" if failed else "ok", 1 if failed else 0)

        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        run_daily.run(_args("--pending-only"))
        assert isolated_pipeline.heartbeats == 1

    def test_a_dry_run_never_pings(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))
        run_daily.run(_args("--dry-run"))
        assert isolated_pipeline.heartbeats == 0
