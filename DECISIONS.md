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

### WAL journal mode enabled for frontend-safe concurrent access (2026-08-13)
The DB previously ran with the default rollback-journal (`journal_mode=delete`). Now that a frontend will read the DB while `run_daily.py` writes on a cron schedule, WAL (`PRAGMA journal_mode=WAL`) is the mechanism that makes concurrent reads safe. Set by the writer/init paths (`ingest.init_db`, `seed.init_db`, `migrate`) — the mode persists in the DB file header, so every later connection runs in WAL automatically. The real DB was flipped on 13-Aug-2026.

**Lesson learned (proved by the concurrency test):** readers must NEVER toggle journal mode at connection time. `query.get_connection` originally ran `PRAGMA journal_mode=WAL` on open; while a writer held its lock, the mode *change* needed an exclusive lock and raised `database is locked`. Reassigning journal mode is a write-side operation — readers just open and inherit. This is why `query.py` now sets only `busy_timeout` (covering the brief WAL checkpoint write-lock window) and lets the file header handle the rest. The future better-sqlite3 frontend should follow the same rule: read, don't reconfigure.

### Frontend DB access: direct SQLite via better-sqlite3 (2026-08-13)
Decision for Phase 3: SvelteKit server routes read `db/trackaroo.db` directly with better-sqlite3, rather than standing up a thin read API. Rationale: single-user, self-hosted, one database file, and the dashboard's queries are already proven fast (see perf numbers below). An API layer would add a service to deploy for no benefit at this scale. WAL makes the direct read safe against the cron writer. (Node's built-in `node:sqlite` is a viable fallback if a native build of better-sqlite3 becomes a nuisance.)

### Frontend location: `web/` subdirectory in this repo (2026-08-13)
SvelteKit scaffolds under `web/`, sharing the same clone, `db/` file, and Docker build as the Python pipeline. Chosen over a separate repo so the daily runner and the dashboard deploy together and always agree on the DB file they read.

### No new indexes needed — measured, not assumed (2026-08-13)
The proposed `price_snapshots (product_id, snapshot_date)` index doesn't map to the schema — `price_snapshots` references `retailer_listing_id`, not `product_id`. `EXPLAIN QUERY PLAN` confirms the per-product price-history path already uses `idx_retailer_listings_product` (covering) + `idx_snapshots_listing_date` with no full scan. Measured on a synthetic 333-listing × 30-day DB (~10k snapshots): `show_latest_prices` = 60 ms, `show_biggest_movers` = 7 ms. Adding a covering `(retailer_listing_id, snapshot_date, price_aud, stock_status)` index would shave the `price_aud` table-lookup off the history query, but at this scale it's ~nothing; revisit if snapshots grow past ~50k rows or the dashboard's history query shows up hot in profiling.

### Price-anomaly sensitivity is history-dependent (2026-08-13)
With N stable price points plus one jump, the jump's max detectable deviation is about √N standard deviations. A 3× spike over only 5–6 days computes to ~2.2σ and does NOT trip the 3σ threshold; it needs ~10+ history points to be flagged. On 13-Aug real data, 226 of 333 listings sit at exactly 3 points, so the anomaly check currently misses most single-day jumps — by design (the threshold avoids false positives on thin data). Worth revisiting `PRICE_ANOMALY_STD_DEVS` or adding history-depth awareness once listings accumulate more days. Test `test_appearing_disappearing_variants_no_false_positive` locks in the intended behavior: a genuine jump on a mature listing flags; a vanished or freshly-appeared variant does not.

### PCCG stock status fix: _map_stock_label() retains sold-out/preorder variants (2026-08-13)
The PCCG scraper originally marked every product `in_stock` regardless of actual stock state. The Algolia index carries an `indicator.label` field with values like "In stock", "Sold Out", "ETA: DD/MM/YY", and "Stock at Supplier". The fix introduced `_map_stock_label()` in `scraper/pccg.py` which maps these labels to the schema enum (`in_stock`, `out_of_stock`, `preorder`, `unknown`).

**Why retain sold-out products?** Their price still matters for history — a sold-out product's last price is the reference point for when it restocks. Dropping them would create gaps in the price timeline.

**Impact:** On 13-Aug PCCG GPU data, 32 of 102 variants were `out_of_stock` and 2 were `preorder`. The DB had all 123 PCCG rows marked `in_stock` from the buggy ingest. A new `resync_stock_status.py` script was created to compare buggy vs. fixed JSON and update the affected 37 rows (3 CPU + 34 GPU). The script supports `--dry-run` and is idempotent.

**Lesson:** When a scraper bug corrupts data that's already been ingested, a targeted resync script is better than re-ingesting everything. It's scoped to the affected date and retailer, supports dry-run, and leaves unrelated data untouched.

### Backup files are excluded from ingestion (2026-08-13)
The `data/` directory contains `.backup_buggy.json` files preserving the original buggy scrape output for audit purposes. The ingest pipeline and E2E tests now filter out any file containing `.backup` in the filename, preventing these archive files from being re-ingested or causing parse errors. This keeps the raw audit trail intact while preventing accidental double-processing.

### Resync script for stock_status corrections (2026-08-13)
`resync_stock_status.py` is a standalone tool that:
- Compares buggy vs. fixed JSON pairs for a given date
- Identifies rows where `stock_status` was incorrect in the DB
- Supports `--dry-run` (preview only) and apply mode
- Is idempotent — safe to re-run
- Only affects PCCG rows for the specified date
- Does NOT touch Scorptec data or other dates

9 new regression tests cover: dry-run behavior, apply mode, idempotency, backup file filtering, and helper function correctness.

### Charts: uPlot, single accent hue + line styles (2026-08-15)
Phase 3 dashboard charts settled on **uPlot** (~8kb, zero default theme) rather than a heavier charting lib (ECharts/Recharts) or D3 by hand. All price lines share the one accent token `--accent`; variant/retailer series are distinguished by line style (solid / dashed / dotted) instead of extra hues, keeping the plot within the design system's "one restrained accent" rule. Crosshair + tooltip are hand-rolled: cursor data comes through uPlot's `setCursor` hook reading `u.cursor.idx`, tooltip HTML is token-styled (`text-text`, `border-border`, `bg-surface`). On a theme toggle, the chart rebuilds (read `getComputedStyle` once at mount); ResizeObserver keeps it responsive.

### Theme strategy: CSS variables + `data-theme`, dark default (2026-08-15)
Design tokens live as CSS custom properties in `src/app.css` with a dark-default `:root` and a light override under `[data-theme='light']`; Tailwind v4 maps them via `@theme inline` (`bg-surface`, `text-muted`, etc.). The theme toggle (`src/lib/theme.ts`) persists to `localStorage` (`trackaroo-theme`), and `app.html` has an inline pre-hydration script applying the stored theme to `documentElement.dataset.theme` before paint to avoid FOUC. Default is dark.

### Frontend DB path resolution (2026-08-15)
The default DB path in `web/src/lib/server/db.ts` is resolved relative to the server module with `fileURLToPath(import.meta.url)` up to the repo root: `../../../../db/trackaroo.db` (from `src/lib/server/`, that lands on `<repo>/db/trackaroo.db`). `TRACKAROO_DB` env overrides it when deploying elsewhere. Read-only open, `busy_timeout=5000`, WAL inherited from file header — mirrors the Python reader rule (never toggle journal mode).

### SvelteKit pages receive load results as a single `data` prop (2026-08-15)
Under Svelte 5 runes, `+page.svelte` components must destructure the load result through the single `data` prop (`let { data } = $props()`), NOT as individual top-level props. Initially the views destructured `{ summary, listings }` etc. directly, which SSR-rendered with every page 500ing (`Cannot read properties of undefined`). A production smoke test caught it — svelte-check and vitest did not, because component compile succeeds either way. Lesson: always smoke-test SSR-rendered routes against the real DB, not just typecheck/unit tests.

### Component smoke tests via client `mount()` (2026-08-15)
Vitest runs modules under node conditions, so `import { render } from 'svelte/server'` fails against client-compiled components and `mount()` from the bare `svelte` main resolves to the server build (which throws `lifecycle_function_unavailable`). Fix: in `vite.config.js`, when `process.env.VITEST` is set, alias the bare `svelte` specifier to `node_modules/svelte/src/index-client.js` so arrays of integration-style component tests can `mount()` in jsdom. The alias is scoped to vitest only — the production build keeps its node/server condition resolution.
