# Project Status

**Last updated:** 2026-08-12 (code-quality hardening complete; PCCG verified live)
**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Backend complete and hardened — all tests passing, ready for Phase 3 (frontend)

## Active Issues

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
- `requirements.txt` — pinned dependencies
- `unit_testing/` — **188 regression tests** across 9 modules (seed, matching, schema, ingestion, scraper, daily runner, health checks, query, CLI smoke tests)
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking
- Historical data: Scorptec + PCCG snapshots for 09-Aug through 12-Aug

## What's verified

- **Backend:** 188 tests pass in ~0.8s — seed, matching, schema/triggers, ingestion, scrapers, daily runner, health checks, query, CLI entry points
- **Scorptec:** 192 variants matched on 12-Aug (multi-variant); historically up to 194
- **PCCG:** 123 variants matched on 12-Aug (multi-variant, verified live)
- **Health checks:** 10/10 green on the real DB — JSON validation, freshness, match-count anomalies (variant-based), price anomalies (active; most listings still accumulating 3+ history points)
- **Schema:** `variant_name` column present; `last_snapshot_at` auto-maintained by triggers
- **Code quality:** all modules type-hinted + logged; shared watchlist module deduplicates logic; secrets moved to env vars
- **Regression:** 188 passing

## What's NOT done yet

1. **Frontend (Phase 3)** — SvelteKit dashboard, charts, biggest movers view
2. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups
3. **Price anomaly detection maturity** — detection code is active but needs more scrape dates for every listing to exceed the 3-point minimum history
4. **RAM tracking (RAM_SCOPE.md)** — planned but not started; not required for Phase 3

## Next concrete steps

1. **Move to Phase 3 (frontend)** — SvelteKit dashboard reading SQLite directly
2. **Accumulate more scrape data** — run daily scrapes to build historical depth
3. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups

## Regression test count

- **188 tests** across 9 test modules — all passing in ~0.8s
  - `test_seed.py` — seed, watchlist loading, schema creation
  - `test_matching.py` — product matching logic
  - `test_schema.py` — schema validation, triggers, constraints
  - `test_ingest.py` — ingestion pipeline + TestVariantTracking
  - `test_scraper.py` — scraper URL fallback, category mapping
  - `test_run_daily.py` — daily runner integration
  - `test_health_checks.py` — JSON validation, DB freshness, match count anomalies, price anomalies
  - `test_query.py` — query tool (latest prices, trends, biggest movers)
  - `test_cli.py` — CLI entry-point smoke tests

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.