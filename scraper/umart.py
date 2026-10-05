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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
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
from db.watchlist import load_retired, load_watchlist, WatchlistProduct
from scraper.catalogue_io import catalogue_item, save_catalogue
from scraper.chip_key import Matcher
from scraper.run_report import EXIT_OK, RunReport, exit_code_for
from scraper.snapshot_io import save_category_snapshot

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


def parse_product_grid(html: str, stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Parse one category page into product dicts.

    A card missing a price or an id is skipped rather than raising: one broken
    tile must not cost the whole day's run.

    Args:
        html: A category page body.
        stats: Optional counter dict updated with ``cards_seen`` and
            ``cards_dropped`` (#14).

    Returns:
        One dict per parsed product, with name, price_aud, stock_status, url
        and retailer_sku.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []
    cards = soup.find_all(class_="goods-item")
    dropped = 0

    for card in cards:
        sku = card.get("data-id")
        price = _price_from(card)
        if not sku or price is None:
            dropped += 1
            continue

        link = card.find("a", href=re.compile(r"/product/"))
        name_el = card.find(attrs={"itemprop": "name"})
        if name_el is not None:
            name = name_el.get_text(" ", strip=True)
        elif link is not None:
            name = link.get("title") or link.get_text(" ", strip=True)
        else:
            dropped += 1
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

    if stats is not None:
        stats["cards_seen"] = stats.get("cards_seen", 0) + len(cards)
        stats["cards_dropped"] = stats.get("cards_dropped", 0) + dropped
    if dropped:
        logger.warning("Dropped %d of %d Umart card(s): no id, price or name", dropped, len(cards))

    return products


def get_max_page(html: str) -> int:
    """Highest page number linked from a category page (1 when unpaginated)."""
    pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
    if not pages:
        return 1
    highest = max(pages)
    if highest > UMART_MAX_PAGES:
        # The cap used to apply silently, dropping every page past it (#14).
        logger.warning("Umart lists %d pages but UMART_MAX_PAGES is %d - pages %d-%d will not be scraped",
                       highest, UMART_MAX_PAGES, UMART_MAX_PAGES + 1, highest)
    return min(highest, UMART_MAX_PAGES)


def scrape_all_pages(category_url: str, stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Walk every page of one category.

    Page one is fetched first to learn the page count, rather than following
    "next" links, because Umart renders the full pager on every page. Pages
    attempted vs fetched go into ``stats`` so a hole is reported (#14).
    """
    counts = stats if stats is not None else {}
    counts["pages_attempted"] = counts.get("pages_attempted", 0) + 1
    first = fetch_page(category_url)
    if first is None:
        logger.warning("Umart category page 1 failed - category skipped: %s", category_url)
        return []
    counts["pages_fetched"] = counts.get("pages_fetched", 0) + 1

    products = parse_product_grid(first, stats=counts)
    last_page = get_max_page(first)
    logger.info("  page 1/%d: %d products", last_page, len(products))

    for page in range(2, last_page + 1):
        time.sleep(UMART_PAGE_DELAY)
        counts["pages_attempted"] += 1
        html = fetch_page(f"{category_url}?page={page}")
        if html is None:
            # A hole in the middle is not worth abandoning the rest for, but it
            # is no longer silent: the count lands in the run report.
            logger.warning("Umart page %d/%d failed - skipped (%d product(s) so far)",
                           page, last_page, len(products))
            continue
        counts["pages_fetched"] += 1
        page_products = parse_product_grid(html, stats=counts)
        logger.info("  page %d/%d: %d products", page, last_page, len(page_products))
        products.extend(page_products)

    return products


def scrape_umart(
    watchlist: List[WatchlistProduct],
    only_category: Optional[str] = None,
    report: Optional[RunReport] = None,
    retired: Sequence[WatchlistProduct] = (),
) -> Tuple[List[Dict[str, Any]], Set[int], Dict[str, List[Dict[str, Any]]]]:
    """Scrape Umart and match the watchlist against it.

    Each scraped product resolves to at most one watchlist row via the
    canonical chip-key ``Matcher`` (see ``scraper/chip_key.py``): exact key
    equality, with VRAM used only to disambiguate GPU rows that share a key.
    Bundle exclusion comes from the same matcher (``is_excluded`` covers
    "bundle" and "combo").

    Args:
        watchlist: Watchlist entries to match against.
        retired: Untracked rows, matched as sinks: a listing that resolves to one
            is dropped, so it cannot be mis-filed under a tracked sibling (#18).
        only_category: "cpu" or "gpu" to scrape one category; None for both.

    Returns:
        (results, matched watchlist indices, all scraped products per category).
    """
    matcher = Matcher([*watchlist, *retired])  # retired rows are sinks (#18)
    dropped = 0

    results: List[Dict[str, Any]] = []
    matched_ids: Set[int] = set()
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}

    for category, url in CATEGORY_URLS.items():
        if only_category and category != only_category:
            continue
        logger.info("Scraping Umart %s -> %s", category.upper(), url)
        scraped = scrape_all_pages(url, stats=report.category(category) if report is not None else None)
        all_scraped[category] = scraped
        logger.info("  %d products total for %s", len(scraped), category)

        for product in scraped:
            i = matcher.resolve(product["name"], category, product.get("full_description", ""))
            if i is None:
                continue
            if i >= len(watchlist):
                dropped += 1
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

    if dropped:
        logger.info("dropped %d listing(s) matched to retired products", dropped)
    return results, matched_ids, all_scraped


def catalogue_items(scraped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every scraped card, matched or not, in the catalogue shape (#16)."""
    return [
        catalogue_item(p["name"], p.get("url", ""), p.get("price_aud"), p.get("stock_status", "unknown"),
                       p.get("retailer_sku"))
        for p in scraped
    ]


def main() -> int:
    setup_logging()
    logger.info("Loading watchlist...")
    watchlist = load_watchlist()
    retired = load_retired()
    logger.info("  %d products in watchlist", len(watchlist))

    report = RunReport("umart")
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    for category in ("cpu", "gpu"):
        logger.info("\nScraping Umart %s...", category.upper())
        products, matched_ids, cat_scraped = scrape_umart(watchlist, only_category=category, report=report, retired=retired)
        # Saved per category so a timeout during GPUs keeps the CPUs (R2).
        save_category_snapshot(DATA_DIR, "umart", category, today, watchlist, products, matched_ids)
        try:
            save_catalogue(DATA_DIR, "umart", category, today,
                           catalogue_items([p for ps in cat_scraped.values() for p in ps]))
        except Exception as exc:  # the catalogue must never break a scrape (#16)
            logger.warning("Could not save umart %s catalogue: %s", category, exc)
        report.set(category, matched=len(products))
        report.flush()

    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, report.matched, len(watchlist))
    code = exit_code_for(report)
    if code != EXIT_OK:
        logger.error("Umart scrape incomplete: %s", {c: v["matched"] for c, v in report.categories.items()})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
