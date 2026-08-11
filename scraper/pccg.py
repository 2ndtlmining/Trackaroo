"""
PC Case Gear scraper — uses PCCG's Algolia search API directly.
No Playwright needed — we query the Algolia index that powers PCCG's site search.
Uses batched multi-query requests to avoid rate limiting.
"""
import csv
import json
import time
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import requests

# Algolia API credentials (embedded in PCCG page source — read-only search key)
ALGOLIA_APP_ID = "HPD3DBJ2IO"
ALGOLIA_API_KEY = "9559cf1a6c7521a30ba0832ec6c38499"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_INDEX = "pccg_products"
PCCG_BASE = "https://www.pccasegear.com"

HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
}

# Batch size for multi-query requests
BATCH_SIZE = 16  # Larger batches = fewer iteration rounds; Algolia handles 16+ queries per call
BATCH_DELAY = 1.0  # Seconds between successful batches — Algolia rate limits are strict


def load_watchlist(path="db/watchlist.csv"):
    """Load watchlist CSV, skipping comment lines."""
    products = []
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    reader = csv.DictReader(lines)
    for row in reader:
        spec = row["spec"]
        if row["category"] == "cpu":
            row["cores"] = int(spec.replace("c", ""))
            row["vram_gb"] = None
        else:
            row["vram_gb"] = int(spec.replace("GB", ""))
            row["cores"] = None
        row["search_terms"] = [t.strip().lower() for t in row["search_aliases"].split("|")]
        products.append(row)
    return products


def match_product(scraped_name, watchlist_product):
    """Check if a scraped product matches a watchlist entry."""
    name_lower = scraped_name.lower()
    search_terms = watchlist_product["search_terms"]
    if not search_terms:
        return False
    primary_term = search_terms[0].lower()
    if primary_term not in name_lower:
        return False
    # Guard: ensure the match isn't a substring of a different variant
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
        vram_str = f"{wp['vram_gb']}gb"
        if vram_str in name_lower:
            return True
        return False
    return True


def _parse_price(price_text):
    """Extract a float price from price text."""
    if price_text is None:
        return None
    if isinstance(price_text, (int, float)):
        return float(price_text)
    m = re.search(r"\$?([\d,]+\.?\d*)", str(price_text))
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _extract_products(hits):
    """Extract product dicts from Algolia hits."""
    products = []
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
        products.append({
            "name": name,
            "price": price,
            "url": full_url,
            "brand": brand,
        })
    return products


def algolia_single_search(query, category_filter, hits_per_page=20, max_pages=10):
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
    attrs = "products_name,products_price,products_model,Product_URL,manufacturers_name"

    all_products = []
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

        for attempt in range(3):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=15)
                if r.status_code == 429:
                    wait = 5 * (attempt + 1)  # Longer backoff for Algolia rate limits
                    print(f"    Rate limited (attempt {attempt + 1}/3), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    print(f"    Algolia API error: {r.status_code} - {r.text[:200]}")
                    return all_products

                data = r.json()
                if "results" not in data:
                    print(f"    Algolia API unexpected response")
                    return all_products

                result = data["results"][0]
                hits = result.get("hits", [])
                products = _extract_products(hits)
                all_products.extend(products)

                # Check if there are more pages
                nb_pages = result.get("nbPages", 1)
                if page + 1 >= nb_pages:
                    break  # Last page

                page += 1
                time.sleep(0.3)  # Be polite between pages
                break  # Success, move to next page

            except requests.RequestException as e:
                print(f"    Algolia request error: {e}")
                return all_products

    return all_products


def algolia_batch_search(queries, category_filter, hits_per_page=20, max_pages=10):
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
    attrs = "products_name,products_price,products_model,Product_URL,manufacturers_name"

    # Track accumulated products and remaining pages per query
    all_results = [[] for _ in queries]
    nb_pages = [max_pages] * len(queries)  # Start at max; first response will set real values

    page = 0
    while page < max_pages:
        # Check if any queries still have pages to fetch
        active = [i for i in range(len(queries)) if page < nb_pages[i]]
        if not active:
            break

        # Build batch request with only active queries
        requests_list = []
        active_indices = []
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

        for attempt in range(3):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=15)
                if r.status_code == 429:
                    wait = 5 * (attempt + 1)  # Longer backoff for Algolia rate limits
                    print(f"    Rate limited (attempt {attempt + 1}/3), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    print(f"    Algolia API error: {r.status_code} - {r.text[:200]}")
                    return all_results

                data = r.json()
                if "results" not in data:
                    print(f"    Algolia API unexpected response")
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
                        nb_pages[idx] = result_nb_pages

                # Success — move to next page
                page += 1
                time.sleep(0.3)  # Be polite between pages
                break  # Break retry loop

            except requests.RequestException as e:
                print(f"    Algolia batch request error: {e}")
                return all_results

    return all_results


def scrape_category(category, watchlist):
    """Scrape a single category (cpu or gpu) from PCCG via Algolia API.

    Uses batched multi-query requests to avoid rate limiting.

    Returns (results_list, matched_global_indices_set).
    """
    category_watchlist = [wp for wp in watchlist if wp["category"] == category]
    category_filter = "Graphics Cards" if category == "gpu" else "CPUs"

    print(f"\nScraping PCCG {category.upper()} (filter: {category_filter})")

    results = []
    matched_global = set()
    consecutive_failures = 0  # Track consecutive failed batches for backoff

    # Sort watchlist by search term length (longest first = most specific)
    sorted_indices = sorted(
        range(len(category_watchlist)),
        key=lambda i: len(category_watchlist[i]["search_terms"][0]),
        reverse=True,
    )

    # Track ALL matches per watchlist item, then pick cheapest
    all_matches = {}  # global_idx -> list of matched product dicts

    # Process in batches
    for batch_start in range(0, len(sorted_indices), BATCH_SIZE):
        batch_indices = sorted_indices[batch_start:batch_start + BATCH_SIZE]
        queries = []

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
            global_idx = None
            for gi, gw in enumerate(watchlist):
                if gw["model"] == wp["model"]:
                    global_idx = gi
                    break

            products = batch_results[i] if i < len(batch_results) else []

            # Collect ALL matching products
            for prod in products:
                if match_product(prod["name"], wp):
                    price = _parse_price(prod["price"])
                    if price:
                        match_dict = {
                            "watchlist_model": wp["model"],
                            "watchlist_category": wp["category"],
                            "watchlist_brand": wp["brand"],
                            "watchlist_gen_tier": wp["gen_tier"],
                            "retailer": "pccg",
                            "scraped_name": prod["name"][:120],
                            "price_aud": price,
                            "stock_status": "in_stock",
                            "url": prod["url"],
                        }
                        if global_idx not in all_matches:
                            all_matches[global_idx] = []
                        all_matches[global_idx].append(match_dict)

        # Delay between batches to avoid rate limiting
        # Use exponential backoff for consecutive failed batches
        if batch_failed:
            consecutive_failures += 1
            delay = min(BATCH_DELAY * (2 ** consecutive_failures), 20)
        else:
            consecutive_failures = 0
            delay = BATCH_DELAY
        time.sleep(delay)

    # Save ALL in-stock variants for each watchlist item
    results = []
    matched_global = set()
    for global_idx, matches in all_matches.items():
        if not matches:
            continue
        # All PCCG products are considered in_stock (Algolia only returns active products)
        results.extend(matches)
        matched_global.add(global_idx)
        if len(matches) > 1:
            wp_model = watchlist[global_idx]["model"]
            print(f"  {wp_model}: {len(matches)} in-stock variants saved")

    return results, matched_global


def main():
    print("Loading watchlist...")
    watchlist = load_watchlist()
    print(f"  {len(watchlist)} products")

    all_results = []
    all_matched = set()

    for category in ["cpu", "gpu"]:
        results, matched = scrape_category(category, watchlist)
        all_results.extend(results)
        all_matched.update(matched)
        print(f"  {category.upper()}: {len(results)} matched")

    # Report unmatched
    unmatched = [wp["model"] for i, wp in enumerate(watchlist) if i not in all_matched]
    print(f"\n{'=' * 60}")
    print(f"Total: {len(all_results)} matched / {len(watchlist)}")
    print(f"Unmatched: {len(unmatched)}")
    if unmatched:
        print(f"\nUnmatched products:")
        for m in unmatched:
            print(f"  - {m}")

    # Save to separate JSON files
    today = date.today().strftime("%d_%B_%Y")
    Path("data").mkdir(exist_ok=True)

    for category in ["cpu", "gpu"]:
        cat_results = [p for p in all_results if p["watchlist_category"] == category]
        cat_unmatched = [
            m for m in unmatched
            if any(wp["model"] == m and wp["category"] == category for wp in watchlist)
        ]
        output_file = f"data/{category}_pccg_{today}.json"
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
        print(f"\nSaved: {output_file}")


if __name__ == "__main__":
    main()
