# Project Status

**Last updated:** 2026-08-17 (feature-suggestions §2–§4 shipped: band-chart product page + brand-grouped listings, compare route, 90-day low/high badges; repo cleanup §6 done — `resync_stock_status.py` removed, `fetch_test.py` → `scraper/scorptec.py`)
**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Phase 5 — frontend/UX improvements program + PCCG reliability (see Active Issues below).

## Active Issues

### ✅ COMPLETE: PCCG reliability — recurring 429 hard-rate-limit fixed (16-Aug-2026)
- **Root cause (confirmed by reading `scraper/pccg.py`):** both `algolia_single_search()` and `algolia_batch_search()` had an infinite loop — when every retry hit 429, the inner `for` exhausted, `page` never incremented, and the outer `while page < max_pages` rebuilt and retried the same request forever until the 300s subprocess timeout. Plus a second loop: in `algolia_single_search` reaching the last page `break`-ed only the inner loop, spinning on the final page even when not rate-limited. (Plan §10/11.1, `IMPROVEMENT_16_Aug_V1.md`.)
- **Fixes (all §10 items landed):**
  - `retries_exhausted` flag: exhausted retries now log a clear one-line reason and return, terminating in seconds instead of hanging
  - `Retry-After` header honoured on 429 (fallback to the fixed formula)
  - Non-JSON 200 responses (WAF/challenge pages) handled without crashing the run
  - 401/403 logged distinctly as possible credential rotation, not generic "API error"
  - Circuit breaker in `scrape_category()`: aborts after `TRACKAROO_ALGOLIA_CIRCUIT_BREAKER` (default 3) consecutive failed batches, returns what it matched
  - Cooldown file `data/pccg_cooldown.json` written on trip; scraper skips (exits 0, expected behaviour) within `TRACKAROO_PCCG_COOLDOWN_HOURS` (default 4); cleared on success
  - Short delay between CPU/GPU category passes (`TRACKAROO_CATEGORY_PASS_DELAY`, default 2s)
  - `health_checks.py` `check_today_coverage`: per-retailer "today has a snapshot?" warning (e.g. `pccg: no snapshot for today yet`)
  - DEPLOYMENT.md documents the safe scheduled `run_daily.py --pccg` retry (~12/18h) for the PCCG retry queue
- **New config knobs:** `TRACKAROO_ALGOLIA_CIRCUIT_BREAKER`, `TRACKAROO_PCCG_COOLDOWN_HOURS`, `TRACKAROO_PCCG_COOLDOWN_FILE`, `TRACKAROO_CATEGORY_PASS_DELAY` (all in `.env.example`).
- **Tests:** +14 `test_pccg_reliability.py` (429 termination, last-page exit, Retry-After, WAF-page guard, 403 logging, circuit breaker, cooldown) + 3 `test_health_checks.py` today-coverage tests → **277 backend tests passing** (was 251).
- **Live-checked:** `health_checks --db-only` shows `[OK] today_coverage_scorptec (191 variants)` + `[WARNING] today_coverage_pccg (no snapshot for today)` — the exact partial-day state the plan wanted named.

### ✅ COMPLETE: Real spec data (CPU + GPU) per `IMPROVEMENT_16_Aug_V1.md` §3–§9 (16-Aug-2026)
- **Sources (final):** GPU — `RightNow-AI/RightNow-GPU-Database` (Apache-2.0, TechPowerUp data via `dbgpu`; 2824 records, no pricing → MSRP delta stays dormant, MSRP shown in USD when present). Intel — `toUpperCase78/intel-processors` raw CSVs (core + Core Ultra files). AMD — first-party `amd.com` product pages (browser UA, 1s delay; 24/28 SKUs 200, the 4 OEM-only SKUs 404 by design). The plan's Option A (`felixsteinke/cpu-spec-dataset`) was rejected (AGPL-3.0, missing current-gen parts).
- **Schema:** new `specs` table (21 columns, `UNIQUE(product_id, source)`, `idx_specs_product`) in `db/schema.sql` + idempotent migration in `migrate.py`. One row per canonical product; `raw_json` keeps the verbatim source record for future fields.
- **`sync_specs.py`** (repo root): fetch (4xx definitive, 5xx/network retry with backoff) → pure parsers → match → upsert. Conflicting re-matches are flagged, never overwritten; unmatched records and vanished source rows are reported, never deleted. Report → `data/spec_sync_report.json`. Flags: `--category {gpu,cpu}`, `--dry-run`, `--report-only`; exits 1 on source failure. Never called from or by `run_daily.py` (§2 priority rule).
- **`spec_matching.py`:** name normalization (strip brand/AIB prefixes, lowercase, collapse whitespace) + exact normalized matching at the `products` level; no fuzzy guessing.
- **Coverage against the real watchlist:** Intel 25/25, AMD 24/28 (4 OEM-only SKUs have no public page), GPU 46/47 (RX 9070 XTX absent from the dataset).
- **Spec panel (§7):** `SpecPanel.svelte` renders below the price chart on `/product/[id]` (GPU: generation/architecture, VRAM, MSRP-if-present, shaders, TDP; CPU: generation, cores/threads, clocks, TDP; collapsed "Show full specs" details). Fetched via one extra `SELECT` inside `getProductHistory` — never joined into list/index queries (§7.3). No panel at all when a product has no spec row (§7.4).
- **Tests:** +89 backend (`test_specs_schema.py`, `test_specs_matching.py`, `test_sync_specs.py` → **366 backend tests**), +8 vitest (3 repos + 5 SpecPanel → **109**), +4 Playwright e2e (panel-below-chart layout, expand/collapse, no-panel negative, GPU fields → **27**).
- **First live sync run (16-Aug):** `python sync_specs.py` populated the production `specs` table — **95 rows** (46 GPU + 25 Intel + 24 AMD). This surfaced a real matching bug: `match_gpu`'s VRAM-variant guard filtered on `memorySize`, but `sync_specs.parse_gpu_records` emits normalized records whose VRAM key is `vram_gb` — so every VRAM-variant GPU (RTX 3050/3060/4060 Ti/5060 Ti, RX 9060 XT) came back unmatched. Fixed by reading VRAM from either key (`_record_vram`) + 3 regression tests locking the normalized-record shape (`TestMatchGpuNormalizedRecords`). Re-ran GPU sync → all 5 now match to the correct variant; GPU coverage is genuinely **46/47** (RX 9070 XTX is absent from the dataset). Second bug found by the same live run: `data/spec_sync_report.json` was picked up by the ingest glob and failed as a "snapshot". Fixed with an `is_snapshot_file()` convention predicate in `ingest.py` (used by `ingest.main()` and the e2e test) + 5 tests (`TestIsSnapshotFile`).
- **Watchlist correction (16-Aug, signed off):** `db/watchlist.csv` line 118 listed the Arc B570 as 12GB; the GPU dataset and Intel's official spec say 10GB — corrected to 10GB (separate commit `fix: Arc B570 watchlist VRAM 12GB -> 10GB`).

### ✅ COMPLETE: Feature suggestions §2–§4 + repo cleanup §6 (17-Aug-2026)
- **§2 Product detail redesign — band chart + brand-grouped listings:**
  - `getPriceBand` in `repos.ts`: per-day `MIN`/`MAX` in-stock price over non-bundle listings + cheapest-in-stock at the latest day; `getProductHistory` returns it as `band`
  - `PriceChart.svelte` rewritten: default view is a shaded low→high band (`uPlot` `bands` option) with a green "Cheapest in stock" marker; individual listing lines are hidden until toggled on
  - New `BrandGroupedListings.svelte` + pure `listingsPanel.ts` (`deriveListingBrand` via `web/src/lib/branding.ts` — AIB first-token map, fallback to product brand; no schema change): collapsible brand groups (`MSI · $619–$635 · 2 listings · 1 in stock`), free-text search against variant name, "In stock only" filter, cheapest-first sort, per-listing "Show on chart"/"On chart" toggle
- **§3 Compare feature:** new `/compare?ids=1,2` route (2–4 products, same category enforced server-side; shareable/bookmarkable) + `getComparisonData` joining products + specs + latest-day per-retailer in-stock prices; products page has per-card "Compare" checkboxes, category lock (different category disabled), and a floating "Compare (N) →" bar at ≥2
- **§4 Quick wins:** §4.1 "Lowest in 90 days" — `getPriceExtremes` (in-stock low/high, anchored to latest snapshot day) drives a green `90d low` badge on dashboard deal cards and `90d low`/`90d high` chips on the product page; §4.2 carousel `title=` tooltip and §4.3 insufficient-history state were already shipped earlier
- **§6 Repo cleanup:** `resync_stock_status.py` + `unit_testing/test_resync.py` deleted (one-off; bug fixed at source); `fetch_test.py` → `scraper/scorptec.py` via `git mv` (references updated in `run_daily.py`, `test_scraper.py`, `test_matching.py`, `db/watchlist.py`, README, SPEC.md, RAM_SCOPE.md); `migrate.py` docstring now says it's a historical-upgrade tool only
- **Regression after each milestone (all green):** pytest 365 / svelte-check 0 errors / vitest 154 / e2e 38
- **New tests:** +4 repos (getPriceBand, getComparisonData, getPriceExtremes), +10 `listingsPanel.test.ts` (new suite), +6 components (BrandGroupedListings interactions, ProductCard compare, CheapestCarousel badge/tooltip), +10 e2e (band chart + grouped listings panel, compare flow/validation, 90-day chips + carousel badge)

### 🔄 IN PROGRESS: Frontend & UX Improvement Program (15 Aug-2026)

Goal: make the dashboard actually help the user *find deals*, plus polish. Driven by user feedback + `FRONTEND_IMPROVEMENTS.md` (implementation brief in repo root).

**Progress tracker** (check off as each lands; update "What's verified" + regression numbers when done):

| # | Item | Status |
|---|------|--------|
| F1 | Docker: preload `data/*.json` history so a fresh container isn't empty | ✅ done — 1726 snapshots / 341 listings hydrated on first boot |
| F2 | Header: show last snapshot date, snapshot count, DB size | ✅ done — header shows `Last snapshot: YYYY-MM-DD`, `N snapshots`, `Size` (hidden on tiny screens) |
| F3 | Product search/filter by model name (CPU & GPU) | ✅ done — `Search by model` input (debounced, `?q=`) matches model/brand/variant |
| F4 | Sort/view cheapest product per category/model (e.g. all 5090s, cheapest first) | ✅ done — `Sort by price` (low→high / high→low, `?sort=`) on table views; pairs with search |
| F5 | Website icon / favicon | ✅ done — `static/favicon.svg` (accent-blue chart mark), linked in `app.html` |
| F6 | Additional visual improvements (after walk-through) | ⬜ planned |
| FI3 | Products page: card grid (grouped by model, expandable variants); keep dense table on Movers | ✅ done — one card per product (model, brand, category, cheapest in-stock "from $X" + retailer, listing count); expand reveals the variant table in compact mode; `sort=price-*` orders cards by cheapest in-stock price |
| FI1 | ~~Deal score (`deal_score`, `pct_below_30d_avg`, `is_all_time_low`) gated behind ≥7 snapshot days~~ | ❌ declined (17-Aug) — user doesn't want a deal score; removed from the plan |
| FI5 | Inline uPlot sparklines (7–30d) in rows/cards instead of "New listing" text; depends on accumulated history | ⬜ planned |
| ~~FI2~~ | ~~Product images (`image_url` column, hotlink retailer img, placeholder)~~ | ❌ declined — user doesn't want product images; scrapped from plan |

Notes:
- Git + GitHub: commits for this batch (F1–F5 + FI4 carousel) made after this entry; check `git status` is clean before ending sessions.
- No image attached to review; visual feedback taken from the live pages.
- FRONTEND_IMPROVEMENTS.md priority order (v2): FI2 (images — **declined**) → FI3 (cards ✅) → FI4 (carousel ✅) → FI1 (deal score — **declined 17-Aug**) → FI5 (sparklines). Carousel ships with the GPU/CPU toggle (resolved the GPU-only vs +CPU question).

### ✅ COMPLETE: Phase 4 Deployment — single Docker image (15 Aug-2026)
- **All-in-one Dockerfile** at the repo root: Python pipeline **and** SvelteKit dashboard in one container. `docker build -t trackaroo .` then `docker run -p 3000:3000 -v trackaroo-data:/data trackaroo`. No docker-compose required.
- **`deploy/entrypoint-single.sh`**: seeds the DB, starts the dashboard on :3000, runs the pipeline immediately then every `RUN_INTERVAL_HOURS` (default 24). `RUN_ONCE=1` runs one pipeline then exits (host crontab compatible).
- **Runtime gotcha fixed:** the scrapers use Python 3.12 PEP 701 f-strings (`f"{wp["vram_gb"]}gb"`), which are compile errors on 3.11 — so the runtime stage is `python:3.12-slim` with the Node binary copied from the Node build stage (bookworm apt `python3` is 3.11 and would crash).
- **`docker-compose.yml`** kept as an optional two-service split of the same image (`cron` pins the pipeline-only entrypoint, `web` runs the server). `web/Dockerfile` removed (orphaned).
- **Verified live in Docker:** image built, container booted — DB seeded (100 products), both scrapers ran OK, 315 listings ingested, backup created, dashboard served HTTP 200 with live data (315 listings today / 2 retailers).
- **Playwright e2e suite added** (19 tests in `e2e/app.spec.ts`): navigation, theme toggle/persistence/reload, dashboard stat tiles + table, category/retailer/tier URL filters, clear-filters, products empty-state, movers windows + link-through, product detail + 404. Includes a `goto()` helper that waits for Svelte hydration (`networkidle`) — clicks/selects before hydration silently did nothing.
- **Regression counts now:** 251 backend (15 modules via pytest; **277 as of 16-Aug** after PCCG-reliability + today-coverage tests), 90 frontend (vitest), 19 e2e (Playwright).
- **Docs updated:** README (quick-start Docker + frontend e2e + repo layout), DEPLOYMENT.md (single-image Option C primary), AGENTS.md (commands + Docker + E2E conventions).

### ✅ COMPLETE: Frontend M4–M5 (15 Aug-2026)
- **M4 polish & verify:**
  - §7a freshness wording — `LatestListingTable` now shows stale listings as `last seen {Nd} ago` in the freshness column, mutes the stale price cell, and drops hover on stale rows (never present stale data as current)
  - Dashboard "Listings today" stat carries the latest snapshot date as context subtext
  - Dark/light parity + chart tooltip token styling confirmed; `.num` mono/tabular-nums applied consistently; `meta name="description"` added to the dashboard
  - Full verification: `svelte-check` 0 errors, `npm run build` green, production `adapter-node` server smoke-tested against the real DB — `/`, `/products`, `/movers` for 24h/7d/30d (invalid window falls back to 7d), `/product/1` all 200; `/product/999999` 404
- **M5 tests & docs (partial):** added `test/components.test.ts` (13 tests) — presentational components (`Badge`, `StatTile`, `PriceChange`, `StockBadge`, `Chip`, `LatestListingTable`) mounted in jsdom, covering tone mapping, empty state, variant truncation, new-listing vs stale labelling, and "last seen" wording. Added vitest-only `svelte` → client-runtime alias in `vite.config.js` so client component tests can `mount()` (see DECISIONS.md).
- **Frontend tests now 90** (formats 27, change 11, filters 14, theme 7, repos 18, components 13) — all passing.
- **Docs updated:** DECISIONS.md (uPlot choice, theme strategy, DB path, `data` prop lesson, component-test alias), STATUS.md regression counts.

### ✅ COMPLETE: Frontend M0–M3 (14–15 Aug-2026)
- **Scaffold (M0):** SvelteKit + TypeScript + Tailwind v4 + `adapter-node` in `web/`; better-sqlite3 native build verified; `.gitignore` updated.
- **Design foundations (M1):** token-driven `app.css` with `data-theme` dark-default/light; `theme.ts` toggle persisted in `localStorage`; primitives `Badge`, `StatTile`, `PriceChange`, `Chip`, `Filters`, `Header` + `+layout.svelte`; `.num` mono/tabular-nums utility.
- **Server data layer (M2):** `src/lib/server/db.ts` (read-only singleton, `busy_timeout=5000`, never toggles journal mode, path `TRACKAROO_DB` → default `../../../../db/trackaroo.db`), `repos.ts` (`getSummary`, `getLatestListings`, `getProductHistory`, `getMovers`, `getBrands`), `formats.ts` + `change.ts`. Vitest suites: formats 27, change 11, repos 18 (temp DB seeded from `data/*.json`).
- **Views (M3):** Dashboard `/` (stat row + filterable latest-prices table), Products `/products` (full filterable table), Movers `/movers` (24h/7d/30d windows, abs/pct/price sort, up/down/all filter, not-enough-history state), Product `/product/[id]` (meta chips + uPlot `PriceChart.svelte` with one series per retailer listing, single accent hue + solid/dashed/dotted line styles + hand-rolled token-styled tooltip + retailer listings panel), filters via `searchParams`.
- **Verified:** `svelte-check` 0 errors, `vitest` 77 passing, `npm run build` green, and a live smoke test of the production `adapter-node` server against the real DB: `/`, `/products`, `/movers?window=24h` (invalid `window` falls back to 7d), `/product/1` all 200; `/product/999999` correctly 404; expected UI markers present (stat tiles, chips, chart container, retailer listings).
- **Bug caught by smoke test:** pages were destructuring load results as top-level props instead of SvelteKit's single `data` prop — fixed across all four pages (Svelte 5 `$props()`). Also fixed a mis-written file path for the product `+page.server.ts` (stray duplicate directory segment) that silently excluded the product load from the build.

### ✅ COMPLETE: PCCG Stock Status Hardening (13-Aug-2026)
- **What broke:** PCCG scraper marked every product `in_stock` regardless of actual state ("Sold Out", "ETA: ...", "Stock at Supplier" were ignored)
- **Fix:** `_map_stock_label()` in `scraper/pccg.py` correctly maps indicator labels to schema enum
- **Impact:** 37 DB rows corrected for 13-Aug PCCG (3 CPU out_of_stock, 32 GPU out_of_stock, 2 GPU preorder)
- **Resync script:** `resync_stock_status.py` — dry-run + apply mode, idempotent, scoped to PCCG only
- **Backup files:** `.backup_buggy.json` files retained for audit; ingest pipeline now filters them out
- **New tests:** `test_resync.py` (9 tests: dry-run, apply, idempotency, backup filtering, helpers)
- **DB state verified:** PCCG 13-Aug now shows 86 in_stock, 35 out_of_stock, 2 preorder (was 123 all in_stock)

### ✅ COMPLETE: Frontend-Readiness Hardening (13-Aug-2026)
- **WAL mode enabled** — the real DB now runs `journal_mode=WAL`, set by the writer/init paths (`ingest.init_db`, `seed.init_db`, `migrate`). This is what makes `run_daily.py` (cron) writing while the frontend reads safe.
- **Reader path fixed** — `query.get_connection` no longer toggles journal mode on open (the concurrency test exposed that a mode *change* on open takes an exclusive lock and can hit `database is locked` while the writer holds its lock). Readers inherit WAL from the file header; they set only `busy_timeout`.
- **New tests (+10 → 207 total, +9 resync → 226):** `test_concurrency.py` (reader/writer threads under WAL — no lock errors), `test_e2e.py` (scrape-shaped JSON → ingest → query → health checks, plus real `data/` files), price-anomaly regression (`test_appearing_disappearing_variants_no_false_positive`: jump flags, vanishing/appearing variants don't), and `test_performance.py` (per-query wall-clock bounds + EXPLAIN index assertion).
- **Indexes reviewed, measured not guessed** — the per-product history path already uses `idx_retailer_listings_product` + `idx_snapshots_listing_date` with no scans. Measured at ~10k snapshots: `show_latest_prices` 60ms, `show_biggest_movers` 7ms. No new index needed at this scale.
- **`.env.example` committed** — `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` documented; `.gitignore` now negates `.env.example` so the template stays tracked.
- **Anomaly sensitivity finding** — a single-day jump is only detectable once a listing has ~10+ history points (max deviation ≈ √N σ). Documented in `DECISIONS.md`; revisit calibration once listings accumulate more days.
- **Decisions locked for Phase 3** — frontend reads SQLite directly via better-sqlite3; SvelteKit scaffolds into `web/` in this repo.

### ✅ COMPLETE: New data point 13-Aug (5 days of history)
Live `run_daily.py` scrape both retailers → 315 snapshots ingested (0 errors); DB health 10/10. Listings now span 09–13 Aug; 310 of 333 listings have 3+ price points (the anomaly-detection floor).

### ✅ COMPLETE: Code Quality & Critical Bug Fixes (12-Aug-2026)
- **What changed:** Full code-quality pass across the backend plus a critical health-check bug fix
- **fetch_test.py:** Rewritten cleanly — the previous session had mangled it to 895 lines (blank line between every line); restored to a clean ~470-line version with type hints + logging
- **Health check bug:** `check_match_count_anomalies` counted `COUNT(DISTINCT product_id)` but thresholds were calibrated for variant/listing counts — produced false "Match count dropped: 54" warnings against 192 real variants. **Fixed** to count distinct listings; real DB now reports Scorptec 192 / PCCG 123 variants, both stable
- **Shared module:** `db/watchlist.py` extracted (parse_spec, load_watchlist, load_watchlist_products) — removed 3 copies of the same CSV/spec logic from `fetch_test.py`, `scraper/pccg.py`, `seed.py`
- **Type hints + logging:** Applied consistently to all modules (`ingest.py`, `health_checks.py`, `query.py`, `seed.py`, `run_daily.py`, `migrate.py`); removed unused imports (`timedelta`, `json`, `csv`, `List`)
- **PCCG scraper cleanup:** Replaced `__import__("urllib.parse").urlencode` code smell with the real import; fixed `global_idx` type issue; Algolia app ID/API key moved to env vars (`ALGOLIA_APP_ID`, `ALGOLIA_API_KEY`) with defaults
- **mwave references:** Removed stale `mwave` option from `query.py --retailer` choices
- **requirements.txt:** Added with pinned deps (requests, beautifulsoup4, pytest, pytest-mock)
- **New tests:** `test_query.py` (12 tests), `test_cli.py` (9 CLI smoke tests), multi-variant regression test for the anomaly fix
- **Tests:** **188 passing** (up from 175)

### ✅ COMPLETE: Multi-Variant Tracking (11-Aug-2026)
- **What changed:** Converted from "cheapest-only" to "all in-stock variants" tracking
- **Impact:** Each in-stock model/brand variant (e.g., GIGABYTE, ASUS, Zotac 5090) now gets its own `retailer_listing` and individual price history
- **Schema:** Added `variant_name TEXT` column to `retailer_listings`
- **Scrapers:** Both `fetch_test.py` (Scorptec) and `scraper/pccg.py` (PCCG) updated to save ALL in-stock variants
- **Ingestion:** `ingest.py` passes `variant_name` (from `scraped_name`) when creating listings
- **Queries:** `query.py` displays variant names in output
- **Health checks:** Thresholds updated for multi-variant counts (Scorptec: 90 total / 30 per category; PCCG: 20 total / 5 per category)
- **Verified:** 11-Aug Scorptec scrape captured 194 variants (up from 56), including 15 RTX 5090 variants from $6,599–$7,599

### ✅ COMPLETE: PCCG Scraper — Live & Verified (12-Aug-2026)
- The Algolia rate limit that was blocking live PCCG scrapes has cleared; the scraper is now verified against live data
- **12-Aug-2026:** 123 PCCG variants matched (21 CPU / 102 GPU)
- Multi-variant PCCG tracking confirmed working end-to-end

## What exists right now

- Project README (`README.md`) — objectives, what's built, quick start, repo layout
- Full specification (`SPEC.md`) — purpose, architecture, data model, scraping approach, frontend scope, risks, build phases
- Product scope rules (`SCOPE_RULES.md`) — 2-generation tracking limit, defined per product line
- Decision log (`DECISIONS.md`) — rationale for stack choices and key policies
- SQLite schema (`db/schema.sql`) — `products` / `retailer_listings` (with `variant_name`) / `price_snapshots` with triggers
- Watchlist (`db/watchlist.csv`) — 100 products (53 CPUs, 47 GPUs) across 3 generations per SCOPE_RULES.md
- Shared watchlist loader (`db/watchlist.py`) — parse_spec + load_watchlist + load_watchlist_products
- Scorptec scraper (`scraper/scorptec.py`) — working, multi-variant, outputs separate CPU/GPU JSON files (renamed from `fetch_test.py` 17-Aug per feature-suggestions §6.3)
- PCCG scraper (`scraper/pccg.py`) — working, multi-variant, verified live (Algolia API, no Playwright)
- `migrate.py` — schema migration tool for historical upgrades only (adds `variant_name` column + WAL to pre-12-Aug DBs)
- `seed.py` — populates SQLite `products` table from `db/watchlist.csv`
- `ingest.py` — reads scraped JSON files and writes `retailer_listings` + `price_snapshots` into the DB
- `query.py` — query tool with three modes: latest prices, trends, biggest movers (shows variant names)
- `health_checks.py` — validates scraped JSON output and DB state (multi-variant thresholds; variant-count anomaly detection)
- `run_daily.py` — one-command daily runner: scrapes both retailers → validates → ingests → validates DB
- `sync_specs.py` — weekly spec sync: fetches GPU/Intel/AMD spec datasets → matches to `products` → upserts `specs` rows; `--category` / `--dry-run` / `--report-only`; report to `data/spec_sync_report.json`
- `spec_matching.py` — name normalization + product→spec-dataset matching (exact normalized match, no guessing)
- `backup_db.py` — standalone DB backup with retention pruning
- `requirements.txt` — pinned dependencies
- `Dockerfile` — **single all-in-one image** (Python pipeline + dashboard); `docker run -p 3000:3000 -v trackaroo-data:/data trackaroo`
- `docker-compose.yml` — optional two-service split of the same image
- `deploy/entrypoint-single.sh` — all-in-one entrypoint (seed → dashboard → pipeline scheduler); `entrypoint.sh` for pipeline-only
- `.dockerignore` — excludes regenerable artifacts and the web build context
- `unit_testing/` — **365 regression tests** across 18 modules (seed, matching, schema, ingestion, scraper, PCCG reliability, daily runner, health checks, query, concurrency/WAL, E2E pipeline, performance, CLI smoke tests, backup, config, specs schema, specs matching, sync_specs; `test_resync.py` removed 17-Aug with its one-off script)
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking
- Historical data: Scorptec + PCCG snapshots for 09-Aug through 17-Aug (16-Aug PCCG missing — rate-limited; 17-Aug full: 185 Scorptec + 123 PCCG = 308 snapshots)
- `.env.example` — committed template documenting Algolia env vars (and `.gitignore` negation)
- `PHASE3_PLAN.md` — executable Phase 3 frontend handoff plan (locked decisions, data model facts, M0–M5 steps)
- `web/` — Phase 3 frontend (SvelteKit + TS + Tailwind v4 + adapter-node):
  - `src/app.css` + `src/lib/theme.ts` — token system, dark/light, theme toggle
  - `src/lib/components/` — `Badge`, `StatTile`, `PriceChange`, `Chip`, `Filters`, `Header`, `LatestListingTable` (also renders `compact` inside product cards), `PriceChart` (uPlot; low/high band + cheapest-in-stock + toggleable listing overlays), `SpecPanel` (product-page spec panel), `CheapestCarousel` (dashboard cheapest-deals, GPU/CPU toggle, 90d-low badge), `ProductCard` (products-page card grid, compare checkbox), `BrandGroupedListings` (product-page grouped listings panel), `+layout.svelte`
  - `src/lib/` — `branding.ts` (client-safe AIB brand derivation), `listingsPanel.ts` (pure grouped-listings logic), `formats.ts`/`change.ts`
  - `src/lib/server/` — `db.ts` (better-sqlite3 read-only singleton), `repos.ts` (incl. `groupListingsByProduct`, `getPriceBand`, `getComparisonData`, `getPriceExtremes`)
  - Routes — `/` dashboard (table), `/products` (card grid, expandable variant listings, compare selection), `/compare` (side-by-side specs + prices), `/movers` (dense table), `/product/[id]` with URL-driven filters
  - `test/` — vitest: formats (28), change (11), filters (18), theme (7), repos (44), components (36), listingsPanel (10) — **154 tests**
  - `e2e/` — Playwright: 38 tests (app.spec.ts + seed.mjs deterministic DB, incl. spec-panel, grouped-listings panel, compare flow/validation, 90d-low badges + chips) — **38 tests**

## What's verified

- **Backend:** 365 tests pass — seed, matching, schema/triggers, ingestion, scrapers, PCCG reliability, daily runner, health checks, query, concurrent WAL access, E2E pipeline, query performance, CLI entry points, backup, config, specs schema/matching/sync
- **Stock status:** PCCG 13-Aug corrected from 123 all-in_stock to 86 in_stock + 35 out_of_stock + 2 preorder; resync verified idempotent (one-off `resync_stock_status.py` tool since removed — bug fixed at the source)
- **Concurrency:** test proving readers hit no lock errors while a writer commits under WAL (stable 10/10)
- **Performance:** `show_latest_prices` 60ms / `show_biggest_movers` 7ms on ~10k synthetic snapshots; history query provably index-backed
- **Scorptec:** 192 variants matched on 13-Aug (multi-variant)
- **PCCG:** 123 variants matched on 13-Aug (multi-variant, verified live)
- **Health checks:** 10/10 green on the real DB — JSON validation, freshness, match-count anomalies (variant-based), price anomalies (active; 310 of 333 listings now past the 3-point floor)
- **Schema:** `variant_name` column present; `last_snapshot_at` auto-maintained by triggers; DB in WAL mode
- **Code quality:** all modules type-hinted + logged; shared watchlist module deduplicates logic; secrets moved to env vars
- **Spec sync:** live-fetch coverage verified against the real watchlist — Intel 25/25, AMD 24/28 (4 OEM-only SKUs have no public page), GPU 46/47 (RX 9070 XTX absent from the dataset); upsert conflict/unmatched/vanished-row behaviour locked in by tests; price pipeline untouched (§2 priority rule)
- **Spec panel:** renders below the price chart on `/product/[id]` (E2E bounding-box assertion), hidden when a product has no spec row; fetched via one extra `SELECT` in the detail load only — never joined into list/index queries
- **Frontend:** `svelte-check` 0 errors; vitest **154 passing**; Playwright e2e **38 passing**; production build green; live `adapter-node` smoke test of all routes against the real DB (dashboard/products/movers/product 200s, unknown product 404, bad window param falls back)
- **Docker:** single all-in-one image built and booted — DB seeded, both scrapers OK, 315 listings ingested, backup created, dashboard HTTP 200 with live stats
- **Feature suggestions §2–§4:** band chart + brand-grouped listings on `/product/[id]`, `/compare?ids=` (2–4 same-category products), `90d low`/`90d high` on product page + dashboard cards — regression green after each milestone
- **Regression:** backend 365 passing (pytest); frontend 154 passing (vitest) + 38 e2e (Playwright)

## What's NOT done yet

1. **Hardcoded values review** — Scan for magic numbers, hardcoded thresholds, paths that should be config-driven (e.g., health check limits, BATCH_SIZE, timeouts). Lower priority; can be done as a separate pass.
2. **Frontend (Phase 3) — complete.** M0–M5 done: views, polish/verify, units + e2e. Remaining: final visual QA eyeball (any new filters/hardening belong to Phase 4).
3. **Detailed deployment** — done: single Docker image + compose split verified. Optional extras for later: reverse proxy (Caddy/nginx/Traefik) for TLS, host-cron option docs already in DEPLOYMENT.md.
4. **Hardening (Phase 4, remaining)** — reverse proxy/TLS, Prometheus-style monitoring, alerting on pipeline failure (current: exit codes + logs).
5. **Price anomaly detection maturity** — a single-day jump only trips the 3σ check once a listing has ~10+ history points (max deviation ≈ √N); most listings still below that depth. See DECISIONS.md.
6. **RAM tracking (RAM_SCOPE.md)** — planned but not started; not required for Phase 3/4

## Next concrete steps

1. **Accumulate more scrape data** — run daily scrapes to build historical depth (now 9 days, 09–17 Aug; anomaly detection sensitivity improves with each new ≥10-point listing)
2. **Reverse proxy + TLS** — put the dashboard behind Caddy/nginx/Traefik if internet-facing (docs in DEPLOYMENT.md)
3. **Monitoring/alerting** — watch pipeline success via exit codes / logs (health checks already log "DB health: all N checks passed")
4. **Weekly spec sync cadence** — `sync_specs.py` is built and has run once live; schedule it (e.g. Sunday 03:00, clear of the daily price run) when the deployment cron is finalised

## Regression test count

- **365 tests (was 374; −9 = one-off `resync_stock_status.py` + its `test_resync.py` removed 17-Aug)** across 18 test modules via pytest
  - `test_seed.py` — seed, watchlist loading, schema creation
  - `test_matching.py` — product matching logic
  - `test_schema.py` — schema validation, triggers, constraints
  - `test_ingest.py` — ingestion pipeline + TestVariantTracking
  - `test_scraper.py` — scraper URL fallback, category mapping
  - `test_pccg_reliability.py` — **new:** 429-termination, last-page exit, Retry-After, WAF-page guard, 403 logging, circuit breaker, cooldown (14)
  - `test_run_daily.py` — daily runner integration
  - `test_health_checks.py` — JSON validation, DB freshness, match/price anomalies + **today-coverage (3 new)** + variant appear/disappear regression
  - `test_query.py` — query tool (latest prices, trends, biggest movers)
  - `test_concurrency.py` — WAL-enable + concurrent read/write under load
  - `test_e2e.py` — full pipeline: scrape-shaped JSON → ingest → query → health checks
  - `test_performance.py` — query wall-clock bounds + index usage over ~10k synthetic snapshots
  - `test_cli.py` — CLI entry-point smoke tests
  - `test_backup.py` — backup_db.py retention
  - `test_config.py` — config.py env-override
  - `test_specs_schema.py` — **new:** specs table DDL + idempotent migration
  - `test_specs_matching.py` — **new:** name normalization + product→dataset matching
  - `test_sync_specs.py` — **new:** fetch/parse/upsert, conflict no-overwrite, report, CLI flags
- **Frontend unit (vitest, `web/`) — 154 tests** across 7 suites (formats 28, change 11, filters 18, theme 7, repos 44, components 36, listingsPanel 10) — against temp DBs seeded from `data/*.json`
- **Frontend e2e (Playwright, `web/e2e/`) — 38 tests** — navigation, theme, dashboard filters, **products card grid (3: heading+cards, empty state, card expand/collapse)**, **compare (4: flow to /compare, category lock, clear bar, invalid URLs)**, movers, product detail, **grouped listings (4: brand groups, expand+toggle, search, in-stock filter)**, **spec panel (4: below-chart layout, expand/collapse, no-panel negative, GPU fields)**, **90d chips + carousel badge (2)**; runs via `npm run test:e2e` against a seeded dev server

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.