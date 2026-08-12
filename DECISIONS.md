# Decision Log

Rationale behind key choices, so anyone (human or AI) picking this project up later understands *why*, not just *what*. Add a new entry whenever a significant decision is made or revisited — don't rewrite history, append.

---

### Data source: scraping, not an API
No public product/pricing API exists for Scorptec, PC Case Gear, or Mwave — confirmed by checking each site directly (custom platforms, not Shopify/Magento/BigCommerce, which would have exposed something usable). All three have clean, server-rendered category listing pages, so scraping is low-complexity and shouldn't require JS rendering for core fields (name/price/stock). This should be re-verified per retailer in Phase 1 in case a site behaves differently than its category pages suggested.

### Database: SQLite (not Convex, not self-hosted Supabase)
Considered three options:
- **Convex** — appealing because schema/backend logic live in code (TypeScript) and self-hosting is real. Rejected because: (a) Convex's backend functions are TS-native — the Python scraper would need to call in via its Python client while business logic still lives in TS, splitting the data layer across two languages; (b) Convex isn't built for OLAP-style aggregation — "biggest % change over N days across 500+ SKUs" is a SQL window-function problem, and Convex has no equivalent, so it'd be hand-rolled; (c) self-hosted Convex has no official support plan and is less battle-tested than SQLite/Postgres for this kind of workload.
- **Self-hosted Supabase (Postgres)** — a real contender since it's already running in the home infrastructure and gives full SQL. Not chosen for this project specifically because SQLite gives the same SQL analytics capability with zero additional ops (no new service to run), and this project doesn't need Supabase's other features (auth, realtime, storage).
- **SQLite (chosen)** — zero-ops, single file, backs up trivially, and the analytics needs of this project (time-series price aggregation) are squarely SQL's strength. If the project outgrows SQLite later, migrating to Postgres/Supabase is a well-trodden path.

### Scraper language: Python (not Node/TypeScript)
FluxTracker (a prior project) used Node/SvelteKit, so reusing that stack was considered for consistency. Python was chosen instead for the scraper specifically because its scraping ecosystem (httpx, BeautifulSoup, Playwright as fallback) is stronger and faster to iterate with for this kind of per-retailer HTML parsing work. The frontend remains SvelteKit — only the ingestion layer is Python.

### Frontend: SvelteKit
Matches the existing FluxTracker deployment pattern (Docker on Proxmox, adapter-node), which is proven infrastructure. SvelteKit's reactivity model also suits a filterable stats dashboard well, and its compiled output keeps chart-heavy pages fast even with hundreds of SKUs and dense time-series data.

### Product matching strategy: manual/semi-manual first, not automatic fuzzy matching
Real-world product names vary significantly between retailers for the same physical card/chip (e.g. "ASUS TUF Gaming RTX 5070 Ti OC 16GB" vs. "ASUS TUF-RTX5070TI-O16G-GAMING"). Automatic fuzzy matching risks silently mismatching products, which would corrupt price-comparison data in a hard-to-detect way. Starting with a manual or semi-manual mapping table trades some upfront effort for correctness; automation can be revisited once there's real data to see how messy the matching problem actually is in practice.

### Product scope: curated watchlist via 2-generation rule (not "track everything")
Tracking every CPU/GPU a retailer lists would blow out both scrape time and matching effort, and much of that long tail (old, discontinued, rarely-priced-competitively products) wouldn't be useful for "current market" price tracking anyway. The 2-generation rule (current + 2 prior generations per product line) keeps the watchlist meaningful and bounded. Full rules and per-line generation tables live in `SCOPE_RULES.md`.

### Data retention: never delete, freeze instead
When a product/listing stops being tracked (rolls out of scope, gets delisted by a retailer, or a scraper breaks), the rule is to stop writing new snapshots and mark it (`tracked=false` / `status=delisted|stale`) rather than delete any historical rows. This preserves price history for later analysis and avoids silently losing data due to a scope change or a temporary scraper issue. See spec §7a for the full policy and schema fields that implement it.

### Mwave removed from scope (2026-08-10)
Mwave uses CloudFront bot protection that blocks all automated requests — even with stealth headers and Playwright. No viable scraping path was found. Removed from SPEC.md retailer table and from active work. PCCG and Scorptec remain as the two data sources.

### PCCG uses Algolia API, not Playwright (2026-08-10)
PCCG's product search is powered by Algolia InstantSearch. The Algolia credentials (app ID + read-only API key) are embedded in PCCG's page source. This means we can query the Algolia search API directly — no Playwright, no headless browser, no JS rendering needed. Much faster and more reliable. The multi-query API endpoint accepts batched requests with URL-encoded params strings. Rate limiting is strict (~429 after ~30 rapid queries) — batched requests with delays between batches is the working approach.

### Scorptec scraper outputs separate CPU/GPU JSON files (2026-08-10)
User requested separate files per category: `cpu_scorptec_10_August_2026.json`, `gpu_scorptec_10_August_2026.json`. Same convention applies to PCCG. This makes it easier to reason about per-category match rates and debug issues.

### Historical JSON data is never deleted (2026-08-10)
Scraped JSON files in `data/` are retained indefinitely — they serve as the raw audit trail and can be re-ingested if the DB needs rebuilding. New daily snapshots get new filenames with the date. Old files are not removed.

### Shared watchlist loader module `db/watchlist.py` (2026-08-12)
The watchlist CSV parsing + spec parsing logic (`parse_spec`, `load_watchlist`) was copy-pasted three times — in `fetch_test.py`, `scraper/pccg.py`, and `seed.py`, with slight drift between them. Extracted into a single `db/watchlist.py` module with three entry points: `load_watchlist` (scraper-shaped rows with `search_terms`), `load_watchlist_products` (seed-shaped rows for the `products` table), and `parse_spec`. The importing modules re-export or delegate to it, so behavior is identical but no longer duplicated. Kept next to `db/watchlist.csv` since it is the loader for that data file.

### Match-count anomaly checks count listings, not products (2026-08-12)
`health_checks.py`'s `check_match_count_anomalies` originally counted `COUNT(DISTINCT product_id)` per retailer per date. Once multi-variant tracking landed, that under-reported massively (e.g. Scorptec 54 products but 192 variant listings), producing false "Match count dropped" warnings against thresholds calibrated for variants. Fixed to count `COUNT(DISTINCT retailer_listings.id)` so the metric and the thresholds mean the same thing. Lesson: when the semantics of a metric change (products → variants), everything calibrated on it must change together.

### Algolia credentials via environment variables (2026-08-12)
The PCCG scraper embeds the Algolia app ID and read-only search key found in PCCG's page source. Hardcoded in the repo, they risk being committed/forgotten alongside unrelated changes. Now read from `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` env vars with the known-good values as defaults (they are read-only public search keys, so the defaults keep zero-config local use working).
