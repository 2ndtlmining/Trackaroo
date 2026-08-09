"""
Scrape Scorptec for watchlist products and save results to JSON.
Usage: python fetch_test.py
"""
import csv
import json
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = "Trackaroo/1.0 (Personal price tracker; daily snapshots)"
HEADERS = {"User-Agent": UA}
BASE = "https://www.scorptec.com.au"

# Category pages to scrape per product type
CATEGORY_URLS = {
    "cpu_amd_am4": f"{BASE}/product/cpu/amd-am4-5000",
    "cpu_amd_am5_7000": f"{BASE}/product/cpu/amd-am5-7000",
    "cpu_amd_am5_8000": f"{BASE}/product/cpu/amd-am5-8000",
    "cpu_amd_am5_9000": f"{BASE}/product/cpu/amd-am5-9000",
    "cpu_intel_all": f"{BASE}/product/cpu/intel",
    "gpu_nvidia": f"{BASE}/product/graphics-cards/nvidia",
    "gpu_amd": f"{BASE}/product/graphics-cards/amd",
    "gpu_intel": f"{BASE}/product/graphics-cards/intel",
}


def load_watchlist(path="db/watchlist.csv"):
    """Load watchlist CSV, skipping comment lines."""
    products = []
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    reader = csv.DictReader(lines)
    for row in reader:
        # Parse spec into cores or vram_gb
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


def fetch_page(url, retries=2):
    """Fetch a URL with retries."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r.text
        except requests.RequestException as e:
            print(f"  Attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(2)
    return None


def parse_product_grid(html):
    """Extract products from Scorptec product-grid elements using data attributes."""
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for grid in soup.select(".product-grid"):
        # Data attributes are the most reliable source
        name = grid.get("data-shortintro", "")
        full_desc = grid.get("data-intro", "")
        price_str = grid.get("data-price", "")
        instock = grid.get("data-instock", "")
        sku = grid.get("data-sku", "")

        # Get link from the title element
        title_link = grid.select_one(".grid-product-title a[href]")
        url = title_link["href"] if title_link else ""
        if url and not url.startswith("http"):
            url = BASE + url

        # Parse price
        price = None
        if price_str:
            try:
                price = float(price_str)
            except ValueError:
                pass

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


def match_product(scraped_name, scraped_desc, watchlist_product):
    """Check if a scraped product matches a watchlist entry using search terms.

    Uses the primary search term (e.g. 'rtx 5070') as the main matcher.
    Brand names like 'Nvidia' or 'AMD' often don't appear in scraped product names
    (e.g. 'ASUS Dual GeForce RTX 5070' has no 'Nvidia'), so we skip the brand check
    and rely on the specific model number in the search term.
    """
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


def scrape_scorptec(watchlist):
    """Scrape Scorptec and match against watchlist.

    Key: when iterating the watchlist for each scraped product, we process
    entries with LONGER primary search terms first. This prevents substring
    conflicts — e.g. 'ryzen 5 5600' matching before 'ryzen 5 5600x' can.
    """
    # Build sorted index order: longer search terms first (more specific matches first)
    watchlist_order = sorted(
        range(len(watchlist)),
        key=lambda i: len(watchlist[i]["search_terms"][0]),
        reverse=True,
    )

    results = []
    matched_watchlist_ids = set()
    all_scraped = {}  # Track all scraped products per category for debugging

    for cat_key, url in CATEGORY_URLS.items():
        print(f"\nScraping: {cat_key} -> {url}")
        time.sleep(0.5)  # Be polite

        html = fetch_page(url)
        if not html:
            print(f"  Failed to fetch {url}, skipping.")
            continue

        scraped_products = parse_product_grid(html)
        all_scraped[cat_key] = scraped_products
        print(f"  Found {len(scraped_products)} products on page")

        for scraped in scraped_products:
            for i in watchlist_order:
                if i in matched_watchlist_ids:
                    continue  # Already matched

                wp = watchlist[i]
                if match_product(scraped["name"], scraped["full_description"], wp):
                    results.append({
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
                    })
                    matched_watchlist_ids.add(i)
                    break  # One match per scraped product

    return results, matched_watchlist_ids, all_scraped


def analyze_unmatched(watchlist, matched_ids, all_scraped):
    """Analyze why products weren't matched."""
    print(f"\n{'=' * 60}")
    print("Unmatched product analysis:")
    print(f"{'=' * 60}")

    likely_delist = []
    possible_stocked = []

    for i, wp in enumerate(watchlist):
        if i in matched_ids:
            continue

        primary = wp["search_terms"][0] if wp["search_terms"] else ""
        found_anywhere = False
        matching_scraped = None

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

    print(f"\nLikely delisted at Scorptec ({len(likely_delist)} products):")
    for m in likely_delist:
        print(f"  - {m}")

    if possible_stocked:
        print(f"\nPossibly stocked but matching issue ({len(possible_stocked)} products):")
        for model, primary, scraped_name in possible_stocked:
            print(f"  - {model}")
            print(f"    Search term: '{primary}' found in: '{scraped_name}'")

    return likely_delist, possible_stocked


def main():
    print("Loading watchlist...")
    watchlist = load_watchlist()
    print(f"  {len(watchlist)} products in watchlist")

    print("\nScraping Scorptec...")
    results, matched_ids, all_scraped = scrape_scorptec(watchlist)

    # Report
    print(f"\n{'=' * 60}")
    print(f"Results: {len(results)} matched / {len(watchlist)} total")

    # Analyze unmatched
    delisted, matching_issues = analyze_unmatched(watchlist, matched_ids, all_scraped)

    # Build unmatched list
    unmatched_models = [wp["model"] for i, wp in enumerate(watchlist) if i not in matched_ids]

    # Save to separate CPU and GPU JSON files
    today = date.today().strftime("%d_%B_%Y")
    Path("data").mkdir(exist_ok=True)

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
        output_file = f"data/{category}_scorptec_{today}.json"
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
        print(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    main()
