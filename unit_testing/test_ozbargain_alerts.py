"""OzBargain Discord alerts (#34). send_embed is always mocked; no network."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ozbargain_alerts as oa

MEL = timezone(timedelta(hours=10))
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=MEL)
TODAY, YESTERDAY = "2026-10-03", "2026-10-02"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TRACKAROO_PUBLIC_BASE_URL", raising=False)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((Path(__file__).parent.parent / "db" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO products (id, category, brand, model, vram_gb) VALUES (1,'gpu','NVIDIA','RTX 5070 Ti',16)")
    conn.execute("INSERT INTO products (id, category, brand, model) VALUES (2,'cpu','AMD','Ryzen 7 9800X3D')")
    conn.commit()
    return conn


_lid = [0]


def snap(conn, pid=1, price=1199.0, retailer="pccg", date=TODAY, stock="in_stock",
         variant="Card", url=None):
    _lid[0] += 1
    conn.execute("INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url)"
                 " VALUES (?,?,?,?,?)", (_lid[0], pid, retailer, variant, url or f"https://x/{_lid[0]}"))
    conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
                 " VALUES (?,?,?,?)", (_lid[0], date, price, stock))
    conn.commit()


_nid = [1000]


def deal(conn, **kw):
    _nid[0] += 1
    d = dict(node_id=_nid[0], category="gpu", title="t", url=f"https://www.ozbargain.com.au/node/{_nid[0]}",
             price_aud=1099.0, retailer="Mwave", votes_pos=42, votes_neg=1, comment_count=0,
             posted_at=None, starts_at=None, expires_at=None, expired=0, product_id=1,
             first_seen_at="x", last_seen_at="x", alerted_at=None)
    d.update(kw)
    cols = ",".join(d)
    conn.execute(f"INSERT INTO ozb_deals ({cols}) VALUES ({','.join('?' * len(d))})", list(d.values()))
    conn.commit()
    return d["node_id"]


# --- best_in_stock
def test_best_min_in_stock_latest_date(db):
    snap(db, price=1299, retailer="scorptec")
    snap(db, price=1199, retailer="pccg")
    assert oa.best_in_stock(db, 1) == (1199.0, "pccg")


def test_best_ignores_oos_and_old(db):
    snap(db, price=1000, retailer="umart", stock="out_of_stock")
    snap(db, price=900, retailer="mwave", date=YESTERDAY)
    snap(db, price=1250, retailer="pccg")
    assert oa.best_in_stock(db, 1) == (1250.0, "pccg")


@pytest.mark.parametrize("variant,url", [
    ("Gaming Bundle", None), ("Card + combo", None), ("Card", "https://x/some-bundle-deal"),
    ("Card", "https://x/bdl-123")])
def test_best_ignores_bundles(db, variant, url):
    snap(db, price=800, variant=variant, url=url)
    snap(db, price=1250, retailer="scorptec")
    assert oa.best_in_stock(db, 1) == (1250.0, "scorptec")


def test_best_ignores_delisted(db):
    snap(db, price=900, retailer="umart")
    db.execute("UPDATE retailer_listings SET status='delisted'")
    snap(db, price=1250, retailer="pccg")
    assert oa.best_in_stock(db, 1) == (1250.0, "pccg")


def test_best_none_when_product_older_than_global_latest(db):
    snap(db, pid=1, price=1000, date=YESTERDAY)
    snap(db, pid=2, price=500, date=TODAY)
    assert oa.best_in_stock(db, 1) is None


def test_best_none_when_nothing_in_stock(db):
    snap(db, stock="out_of_stock")
    assert oa.best_in_stock(db, 1) is None
    assert oa.best_in_stock(db, 2) is None


# --- alert_candidates
def ids(db):
    return [c["node_id"] for c in oa.alert_candidates(db, NOW)]


def test_qualifying_included(db):
    snap(db)
    n = deal(db)
    assert ids(db) == [n]
    c = oa.alert_candidates(db, NOW)[0]
    assert c["best_price"] == 1199.0 and c["best_retailer"] == "pccg"
    assert c["product_name"] == "NVIDIA RTX 5070 Ti 16GB"


def test_price_equal_excluded_one_cent_below_included(db):
    snap(db, price=1199.0)
    deal(db, price_aud=1199.0)
    below = deal(db, price_aud=1198.99)
    assert ids(db) == [below]


def test_votes(db):
    snap(db)
    deal(db, votes_pos=1, votes_neg=2)
    zero = deal(db, votes_pos=3, votes_neg=3)
    assert ids(db) == [zero]


@pytest.mark.parametrize("kw", [
    {"expired": 1}, {"starts_at": "2026-10-03T18:00:00+10:00"}, {"price_aud": None},
    {"product_id": None}, {"alerted_at": "2026-10-03T10:00:00+10:00"}])
def test_exclusions(db, kw):
    snap(db)
    deal(db, **kw)
    assert ids(db) == []


@pytest.mark.parametrize("starts,included", [
    ("2026-10-03T13:00:00", False),            # no tz = Melbourne, future
    ("2026-10-03T11:00:00", True),
    ("2026-10-03T03:00:00Z", False),           # 13:00 +10, future
    ("2026-10-03T01:00:00Z", True),
    ("2026-10-03T13:00:00+11:00", True),       # == 12:00 +10 == now, not future
    ("2026-10-03T14:00:00+11:00", False),      # 13:00 +10, one hour ahead
    ("2026-10-03T12:00:00+11:00", True),       # 11:00 +10, past
    ("garbage", True),
])
def test_starts_at_offsets(db, starts, included):
    snap(db)
    n = deal(db, starts_at=starts)
    assert (ids(db) == [n]) is included


def test_past_start_included(db):
    snap(db)
    n = deal(db, starts_at="2026-10-03T08:00:00+10:00")
    assert ids(db) == [n]


def test_no_best_included_and_last(db):
    snap(db, pid=1, price=1199)
    nobest = deal(db, product_id=2, category="cpu", price_aud=500)
    with_best = deal(db, price_aud=1190)
    assert ids(db) == [with_best, nobest]
    assert oa.alert_candidates(db, NOW)[1]["best_price"] is None


def test_cap_and_order(db):
    snap(db, price=1000)
    for p in (990, 900, 950, 800, 970, 850, 999):
        deal(db, price_aud=p)
    got = oa.alert_candidates(db, NOW)
    assert len(got) == oa.MAX_ALERTS_PER_POLL == 5
    assert [c["price_aud"] for c in got] == [800, 850, 900, 950, 970]


# --- send_alerts
def alerted(db):
    return [r[0] for r in db.execute("SELECT alerted_at FROM ozb_deals ORDER BY node_id")]


def test_send_no_webhook(db, monkeypatch):
    snap(db)
    deal(db)
    monkeypatch.setattr("notify_discord.send_embed", lambda *a: pytest.fail("sent"))
    assert oa.send_alerts(db, NOW) == 0
    assert alerted(db) == [None]


def test_send_success_marks(db, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook")
    snap(db)
    deal(db)
    deal(db)
    sent = []
    monkeypatch.setattr("notify_discord.send_embed", lambda url, e: sent.append((url, e)) or True)
    assert oa.send_alerts(db, NOW) == 2
    assert alerted(db) == [NOW.isoformat(timespec="seconds")] * 2
    assert sent[0][0] == "https://hook"
    assert oa.send_alerts(db, NOW) == 0


def test_send_false_retries(db, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook")
    snap(db)
    deal(db)
    monkeypatch.setattr("notify_discord.send_embed", lambda *a: False)
    assert oa.send_alerts(db, NOW) == 0
    assert alerted(db) == [None]
    monkeypatch.setattr("notify_discord.send_embed", lambda *a: True)
    assert oa.send_alerts(db, NOW) == 1


def test_send_raise_caught(db, monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://hook")
    snap(db)
    deal(db, price_aud=900)
    deal(db, price_aud=950)
    calls = []

    def fake(url, e):
        calls.append(e)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return True
    monkeypatch.setattr("notify_discord.send_embed", fake)
    with caplog.at_level("WARNING"):
        assert oa.send_alerts(db, NOW) == 1
    assert len(calls) == 2 and "failed" in caplog.text
    assert alerted(db)[0] is None and alerted(db)[1] is not None


# --- build_embed
def cand(**kw):
    c = dict(node_id=5, product_id=1, product_name="NVIDIA RTX 5070 Ti 16GB", price_aud=1099.0,
             retailer="Mwave", votes_pos=42, votes_neg=1, url="https://www.ozbargain.com.au/node/5",
             best_price=1199.0, best_retailer="pccg")
    c.update(kw)
    return c


def test_embed_full():
    e = oa.build_embed(cand(), "https://t.example")
    assert e["title"] == "OzBargain: NVIDIA RTX 5070 Ti 16GB $1,099 at Mwave"
    assert "Our best today: $1,199 at PCCG" in e["description"]
    assert "+42 / −1 votes" in e["description"]
    assert "https://www.ozbargain.com.au/node/5" in e["description"]
    assert "https://t.example/product/1" in e["description"]
    assert "/goto/" not in str(e)
    assert all(ord(ch) < 0x2190 or ord(ch) == 0x2212 for ch in e["title"] + e["description"])


def test_embed_no_best_no_base():
    e = oa.build_embed(cand(best_price=None, best_retailer=None), "")
    assert "Not in stock at our retailers" in e["description"]
    assert "/product/" not in e["description"]
