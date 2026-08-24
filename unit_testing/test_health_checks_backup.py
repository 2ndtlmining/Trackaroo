"""Tests for the health checks guarding the JSON backup and run cadence.

Three checks added after the 19/21-Aug 2026 data-loss incident:

- check_json_db_parity   — can the JSON backup still rebuild this day?
- check_missing_days     — did a scheduled run get skipped entirely?
- check_scraper_cooldown — is a retailer deliberately paused right now?
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import health_checks
from health_checks import (
    CheckResult,
    check_json_db_parity,
    check_missing_days,
    check_scraper_cooldown,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

URL = "https://www.pccasegear.com/products/68242/gigabyte-rtx-5080"


def statuses(results):
    return {r.check_name: r.status for r in results}


@pytest.fixture
def db_file(tmp_path):
    """A DB with one PCCG GPU listing snapshotted on 21 and 22 August."""
    path = tmp_path / "t.db"
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    c.execute(
        "INSERT INTO products (id, category, brand, model, generation_tier, tracked)"
        " VALUES (1, 'gpu', 'NVIDIA', 'GeForce RTX 5080', 'current', 1)"
    )
    c.execute(
        "INSERT INTO retailer_listings (id, product_id, retailer, listing_url, variant_name)"
        " VALUES (1, 1, 'pccg', ?, 'Gigabyte RTX 5080')", (URL,)
    )
    for day in ("2026-08-21", "2026-08-22"):
        c.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
            " VALUES (1, ?, 2499.0, 'in_stock')", (day,)
        )
    c.commit()
    c.close()
    return path


def write_json(data_dir, products, name="gpu_pccg_21_August_2026.json"):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_text(json.dumps({
        "retailer": "pccg", "scrape_date": "21_August_2026", "category": "gpu",
        "total_watchlist": 100, "matched": len(products), "unmatched_count": 0,
        "unmatched_models": [], "products": products,
    }), encoding="utf-8")


# ── check_json_db_parity ──────────────────────────────────────────────────

def test_parity_passes_when_json_covers_every_db_snapshot(db_file, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    write_json(data_dir, [{"url": URL}])
    monkeypatch.setattr(health_checks, "DATA_DIR", data_dir)

    results = check_json_db_parity("2026-08-21", db_file)

    assert statuses(results) == {"json_db_parity_pccg_gpu": CheckResult.OK}


def test_parity_errors_when_the_json_file_lost_its_products(db_file, tmp_path, monkeypatch):
    """The exact 21-Aug regression: an empty re-run clobbered a good file."""
    data_dir = tmp_path / "data"
    write_json(data_dir, [])
    monkeypatch.setattr(health_checks, "DATA_DIR", data_dir)

    results = check_json_db_parity("2026-08-21", db_file)

    assert statuses(results) == {"json_db_parity_pccg_gpu": CheckResult.ERROR}
    assert "export_snapshots.py --repair" in results[0].message


def test_parity_errors_when_the_json_file_is_missing(db_file, tmp_path, monkeypatch):
    monkeypatch.setattr(health_checks, "DATA_DIR", tmp_path / "empty")

    results = check_json_db_parity("2026-08-21", db_file)

    assert statuses(results) == {"json_db_parity_pccg_gpu": CheckResult.ERROR}
    assert "missing or unreadable" in results[0].message


def test_parity_matches_on_sku_so_a_slug_rewrite_is_not_a_gap(db_file, tmp_path, monkeypatch):
    # The DB holds the slugged URL; the JSON holds the bare one. Same listing.
    data_dir = tmp_path / "data"
    write_json(data_dir, [{"url": "https://www.pccasegear.com/products/68242"}])
    monkeypatch.setattr(health_checks, "DATA_DIR", data_dir)

    results = check_json_db_parity("2026-08-21", db_file)

    assert statuses(results) == {"json_db_parity_pccg_gpu": CheckResult.OK}


def test_parity_is_silent_for_a_date_with_no_data(db_file, tmp_path, monkeypatch):
    monkeypatch.setattr(health_checks, "DATA_DIR", tmp_path / "data")
    assert check_json_db_parity("2026-01-01", db_file) == []


def test_parity_is_silent_when_the_db_is_absent(tmp_path):
    assert check_json_db_parity("2026-08-21", tmp_path / "nope.db") == []


# ── check_missing_days ────────────────────────────────────────────────────

def test_no_gap_reported_for_consecutive_days(db_file):
    results = check_missing_days(db_file)
    assert statuses(results) == {"missing_days": CheckResult.OK}


def test_a_skipped_day_is_reported(db_file):
    c = sqlite3.connect(str(db_file))
    c.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
        " VALUES (1, '2026-08-24', 2499.0, 'in_stock')"
    )
    c.commit()
    c.close()

    results = check_missing_days(db_file)

    assert statuses(results) == {"missing_days": CheckResult.WARNING}
    assert "2026-08-23" in results[0].message


def test_a_single_day_of_history_cannot_have_gaps(tmp_path):
    path = tmp_path / "one.db"
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    c.execute(
        "INSERT INTO products (id, category, brand, model, tracked)"
        " VALUES (1, 'gpu', 'NVIDIA', 'RTX 5080', 1)"
    )
    c.execute(
        "INSERT INTO retailer_listings (id, product_id, retailer, listing_url)"
        " VALUES (1, 1, 'pccg', 'https://x/products/1')"
    )
    c.execute(
        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
        " VALUES (1, '2026-08-21', 1.0, 'in_stock')"
    )
    c.commit()
    c.close()

    assert check_missing_days(path) == []


def test_missing_days_is_silent_when_the_db_is_absent(tmp_path):
    assert check_missing_days(tmp_path / "nope.db") == []


# ── check_scraper_cooldown ────────────────────────────────────────────────

def write_cooldown(path, tripped_at, reason="429 circuit breaker"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "tripped_at": tripped_at.isoformat(), "reason": reason,
    }), encoding="utf-8")


def test_no_cooldown_file_means_nothing_to_report(tmp_path, monkeypatch):
    monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", tmp_path / "absent.json")
    assert check_scraper_cooldown() == []


def test_an_active_cooldown_warns_and_says_when_it_lifts(tmp_path, monkeypatch):
    path = tmp_path / "pccg_cooldown.json"
    write_cooldown(path, datetime.now(timezone.utc) - timedelta(hours=1))
    monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", path)
    monkeypatch.setattr("config.PCCG_COOLDOWN_HOURS", 4.0)

    results = check_scraper_cooldown()

    assert statuses(results) == {"scraper_cooldown_pccg": CheckResult.WARNING}
    assert "429 circuit breaker" in results[0].message
    assert "resumes in 3.0h" in results[0].message


def test_an_expired_cooldown_reports_ok(tmp_path, monkeypatch):
    path = tmp_path / "pccg_cooldown.json"
    write_cooldown(path, datetime.now(timezone.utc) - timedelta(hours=9))
    monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", path)
    monkeypatch.setattr("config.PCCG_COOLDOWN_HOURS", 4.0)

    results = check_scraper_cooldown()

    assert statuses(results) == {"scraper_cooldown_pccg": CheckResult.OK}


def test_an_unreadable_cooldown_file_warns_rather_than_raising(tmp_path, monkeypatch):
    path = tmp_path / "pccg_cooldown.json"
    path.write_text("{truncated", encoding="utf-8")
    monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", path)

    results = check_scraper_cooldown()

    assert statuses(results) == {"scraper_cooldown_pccg": CheckResult.WARNING}
    assert "unreadable" in results[0].message


def test_a_naive_timestamp_is_treated_as_utc(tmp_path, monkeypatch):
    # Older cooldown files were written without a timezone offset.
    path = tmp_path / "pccg_cooldown.json"
    write_cooldown(path, datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1))
    monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", path)
    monkeypatch.setattr("config.PCCG_COOLDOWN_HOURS", 4.0)

    results = check_scraper_cooldown()

    assert statuses(results) == {"scraper_cooldown_pccg": CheckResult.WARNING}
