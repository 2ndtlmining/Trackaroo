"""
Scrape Scorptec for watchlist products and save results to JSON.

Usage: python -m scraper.scorptec
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

from config import (
    DATA_DIR,
    FILE_DATE_FORMAT,
    SCORPTEC_MAX_PAGES,
    SCORPTEC_MAX_RETRIES,
    SCORPTEC_PAGE_DELAY,
    SCORPTEC_RETRY_DELAY,
    SCORPTEC_TIMEOUT_SECONDS,
    setup_logging,
)
from db.watchlist import load_watchlist, WatchlistProduct
from scraper.catalogue_io import catalogue_item, save_catalogue
from scraper.chip_key import Matcher, normalise
from scraper.run_report import EXIT_OK, RunReport, exit_code_for
from scraper.snapshot_io import save_category_snapshot

logger = logging.getLogger(__name__)

UA = "Trackaroo/1.0 (Personal price tracker; daily snapshots)"
HEADERS = {"User-Agent": UA}
BASE = "https://www.scorptec.com.au"

# Category pages to scrape per product type
CATEGORY_URLS: Dict[str, str] = {
    "cpu_amd_am4": f"{BASE}/product/cpu/amd-am4-5000",
    "cpu_amd_am5_7000": f"{BASE}/product/cpu/amd-am5-7000",
    "cpu_amd_am5_8000": f"{BASE}/product/cpu/amd-am5-8000",
    "cpu_amd_am5_9000": f"{BASE}/product/cpu/amd-am5-9000",
    "cpu_intel_all": f"{BASE}/product/cpu/intel",
    "gpu_nvidia": f"{BASE}/product/graphics-cards/nvidia",
    "gpu_amd": f"{BASE}/product/graphics-cards/amd",
    "gpu_intel": f"{BASE}/product/graphics-cards/intel",
}

# Fallback URL category paths — when a product <a> tag has an empty href
# (Scorptec populates some links client-side via JavaScript), we construct
# the URL from the SKU using the correct product-detail path.
CATEGORY_URL_PATHS: Dict[str, str] = {
    "cpu_amd_am4": "cpu/amd-socket-am4",
    "cpu_amd_am5_7000": "cpu/amd-socket-am5",
    "cpu_amd_am5_8000": "cpu/amd-socket-am5",
    "cpu_amd_am5_9000": "cpu/amd-socket-am5",
    "cpu_intel_all": "cpu/intel",
    "gpu_nvidia": "graphics-cards/nvidia",
    "gpu_amd": "graphics-cards/amd",
    "gpu_intel": "graphics-cards/intel",
}


def fetch_page(url: str, retries: Optional[int] = None) -> Optional[str]:
    """Fetch a URL with retries.

    Args:
        url: The URL to fetch.
        retries: Number of retry attempts after the initial try. Defaults to
            config.SCORPTEC_MAX_RETRIES.

    Returns:
        The response text on success, or None if all attempts fail.
    """
    if retries is None:
        retries = SCORPTEC_MAX_RETRIES
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=SCORPTEC_TIMEOUT_SECONDS)
            if r.status_code == 200:
                return r.text
            logger.warning("Non-200 status %s for %s (attempt %d/%d)",
                           r.status_code, url, attempt + 1, retries + 1)
        except requests.RequestException as e:
            logger.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
        # Back off before every retry. A non-200 used to be retried at once:
        # a burst of requests at a CDN that had just refused one (#14).
        if attempt < retries:
            time.sleep(SCORPTEC_RETRY_DELAY)
    return None


def get_next_page_url(html: str, base_url: str) -> Optional[str]:
    """Extract the next page URL from a Scorptec pagination link.

    Scorptec uses a '.next' CSS class on the pagination <a> tag for the
    next page. Returns None if there is no next page.

    Args:
        html: Raw HTML from the current category page.
        base_url: Base URL for resolving relative links.

    Returns:
        Full URL of the next page, or None if this is the last page.
    """
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("a.next[href]")
    if next_link:
        href = str(next_link["href"])
        if href.startswith("http"):
            return href
        return f"{BASE}{href}"
    return None


def scrape_all_pages(
    url: str,
    category_path: str,
    max_pages: int = SCORPTEC_MAX_PAGES,
    stats: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Scrape all pages of a Scorptec category, following pagination links.

    Args:
        url: Starting URL for the category.
        category_path: URL path segment for constructing fallback product URLs.
        max_pages: Safety limit to avoid infinite loops. Defaults to
            config.SCORPTEC_MAX_PAGES.
        stats: Optional counter dict updated with ``pages_attempted``,
            ``pages_fetched``, ``cards_seen`` and ``cards_dropped`` (#14).

    Returns:
        All scraped products across all pages.
    """
    counts = stats if stats is not None else {}
    all_products: List[Dict[str, Any]] = []
    page = 1
    current_url = url

    while current_url and page <= max_pages:
        logger.info("Page %d: %s", page, current_url)
        time.sleep(SCORPTEC_PAGE_DELAY)  # Be polite between pages

        counts["pages_attempted"] = counts.get("pages_attempted", 0) + 1
        html = fetch_page(current_url)
        if not html:
            logger.warning("Failed to fetch page %d, stopping pagination (%d product(s) kept from earlier pages).",
                           page, len(all_products))
            break
        counts["pages_fetched"] = counts.get("pages_fetched", 0) + 1

        products = parse_product_grid(html, category_path=category_path, stats=counts)
        all_products.extend(products)
        logger.info(
            "Found %d products on page %d (%d total)",
            len(products),
            page,
            len(all_products),
        )

        # Check if there's a next page
        next_url = get_next_page_url(html, url)
        if not next_url:
            logger.info("No more pages. Total: %d products.", len(all_products))
            break

        page += 1
        current_url = next_url

    if page > max_pages:
        logger.info("Reached max pages (%d). Total: %d products.", max_pages, len(all_products))

    return all_products


def parse_product_grid(
    html: str, category_path: str = "", stats: Optional[Dict[str, int]] = None
) -> List[Dict[str, Any]]:
    """Extract products from Scorptec product-grid elements using data attributes.

    Args:
        html: Raw HTML from a Scorptec category page.
        category_path: URL path segment for constructing fallback product URLs
            when the server-side <a> tag has an empty href (Scorptec populates
            some links client-side via JavaScript). E.g. "cpu/intel" or
            "graphics-cards/nvidia".
        stats: Optional counter dict updated with ``cards_seen`` and
            ``cards_dropped`` (#14).

    Returns:
        List of scraped product dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []
    grids = soup.select(".product-grid")
    dropped = 0
    for grid in grids:
        # Data attributes are the most reliable source
        name = str(grid.get("data-shortintro", ""))
        full_desc = str(grid.get("data-intro", ""))
        price_str = str(grid.get("data-price", ""))
        instock = str(grid.get("data-instock", ""))
        sku = str(grid.get("data-sku", ""))

        # Get link from the title element
        title_link = grid.select_one(".grid-product-title a[href]")
        url = str(title_link["href"]) if title_link else ""
        if url and not url.startswith("http"):
            url = BASE + url

        # Fallback: when href is empty (JS-populated link), construct URL from SKU
        if not url and sku and category_path:
            url = f"{BASE}/product/{category_path}/{sku}"

        # Parse price
        price: Optional[float] = None
        if price_str:
            try:
                price = float(price_str)
            except ValueError:
                logger.debug("Could not parse price %r for %s", price_str, name)

        # Parse stock status
        stock = "unknown"
        if instock == "1":
            stock = "in_stock"
        elif instock == "0":
            stock = "out_of_stock"

        if name and price is not None:
            products.append({
                "name": name,
                "full_description": full_desc,
                "price_aud": price,
                "stock_status": stock,
                "url": url,
                "retailer_sku": sku,
            })
        else:
            dropped += 1
            logger.debug("Dropped card sku=%r: name=%r price=%r", sku, name, price_str)

    if stats is not None:
        stats["cards_seen"] = stats.get("cards_seen", 0) + len(grids)
        stats["cards_dropped"] = stats.get("cards_dropped", 0) + dropped
    if dropped:
        logger.warning("Dropped %d of %d product card(s): no name or unparseable price", dropped, len(grids))
    return products


def _is_bundle_product(name: str, desc: str = "", url: str = "") -> bool:
    """Return True if the listing is a component bundle (e.g. CPU + motherboard).

    Scorptec sells combos like "gigabyte z890 ultra 5 power bundle". These price
    the whole combo, not the CPU alone, so they must never match a CPU-only
    watchlist product. Signals: the word 'bundle'/'combo' in the name/description,
    or the Scorptec bundle URL pattern (/bundle/ or '-bdl-' slug).
    """
    haystack = f"{name.lower()} {desc.lower()}"
    if "bundle" in haystack or "combo" in haystack:
        return True
    url_lower = url.lower()
    return "/bundle/" in url_lower or "-bdl-" in url_lower


def match_product(scraped_name: str, scraped_desc: str, watchlist_product: WatchlistProduct) -> bool:
    """Check if a scraped product matches a watchlist entry.

    Matching is exact chip-key equality (see `scraper/chip_key.py`): the
    scraped name is reduced to a canonical key such as `rtx 5060 ti` or
    `ryzen 5500gt`, and it matches only when that key equals the watchlist
    row's own key. Search terms are no longer used to match; they still
    drive PCCG's Algolia search queries.

    Args:
        scraped_name: Name of the scraped product.
        scraped_desc: Full description of the scraped product.
        watchlist_product: Watchlist entry to test against.

    Returns:
        True if the scraped product matches the watchlist entry.
    """
    # Component bundles (CPU + motherboard) must not match a single component
    if _is_bundle_product(scraped_name, scraped_desc):
        return False
    return Matcher([watchlist_product]).resolve(
        scraped_name, watchlist_product["category"], scraped_desc
    ) == 0


def scrape_scorptec(
    watchlist: List[WatchlistProduct],
    only_category: Optional[str] = None,
    report: Optional["RunReport"] = None,
) -> Tuple[List[Dict[str, Any]], Set[int], Dict[str, List[Dict[str, Any]]]]:
    """Scrape Scorptec and match against watchlist.

    Each scraped product resolves to at most one watchlist row via the
    canonical chip-key `Matcher` (see `scraper/chip_key.py`): exact key
    equality, with VRAM used only to disambiguate GPU rows that share a key.

    For each watchlist item, we capture ALL matching products and keep only
    the cheapest in-stock variant. This ensures we don't miss cheaper models
    (e.g., Zotac 5090 at $6,999 vs ASUS at $7,599).

    Args:
        watchlist: List of watchlist product dicts.
        only_category: "cpu" or "gpu" to scrape one category; None for both.

    Returns:
        Tuple of (matched results, matched watchlist ids, all scraped products per category).
    """
    matcher = Matcher(watchlist)

    # Track ALL matches per watchlist item, then pick cheapest in-stock
    all_matches: Dict[int, List[Dict[str, Any]]] = {}  # watchlist_index -> list of matched product dicts
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}  # Track all scraped products per category for debugging

    for cat_key, cat_url in CATEGORY_URLS.items():
        if only_category and not cat_key.startswith(f"{only_category}_"):
            continue
        logger.info("Scraping: %s -> %s", cat_key, cat_url)

        # Pass the category URL path so fallback URLs can be constructed
        fallback_path = CATEGORY_URL_PATHS.get(cat_key, "")
        category = cat_key.split("_", 1)[0]  # "cpu_amd_am4" -> "cpu"
        stats = report.category(category) if report is not None else None
        # Scrape ALL pages, not just page 1
        scraped_products = scrape_all_pages(cat_url, category_path=fallback_path, stats=stats)
        all_scraped[cat_key] = scraped_products
        logger.info("Total for %s: %d products across all pages", cat_key, len(scraped_products))

        for scraped in scraped_products:
            if _is_bundle_product(scraped["name"], scraped.get("full_description", ""), scraped.get("url", "")):
                continue
            i = matcher.resolve(scraped["name"], category, scraped.get("full_description", ""))
            if i is None:
                continue
            wp = watchlist[i]
            match_dict = {
                "watchlist_model": wp["model"],
                "watchlist_category": wp["category"],
                "watchlist_brand": wp["brand"],
                "watchlist_gen_tier": wp["gen_tier"],
                "retailer": "scorptec",
                "scraped_name": scraped["name"],
                "price_aud": scraped["price_aud"],
                "stock_status": scraped["stock_status"],
                "url": scraped["url"],
                "retailer_sku": scraped["retailer_sku"],
            }
            all_matches.setdefault(i, []).append(match_dict)

    # Save ALL matched variants for each watchlist item — regardless of stock
    # state. An out-of-stock variant's price history still matters, and this
    # matches PCCG's behaviour (see scrape_category). Without it, an OOS card
    # whose sibling variant is buyable would quietly stop receiving snapshots.
    results: List[Dict[str, Any]] = []
    matched_watchlist_ids: Set[int] = set()
    for i, matches in all_matches.items():
        if not matches:
            continue
        results.extend(matches)
        matched_watchlist_ids.add(i)
        logger.info("%s: %d variants saved", watchlist[i]["model"], len(matches))

    return results, matched_watchlist_ids, all_scraped


def _term_matches_only_variants(term: str, name_lower: str) -> bool:
    """Return True when ``term`` appears in ``name_lower`` only as the prefix
    of a longer variant code (e.g. 'ryzen 9 9900' inside 'ryzen 9 9900x', or
    'core ultra 5 245' inside 'core ultra 5 245k').

    A standalone occurrence — end of string, punctuation, a directly-following
    digit like '12gb', or a space followed by a long descriptor word like
    'processor' or 'windforce' — makes this return False.

    Mirrors the variant-substring guard used by the PCCG matcher, so the
    unmatched-product analysis doesn't cry wolf over a base model that the
    retailer simply doesn't carry (it only stocks the X/X3D/K variant).

    Args:
        term: Lowercased search term, e.g. 'ryzen 9 9900'.
        name_lower: Lowercased scraped product name.

    Returns:
        True if every occurrence of ``term`` is inside a longer variant code.
    """
    start = 0
    while True:
        pos = name_lower.find(term, start)
        if pos == -1:
            break
        after = pos + len(term)
        p = after
        while p < len(name_lower) and name_lower[p] == " ":
            p += 1
        if p >= len(name_lower) or not name_lower[p].isalnum():
            # End of string or followed by punctuation: a standalone identifier.
            return False
        if p > after and name_lower[p].isdigit():
            # '5070 12gb' — spec figures after the model, still the same product.
            return False
        if p > after:
            word_end = p
            while word_end < len(name_lower) and name_lower[word_end].isalnum():
                word_end += 1
            if word_end - p >= 6:
                # '5070 windforce' — a descriptor word, not a variant suffix.
                return False
        # Directly-attached alnum ('9900' + 'x') or a short word after a space
        # ('5070 ti') — a longer variant code. Keep scanning for a real match.
        start = after
    return True


def analyze_unmatched(
    watchlist: List[WatchlistProduct],
    matched_ids: Set[int],
    all_scraped: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], List[Tuple[str, str, Optional[str]]]]:
    """Analyze why products weren't matched.

    An unmatched product whose search term never appears in any scraped name
    is likely delisted. A term that appears only inside a longer variant code
    (e.g. 'ryzen 9 9900' inside a '9900x' listing) means the base model isn't
    stocked — informative, but not a matching bug. Only a term present as a
    genuine standalone match that still didn't pair is a real matching issue.

    Args:
        watchlist: List of watchlist product dicts.
        matched_ids: Set of watchlist indices that matched.
        all_scraped: All scraped products per category key.

    Returns:
        Tuple of (likely delisted model names, possible stock/match issues).
    """
    logger.info("\n%s\nUnmatched product analysis:\n%s", "=" * 60, "=" * 60)

    likely_delist: List[str] = []
    possible_stocked: List[Tuple[str, str, Optional[str]]] = []
    variant_only: List[Tuple[str, str, Optional[str]]] = []

    for i, wp in enumerate(watchlist):
        if i in matched_ids:
            continue

        # The model name, normalised so "Core i5-14400F" finds "core i5 14400f"
        # (#20: there are no search aliases any more).
        primary = normalise(wp["model"])
        if not primary:
            continue

        matching_names: List[str] = []
        for cat_key, scraped in all_scraped.items():
            for s in scraped:
                if primary in normalise(s["name"]):
                    matching_names.append(s["name"][:80])

        if not matching_names:
            likely_delist.append(wp["model"])
            continue

        if all(_term_matches_only_variants(primary, normalise(n)) for n in matching_names):
            variant_only.append((wp["model"], primary, matching_names[0]))
        else:
            possible_stocked.append((wp["model"], primary, matching_names[0]))

    logger.info("\nLikely delisted at Scorptec (%d products):", len(likely_delist))
    for m in likely_delist:
        logger.info("  - %s", m)

    if variant_only:
        logger.info("\nOnly stocked as a different variant (%d products):", len(variant_only))
        for model, primary, scraped_name in variant_only:
            logger.info("  - %s", model)
            logger.info("    '%s' found only inside: '%s'", primary, scraped_name)

    if possible_stocked:
        logger.info("\nPossibly stocked but matching issue (%d products):", len(possible_stocked))
        for model, primary, scraped_name in possible_stocked:
            logger.info("  - %s", model)
            logger.info("    Search term: '%s' found in: '%s'", primary, scraped_name)

    return likely_delist, possible_stocked


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
    logger.info("  %d products in watchlist", len(watchlist))

    report = RunReport("scorptec")
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    results: List[Dict[str, Any]] = []
    matched_ids: Set[int] = set()
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}
    for category in ("cpu", "gpu"):
        logger.info("\nScraping Scorptec %s...", category.upper())
        cat_results, cat_ids, cat_scraped = scrape_scorptec(watchlist, only_category=category, report=report)
        # Saved the moment the category is done. run_daily kills a scraper at
        # SCRAPER_TIMEOUT_SECONDS, and results used to be saved only at the very
        # end, so a slow GPU pass cost the finished CPUs as well (R2).
        save_category_snapshot(DATA_DIR, "scorptec", category, today, watchlist, cat_results, cat_ids)
        try:
            save_catalogue(DATA_DIR, "scorptec", category, today,
                           catalogue_items([p for ps in cat_scraped.values() for p in ps]))
        except Exception as exc:  # the catalogue must never break a scrape (#16)
            logger.warning("Could not save scorptec %s catalogue: %s", category, exc)
        report.set(category, matched=len(cat_results))
        report.flush()
        results.extend(cat_results)
        matched_ids |= cat_ids
        all_scraped.update(cat_scraped)

    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, len(results), len(watchlist))
    analyze_unmatched(watchlist, matched_ids, all_scraped)

    code = exit_code_for(report)
    if code != EXIT_OK:
        logger.error("Scorptec scrape incomplete: %s", {c: v["matched"] for c, v in report.categories.items()})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
