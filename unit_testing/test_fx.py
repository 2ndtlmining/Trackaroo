"""AUD/USD rate cache (#32). HTTP is always mocked."""
import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import fx

FIXTURE = Path(__file__).parent / "fixtures" / "rba_f11_1_sample.csv"


@pytest.fixture
def rba_text():
    return FIXTURE.read_text(encoding="utf-8")


def _resp(text="", json_data=None, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_data
    if status >= 400:
        r.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return r


def _rows(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT rate_date, aud_per_usd, source FROM fx_rates ORDER BY rate_date").fetchall()
    finally:
        conn.close()


FRANK = {"date": "2026-10-01", "rates": {"AUD": 1.53}}


def _by_url(rba=None, frank=None):
    def fake_get(url, **k):
        if "rba.gov.au" in url:
            if isinstance(rba, Exception):
                raise rba
            return rba
        return frank
    return fake_get


class TestParsers:
    def test_latest_numeric_row_inverted(self, rba_text):
        d, rate = fx.parse_rba_csv(rba_text)
        assert d == "2026-09-30"
        assert rate == pytest.approx(1 / 0.6480)

    def test_missing_column_returns_none(self):
        assert fx.parse_rba_csv("Series ID,FXRJY\n30-Sep-2026,95.9\n") is None

    def test_no_series_row_returns_none(self):
        assert fx.parse_rba_csv("nothing,here\n") is None

    def test_rows_helper_returns_all_numeric_rows(self, rba_text):
        rows = fx.parse_rba_rows(rba_text)
        assert [d for d, _ in rows] == ["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]

    def test_bounds_apply_to_every_row(self):
        text = "Series ID,FXRUSD\n29-Sep-2026,0.6500\n30-Sep-2026,1.25\n01-Oct-2026,0.3\n"
        assert [d for d, _ in fx.parse_rba_rows(text)] == ["2026-09-29"]
        assert fx.parse_rba_csv("Series ID,FXRUSD\n30-Sep-2026,1.25\n") is None  # 0.8 AUD/USD
        assert fx.parse_rba_csv("Series ID,FXRUSD\n30-Sep-2026,0.3333\n") is None  # 3.0 AUD/USD

    def test_out_of_range_rates_log_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="fx"):
            fx.parse_rba_rows("Series ID,FXRUSD\n29-Sep-2026,0.6500\n01-Oct-2026,0.3\n")
            assert "FX RBA rate 3.3333 outside 1.0-2.5, rejected" in caplog.text
            caplog.clear()
            fx.parse_rba_csv("Series ID,FXRUSD\n30-Sep-2026,1.25\n")
            assert "FX RBA rate 0.8000 outside 1.0-2.5, rejected" in caplog.text
            caplog.clear()
            fx.parse_frankfurter({"date": "2026-10-01", "rates": {"AUD": 3.0}})
            assert "FX Frankfurter rate 3.0000 outside 1.0-2.5, rejected" in caplog.text

    def test_in_range_rates_do_not_warn(self, caplog):
        with caplog.at_level(logging.WARNING, logger="fx"):
            fx.parse_frankfurter(FRANK)
            fx.parse_rba_rows("Series ID,FXRUSD\n29-Sep-2026,0.6500\n")
        assert caplog.text == ""

    def test_frankfurter(self):
        assert fx.parse_frankfurter(FRANK) == ("2026-10-01", 1.53)

    @pytest.mark.parametrize("rate", [0.8, 3.0])
    def test_frankfurter_out_of_bounds(self, rate):
        assert fx.parse_frankfurter({"date": "2026-10-01", "rates": {"AUD": rate}}) is None

    def test_frankfurter_malformed(self):
        assert fx.parse_frankfurter({}) is None


class TestRun:
    def test_rba_ok_upserts_recent_rows(self, tmp_path, monkeypatch, rba_text):
        get = MagicMock(return_value=_resp(rba_text))
        monkeypatch.setattr(fx.requests, "get", get)
        db = tmp_path / "t.db"
        result = fx.run(db)
        assert result[0] == "2026-09-30" and result[2] == "rba"
        rows = _rows(db)
        assert {r[2] for r in rows} == {"rba"}
        assert [r[0] for r in rows] == ["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
        assert get.call_count == 1
        assert get.call_args.kwargs["timeout"] == 10
        assert get.call_args.kwargs["headers"]["User-Agent"].startswith("Trackaroo/1.0")

    def test_only_rows_within_seven_days_are_stored(self, tmp_path, monkeypatch):
        text = "Series ID,FXRUSD\n20-Sep-2026,0.6500\n23-Sep-2026,0.6500\n30-Sep-2026,0.6480\n"
        monkeypatch.setattr(fx.requests, "get", MagicMock(return_value=_resp(text)))
        db = tmp_path / "t.db"
        fx.run(db)
        assert [r[0] for r in _rows(db)] == ["2026-09-23", "2026-09-30"]

    def test_rba_raising_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fx.requests, "get", _by_url(ConnectionError("down"), _resp(json_data=FRANK)))
        db = tmp_path / "t.db"
        assert fx.run(db) == ("2026-10-01", 1.53, "frankfurter")
        assert _rows(db) == [("2026-10-01", 1.53, "frankfurter")]

    def test_rba_403_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fx.requests, "get", _by_url(_resp(status=403), _resp(json_data=FRANK)))
        assert fx.run(tmp_path / "t.db")[2] == "frankfurter"

    def test_both_failing_returns_none_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(fx.requests, "get", MagicMock(side_effect=ConnectionError("down")))
        with caplog.at_level(logging.WARNING):
            assert fx.run(tmp_path / "t.db") is None
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_second_run_same_date_keeps_one_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fx.requests, "get", MagicMock(return_value=_resp("Series ID,FXRUSD\n30-Sep-2026,0.6480\n")))
        db = tmp_path / "t.db"
        fx.run(db)
        monkeypatch.setattr(fx.requests, "get", MagicMock(return_value=_resp("Series ID,FXRUSD\n30-Sep-2026,0.6400\n")))
        fx.run(db)
        rows = _rows(db)
        assert len(rows) == 1 and rows[0][1] == pytest.approx(1 / 0.64)

    def test_creates_table_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fx.requests, "get", _by_url(_resp(status=403), _resp(json_data=FRANK)))
        db = tmp_path / "bare.db"
        sqlite3.connect(str(db)).close()
        fx.run(db)
        assert len(_rows(db)) == 1

    def test_defaults_to_module_db_path_at_call_time(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fx.requests, "get", _by_url(_resp(status=403), _resp(json_data=FRANK)))
        target = tmp_path / "late.db"
        monkeypatch.setattr(fx, "DB_PATH", target)
        fx.run()
        assert len(_rows(target)) == 1
