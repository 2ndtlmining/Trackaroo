"""
Tests for check_alerts.py — the price-drop & restock alert engine.

Covers:
- format_aud
- query_active_alerts / query_latest_rows (snapshot pairing, exclusions)
- aggregate_product_prices (cheapest in-stock, restock detection)
- evaluate (price fire, restock fire, cooldowns, price precedence)
- build_message (price / restock titles and bodies)
- send_discord / send_webhook / send_email (never raise)
- deliver (channel routing, unconfigured-channel skip)
- run (no-op, dry-run, cooldown advance, unconfigured-channel no-advance)
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_alerts import (  # noqa: E402
    aggregate_product_prices,
    build_message,
    deliver,
    evaluate,
    format_aud,
    query_active_alerts,
    query_latest_rows,
    run,
    send_discord,
    send_email,
    send_webhook,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _seed_listing(
    db,
    *,
    retailer="scorptec",
    category="cpu",
    brand="AMD",
    model="Test CPU",
    variant=None,
    url="https://x.com/1",
    tracked=1,
    status="active",
    snapshots,
):
    """Insert a product + listing + snapshots. snapshots = [(date, price, stock)]."""
    cur = db.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, ?)",
        (category, brand, model, tracked),
    )
    product_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, retailer, variant, url, status),
    )
    listing_id = cur.lastrowid
    for snapshot_date, price, stock in snapshots:
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
            "VALUES (?, ?, ?, ?)",
            (listing_id, snapshot_date, price, stock),
        )
    db.commit()
    return product_id, listing_id


def _add_alert(
    db,
    product_id,
    *,
    target_price=100,
    channel="discord",
    notify_on_restock=0,
    active=1,
    last_notified_at=None,
    last_notified_price=None,
):
    cur = db.execute(
        "INSERT INTO price_alerts (product_id, target_price, channel, notify_on_restock, active, "
        "last_notified_at, last_notified_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, target_price, channel, notify_on_restock, active, last_notified_at, last_notified_price),
    )
    db.commit()
    return cur.lastrowid


def _alert(**kw):
    base = {
        "id": 1,
        "product_id": 1,
        "target_price": 100,
        "channel": "discord",
        "notify_on_restock": 0,
        "last_notified_at": None,
        "last_notified_price": None,
    }
    base.update(kw)
    return base


def _prod(pid=1, *, in_stock_price: int | None = 90, restock=False, retailer="scorptec", url="https://x.com/1") -> dict:
    # in_stock_price may be None (nothing in stock) — see evaluate() tests.
    return {
        "product_id": pid,
        "category": "cpu",
        "brand": "AMD",
        "model": "Test CPU",
        "in_stock_price": in_stock_price,
        "in_stock_retailer": retailer,
        "in_stock_url": url,
        "restock": restock,
    }


NOW = datetime(2026, 8, 20, 4, 0, 0, tzinfo=timezone.utc)


# ── format_aud ───────────────────────────────────────────────────────

class TestFormatAud:
    def test_formats_with_thousands_separator(self):
        assert format_aud(1049.0) == "$1,049"
        assert format_aud(599.0) == "$599"
        assert format_aud(9999.99) == "$10,000"


# ── query_active_alerts / query_latest_rows ──────────────────────────

class TestQueryActiveAlerts:
    def test_returns_only_active_rows(self, db):
        pid, _ = _seed_listing(db, snapshots=[("2026-08-19", 100, "in_stock")])
        _add_alert(db, pid, active=1)
        _add_alert(db, pid, channel="email", active=0)
        rows = query_active_alerts(db)
        assert len(rows) == 1
        assert rows[0]["channel"] == "discord"
        assert rows[0]["target_price"] == 100

    def test_returns_empty_when_no_alerts(self, db):
        assert query_active_alerts(db) == []


class TestQueryLatestRows:
    def test_pairs_latest_with_previous_snapshot(self, db):
        _seed_listing(db, snapshots=[("2026-08-18", 100, "out_of_stock"), ("2026-08-19", 90, "in_stock")])
        rows = query_latest_rows(db)
        assert len(rows) == 1
        assert rows[0]["cur_price"] == 90
        assert rows[0]["cur_status"] == "in_stock"
        assert rows[0]["prev_price"] == 100
        assert rows[0]["prev_status"] == "out_of_stock"

    def test_excludes_bundle_variant_names(self, db):
        _seed_listing(db, variant="Ryzen bundle", snapshots=[("2026-08-19", 90, "in_stock")])
        assert query_latest_rows(db) == []

    def test_excludes_untracked_and_inactive(self, db):
        _seed_listing(db, tracked=0, snapshots=[("2026-08-19", 90, "in_stock")])
        _seed_listing(db, status="delisted", url="https://x.com/2", snapshots=[("2026-08-19", 90, "in_stock")])
        assert query_latest_rows(db) == []


# ── aggregate_product_prices ─────────────────────────────────────────

class TestAggregateProductPrices:
    def test_picks_cheapest_in_stock_listing(self):
        rows = [
            {"product_id": 1, "category": "cpu", "brand": "AMD", "model": "M",
             "retailer": "scorptec", "listing_url": "https://x/1", "cur_price": 110,
             "cur_status": "in_stock", "prev_price": 100, "prev_status": "in_stock"},
            {"product_id": 1, "category": "cpu", "brand": "AMD", "model": "M",
             "retailer": "pccg", "listing_url": "https://x/2", "cur_price": 95,
             "cur_status": "in_stock", "prev_price": 99, "prev_status": "in_stock"},
        ]
        agg = aggregate_product_prices(rows)
        assert agg[1]["in_stock_price"] == 95
        assert agg[1]["in_stock_retailer"] == "pccg"
        assert agg[1]["in_stock_url"] == "https://x/2"

    def test_ignores_out_of_stock_for_price(self):
        rows = [
            {"product_id": 1, "category": "cpu", "brand": "AMD", "model": "M",
             "retailer": "scorptec", "listing_url": "https://x/1", "cur_price": 50,
             "cur_status": "out_of_stock", "prev_price": 100, "prev_status": "in_stock"},
        ]
        agg = aggregate_product_prices(rows)
        assert agg[1]["in_stock_price"] is None

    def test_detects_restock_transition(self):
        rows = [
            {"product_id": 1, "category": "cpu", "brand": "AMD", "model": "M",
             "retailer": "scorptec", "listing_url": "https://x/1", "cur_price": 90,
             "cur_status": "in_stock", "prev_price": 100, "prev_status": "out_of_stock"},
        ]
        assert aggregate_product_prices(rows)[1]["restock"] is True

    def test_no_restock_when_still_in_stock(self):
        rows = [
            {"product_id": 1, "category": "cpu", "brand": "AMD", "model": "M",
             "retailer": "scorptec", "listing_url": "https://x/1", "cur_price": 90,
             "cur_status": "in_stock", "prev_price": 100, "prev_status": "in_stock"},
        ]
        assert aggregate_product_prices(rows)[1]["restock"] is False


# ── evaluate ─────────────────────────────────────────────────────────

class TestEvaluate:
    def test_fires_on_price_breach(self):
        fired = evaluate([_alert(target_price=100)], {1: _prod(in_stock_price=90)}, NOW)
        assert len(fired) == 1
        assert fired[0]["reason"] == "price"
        assert fired[0]["price"] == 90

    def test_no_fire_when_price_above_target(self):
        assert evaluate([_alert(target_price=100)], {1: _prod(in_stock_price=150)}, NOW) == []

    def test_no_fire_on_sustained_breach_same_price(self):
        # Cooldown: a sustained breach at the same price does not re-fire.
        assert evaluate([_alert(target_price=100, last_notified_price=90)], {1: _prod(in_stock_price=90)}, NOW) == []

    def test_fires_on_further_drop(self):
        fired = evaluate([_alert(target_price=100, last_notified_price=90)], {1: _prod(in_stock_price=80)}, NOW)
        assert len(fired) == 1
        assert fired[0]["reason"] == "price"
        assert fired[0]["price"] == 80

    def test_no_price_fire_when_nothing_in_stock(self):
        assert evaluate([_alert(target_price=100)], {1: _prod(in_stock_price=None)}, NOW) == []

    def test_fires_on_restock(self):
        fired = evaluate([_alert(notify_on_restock=1)], {1: _prod(in_stock_price=None, restock=True)}, NOW)
        assert len(fired) == 1
        assert fired[0]["reason"] == "restock"
        assert fired[0]["restock"] is True

    def test_restock_requires_flag(self):
        assert evaluate([_alert(notify_on_restock=0)], {1: _prod(in_stock_price=None, restock=True)}, NOW) == []

    def test_restock_cooldown_suppresses_recent_notify(self):
        recent = (NOW - timedelta(hours=1)).isoformat()
        assert evaluate(
            [_alert(notify_on_restock=1, last_notified_at=recent)],
            {1: _prod(in_stock_price=None, restock=True)},
            NOW,
        ) == []

    def test_restock_cooldown_allows_after_window(self):
        old = (NOW - timedelta(hours=RESTOCK_HOURS() + 1)).isoformat()
        fired = evaluate(
            [_alert(notify_on_restock=1, last_notified_at=old)],
            {1: _prod(in_stock_price=None, restock=True)},
            NOW,
        )
        assert len(fired) == 1
        assert fired[0]["reason"] == "restock"

    def test_price_takes_precedence_over_restock(self):
        fired = evaluate(
            [_alert(target_price=100, notify_on_restock=1)],
            {1: _prod(in_stock_price=90, restock=True)},
            NOW,
        )
        assert len(fired) == 1
        assert fired[0]["reason"] == "price"
        assert fired[0]["restock"] is True

    def test_skips_product_with_no_state(self):
        assert evaluate([_alert(product_id=99)], {}, NOW) == []


def RESTOCK_HOURS():
    from check_alerts import RESTOCK_COOLDOWN_HOURS
    return RESTOCK_COOLDOWN_HOURS


# ── build_message ────────────────────────────────────────────────────

class TestBuildMessage:
    def test_price_message(self):
        entry = {"alert": _alert(target_price=100), "product": _prod(in_stock_price=90),
                 "reason": "price", "price": 90, "restock": False}
        title, body = build_message(entry)
        assert title == "Price alert: AMD Test CPU at $90"
        assert "your target: $100" in body
        assert "https://x.com/1" in body

    def test_price_message_mentions_restock(self):
        entry = {"alert": _alert(target_price=100), "product": _prod(in_stock_price=90, restock=True),
                 "reason": "price", "price": 90, "restock": True}
        _, body = build_message(entry)
        assert "It just restocked." in body

    def test_restock_message(self):
        entry = {"alert": _alert(notify_on_restock=1), "product": _prod(in_stock_price=95, restock=True),
                 "reason": "restock", "price": 95, "restock": True}
        title, body = build_message(entry)
        assert title == "Restock: AMD Test CPU"
        assert "back in stock" in body
        assert "$95" in body

    def test_restock_message_without_price(self):
        entry = {"alert": _alert(notify_on_restock=1), "product": _prod(in_stock_price=None, restock=True),
                 "reason": "restock", "price": None, "restock": True}
        _, body = build_message(entry)
        assert "Current price" not in body


# ── send_* (never raise) ─────────────────────────────────────────────

class TestSenders:
    def test_send_discord_swallows_errors(self, caplog):
        send_discord("http://127.0.0.1:1/nope", "t", "b")  # must not raise

    def test_send_webhook_swallows_errors(self, caplog):
        send_webhook("http://127.0.0.1:1/nope", "t", "b")  # must not raise

    def test_send_email_swallows_errors(self, caplog):
        send_email("127.0.0.1", 1, "", "", "a@b.c", "d@e.f", "t", "b")  # must not raise


class TestSenderRedaction:
    """final review M2: a webhook URL's token lives in the path. An
    exception raised while POSTing to it can embed the full URL in its
    message (urllib.error.URLError's reason, or any wrapped exception), so
    logging the exception directly leaks the token. Apply the same
    redaction as notify_discord.py / heartbeat.py: exception class name +
    HTTP status only (+ scheme://hostname), never the raw exception text."""

    TOKEN_URL = "http://example.invalid/webhooks/123/SENTINEL-WEBHOOK-TOKEN"

    def test_send_discord_never_logs_the_webhook_token(self, monkeypatch, caplog):
        def boom(req, timeout=None):
            raise OSError(f"Failed to reach {req.full_url}")

        monkeypatch.setattr("check_alerts.urllib.request.urlopen", boom)
        with caplog.at_level("ERROR"):
            send_discord(self.TOKEN_URL, "t", "b")
        assert "SENTINEL-WEBHOOK-TOKEN" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-WEBHOOK-TOKEN" not in record.getMessage()

    def test_send_webhook_never_logs_the_webhook_token(self, monkeypatch, caplog):
        def boom(req, timeout=None):
            raise OSError(f"Failed to reach {req.full_url}")

        monkeypatch.setattr("check_alerts.urllib.request.urlopen", boom)
        with caplog.at_level("ERROR"):
            send_webhook(self.TOKEN_URL, "t", "b")
        assert "SENTINEL-WEBHOOK-TOKEN" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-WEBHOOK-TOKEN" not in record.getMessage()


# ── deliver ──────────────────────────────────────────────────────────

class TestDeliver:
    def _entry(self, channel):
        return {"alert": _alert(channel=channel), "product": _prod(in_stock_price=90),
                "reason": "price", "price": 90, "restock": False}

    def test_discord_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.delenv("TRACKAROO_DISCORD_WEBHOOK_URL", raising=False)
        assert deliver(self._entry("discord")) is False

    def test_discord_configured_returns_true(self, monkeypatch):
        calls = []
        monkeypatch.setenv("TRACKAROO_DISCORD_WEBHOOK_URL", "https://hook/d")
        monkeypatch.setattr("check_alerts.send_discord", lambda url, t, b: calls.append(("d", url)))
        assert deliver(self._entry("discord")) is True
        assert calls == [("d", "https://hook/d")]

    def test_email_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.delenv("TRACKAROO_SMTP_HOST", raising=False)
        assert deliver(self._entry("email")) is False

    def test_email_configured_returns_true(self, monkeypatch):
        calls = []
        monkeypatch.setenv("TRACKAROO_SMTP_HOST", "smtp.example")
        monkeypatch.setattr("check_alerts.send_email", lambda *a: calls.append(a))
        assert deliver(self._entry("email")) is True
        assert len(calls) == 1

    def test_webhook_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.delenv("TRACKAROO_ALERT_WEBHOOK_URL", raising=False)
        assert deliver(self._entry("webhook")) is False

    def test_webhook_configured_returns_true(self, monkeypatch):
        calls = []
        monkeypatch.setenv("TRACKAROO_ALERT_WEBHOOK_URL", "https://hook/w")
        monkeypatch.setattr("check_alerts.send_webhook", lambda url, t, b: calls.append(url))
        assert deliver(self._entry("webhook")) is True
        assert calls == ["https://hook/w"]

    def test_unknown_channel_returns_false(self, monkeypatch):
        assert deliver(self._entry("carrier-pigeon")) is False


# ── run ──────────────────────────────────────────────────────────────

class TestRun:
    def test_noop_without_alerts(self, monkeypatch, db_path):
        monkeypatch.setattr("check_alerts.load_dotenv", lambda *a, **k: None)
        assert run(db_path=str(db_path)) == 0

    def test_dry_run_prints_without_advancing_cooldown(self, monkeypatch, db_path, capsys):
        conn = sqlite3.connect(str(db_path))
        pid, _ = _seed_listing(conn, snapshots=[("2026-08-19", 90, "in_stock")])
        _add_alert(conn, pid, target_price=100)
        conn.close()

        monkeypatch.setattr("check_alerts.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("TRACKAROO_DISCORD_WEBHOOK_URL", "https://hook/d")
        run(db_path=str(db_path), dry_run=True)
        out = capsys.readouterr().out
        assert "DRY-RUN" in out

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT last_notified_at FROM price_alerts").fetchone()
        conn.close()
        assert row[0] is None

    def test_fires_and_advances_cooldown(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        pid, _ = _seed_listing(conn, snapshots=[("2026-08-19", 90, "in_stock")])
        _add_alert(conn, pid, target_price=100)
        conn.close()

        monkeypatch.setattr("check_alerts.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("TRACKAROO_DISCORD_WEBHOOK_URL", "https://hook/d")
        monkeypatch.setattr("check_alerts.send_discord", lambda *a, **k: None)

        assert run(db_path=str(db_path)) == 1

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT last_notified_at, last_notified_price FROM price_alerts"
        ).fetchone()
        conn.close()
        assert row[0] is not None
        assert row[1] == 90

    def test_cooldown_suppresses_same_price_refire(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        pid, _ = _seed_listing(conn, snapshots=[("2026-08-19", 90, "in_stock")])
        _add_alert(conn, pid, target_price=100)
        conn.close()

        monkeypatch.setattr("check_alerts.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("TRACKAROO_DISCORD_WEBHOOK_URL", "https://hook/d")
        monkeypatch.setattr("check_alerts.send_discord", lambda *a, **k: None)

        assert run(db_path=str(db_path)) == 1
        # Same price, now at the last-notified price — must not re-fire.
        assert run(db_path=str(db_path)) == 0

    def test_unconfigured_channel_does_not_advance_cooldown(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        pid, _ = _seed_listing(conn, snapshots=[("2026-08-19", 90, "in_stock")])
        _add_alert(conn, pid, target_price=100, channel="discord")
        conn.close()

        monkeypatch.setattr("check_alerts.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("TRACKAROO_DISCORD_WEBHOOK_URL", raising=False)

        assert run(db_path=str(db_path)) == 0

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT last_notified_at FROM price_alerts").fetchone()
        conn.close()
        assert row[0] is None
