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

# Fallback URL category paths — when a product <a> tag has an empty href
# (Scorptec populates some links client-side via JavaScript), we construct
# the URL from the SKU using the correct product-detail path.
CATEGORY_URL_PATHS = {
    "cpu_amd_am4": "cpu/amd-socket-am4",
    "cpu_amd_am5_7000": "cpu/amd-socket-am5",
    "cpu_amd_am5_8000": "cpu/amd-socket-am5",
    "cpu_amd_am5_9000": "cpu/amd-socket-am5",
    "cpu_intel_all": "cpu/intel",
    "gpu_nvidia": "graphics-cards/nvidia",
    "gpu_amd": "graphics-cards/amd",
    "gpu_intel": "graphics-cards/intel",
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


def get_next_page_url(html, base_url):
    """Extract the next page URL from a Scorptec pagination link.

    Scorptec uses a '.next' CSS class on the pagination <a> tag for the
    next page. Returns None if there is no next page.

    Parameters
    ----------
    html : str
        Raw HTML from the current category page.
    base_url : str
        Base URL for resolving relative links.

    Returns
    -------
    str or None
        Full URL of the next page, or None if this is the last page.
    """
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("a.next[href]")
    if next_link:
        href = next_link["href"]
        if href.startswith("http"):
            return href
        return f"{BASE}{href}"
    return None


def scrape_all_pages(url, category_path, max_pages=20):
    """Scrape all pages of a Scorptec category, following pagination links.

    Parameters
    ----------
    url : str
        Starting URL for the category.
    category_path : str
        URL path segment for constructing fallback product URLs.
    max_pages : int
        Safety limit to avoid infinite loops.

    Returns
    -------
    list[dict]
        All scraped products across all pages.
    """
    all_products = []
    page = 1
    current_url = url

    while current_url and page <= max_pages:
        print(f"  Page {page}: {current_url}")
        time.sleep(0.5)  # Be polite between pages

        html = fetch_page(current_url)
        if not html:
            print(f"  Failed to fetch page {page}, stopping pagination.")
            break

        products = parse_product_grid(html, category_path=category_path)
        all_products.extend(products)
        print(f"  Found {len(products)} products on page {page} ({len(all_products)} total)")

        # Check if there's a next page
        next_url = get_next_page_url(html, url)
        if not next_url:
            print(f"  No more pages. Total: {len(all_products)} products.")
            break

        page += 1
        current_url = next_url

    if page > max_pages:
        print(f"  Reached max pages ({max_pages}). Total: {len(all_products)} products.")

    return all_products


def parse_product_grid(html, category_path=""):
    """Extract products from Scorptec product-grid elements using data attributes.

    Parameters
    ----------
    html : str
        Raw HTML from a Scorptec category page.
    category_path : str
        URL path segment for constructing fallback product URLs when the
        server-side <a> tag has an empty href (Scorptec populates some links
        client-side via JavaScript). E.g. "cpu/intel" or "graphics-cards/nvidia".
    """
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

        # Fallback: when href is empty (JS-populated link), construct URL from SKU
        if not url and sku and category_path:
            url = f"{BASE}/product/{category_path}/{sku}"

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

    For each watchlist item, we capture ALL matching products and keep only
    the cheapest in-stock variant. This ensures we don't miss cheaper models
    (e.g., Zotac 5090 at $6,999 vs ASUS at $7,599).
    """
    # Build sorted index order: longer search terms first (more specific matches first)
    watchlist_order = sorted(
        range(len(watchlist)),
        key=lambda i: len(watchlist[i]["search_terms"][0]),
        reverse=True,
    )

    # Track ALL matches per watchlist item, then pick cheapest in-stock
    all_matches = {}  # watchlist_index -> list of matched product dicts
    all_scraped = {}  # Track all scraped products per category for debugging

    for cat_key, cat_url in CATEGORY_URLS.items():
        print(f"\nScraping: {cat_key} -> {cat_url}")

        # Pass the category URL path so fallback URLs can be constructed
        fallback_path = CATEGORY_URL_PATHS.get(cat_key, "")
        # Scrape ALL pages, not just page 1
        scraped_products = scrape_all_pages(cat_url, category_path=fallback_path)
        all_scraped[cat_key] = scraped_products
        print(f"  Total for {cat_key}: {len(scraped_products)} products across all pages")

        for scraped in scraped_products:
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
    results = []
    matched_watchlist_ids = set()
    for i, matches in all_matches.items():
        if not matches:
            continue
        # Keep only in-stock variants
        in_stock = [m for m in matches if m["stock_status"] == "in_stock"]
        if in_stock:
            results.extend(in_stock)
            matched_watchlist_ids.add(i)
            print(f"  {watchlist[i]['model']}: {len(in_stock)} in-stock variants saved")
        else:
            # All out of stock — still save them for reference
            results.extend(matches)
            matched_watchlist_ids.add(i)
            print(f"  {watchlist[i]['model']}: {len(matches)} variants found (all out of stock)")

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
