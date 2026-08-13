# Project Status

**Last updated:** 2026-08-14 (Phase 3 frontend build plan finalized in `PHASE3_PLAN.md`; implementation not yet started)
**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Backend complete and frontend-ready — all tests passing, Phase 3 (frontend) is next

## Active Issues

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
- Scorptec scraper (`fetch_test.py`) — working, multi-variant, outputs separate CPU/GPU JSON files
- PCCG scraper (`scraper/pccg.py`) — working, multi-variant, verified live (Algolia API, no Playwright)
- `migrate.py` — schema migration script (adds `variant_name` column)
- `seed.py` — populates SQLite `products` table from `db/watchlist.csv`
- `ingest.py` — reads scraped JSON files and writes `retailer_listings` + `price_snapshots` into the DB
- `query.py` — query tool with three modes: latest prices, trends, biggest movers (shows variant names)
- `health_checks.py` — validates scraped JSON output and DB state (multi-variant thresholds; variant-count anomaly detection)
- `run_daily.py` — one-command daily runner: scrapes both retailers → validates → ingests → validates DB
- `resync_stock_status.py` — corrects stock_status after scraper fixes; dry-run + apply mode, idempotent
- `requirements.txt` — pinned dependencies
- `unit_testing/` — **226 regression tests** across 14 modules (seed, matching, schema, ingestion, scraper, daily runner, health checks, query, concurrency/WAL, E2E pipeline, performance, CLI smoke tests, resync)
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking
- Historical data: Scorptec + PCCG snapshots for 09-Aug through 13-Aug
- `.env.example` — committed template documenting Algolia env vars (and `.gitignore` negation)
- `PHASE3_PLAN.md` — executable Phase 3 frontend handoff plan (locked decisions, data model facts, M0–M5 steps)

## What's verified

- **Backend:** 226 tests pass in ~6s — seed, matching, schema/triggers, ingestion, scrapers, daily runner, health checks, query, concurrent WAL access, E2E pipeline, query performance, CLI entry points, resync
- **Stock status:** PCCG 13-Aug corrected from 123 all-in_stock to 86 in_stock + 35 out_of_stock + 2 preorder; resync verified idempotent
- **Concurrency:** test proving readers hit no lock errors while a writer commits under WAL (stable 10/10)
- **Performance:** `show_latest_prices` 60ms / `show_biggest_movers` 7ms on ~10k synthetic snapshots; history query provably index-backed
- **Scorptec:** 192 variants matched on 13-Aug (multi-variant)
- **PCCG:** 123 variants matched on 13-Aug (multi-variant, verified live)
- **Health checks:** 10/10 green on the real DB — JSON validation, freshness, match-count anomalies (variant-based), price anomalies (active; 310 of 333 listings now past the 3-point floor)
- **Schema:** `variant_name` column present; `last_snapshot_at` auto-maintained by triggers; DB in WAL mode
- **Code quality:** all modules type-hinted + logged; shared watchlist module deduplicates logic; secrets moved to env vars
- **Regression:** 226 passing

## What's NOT done yet

1. **Hardcoded values review** — Scan for magic numbers, hardcoded thresholds, paths that should be config-driven (e.g., health check limits, BATCH_SIZE, timeouts). Lower priority; can be done as a separate pass before frontend.
2. **Frontend (Phase 3)** — SvelteKit dashboard in `web/`, reading the DB directly via better-sqlite3: product table, price history charts, biggest movers
3. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups
4. **Price anomaly detection maturity** — a single-day jump only trips the 3σ check once a listing has ~10+ history points (max deviation ≈ √N); most listings still below that depth. See DECISIONS.md.
5. **RAM tracking (RAM_SCOPE.md)** — planned but not started; not required for Phase 3

## Next concrete steps

1. **Move to Phase 3 (frontend)** — SvelteKit dashboard in `web/` reading `db/trackaroo.db` directly via better-sqlite3 (WAL already active); scaffold and build per `PHASE3_PLAN.md`
2. **Accumulate more scrape data** — run daily scrapes to build historical depth (now 5 days; anomaly detection sensitivity improves with each new ≥10-point listing)
3. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups

## Regression test count

- **226 tests** across 14 test modules — all passing in ~6s
  - `test_seed.py` — seed, watchlist loading, schema creation
  - `test_matching.py` — product matching logic
  - `test_schema.py` — schema validation, triggers, constraints
  - `test_ingest.py` — ingestion pipeline + TestVariantTracking
  - `test_scraper.py` — scraper URL fallback, category mapping
  - `test_run_daily.py` — daily runner integration
  - `test_health_checks.py` — JSON validation, DB freshness, match/price anomalies + variant appear/disappear regression
  - `test_query.py` — query tool (latest prices, trends, biggest movers)
  - `test_concurrency.py` — WAL-enable + concurrent read/write under load
  - `test_e2e.py` — full pipeline: scrape-shaped JSON → ingest → query → health checks
  - `test_performance.py` — query wall-clock bounds + index usage over ~10k synthetic snapshots
  - `test_cli.py` — CLI entry-point smoke tests
  - `test_resync.py` — resync_stock_status.py: dry-run, apply, idempotency, backup filtering

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.