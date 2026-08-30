# Mwave Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Mwave as Trackaroo's third retailer, so the daily pipeline collects CPU/GPU prices from Scorptec, PCCG and Mwave.

**Architecture:** A new `scraper/mwave.py` following the `scraper/scorptec.py` shape — fetch server-rendered category pages, parse the product grid with BeautifulSoup, match against the watchlist, emit the standard snapshot envelope via `snapshot_io.save_snapshot`. Mwave sits behind AWS WAF, so a challenge-detecting fetch layer reusing PCCG's cooldown pattern comes *before* the parser. The retailer name is then threaded through the nine places it is hardcoded.

**Tech Stack:** Python 3.12, `requests`, `BeautifulSoup4`, `pytest`. No new dependencies.

**Spec:** [`docs/proposals/THIRD_RETAILER.md`](../../proposals/THIRD_RETAILER.md)

## Global Constraints

- **Python 3.12 required.** The repo uses PEP 701 f-strings that are compile errors on 3.11. Never target 3.11.
- **Never write a snapshot with bare `open(path, "w")`.** Always `scraper.snapshot_io.save_snapshot()` — it writes atomically and refuses to replace a richer snapshot with a poorer one.
- **Never delete price or product data.** Products out of scope get `tracked=0`; listings get `status='delisted'`/`'stale'`.
- **Listings are identified by stable SKU key**, never raw URL — retailers rewrite slugs.
- **Steps after ingest are best-effort** — wrap in `try/except` so they cannot break a run that already collected good data.
- **Entry points call `config.setup_logging()`**, never `logging.basicConfig`.
- **Log strings must be ASCII.** Use `->` not `→`; the Windows console is cp1252 and mojibakes em-dashes.
- **Retailer slug is exactly `mwave`** — lowercase, no spaces. It must match `web/src/lib/types.ts:7`, which already declares it.
- **Full validation gate:** `python -m pytest -q` (repo root), then from `web/`: `npm run check`, `npm test`, `npm run test:e2e`.
- **Baseline at plan time:** pytest 650 passing, vitest 393, e2e 68, svelte-check 0 errors.

---

## Task 0: WAF viability gate (GO/NO-GO — do this first, alone)

**This is not a formality. If it fails, the rest of the plan is void** and the recommendation moves to Umart. Do not write scraper code before this passes.

During the 30-Aug spike Mwave served real HTML for the first several requests, then returned **HTTP 202 with an AWS WAF challenge** (`window.awsWafCookieDomainList`, `challenge.js`) — the same mechanism Centre Com was ruled out for. The open question is whether a *polite daily* pattern trips it.

**Files:**
- Create: `docs/proposals/mwave-waf-probe.md` (findings; delete after the decision is recorded in the proposal)

- [ ] **Step 1: Confirm the WAF block from yesterday has aged out**

```bash
curl -s -o /dev/null -w 'http=%{http_code} size=%{size_download}\n' \
  --max-time 25 \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: en-AU,en;q=0.9" \
  "https://www.mwave.com.au/graphics-cards"
```

Expected if healthy: `http=200 size=~160000`.
`http=202` with ~2000 bytes means still challenged — wait an hour and retry before concluding anything.

- [ ] **Step 2: Simulate one realistic daily run — 8 requests, 5s apart**

A real run fetches roughly 8-20 category pages once per day. This measures that shape, not a burst.

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
for i in 1 2 3 4 5 6 7 8; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 -A "$UA" \
    -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
    -H "Accept-Language: en-AU,en;q=0.9" \
    "https://www.mwave.com.au/graphics-cards?page=$i")
  echo "page $i -> $code"
  sleep 5
done
```

Expected to proceed: **all eight return 200.**
Any `202` or `403` means the daily cadence itself trips the WAF.

- [ ] **Step 3: Record the verdict and decide**

Write the eight status codes into `docs/proposals/mwave-waf-probe.md`.

- **All 200** -> proceed to Task 1. Set `MWAVE_PAGE_DELAY` default to **5.0s** (the cadence just proven safe), not 0.5s.
- **Any challenge** -> **STOP.** Do not continue this plan. Update `docs/proposals/THIRD_RETAILER.md` to move Mwave alongside Centre Com, and start the Umart URL-discovery pass instead (proposal, "Umart" section). Tell the user before doing anything else.

- [ ] **Step 4: Commit the finding**

```bash
git add docs/proposals/
git commit -m "docs: record Mwave WAF viability probe result"
```

---

## Task 1: Capture a real page as a test fixture

Everything downstream is parsed against a saved file, so the suite never depends on Mwave being reachable — the same reason `unit_testing/test_scraper.py` uses HTML fixtures.

**Files:**
- Create: `unit_testing/fixtures/mwave_gpu_grid.html`
- Test: `unit_testing/test_mwave.py`

**Interfaces:**
- Produces: the fixture path other tasks parse against.

- [ ] **Step 1: Save one real category page**

```bash
mkdir -p unit_testing/fixtures
curl -s --max-time 25 \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: en-AU,en;q=0.9" \
  "https://www.mwave.com.au/graphics-cards" \
  -o unit_testing/fixtures/mwave_gpu_grid.html
```

- [ ] **Step 2: Verify it is a real grid, not a challenge page**

```bash
python -c "
h=open('unit_testing/fixtures/mwave_gpu_grid.html',encoding='utf-8',errors='replace').read()
import re
print('bytes:', len(h))
print('awsWaf present:', 'awsWaf' in h)
print('product links:', len(set(re.findall(r'href=\"(/products/[^\"]*)\"', h))))
"
```

Expected: `bytes` > 100000, `awsWaf present: False`, `product links` >= 30.
If `awsWaf present: True`, the file is a challenge page — delete it and go back to Task 0.

- [ ] **Step 3: Print the real card structure so the parser targets actual selectors**

Do not guess selectors. Read them:

```bash
python -c "
from bs4 import BeautifulSoup
h=open('unit_testing/fixtures/mwave_gpu_grid.html',encoding='utf-8',errors='replace').read()
s=BeautifulSoup(h,'html.parser')
a=s.select_one('a[href^=\"/products/\"]')
n=a
for _ in range(8):
    n=n.parent
    if n is None: break
    if n.select_one('.price'): break
print('container tag:', n.name, 'classes:', n.get('class'))
print(str(n)[:2000])
"
```

Record the container class, the name element and the price element. Task 2 uses these exact selectors.

- [ ] **Step 4: Commit the fixture**

```bash
git add unit_testing/fixtures/mwave_gpu_grid.html
git commit -m "test: add Mwave GPU grid fixture"
```

---

## Task 2: Parse the product grid

**Files:**
- Create: `scraper/mwave.py`
- Test: `unit_testing/test_mwave.py`

**Interfaces:**
- Produces: `parse_product_grid(html: str) -> List[Dict[str, Any]]`, each dict having exactly the keys the other scrapers emit: `name` (str), `full_description` (str), `price_aud` (float), `stock_status` (str, one of `in_stock`/`out_of_stock`/`preorder`/`unknown`), `url` (str, absolute), `retailer_sku` (str).
- Produces: `BASE = "https://www.mwave.com.au"`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Mwave scraper."""
from pathlib import Path

import pytest

from scraper.mwave import parse_product_grid

FIXTURE = Path(__file__).parent / "fixtures" / "mwave_gpu_grid.html"


@pytest.fixture
def grid_html():
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


class TestParseProductGrid:
    def test_finds_products(self, grid_html):
        products = parse_product_grid(grid_html)
        assert len(products) >= 30

    def test_every_product_has_the_snapshot_keys(self, grid_html):
        required = {"name", "full_description", "price_aud", "stock_status", "url", "retailer_sku"}
        for p in parse_product_grid(grid_html):
            assert required <= set(p), f"missing {required - set(p)}"

    def test_prices_are_positive_floats(self, grid_html):
        for p in parse_product_grid(grid_html):
            assert isinstance(p["price_aud"], float)
            assert p["price_aud"] > 0

    def test_prices_are_plausible_for_gpus(self, grid_html):
        """Catches a comma-parsing bug turning $1,999.00 into 1.0."""
        prices = [p["price_aud"] for p in parse_product_grid(grid_html)]
        assert max(prices) > 500, f"max price {max(prices)} suggests thousands separators were dropped"

    def test_urls_are_absolute(self, grid_html):
        for p in parse_product_grid(grid_html):
            assert p["url"].startswith("https://www.mwave.com.au/products/")

    def test_skus_are_unique_and_non_empty(self, grid_html):
        skus = [p["retailer_sku"] for p in parse_product_grid(grid_html)]
        assert all(skus), "every product needs a retailer_sku"
        assert len(set(skus)) == len(skus), "retailer_sku must be unique per product"

    def test_stock_status_is_a_known_value(self, grid_html):
        allowed = {"in_stock", "out_of_stock", "preorder", "unknown"}
        for p in parse_product_grid(grid_html):
            assert p["stock_status"] in allowed

    def test_empty_html_returns_empty_list(self):
        assert parse_product_grid("") == []

    def test_challenge_page_yields_no_products(self):
        """An AWS WAF challenge must parse as zero products, never crash."""
        challenge = '<html><head><script>window.awsWafCookieDomainList=[];</script></head><body></body></html>'
        assert parse_product_grid(challenge) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.mwave'`

- [ ] **Step 3: Write the parser**

Use the selectors recorded in Task 1 Step 3 — the `SELECTOR` constants below are placeholders **you must replace with what that step printed**. The rest of the function is correct as written.

```python
"""Mwave scraper — server-rendered category grids.

Mwave sits behind AWS WAF. It serves real HTML to a well-behaved client but
returns HTTP 202 with a challenge page once a burst trips it, so requests are
spaced by MWAVE_PAGE_DELAY and a challenge trips a cooldown rather than a
retry (see fetch_page).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

BASE = "https://www.mwave.com.au"

# Replace with the values printed by Task 1 Step 3.
CARD_SELECTOR = "div.product-item"
NAME_SELECTOR = "a[href^='/products/']"
PRICE_SELECTOR = ".price"


def _parse_price(text: str) -> Optional[float]:
    """Parse '$1,999.00' -> 1999.0. Returns None when no number is present."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_stock(card_text: str) -> str:
    """Map Mwave's grid stock wording onto the schema's four values."""
    lowered = card_text.lower()
    if "pre-order" in lowered or "preorder" in lowered:
        return "preorder"
    if "out of stock" in lowered or "sold out" in lowered:
        return "out_of_stock"
    if "in stock" in lowered or "add to cart" in lowered:
        return "in_stock"
    return "unknown"


def _sku_from_href(href: str) -> str:
    """Mwave product URLs are slugs; the trailing slug segment is the stable key."""
    return href.rstrip("/").split("/")[-1]


def parse_product_grid(html: str) -> List[Dict[str, Any]]:
    """Extract product dicts from one category page.

    A WAF challenge page contains no product cards, so it returns [] rather
    than raising — the caller decides that zero products means trouble.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for card in soup.select(CARD_SELECTOR):
        link = card.select_one(NAME_SELECTOR)
        if link is None:
            continue
        href = link.get("href") or ""
        if not href.startswith("/products/"):
            continue

        name = link.get_text(" ", strip=True)
        price_el = card.select_one(PRICE_SELECTOR)
        price = _parse_price(price_el.get_text(" ", strip=True) if price_el else "")
        if not name or price is None:
            continue

        sku = _sku_from_href(href)
        if sku in seen:
            continue
        seen.add(sku)

        products.append({
            "name": name,
            "full_description": card.get_text(" ", strip=True)[:500],
            "price_aud": price,
            "stock_status": _parse_stock(card.get_text(" ", strip=True)),
            "url": f"{BASE}{href}",
            "retailer_sku": sku,
        })

    return products
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: PASS (10 tests).

If `test_finds_products` fails with 0, `CARD_SELECTOR` is wrong — re-read Task 1 Step 3's output and fix the three selector constants. Do not loosen the test.

- [ ] **Step 5: Commit**

```bash
git add scraper/mwave.py unit_testing/test_mwave.py
git commit -m "feat(mwave): parse the product grid"
```

---

## Task 3: WAF-aware fetch layer

**Files:**
- Modify: `scraper/mwave.py`
- Modify: `config.py` (add the Mwave knobs beside `SCORPTEC_*`, around line 175-183)
- Test: `unit_testing/test_mwave.py`

**Interfaces:**
- Consumes: `BASE` from Task 2.
- Produces: `is_waf_challenge(html: str) -> bool`, `fetch_page(url: str) -> Optional[str]`, `HEADERS: Dict[str, str]`.
- Produces config: `MWAVE_TIMEOUT_SECONDS` (int, 15), `MWAVE_MAX_RETRIES` (int, 2), `MWAVE_RETRY_DELAY` (float, 2.0), `MWAVE_PAGE_DELAY` (float, 5.0), `MWAVE_MAX_PAGES` (int, 20).

- [ ] **Step 1: Write the failing test**

Append to `unit_testing/test_mwave.py`:

```python
from unittest.mock import patch

from scraper.mwave import HEADERS, fetch_page, is_waf_challenge


class TestWafDetection:
    def test_detects_the_challenge_page(self):
        assert is_waf_challenge("<script>window.awsWafCookieDomainList = [];</script>")

    def test_detects_goku_props(self):
        assert is_waf_challenge('<script>window.gokuProps = {"key":"x"};</script>')

    def test_real_grid_is_not_a_challenge(self, grid_html):
        assert not is_waf_challenge(grid_html)

    def test_empty_string_is_not_a_challenge(self):
        assert not is_waf_challenge("")


class TestHeaders:
    def test_sends_a_full_browser_user_agent(self):
        """A bare 'Mozilla/5.0' got 403 during the spike; the full UA got 200."""
        assert "Chrome/" in HEADERS["User-Agent"]
        assert "AppleWebKit" in HEADERS["User-Agent"]

    def test_sends_accept_and_language(self):
        assert "text/html" in HEADERS["Accept"]
        assert "en-AU" in HEADERS["Accept-Language"]


class TestFetchPage:
    def test_returns_html_on_success(self):
        with patch("scraper.mwave.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.text = "<html>ok</html>"
            assert fetch_page("https://www.mwave.com.au/graphics-cards") == "<html>ok</html>"

    def test_returns_none_on_a_challenge_and_does_not_retry(self):
        """A challenge means back off, not hammer -- retrying is what deepens a block."""
        with patch("scraper.mwave.requests.get") as get:
            get.return_value.status_code = 202
            get.return_value.text = "<script>window.awsWafCookieDomainList = [];</script>"
            assert fetch_page("https://www.mwave.com.au/graphics-cards") is None
            assert get.call_count == 1

    def test_returns_none_on_http_error(self):
        with patch("scraper.mwave.requests.get") as get:
            get.return_value.status_code = 500
            get.return_value.text = ""
            assert fetch_page("https://www.mwave.com.au/graphics-cards") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: FAIL — `ImportError: cannot import name 'HEADERS'`

- [ ] **Step 3: Add the config knobs**

In `config.py`, immediately after the `SCORPTEC_*` block (near line 183):

```python
# ── Mwave ───────────────────────────────────────────────────────────
# Mwave is behind AWS WAF. The 5s page delay is not arbitrary politeness: a
# burst of ~12 requests tripped a challenge during the 30-Aug spike, while
# 8 requests at 5s intervals were served normally. Do not lower it.
MWAVE_TIMEOUT_SECONDS = _env_int("TRACKAROO_MWAVE_TIMEOUT_SECONDS", 15)
MWAVE_MAX_RETRIES = _env_int("TRACKAROO_MWAVE_MAX_RETRIES", 2)
MWAVE_RETRY_DELAY = _env_float("TRACKAROO_MWAVE_RETRY_DELAY", 2.0)
MWAVE_PAGE_DELAY = _env_float("TRACKAROO_MWAVE_PAGE_DELAY", 5.0)
MWAVE_MAX_PAGES = _env_int("TRACKAROO_MWAVE_MAX_PAGES", 20)
```

Add matching lines to the docstring env table at the top of `config.py` (the block around lines 42-46 that documents `TRACKAROO_SCORPTEC_*`).

- [ ] **Step 4: Add the fetch layer to `scraper/mwave.py`**

```python
import time

import requests

from config import (
    MWAVE_MAX_RETRIES,
    MWAVE_RETRY_DELAY,
    MWAVE_TIMEOUT_SECONDS,
)

# The spike measured this precisely: a bare "Mozilla/5.0" got 403 Request
# blocked, while this full set was served 200 repeatedly. These headers are
# load-bearing, not decoration.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}

_WAF_MARKERS = ("awsWafCookieDomainList", "gokuProps", "challenge.js")


def is_waf_challenge(html: str) -> bool:
    """True when the response is an AWS WAF interstitial rather than content.

    Mwave returns these with HTTP 202, so the status code alone is not enough.
    """
    if not html:
        return False
    return any(marker in html for marker in _WAF_MARKERS)


def fetch_page(url: str) -> Optional[str]:
    """Fetch one page, or None.

    A WAF challenge returns None immediately and is NOT retried: retrying a
    challenge is what turns a soft throttle into a hard block. Transport
    errors are retried normally.
    """
    for attempt in range(MWAVE_MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=MWAVE_TIMEOUT_SECONDS)
            if is_waf_challenge(r.text):
                LOGGER.warning("Mwave returned a WAF challenge for %s -> backing off", url)
                return None
            if r.status_code == 200:
                return r.text
            LOGGER.warning("Mwave HTTP %s for %s", r.status_code, url)
            return None
        except requests.RequestException as e:
            LOGGER.warning("Mwave fetch error (attempt %d): %s", attempt + 1, e)
            if attempt < MWAVE_MAX_RETRIES:
                time.sleep(MWAVE_RETRY_DELAY)
    return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: PASS (all tests from Tasks 2 and 3).

- [ ] **Step 6: Commit**

```bash
git add scraper/mwave.py config.py unit_testing/test_mwave.py
git commit -m "feat(mwave): WAF-aware fetch layer with measured rate limits"
```

---

## Task 4: Category walk, watchlist matching, snapshot output

**Files:**
- Modify: `scraper/mwave.py`
- Test: `unit_testing/test_mwave.py`

**Interfaces:**
- Consumes: `fetch_page`, `parse_product_grid`, `MWAVE_PAGE_DELAY`, `MWAVE_MAX_PAGES`.
- Produces: `CATEGORY_URLS: Dict[str, List[str]]`, `scrape_all_pages(url: str) -> List[Dict]`, `scrape_mwave(watchlist) -> Tuple[List[Dict], Set[int], Dict]`, `main() -> None`.

**Reuse, do not reimplement:** `match_product` and `_is_bundle_product` in `scraper/scorptec.py:234` and `:219` already encode the longest-term-first matching rule and the bundle exclusions. Import them rather than writing new ones — divergence between retailers in what counts as a match is a data-integrity bug.

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import patch

from scraper.mwave import CATEGORY_URLS, scrape_all_pages


class TestCategoryUrls:
    def test_covers_both_categories(self):
        assert set(CATEGORY_URLS) == {"cpu", "gpu"}

    def test_every_url_is_absolute_and_mwave(self):
        for urls in CATEGORY_URLS.values():
            for u in urls:
                assert u.startswith("https://www.mwave.com.au/")


class TestScrapeAllPages:
    def test_stops_when_a_page_yields_nothing(self):
        pages = ["<grid1>", ""]
        with patch("scraper.mwave.fetch_page", side_effect=pages), \
             patch("scraper.mwave.parse_product_grid", side_effect=[[{"retailer_sku": "a"}], []]), \
             patch("scraper.mwave.time.sleep"):
            out = scrape_all_pages("https://www.mwave.com.au/graphics-cards")
        assert len(out) == 1

    def test_stops_on_a_waf_challenge_rather_than_continuing(self):
        """fetch_page returns None on a challenge; walking on would hammer it."""
        with patch("scraper.mwave.fetch_page", return_value=None), \
             patch("scraper.mwave.time.sleep"):
            out = scrape_all_pages("https://www.mwave.com.au/graphics-cards")
        assert out == []

    def test_deduplicates_across_pages(self):
        with patch("scraper.mwave.fetch_page", side_effect=["a", "b", ""]), \
             patch("scraper.mwave.parse_product_grid", side_effect=[
                 [{"retailer_sku": "x"}], [{"retailer_sku": "x"}], []]), \
             patch("scraper.mwave.time.sleep"):
            out = scrape_all_pages("https://www.mwave.com.au/graphics-cards")
        assert len(out) == 1

    def test_respects_the_page_cap(self):
        with patch("scraper.mwave.fetch_page", return_value="page"), \
             patch("scraper.mwave.parse_product_grid",
                   side_effect=lambda h: [{"retailer_sku": object()}]), \
             patch("scraper.mwave.time.sleep"), \
             patch("scraper.mwave.MWAVE_MAX_PAGES", 3) as _cap:
            out = scrape_all_pages("https://www.mwave.com.au/graphics-cards")
        assert len(out) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: FAIL — `ImportError: cannot import name 'CATEGORY_URLS'`

- [ ] **Step 3: Find the real CPU category URL before writing the constant**

`/graphics-cards` is confirmed. The CPU path is not. Discover it:

```bash
curl -s --max-time 25 \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36" \
  -H "Accept-Language: en-AU,en;q=0.9" \
  "https://www.mwave.com.au/" | grep -o 'href="/[a-z-]*processor[a-z-]*"\|href="/[a-z-]*cpu[a-z-]*"' | sort -u
```

Use whatever it prints. Wait 5s between this and any other request.

- [ ] **Step 4: Implement the walk and the entry point**

```python
from datetime import date
from typing import Set, Tuple

from config import DATA_DIR, FILE_DATE_FORMAT, MWAVE_MAX_PAGES, MWAVE_PAGE_DELAY, setup_logging
from db.watchlist import WatchlistProduct, load_watchlist
from scraper.scorptec import _is_bundle_product, match_product
from scraper.snapshot_io import build_snapshot, save_snapshot

# Replace the CPU entry with what Task 4 Step 3 discovered.
CATEGORY_URLS: Dict[str, List[str]] = {
    "gpu": [f"{BASE}/graphics-cards"],
    "cpu": [f"{BASE}/cpu-processors"],
}


def scrape_all_pages(url: str) -> List[Dict[str, Any]]:
    """Walk ?page=N until a page yields nothing, the cap is hit, or the WAF bites."""
    products: List[Dict[str, Any]] = []
    seen: set = set()

    for page in range(1, MWAVE_MAX_PAGES + 1):
        page_url = url if page == 1 else f"{url}?page={page}"
        html = fetch_page(page_url)
        if html is None:
            # Either a challenge or a hard error. Either way, stop -- the
            # partial result is still worth keeping and snapshot_io will
            # refuse to overwrite a richer file with it.
            LOGGER.warning("Mwave walk stopped at page %d of %s", page, url)
            break

        batch = parse_product_grid(html)
        if not batch:
            break

        new = [p for p in batch if p["retailer_sku"] not in seen]
        for p in new:
            seen.add(p["retailer_sku"])
        products.extend(new)

        if not new:
            break

        time.sleep(MWAVE_PAGE_DELAY)

    return products
```

Then add `scrape_mwave(watchlist)` and `main()` mirroring `scraper/scorptec.py:286` and `:480` exactly — same longest-term-first matching, same cheapest-in-stock-wins rule, same two output files. The only differences are `retailer="mwave"` and the output filename `f"{category}_mwave_{today}.json"`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest unit_testing/test_mwave.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scraper/mwave.py unit_testing/test_mwave.py
git commit -m "feat(mwave): category walk, watchlist matching, snapshot output"
```

---

## Task 5: Thread `mwave` through the nine hardcoded places

The scraper is useless until every one of these knows the name. Missing any one means data is silently dropped, not loudly rejected.

**Files:**
- Modify: `ingest.py:37`
- Modify: `health_checks.py:89`, `:229`, `:323`
- Modify: `check_staleness.py:49`
- Modify: `query.py:221`
- Modify: `run_daily.py:170-190`
- Test: `unit_testing/test_ingest.py`, `unit_testing/test_health_checks.py`, `unit_testing/test_check_staleness.py`

**No schema change is needed.** `db/schema.sql:37` already reads `CHECK (retailer IN ('scorptec', 'pccg', 'mwave'))`. Verify before assuming:

```bash
grep -n "CHECK (retailer" db/schema.sql
```

- [ ] **Step 1: Write the failing tests**

```python
# unit_testing/test_ingest.py
def test_snapshot_filename_regex_accepts_mwave():
    from ingest import _SNAPSHOT_FILENAME_RE
    assert _SNAPSHOT_FILENAME_RE.match("gpu_mwave_30_August_2026.json")
    assert _SNAPSHOT_FILENAME_RE.match("cpu_mwave_30_August_2026.json")


# unit_testing/test_check_staleness.py
def test_mwave_is_an_expected_retailer():
    from check_staleness import EXPECTED_RETAILERS
    assert "mwave" in EXPECTED_RETAILERS
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_ingest.py -k mwave unit_testing/test_check_staleness.py -k mwave -v`
Expected: FAIL.

- [ ] **Step 3: Make the edits**

```python
# ingest.py:37
_SNAPSHOT_FILENAME_RE = re.compile(r"^(?:cpu|gpu)_(?:scorptec|pccg|mwave)_\d{1,2}_\w+_\d{4}\.json$")

# check_staleness.py:49
EXPECTED_RETAILERS = ("scorptec", "pccg", "mwave")

# health_checks.py:89
expected_retailers = ["scorptec", "pccg", "mwave"]

# health_checks.py:229
expected_retailers = {"scorptec", "pccg", "mwave"}

# health_checks.py:323
for retailer in ("scorptec", "pccg", "mwave"):

# query.py:221
parser.add_argument("--retailer", type=str, choices=['scorptec', 'pccg', 'mwave'], help="Filter by retailer")
```

In `run_daily.py`, add the flag and the run block alongside the existing two:

```python
parser.add_argument("--mwave", action="store_true", help="Only run Mwave scraper")

# then, replacing the two run_* lines near :181
any_selected = args.scorptec or args.pccg or args.mwave
run_scorptec = (not any_selected) or args.scorptec
run_pccg = (not any_selected) or args.pccg
run_mwave = (not any_selected) or args.mwave

if not (run_scorptec or run_pccg or run_mwave):
    LOGGER.error("No scrapers selected. Use --scorptec, --pccg, --mwave, or none for all.")
    sys.exit(1)
```

and after the PCCG block:

```python
if run_mwave:
    time.sleep(SCRAPER_GAP_SECONDS)
    results["mwave"] = run_scraper("Mwave", "scraper.mwave", "mwave")
```

Update the `LOGGER.info("Scorptec: %s | PCCG: %s", ...)` line to include Mwave.

- [ ] **Step 4: Run the full backend suite**

Run: `python -m pytest -q`
Expected: PASS. Baseline was 650; expect ~680 with the new Mwave tests.

Some existing health-check tests assert on exact retailer counts and will need updating — that is expected and correct, not a reason to revert.

- [ ] **Step 5: Commit**

```bash
git add ingest.py health_checks.py check_staleness.py query.py run_daily.py unit_testing/
git commit -m "feat: thread mwave through ingest, health, staleness and the CLIs"
```

---

## Task 6: Live run and end-to-end verification

**Files:**
- Modify: `STATUS.md`
- Modify: `DEPLOYMENT.md` (retailer list)
- Modify: `README.md` (retailer list)

- [ ] **Step 1: Run the scraper alone against the real site**

```bash
python -m scraper.mwave
```

Expected: two files in `data/` — `cpu_mwave_<date>.json` and `gpu_mwave_<date>.json`. Check the match count is non-trivial:

```bash
python -c "
import json,glob
for f in sorted(glob.glob('data/*_mwave_*.json')):
    d=json.load(open(f))
    print(f, 'matched', d['matched'], 'of', d['total_watchlist'])
"
```

Expected: GPU matched >= 15. A matched count of 0 means the selectors or the matching are wrong — **do not ingest it**; go back to Task 2.

- [ ] **Step 2: Dry-run the ingest**

```bash
python ingest.py --dry-run
```

Expected: it reports the Mwave files and the listings it would create, with no errors. If it says nothing about Mwave, the filename regex in Task 5 is wrong.

- [ ] **Step 3: Back up, then ingest for real**

```bash
python backup_db.py
python run_daily.py --mwave
```

- [ ] **Step 4: Verify the data landed**

```bash
python -c "
import sqlite3
db=sqlite3.connect('db/trackaroo.db')
print('mwave listings:', db.execute(\"SELECT COUNT(*) FROM retailer_listings WHERE retailer='mwave'\").fetchone()[0])
print('mwave snapshots:', db.execute(\"SELECT COUNT(*) FROM price_snapshots ps JOIN retailer_listings l ON l.id=ps.retailer_listing_id WHERE l.retailer='mwave'\").fetchone()[0])
"
```

Expected: both non-zero.

- [ ] **Step 5: Run the full validation gate**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e
```

Expected: all green. The frontend needs no changes — `types.ts:7` and `filters.ts:8-15` already declare `mwave` — but the suites must still pass.

- [ ] **Step 6: Check the dashboard actually shows it**

```bash
cd web && npm run dev
```

Open the dashboard, confirm Mwave appears in the retailer filter on `/products` and that Mwave rows show up. Then stop the dev server.

- [ ] **Step 7: Update the docs**

Add a dated bullet under **Recent changes** in `STATUS.md` (do not start a nested "Prior update" chain). Update the retailer lists in `README.md` and `DEPLOYMENT.md`. Mark the Mwave item done in `docs/proposals/THIRD_RETAILER.md` and note what the WAF actually did in production.

- [ ] **Step 8: Commit and push**

```bash
git add -A
git commit -m "feat: add Mwave as the third retailer"
git push origin main
```

- [ ] **Step 9: Deploy**

On the prod host (192.168.10.163):

```bash
cd /path/to/Trackaroo
git pull
docker stop trackaroo && docker rm trackaroo
docker build -t trackaroo .
docker run -d --name trackaroo -p 3000:3000 --restart unless-stopped \
  --env-file .env -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" trackaroo
docker logs -f trackaroo
```

Watch the first scheduled run for WAF challenges in the log. If Mwave starts returning challenges in production, `TRACKAROO_MWAVE_PAGE_DELAY` is the knob — raise it before considering anything else.

---

## Deliberately out of scope

- **The `CHECK`-constraint / `retailers` lookup-table refactor.** Not needed for Mwave, which is already in the list. It is the prerequisite for retailer four — its own plan, with a rehearsed migration.
- **Umart and PLE.** Each needs a URL-discovery pass first (see the proposal).
- **Centre Com.** Ruled out — AWS WAF CAPTCHA on every path including `robots.txt`.
- **`check_delisted.py` support for Mwave.** Scorptec-specific today; add it once Mwave has a fortnight of clean history.
