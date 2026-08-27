"""
Tests for check_staleness.py — the "a run never happened" monitor.

The existing health checks only run *inside* a pipeline run, so they cannot
detect the one failure that matters most: the run not happening at all. That
is exactly how 27-Aug-2026 was discovered by a human rather than by the
system. This monitor is the missing piece — it reads only the DB, needs no
network, and is safe to run on any schedule.
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import check_staleness
from health_checks import CheckResult


SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    model TEXT
);
CREATE TABLE retailer_listings (
    id INTEGER PRIMARY KEY,
    product_id INTEGER,
    retailer TEXT
);
CREATE TABLE price_snapshots (
    id INTEGER PRIMARY KEY,
    retailer_listing_id INTEGER,
    snapshot_date TEXT,
    price_aud REAL,
    stock_status TEXT
);
"""


def _make_db(tmp_path, snapshots):
    """snapshots: list of (retailer, date_str)."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA)
    listing_ids = {}
    for i, (retailer, day) in enumerate(snapshots, start=1):
        if retailer not in listing_ids:
            lid = len(listing_ids) + 1
            conn.execute(
                "INSERT INTO retailer_listings (id, product_id, retailer) VALUES (?,?,?)",
                (lid, 1, retailer),
            )
            listing_ids[retailer] = lid
        conn.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
            " VALUES (?,?,?,?)",
            (listing_ids[retailer], day, 100.0, "in_stock"),
        )
    conn.commit()
    conn.close()
    return db


def _statuses(results):
    return {r.check_name: r.status for r in results}


def _worst(results):
    return check_staleness.worst_status(results)


# ── Healthy ────────────────────────────────────────────────────────

def test_todays_data_is_not_stale(tmp_path):
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-27")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _worst(results) == CheckResult.OK
    assert _statuses(results)["snapshot_staleness"] == CheckResult.OK


def test_yesterdays_data_is_tolerated_at_default_threshold(tmp_path):
    """A run that has not fired *yet today* is not an outage."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-26"), ("pccg", "2026-08-26")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _worst(results) == CheckResult.OK


# ── The failure this monitor exists for ────────────────────────────

def test_two_days_without_data_is_an_error(tmp_path):
    """Nothing since the day before yesterday = a run was missed outright."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-25"), ("pccg", "2026-08-25")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _worst(results) == CheckResult.ERROR
    stale = [r for r in results if r.check_name == "snapshot_staleness"][0]
    assert stale.status == CheckResult.ERROR
    assert "2 days" in stale.message


def test_threshold_is_configurable(tmp_path):
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-25")])

    assert _worst(check_staleness.evaluate(db_path=db, today=today, threshold_days=5)) != CheckResult.ERROR
    assert _worst(check_staleness.evaluate(db_path=db, today=today, threshold_days=1)) == CheckResult.ERROR


def test_one_lagging_retailer_warns_but_does_not_error(tmp_path):
    """PCCG cooling down is degraded, not an outage — the pipeline still ran."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-22")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _worst(results) == CheckResult.WARNING
    assert _statuses(results)["retailer_staleness_pccg"] == CheckResult.WARNING
    assert _statuses(results)["snapshot_staleness"] == CheckResult.OK


# ── Degenerate inputs must alert, not crash ────────────────────────

def test_missing_database_is_an_error(tmp_path):
    results = check_staleness.evaluate(db_path=tmp_path / "nope.db", today=date(2026, 8, 27))

    assert _worst(results) == CheckResult.ERROR
    assert any("not found" in r.message.lower() for r in results)


def test_empty_database_is_an_error(tmp_path):
    db = _make_db(tmp_path, [])

    results = check_staleness.evaluate(db_path=db, today=date(2026, 8, 27))

    assert _worst(results) == CheckResult.ERROR
    assert any("no price snapshots" in r.message.lower() for r in results)


def test_unreadable_database_is_an_error_not_an_exception(tmp_path):
    db = tmp_path / "garbage.db"
    db.write_bytes(b"this is not a sqlite file at all")

    results = check_staleness.evaluate(db_path=db, today=date(2026, 8, 27))

    assert _worst(results) == CheckResult.ERROR


# ── CLI / alerting behaviour ───────────────────────────────────────

def test_run_returns_nonzero_exit_when_stale(tmp_path, monkeypatch):
    """Exit code alone must be enough for a scheduler with no Discord."""
    sent = []
    monkeypatch.setattr(check_staleness, "send_alert", lambda lines, dry_run=False: sent.append(lines) or 1)
    db = _make_db(tmp_path, [("scorptec", "2026-08-20")])

    code = check_staleness.run(db_path=str(db), today=date(2026, 8, 27))

    assert code == 1
    assert sent, "a stale DB must raise a Discord alert"


def test_run_returns_zero_and_stays_quiet_when_fresh(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(check_staleness, "send_alert", lambda lines, dry_run=False: sent.append(lines) or 1)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-27")])

    code = check_staleness.run(db_path=str(db), today=date(2026, 8, 27))

    assert code == 0
    assert not sent, "a healthy DB must not alert"


def test_warnings_alone_do_not_alert_or_fail(tmp_path, monkeypatch):
    """One lagging retailer is reported, but must not page anyone."""
    sent = []
    monkeypatch.setattr(check_staleness, "send_alert", lambda lines, dry_run=False: sent.append(lines) or 1)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-20")])

    code = check_staleness.run(db_path=str(db), today=date(2026, 8, 27))

    assert code == 0
    assert not sent


def test_run_never_raises_on_a_broken_db(tmp_path, monkeypatch):
    monkeypatch.setattr(check_staleness, "send_alert", lambda lines, dry_run=False: 1)
    db = tmp_path / "garbage.db"
    db.write_bytes(b"nope")

    assert check_staleness.run(db_path=str(db), today=date(2026, 8, 27)) == 1


def test_alert_failure_does_not_crash_the_monitor(tmp_path, monkeypatch):
    """Discord being down must not turn a staleness report into a traceback."""
    def _boom(lines, dry_run=False):
        raise RuntimeError("webhook down")
    monkeypatch.setattr(check_staleness, "send_alert", _boom)
    db = _make_db(tmp_path, [("scorptec", "2026-08-20")])

    assert check_staleness.run(db_path=str(db), today=date(2026, 8, 27)) == 1


def test_cli_dry_run_does_not_post(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(check_staleness, "send_alert",
                        lambda lines, dry_run=False: captured.setdefault("dry_run", dry_run) or 1)
    db = _make_db(tmp_path, [("scorptec", "2026-08-20")])

    check_staleness.main(["--db", str(db), "--dry-run", "--today", "2026-08-27"])

    assert captured["dry_run"] is True
