"""
Tests for the central configuration module (config.py).

Verifies:
- Default paths resolve to the repo root (not the process CWD)
- Environment overrides change paths and thresholds
- Malformed env overrides fall back to defaults
- Backend modules import the same canonical values
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

import config


def _config_value_with_env(env_var: str, env_value: str, attr: str):
    """Import config in a fresh subprocess under the given env var.

    Env overrides are read at import time (process start in deployment), so
    a subprocess is the faithful way to exercise them.
    """
    code = f"import config; print(config.{attr})"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, env_var: env_value},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


class TestPathDefaults:
    def test_base_dir_is_repo_root(self):
        """BASE_DIR must resolve to the repository root."""
        assert config.BASE_DIR == Path(__file__).resolve().parent.parent

    def test_data_dir_points_at_repo_data(self):
        assert config.DATA_DIR == config.BASE_DIR / "data"

    def test_db_path_default(self):
        assert config.DB_PATH == config.BASE_DIR / "db" / "trackaroo.db"

    def test_schema_and_watchlist_defaults(self):
        assert config.SCHEMA_PATH == config.BASE_DIR / "db" / "schema.sql"
        assert config.WATCHLIST_PATH == config.BASE_DIR / "db" / "watchlist.csv"


class TestEnvOverrides:
    def test_db_path_env_override(self):
        raw = "C:/custom/place/trackaroo.db"
        out = _config_value_with_env("TRACKAROO_DB", raw, "DB_PATH")
        assert out == str(Path(raw).expanduser())

    def test_data_dir_env_override(self):
        # Use an absolute platform-neutral path (avoids Windows drive-relative quirks)
        out = _config_value_with_env("TRACKAROO_DATA_DIR", str(Path("C:/tmp/scrapes")), "DATA_DIR")
        assert out == str(Path("C:/tmp/scrapes"))

    def test_scrape_timeout_env_override(self):
        out = _config_value_with_env("TRACKAROO_SCRAPER_TIMEOUT_SECONDS", "90", "SCRAPER_TIMEOUT_SECONDS")
        assert out == "90"

    def test_stale_threshold_env_override(self):
        out = _config_value_with_env("TRACKAROO_STALE_THRESHOLD_DAYS", "7", "STALE_THRESHOLD_DAYS")
        assert out == "7"

    def test_price_anomaly_sigma_env_override(self):
        out = _config_value_with_env("TRACKAROO_PRICE_ANOMALY_STD_DEVS", "4.5", "PRICE_ANOMALY_STD_DEVS")
        assert out == "4.5"

    def test_match_thresholds_json_override(self):
        raw = json.dumps({"scorptec": {"min_total": 180, "min_per_category": 60}})
        out = _config_value_with_env("TRACKAROO_MATCH_THRESHOLDS_JSON", raw, "MATCH_THRESHOLDS")
        assert "'min_total': 180" in out and "'min_per_category': 60" in out

    def test_batch_size_env_override(self):
        out = _config_value_with_env("TRACKAROO_BATCH_SIZE", "32", "BATCH_SIZE")
        assert out == "32"


class TestMalformedOverrides:
    def test_non_numeric_int_falls_back(self):
        """A non-numeric env value must not crash config import."""
        out = _config_value_with_env("TRACKAROO_STALE_THRESHOLD_DAYS", "banana", "STALE_THRESHOLD_DAYS")
        assert out == "3"

    def test_malformed_json_falls_back(self):
        out = _config_value_with_env("TRACKAROO_MATCH_THRESHOLDS_JSON", "{not json", "MATCH_THRESHOLDS")
        assert "'min_total': 90" in out


class TestSharedConsumption:
    def test_health_checks_import_same_values(self):
        """health_checks.py must honour the same env-supplied thresholds."""
        import health_checks
        assert health_checks.STALE_THRESHOLD_DAYS == config.STALE_THRESHOLD_DAYS
        assert health_checks.MATCH_THRESHOLDS == config.MATCH_THRESHOLDS
        assert health_checks.DB_PATH == config.DB_PATH
        assert health_checks.DATA_DIR == config.DATA_DIR

    def test_run_daily_imports_same_paths(self):
        import run_daily
        assert run_daily.DATA_DIR == config.DATA_DIR
        assert run_daily.DB_PATH == config.DB_PATH
        assert run_daily.SCRAPER_TIMEOUT_SECONDS == config.SCRAPER_TIMEOUT_SECONDS

    def test_ingest_imports_same_paths(self):
        import ingest
        assert ingest.DATA_DIR == config.DATA_DIR
        assert ingest.DB_PATH == config.DB_PATH
        assert ingest.SCHEMA_PATH == config.SCHEMA_PATH

    def test_pccg_batch_tuning_imports_config(self):
        import scraper.pccg as pccg
        assert pccg.BATCH_SIZE == config.BATCH_SIZE
        assert pccg.BATCH_DELAY == config.BATCH_DELAY