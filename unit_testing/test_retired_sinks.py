"""Retired watchlist rows are matched as sinks and dropped by every scraper (#18)."""
import logging

import pytest

from scraper import pccg, scorptec, umart

TRACKED = [{"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 3060", "gen_tier": "current-2",
            "vram_gb": 12, "cores": None, "tracked": True}]
RETIRED = [{"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 3060 Ti", "gen_tier": "current-2",
            "vram_gb": 8, "cores": None, "tracked": False}]

TI = "Gigabyte GeForce RTX 3060 Ti Gaming OC 8GB"
BASE = "Gigabyte GeForce RTX 3060 Gaming OC 12GB"
DROP_LOG = "dropped 1 listing(s) matched to retired products"


def _card(name, n):
    return {"name": name, "price_aud": 500.0 + n, "stock_status": "in_stock",
            "url": f"https://x/{n}", "retailer_sku": f"sku{n}", "full_description": ""}


def _run_umart(monkeypatch, retired):
    monkeypatch.setattr(umart, "scrape_all_pages", lambda *a, **k: [_card(TI, 1), _card(BASE, 2)])
    results, matched, _ = umart.scrape_umart(TRACKED, only_category="gpu", retired=retired)
    return results, matched


def _run_scorptec(monkeypatch, retired):
    # Scorptec walks several GPU sub-category URLs; serve the cards for one only.
    monkeypatch.setattr(scorptec, "scrape_all_pages",
                        lambda url, **k: [_card(TI, 1), _card(BASE, 2)] if url.endswith("nvidia") else [])
    results, matched, _ = scorptec.scrape_scorptec(TRACKED, only_category="gpu", retired=retired)
    return results, matched


def _run_pccg(monkeypatch, retired):
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda *a, **k: [
        {"name": TI, "price": 501, "url": "/p/1", "stock_status": "in_stock"},
        {"name": BASE, "price": 502, "url": "/p/2", "stock_status": "in_stock"},
    ])
    results, matched, _ = pccg.scrape_category("gpu", TRACKED, retired=retired)
    return results, matched


RUNNERS = [(_run_umart, "scraper.umart"), (_run_scorptec, "scraper.scorptec"), (_run_pccg, "scraper.pccg")]


@pytest.mark.parametrize("runner,logger_name", RUNNERS)
def test_retired_chip_is_a_sink_not_a_sibling_match(monkeypatch, caplog, runner, logger_name):
    with caplog.at_level(logging.INFO):
        results, matched = runner(monkeypatch, RETIRED)
    assert [r["watchlist_model"] for r in results] == ["GeForce RTX 3060"]
    assert all(r["watchlist_gen_tier"] for r in results)
    assert matched == {0}
    assert DROP_LOG in caplog.text


@pytest.mark.parametrize("runner,logger_name", RUNNERS)
def test_no_retired_rows_means_no_drop_log(monkeypatch, caplog, runner, logger_name):
    with caplog.at_level(logging.INFO):
        results, _ = runner(monkeypatch, ())
    assert [r["watchlist_model"] for r in results] == ["GeForce RTX 3060"]
    assert "retired products" not in caplog.text


def test_discover_treats_retired_chips_as_known_not_new_or_tracked():
    import discover
    from scraper.chip_key import Matcher

    wl = TRACKED + RETIRED
    env = [{"category": "gpu", "retailer": "umart", "items": [
        {"title": TI, "url": "https://x/1", "price_aud": 500.0},
        {"title": "Gigabyte GeForce RTX 3060 Ti Gaming OC", "url": "https://x/2", "price_aud": 510.0},
    ]}]
    groups, tracked, _ = discover._classify(env, Matcher(wl), wl)
    assert groups == {}      # not a new part
    assert tracked == set()  # and not flipped to 'tracked'
