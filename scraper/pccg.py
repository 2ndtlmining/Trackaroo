"""PC Case Gear scraper — uses PCCG's Algolia search API directly.
No Playwright needed — we query the Algolia index that powers PCCG's site search.
Uses batched multi-query requests to avoid rate limiting.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import requests

from config import (
    ALGOLIA_BACKOFF_MAX_SECONDS,
    ALGOLIA_MAX_RETRIES,
    ALGOLIA_RATE_LIMIT_WAIT_SECONDS,
    ALGOLIA_TIMEOUT_SECONDS,
    BATCH_DELAY,
    BATCH_SIZE,
    DATA_DIR,
    FILE_DATE_FORMAT,
)
from db.watchlist import load_watchlist, WatchlistProduct

LOGGER = logging.getLogger(__name__)

# Algolia API credentials (embedded in PCCG page source — read-only search key).
# Overridable via environment variables so secrets stay out of source control.
ALGOLIA_APP_ID = os.environ.get("ALGOLIA_APP_ID", "HPD3DBJ2IO")
ALGOLIA_API_KEY = os.environ.get("ALGOLIA_API_KEY", "9559cf1a6c7521a30ba0832ec6c38499")
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_INDEX = "pccg_products"
PCCG_BASE = "https://www.pccasegear.com"

# Fields requested from the Algolia index. indicator.* carries the displayed
# stock state ("In stock" / "Sold Out" / "ETA: ..." / "Stock at Supplier");
# is_ETA_TBA is a secondary on-order signal used if the label is missing.
STOCK_ATTRS = "products_name,products_price,products_model,Product_URL,manufacturers_name,indicator,is_ETA_TBA"

HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
}

# Batch size for multi-query requests (config-driven — see TRACKAROO_BATCH_SIZE)


def match_product(scraped_name: str, watchlist_product: WatchlistProduct) -> bool:
    """Check if a scraped product matches a watchlist entry."""
    name_lower = scraped_name.lower()
    search_terms = watchlist_product["search_terms"]
    if not search_terms:
        return False
    primary_term = search_terms[0].lower()
    if primary_term not in name_lower:
        return False
    # Guard: ensure the match isnt a substring of a different variant
    # e.g., "5800x" should not match "5800x3d", "9900" should not match "9900x",
    # "rtx 5070" should not match "rtx 5070 ti"
    match_end = name_lower.index(primary_term) + len(primary_term)
    # Check if there's a space after the match (for space-separated variants)
    had_space = match_end < len(name_lower) and name_lower[match_end] == " "
    # Skip whitespace to find the next meaningful character
    pos = match_end
    while pos < len(name_lower) and name_lower[pos] == " ":
        pos += 1
    # Directly-attached variant: no space + alphanumeric char (e.g., "5800x" + "3d", "14700k" + "f")
    if not had_space and pos < len(name_lower) and name_lower[pos].isalnum():
        return False
    # Space-separated variant: search term ends with digit + short word follows
    # Short words (< 6 chars) like "Ti", "X", "3D" are variants;
    # longer words like "Processor", "Windforce" are generic descriptors.
    if primary_term and primary_term[-1].isdigit() and pos < len(name_lower):
        if name_lower[pos].isalpha():
            word_end = pos
            while word_end < len(name_lower) and name_lower[word_end].isalnum():
                word_end += 1
            if word_end - pos < 6:
                return False
        elif name_lower[pos].isdigit():
            return False
    # GPU VRAM guard to prevent false matches
    wp = watchlist_product
    if wp["category"] == "gpu" and wp.get("vram_gb"):
        model_num = wp["model"].lower().split()[-1]
        if model_num in name_lower:
            return True
        vram_str = f"{wp["vram_gb"]}gb"
        if vram_str in name_lower:
            return True
        return False
    return True


def _parse_price(price_text: Any) -> float | None:
    """Extract a float price from price text."""
    if price_text is None:
        return None
    if isinstance(price_text, (int, float)):
        return float(price_text)
    m = re.search(r"\$?([\d,]+\.?\d*)", str(price_text))
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _map_stock_label(label: str) -> str:
    """Map a PCCG Algolia indicator label to the schema stock_status enum.

    Vocabularies observed live (2026-08-13) on the GeForce RTX 5090 index:
        "In stock"          -> in_stock
        "Sold Out"          -> out_of_stock
        "ETA: DD/MM/YY"     -> preorder   (on order, awaiting arrival)
        "Stock at Supplier" -> preorder   (orderable, not on-hand)
    Anything unrecognised or blank maps to 'unknown' rather than guessing.
    """
    if not label:
        return "unknown"
    lowered = str(label).strip().lower()
    if lowered == "in stock":
        return "in_stock"
    if lowered == "sold out":
        return "out_of_stock"
    if "eta" in lowered or "preorder" in lowered or "stock at supplier" in lowered:
        return "preorder"
    return "unknown"


def _extract_products(hits: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Extract product dicts from Algolia hits, including real stock status.

    Stock status comes from the index's ``indicator.label`` (what the PCCG
    product grid actually displays). ``is_ETA_TBA`` is a secondary signal used
    only when the label is missing. Sold-out/orderable products are still
    returned — their price history matters — with their true status attached.
    """
    products: list[Dict[str, Any]] = []
    for hit in hits:
        name = hit.get("products_name", "")
        price = hit.get("products_price")
        url_slug = hit.get("Product_URL", "")
        brand = hit.get("manufacturers_name", "")
        if not name:
            continue
        if url_slug and not url_slug.startswith("http"):
            full_url = f"{PCCG_BASE}{url_slug}"
        elif url_slug:
            full_url = url_slug
        else:
            full_url = ""
        label = ((hit.get("indicator") or {}).get("label") or "").strip()
        stock_status = _map_stock_label(label)
        if not label and str(hit.get("is_ETA_TBA", "")).strip() == "1":
            stock_status = "preorder"
        products.append({
            "name": name,
            "price": price,
            "url": full_url,
            "brand": brand,
            "stock_status": stock_status,
        })
    return products


def algolia_single_search(
    query: str,
    category_filter: str,
    hits_per_page: int = 20,
    max_pages: int = 10,
) -> list[Dict[str, Any]]:
    """Search a single query on PCCG via Algolia, paginating through all results.

    Args:
        query: Search query string
        category_filter: Algolia category filter
        hits_per_page: Number of results per page
        max_pages: Safety limit for pagination

    Returns:
        List of product dicts across all pages
    """
    filter_str = f'categories.lvl0:"{category_filter}"'
    attrs = STOCK_ATTRS

    all_products: list[Dict[str, Any]] = []
    page = 0

    while page < max_pages:
        params_dict = {
            "query": query,
            "hitsPerPage": hits_per_page,
            "page": page,
            "attributesToRetrieve": attrs,
            "filters": filter_str,
        }
        params_str = urlencode(params_dict)
        payload = {"requests": [{"indexName": ALGOLIA_INDEX, "params": params_str}]}

        for attempt in range(ALGOLIA_MAX_RETRIES):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
                if r.status_code == 429:
                    wait = ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1)
                    LOGGER.warning("Rate limited (attempt %d/%d), waiting %ds...", attempt + 1, ALGOLIA_MAX_RETRIES, wait)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    LOGGER.error("Algolia API error: %s - %s", r.status_code, r.text[:200])
                    return all_products

                data = r.json()
                if "results" not in data:
                    LOGGER.error("Algolia API unexpected response")
                    return all_products

                result = data["results"][0]
                hits = result.get("hits", [])
                products = _extract_products(hits)
                all_products.extend(products)

                # Check if there are more pages
                nb_pages = result.get("nbPages", 1)
                if page + 1 >= nb_pages:
                    break

                page += 1
                time.sleep(0.3)
                break

            except requests.RequestException as e:
                LOGGER.error("Algolia request error: %s", e)
                return all_products

    return all_products


def algolia_batch_search(
    queries: list[str],
    category_filter: str,
    hits_per_page: int = 20,
    max_pages: int = 10,
) -> list[list[Dict[str, Any]]]:
    """Batch search PCCG via Algolia multi-query API with pagination.

    Sends multiple queries in a single API request and paginates through
    all results for each query. This is much faster than calling
    algolia_single_search sequentially for each query.

    Args:
        queries: List of search query strings
        category_filter: Algolia category filter
        hits_per_page: Number of results per page
        max_pages: Safety limit for pagination

    Returns:
        List of lists of product dicts (one list per query)
    """
    filter_str = f'categories.lvl0:"{category_filter}"'
    attrs = STOCK_ATTRS

    # Track accumulated products and remaining pages per query
    all_results: list[list[Dict[str, Any]]] = [[] for _ in queries]
    nb_pages_list: list[int] = [max_pages] * len(queries)

    page = 0
    while page < max_pages:
        # Check if any queries still have pages to fetch
        active = [i for i in range(len(queries)) if page < nb_pages_list[i]]
        if not active:
            break

        # Build batch request with only active queries
        requests_list: list[Dict[str, Any]] = []
        active_indices: list[int] = []
        for i in active:
            params_dict = {
                "query": queries[i],
                "hitsPerPage": hits_per_page,
                "page": page,
                "attributesToRetrieve": attrs,
                "filters": filter_str,
            }
            params_str = urlencode(params_dict)
            requests_list.append({"indexName": ALGOLIA_INDEX, "params": params_str})
            active_indices.append(i)

        payload = {"requests": requests_list}

        for attempt in range(ALGOLIA_MAX_RETRIES):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
                if r.status_code == 429:
                    wait = ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1)
                    LOGGER.warning("Rate limited (attempt %d/%d), waiting %ds...", attempt + 1, ALGOLIA_MAX_RETRIES, wait)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    LOGGER.error("Algolia API error: %s - %s", r.status_code, r.text[:200])
                    return all_results

                data = r.json()
                if "results" not in data:
                    LOGGER.error("Algolia API unexpected response")
                    return all_results

                # Process each result
                for j, result in enumerate(data["results"]):
                    idx = active_indices[j]
                    hits = result.get("hits", [])
                    products = _extract_products(hits)
                    all_results[idx].extend(products)

                    # Track total pages for this query
                    result_nb_pages = result.get("nbPages", 1)
                    if page == 0:
                        nb_pages_list[idx] = result_nb_pages

                # Success — move to next page
                page += 1
                time.sleep(0.3)
                break

            except requests.RequestException as e:
                LOGGER.error("Algolia batch request error: %s", e)
                return all_results

    return all_results


def scrape_category(
    category: str,
    watchlist: list[WatchlistProduct],
) -> Tuple[list[Dict[str, Any]], set[int]]:
    """Scrape a single category (cpu or gpu) from PCCG via Algolia API.

    Uses batched multi-query requests to avoid rate limiting.

    Returns (results_list, matched_global_indices_set).
    """
    category_watchlist = [wp for wp in watchlist if wp["category"] == category]
    category_filter = "Graphics Cards" if category == "gpu" else "CPUs"

    LOGGER.info("Scraping PCCG %s (filter: %s)", category.upper(), category_filter)

    results: list[Dict[str, Any]] = []
    matched_global: set[int] = set()
    consecutive_failures = 0  # Track consecutive failed batches for backoff

    # Sort watchlist by search term length (longest first = most specific)
    sorted_indices = sorted(
        range(len(category_watchlist)),
        key=lambda i: len(category_watchlist[i]["search_terms"][0]),
        reverse=True,
    )

    # Map each model back to its global index in the full watchlist
    model_to_global: Dict[str, int] = {
        wp["model"]: gi for gi, wp in enumerate(watchlist)
    }

    # Track ALL matches per watchlist item, then pick cheapest
    all_matches: dict[int, list[Dict[str, Any]]] = {}  # global_idx -> list of matched product dicts

    # Process in batches
    for batch_start in range(0, len(sorted_indices), BATCH_SIZE):
        batch_indices = sorted_indices[batch_start : batch_start + BATCH_SIZE]
        queries: list[str] = []

        for idx in batch_indices:
            wp = category_watchlist[idx]
            primary_term = wp["search_terms"][0] if wp["search_terms"] else wp["model"]
            queries.append(primary_term)

        # Batch query — max 3 pages is enough; products appear early
        batch_results = algolia_batch_search(queries, category_filter, hits_per_page=20, max_pages=3)

        # Check if batch failed (all empty) — if so, add a cool-down
        batch_failed = all(len(pr) == 0 for pr in batch_results)

        # Process each result
        for i, idx in enumerate(batch_indices):
            wp = category_watchlist[idx]

            # Find global index
            global_idx = model_to_global.get(wp["model"])

            products = batch_results[i] if i < len(batch_results) else []

            # Collect ALL matching products
            for prod in products:
                if match_product(prod["name"], wp):
                    price = _parse_price(prod["price"])
                    if price and global_idx is not None:
                        match_dict = {
                            "watchlist_model": wp["model"],
                            "watchlist_category": wp["category"],
                            "watchlist_brand": wp["brand"],
                            "watchlist_gen_tier": wp["gen_tier"],
                            "retailer": "pccg",
                            "scraped_name": prod["name"][:120],
                            "price_aud": price,
                            "stock_status": prod.get("stock_status", "unknown"),
                            "url": prod["url"],
                        }
                        if global_idx not in all_matches:
                            all_matches[global_idx] = []
                        all_matches[global_idx].append(match_dict)

        # Delay between batches to avoid rate limiting
        # Use exponential backoff for consecutive failed batches
        if batch_failed:
            consecutive_failures += 1
            delay = min(BATCH_DELAY * (2 ** consecutive_failures), ALGOLIA_BACKOFF_MAX_SECONDS)
        else:
            consecutive_failures = 0
            delay = BATCH_DELAY
        time.sleep(delay)

    # Save ALL matched variants for each watchlist item — regardless of stock
    # state. Sold-out and on-order cards keep their listings and price history.
    results = []
    matched_global = set()
    for global_idx, matches in all_matches.items():
        if not matches:
            continue
        results.extend(matches)
        matched_global.add(global_idx)
        if len(matches) > 1:
            wp_model = watchlist[global_idx]["model"]
            LOGGER.info("  %s: %d variants saved", wp_model, len(matches))

    return results, matched_global


def main() -> None:
    """Run the PCCG scraper to collect price data for all watchlist products."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info("Loading watchlist...")
    watchlist = load_watchlist()
    LOGGER.info("  %d products", len(watchlist))

    all_results: list[Dict[str, Any]] = []
    all_matched: set[int] = set()

    for category in ["cpu", "gpu"]:
        results, matched = scrape_category(category, watchlist)
        all_results.extend(results)
        all_matched.update(matched)
        LOGGER.info("  %s: %d matched", category.upper(), len(results))

    # Report unmatched
    unmatched = [wp["model"] for i, wp in enumerate(watchlist) if i not in all_matched]
    LOGGER.info("\n%s\nTotal: %d matched / %d", "=" * 60, len(all_results), len(watchlist))
    LOGGER.info("Unmatched: %d", len(unmatched))
    if unmatched:
        LOGGER.info("\nUnmatched products:")
        for m in unmatched:
            LOGGER.info("  - %s", m)

    # Save to separate JSON files
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    for category in ["cpu", "gpu"]:
        cat_results = [p for p in all_results if p["watchlist_category"] == category]
        cat_unmatched = [
            m for m in unmatched
            if any(wp["model"] == m and wp["category"] == category for wp in watchlist)
        ]
        output_file = DATA_DIR / f"{category}_pccg_{today}.json"
        output_data = {
            "retailer": "pccg",
            "scrape_date": today,
            "category": category,
            "total_watchlist": len(watchlist),
            "matched": len(cat_results),
            "unmatched_count": len(cat_unmatched),
            "unmatched_models": cat_unmatched,
            "products": cat_results,
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        LOGGER.info("Saved: %s", output_file)


if __name__ == "__main__":
    main()