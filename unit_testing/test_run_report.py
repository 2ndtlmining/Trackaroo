"""A scraper killed by the timeout keeps what it had finished (R2), and each
run's matched count reaches run_daily (R3)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

import run_daily
from scraper import scorptec, umart
from scraper.run_report import (
    EXIT_DEGRADED, EXIT_OK, REPORT_ENV, RunReport, exit_code_for, read_run_report,
)
from scraper.snapshot_io import save_category_snapshot

WATCHLIST = [
    {"model": "Ryzen 7 9800X3D", "category": "cpu", "brand": "AMD", "gen_tier": "current",
     "vram_gb": None, "search_terms": ["ryzen 7 9800x3d"]},
    {"model": "GeForce RTX 5070", "category": "gpu", "brand": "NVIDIA", "gen_tier": "current",
     "vram_gb": 12, "search_terms": ["rtx 5070"]},
]

CPU_CARD = {"name": "amd ryzen 7 9800x3d desktop processor", "full_description": "AMD Ryzen 7 9800X3D",
            "price_aud": 699.0, "stock_status": "in_stock",
            "url": "https://www.scorptec.com.au/product/cpu/amd-socket-am5/112233", "retailer_sku": "112233"}


class TestRunReport:
    def test_flush_writes_the_counts(self, tmp_path):
        path = tmp_path / "r.json"
        report = RunReport("umart", path=path)
        report.set("cpu", matched=27)
        report.note("hello")
        report.flush()

        data = read_run_report(path)
        assert data["retailer"] == "umart"
        assert data["matched"] == 27
        assert data["categories"]["cpu"]["matched"] == 27
        assert data["notes"] == ["hello"]

    def test_without_a_path_flush_is_a_no_op(self, monkeypatch, tmp_path):
        monkeypatch.delenv(REPORT_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        report = RunReport("umart")
        assert report.path is None
        report.flush()  # must not raise or write anywhere
        assert os.listdir(tmp_path) == []

    def test_the_path_comes_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(REPORT_ENV, str(tmp_path / "env.json"))
        assert RunReport("pccg").path == tmp_path / "env.json"

    def test_an_unreadable_report_reads_as_none(self, tmp_path):
        (tmp_path / "bad.json").write_text("{", encoding="utf-8")
        assert read_run_report(tmp_path / "bad.json") is None
        assert read_run_report(tmp_path / "absent.json") is None

    def test_exit_code_needs_both_categories(self):
        report = RunReport("x", path=None)
        report.set("cpu", matched=3)
        assert exit_code_for(report) == EXIT_DEGRADED
        report.set("gpu", matched=1)
        assert exit_code_for(report) == EXIT_OK


class TestPartialResultsSurvive:
    def test_scorptec_killed_during_gpus_keeps_the_cpus(self, tmp_path, monkeypatch):
        def pages(url, category_path="", **kwargs):
            if "/cpu/" in url:
                return [CPU_CARD] if url.endswith("amd-am5-9000") else []
            raise RuntimeError("killed by run_daily's timeout")

        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_all_pages", pages)
        monkeypatch.setenv(REPORT_ENV, str(tmp_path / "report.json"))

        with pytest.raises(RuntimeError):
            scorptec.main()

        [cpu_file] = tmp_path.glob("cpu_scorptec_*.json")
        assert json.loads(cpu_file.read_text(encoding="utf-8"))["matched"] == 1
        assert not list(tmp_path.glob("gpu_scorptec_*.json"))
        assert read_run_report(tmp_path / "report.json")["categories"]["cpu"]["matched"] == 1

    def test_umart_saves_each_category_as_it_finishes(self, tmp_path, monkeypatch):
        calls = []

        def fake_scrape(wl, only_category=None, **kwargs):
            calls.append(only_category)
            if only_category == "gpu":
                raise RuntimeError("killed")
            return [], set(), {}

        monkeypatch.setattr(umart, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
        monkeypatch.setattr(umart, "scrape_umart", fake_scrape)

        with pytest.raises(RuntimeError):
            umart.main()
        assert calls == ["cpu", "gpu"]
        assert list(tmp_path.glob("cpu_umart_*.json"))

    def test_incremental_save_never_downgrades(self, tmp_path):
        """Review Focus 4: a partial re-run parks its result instead of overwriting."""
        rich = [dict(CPU_CARD, url=f"https://x/{i}", watchlist_model="Ryzen 7 9800X3D",
                     watchlist_category="cpu") for i in range(5)]
        save_category_snapshot(tmp_path, "scorptec", "cpu", "29_September_2026", WATCHLIST, rich, {0})
        written = save_category_snapshot(tmp_path, "scorptec", "cpu", "29_September_2026",
                                         WATCHLIST, rich[:1], {0})

        assert ".partial-" in written.name
        main_file = tmp_path / "cpu_scorptec_29_September_2026.json"
        assert json.loads(main_file.read_text(encoding="utf-8"))["matched"] == 5


class TestRunScraperReadsTheReport:
    def test_a_timeout_still_reports_what_was_matched(self, monkeypatch):
        seen = {}

        def fake_run(cmd, capture_output, text, timeout, env):
            seen["path"] = Path(env[REPORT_ENV])
            seen["path"].write_text(json.dumps({
                "retailer": "scorptec", "matched": 41,
                "categories": {"cpu": {"matched": 41}}, "notes": [],
            }), encoding="utf-8")
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(run_daily.subprocess, "run", fake_run)

        outcome = run_daily.run_scraper("Scorptec", "scraper.scorptec", "scorptec")

        assert outcome.status == "timeout"
        assert outcome.matched == 41
        assert outcome.report["categories"]["cpu"]["matched"] == 41
        assert not seen["path"].exists()  # temp report cleaned up

    def test_the_scraper_notes_become_the_outcome_detail(self, monkeypatch):
        def fake_run(cmd, capture_output, text, timeout, env):
            Path(env[REPORT_ENV]).write_text(json.dumps({
                "retailer": "pccg", "matched": 0, "categories": {},
                "notes": ["circuit breaker tripped for cpu"],
            }), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 2)

        monkeypatch.setattr(run_daily.subprocess, "run", fake_run)

        outcome = run_daily.run_scraper("PCCG", "scraper.pccg", "pccg")

        assert outcome.status == "degraded"
        assert outcome.detail == "circuit breaker tripped for cpu"

    def test_the_matched_count_reaches_scrape_runs(self, isolated_pipeline, monkeypatch):
        import sqlite3
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "ok", 0, matched=123))

        run_daily.run(run_daily.build_parser().parse_args(["--umart"]))

        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        assert conn.execute("SELECT matched FROM scrape_runs WHERE retailer = 'umart'").fetchone()[0] == 123
        conn.close()
