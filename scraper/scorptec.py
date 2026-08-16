"""
Scrape Scorptec for watchlist products and save results to JSON.

Usage: python fetch_test.py
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, FILE_DATE_FORMAT
from db.watchlist import load_watchlist, WatchlistProduct

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


def fetch_page(url: str, retries: int = 2) -> Optional[str]:
    """Fetch a URL with retries.

    Args:
        url: The URL to fetch.
        retries: Number of retry attempts after the initial try.

    Returns:
        The response text on success, or None if all attempts fail.
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.text
            logger.warning("Non-200 status %s for %s", r.status_code, url)
        except requests.RequestException as e:
            logger.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
            time.sleep(2)
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


def scrape_all_pages(url: str, category_path: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    """Scrape all pages of a Scorptec category, following pagination links.

    Args:
        url: Starting URL for the category.
        category_path: URL path segment for constructing fallback product URLs.
        max_pages: Safety limit to avoid infinite loops.

    Returns:
        All scraped products across all pages.
    """
    all_products: List[Dict[str, Any]] = []
    page = 1
    current_url = url

    while current_url and page <= max_pages:
        logger.info("Page %d: %s", page, current_url)
        time.sleep(0.5)  # Be polite between pages

        html = fetch_page(current_url)
        if not html:
            logger.warning("Failed to fetch page %d, stopping pagination.", page)
            break

        products = parse_product_grid(html, category_path=category_path)
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


def parse_product_grid(html: str, category_path: str = "") -> List[Dict[str, Any]]:
    """Extract products from Scorptec product-grid elements using data attributes.

    Args:
        html: Raw HTML from a Scorptec category page.
        category_path: URL path segment for constructing fallback product URLs
            when the server-side <a> tag has an empty href (Scorptec populates
            some links client-side via JavaScript). E.g. "cpu/intel" or
            "graphics-cards/nvidia".

    Returns:
        List of scraped product dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []
    for grid in soup.select(".product-grid"):
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
    """Check if a scraped product matches a watchlist entry using search terms.

    Uses the primary search term (e.g. 'rtx 5070') as the main matcher.
    Brand names like 'Nvidia' or 'AMD' often don't appear in scraped product names
    (e.g. 'ASUS Dual GeForce RTX 5070' has no 'Nvidia'), so we skip the brand check
    and rely on the specific model number in the search term.

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

    name_lower = scraped_name.lower()
    desc_lower = scraped_desc.lower()
    combined = f"{name_lower} {desc_lower}"

    search_terms = watchlist_product["search_terms"]
    if not search_terms:
        return False

    # Primary match: first search term must be in the combined text
    # This is the key identifier (e.g. 'rtx 5070', 'ryzen 7 5800x3d')
    primary_term = search_terms[0].lower()
    if primary_term not in combined:
        return False

    # Extra guard: for GPUs, check VRAM matches if present in the scraped name
    # This prevents 'rtx 5070' matching 'rtx 5070 ti' accidentally
    wp = watchlist_product
    if wp["category"] == "gpu" and wp.get("vram_gb"):
        vram = wp["vram_gb"]
        vram_str = f"{vram}gb"
        # VRAM must appear OR the model must be distinctive enough
        model_num = wp["model"].lower().split()[-1]  # e.g. '5070', '5090'
        if model_num in name_lower:
            return True
        if vram_str in combined:
            return True
        # If neither VRAM nor exact model number matched, reject
        return False

    return True


def scrape_scorptec(watchlist: List[WatchlistProduct]) -> Tuple[List[Dict[str, Any]], Set[int], Dict[str, List[Dict[str, Any]]]]:
    """Scrape Scorptec and match against watchlist.

    Key: when iterating the watchlist for each scraped product, we process
    entries with LONGER primary search terms first. This prevents substring
    conflicts — e.g. 'ryzen 5 5600' matching before 'ryzen 5 5600x' can.

    For each watchlist item, we capture ALL matching products and keep only
    the cheapest in-stock variant. This ensures we don't miss cheaper models
    (e.g., Zotac 5090 at $6,999 vs ASUS at $7,599).

    Args:
        watchlist: List of watchlist product dicts.

    Returns:
        Tuple of (matched results, matched watchlist ids, all scraped products per category).
    """
    # Build sorted index order: longer search terms first (more specific matches first)
    watchlist_order = sorted(
        range(len(watchlist)),
        key=lambda i: len(watchlist[i]["search_terms"][0]),
        reverse=True,
    )

    # Track ALL matches per watchlist item, then pick cheapest in-stock
    all_matches: Dict[int, List[Dict[str, Any]]] = {}  # watchlist_index -> list of matched product dicts
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}  # Track all scraped products per category for debugging

    for cat_key, cat_url in CATEGORY_URLS.items():
        logger.info("Scraping: %s -> %s", cat_key, cat_url)

        # Pass the category URL path so fallback URLs can be constructed
        fallback_path = CATEGORY_URL_PATHS.get(cat_key, "")
        # Scrape ALL pages, not just page 1
        scraped_products = scrape_all_pages(cat_url, category_path=fallback_path)
        all_scraped[cat_key] = scraped_products
        logger.info("Total for %s: %d products across all pages", cat_key, len(scraped_products))

        for scraped in scraped_products:
            if _is_bundle_product(scraped["name"], scraped.get("full_description", ""), scraped.get("url", "")):
                continue
            for i in watchlist_order:
                wp = watchlist[i]
                if match_product(scraped["name"], scraped["full_description"], wp):
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
                    if i not in all_matches:
                        all_matches[i] = []
                    all_matches[i].append(match_dict)
                    break  # One match per scraped product (avoid duplicate matches)

    # Save ALL in-stock variants for each watchlist item
    results: List[Dict[str, Any]] = []
    matched_watchlist_ids: Set[int] = set()
    for i, matches in all_matches.items():
        if not matches:
            continue
        # Keep only in-stock variants
        in_stock = [m for m in matches if m["stock_status"] == "in_stock"]
        if in_stock:
            results.extend(in_stock)
            matched_watchlist_ids.add(i)
            logger.info("%s: %d in-stock variants saved", watchlist[i]["model"], len(in_stock))
        else:
            # All out of stock — still save them for reference
            results.extend(matches)
            matched_watchlist_ids.add(i)
            logger.info("%s: %d variants found (all out of stock)", watchlist[i]["model"], len(matches))

    return results, matched_watchlist_ids, all_scraped


def analyze_unmatched(
    watchlist: List[WatchlistProduct],
    matched_ids: Set[int],
    all_scraped: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], List[Tuple[str, str, Optional[str]]]]:
    """Analyze why products weren't matched.

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

    for i, wp in enumerate(watchlist):
        if i in matched_ids:
            continue

        primary = wp["search_terms"][0] if wp["search_terms"] else ""
        found_anywhere = False
        matching_scraped: Optional[str] = None

        for cat_key, scraped in all_scraped.items():
            for s in scraped:
                if primary in s["name"].lower():
                    found_anywhere = True
                    matching_scraped = s["name"][:80]
                    break
            if found_anywhere:
                break

        if found_anywhere:
            possible_stocked.append((wp["model"], primary, matching_scraped))
        else:
            likely_delist.append(wp["model"])

    logger.info("\nLikely delisted at Scorptec (%d products):", len(likely_delist))
    for m in likely_delist:
        logger.info("  - %s", m)

    if possible_stocked:
        logger.info("\nPossibly stocked but matching issue (%d products):", len(possible_stocked))
        for model, primary, scraped_name in possible_stocked:
            logger.info("  - %s", model)
            logger.info("    Search term: '%s' found in: '%s'", primary, scraped_name)

    return likely_delist, possible_stocked


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Loading watchlist...")
    watchlist = load_watchlist()
    logger.info("  %d products in watchlist", len(watchlist))

    logger.info("\nScraping Scorptec...")
    results, matched_ids, all_scraped = scrape_scorptec(watchlist)

    # Report
    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, len(results), len(watchlist))

    # Analyze unmatched
    delisted, matching_issues = analyze_unmatched(watchlist, matched_ids, all_scraped)

    # Build unmatched list
    unmatched_models = [wp["model"] for i, wp in enumerate(watchlist) if i not in matched_ids]

    # Save to separate CPU and GPU JSON files
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    cpu_results = [p for p in results if p["watchlist_category"] == "cpu"]
    gpu_results = [p for p in results if p["watchlist_category"] == "gpu"]
    cpu_unmatched = [m for m in unmatched_models if any(
        wp["model"] == m and wp["category"] == "cpu" for wp in watchlist
    )]
    gpu_unmatched = [m for m in unmatched_models if any(
        wp["model"] == m and wp["category"] == "gpu" for wp in watchlist
    )]

    for category, products, unmatched in [
        ("cpu", cpu_results, cpu_unmatched),
        ("gpu", gpu_results, gpu_unmatched),
    ]:
        output_file = DATA_DIR / f"{category}_scorptec_{today}.json"
        output_data = {
            "retailer": "scorptec",
            "scrape_date": today,
            "category": category,
            "total_watchlist": len(watchlist),
            "matched": len(products),
            "unmatched_count": len(unmatched),
            "unmatched_models": unmatched,
            "products": products,
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        logger.info("\nSaved to: %s", output_file)


if __name__ == "__main__":
    main()
