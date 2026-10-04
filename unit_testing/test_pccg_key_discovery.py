"""PCCG Algolia key discovery (#11b).

When Algolia rejects the hard-coded search key, the scraper reads the current
key from one pccasegear.com page (Algolia Insights' ``aa('init', ...)`` block
carries appId + apiKey), caches it, and retries the category once. A rotated
key then costs one page fetch, not a dead PCCG feed until a human notices.
"""
import json
import unittest.mock

import pytest

from scraper import pccg, pccg_key
from scraper.run_report import EXIT_AUTH, EXIT_OK

OLD_APP, OLD_KEY = "HPD3DBJ2IO", "9559cf1a6c7521a30ba0832ec6c38499"
NEW_KEY = "0123456789abcdef0123456789abcdef"

# Trimmed from the live page (5-Oct-2026), key swapped for a fake one.
PAGE = """
  <link rel="preconnect" href="https://hpd3dbj2io-dsn.algolia.net">
  <script>
    }(window, document, "script", ALGOLIA_INSIGHTS_SRC, "aa");

    aa('init', {
      appId: 'HPD3DBJ2IO',
      apiKey: '%s',
    });
  </script>
"""

def _catalogue(name):
    return {"results": [{"hits": [
        {"products_name": name, "products_price": 799, "Product_URL": "/products/1",
         "manufacturers_name": "X", "indicator": {"label": "In stock"}}], "nbPages": 1}]}


CPU_OK = _catalogue("AMD Ryzen 7 9800X3D Processor")
GPU_OK = _catalogue("Gigabyte GeForce RTX 5070 Windforce 12GB")


def _resp(status, body="", payload=None):
    r = unittest.mock.Mock()
    r.status_code = status
    r.text = body if payload is None else json.dumps(payload)
    r.headers = {}
    r.json.return_value = payload
    return r


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Fresh credentials, temp data dir and cache, report file, no sleeps."""
    monkeypatch.setattr(pccg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pccg, "PCCG_COOLDOWN_FILE", tmp_path / "pccg_cooldown.json")
    monkeypatch.setattr(pccg_key, "CACHE_FILE", tmp_path / "pccg_algolia.json")
    monkeypatch.setattr(pccg.time, "sleep", lambda s: None)
    monkeypatch.setenv("TRACKAROO_RUN_REPORT", str(tmp_path / "report.json"))
    monkeypatch.delenv("ALGOLIA_API_KEY", raising=False)
    monkeypatch.delenv("ALGOLIA_APP_ID", raising=False)
    pccg.set_credentials(OLD_APP, OLD_KEY)
    yield tmp_path
    pccg.set_credentials(OLD_APP, OLD_KEY)


def _algolia(accept_key):
    """requests.post stand-in: 403 unless the request carries accept_key."""
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append(headers["X-Algolia-API-Key"])
        if headers["X-Algolia-API-Key"] != accept_key:
            return _resp(403, "Invalid Application-ID or API key")
        gpu = "Graphics" in json["requests"][0]["params"]
        return _resp(200, payload=GPU_OK if gpu else CPU_OK)
    return post, calls


def _page(key):
    gets = []

    def get(url, headers=None, timeout=None):
        gets.append(url)
        return _resp(200, PAGE % key)
    return get, gets


# ── Parsing ───────────────────────────────────────────────────────────

def test_parses_app_id_and_key_from_the_insights_init_block():
    assert pccg_key.parse_credentials(PAGE % NEW_KEY) == ("HPD3DBJ2IO", NEW_KEY)


@pytest.mark.parametrize("html", [
    "", "<html>no algolia here</html>",
    "aa('init', { appId: 'HPD3DBJ2IO' });",                      # no key
    "aa('init', { appId: 'HPD3DBJ2IO', apiKey: 'not-hex!' });",  # not a search key
])
def test_returns_none_when_the_page_has_no_usable_key(html):
    assert pccg_key.parse_credentials(html) is None


def test_discovery_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(pccg_key.requests, "get", boom)
    assert pccg_key.discover_credentials() is None


def test_discovery_needs_a_200(monkeypatch):
    monkeypatch.setattr(pccg_key.requests, "get", lambda *a, **k: _resp(403, PAGE % NEW_KEY))
    assert pccg_key.discover_credentials() is None


# ── Rotation end to end ───────────────────────────────────────────────

def test_rotated_key_is_discovered_cached_and_the_run_succeeds(isolated, monkeypatch):
    post, posts = _algolia(accept_key=NEW_KEY)
    get, gets = _page(NEW_KEY)
    monkeypatch.setattr(pccg.requests, "post", post)
    monkeypatch.setattr(pccg_key.requests, "get", get)

    assert pccg.main() == EXIT_OK
    # Budget: one rejected query, then one query per category, plus ONE page.
    assert posts == [OLD_KEY, NEW_KEY, NEW_KEY]
    assert len(gets) == 1
    assert json.loads((isolated / "pccg_algolia.json").read_text())["api_key"] == NEW_KEY
    assert not (isolated / "pccg_cooldown.json").exists()
    notes = json.loads((isolated / "report.json").read_text())["notes"]
    assert any("rotated" in n for n in notes)


def test_next_run_starts_from_the_cached_key(isolated, monkeypatch):
    (isolated / "pccg_algolia.json").write_text(json.dumps({"app_id": OLD_APP, "api_key": NEW_KEY}))
    post, posts = _algolia(accept_key=NEW_KEY)
    get, gets = _page(NEW_KEY)
    monkeypatch.setattr(pccg.requests, "post", post)
    monkeypatch.setattr(pccg_key.requests, "get", get)

    assert pccg.main() == EXIT_OK
    assert posts == [NEW_KEY, NEW_KEY]
    assert gets == []


def test_an_explicit_env_key_beats_the_cache(isolated, monkeypatch):
    (isolated / "pccg_algolia.json").write_text(json.dumps({"app_id": OLD_APP, "api_key": NEW_KEY}))
    monkeypatch.setenv("ALGOLIA_API_KEY", OLD_KEY)
    assert pccg_key.cached_credentials_unless_env() is None


def test_page_still_showing_the_rejected_key_fails_loudly_once(isolated, monkeypatch):
    post, posts = _algolia(accept_key=NEW_KEY)
    get, gets = _page(OLD_KEY)  # PCCG has not published a new key
    monkeypatch.setattr(pccg.requests, "post", post)
    monkeypatch.setattr(pccg_key.requests, "get", get)

    assert pccg.main() == EXIT_AUTH
    assert posts == [OLD_KEY]       # no retry with the same key
    assert len(gets) == 1
    assert not (isolated / "pccg_cooldown.json").exists()
    assert not (isolated / "pccg_algolia.json").exists()


def test_discovered_key_also_rejected_fails_loudly_without_looping(isolated, monkeypatch):
    post, posts = _algolia(accept_key="f" * 32)  # neither key works
    get, gets = _page(NEW_KEY)
    monkeypatch.setattr(pccg.requests, "post", post)
    monkeypatch.setattr(pccg_key.requests, "get", get)

    assert pccg.main() == EXIT_AUTH
    assert posts == [OLD_KEY, NEW_KEY]
    assert len(gets) == 1
    notes = json.loads((isolated / "report.json").read_text())["notes"]
    assert any("ALGOLIA_API_KEY" in n for n in notes)


def test_page_fetch_failure_keeps_the_original_auth_failure(isolated, monkeypatch):
    post, posts = _algolia(accept_key=NEW_KEY)
    monkeypatch.setattr(pccg.requests, "post", post)
    monkeypatch.setattr(pccg_key.requests, "get", lambda *a, **k: _resp(503))

    assert pccg.main() == EXIT_AUTH
    assert posts == [OLD_KEY]
