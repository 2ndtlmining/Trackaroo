"""
Tests for notify_discord.py — the daily Discord digest.

Covers the digest query (same-listing previous-snapshot pairing, exclusions),
the top-movers grouping, embed formatting (colours, retailer/Trackaroo links),
webhook sending (error swallowing), and the run() orchestration (routing,
no-op without webhooks, dry-run).
"""
import argparse
import sqlite3
import sys
import unittest.mock
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notify_discord import (  # noqa: E402
    build_digest,
    build_embed,
    format_aud,
    load_dotenv,
    query_digest_rows,
    run,
    send_alert,
    send_embed,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _seed_listing(
    db,
    *,
    retailer="scorptec",
    category="cpu",
    brand="AMD",
    model="Test CPU",
    variant="Variant A",
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


def _row(
    product_id,
    *,
    category="cpu",
    brand="AMD",
    model="Test CPU",
    retailer="scorptec",
    url="https://x.com/1",
    today,
    prev,
):
    return {
        "product_id": product_id,
        "category": category,
        "brand": brand,
        "model": model,
        "retailer": retailer,
        "listing_url": url,
        "today_price": today,
        "today_date": "2026-08-11",
        "prev_price": prev,
        "prev_date": "2026-08-10",
        "pct": (today - prev) / prev * 100.0,
    }


class _OkResponse:
    status_code = 204

    def raise_for_status(self):
        return None


class _ErrorResponse:
    """A real 5xx: `requests.post` returns normally, and `raise_for_status()`
    is what turns it into an exception -- fix-round-1 I1 covers exactly this
    path, not just a raising `requests.post`.
    """
    status_code = 500

    def raise_for_status(self):
        raise requests.HTTPError("500 Server Error")


# ── format_aud ───────────────────────────────────────────────────────

class TestFormatAud:
    def test_formats_with_thousands_separator(self):
        assert format_aud(1049.0) == "$1,049"
        assert format_aud(599.0) == "$599"
        assert format_aud(9999.99) == "$10,000"


# ── load_dotenv ──────────────────────────────────────────────────────

class TestLoadDotenv:
    def test_loads_key_value_pairs(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DISCORD_WEBHOOK_URL=https://hook/digest\n"
            "# a comment\n"
            "DISCORD_WEBHOOK_ALERT=\"https://hook/alert\"\n"
            "\n"
            "TRACKAROO_PUBLIC_BASE_URL=https://x.example/\n"
        )
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_ALERT", raising=False)
        monkeypatch.delenv("TRACKAROO_PUBLIC_BASE_URL", raising=False)
        load_dotenv(env_file)
        assert os_environ("DISCORD_WEBHOOK_URL") == "https://hook/digest"
        assert os_environ("DISCORD_WEBHOOK_ALERT") == "https://hook/alert"
        assert os_environ("TRACKAROO_PUBLIC_BASE_URL") == "https://x.example/"

    def test_real_env_wins_over_dotenv(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("DISCORD_WEBHOOK_URL=https://from-file\n")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://from-env")
        load_dotenv(env_file)
        assert os_environ("DISCORD_WEBHOOK_URL") == "https://from-env"

    def test_missing_file_is_noop(self, tmp_path):
        load_dotenv(tmp_path / "does-not-exist.env")  # should not raise


# ── query_digest_rows ────────────────────────────────────────────────

class TestQueryDigestRows:
    def test_pairs_current_with_previous_on_same_listing(self, db):
        _seed_listing(db, snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        rows = query_digest_rows(db)
        assert len(rows) == 1
        assert rows[0]["today_price"] == 110
        assert rows[0]["prev_price"] == 100
        assert rows[0]["brand"] == "AMD"
        assert rows[0]["retailer"] == "scorptec"
        assert rows[0]["listing_url"] == "https://x.com/1"

    def test_excludes_listing_with_no_previous_snapshot(self, db):
        _seed_listing(db, snapshots=[("2026-08-11", 110, "in_stock")])
        assert query_digest_rows(db) == []

    def test_excludes_out_of_stock_current(self, db):
        _seed_listing(db, snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "out_of_stock")])
        assert query_digest_rows(db) == []

    def test_uses_most_recent_snapshot_as_current(self, db):
        _seed_listing(
            db,
            snapshots=[
                ("2026-08-08", 90, "in_stock"),
                ("2026-08-09", 100, "in_stock"),
                ("2026-08-10", 110, "in_stock"),
            ],
        )
        rows = query_digest_rows(db)
        assert rows[0]["today_price"] == 110
        assert rows[0]["prev_price"] == 100

    def test_excludes_bundle_variant_names(self, db):
        _seed_listing(db, variant="Ryzen 7 9800X3D + motherboard bundle", snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        assert query_digest_rows(db) == []

    def test_excludes_bundle_urls(self, db):
        _seed_listing(db, url="https://x.com/bdl-1234", snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        assert query_digest_rows(db) == []

    def test_excludes_untracked_products(self, db):
        _seed_listing(db, tracked=0, snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        assert query_digest_rows(db) == []

    def test_excludes_inactive_listings(self, db):
        _seed_listing(db, status="delisted", snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        assert query_digest_rows(db) == []

    def test_keeps_rows_for_both_retailers(self, db):
        _seed_listing(db, retailer="scorptec", snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        _seed_listing(db, retailer="pccg", url="https://x.com/2", snapshots=[("2026-08-10", 95, "in_stock"), ("2026-08-11", 99, "in_stock")])
        rows = query_digest_rows(db)
        assert {r["retailer"] for r in rows} == {"scorptec", "pccg"}


# ── build_digest ─────────────────────────────────────────────────────

class TestBuildDigest:
    def test_keeps_cheapest_listing_per_product(self):
        rows = [
            _row(1, today=110, prev=100),      # scorptec $110
            _row(1, retailer="pccg", url="https://x.com/2", today=99, prev=90),  # pccg $99
        ]
        digest = build_digest(rows)
        products = digest["cpu:up"]
        assert len(products) == 1
        assert products[0]["retailer"] == "pccg"
        assert products[0]["today_price"] == 99

    def test_move_on_pricier_listing_survives_flat_cheaper_one(self):
        rows = [
            _row(1, today=1149, prev=1149),    # flat $1,149
            _row(1, retailer="pccg", url="https://x.com/2", today=1199, prev=1149),  # moved to $1,199
        ]
        digest = build_digest(rows)
        products = digest["cpu:up"]
        assert len(products) == 1
        assert products[0]["retailer"] == "pccg"
        assert products[0]["today_price"] == 1199

    def test_skips_flat_moves(self):
        digest = build_digest([_row(1, today=100, prev=100)])
        assert digest == {}

    def test_splits_up_and_down_per_category(self):
        rows = [
            _row(1, category="cpu", model="CPU Up", today=110, prev=100),
            _row(2, category="cpu", model="CPU Down", today=90, prev=100),
            _row(3, category="gpu", model="GPU Up", today=120, prev=100),
            _row(4, category="gpu", model="GPU Down", today=80, prev=100),
        ]
        digest = build_digest(rows)
        assert set(digest) == {"cpu:up", "cpu:down", "gpu:up", "gpu:down"}
        assert digest["cpu:up"][0]["model"] == "CPU Up"
        assert digest["cpu:down"][0]["model"] == "CPU Down"

    def test_caps_at_top_three_sorted_by_magnitude(self):
        rows = [_row(i, model=f"CPU {i}", today=100 + i, prev=100) for i in range(1, 6)]
        digest = build_digest(rows)
        ups = digest["cpu:up"]
        assert len(ups) == 3
        assert [r["model"] for r in ups] == ["CPU 5", "CPU 4", "CPU 3"]


# ── build_embed ──────────────────────────────────────────────────────

class TestBuildEmbed:
    def test_up_embed_title_color_and_price_line(self):
        embed = build_embed("gpu:up", [_row(1, brand="NVIDIA", model="RTX 5070", today=1049, prev=999)])
        assert embed["title"] == "GPU price ups"
        assert embed["color"] == 0xF87171
        assert "**NVIDIA RTX 5070**" in embed["description"]
        assert "$999 → $1,049 (+5.0%) · Scorptec" in embed["description"]

    def test_down_embed_uses_down_color(self):
        embed = build_embed("cpu:down", [_row(1, today=90, prev=100)])
        assert embed["title"] == "CPU price drops"
        assert embed["color"] == 0x34D399
        assert "(-10.0%)" in embed["description"]

    def test_links_to_retailer_and_optionally_trackaroo(self):
        embed = build_embed("cpu:up", [_row(1, retailer="pccg", today=110, prev=100)])
        assert "[View on PCCG](https://x.com/1)" in embed["description"]
        assert "Trackaroo page" not in embed["description"]

        with_base = build_embed("cpu:up", [_row(1, retailer="pccg", today=110, prev=100)], "https://trackaroo.example")
        assert "[Trackaroo page](https://trackaroo.example/product/1)" in with_base["description"]


# ── send_embed ───────────────────────────────────────────────────────

class TestSendEmbed:
    def test_posts_embed_json_and_reports_success(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", fake_post)
        assert send_embed("https://hook/gpu", {"title": "t"}) is True
        assert captured["url"] == "https://hook/gpu"
        assert captured["json"] == {"embeds": [{"title": "t"}]}
        assert captured["timeout"] == 10

    def test_swallows_webhook_errors_and_reports_failure(self, monkeypatch, caplog):
        """Fix-round-1 I1: a raised RequestException must not just be logged --
        the caller needs to know delivery failed so a same-day claim can be
        released for the next hourly retry."""
        def fake_post(url, json=None, timeout=None):
            raise requests.RequestException("boom")

        monkeypatch.setattr("notify_discord.requests.post", fake_post)
        assert send_embed("https://hook/gpu", {"title": "t"}) is False  # must not raise
        assert "Discord webhook failed" in caplog.text

    def test_a_non_2xx_status_reports_failure(self, monkeypatch, caplog):
        """Fix-round-1 I1: a real webhook outage/5xx never raises out of
        requests.post itself -- raise_for_status() is what turns it into an
        exception, and that must also be reported as a delivery failure."""
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: _ErrorResponse())
        assert send_embed("https://hook/gpu", {"title": "t"}) is False
        assert "Discord webhook failed" in caplog.text


class TestSendEmbedRedaction:
    """final review M2: requests' HTTPError/ConnectionError messages embed the
    full request URL, and a Discord webhook URL's token lives in the path --
    logging the exception directly (``LOGGER.error(..., e)``) leaked it.
    Apply the same redaction as heartbeat.py's fix-round-1 I1: exception
    class name + HTTP status only (+ scheme://hostname), never the raw
    exception text or the URL itself."""

    TOKEN_URL = "https://discord.com/api/webhooks/123456/SENTINEL-DISCORD-TOKEN"

    def test_a_raising_post_never_logs_the_webhook_token(self, monkeypatch, caplog):
        def fake_post(url, json=None, timeout=None):
            # requests/urllib3 embed the full URL in exception text -- this is
            # the real shape a ConnectionError's MaxRetryError message takes.
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

        monkeypatch.setattr("notify_discord.requests.post", fake_post)
        with caplog.at_level("ERROR"):
            assert send_embed(self.TOKEN_URL, {"title": "t"}) is False
        assert "SENTINEL-DISCORD-TOKEN" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-DISCORD-TOKEN" not in record.getMessage()

    def test_a_404_response_never_logs_the_webhook_token(self, monkeypatch, caplog):
        resp = unittest.mock.Mock(status_code=404)
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"404 Client Error: Not Found for url: {self.TOKEN_URL}", response=resp
        )
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: resp)
        with caplog.at_level("ERROR"):
            assert send_embed(self.TOKEN_URL, {"title": "t"}) is False
        assert "SENTINEL-DISCORD-TOKEN" not in caplog.text
        for record in caplog.records:
            assert "SENTINEL-DISCORD-TOKEN" not in record.getMessage()
        # The status code is still useful and not secret -- keep reporting it.
        assert "404" in caplog.text


# ── send_alert ──────────────────────────────────────────────────────

class TestSendAlert:
    """Pipeline-issue alerts go to DISCORD_WEBHOOK_ALERT and never raise."""

    def test_noop_without_webhook(self, monkeypatch):
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("DISCORD_WEBHOOK_ALERT", raising=False)
        posts = []
        monkeypatch.setattr(
            "notify_discord.requests.post", lambda *a, **k: posts.append(1) or _OkResponse()
        )
        assert send_alert(["- boom"]) is False  # harmless: nothing was ever going to be sent
        assert posts == []

    def test_sends_alert_embed_when_configured(self, monkeypatch):
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _OkResponse()

        monkeypatch.setattr("notify_discord.requests.post", fake_post)
        lines = ["- Scraper **PCCG** failed", "- Health check error: thing (ERROR): boom"]
        assert send_alert(lines) is True

        assert captured["url"] == "https://hook/alert"
        embed = captured["json"]["embeds"][0]
        assert embed["title"] == "Trackaroo alert — pipeline issue"
        assert embed["color"] == 0xFB923C
        assert "**PCCG**" in embed["description"]
        assert "boom" in embed["description"]

    def test_dry_run_prints_without_posting(self, monkeypatch, capsys):
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        posts = []
        monkeypatch.setattr(
            "notify_discord.requests.post", lambda *a, **k: posts.append(1) or _OkResponse()
        )

        assert send_alert(["- Scraper **Scorptec** failed"], dry_run=True) is True
        assert posts == []
        assert "pipeline issue" in capsys.readouterr().out

    def test_a_raising_post_is_reported_as_failure_not_success(self, monkeypatch, caplog):
        """Fix-round-1 I1: this used to be `# still counted as attempted` and
        return 1 -- i.e. a real webhook outage was silently reported as a
        successful send, so run_daily never released the same-day claim and
        the next hourly retry skipped resending it."""
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")

        def fake_post(url, json=None, timeout=None):
            raise requests.RequestException("boom")

        monkeypatch.setattr("notify_discord.requests.post", fake_post)
        assert send_alert(["- boom"]) is False
        assert "Discord webhook failed" in caplog.text

    def test_a_non_2xx_status_is_reported_as_failure_not_success(self, monkeypatch, caplog):
        """Fix-round-1 I1: the non-raising failure mode (a real Discord 5xx) --
        requests.post returns normally, raise_for_status() is what raises."""
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://hook/alert")
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: _ErrorResponse())

        assert send_alert(["- boom"]) is False
        assert "Discord webhook failed" in caplog.text


# ── run ──────────────────────────────────────────────────────────────

class TestRun:
    def _seed_file_db(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS products ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, brand TEXT, model TEXT,"
            " variant TEXT, tracked INTEGER DEFAULT 1)"
        )
        # Full schema comes from the db_path fixture; this is a no-op fallback.
        conn.close()
        return db_path

    def test_noop_without_webhook(self, monkeypatch, db_path):
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        posts = []
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: posts.append(1) or _OkResponse())
        assert run(db_path=str(db_path)) == 0
        assert posts == []

    def test_sends_all_categories_to_the_single_webhook(self, monkeypatch, db_path):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, category="gpu", brand="NVIDIA", model="RTX 5070", snapshots=[("2026-08-10", 999, "in_stock"), ("2026-08-11", 1049, "in_stock")])
        _seed_listing(conn, category="cpu", model="CPU Up", url="https://x.com/2", snapshots=[("2026-08-10", 100, "in_stock"), ("2026-08-11", 110, "in_stock")])
        conn.close()

        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/digest")
        posts = []
        monkeypatch.setattr(
            "notify_discord.requests.post",
            lambda url, json=None, timeout=None: posts.append((url, json)) or _OkResponse(),
        )

        count = run(db_path=str(db_path))
        assert count == 2
        urls = {u for u, _ in posts}
        assert urls == {"https://hook/digest"}
        titles = {j["embeds"][0]["title"] for _, j in posts}
        assert "GPU price ups" in titles
        assert "CPU price ups" in titles

    def test_dry_run_prints_embeds_without_posting(self, monkeypatch, db_path, capsys):
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, category="gpu", brand="NVIDIA", model="RTX 5070", snapshots=[("2026-08-10", 999, "in_stock"), ("2026-08-11", 1049, "in_stock")])
        conn.close()

        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/digest")
        posts = []
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: posts.append(1) or _OkResponse())

        run(db_path=str(db_path), dry_run=True)
        out = capsys.readouterr().out
        assert "GPU price ups" in out
        assert posts == []

    def test_test_mode_sends_sample_to_the_webhook(self, monkeypatch, db_path):
        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/digest")
        posts = []
        monkeypatch.setattr(
            "notify_discord.requests.post",
            lambda url, json=None, timeout=None: posts.append((url, json)) or _OkResponse(),
        )

        count = run(db_path=str(db_path), test=True)
        assert count == 1
        assert {u for u, _ in posts} == {"https://hook/digest"}
        assert all("Test — Trackaroo digest" in j["embeds"][0]["title"] for _, j in posts)

    def test_a_failed_send_is_not_counted_as_delivered(self, monkeypatch, db_path):
        """Fix-round-1 I1: run() used to count an embed as "sent" the moment it
        was attempted, regardless of whether Discord actually accepted it."""
        conn = sqlite3.connect(str(db_path))
        _seed_listing(conn, category="gpu", brand="NVIDIA", model="RTX 5070", snapshots=[("2026-08-10", 999, "in_stock"), ("2026-08-11", 1049, "in_stock")])
        conn.close()

        monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook/digest")
        monkeypatch.setattr("notify_discord.requests.post", lambda *a, **k: _ErrorResponse())

        assert run(db_path=str(db_path)) == 0


def os_environ(key):
    import os
    return os.environ.get(key)

def test_retailer_labels_cover_all_six_planned_retailers():
    """The digest prints raw slugs for any retailer missing a label."""
    from notify_discord import RETAILER_LABELS

    for slug in ("scorptec", "pccg", "mwave", "umart", "centrecom", "ple"):
        assert slug in RETAILER_LABELS, f"{slug} would print as a raw slug"
