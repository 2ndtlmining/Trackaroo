"""
Tests for the PCCG reliability fixes (IMPROVEMENT_16_Aug_V1.md §10/11.1–11.6).

Covers:
- Infinite-loop fix: retries exhausted on 429 must terminate (not loop forever)
- Retry-After header preferred over the fixed formula
- Non-JSON 200 response (WAF challenge page) handled without crashing
- 401/403 logged distinctly (credential rotation, not rate-limiting)
- Circuit breaker aborts a category pass after N consecutive failed batches
  and returns what was matched so far
- Cooldown file: written on trip, respected within window, cleared on success
"""
import json
import sys
import time
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from scraper.pccg import (
    _clear_cooldown,
    _cooldown_active,
    _retry_wait,
    _write_cooldown,
    algolia_batch_search,
    algolia_single_search,
    scrape_category,
)

ALGOLIA_RESPONSE_OK = {
    "results": [
        {"hits": [{"products_name": "Test GPU", "products_price": 999,
                   "Product_URL": "/products/test", "manufacturers_name": "NVIDIA"}],
         "nbPages": 1},
    ]
}


# ── 429 retry-exhausted termination (the original infinite-loop bug) ──

def _fake_429(*args, **kwargs):
    resp = unittest.mock.Mock()
    resp.status_code = 429
    resp.text = ""
    resp.headers = {}
    return resp


def _fake_200(payload):
    def _respond(*args, **kwargs):
        resp = unittest.mock.Mock()
        resp.status_code = 200
        resp.text = json.dumps(payload)
        resp.headers = {}
        resp.json.return_value = payload
        return resp
    return _respond


def test_batch_search_terminates_when_all_retries_429(monkeypatch):
    """All-attempts-429 must return (not loop forever) with empty results."""
    calls = []
    def _counted_429(*args, **kwargs):
        calls.append(1)
        return _fake_429()
    monkeypatch.setattr("scraper.pccg.requests.post", _counted_429)
    monkeypatch.setattr("scraper.pccg.BATCH_DELAY", 0)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 0)

    start = time.time()
    result = algolia_batch_search(["RTX 5090"], "Graphics Cards", hits_per_page=20, max_pages=3)
    elapsed = time.time() - start

    # Must have given up quickly, not spun in the outer while for max_pages.
    assert elapsed < 5
    assert result == [[]]
    # ALGOLIA_MAX_RETRIES attempts, not max_pages pages.
    assert len(calls) == 3


def test_single_search_terminates_when_all_retries_429(monkeypatch):
    calls = []
    def _counted_429(*args, **kwargs):
        calls.append(1)
        return _fake_429()
    monkeypatch.setattr("scraper.pccg.requests.post", _counted_429)
    monkeypatch.setattr("scraper.pccg.BATCH_DELAY", 0)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 0)

    start = time.time()
    result = algolia_single_search("RTX 5090", "Graphics Cards", hits_per_page=20, max_pages=3)
    elapsed = time.time() - start

    assert elapsed < 5
    assert result == []
    assert len(calls) == 3


def test_single_search_last_page_breaks_outer_loop(monkeypatch):
    """Reaching nbPages must not re-request the same page forever — a second
    variant of the loop bug where the inner `break` never escaped the while."""
    payload = {
        "results": [
            {"hits": [{"products_name": "Test GPU", "products_price": 999,
                       "Product_URL": "/products/test", "manufacturers_name": "NVIDIA"}],
             "nbPages": 1},
        ]
    }
    calls = []
    def _counted_200(*args, **kwargs):
        calls.append(1)
        return _fake_200(payload)()
    monkeypatch.setattr("scraper.pccg.requests.post", _counted_200)

    start = time.time()
    result = algolia_single_search("RTX 5090", "Graphics Cards", hits_per_page=20, max_pages=3)
    elapsed = time.time() - start

    assert elapsed < 5
    assert len(result) == 1
    assert len(calls) == 1  # One request; last page detected, no retry.


# ── Retry-After header handling ─────────────────────────────────────

def test_retry_wait_uses_header_when_present(monkeypatch):
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 5.0)
    assert _retry_wait("10", 0) == 10.0


def test_retry_wait_caps_a_pathological_retry_after(monkeypatch):
    """An absurd Retry-After must not stall the run — capped at a ceiling."""
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 5.0)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_MAX_RETRIES", 3)
    assert _retry_wait("3600", 0) == 60.0  # 5 * 3 * 4


def test_retry_wait_falls_back_to_jittered_formula(monkeypatch):
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 5.0)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_BACKOFF_MAX_SECONDS", 20.0)
    w0 = _retry_wait(None, 0)
    w2 = _retry_wait(None, 2)
    assert 4.5 <= w0 <= 5.5
    assert 13.5 <= w2 <= 16.5


def test_batch_search_prefers_retry_after(monkeypatch):
    """429 responses carrying Retry-After use it instead of the fixed formula."""
    def _with_retry_after(*args, **kwargs):
        resp = unittest.mock.Mock()
        resp.status_code = 429
        resp.text = ""
        resp.headers = {"Retry-After": "1"}
        return resp
    monkeypatch.setattr("scraper.pccg.requests.post", _with_retry_after)
    # If the header were ignored, the formula would sleep 5s and make the test slow.
    monkeypatch.setattr("scraper.pccg.ALGOLIA_RATE_LIMIT_WAIT_SECONDS", 30.0)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_MAX_RETRIES", 2)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_TIMEOUT_SECONDS", 5)

    start = time.time()
    result = algolia_batch_search(["RTX 5090"], "Graphics Cards")
    elapsed = time.time() - start

    assert elapsed < 5
    assert result == [[]]


# ── Non-JSON 200 (WAF/challenge page) ──────────────────────────────

def test_non_json_200_returns_without_crashing(monkeypatch):
    def _html_200(*args, **kwargs):
        resp = unittest.mock.Mock()
        resp.status_code = 200
        resp.text = "<html>challenge</html>"
        resp.headers = {}
        resp.json.side_effect = ValueError("no json")
        return resp
    monkeypatch.setattr("scraper.pccg.requests.post", _html_200)

    result = algolia_batch_search(["RTX 5090"], "Graphics Cards")
    assert result == [[]]


# ── 401/403 distinct logging ───────────────────────────────────────

def test_403_logs_auth_rotation_not_api_error(monkeypatch, caplog):
    def _forbidden(*args, **kwargs):
        resp = unittest.mock.Mock()
        resp.status_code = 403
        resp.text = "forbidden"
        resp.headers = {}
        return resp
    monkeypatch.setattr("scraper.pccg.requests.post", _forbidden)

    with caplog.at_level("ERROR", logger="scraper.pccg"):
        result = algolia_batch_search(["RTX 5090"], "Graphics Cards")

    assert result == [[]]
    assert any("rotated" in r.message or "rotated" in r.msg for r in caplog.records)


# ── Circuit breaker ────────────────────────────────────────────────

def test_circuit_breaker_aborts_after_n_failed_batches(monkeypatch):
    """Consecutive all-empty batches trip the breaker and return early."""
    monkeypatch.setattr("scraper.pccg.algolia_batch_search", lambda *a, **k: [[] for _ in a[0]])
    monkeypatch.setattr("scraper.pccg.BATCH_DELAY", 0)
    monkeypatch.setattr("scraper.pccg.BATCH_SIZE", 2)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_CIRCUIT_BREAKER_LIMIT", 3)
    monkeypatch.setattr("scraper.pccg._write_cooldown", lambda reason: None)
    monkeypatch.setattr("scraper.pccg._clear_cooldown", lambda: None)

    watchlist = [
        {"category": "gpu", "model": f"GPU {i}", "brand": "NVIDIA", "gen_tier": "current",
         "search_terms": [f"gpu {i}"]}
        for i in range(10)
    ]
    results, matched, tripped = scrape_category("gpu", watchlist)

    assert tripped is True
    assert results == []
    assert matched == set()


def test_circuit_breaker_keeps_prior_matches_when_not_tripped(monkeypatch):
    """A single failed batch must not trip the breaker or discard earlier matches."""
    monkeypatch.setattr("scraper.pccg.BATCH_DELAY", 0)
    monkeypatch.setattr("scraper.pccg.BATCH_SIZE", 2)
    monkeypatch.setattr("scraper.pccg.ALGOLIA_CIRCUIT_BREAKER_LIMIT", 3)
    monkeypatch.setattr("scraper.pccg._write_cooldown", lambda reason: None)
    monkeypatch.setattr("scraper.pccg._clear_cooldown", lambda: None)

    def _search(queries, *a, **k):
        out = []
        for q in queries:
            if "found" in q:
                out.append([{"name": f"Listed {q}", "price": 500,
                             "url": "/p/x", "stock_status": "in_stock"}])
            else:
                out.append([])
        return out
    monkeypatch.setattr("scraper.pccg.algolia_batch_search", _search)

    watchlist = [
        {"category": "gpu", "model": "Found GPU", "brand": "NVIDIA", "gen_tier": "current",
         "search_terms": ["found gpu"]},
        {"category": "gpu", "model": "Missing GPU", "brand": "NVIDIA", "gen_tier": "current",
         "search_terms": ["missing gpu"]},
    ]
    results, matched, tripped = scrape_category("gpu", watchlist)

    assert tripped is False
    assert len(results) == 1
    assert matched == {0}


# ── Cooldown file ──────────────────────────────────────────────────

def test_cooldown_write_and_active(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_FILE", tmp_path / "pccg_cooldown.json")
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_HOURS", 4.0)

    _clear_cooldown()
    assert _cooldown_active() is False

    _write_cooldown("test reason")
    assert (tmp_path / "pccg_cooldown.json").exists()
    assert _cooldown_active() is True


def test_cooldown_expired_is_inactive(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_FILE", tmp_path / "pccg_cooldown.json")
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_HOURS", 4.0)

    old = datetime.now(timezone.utc) - timedelta(hours=10)
    (tmp_path / "pccg_cooldown.json").write_text(
        json.dumps({"tripped_at": old.isoformat(), "reason": "old"}),
        encoding="utf-8",
    )
    assert _cooldown_active() is False


def test_unreadable_cooldown_is_inactive(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_FILE", tmp_path / "pccg_cooldown.json")
    (tmp_path / "pccg_cooldown.json").write_text("{not json", encoding="utf-8")
    assert _cooldown_active() is False


def test_clear_cooldown_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_FILE", tmp_path / "pccg_cooldown.json")
    _write_cooldown("test")
    assert (tmp_path / "pccg_cooldown.json").exists()

    _clear_cooldown()
    assert not (tmp_path / "pccg_cooldown.json").exists()