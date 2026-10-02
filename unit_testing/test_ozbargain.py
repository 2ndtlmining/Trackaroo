"""OzBargain RSS feed parser (#34). Pure parsing; no network."""
from datetime import datetime
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
