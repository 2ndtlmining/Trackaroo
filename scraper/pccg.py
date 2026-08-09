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
BATCH_SIZE = 4  # Smaller batches to stay under Algolia rate limits
BATCH_DELAY = 0.5  # Seconds between successful batches


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


def algolia_batch_search(queries, category_filter, hits_per_page=20):
    """Batch search PCCG via Algolia multi-query API.

    Args:
        queries: List of search query strings
        category_filter: Algolia category filter
        hits_per_page: Number of results per query

    Returns:
        List of lists of product dicts (one list per query)
    """
    # Build facet filters
    filter_str = f'categories.lvl0:"{category_filter}"'
    attrs = "products_name,products_price,products_model,Product_URL,manufacturers_name"

    requests_list = []
    for q in queries:
        # Algolia multi-query API expects params as a URL-encoded string, not a dict
        params_dict = {
            "query": q,
            "hitsPerPage": hits_per_page,
            "attributesToRetrieve": attrs,
            "filters": filter_str,
        }
        params_str = urlencode(params_dict)
        requests_list.append({
            "indexName": ALGOLIA_INDEX,
            "params": params_str,
        })

    payload = {"requests": requests_list}

    all_results = []
    for attempt in range(3):  # Max 3 attempts per batch
        try:
            r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                wait = 2 * (attempt + 1)
                print(f"  Rate limited (attempt {attempt + 1}/3), waiting {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"  Algolia API error: {r.status_code} - {r.text[:200]}")
                return [[]] * len(queries)

            data = r.json()
            if "results" not in data:
                print(f"  Algolia API unexpected response")
                return [[]] * len(queries)

            for result in data["results"]:
                hits = result.get("hits", [])
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
                all_results.append(products)
            break  # Success

        except requests.RequestException as e:
            print(f"  Algolia request error: {e}")
            return [[]] * len(queries)

    # Fill missing results if we got fewer than expected
    while len(all_results) < len(queries):
        all_results.append([])

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

    # Process in batches
    for batch_start in range(0, len(sorted_indices), BATCH_SIZE):
        batch_indices = sorted_indices[batch_start:batch_start + BATCH_SIZE]
        queries = []

        for idx in batch_indices:
            wp = category_watchlist[idx]
            primary_term = wp["search_terms"][0] if wp["search_terms"] else wp["model"]
            queries.append(primary_term)

        # Batch query
        batch_results = algolia_batch_search(queries, category_filter, hits_per_page=20)

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

            if global_idx is not None and global_idx in matched_global:
                continue

            products = batch_results[i] if i < len(batch_results) else []

            # Try to match
            for prod in products:
                if match_product(prod["name"], wp):
                    price = _parse_price(prod["price"])
                    if price:
                        results.append({
                            "watchlist_model": wp["model"],
                            "watchlist_category": wp["category"],
                            "watchlist_brand": wp["brand"],
                            "watchlist_gen_tier": wp["gen_tier"],
                            "retailer": "pccg",
                            "scraped_name": prod["name"][:120],
                            "price_aud": price,
                            "stock_status": "in_stock",
                            "url": prod["url"],
                        })
                        matched_global.add(global_idx)
                        break

        # Delay between batches to avoid rate limiting
        # Use exponential backoff for consecutive failed batches
        if batch_failed:
            consecutive_failures += 1
            delay = min(BATCH_DELAY * (2 ** consecutive_failures), 20)
        else:
            consecutive_failures = 0
            delay = BATCH_DELAY
        time.sleep(delay)

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
