"""
Scrape Umart for watchlist products and save results to JSON.

Usage: python -m scraper.umart

Umart is the plainest of the three retailers: server-rendered category pages,
no WAF, and a `robots.txt` that permits product and category paths. The grid
carries schema.org microdata, so the parser reads attributes rather than text.

Two things here are the product of a discovery pass on 31-Aug-2026 that is
written up in `docs/proposals/THIRD_RETAILER.md`:

* **The category URL scheme.** An earlier guess used `_1350G.html` and bounced
  to the homepage, which got Umart filed as "unassessed" for a week. `G` is the
  *goods* form; categories are path-based with a trailing numeric id, and they
  are listed on the homepage. No guessing is needed, and none is done here.
* **Prices are read from the `content` attribute, never the text.** The visible
  price renders as ``$&nbsp;579.00``. A dollar-sign regex over the raw HTML
  therefore matches nothing, which makes the page look client-rendered when it
  is not -- a wrong turn this project made twice. ``content="579.00"`` has no
  entity in it and no currency symbol to strip.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    DATA_DIR,
    FILE_DATE_FORMAT,
    UMART_MAX_PAGES,
    UMART_MAX_RETRIES,
    UMART_PAGE_DELAY,
    UMART_RETRY_DELAY,
    UMART_TIMEOUT_SECONDS,
    setup_logging,
)
from db.watchlist import load_watchlist, WatchlistProduct
from scraper.chip_key import Matcher
from scraper.run_report import EXIT_DEGRADED, EXIT_OK
from scraper.snapshot_io import build_snapshot, save_snapshot

logger = logging.getLogger(__name__)

UA = "Trackaroo/1.0 (Personal price tracker; daily snapshots)"
HEADERS = {"User-Agent": UA}
BASE = "https://www.umart.com.au"

# Category listing pages, discovered from the homepage rather than guessed.
# 20 products per page: ~11 pages of GPUs and ~3 of CPUs as at 31-Aug-2026.
CATEGORY_URLS: Dict[str, str] = {
    "cpu": f"{BASE}/pc-parts/computer-parts/cpu-processors-611",
    "gpu": f"{BASE}/pc-parts/computer-parts/graphics-cards-gpu-610",
}

# schema.org availability -> the DB's stock_status vocabulary. Anything Umart
# reports that is not one of these reads as 'unknown' rather than guessing, so a
# new availability value shows up in the data instead of being silently coerced
# to "in stock".
_AVAILABILITY = {
    "instock": "in_stock",
    "outofstock": "out_of_stock",
    "preorder": "preorder",
    "backorder": "preorder",
}


def fetch_page(url: str, retries: Optional[int] = None) -> Optional[str]:
    """Fetch one page, returning None rather than raising on failure.

    Args:
        url: Absolute URL to fetch.
        retries: Attempts before giving up. Defaults to UMART_MAX_RETRIES.

    Returns:
        The response body, or None if every attempt failed.
    """
    attempts = UMART_MAX_RETRIES if retries is None else retries

    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=HEADERS, timeout=UMART_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return response.text
            logger.warning("  HTTP %s for %s", response.status_code, url)
        except requests.RequestException as exc:
            logger.warning("  Request failed for %s: %s", url, exc)

        if attempt < attempts - 1:
            time.sleep(UMART_RETRY_DELAY)

    logger.error("  Giving up on %s after %d attempt(s)", url, attempts)
    return None


def _price_from(card: Any) -> Optional[float]:
    """Read the price out of the microdata `content` attribute.

    Deliberately not parsed from the rendered text: that is ``$&nbsp;579.00``.
    """
    el = card.find(attrs={"itemprop": "price"})
    if el is None:
        return None
    raw = el.get("content") or el.get_text(strip=True)
    if not raw:
        return None
    try:
        return float(str(raw).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _stock_from(card: Any) -> str:
    """Map schema.org availability onto the DB's stock vocabulary."""
    el = card.find(attrs={"itemprop": "availability"})
    href = (el.get("href") or "") if el is not None else ""
    token = href.rstrip("/").rsplit("/", 1)[-1].lower()
    return _AVAILABILITY.get(token, "unknown")


def parse_product_grid(html: str) -> List[Dict[str, Any]]:
    """Parse one category page into product dicts.

    A card missing a price or an id is skipped rather than raising: one broken
    tile must not cost the whole day's run.

    Args:
        html: A category page body.

    Returns:
        One dict per parsed product, with name, price_aud, stock_status, url
        and retailer_sku.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []

    for card in soup.find_all(class_="goods-item"):
        sku = card.get("data-id")
        price = _price_from(card)
        if not sku or price is None:
            continue

        link = card.find("a", href=re.compile(r"/product/"))
        name_el = card.find(attrs={"itemprop": "name"})
        if name_el is not None:
            name = name_el.get_text(" ", strip=True)
        elif link is not None:
            name = link.get("title") or link.get_text(" ", strip=True)
        else:
            continue

        products.append(
            {
                "name": name,
                "full_description": name,
                "price_aud": price,
                "stock_status": _stock_from(card),
                "url": urljoin(BASE, link["href"]) if link else "",
                "retailer_sku": str(sku),
            }
        )

    return products


def get_max_page(html: str) -> int:
    """Highest page number linked from a category page (1 when unpaginated)."""
    pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
    return min(max(pages), UMART_MAX_PAGES) if pages else 1


def scrape_all_pages(category_url: str) -> List[Dict[str, Any]]:
    """Walk every page of one category.

    Page one is fetched first to learn the page count, rather than following
    "next" links, because Umart renders the full pager on every page.
    """
    first = fetch_page(category_url)
    if first is None:
        return []

    products = parse_product_grid(first)
    last_page = get_max_page(first)
    logger.info("  page 1/%d: %d products", last_page, len(products))

    for page in range(2, last_page + 1):
        time.sleep(UMART_PAGE_DELAY)
        html = fetch_page(f"{category_url}?page={page}")
        if html is None:
            # A hole in the middle of a category is not worth abandoning the
            # rest for: the missing products simply go unmatched today.
            continue
        page_products = parse_product_grid(html)
        logger.info("  page %d/%d: %d products", page, last_page, len(page_products))
        products.extend(page_products)

    return products


def scrape_umart(
    watchlist: List[WatchlistProduct],
) -> Tuple[List[Dict[str, Any]], Set[int], Dict[str, List[Dict[str, Any]]]]:
    """Scrape Umart and match the watchlist against it.

    Each scraped product resolves to at most one watchlist row via the
    canonical chip-key ``Matcher`` (see ``scraper/chip_key.py``): exact key
    equality, with VRAM used only to disambiguate GPU rows that share a key.
    Bundle exclusion comes from the same matcher (``is_excluded`` covers
    "bundle" and "combo").

    Args:
        watchlist: Watchlist entries to match against.

    Returns:
        (results, matched watchlist indices, all scraped products per category).
    """
    matcher = Matcher(watchlist)

    results: List[Dict[str, Any]] = []
    matched_ids: Set[int] = set()
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}

    for category, url in CATEGORY_URLS.items():
        logger.info("Scraping Umart %s -> %s", category.upper(), url)
        scraped = scrape_all_pages(url)
        all_scraped[category] = scraped
        logger.info("  %d products total for %s", len(scraped), category)

        for product in scraped:
            i = matcher.resolve(product["name"], category, product.get("full_description", ""))
            if i is None:
                continue
            wp = watchlist[i]
            results.append(
                {
                    "watchlist_model": wp["model"],
                    "watchlist_category": wp["category"],
                    "watchlist_brand": wp["brand"],
                    "watchlist_gen_tier": wp["gen_tier"],
                    "retailer": "umart",
                    "scraped_name": product["name"],
                    "price_aud": product["price_aud"],
                    "stock_status": product["stock_status"],
                    "url": product["url"],
                    "retailer_sku": product["retailer_sku"],
                }
            )
            matched_ids.add(i)

    return results, matched_ids, all_scraped


def main() -> int:
    setup_logging()
    logger.info("Loading watchlist...")
    watchlist = load_watchlist()
    logger.info("  %d products in watchlist", len(watchlist))

    logger.info("\nScraping Umart...")
    results, matched_ids, _ = scrape_umart(watchlist)

    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, len(results), len(watchlist))

    unmatched_models = [wp["model"] for i, wp in enumerate(watchlist) if i not in matched_ids]

    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    counts: Dict[str, int] = {}
    for category in ("cpu", "gpu"):
        products = [p for p in results if p["watchlist_category"] == category]
        counts[category] = len(products)
        unmatched = [
            m
            for m in unmatched_models
            if any(wp["model"] == m and wp["category"] == category for wp in watchlist)
        ]
        output_file = DATA_DIR / f"{category}_umart_{today}.json"
        output_data = build_snapshot(
            retailer="umart",
            scrape_date=today,
            category=category,
            total_watchlist=len(watchlist),
            products=products,
            unmatched_models=unmatched,
        )
        save_snapshot(output_file, output_data)

    if not all(counts.values()):
        logger.error("Umart scrape incomplete: %s", counts)
        return EXIT_DEGRADED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
