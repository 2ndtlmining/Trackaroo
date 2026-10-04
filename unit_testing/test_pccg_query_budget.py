"""
Tests for the PCCG Algolia query budget — the root cause of the daily 429s.

PCCG's public search key carries ``"maxQueriesPerIPPerHour": 100`` (confirmed
against ``GET /1/keys/<key>`` on 27-Aug-2026). The scraper used to issue one
Algolia query per watchlist product per page; with 100 tracked products that
spent the entire hourly budget on page 0 alone, so most runs 429'd partway
through. Backoff could never fix it — the budget is a rolling ~60-minute
window (measured 27-Aug-2026: a heavy spend at 18:06 GMT was still 429ing at
19:01 GMT, after a fresh clock hour had begun), so waiting inside a run
cannot create quota.

The fix: pull each category whole with a single empty query
(``hitsPerPage`` up to Algolia's 1000 maximum) and match the watchlist against
it locally. Two categories = two queries per run.

These tests pin that budget so nobody reintroduces per-product searching.
"""
import json
import sys
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.pccg import algolia_fetch_catalogue, scrape_category


def _catalogue_response(hits, nb_pages=1):
    return {"results": [{"hits": hits, "nbPages": nb_pages, "nbHits": len(hits)}]}


def _hit(name, price, url, label="In stock"):
    return {
        "products_name": name,
        "products_price": price,
        "Product_URL": url,
        "manufacturers_name": name.split()[0],
        "indicator": {"label": label},
    }


def _count_queries(sent):
    """Total Algolia queries across every captured request body."""
    return sum(len(body["requests"]) for body in sent)


def _capture_post(responses):
    """Fake requests.post that records each request body and replays responses."""
    sent = []

    def _post(url, json=None, headers=None, timeout=None, **kwargs):
        sent.append(json)
        payload = responses[min(len(sent) - 1, len(responses) - 1)]
        resp = unittest.mock.Mock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = payload
        resp.text = globals()["json"].dumps(payload)
        return resp

    return _post, sent


# ── The budget itself ──────────────────────────────────────────────

def test_scrape_category_spends_exactly_one_query_per_category(monkeypatch):
    """The whole category must cost ONE Algolia query, not one per product."""
    hits = [_hit(f"Gigabyte GeForce RTX 507{i} Windforce 12GB", 1000 + i, f"/products/{i}")
            for i in range(3)]
    post, sent = _capture_post([_catalogue_response(hits)])
    monkeypatch.setattr("scraper.pccg.requests.post", post)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_PAGE_DELAY", 0)
    monkeypatch.setattr("scraper.pccg._write_cooldown", lambda reason: None)

    watchlist = [
        {"category": "gpu", "model": f"GeForce RTX 507{i}", "brand": "NVIDIA",
         "gen_tier": "current", "vram_gb": 12}
        for i in range(3)
    ]
    scrape_category("gpu", watchlist)

    assert len(sent) == 1, f"expected 1 HTTP request, got {len(sent)}"
    assert _count_queries(sent) == 1, (
        f"expected 1 Algolia query for the category, got {_count_queries(sent)}")


def test_full_watchlist_run_stays_well_under_the_hourly_key_limit(monkeypatch):
    """A 100-product watchlist must not approach maxQueriesPerIPPerHour=100."""
    post, sent = _capture_post([_catalogue_response(
        [_hit("Gigabyte GeForce RTX 5070 Windforce 12GB", 1349, "/products/1")])])
    monkeypatch.setattr("scraper.pccg.requests.post", post)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_PAGE_DELAY", 0)
    monkeypatch.setattr("scraper.pccg._write_cooldown", lambda reason: None)

    watchlist = (
        [{"category": "gpu", "model": f"GPU {i}", "brand": "NVIDIA", "gen_tier": "current", "vram_gb": 12} for i in range(47)]
        + [{"category": "cpu", "model": f"CPU {i}", "brand": "AMD", "gen_tier": "current"} for i in range(53)]
    )
    scrape_category("gpu", watchlist)
    scrape_category("cpu", watchlist)

    assert _count_queries(sent) == 2, (
        f"a full run must cost 2 queries (one per category), got {_count_queries(sent)}")


def test_catalogue_request_asks_for_the_whole_category(monkeypatch):
    """The catalogue query is an empty query filtered to the category."""
    post, sent = _capture_post([_catalogue_response([])])
    monkeypatch.setattr("scraper.pccg.requests.post", post)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_PAGE_DELAY", 0)

    algolia_fetch_catalogue("Graphics Cards")

    params = sent[0]["requests"][0]["params"]
    assert "query=&" in params, f"catalogue query must be empty: {params}"
    assert "hitsPerPage=1000" in params, params
    assert "Graphics+Cards" in params, params


def test_catalogue_paginates_when_category_exceeds_one_page(monkeypatch):
    """If a category ever outgrows hitsPerPage, keep pulling pages."""
    page0 = _catalogue_response([_hit("Gigabyte GeForce RTX 5070 A 12GB", 1000, "/a")],
                                nb_pages=2)
    page1 = _catalogue_response([_hit("Gigabyte GeForce RTX 5070 B 12GB", 1100, "/b")],
                                nb_pages=2)
    post, sent = _capture_post([page0, page1])
    monkeypatch.setattr("scraper.pccg.requests.post", post)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_PAGE_DELAY", 0)

    products = algolia_fetch_catalogue("Graphics Cards")

    assert len(sent) == 2
    assert {p["name"] for p in products} == {
        "Gigabyte GeForce RTX 5070 A 12GB", "Gigabyte GeForce RTX 5070 B 12GB"}


# ── Failure handling ───────────────────────────────────────────────

def test_empty_catalogue_trips_the_breaker_and_writes_cooldown(monkeypatch):
    """A category that returns nothing at all is a block, not an empty shop."""
    written = []
    monkeypatch.setattr("scraper.pccg.algolia_fetch_catalogue", lambda *a, **k: [])
    monkeypatch.setattr("scraper.pccg._write_cooldown", lambda reason: written.append(reason))

    watchlist = [{"category": "gpu", "model": "GPU 1", "brand": "NVIDIA",
                  "gen_tier": "current", "vram_gb": 12}]
    results, matched, tripped = scrape_category("gpu", watchlist)

    assert tripped is True
    assert results == []
    assert matched == set()
    assert written, "an empty catalogue must write a cooldown file"


# ── Matching against the full catalogue ────────────────────────────

def test_catalogue_matching_keeps_the_variant_guard(monkeypatch):
    """Local matching must not let a base model claim its Ti/X variant."""
    monkeypatch.setattr("scraper.pccg.algolia_fetch_catalogue", lambda *a, **k: [
        {"name": "Gigabyte GeForce RTX 5070 Windforce OC 12GB", "price": 1349,
         "url": "/p/1", "stock_status": "in_stock"},
        {"name": "ASUS GeForce RTX 5070 Ti TUF 16GB", "price": 1899,
         "url": "/p/2", "stock_status": "out_of_stock"},
    ])

    watchlist = [
        {"category": "gpu", "model": "GeForce RTX 5070", "brand": "NVIDIA",
         "gen_tier": "current", "vram_gb": 12},
        {"category": "gpu", "model": "GeForce RTX 5070 Ti", "brand": "NVIDIA",
         "gen_tier": "current", "vram_gb": 16},
    ]
    results, matched, tripped = scrape_category("gpu", watchlist)

    assert tripped is False
    assert matched == {0, 1}
    by_model = {r["watchlist_model"]: r for r in results}
    assert by_model["GeForce RTX 5070"]["price_aud"] == 1349
    assert by_model["GeForce RTX 5070 Ti"]["price_aud"] == 1899


def test_out_of_stock_listings_are_still_recorded(monkeypatch):
    """Sold-out cards keep their price history — unchanged by the rewrite."""
    monkeypatch.setattr("scraper.pccg.algolia_fetch_catalogue", lambda *a, **k: [
        {"name": "Gigabyte Aorus GeForce RTX 5090 Master GDDR7 32GB", "price": 7799,
         "url": "/p/9", "stock_status": "out_of_stock"},
    ])

    watchlist = [{"category": "gpu", "model": "GeForce RTX 5090", "brand": "NVIDIA",
                  "gen_tier": "current", "vram_gb": 32}]
    results, matched, tripped = scrape_category("gpu", watchlist)

    assert matched == {0}
    assert results[0]["stock_status"] == "out_of_stock"
    assert results[0]["price_aud"] == 7799
