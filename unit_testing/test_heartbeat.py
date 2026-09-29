"""The external heartbeat (#9): opt-in, best-effort, only after a complete day."""
import logging
import unittest.mock

import requests

import heartbeat
import run_daily
from scraper.snapshot_io import build_snapshot, save_snapshot


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

    def test_a_connection_error_never_logs_the_secret_token(self, monkeypatch, caplog):
        """fix-round-1 I1: the ping URL's path is a healthchecks.io-style secret."""
        token_url = "https://hc-ping.example/SENTINEL-TOKEN-ABC123"

        def boom(*a, **k):
            # requests/urllib3 embed the full URL in exception text -- this is
            # exactly the shape a real MaxRetryError message takes.
            raise requests.ConnectionError(
                f"HTTPSConnectionPool(host='hc-ping.example', port=443): "
                f"Max retries exceeded with url: {token_url}"
            )

        monkeypatch.setattr(heartbeat.requests, "get", boom)
        with caplog.at_level(logging.WARNING):
            assert heartbeat.ping(token_url) is False
        assert "SENTINEL-TOKEN-ABC123" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-TOKEN-ABC123" not in record.getMessage()

    def test_userinfo_in_the_url_never_reaches_the_log(self, monkeypatch, caplog):
        """final review M1: _safe_host used scheme://netloc, and netloc
        includes user:pass@ -- a heartbeat URL with basic-auth credentials
        embedded (or any URL carrying a userinfo component) leaked the
        password into the "safe" host-only log line."""
        token_url = "https://u:secret@host/uuid-token"

        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(heartbeat.requests, "get", boom)
        with caplog.at_level(logging.WARNING):
            assert heartbeat.ping(token_url) is False
        assert "secret" not in caplog.text
        assert "uuid-token" not in caplog.text
        for record in caplog.records:
            assert "secret" not in record.getMessage()
            assert "uuid-token" not in record.getMessage()

    def test_a_4xx_response_never_logs_the_secret_token(self, monkeypatch, caplog):
        """fix-round-1 I1: same guard for an HTTPError carrying a response."""
        token_url = "https://hc-ping.example/SENTINEL-TOKEN-XYZ789"
        resp = unittest.mock.Mock(status_code=404)
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"404 Client Error: Not Found for url: {token_url}", response=resp
        )
        monkeypatch.setattr(heartbeat.requests, "get", lambda *a, **k: resp)
        with caplog.at_level(logging.WARNING):
            assert heartbeat.ping(token_url) is False
        assert "SENTINEL-TOKEN-XYZ789" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-TOKEN-XYZ789" not in record.getMessage()
        # The status code is still useful and not secret -- keep reporting it.
        assert "404" in caplog.text


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _writing_scraper(data_dir, fail_first=frozenset()):
    """A fake scraper that writes a real one-product snapshot when it
    succeeds (final review I2b: pending_retailers now requires actual
    price_snapshots data, not just an 'ok' scrape_runs row, so a heartbeat
    test claiming "a complete clean day" must actually ingest something)."""
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


class TestRunDailyPings:
    def test_a_complete_clean_day_pings(self, isolated_pipeline, monkeypatch):
        scraper, _ = _writing_scraper(isolated_pipeline.data_dir)
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 1

    def test_a_run_with_a_missing_retailer_does_not_ping(self, isolated_pipeline, monkeypatch):
        """#9 acceptance."""
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 0

    def test_the_retry_that_completes_the_day_pings(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first={"umart"})
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        run_daily.run(_args("--pending-only"))
        assert isolated_pipeline.heartbeats == 1

    def test_a_dry_run_never_pings(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))
        run_daily.run(_args("--dry-run"))
        assert isolated_pipeline.heartbeats == 0
