"""Ready-to-retire suggestions (#17): tracked products no retailer has listed lately."""
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import retire_suggest

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
TODAY = date(2026, 11, 1)  # 31 days after 2026-10-01, 29 after 2026-10-03


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def add(conn, model, created="2026-08-01", snaps=(), tracked=1, brand="NVIDIA", retailer="pccg"):
    """Insert a product with listings and snapshots; a snap is a date or (date, stock, retailer)."""
    pid = conn.execute(
        "INSERT INTO products (category, brand, model, tracked, created_at) VALUES ('gpu', ?, ?, ?, ?)",
        (brand, model, tracked, created + "T00:00:00.000Z"),
    ).lastrowid
    listings = {}
    for snap in snaps:
        d, stock, r = (snap, "in_stock", retailer) if isinstance(snap, str) else (tuple(snap) + (retailer,))[:3]
        if r not in listings:
            listings[r] = conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url) VALUES (?, ?, ?)",
                (pid, r, f"https://{r}.example/{model}"),
            ).lastrowid
        conn.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status)"
            " VALUES (?, ?, 100, ?)", (listings[r], d, stock),
        )
    conn.commit()
    return pid


def rows(conn):
    return {r["product_id"]: dict(r) for r in conn.execute("SELECT * FROM retire_suggestions")}


def test_flagged_after_31_days_without_a_snapshot(conn):
    a = add(conn, "A", snaps=["2026-10-01"])
    assert retire_suggest.update(conn, TODAY, 30) == [a]
    assert rows(conn)[a]["decision"] == "pending"
    assert rows(conn)[a]["first_flagged"] == "2026-11-01"
    assert rows(conn)[a]["last_seen"] == "2026-10-01"


def test_not_flagged_at_29_days(conn):
    add(conn, "B", snaps=["2026-10-03"])
    assert retire_suggest.update(conn, TODAY, 30) == []
    assert rows(conn) == {}


def test_out_of_stock_snapshot_counts_as_live(conn):
    add(conn, "C", snaps=[("2026-10-31", "out_of_stock")])
    assert retire_suggest.update(conn, TODAY, 30) == []


def test_young_product_never_listed_is_not_flagged(conn):
    add(conn, "D", created="2026-10-22", snaps=[])
    assert retire_suggest.update(conn, TODAY, 30) == []


def test_old_product_never_listed_is_flagged(conn):
    e = add(conn, "E", created="2026-08-01", snaps=[])
    assert retire_suggest.update(conn, TODAY, 30) == [e]
    assert rows(conn)[e]["last_seen"] is None
    assert rows(conn)[e]["last_seen_retailer"] is None


def test_untracked_and_holding_products_are_ignored(conn):
    add(conn, "F", tracked=0, snaps=["2026-09-01"])
    add(conn, "G", brand="Unmatched", snaps=["2026-09-01"])
    assert retire_suggest.find_stale(conn, TODAY, 30) == []
    assert retire_suggest.update(conn, TODAY, 30) == []


def test_live_again_removes_pending_and_kept_but_not_requested(conn):
    p = add(conn, "P", snaps=["2026-10-30"])
    k = add(conn, "K", snaps=["2026-10-30"])
    r = add(conn, "R", snaps=["2026-10-30"])
    conn.executemany(
        "INSERT INTO retire_suggestions (product_id, first_flagged, decision, keep_until)"
        " VALUES (?, '2026-10-01', ?, ?)",
        [(p, "pending", None), (k, "kept", "2026-12-01"), (r, "requested", None)],
    )
    conn.commit()
    assert retire_suggest.update(conn, TODAY, 30) == []
    assert list(rows(conn)) == [r]


def test_kept_reopens_after_keep_until_without_renotify(conn):
    k = add(conn, "K", snaps=["2026-09-01"])
    conn.execute(
        "INSERT INTO retire_suggestions (product_id, first_flagged, decision, keep_until, notified)"
        " VALUES (?, '2026-08-01', 'kept', '2026-10-31', 1)", (k,),
    )
    conn.commit()
    assert retire_suggest.update(conn, TODAY, 30) == []  # reopened, not newly flagged
    row = rows(conn)[k]
    assert (row["decision"], row["keep_until"], row["notified"]) == ("pending", None, 1)
    assert row["first_flagged"] == "2026-08-01"


def test_kept_stays_hidden_before_keep_until(conn):
    k = add(conn, "K", snaps=["2026-09-01"])
    conn.execute(
        "INSERT INTO retire_suggestions (product_id, first_flagged, decision, keep_until)"
        " VALUES (?, '2026-08-01', 'kept', '2026-11-30')", (k,),
    )
    conn.commit()
    retire_suggest.update(conn, TODAY, 30)
    assert rows(conn)[k]["decision"] == "kept"


def test_retired_product_row_is_deleted(conn):
    r = add(conn, "R", tracked=0, snaps=["2026-09-01"])
    conn.execute(
        "INSERT INTO retire_suggestions (product_id, first_flagged, decision) VALUES (?, '2026-10-01', 'requested')",
        (r,),
    )
    conn.commit()
    retire_suggest.update(conn, TODAY, 30)
    assert rows(conn) == {}


def test_last_seen_retailer_is_the_latest_snapshots_retailer(conn):
    s = add(conn, "S", snaps=[
        ("2026-09-10", "in_stock", "pccg"),
        ("2026-09-20", "in_stock", "umart"),
        ("2026-09-05", "in_stock", "mwave"),
    ])
    assert retire_suggest.find_stale(conn, TODAY, 30) == [
        {"product_id": s, "model": "S", "last_seen": "2026-09-20", "last_seen_retailer": "umart"}
    ]


def test_find_stale_is_ordered_by_model(conn):
    z = add(conn, "Zed", snaps=["2026-09-01"])
    a = add(conn, "Alpha", snaps=["2026-09-01"])
    assert [r["product_id"] for r in retire_suggest.find_stale(conn, TODAY, 30)] == [a, z]


def test_update_refreshes_last_seen_on_existing_rows(conn):
    a = add(conn, "A", snaps=["2026-09-01"])
    retire_suggest.update(conn, TODAY, 30)
    conn.execute("UPDATE price_snapshots SET snapshot_date = '2026-09-15'")
    conn.commit()
    assert retire_suggest.update(conn, TODAY, 30) == []
    assert rows(conn)[a]["last_seen"] == "2026-09-15"


@pytest.fixture
def discord(monkeypatch):
    import notify_discord
    sent = []
    outcome = {"ok": False}
    monkeypatch.setattr(notify_discord, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(
        notify_discord, "send_embed", lambda hook, embed: sent.append((hook, embed)) or outcome["ok"]
    )
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    monkeypatch.setenv("TRACKAROO_PUBLIC_BASE_URL", "https://trackaroo.test")
    return sent, outcome


def test_notify_sends_once_and_stamps_only_on_success(conn, discord):
    sent, outcome = discord
    a = add(conn, "A", snaps=["2026-10-01"])
    retire_suggest.update(conn, TODAY, 30)

    assert retire_suggest.notify_new(conn) == 0  # delivery fails
    assert rows(conn)[a]["notified"] == 0
    assert len(sent) == 1

    outcome["ok"] = True
    assert retire_suggest.notify_new(conn) == 1
    assert rows(conn)[a]["notified"] == 1
    assert len(sent) == 2

    assert retire_suggest.notify_new(conn) == 0  # nothing new, nothing sent
    assert len(sent) == 2


def test_notify_skips_without_webhook(conn, discord, monkeypatch):
    sent, outcome = discord
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")
    add(conn, "A", snaps=["2026-10-01"])
    retire_suggest.update(conn, TODAY, 30)
    assert retire_suggest.notify_new(conn) == 0
    assert sent == []


def test_notify_ignores_non_pending_rows(conn, discord):
    sent, outcome = discord
    outcome["ok"] = True
    k = add(conn, "K", snaps=["2026-09-01"])
    conn.execute(
        "INSERT INTO retire_suggestions (product_id, first_flagged, decision, keep_until)"
        " VALUES (?, '2026-10-01', 'kept', '2026-12-01')", (k,),
    )
    conn.commit()
    assert retire_suggest.notify_new(conn) == 0
    assert sent == []


def test_embed_has_no_emoji_and_links_discover():
    embed = retire_suggest.build_embed(
        [
            {"model": "RTX 3060", "last_seen": "2026-09-05", "last_seen_retailer": "pccg"},
            {"model": "RX 6600", "last_seen": None, "last_seen_retailer": None},
        ],
        "https://trackaroo.test/",
    )
    assert embed["title"] == "Ready to retire"
    assert embed["url"] == "https://trackaroo.test/discover"
    assert embed["color"] == 0x64748B
    lines = embed["description"].split("\n")
    assert lines[0].startswith("**RTX 3060**: last seen 5 Sep at ")
    assert lines[1] == "**RX 6600**: never listed"
    assert embed["description"].endswith("Retire or Keep each one on the Discover page.")
    assert re.search(r"[\U0001F000-\U0001FFFF☀-➿]", embed["title"] + embed["description"]) is None


def test_embed_without_base_url_has_no_link():
    assert "url" not in retire_suggest.build_embed([], "")


def test_run_skips_when_table_missing(tmp_path):
    db = tmp_path / "bare.db"
    sqlite3.connect(str(db)).close()
    assert retire_suggest.run(db_path=db, today=TODAY) == {"skipped": "no table"}


def test_run_updates_and_notifies(tmp_path, discord):
    sent, outcome = discord
    outcome["ok"] = True
    db = tmp_path / "run.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    add(c, "A", snaps=["2026-10-01"])
    c.close()

    summary = retire_suggest.run(notify=False, db_path=db, today=TODAY)
    assert summary["flagged"] == 1 and summary["notified"] == 0 and sent == []
    summary = retire_suggest.run(notify=True, db_path=db, today=TODAY)
    assert summary["flagged"] == 0 and summary["notified"] == 1 and len(sent) == 1
