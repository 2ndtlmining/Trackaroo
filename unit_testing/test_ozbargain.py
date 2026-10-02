"""OzBargain RSS feed parser (#34). Pure parsing; no network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ozbargain
from ozbargain import FEEDS, USER_AGENT, parse_feed, parse_price, parse_retailer

try:
    from zoneinfo import ZoneInfo

    MEL = ZoneInfo("Australia/Melbourne")
except Exception:  # no tzdata on Windows
    from datetime import timedelta, timezone

    MEL = timezone(timedelta(hours=10))

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=MEL)
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def gpu_items():
    text = (FIX / "ozbargain_video_card_feed.xml").read_text(encoding="utf-8")
    return {i.node_id: i for i in parse_feed(text, "gpu", NOW)}


@pytest.fixture
def cpu_items():
    text = (FIX / "ozbargain_cpu_feed.xml").read_text(encoding="utf-8")
    return parse_feed(text, "cpu", NOW)


def test_constants():
    assert [c for c, _ in FEEDS] == ["gpu", "cpu"]
    assert FEEDS[0][1] == "https://www.ozbargain.com.au/tag/video-card/feed"
    assert FEEDS[1][1] == "https://www.ozbargain.com.au/tag/cpu/feed"
    assert USER_AGENT == "Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("$1,099 @ Mwave", 1099.0),
        ("$949.95 Delivered", 949.95),
        ("$529 (Was $649)", 529.0),
        ("$1,099 (was $1,299) @ X", 1099.0),
        ("$899.95 @ Y", 899.95),
        ("10% off", None),
        ("10% off Graphics Cards @ Scorptec", None),
        ("$0", None),
        ("$0.00 freebie", None),
        ("no price", None),
        ("$50 off RTX 5070 Ti @ Mwave", None),
        ("$50 off, now $899 @ X", 899.0),
        ("Save $100: RTX 5070 $899 @ X", 899.0),
        ("Saving $100 on RTX 5070 $899 @ X", 899.0),
        ("$30 Cashback on Ryzen 7 9800X3D $689 @ PCCG", 689.0),
        ("$20 gift card with RTX 5070 $899", 899.0),
        ("RTX 5070 US$549 / A$899 @ Amazon", 899.0),
        ("US$549 @ Newegg", None),
        ("NZ$599 @ PB Tech", None),
        ("A$1,099", 1099.0),
        ("AU$1,099", 1099.0),
        ("$1099", 1099.0),
        ("$1,099.00", 1099.0),
    ],
)
def test_parse_price(title, expected):
    assert parse_price(title) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("RTX 5070 $1,099 @ Mwave", "Mwave"),
        ("RTX 5070 $5 @  Amazon AU  ", "Amazon AU"),
        ("A @ B @ Centre Com", "Centre Com"),
        ("No retailer $5", None),
        ("Foo@Bar $5", None),
    ],
)
def test_parse_retailer(title, expected):
    assert parse_retailer(title) == expected


def test_gpu_feed_basics(gpu_items):
    assert len(gpu_items) == 9
    assert sorted(gpu_items) == list(range(912001, 912010))
    a = gpu_items[912001]
    assert a.url == "https://www.ozbargain.com.au/node/912001"
    assert a.category == "gpu"
    assert a.price_aud == 1099.0
    assert a.retailer == "Mwave"
    assert (a.votes_pos, a.votes_neg, a.comment_count) == (42, 1, 15)
    assert a.posted_at == "2026-10-03T09:12:00+10:00"
    assert a.expires_at == "2026-10-04T23:59:00+10:00"
    assert a.starts_at is None
    assert a.expired is False
    assert a.product_slugs == ["nvidia-geforce-rtx-5070-ti"]


def test_odd_titles(gpu_items):
    assert gpu_items[912002].price_aud == 529.0  # first amount wins
    assert gpu_items[912003].price_aud == 949.95
    assert gpu_items[912005].price_aud is None
    assert gpu_items[912005].retailer == "Scorptec"
    assert gpu_items[912002].product_slugs == []


def test_votes_negative(gpu_items):
    f = gpu_items[912006]
    assert (f.votes_pos, f.votes_neg) == (2, 7)


def test_expired_by_title_msg(gpu_items):
    assert gpu_items[912003].expired is True


def test_expired_by_past_expiry(gpu_items):
    i = gpu_items[912009]
    assert i.expires_at == "2026-10-02T23:59:00+10:00"
    assert i.expired is True


def test_naive_expiry_treated_as_melbourne(gpu_items):
    i = gpu_items[912002]
    assert i.expires_at == "2026-10-10T23:59:00"
    assert i.expired is False


def test_naive_past_expiry_is_expired():
    xml = (
        '<rss version="2.0" xmlns:ozb="https://www.ozbargain.com.au"><channel><item>'
        "<title>X $5 @ Y</title><link>https://www.ozbargain.com.au/node/1</link>"
        '<ozb:meta expiry="2026-10-03T11:59:00"/></item></channel></rss>'
    )
    assert parse_feed(xml, "gpu", NOW)[0].expired is True


def test_future_start(gpu_items):
    i = gpu_items[912007]
    assert i.starts_at == "2026-10-05T09:00:00+10:00"
    assert i.expired is False


def test_missing_meta(gpu_items):
    i = gpu_items[912008]
    assert (i.votes_pos, i.votes_neg, i.comment_count) == (0, 0, 0)
    assert i.expires_at is None
    assert i.starts_at is None
    assert i.expired is False
    assert i.price_aud == 1599.0


def test_no_goto_urls(gpu_items, cpu_items):
    for i in list(gpu_items.values()) + cpu_items:
        for v in vars(i).values():
            assert "/goto/" not in str(v)


def test_cpu_feed(cpu_items):
    assert len(cpu_items) == 3
    assert all(i.category == "cpu" for i in cpu_items)
    assert cpu_items[0].price_aud == 689.0
    assert cpu_items[0].retailer == "PCCG"
    assert cpu_items[1].price_aud == 399.0
    assert cpu_items[1].retailer == "Amazon AU"
    assert [i.expired for i in cpu_items] == [False, False, True]


def test_guid_fallback_and_skip():
    xml = (
        '<rss version="2.0"><channel>'
        '<item><title>A $5</title><guid isPermaLink="false">777 at https://x</guid></item>'
        "<item><title>B $5</title></item>"
        "</channel></rss>"
    )
    items = parse_feed(xml, "gpu", NOW)
    assert [i.node_id for i in items] == [777]
    assert items[0].url == "https://www.ozbargain.com.au/node/777"


@pytest.mark.parametrize(
    "bad", ["<html>blocked</html>", "<rss><channel><item>", "", "not xml at all"]
)
def test_malformed_raises_value_error(bad):
    with pytest.raises(ValueError, match="gpu"):
        parse_feed(bad, "gpu", NOW)


def test_html_not_rss_raises():
    # well-formed XML that is not a feed must not silently yield "ok, zero items"
    with pytest.raises(ValueError, match="cpu"):
        parse_feed("<html>blocked</html>", "cpu", NOW)


def test_naive_now_is_normalised_to_melbourne():
    xml = (
        '<rss version="2.0" xmlns:ozb="https://www.ozbargain.com.au"><channel><item>'
        "<title>X $5 @ Y</title><link>https://www.ozbargain.com.au/node/1</link>"
        '<ozb:meta expiry="2026-10-03T11:59:00"/></item></channel></rss>'
    )
    items = parse_feed(xml, "gpu", datetime(2026, 10, 3, 12, 0))
    assert items[0].expired is True


def test_naive_expiry_uses_melbourne_dst():
    # DST started 2026-10-04: Melbourne is +11 on 10-10, so 00:30 local is 13:30Z the day before
    xml = (
        '<rss version="2.0" xmlns:ozb="https://www.ozbargain.com.au"><channel><item>'
        "<title>X $5 @ Y</title><link>https://www.ozbargain.com.au/node/1</link>"
        '<ozb:meta expiry="2026-10-10T00:30:00"/></item></channel></rss>'
    )
    from datetime import timezone as tz

    now = datetime(2026, 10, 9, 13, 45, tzinfo=tz.utc)  # 00:45 Melbourne (+11)
    assert parse_feed(xml, "gpu", now)[0].expired is True


# ---------------------------------------------------------------- Task 2: poll
import dataclasses  # noqa: E402
import logging  # noqa: E402
import sqlite3  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

TRACKED = [
    ("gpu", "NVIDIA", "RTX 5070 Ti", 16), ("gpu", "NVIDIA", "RTX 5060 Ti", 8),
    ("gpu", "NVIDIA", "RTX 5060 Ti", 16), ("gpu", "NVIDIA", "RTX 5080", 16),
    ("gpu", "NVIDIA", "RTX 5070", 12), ("gpu", "AMD", "RX 9060 XT", 16),
    ("cpu", "AMD", "Ryzen 7 9800X3D", None),
]


def _mk_db(path=":memory:"):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).parent.parent / "db" / "schema.sql").read_text(encoding="utf-8"))
    for cat, brand, model, vram in TRACKED:
        conn.execute("INSERT INTO products (category, brand, model, vram_gb) VALUES (?,?,?,?)", (cat, brand, model, vram))
    conn.execute("INSERT INTO products (category, brand, model, vram_gb, tracked) VALUES ('gpu','NVIDIA','RTX 5050',8,0)")
    conn.commit()
    return conn


def _pid(conn, model):
    return conn.execute("SELECT id FROM products WHERE model=?", (model,)).fetchone()[0]


@pytest.fixture
def mdb():
    return _mk_db()


def test_match_items(mdb, gpu_items, cpu_items):
    m = ozbargain.build_matchers(mdb)
    assert set(m) == {"gpu", "cpu"}
    assert ozbargain.match_item(gpu_items[912001], m) == _pid(mdb, "RTX 5070 Ti")
    assert ozbargain.match_item(gpu_items[912002], m) is None  # 8GB vs 16GB ambiguous
    assert ozbargain.match_item(gpu_items[912004], m) is None  # prebuilt
    assert ozbargain.match_item(gpu_items[912008], m) == _pid(mdb, "RTX 5080")
    assert ozbargain.match_item(gpu_items[912009], m) is None  # untracked RTX 5050
    assert ozbargain.match_item(cpu_items[0], m) == _pid(mdb, "Ryzen 7 9800X3D")


def test_match_slug_fallback(mdb, gpu_items):
    m = ozbargain.build_matchers(mdb)
    item = dataclasses.replace(gpu_items[912001], title="ASUS Prime 16GB $1,099 @ Mwave",
                               product_slugs=["nvidia-geforce-rtx-5070-ti"])
    assert ozbargain.match_item(item, m) == _pid(mdb, "RTX 5070 Ti")


def _deals(conn):
    return {r["node_id"]: r for r in conn.execute("SELECT * FROM ozb_deals")}


def test_upsert_idempotent_and_keeps(mdb, gpu_items):
    item = gpu_items[912001]
    pid = _pid(mdb, "RTX 5070 Ti")
    ozbargain.upsert_items(mdb, [item], [pid], "2026-10-03T10:00:00")
    mdb.execute("UPDATE ozb_deals SET alerted_at='2026-10-03T10:01:00'")
    newer = dataclasses.replace(item, votes_pos=99, votes_neg=3, expired=True)
    ozbargain.upsert_items(mdb, [newer], [None], "2026-10-03T12:00:00")
    rows = _deals(mdb)
    assert len(rows) == 1
    r = rows[912001]
    assert (r["votes_pos"], r["votes_neg"], r["expired"]) == (99, 3, 1)
    assert r["first_seen_at"] == "2026-10-03T10:00:00"
    assert r["last_seen_at"] == "2026-10-03T12:00:00"
    assert r["alerted_at"] == "2026-10-03T10:01:00"
    assert r["product_id"] == pid


def test_prune(mdb, gpu_items):
    iso = lambda d: (NOW - timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
    ozbargain.upsert_items(mdb, [gpu_items[912001]], [None], iso(181))
    ozbargain.upsert_items(mdb, [gpu_items[912008]], [None], iso(179))
    mdb.execute("INSERT INTO ozb_polls VALUES (?,1,0,NULL)", (iso(31),))
    mdb.execute("INSERT INTO ozb_polls VALUES (?,1,0,NULL)", (iso(29),))
    ozbargain.prune(mdb, NOW)
    assert set(_deals(mdb)) == {912008}
    assert mdb.execute("SELECT COUNT(*) FROM ozb_polls").fetchone()[0] == 1


# --- run()
def _resp(text="", status=200):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if status >= 400:
        r.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return r


def _ok_gpu():
    return _resp((FIX / "ozbargain_video_card_feed.xml").read_text(encoding="utf-8"))


def _ok_cpu():
    return _resp((FIX / "ozbargain_cpu_feed.xml").read_text(encoding="utf-8"))


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    path = tmp_path / "run.db"
    _mk_db(path).close()
    calls = []

    def install(gpu, cpu):
        def fake_get(url, **kw):
            calls.append((url, kw))
            out = gpu if url == FEEDS[0][1] else cpu
            if isinstance(out, Exception):
                raise out
            return out
        monkeypatch.setattr(ozbargain.requests, "get", fake_get)
    return path, calls, install


def _polls(path):
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    try:
        return c.execute("SELECT * FROM ozb_polls").fetchall(), c.execute("SELECT COUNT(*) FROM ozb_deals").fetchone()[0]
    finally:
        c.close()


def test_run_both_ok_and_budget(run_env):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    res = ozbargain.run(db_path=path, now=NOW)
    assert [c[0] for c in calls] == [u for _, u in FEEDS]
    for _, kw in calls:
        assert kw["timeout"] == 10
        assert kw["headers"]["User-Agent"] == USER_AGENT
    assert res["ok"] and res["items"] == 12 and res["matched"] == 5 and res["errors"] == []
    polls, n = _polls(path)
    assert n == 12 and len(polls) == 1 and polls[0]["ok"] == 1 and polls[0]["items"] == 12


@pytest.mark.parametrize("bad", [RuntimeError("boom"), _resp(status=403), _resp("<html><body>blocked</body></html>")])
def test_run_one_feed_down(run_env, bad, caplog):
    path, calls, install = run_env
    install(_ok_gpu(), bad)
    with caplog.at_level(logging.WARNING):
        res = ozbargain.run(db_path=path, now=NOW)
    assert res["ok"] and res["items"] == 9 and len(res["errors"]) == 1
    assert any(r.levelno == logging.WARNING and "cpu" in r.getMessage() for r in caplog.records)
    polls, n = _polls(path)
    assert polls[0]["ok"] == 1 and n == 9


def test_run_both_fail(run_env):
    path, calls, install = run_env
    install(RuntimeError("a"), _resp(status=403))
    res = ozbargain.run(db_path=path, now=NOW)
    assert not res["ok"] and res["items"] == 0 and len(res["errors"]) == 2
    polls, n = _polls(path)
    assert polls[0]["ok"] == 0 and polls[0]["error"] and n == 0


def test_run_dry_run_writes_nothing(run_env):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    res = ozbargain.run(db_path=path, dry_run=True, now=NOW)
    assert res["ok"] and res["matched"] == 5
    assert _polls(path) == ([], 0)


def test_cli_dry_run_prints_matches(run_env, monkeypatch, capsys):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    monkeypatch.setattr(ozbargain, "DB_PATH", path)
    monkeypatch.setattr("config.setup_logging", lambda *a, **k: None)
    ozbargain.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "912001" in out and "913001" in out and "912004" not in out
    assert _polls(path) == ([], 0)


def test_run_dry_run_creates_no_tables(tmp_path, monkeypatch):
    path = tmp_path / "bare.db"
    c = _mk_db(path)
    c.execute("DROP TABLE ozb_polls")
    c.execute("DROP TABLE ozb_deals")
    c.commit()
    c.close()
    monkeypatch.setattr(ozbargain.requests, "get",
                        lambda url, **kw: _ok_gpu() if url == FEEDS[0][1] else _ok_cpu())
    ozbargain.run(db_path=path, dry_run=True, now=NOW)
    c = sqlite3.connect(str(path))
    assert not list(c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'ozb_%'"))
    c.close()


def test_run_resolves_db_path_at_call_time(tmp_path, monkeypatch):
    path = tmp_path / "late.db"
    _mk_db(path).close()
    monkeypatch.setattr(ozbargain, "DB_PATH", path)
    monkeypatch.setattr(ozbargain.requests, "get",
                        lambda url, **kw: _ok_gpu() if url == FEEDS[0][1] else _ok_cpu())
    ozbargain.run(now=NOW)
    assert _polls(path)[1] == 12


# --- alerts wiring (#34 task 3)
def test_run_calls_send_alerts_on_ok(run_env, monkeypatch):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    seen = []
    monkeypatch.setattr("ozbargain_alerts.send_alerts", lambda conn, now: seen.append(now))
    ozbargain.run(db_path=path, now=NOW)
    assert seen == [NOW]


def test_run_no_alerts_on_failed_poll_or_dry_run(run_env, monkeypatch):
    path, calls, install = run_env
    monkeypatch.setattr("ozbargain_alerts.send_alerts", lambda *a: pytest.fail("alerted"))
    install(RuntimeError("a"), _resp(status=403))
    ozbargain.run(db_path=path, now=NOW)
    install(_ok_gpu(), _ok_cpu())
    ozbargain.run(db_path=path, dry_run=True, now=NOW)


def test_run_survives_alert_failure(run_env, monkeypatch):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr("ozbargain_alerts.send_alerts", boom)
    assert ozbargain.run(db_path=path, now=NOW)["ok"]


# --- R8 live rule (final review C1)
def _live(**kw):
    d = dict(expired=0, starts_at=None, expires_at=None, last_seen_at=NOW.isoformat())
    d.update(kw)
    return ozbargain.is_live(d, NOW)


def test_is_live_basic_and_expired_flag():
    assert _live()
    assert not _live(expired=1)


def test_is_live_start_and_expiry():
    assert not _live(starts_at="2026-10-03T13:00:00+10:00")
    assert _live(starts_at="2026-10-03T11:00:00+10:00")
    assert not _live(expires_at="2026-10-03T11:00:00+10:00")
    assert not _live(expires_at="2026-10-03T12:00:00+10:00")  # == now is over
    assert _live(expires_at="2026-10-03T13:00:00+10:00")
    assert _live(starts_at="garbage", expires_at="garbage")  # unparseable = absent


def test_is_live_last_seen_window():
    assert _live(last_seen_at=(NOW - timedelta(days=6)).isoformat())
    assert _live(last_seen_at=(NOW - timedelta(days=7)).isoformat())
    assert not _live(last_seen_at=(NOW - timedelta(days=8)).isoformat())
    assert not _live(last_seen_at=None)
    assert not _live(last_seen_at="garbage")


# --- upsert follows a re-match (M4)
def test_upsert_follows_rematch_but_null_keeps(mdb, gpu_items):
    item = gpu_items[912001]
    a, b = _pid(mdb, "RTX 5070 Ti"), _pid(mdb, "RTX 5080")
    ozbargain.upsert_items(mdb, [item], [a], "2026-10-03T10:00:00")
    ozbargain.upsert_items(mdb, [item], [b], "2026-10-03T12:00:00")
    assert _deals(mdb)[912001]["product_id"] == b
    ozbargain.upsert_items(mdb, [item], [None], "2026-10-03T14:00:00")
    assert _deals(mdb)[912001]["product_id"] == b


# --- restart guard (M5)
def test_run_skips_within_90_minutes(run_env, caplog):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    ozbargain.run(db_path=path, now=NOW)
    assert len(calls) == 2
    with caplog.at_level(logging.INFO):
        res = ozbargain.run(db_path=path, now=NOW + timedelta(minutes=89))
    assert len(calls) == 2 and res["ok"] is False and res.get("skipped")
    assert any("skip" in r.getMessage().lower() for r in caplog.records)
    assert len(_polls(path)[0]) == 1


def test_run_polls_after_91_minutes(run_env):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    ozbargain.run(db_path=path, now=NOW)
    res = ozbargain.run(db_path=path, now=NOW + timedelta(minutes=91))
    assert len(calls) == 4 and res["ok"] and len(_polls(path)[0]) == 2


def test_run_guard_compares_datetimes_across_offsets(run_env):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    ozbargain.run(db_path=path, now=NOW)  # 12:00 +10
    # 02:30 UTC == 12:30 +10, 30 minutes later though the string sorts earlier
    ozbargain.run(db_path=path, now=datetime(2026, 10, 3, 2, 30, tzinfo=timezone.utc))
    assert len(calls) == 2


def test_run_dry_run_ignores_guard(run_env):
    path, calls, install = run_env
    install(_ok_gpu(), _ok_cpu())
    ozbargain.run(db_path=path, now=NOW)
    ozbargain.run(db_path=path, dry_run=True, now=NOW + timedelta(minutes=5))
    assert len(calls) == 4
