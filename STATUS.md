# Project Status

**Last updated:** 2026-08-11 (multi-variant tracking complete)
**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Multi-variant tracking — all tests passing, ready for Phase 3 (frontend)

## Active Issues

### ✅ COMPLETE: Multi-Variant Tracking (11-Aug-2026)
- **What changed:** Converted from "cheapest-only" to "all in-stock variants" tracking
- **Impact:** Each in-stock model/brand variant (e.g., GIGABYTE, ASUS, Zotac 5090) now gets its own `retailer_listing` and individual price history
- **Schema:** Added `variant_name TEXT` column to `retailer_listings` via `migrate.py`
- **Scrapers:** Both `fetch_test.py` (Scorptec) and `scraper/pccg.py` (PCCG) updated to save ALL in-stock variants
- **Ingestion:** `ingest.py` passes `variant_name` (from `scraped_name`) when creating listings
- **Queries:** `query.py` displays variant names in output
- **Tests:** 5 new `TestVariantTracking` test cases added (173 total tests, all passing)
- **Health checks:** Thresholds updated for multi-variant counts (Scorptec: 90 total / 30 per category)
- **Verified:** Fresh 11-Aug Scorptec scrape captured 194 variants (up from 56), including 15 RTX 5090 variants from $6,599–$7,599
- **Files changed:** `fetch_test.py`, `scraper/pccg.py`, `db/schema.sql`, `migrate.py`, `ingest.py`, `query.py`, `health_checks.py`, `unit_testing/test_ingest.py`, `unit_testing/test_health_checks.py`, `unit_testing/test_run_daily.py`

### ⚠️ PCCG Scraper — Algolia Rate Limited
- **Problem:** Algolia free tier returns 429 (Too Many Requests) on every attempt
- **Status:** Multi-variant code is ready but untested against live PCCG data
- **Next attempt:** Wait for rate limit to reset, then run `python scraper/pccg.py`

## What exists right now

- Project README (`README.md`) — objectives, what's built, quick start, repo layout
- Full specification (`SPEC.md`) — purpose, architecture, data model, scraping approach, frontend scope, risks, build phases
- Product scope rules (`SCOPE_RULES.md`) — 2-generation tracking limit, defined per product line
- Decision log (`DECISIONS.md`) — rationale for stack choices and key policies
- SQLite schema (`db/schema.sql`) — `products` / `retailer_listings` (with `variant_name`) / `price_snapshots` with triggers
- Watchlist (`db/watchlist.csv`) — 100 products (53 CPUs, 47 GPUs) across 3 generations per SCOPE_RULES.md
- Scorptec scraper (`fetch_test.py`) — working, multi-variant, outputs separate CPU/GPU JSON files
- PCCG scraper (`scraper/pccg.py`) — multi-variant code ready (live data blocked by Algolia rate limit)
- `migrate.py` — schema migration script (adds `variant_name` column)
- `seed.py` — populates SQLite `products` table from `db/watchlist.csv`
- `ingest.py` — reads scraped JSON files and writes `retailer_listings` + `price_snapshots` into the DB
- `query.py` — query tool with three modes: latest prices, trends, biggest movers (shows variant names)
- `health_checks.py` — validates scraped JSON output and DB state (updated thresholds for multi-variant)
- `run_daily.py` — one-command daily runner: scrapes both retailers → validates → ingests → validates DB
- `unit_testing/` — **173 regression tests** across 7 modules (seed, matching, schema, ingestion, scraper, daily runner, health checks, variant tracking)
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking
- Historical data: Scorptec snapshots for 09-Aug, 10-Aug, 11-Aug; PCCG snapshots for 10-Aug

## What's verified

- **Multi-variant tracking:** 173 tests pass in 0.82s — covers variant creation, variant name storage, cheapest queries, per-variant price history, product count integrity
- **Scorptec:** 194 variants matched on 11-Aug (multi-variant). 15 RTX 5090 variants captured
- **PCCG:** 41/100 matched on 10-Aug (single-variant; multi-variant untested)
- **Health checks:** Thresholds updated — Scorptec min_total=90, min_per_category=30
- **Schema:** `variant_name` column added via migration, tested with named column access
- **Regression:** All existing 168 tests + 5 new variant tests = 173 passing

## What's NOT done yet

1. **PCCG multi-variant live test** — blocked by Algolia rate limit
2. **Price anomaly detection** — needs 3+ data points per product/retailer; will activate as more scrape dates accumulate
3. **Frontend (Phase 3)** — SvelteKit dashboard, charts, biggest movers view
4. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups

## Next concrete steps

1. **Get fresh PCCG data** — wait for Algolia rate limit to reset, verify multi-variant on PCCG
2. **Accumulate more scrape data** — run daily scrapes to build historical data
3. **Move to Phase 3 (frontend)** — SvelteKit dashboard, charts, biggest movers view
4. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups

## Regression test count

- **173 tests** across 7 test modules — all passing in 0.82s
  - `test_seed.py` — seed, watchlist loading, schema creation
  - `test_matching.py` — product matching logic
  - `test_schema.py` — schema validation, triggers, constraints
  - `test_ingest.py` — ingestion pipeline + **TestVariantTracking** (5 new tests)
  - `test_scraper.py` — scraper URL fallback, category mapping
  - `test_run_daily.py` — daily runner integration
  - `test_health_checks.py` — JSON validation, DB freshness, match count anomalies, price anomalies

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.
