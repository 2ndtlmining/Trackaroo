# AU CPU/GPU Price Tracker — Specification & Plan

## 1. Purpose

Track daily pricing and stock status for **CPUs and GPUs** across three Australian retailers, store the history, and surface trends — biggest price movers, potential good deals, and long-term price charts per product.

This is a personal-use, self-hosted project. It is not a public-facing price comparison service.

## 2. Retailers in scope

| Retailer | Base URL | Platform notes |
|---|---|---|
| Scorptec | https://www.scorptec.com.au/ | Custom platform, server-rendered HTML, clean category pages (`/product/cpu/...`, `/product/graphics-cards/...`) |
| PC Case Gear | https://www.pccasegear.com/ | Algolia InstantSearch (JS-rendered) — query the embedded Algolia search API directly, no browser needed |
| ~~Mwave~~ | ~~https://www.mwave.com.au/~~ | ~~Removed — CloudFront bot protection blocks all automated requests~~ |

**Confirmed during planning:** none of the retailers expose a public product/pricing API. All data will be sourced via scraping their public category/listing pages.

**Verified during Phase 1 (2026-08-09):**
- **Scorptec** — server-rendered HTML, plain HTTP fetch + BeautifulSoup works perfectly
- **PC Case Gear** — Algolia InstantSearch; the Algolia app ID + read-only search key embedded in page source let us query the search API directly (see DECISIONS.md) — no Playwright/JS rendering needed
- **Mwave** — removed from scope due to CloudFront bot protection blocking all automated requests

## 3. Product scope

- **In scope:** desktop CPUs (Intel + AMD) and desktop/consumer GPUs (NVIDIA + AMD, and Intel Arc). Workstation/server CPUs and professional GPUs (Quadro/RTX Ada/etc.) are **excluded** entirely to keep matching simple.
- **Decided:** curated watchlist, not "track everything." The watchlist is governed by a **2-generation rule** — track the current generation plus two prior (current, −1, −2) per product line; exclude anything older. Full generation tables and maintenance instructions live in the companion file `SCOPE_RULES.md` — that file is the source of truth for exactly which products are in/out, and should be consulted (and updated) whenever a new generation launches.

## 4. Goals

1. Take a daily snapshot of price + stock status for every tracked product at every retailer.
2. Store full price history (not just latest value) so trends can be computed over arbitrary windows.
3. Match the "same" physical product across retailers so it can be compared directly (e.g. one RTX 5070 Ti card, priced at all three).
4. Surface, via a web dashboard:
   - Price history chart per product (and per retailer listing)
   - Biggest price increases / decreases over a selected window (7d / 30d / all-time)
   - Cheapest current price per product across retailers
   - Basic "good deal" signal — e.g. price is at or near its historical low
5. Run unattended, on existing home infrastructure, with visibility when something breaks (a scrape fails, a retailer's page structure changes, zero products found, etc.).
6. **Never delete price/product data.** See §7a, Data Retention Policy.

## 5. Non-goals (for now)

- Not tracking any category beyond CPU/GPU.
- Not building user accounts, alerts/notifications, or public access — single-user, local dashboard.
- Not attempting real-time pricing — daily cadence is the target.
- Not scraping product review content, images, or full specs beyond what's needed to identify and match products.

## 6. Architecture overview

Three components, consistent with prior projects (FluxTracker/FluxFlow pattern):

```
┌─────────────────┐      ┌──────────────────┐      ┌───────────────────┐
│  Python scraper   │ ---> │   SQLite database  │ <--- │  SvelteKit frontend │
│  (ingestion job)  │      │  (price history)   │      │  (charts & stats)   │
└─────────────────┘      └──────────────────┘      └───────────────────┘
      runs daily               single file              reads DB directly
      via scheduler/cron                                  or via small API layer
```

- **Scraper/ingestion (Python):** fetches category pages per retailer, parses product name/price/stock/URL, normalizes, writes a snapshot row per product per retailer per day.
- **Database (SQLite):** single-file, zero-ops, easy to back up on TrueNAS. Chosen over Convex/Supabase for this project because the core analytics need (price-change queries across hundreds of SKUs over time windows) is a natural fit for SQL, and this keeps the stack simple.
- **Frontend (SvelteKit):** matches the FluxTracker stack already running on your infrastructure. Charts via a lightweight library (uPlot or Chart.js — leaning uPlot for dense time-series performance).
- **Deployment:** Docker container(s) on the existing Proxmox cluster, following the same pattern as FluxTracker.

## 7. Data model (draft)

Three core tables, designed to separate canonical product identity from retailer-specific listings from time-series price data:

**`products`** — canonical, cross-retailer identity
- `id`, `category` (cpu/gpu), `brand`, `model` (e.g. "RTX 5070 Ti"), `variant` (e.g. AIB partner/edition if tracked), `vram_gb` / `cores` (category-specific spec fields), `created_at`
- `generation_tier` (enum: `current` / `current-1` / `current-2`) — which SCOPE_RULES.md tier this product sits in. Kept even after a product rolls out of scope, as a historical record of where it sat. Makes scope management queryable without parsing model names.
- `tracked` (bool) — is this product currently in the active watchlist per `SCOPE_RULES.md`? Set to `false` when a generation rolls out of scope. **Never delete the row** — see §7a.
- `last_snapshot_at` — timestamp of the most recent successful price snapshot for this product (across any retailer). Lets any consumer (frontend, another AI, a future you) instantly tell how fresh a product's data is without scanning `price_snapshots`.

**`retailer_listings`** — a specific retailer's page for a product
- `id`, `product_id` (FK), `retailer` (scorptec/pccg/mwave), `retailer_sku_or_url`, `listing_url`, `first_seen_at`, `last_seen_at`
- `status` (enum: `active` / `delisted` / `stale`) — replaces a plain boolean so we can distinguish "retailer removed the listing" (`delisted`) from "we stopped scraping it, e.g. rolled out of scope" (`stale`) from "currently tracked" (`active`). **Rows are never deleted** — see §7a.
- `last_snapshot_at` — timestamp of the most recent successful snapshot for this specific listing.

**`price_snapshots`** — one row per listing per scrape
- `id`, `retailer_listing_id` (FK), `snapshot_date`, `price_aud`, `stock_status` (enum: `in_stock` / `out_of_stock` / `preorder` / `unknown`), `scraped_at`
  - An enum rather than a plain boolean, to handle real-world states like PCCG's "Stock at Supplier" (`preorder`) without losing information. Defaults to `unknown`.
- Append-only. **No updates, no deletes**, ever — see §7a.

**`specs`** — one row per canonical product, from external spec datasets (added 16-Aug-2026, see `IMPROVEMENT_16_Aug_V1.md`)
- `product_id` (FK to `products`), `source` (`rightnow-gpu-db` / `intel-processors-csv` / `amd-com`), `source_record_key` (the identifying name in the source dataset, kept for traceability), `category`, `architecture`, `generation`, `launch_date`, `launch_msrp_usd`
- GPU-specific (nullable on CPU rows): `vram_gb`, `memory_bus_width_bit`, `memory_type`, `tdp_watts`
- CPU-specific (nullable on GPU rows): `thread_count`, `base_clock_mhz`, `boost_clock_mhz`, `socket`, `cache_l3_mb`
- `core_count` is deliberately shared — shading units for GPU rows, physical cores for CPU rows (one column, documented, rather than two over-loaded ones)
- `raw_json` — the full original source record verbatim, so new fields can be read later without a schema migration
- Populated by the weekly `sync_specs.py` (a separate, best-effort job — never part of the daily price pipeline). Fetched only on the product detail page; **never joined into list/index queries**. Rows are never deleted; a conflicting re-match is flagged in the sync report, never silently overwritten.

This structure is what makes "biggest movers" and "cheapest across retailers" clean SQL queries (window functions over `price_snapshots` joined through `retailer_listings` to `products`) rather than something hand-rolled in application code.

### 7a. Data retention policy

**Rule: never delete data. Freeze it instead.**

When a product/listing stops being actively tracked — because a generation rolled out of scope (`SCOPE_RULES.md`), a retailer delisted it, or a scraper issue means we can't match it anymore — the correct action is:

1. Stop writing new `price_snapshots` rows for it.
2. Flip `products.tracked` to `false` (generation rolled out of scope) and/or `retailer_listings.status` to `delisted` or `stale` as appropriate.
3. Leave every existing row exactly as it is. The last snapshot simply becomes the permanent last data point for that product/listing.

**Consuming "freshness" correctly:** any view or query that shows current prices should check `last_snapshot_at` and clearly indicate when a product's data is not from today (e.g. "last seen 14 days ago") rather than silently presenting stale data as current. This applies to the frontend, any future analytics, and any AI picking up this project — do not infer "current price" without checking how recent the snapshot actually is.

This rule is absolute and applies regardless of the reason data stopped updating (delisted, rolled out of scope, scraper broke, retailer changed page structure). Deletion is never the right response to any of those situations.

**Open question for Phase 1:** how strict to make product matching — automatic fuzzy matching (brand+model+VRAM) vs. a manually curated mapping table. **Recommendation: start manual/semi-manual**, since real-world product names vary a lot between retailers (e.g. "ASUS TUF Gaming RTX 5070 Ti OC 16GB" vs "ASUS TUF-RTX5070TI-O16G-GAMING"), and premature automation risks silently mismatching products.

## 8. Scraping approach

- Plain HTTP fetch (requests) + HTML parse (BeautifulSoup) per retailer's category pages, paginating through results. PCCG is fetched via its Algolia search API directly.
- Playwright held in reserve only if a retailer turns out to need JS rendering for price/stock (not needed so far — Scorptec is server-rendered, PCCG uses Algolia).
- One scraper module per retailer (`fetch_test.py` for Scorptec, `scraper/pccg.py` for PCCG), each returning a common normalized record shape, so the ingestion pipeline and DB layer are retailer-agnostic.
- Daily cadence, run via cron or APScheduler inside the container. Reasonable delay between requests within a retailer; no need to hit any site more than once a day.
- Identify the scraper honestly via a descriptive User-Agent string.
- **Resilience requirement:** each scrape run should validate its own output (e.g. "did we get a plausible number of products for this category?") and log/alert if a retailer returns zero results or wildly different data than expected — a sign the page structure changed and the parser needs updating, not that all stock vanished. Implemented in `health_checks.py` (match-count thresholds per retailer/category, freshness, anomaly detection).

## 9. Frontend features (initial scope)

1. Product list/table view — current price per retailer, cheapest highlighted, in-stock status.
2. Price history chart per product — line chart per retailer over time.
3. "Biggest movers" view — largest % price change over a selectable window.
4. Simple deal signal — flag products currently at or near their tracked historical low.
5. Filter by category (CPU/GPU) and brand.

Later/nice-to-have (not in initial build): watchlist-based alerts, cross-category comparisons, export to CSV.

## 10. Risks & considerations

- **Site structure changes** will break scrapers silently unless monitored — build in basic sanity checks from day one (see §8).
- **Product matching accuracy** is the main ongoing maintenance burden — expect to manually reconcile mappings periodically, especially for new product launches.
- **Politeness/ToS** — daily-cadence, low-volume scraping with a clear user-agent is a reasonable, low-impact approach for a personal project; avoid aggressive polling.
- **Retailer promotional pricing/bundles** may create noisy "price changes" that aren't genuine trend signals (e.g. bundle deals, multi-buy discounts) — worth filtering or flagging distinctly if they show up in early data.

## 11. Build phases

**Phase 1 — Foundation** *(complete)*
- Finalize product watchlist scope (which CPUs/GPUs to track)
- Design and create SQLite schema
- Build Scorptec scraper end-to-end (cleanest HTML of the three) → validate daily snapshot loop works

**Phase 2 — Full ingestion** *(complete)*
- Add PC Case Gear scraper to the same pipeline (Mwave dropped — CloudFront bot protection)
- Build the manual/semi-manual cross-retailer product matching layer (search-term based)
- Add scrape-health checks/alerting (health_checks.py; variant-count anomaly detection)

**Phase 3 — Frontend**
- Product table + current pricing view
- Price history charts per product
- Biggest movers + deal-signal views

**Phase 4 — Hardening**
- Deploy to Proxmox/Docker on the daily schedule
- Backups of the SQLite file
- Revisit matching automation and watchlist scope based on real data collected

## 12. Stack summary

| Layer | Choice |
|---|---|
| Scraper | Python (requests + BeautifulSoup; Playwright in reserve) |
| Scheduling | Cron or APScheduler in-container |
| Database | SQLite |
| Frontend | SvelteKit + uPlot/Chart.js |
| Deployment | Docker on existing Proxmox cluster |
