"""A scrape that matched nothing is a failure that alerts; a cooldown skip is not (#7)."""
import pytest

import run_daily
from scraper import pccg, scorptec, umart
from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED

WATCHLIST = [
    {"model": "Ryzen 7 9800X3D", "category": "cpu", "brand": "AMD", "gen_tier": "current",
     "vram_gb": None, "search_terms": ["ryzen 7 9800x3d"]},
    {"model": "GeForce RTX 5070", "category": "gpu", "brand": "NVIDIA", "gen_tier": "current",
     "vram_gb": 12, "search_terms": ["rtx 5070"]},
]


def _match(retailer, model, category):
    return {
        "watchlist_model": model, "watchlist_category": category,
        "watchlist_brand": "X", "watchlist_gen_tier": "current", "retailer": retailer,
        "scraped_name": model.lower(), "price_aud": 500.0, "stock_status": "in_stock",
        "url": f"https://example.com/{retailer}/{category}/1", "retailer_sku": "1",
    }


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


@pytest.mark.parametrize("code,status", [
    (EXIT_OK, "ok"), (EXIT_DEGRADED, "degraded"), (EXIT_SKIPPED, "skipped"),
    (EXIT_AUTH, "auth"), (1, "failed"), (-9, "failed"),
])
def test_status_for_exit(code, status):
    assert run_daily.status_for_exit(code) == status


class TestRunDailyReaction:
    def test_an_empty_scorptec_alerts_and_blocks_the_digest(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "degraded" if label == "scorptec" else "ok", 2 if label == "scorptec" else 0))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert any("Scorptec" in line and "incomplete" in line for line in isolated_pipeline.alerts[0])
        assert isolated_pipeline.digests == 0

    def test_an_empty_scorptec_skips_the_delisted_check(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "degraded" if label == "scorptec" else "ok", 2 if label == "scorptec" else 0))

        run_daily.run(_args())

        assert isolated_pipeline.delisted_runs == 0

    def test_a_cooldown_skip_warns_but_does_not_alert(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "skipped" if label == "pccg" else "ok", 3 if label == "pccg" else 0))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.alerts == []
        assert isolated_pipeline.digests == 1

    def test_all_scrapers_degraded_still_ingests_and_alerts(self, isolated_pipeline, monkeypatch):
        """I2: a degraded scraper wrote real partial data -- an all-degraded run
        is not "nothing to ingest" and must not take the all-failed early exit."""
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "degraded", 2))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        # Reaching the post-ingest `finally` (where the backup runs) proves the
        # all-failed early return was not taken.
        assert isolated_pipeline.backups == 1
        assert isolated_pipeline.alerts != []


class TestScraperExitCodes:
    def test_scorptec_with_an_empty_gpu_category_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_scorptec", lambda wl, only_category=None, **k: (
            [_match("scorptec", "Ryzen 7 9800X3D", "cpu")], {0}, {}) if only_category == "cpu" else ([], set(), {}))

        assert scorptec.main() == EXIT_DEGRADED

    def test_scorptec_with_both_categories_is_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_scorptec", lambda wl, only_category=None, **k: (
            [_match("scorptec", "Ryzen 7 9800X3D", "cpu")], {0}, {}) if only_category == "cpu" else (
            [_match("scorptec", "GeForce RTX 5070", "gpu")], {1}, {}))

        assert scorptec.main() == EXIT_OK

    def test_umart_that_matched_nothing_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(umart, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
        monkeypatch.setattr(umart, "scrape_umart", lambda wl, **k: ([], set(), {}))

        assert umart.main() == EXIT_DEGRADED

    def test_pccg_in_cooldown_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pccg, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(pccg, "_cooldown_active", lambda: True)

        assert pccg.main() == EXIT_SKIPPED

    def test_pccg_breaker_trip_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pccg, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(pccg, "DATA_DIR", tmp_path)
        monkeypatch.setattr(pccg, "_cooldown_active", lambda: False)
        monkeypatch.setattr(pccg, "CATEGORY_PASS_DELAY", 0)
        monkeypatch.setattr(pccg, "scrape_category", lambda category, wl, **k: ([], set(), True))

        assert pccg.main() == EXIT_DEGRADED


class TestRunScraperLogging:
    def test_a_cooldown_skip_logs_at_warning_not_error(self, monkeypatch, caplog):
        """M3: a cooldown skip is expected, handled behaviour, not a problem."""
        class FakeResult:
            returncode = EXIT_SKIPPED

        monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeResult())

        with caplog.at_level("WARNING"):
            outcome = run_daily.run_scraper("PCCG", "scraper.pccg", "pccg")

        assert outcome.status == "skipped"
        assert not any(r.levelname == "ERROR" for r in caplog.records)
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_a_real_failure_still_logs_at_error(self, monkeypatch, caplog):
        class FakeResult:
            returncode = 1

        monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeResult())

        with caplog.at_level("WARNING"):
            outcome = run_daily.run_scraper("Umart", "scraper.umart", "umart")

        assert outcome.status == "failed"
        assert any(r.levelname == "ERROR" for r in caplog.records)


def test_an_auth_outcome_alerts_with_the_fix(isolated_pipeline, monkeypatch):
    monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
        label, "auth" if label == "pccg" else "ok", 4 if label == "pccg" else 0,
        detail="Algolia rejected the PCCG search key (HTTP 403) - update ALGOLIA_API_KEY" if label == "pccg" else ""))

    run_daily.run(_args())

    [line] = [l for l in isolated_pipeline.alerts[0] if "PCCG" in l]
    assert "credentials rejected" in line
    assert "ALGOLIA_API_KEY" in line
