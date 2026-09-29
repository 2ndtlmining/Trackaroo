"""
CLI smoke tests for the command-line entry points (main() functions).

Verifies each main() runs without raising and handles its default/dry-run
paths. All DB/network activity is redirected away from the production
database and scrapers via monkeypatching.
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


# ── seed.main ────────────────────────────────────────────────────────

class TestSeedMain:
    def test_dry_run(self, monkeypatch, tmp_path):
        """seed.main --dry-run creates a fresh DB and exits normally."""
        import seed
        server_db = tmp_path / "seed.db"
        monkeypatch.setattr(seed, "DB_PATH", server_db)
        seed.main(["--dry-run"])
        assert server_db.exists()

    def test_dry_run_no_error_exit(self, monkeypatch, tmp_path):
        """Returns normally (no SystemExit) when there are no errors."""
        import seed
        monkeypatch.setattr(seed, "DB_PATH", tmp_path / "seed2.db")
        seed.main(["--dry-run"])

    def test_active_retailer_sync_failure_does_not_crash_boot(self, monkeypatch, tmp_path, caplog):
        """seed.py runs on every container boot under `set -e` (CLAUDE.md /
        deploy/*.sh); a sync_active_retailers failure must log a WARNING and
        let main() return normally, never crash-loop the container (F20)."""
        import seed

        def boom(conn, retailers):
            raise RuntimeError("disk full")

        monkeypatch.setattr(seed, "DB_PATH", tmp_path / "seed3.db")
        monkeypatch.setattr(seed, "sync_active_retailers", boom)
        with caplog.at_level("WARNING"):
            seed.main([])  # not dry-run: this is the path that calls the sync
        assert "Active-retailer sync failed" in caplog.text
        assert not any(r.levelname == "ERROR" for r in caplog.records)


# ── query.main ───────────────────────────────────────────────────────

class TestQueryMain:
    def test_latest_prices_runs(self, monkeypatch, db, capsys):
        """query.main prints results against an in-memory DB."""
        import query
        monkeypatch.setattr(query, "get_connection", lambda *a, **k: db)
        query.main(["--model", "Test"])
        assert "No data found." in capsys.readouterr().out

    def test_biggest_movers_runs(self, monkeypatch, db, capsys):
        """query.main --biggest-movers runs without raising."""
        import query
        monkeypatch.setattr(query, "get_connection", lambda *a, **k: db)
        query.main(["--biggest-movers"])
        assert "Need at least 2 dates" in capsys.readouterr().out

    def test_group_latest_runs(self, monkeypatch, db, capsys):
        """query.main default (no args) runs against an in-memory DB."""
        import query
        monkeypatch.setattr(query, "get_connection", lambda *a, **k: db)
        query.main([])
        assert "No data found." in capsys.readouterr().out


# ── ingest.main ──────────────────────────────────────────────────────

class TestIngestMain:
    def _write_today_file(self, tmp_path):
        """Write a valid snapshot JSON file for today's date."""
        import ingest
        today = date.today().strftime("%d_%B_%Y")
        data = {
            "retailer": "scorptec",
            "scrape_date": today,
            "category": "cpu",
            "total_watchlist": 1,
            "matched": 1,
            "products": [{
                "watchlist_model": "Ryzen 7 9800X3D",
                "watchlist_category": "cpu",
                "watchlist_brand": "AMD",
                "watchlist_gen_tier": "current",
                "retailer": "scorptec",
                "price_aud": 599.0,
                "stock_status": "in_stock",
                "url": "https://scorptec.com.au/products/test",
            }],
        }
        file_path = tmp_path / f"cpu_scorptec_{today}.json"
        file_path.write_text(json.dumps(data))
        return file_path

    def test_dry_run(self, monkeypatch, tmp_path):
        """ingest.main --dry-run processes today's file without writing."""
        import ingest
        monkeypatch.setattr(ingest, "DB_PATH", tmp_path / "ingest.db")
        monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
        self._write_today_file(tmp_path)
        ingest.main(["--date", date.today().strftime("%Y-%m-%d"), "--dry-run"])

    def test_no_files(self, monkeypatch, tmp_path):
        """ingest.main with no JSON files returns cleanly."""
        import ingest
        monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ingest, "DB_PATH", tmp_path / "ingest2.db")
        ingest.main(["--dry-run"])


# ── run_daily.main ───────────────────────────────────────────────────

class TestRunDailyMain:
    def test_scorptec_dry_run(self, monkeypatch, tmp_path):
        """run_daily.main --scorptec --dry-run --no-health runs cleanly."""
        import run_daily

        def fake_scraper(name, module, label):
            return run_daily.ScrapeOutcome(label, "ok", 0)

        def fake_init_db(path):
            conn = sqlite3.connect(":memory:")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
            return conn

        monkeypatch.setattr(run_daily, "run_scraper", fake_scraper)
        monkeypatch.setattr(run_daily, "init_db", fake_init_db)
        monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
        run_daily.main(["--scorptec", "--dry-run", "--no-health"])

    def test_all_scrapers_failed(self, monkeypatch, tmp_path, capsys):
        """Aborts with SystemExit when both scrapers fail."""
        import run_daily

        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda name, module, label: run_daily.ScrapeOutcome(label, "failed", 1),
        )
        monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
        with pytest.raises(SystemExit) as exc:
            run_daily.main(["--dry-run", "--no-health"])
        assert exc.value.code == 1

    def test_alerts_failure_does_not_break_run(self, monkeypatch, tmp_path):
        """A failing alerts step (e.g. missing price_alerts table) must not crash the daily run."""
        import run_daily

        def fake_init_db(path):
            conn = sqlite3.connect(":memory:")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
            return conn

        def boom(*a, **k):
            raise RuntimeError("no such table: price_alerts")

        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda name, module, label: run_daily.ScrapeOutcome(label, "ok", 0),
        )
        monkeypatch.setattr(run_daily, "init_db", fake_init_db)
        monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
        monkeypatch.setattr(
            run_daily, "ingest_today",
            lambda conn, dry_run=False: {"inserted": 0, "skipped": 0, "errors": 0, "bad_files": []},
        )
        monkeypatch.setattr(run_daily, "check_json_files", lambda *a, **k: [])
        monkeypatch.setattr(run_daily, "run_db_checks", lambda: [])
        monkeypatch.setattr("check_delisted.run", lambda *a, **k: None)
        monkeypatch.setattr("check_stale_listings.run", lambda *a, **k: None)
        monkeypatch.setattr("notify_discord.run", lambda *a, **k: None)
        monkeypatch.setattr("notify_discord.send_alert", lambda *a, **k: None)
        monkeypatch.setattr("check_alerts.run", boom)
        monkeypatch.setattr("backup_db.backup_database", lambda **k: None)

        run_daily.main([])