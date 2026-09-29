"""PC Case Gear scraper — uses PCCG's Algolia search API directly.

No Playwright needed — we query the Algolia index that powers PCCG's site search.

The key is capped at 100 queries per IP in a rolling ~60-minute window, so the
scraper fetches each category **whole** (one empty query, ``hitsPerPage=1000``)
and matches the watchlist locally — 2 queries per run. See
``algolia_fetch_catalogue``. Batching per-product queries into one HTTP request
does **not** reduce the cost; that older approach is what caused the daily 429s.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import requests

from config import (
    ALGOLIA_BACKOFF_MAX_SECONDS,
    ALGOLIA_BATCH_MAX_PAGES,
    ALGOLIA_CATALOGUE_HITS_PER_PAGE,
    ALGOLIA_CATALOGUE_MAX_PAGES,
    ALGOLIA_CIRCUIT_BREAKER_LIMIT,
    ALGOLIA_HITS_PER_PAGE,
    ALGOLIA_MAX_PAGES,
    ALGOLIA_MAX_RETRIES,
    ALGOLIA_PAGE_DELAY,
    ALGOLIA_RATE_LIMIT_WAIT_SECONDS,
    ALGOLIA_TIMEOUT_SECONDS,
    BATCH_DELAY,
    BATCH_SIZE,
    CATEGORY_PASS_DELAY,
    DATA_DIR,
    FILE_DATE_FORMAT,
    PCCG_COOLDOWN_FILE,
    PCCG_COOLDOWN_HOURS,
    setup_logging,
)
from db.watchlist import load_watchlist, WatchlistProduct
from scraper.chip_key import Matcher
from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED, RunReport, exit_code_for
from scraper.snapshot_io import save_category_snapshot

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


def _is_bundle_product(name: str, url: str = "") -> bool:
    """Return True if the listing is a component bundle (e.g. CPU + motherboard).

    Combos price the whole bundle, not the component alone, so they must never
    match a single-component watchlist product. Signals: 'bundle'/'combo' in the
    name, or 'bundle'/'bdl-' in the URL.
    """
    if "bundle" in name.lower() or "combo" in name.lower():
        return True
    url_lower = url.lower()
    return "bundle" in url_lower or "-bdl-" in url_lower


def match_product(scraped_name: str, watchlist_product: WatchlistProduct) -> bool:
    """Check if a scraped product matches a watchlist entry.

    Matching is exact chip-key equality (see `scraper/chip_key.py`): search
    terms no longer drive matching, only the Algolia queries.
    """
    # Component bundles (CPU + motherboard) must not match a single component
    if _is_bundle_product(scraped_name):
        return False
    return Matcher([watchlist_product]).resolve(scraped_name, watchlist_product["category"]) == 0


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


def _retry_wait(retry_after: str | None, attempt: int) -> float:
    """Compute the backoff delay in seconds for a 429 response.

    Algolia/Cloudflare-fronted 429s often carry a ``Retry-After`` header;
    prefer it over the fixed formula when present — but cap it so a
    pathological header can't stall the whole run. Falls back to a jittered
    linear backoff (``ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1)``)
    otherwise; the ±10% jitter stops a burst of retries from re-colliding in
    lockstep.
    """
    if retry_after:
        try:
            ceiling = ALGOLIA_RATE_LIMIT_WAIT_SECONDS * ALGOLIA_MAX_RETRIES * 4
            return min(float(retry_after), ceiling)
        except (TypeError, ValueError):
            pass
    base = min(ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1), ALGOLIA_BACKOFF_MAX_SECONDS)
    return base * random.uniform(0.9, 1.1)


def _log_api_status_error(r: Any) -> None:
    """Log a non-200 Algolia response, distinguishing retryable from fatal.

    429 is handled separately (retry loop); 401/403 mean the embedded
    read-only App ID/API key has likely been rotated by PCCG, which no amount
    of backoff fixes — worth being able to tell apart at a glance in logs.
    """
    if r.status_code in (401, 403):
        LOGGER.error(
            "Algolia auth rejected (%s) — App ID/API key likely rotated by PCCG, not a rate-limit issue: %s - %s",
            r.status_code, r.status_code, r.text[:200],
        )
    else:
        LOGGER.error("Algolia API error: %s - %s", r.status_code, r.text[:200])


class AlgoliaAuthError(RuntimeError):
    """PCCG's public search key was rejected (HTTP 401/403).

    Distinct from an empty catalogue (a block): backing off cannot fix a
    rotated key, so no cooldown is written and a human is paged (#11a).
    """

    def __init__(self, status: int) -> None:
        super().__init__(f"Algolia rejected the PCCG search key (HTTP {status})")
        self.status = status


# ── Circuit-breaker cooldown ─────────────────────────────────────────

def _write_cooldown(reason: str) -> None:
    """Persist a cooldown file so scheduled retries don't immediately re-trip."""
    try:
        payload = {
            "tripped_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        PCCG_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        PCCG_COOLDOWN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        LOGGER.warning("Cooldown written to %s (reason: %s)", PCCG_COOLDOWN_FILE, reason)
    except OSError as e:
        LOGGER.error("Could not write cooldown file %s: %s", PCCG_COOLDOWN_FILE, e)


def _cooldown_active() -> bool:
    """Return True if a persisted cooldown is still within its window.

    Callers should skip the whole PCCG scrape (exit cleanly, not error) when
    this is True — the site was blocking recently and a retry would just
    hammer it again.
    """
    try:
        if not PCCG_COOLDOWN_FILE.exists():
            return False
        payload = json.loads(PCCG_COOLDOWN_FILE.read_text(encoding="utf-8"))
        tripped_at = datetime.fromisoformat(payload["tripped_at"])
        if tripped_at.tzinfo is None:
            tripped_at = tripped_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - tripped_at
        return elapsed < timedelta(hours=PCCG_COOLDOWN_HOURS)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, TypeError):
        LOGGER.warning("Ignoring unreadable cooldown file: %s", PCCG_COOLDOWN_FILE)
        return False


def _clear_cooldown() -> None:
    """Remove the cooldown file after a successful scrape."""
    try:
        if PCCG_COOLDOWN_FILE.exists():
            PCCG_COOLDOWN_FILE.unlink()
            LOGGER.info("Cleared PCCG cooldown file %s", PCCG_COOLDOWN_FILE)
    except OSError as e:
        LOGGER.error("Could not clear cooldown file %s: %s", PCCG_COOLDOWN_FILE, e)


def algolia_single_search(
    query: str,
    category_filter: str,
    hits_per_page: int = ALGOLIA_HITS_PER_PAGE,
    max_pages: int = ALGOLIA_MAX_PAGES,
) -> list[Dict[str, Any]]:
    """Search a single query on PCCG via Algolia, paginating through all results.

    .. deprecated:: 27-Aug-2026
        **No longer used by the pipeline, and must not be reintroduced into it.**
        Per-product searching is what exhausted the search key's
        ``maxQueriesPerIPPerHour: 100`` budget and caused the daily 429s.
        ``scrape_category`` now calls :func:`algolia_fetch_catalogue` instead.
        Kept only as a general-purpose helper for one-off manual queries.

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

        retries_exhausted = True
        for attempt in range(ALGOLIA_MAX_RETRIES):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = _retry_wait(retry_after, attempt)
                    LOGGER.warning("Rate limited (attempt %d/%d), waiting %ds...", attempt + 1, ALGOLIA_MAX_RETRIES, wait)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    _log_api_status_error(r)
                    return all_products
                try:
                    data = r.json()
                except ValueError:
                    LOGGER.error("Algolia returned non-JSON response (likely a WAF/challenge page), body[:200]: %s", r.text[:200])
                    return all_products
                if "results" not in data:
                    LOGGER.error("Algolia API unexpected response")
                    return all_products

                result = data["results"][0]
                hits = result.get("hits", [])
                products = _extract_products(hits)
                all_products.extend(products)

                # Check if there are more pages
                nb_pages = result.get("nbPages", 1)
                retries_exhausted = False
                if page + 1 >= nb_pages:
                    return all_products

                page += 1
                time.sleep(ALGOLIA_PAGE_DELAY)
                break

            except requests.RequestException as e:
                LOGGER.error("Algolia request error: %s", e)
                return all_products

        if retries_exhausted:
            LOGGER.error(
                "Giving up after %d retries on page %d — PCCG appears to be rate-limiting all requests right now.",
                ALGOLIA_MAX_RETRIES, page,
            )
            return all_products

    return all_products


def algolia_batch_search(
    queries: list[str],
    category_filter: str,
    hits_per_page: int = ALGOLIA_HITS_PER_PAGE,
    max_pages: int = ALGOLIA_MAX_PAGES,
) -> list[list[Dict[str, Any]]]:
    """Batch search PCCG via Algolia multi-query API with pagination.

    .. deprecated:: 27-Aug-2026
        **No longer used by the pipeline, and must not be reintroduced into it.**
        Batching queries into one HTTP request made the scrape *look* cheap but
        did nothing for the quota: Algolia bills each entry in ``requests`` as a
        separate query, so 100 watchlist products still cost 100 of the key's
        100-per-IP-per-hour budget. That is the bug this module was rewritten to
        remove — see :func:`algolia_fetch_catalogue`.

    Sends multiple queries in a single API request and paginates through
    all results for each query.

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

        retries_exhausted = True
        for attempt in range(ALGOLIA_MAX_RETRIES):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = _retry_wait(retry_after, attempt)
                    LOGGER.warning("Rate limited (attempt %d/%d), waiting %ds...", attempt + 1, ALGOLIA_MAX_RETRIES, wait)
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    _log_api_status_error(r)
                    return all_results
                try:
                    data = r.json()
                except ValueError:
                    LOGGER.error("Algolia returned non-JSON response (likely a WAF/challenge page), body[:200]: %s", r.text[:200])
                    return all_results
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
                retries_exhausted = False
                page += 1
                time.sleep(ALGOLIA_PAGE_DELAY)
                break

            except requests.RequestException as e:
                LOGGER.error("Algolia batch request error: %s", e)
                return all_results

        if retries_exhausted:
            LOGGER.error(
                "Giving up after %d retries on page %d — PCCG appears to be rate-limiting all requests right now.",
                ALGOLIA_MAX_RETRIES, page,
            )
            return all_results

    return all_results


def algolia_fetch_catalogue(
    category_filter: str,
    hits_per_page: int = ALGOLIA_CATALOGUE_HITS_PER_PAGE,
    max_pages: int = ALGOLIA_CATALOGUE_MAX_PAGES,
) -> list[Dict[str, Any]]:
    """Fetch an entire PCCG category in as few Algolia queries as possible.

    **This is the fix for the daily 429s — do not go back to per-product
    searching.** PCCG's public search key is restricted to
    ``"maxQueriesPerIPPerHour": 100`` (confirmed 27-Aug-2026 against
    ``GET /1/keys/<key>``). The scraper used to send one query per watchlist
    product per page, so 100 tracked products spent the whole hourly budget on
    page 0 alone and most runs 429'd partway through. No backoff could fix
    that: the budget is a **rolling ~60-minute window**, not an hour-boundary
    bucket, so waiting *inside* a run cannot create quota — it only burns the
    run's remaining time. (Measured 27-Aug-2026: a heavy spend at 18:06 GMT
    was still 429ing at 19:01 GMT, i.e. after a fresh clock hour had begun.)
    Quota frees up roughly an hour after the queries that consumed it.

    Fetching the category whole costs one query (229 GPUs / 60 CPUs both fit in
    Algolia's 1000-hit maximum), and the watchlist is matched against it
    locally by ``match_product`` — the same authoritative filter that was
    already applied to search results, so matching is equivalent but can no
    longer miss a listing that fuzzy ranking happened to rank low.

    Args:
        category_filter: Algolia ``categories.lvl0`` value, e.g. "Graphics Cards"
        hits_per_page: Hits per page (1000 is Algolia's maximum)
        max_pages: Safety cap, only reached if a category outgrows one page

    Returns:
        List of product dicts for the whole category (empty on failure).

    Raises:
        AlgoliaAuthError: the key was rejected (401/403).
    """
    filter_str = f'categories.lvl0:"{category_filter}"'
    all_products: list[Dict[str, Any]] = []
    page = 0

    while page < max_pages:
        params_dict = {
            "query": "",
            "hitsPerPage": hits_per_page,
            "page": page,
            "attributesToRetrieve": STOCK_ATTRS,
            "filters": filter_str,
        }
        params_str = urlencode(params_dict)
        payload = {"requests": [{"indexName": ALGOLIA_INDEX, "params": params_str}]}

        retries_exhausted = True
        for attempt in range(ALGOLIA_MAX_RETRIES):
            try:
                r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = _retry_wait(retry_after, attempt)
                    LOGGER.warning(
                        "Rate limited fetching the %s catalogue (attempt %d/%d), waiting %ds — "
                        "the search key allows 100 queries/IP/hour; another process or an "
                        "earlier run today may have spent it.",
                        category_filter, attempt + 1, ALGOLIA_MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                if r.status_code in (401, 403):
                    _log_api_status_error(r)
                    raise AlgoliaAuthError(r.status_code)
                if r.status_code != 200:
                    _log_api_status_error(r)
                    return all_products
                try:
                    data = r.json()
                except ValueError:
                    LOGGER.error("Algolia returned non-JSON response (likely a WAF/challenge page), body[:200]: %s", r.text[:200])
                    return all_products
                if "results" not in data:
                    LOGGER.error("Algolia API unexpected response")
                    return all_products

                result = data["results"][0]
                hits = result.get("hits", [])
                all_products.extend(_extract_products(hits))

                nb_pages = result.get("nbPages", 1)
                retries_exhausted = False
                if page + 1 >= nb_pages:
                    LOGGER.info(
                        "  %s catalogue: %d products in %d Algolia quer%s",
                        category_filter, len(all_products), page + 1,
                        "y" if page == 0 else "ies",
                    )
                    return all_products

                page += 1
                time.sleep(ALGOLIA_PAGE_DELAY)
                break

            except requests.RequestException as e:
                LOGGER.error("Algolia catalogue request error: %s", e)
                return all_products

        if retries_exhausted:
            LOGGER.error(
                "Giving up after %d retries on %s catalogue page %d — PCCG is rate-limiting. "
                "The key's budget is 100 queries/IP in a rolling ~60min window — "
                "it frees up about an hour after whatever spent it, not at the top of the hour.",
                ALGOLIA_MAX_RETRIES, category_filter, page,
            )
            return all_products

    return all_products


def scrape_category(
    category: str,
    watchlist: list[WatchlistProduct],
) -> Tuple[list[Dict[str, Any]], set[int], bool]:
    """Scrape a single category (cpu or gpu) from PCCG via Algolia API.

    Fetches the category once (see ``algolia_fetch_catalogue`` for why) and
    matches the watchlist against it locally.

    Returns (results_list, matched_global_indices_set, breaker_tripped).
    """
    category_watchlist = [wp for wp in watchlist if wp["category"] == category]
    category_filter = "Graphics Cards" if category == "gpu" else "CPUs"

    LOGGER.info("Scraping PCCG %s (filter: %s)", category.upper(), category_filter)

    results: list[Dict[str, Any]] = []
    matched_global: set[int] = set()
    breaker_tripped = False

    # One query for the whole category — the watchlist is matched locally.
    catalogue = algolia_fetch_catalogue(category_filter)

    # An entirely empty category is a block, not an empty shop: PCCG always
    # stocks GPUs and CPUs, so nothing back means the request never really
    # landed. Trip the breaker so the next scheduled run backs off instead of
    # hammering a blocking API, and so the run reports incomplete rather than
    # silently ingesting zero listings.
    if not catalogue:
        LOGGER.error(
            "Circuit breaker tripped: PCCG returned an empty %s catalogue — "
            "treating as a block, not an empty category.", category,
        )
        _write_cooldown("empty catalogue")
        return [], set(), True

    # Map each model back to its global index in the full watchlist
    model_to_global: Dict[str, int] = {
        wp["model"]: gi for gi, wp in enumerate(watchlist)
    }

    # Each product resolves to at most one watchlist row via the canonical
    # chip-key Matcher (see scraper/chip_key.py): exact key equality, with
    # VRAM used only to disambiguate GPU rows that share a key. One listing,
    # one product — unlike the old per-watchlist-entry substring scan, a
    # product can no longer be claimed by two different watchlist rows (#1).
    matcher = Matcher(category_watchlist)
    all_matches: dict[int, list[Dict[str, Any]]] = {}  # global_idx -> matched product dicts
    for prod in catalogue:
        if _is_bundle_product(prod["name"], prod.get("url", "")):
            continue
        local = matcher.resolve(prod["name"], category)
        if local is None:
            continue
        wp = category_watchlist[local]
        global_idx = model_to_global.get(wp["model"])
        if global_idx is None:
            continue
        price = _parse_price(prod["price"])
        if not price:
            continue
        all_matches.setdefault(global_idx, []).append({
            "watchlist_model": wp["model"],
            "watchlist_category": wp["category"],
            "watchlist_brand": wp["brand"],
            "watchlist_gen_tier": wp["gen_tier"],
            "retailer": "pccg",
            "scraped_name": prod["name"][:120],
            "price_aud": price,
            "stock_status": prod.get("stock_status", "unknown"),
            "url": prod["url"],
        })

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

    return results, matched_global, breaker_tripped


def main() -> int:
    """Run the PCCG scraper to collect price data for all watchlist products."""
    setup_logging()
    LOGGER.info("Loading watchlist...")
    watchlist = load_watchlist()
    LOGGER.info("  %d products", len(watchlist))

    report = RunReport("pccg")

    # Respect a circuit-breaker cooldown before doing anything else.
    if _cooldown_active():
        LOGGER.warning(
            "Skipping PCCG scrape: cooldown still active (file %s, window %.0fh). "
            "This is expected handled behaviour, not an error.",
            PCCG_COOLDOWN_FILE, PCCG_COOLDOWN_HOURS,
        )
        report.note(f"skipped: circuit-breaker cooldown active ({PCCG_COOLDOWN_HOURS:.0f}h window)")
        report.flush()
        return EXIT_SKIPPED

    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    all_results: list[Dict[str, Any]] = []
    all_matched: set[int] = set()
    all_tripped: list[str] = []

    try:
        for i, category in enumerate(["cpu", "gpu"]):
            results, matched, tripped = scrape_category(category, watchlist)
            # Saved per category so a timeout during GPUs keeps the CPUs (R2).
            save_category_snapshot(DATA_DIR, "pccg", category, today, watchlist, results, matched)
            report.set(category, matched=len(results))
            report.flush()
            all_results.extend(results)
            all_matched.update(matched)
            LOGGER.info("  %s: %d matched", category.upper(), len(results))
            if tripped:
                all_tripped.append(category)
                report.note(f"circuit breaker tripped for {category} (empty catalogue - treated as a block)")
                report.flush()
            # Short pause between category passes -- same Algolia index and IP.
            if i == 0:
                LOGGER.info("  Pausing %.1fs before next category pass...", CATEGORY_PASS_DELAY)
                time.sleep(CATEGORY_PASS_DELAY)
    except AlgoliaAuthError as e:
        LOGGER.error(
            "%s. No cooldown written: waiting cannot fix a rejected key. Update "
            "ALGOLIA_API_KEY - see DEPLOYMENT.md, 'PCCG key rotation'.", e,
        )
        report.note(f"{e} - update ALGOLIA_API_KEY (DEPLOYMENT.md: 'PCCG key rotation')")
        report.flush()
        return EXIT_AUTH

    if not all_tripped:
        _clear_cooldown()
    else:
        LOGGER.error("PCCG scrape incomplete - circuit breaker tripped for: %s", ", ".join(all_tripped))

    unmatched = [wp["model"] for i, wp in enumerate(watchlist) if i not in all_matched]
    LOGGER.info("\n%s\nTotal: %d matched / %d", "=" * 60, len(all_results), len(watchlist))
    LOGGER.info("Unmatched: %d", len(unmatched))
    for m in unmatched:
        LOGGER.info("  - %s", m)

    if all_tripped:
        return EXIT_DEGRADED
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())