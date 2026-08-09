# Project Status

**Last updated:** 2026-08-10
**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Phase 1 & Step 2 (Full Pipeline Validation) complete

## What exists right now

- Project README (`README.md`) — objectives, what's built, quick start, repo layout
- Full specification (`SPEC.md`) — purpose, architecture, data model, scraping approach, frontend scope, risks, build phases
- Product scope rules (`SCOPE_RULES.md`) — 2-generation tracking limit, defined per product line
- Decision log (`DECISIONS.md`) — rationale for stack choices and key policies
- SQLite schema (`db/schema.sql`) — `products` / `retailer_listings` / `price_snapshots` with triggers. Tested and working.
- Watchlist (`db/watchlist.csv`) — 100 products (53 CPUs, 47 GPUs) across 3 generations per SCOPE_RULES.md
- Scorptec scraper (`fetch_test.py`) — working, outputs separate CPU/GPU JSON files with matched products, prices, URLs
- PCCG scraper (`scraper/pccg.py`) — working via Algolia API (no Playwright needed), batched multi-query with rate-limit handling
- Historical data: Scorptec snapshots for 09-Aug and 10-Aug; PCCG snapshots for 10-Aug
- `data/` folder for scraped JSON output
- `seed.py` — populates SQLite `products` table from `db/watchlist.csv` (idempotent, supports `--dry-run`)
- `ingest.py` — reads scraped JSON files and writes `retailer_listings` + `price_snapshots` into the DB (idempotent, supports `--dry-run`, `--file`, `--date`)
- `unit_testing/` — 103 regression tests covering seed, matching, schema, ingestion, and full pipeline validation (runs in ~0.22s)
- `query.py` — query tool with three modes: latest prices, trends, biggest movers
- `run_daily.py` — one-command daily runner: scrapes both retailers → saves JSON → ingests into DB
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking

## What's verified

- **Scorptec:** 56/100 matched on 10-Aug (32 CPUs, 24 GPUs). Unmatched products are delisted or use different naming at Scorptec.
- **PCCG:** 41/100 matched on 10-Aug (25 CPUs, 16 GPUs). Many older-gen GPUs (RTX 30/40, RX 6000/7000) are delisted at PCCG — they only stock newer gens.
- **Watchlist:** Verified against SCOPE_RULES.md — all 100 products fall within the 2-generation rule.
- **Schema:** Tested against SQLite — tables, constraints, and `last_snapshot_at` triggers all work.
- **Variant guard:** Fixed in `scraper/pccg.py` — prevents false matches like 5800X→5800X3D, 5070→5070 Ti, 14700K→14700KF
- **Ingestion pipeline:** Verified with real data — 121 snapshots across 2 dates (09-Aug and 10-Aug) ingested into DB with 0 errors
- **Regression tests:** 108 tests passing in 0.24s — seed (19), matching (20), schema (31), ingestion (26), pipeline integration (7), daily runner (5)
- **Full pipeline validation (Step 2):** Complete — watchlist → scrape → JSON → DB → query verified end-to-end with real data
- **Named column access:** Enabled `sqlite3.Row` row_factory in test fixtures for cleaner assertions

## What's NOT done yet

1. **PCCG data quality** — the 10-Aug PCCG CPU file has one false match (Ryzen 7 5800X matched to 5800X3D). The guard fix is in code but needs a fresh run to regenerate clean data.
2. **Scorptec URL gaps** — a few products have empty `url` fields (missing title link in product grid). Minor.
3. **Frontend (Phase 3)** — SvelteKit dashboard, charts, biggest movers view
4. **Hardening (Phase 4)** — Docker deployment, cron scheduling, backups

## Next concrete steps

1. Re-run PCCG scraper when rate limits reset (to get clean data with the false-match guard)
2. Move to Phase 3 (frontend) once the data pipeline is proven

### Step 2: Full Pipeline Validation — ✅ COMPLETE

**Goal:** Prove the complete data flow works end-to-end before building the frontend.

**Actions:**
1. **Scrape fresh data** from one retailer (Scorptec or PCCG) for a single product to verify the scraper still works
2. **Ingest the fresh JSON** into the DB using `ingest.py`
3. **Run SQL queries** to verify:
   - Product exists in `products` table
   - Listing exists in `retailer_listings` table
   - Snapshot exists in `price_snapshots` table
   - Triggers fired correctly (`last_snapshot_at` updated)
4. **Compare prices** across dates (09-Aug vs 10-Aug) to verify trend data is usable
5. **Create a simple query script** (`query.py`) to demonstrate data retrieval (e.g., "show me all RTX 5070 prices across retailers")
6. **Add pipeline integration test** to `unit_testing/` that simulates the full flow with mock data

**Success criteria:**
- Fresh scrape produces valid JSON
- Ingestion writes correct rows with no errors
- SQL queries return expected data
- Price trends across dates are queryable
- All 96 existing tests still pass

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.
