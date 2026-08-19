# Trackaroo — Australian CPU/GPU Price Tracker

Daily price and stock tracking for desktop CPUs and GPUs across Australian retailers, with full price history and a self-hosted dashboard.

**Personal use · Single-user · Self-hosted · Daily snapshot cadence**

## Objectives

1. Take a daily price + stock snapshot for every tracked CPU/GPU at each retailer.
2. Store full price history (never delete data) so trends can be computed over any window.
3. Match the same physical product across retailers for direct price comparison.
4. Surface price history charts, biggest movers, and deal signals via a web dashboard.
5. Run unattended with visibility when something breaks.

## Retailers

| Retailer | Status | Method |
|---|---|---|
| [Scorptec](https://www.scorptec.com.au/) | ✅ Active | HTTP + BeautifulSoup (server-rendered HTML) |
| [PC Case Gear](https://www.pccasegear.com/) | ✅ Active | Algolia search API (JS-rendered site) |
| ~~Mwave~~ | ❌ Removed | CloudFront bot protection blocks scraping |

## Spec data sources

Static hardware specs (VRAM, cores, clocks, TDP, launch date, GPU die, bus
interface, memory bandwidth, process node, foundry, cache layout, memory
support…) come from external datasets fetched weekly by `sync_specs.py` —
never scraped live per request, and never joined into the price pipeline:

| Source | Category | Method |
|---|---|---|
| [RightNow-AI/RightNow-GPU-Database](https://github.com/RightNow-AI/RightNow-GPU-Database) | GPU | Raw JSON on GitHub (Apache-2.0; TechPowerUp data via the `dbgpu` project) |
| [toUpperCase78/intel-processors](https://github.com/toUpperCase78/intel-processors) | Intel CPU | Raw CSVs on GitHub |
| [amd.com](https://www.amd.com) first-party product pages | AMD CPU | Polite fetch (browser user-agent, 1s delay between pages) |

Each of the 13 TechPowerUp-grade fields is extracted from the source record's
verbatim `raw_json` (the parsers map them up front for fresh rows, and the
idempotent `backfill_specs_extra()` re-derives them for existing rows on every
sync):

- **GPU** (RightNow = TechPowerUp): `gpu_die` ← `gpuName` (e.g. GB202), `bus_interface` ← `busInterface` (e.g. PCIe 5.0 x16), `memory_bandwidth_gbps` ← `memoryBandwidth` (GB/s, e.g. 1790 ≈ 1.79 TB/s), `memory_clock_mhz` ← `memoryClock`, `process_nm` ← `processSize`, `foundry` ← `foundry` (TSMC), `l2_cache_mb` ← `l2Cache` (e.g. 96 MB on RTX 5090).
- **Intel** (`intel-processors` CSVs): `codename` ← `Code Name` (Arrow Lake), `process_nm` ← `Lithography(nm)`, `memory_speed_mhz` ← `Max Memory Speed(MHz)`, `memory_channels` ← `Max Memory Channels`, `memory_types` ← `Memory Types`, `integrated_graphics` ← `Integrated Graphics`, and `cache_l3_mb` ← `Cache(MB)` (Intel "Smart Cache" equals TechPowerUp's L3 for the desktop watchlist).
- **AMD** (first-party amd.com): `codename` ← `Former Codename` (socket tag stripped, e.g. "Granite Ridge"), `l1_cache_kb` ← `L1 Cache`, `l2_cache_mb` ← `L2 Cache`, `memory_speed_mhz` ← highest data rate in `Max Memory Speed`, `memory_channels` ← `Memory Channels`, `memory_types` ← `System Memory Type` (DDR5), `integrated_graphics` ← `Graphics Model`.

**Known gaps:** GPU launch MSRPs come from the curated `db/launch_msrp.json`
mapping (applied by `backfill_msrp.py` on every container boot — the spec
sources don't publish pricing); a handful of OEM-only SKUs have no amd.com page
and stay unmatched. Specs refresh on a **weekly,
best-effort** schedule (container default: Sunday 03:00 via `SPEC_SYNC_DOW` /
`SPEC_SYNC_HOUR`; bare host: `0 3 * * 0` crontab). Re-running `sync_specs.py`
is always safe — rows are never deleted, conflicts are reported not overwritten,
and the extra-column backfill is idempotent. Per-run match/conflict/unmatched
detail lands in `data/spec_sync_report.json` (`python sync_specs.py --report-only`).

## What's built

| Component | Status | Details |
|---|---|---|
| **Watchlist** | ✅ Complete | 100 products (53 CPUs, 47 GPUs) governed by 2-generation rule |
| **SQLite schema** | ✅ Complete | `products` / `retailer_listings` / `price_snapshots` with triggers |
| **Scorptec scraper** | ✅ Complete | Multi-variant: captures ALL in-stock model variants |
| **PCCG scraper** | ✅ Complete | Multi-variant via Algolia API, verified live |
| **Seed script** | ✅ Complete | Populates `products` table from `watchlist.csv` |
| **Ingestion** | ✅ Complete | Reads JSON → writes DB, idempotent, supports dry-run |
| **Query tool** | ✅ Complete | Latest prices, trends, biggest movers |
| **Daily runner** | ✅ Complete | One command to scrape both retailers + ingest |
| **Spec sync** | ✅ Complete | `sync_specs.py` — weekly best-effort spec fetch + match (GPU/Intel/AMD); separate from the price pipeline |
| **Spec panel** | ✅ Complete | Product-page spec panel below the price chart; hidden when a product has no specs |
| **Regression tests** | ✅ Complete | 461 tests across 20 modules via pytest |
| **Health checks** | ✅ Complete | JSON validation, DB freshness, match anomalies, price anomalies, spec coverage + staleness |
| **Concurrent DB access** | ✅ Complete | WAL mode active — safe reads while cron writes |
| **Frontend** | ✅ Complete | SvelteKit dashboard (`web/`) — dashboard, products (card grid with per-card trend sparklines, expandable per-variant listings, compare selection, inline 7-day trend sparklines), compare (`/compare?ids=` side-by-side specs + prices), movers (dense table + trend sparklines), price-history charts (low/high band + togglable listing lines + brand-grouped listings panel), command palette (Ctrl+K quick search → product/compare, with snapshot-count badges), sortable column headers on the dashboard + movers tables, display-cased variant names; reads the DB directly via better-sqlite3 |
| **Frontend tests** | ✅ Complete | 204 vitest + 48 Playwright e2e (with a `goto()` hydration helper) |
| **Deployment** | ✅ Complete | Single all-in-one Docker image: pipeline + dashboard in one container (docker-compose optional)

## Quick start

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Full daily run — scrape both retailers + ingest into DB + health checks
python run_daily.py

# Scrape only (save JSON, no DB write)
python run_daily.py --scrape-only

# Dry run (preview without writing)
python run_daily.py --dry-run

# Skip health checks
python run_daily.py --no-health

# Skip the Discord digest (it fires automatically on healthy runs)
python run_daily.py --no-notify

# Run health checks standalone
python health_checks.py
python health_checks.py --json-only
python health_checks.py --db-only

# Preview or send the daily Discord digest standalone
python notify_discord.py --dry-run
python notify_discord.py --test

# Query latest prices
python query.py

# Search for a specific product
python query.py --model "RTX 5090"

# Show price trends
python query.py --trends --category gpu

# Sync spec data (weekly, best-effort — separate from the daily price pipeline)
python sync_specs.py
python sync_specs.py --category gpu
python sync_specs.py --dry-run
python sync_specs.py --report-only

# Run regression tests
python -m pytest unit_testing/ -v
```

## Docker (single all-in-one container)

One image runs the whole system — the dashboard **and** the daily
scrape → ingest → health-check → backup pipeline. No docker-compose required.

```bash
# Build (context = repo root)
docker build -t trackaroo .

# Run: dashboard on :3000, pipeline every 24h, data persisted in a volume
docker run -d --name trackaroo \
  -p 3000:3000 \
  -v trackaroo-data:/data \
  trackaroo

# Follow logs
docker logs -f trackaroo

# One-shot pipeline (run manually, e.g. from a host crontab)
docker run --rm -v trackaroo-data:/data -e RUN_ONCE=1 trackaroo
```

On boot the container seeds the DB from the watchlist, serves the dashboard on
:3000, and runs the pipeline immediately, then every `RUN_INTERVAL_HOURS`
(default 24h). It also runs the weekly spec sync (`sync_specs.py`) once a week
at `SPEC_SYNC_DOW` @ `SPEC_SYNC_HOUR` (default Sunday 03:00). Knobs:
`RUN_INTERVAL_HOURS`, `BACKUP_KEEP` (default 14), `SPEC_SYNC_DOW` (0=Sun),
`SPEC_SYNC_HOUR`, `-p 8080:3000` to change the host port. A docker-compose
two-service split is also kept for those who prefer it — see
[DEPLOYMENT.md](DEPLOYMENT.md).

## Frontend (`web/`)

SvelteKit dashboard that reads `db/trackaroo.db` directly (read-only, WAL-safe). Routes: `/` dashboard (sortable table — click a column header for ▲/▼ price/change/freshness sorting), `/products` (card grid grouped by product — each card shows a cheapest-in-stock trend sparkline, expandable variant listings with inline 7-day trend sparklines, compare checkboxes), `/compare?ids=` (side-by-side specs + per-retailer best prices for 2–4 same-category products), `/movers` (24h/7d/30d, sortable by window/abs-pct/price *and* clickable ▲/▼ column headers, per-row trend sparklines), `/product/[id]` (meta + uPlot history chart with low/high band and 90-day chips + brand-grouped listings panel + spec panel). A global **command palette** (Ctrl/Cmd+K) searches the tracked products from any page and jumps straight to a product (or offers a quick "Compare A vs B" when exactly two match); each result shows its snapshot-count badge. Retailer variant names are display-cased (`titleCase()` — e.g. `rtx`→`RTX`, `5600x`→`5600X`) at render time; the stored data stays raw.

```bash
cd web
npm install

# Dev server (open http://localhost:5173)
npm run dev

# Lint/type check
npm run check

# Production build (adapter-node)
npm run build

# Run frontend unit tests (204 vitest)
npm test

# Run browser e2e regression tests (48 Playwright, against a seeded dev server)
npm run test:e2e
```

Point it at a different DB file with `TRACKAROO_DB=/path/to/trackaroo.db`. The default path resolves to `<repo>/db/trackaroo.db` relative to the server module.

## Data model

```
products ────── retailer_listings ────── price_snapshots
(canonical)    (per retailer)           (daily snapshot, append-only)
     │
     └──────── specs (per product, from external datasets via sync_specs.py)
```

- **products** — canonical identity (category, brand, model, generation tier)
- **retailer_listings** — a specific retailer's page for a product variant (e.g., GIGABYTE, ASUS, Zotac 5090 each get their own listing with `variant_name`)
- **price_snapshots** — one row per listing per day. Never updated or deleted.
- **specs** — one row per canonical product, sourced from the external spec datasets above (fetched weekly by `sync_specs.py`). Fetched only on the product detail page — never joined into list/index queries.

The DB runs in `WAL` mode (set by the ingestion writers), so the frontend can read it while the daily cron job writes — no lock errors. Rows are never deleted. Products that roll out of scope are marked `tracked=0`. See [SPEC.md §7a](SPEC.md#7a-data-retention-policy) for the full retention policy.

## Product scope

Track the **current generation plus two prior generations** per product line. Nothing older.

| Product line | Current | −1 | −2 |
|---|---|---|---|
| AMD CPU | Ryzen 9000 (Zen 5) | Ryzen 7000 (Zen 4) | Ryzen 5000 (Zen 3) |
| Intel CPU | Core Ultra 200 (Arrow Lake) | Core 14th Gen | Core 13th Gen |
| NVIDIA GPU | RTX 50 (Blackwell) | RTX 40 (Ada) | RTX 30 (Ampere) |
| AMD GPU | RX 9000 (RDNA 4) | RX 7000 (RDNA 3) | RX 6000 (RDNA 2) |

Full rules in [SCOPE_RULES.md](SCOPE_RULES.md).

## Repo layout

```
Trackaroo/
├── README.md           # this file
├── STATUS.md           # current progress — read this first
├── SPEC.md             # full specification and architecture
├── SCOPE_RULES.md      # product watchlist rules
├── DECISIONS.md        # rationale for key choices
├── FRONTEND_IMPROVEMENTS.md  # frontend/UX improvement implementation brief
│
├── run_daily.py        # one-command daily scraper + ingest runner (health checks + Discord digest)
├── notify_discord.py   # daily Discord digest of biggest CPU/GPU moves (top 3 up/down per category)
├── health_checks.py    # validate JSON output + DB state after each run
├── seed.py             # populate products table from watchlist.csv
├── ingest.py           # read JSON snapshots → write to DB
├── query.py            # query tool (latest prices, trends, movers)
├── backfill_msrp.py    # backfill launch_msrp_usd from db/launch_msrp.json (one-off, re-runnable)
├── backup_db.py        # standalone DB backup with retention pruning
├── sync_specs.py       # weekly spec sync (fetch + match + upsert; never calls run_daily.py)
├── spec_matching.py    # name normalization + product→spec-dataset matching
├── migrate.py          # schema migration tool (historical upgrades only)
├── requirements.txt    # pinned dependencies
│
├── Dockerfile          # all-in-one image: Python pipeline + dashboard (see DEPLOYMENT.md)
├── docker-compose.yml  # optional two-service split of that image
├── deploy/
│   ├── entrypoint.sh          # pipeline-only scheduler loop (used by compose `cron`)
│   ├── entrypoint-single.sh   # all-in-one: seed → dashboard → pipeline scheduler
│   └── bootstrap-data.sh      # hydrates a fresh DB from the baked-in data/*.json history
│
├── scraper/
│   ├── scorptec.py     # Scorptec scraper (server-rendered HTML)
│   └── pccg.py         # PCCG scraper (Algolia API)
│
├── db/
│   ├── schema.sql      # SQLite schema with triggers
│   ├── watchlist.csv   # 100-product watchlist (source of truth)
│   ├── watchlist.py    # shared watchlist loader (parse_spec, load_watchlist)
│   └── trackaroo.db    # SQLite database (generated)
│
├── data/               # scraped JSON snapshots (never deleted)
│   ├── cpu_scorptec_10_August_2026.json
│   ├── gpu_scorptec_10_August_2026.json
│   ├── cpu_pccg_10_August_2026.json
│   └── gpu_pccg_10_August_2026.json
│
├── unit_testing/       # Python regression tests (461 via pytest)
│   ├── conftest.py             # shared pytest fixtures (in-memory DB)
│   ├── test_seed.py            # seed + schema tests
│   ├── test_matching.py        # product matching tests
│   ├── test_schema.py          # SQLite schema tests
│   ├── test_ingest.py          # ingestion + pipeline tests
│   ├── test_scraper.py         # scraper data quality tests
│   ├── test_pccg_reliability.py  # PCCG 429/rate-limit reliability tests
│   ├── test_run_daily.py       # daily runner + health check integration tests
│   ├── test_health_checks.py   # health check validation tests
│   ├── test_query.py           # query tool tests
│   ├── test_concurrency.py     # WAL + concurrent read/write tests
│   ├── test_e2e.py             # scrape → ingest → query → health-check pipeline
│   ├── test_performance.py     # query performance + index-usage tests
│   ├── test_cli.py             # CLI entry-point smoke tests
│   ├── test_backup.py          # backup_db.py retention tests
│   ├── test_config.py          # config.py env-override tests
│   ├── test_specs_schema.py    # specs table DDL + migration tests
│   ├── test_specs_matching.py  # spec name normalization + matching tests
│   ├── test_sync_specs.py      # sync_specs.py fetch/parse/upsert tests
│   └── test_notify_discord.py  # Discord digest: pairing, movers, embeds, POST, routing, gating
│
└── web/                # Phase 3 frontend (SvelteKit, adapter-node)
    ├── src/lib/components/     # Badge, StatTile, PriceChange, Filters, Header, LatestListingTable, PriceChart (uPlot band chart), SpecPanel, CheapestCarousel, ProductCard, BrandGroupedListings, CommandPalette (Ctrl+K), Sparkline, …
    ├── src/lib/branding.ts     # client-safe AIB brand derivation (grouped listings)
    ├── src/lib/listingsPanel.ts # pure grouped-listings logic (search, filters, sort)
    ├── src/lib/tableSort.ts     # pure tri-state column-sort logic (dashboard + movers)
    ├── src/lib/server/         # db.ts (better-sqlite3), repos.ts
    ├── src/routes/             # /, /products, /compare, /movers, /product/[id]
    ├── test/                   # 204 vitest regression tests (9 suites)
    ├── e2e/                    # 48 Playwright regression tests (app.spec.ts, seed.mjs)
    ├── vite.config.js          # sveltekit + tailwind + vitest (client runtime alias for component tests)
    └── package.json
```

## Documentation reading order

1. **[STATUS.md](STATUS.md)** — where are we right now
2. **[SPEC.md](SPEC.md)** — full specification, architecture, data model
3. **[SCOPE_RULES.md](SCOPE_RULES.md)** — which products are tracked and why
4. **[DECISIONS.md](DECISIONS.md)** — rationale behind key choices
5. **[DEPLOYMENT.md](DEPLOYMENT.md)** — Docker (single image), compose, host cron
6. **[IMPROVEMENT_16_Aug_V1.md](IMPROVEMENT_16_Aug_V1.md)** — real spec data plan + PCCG reliability fixes (both implemented; kept as the spec-data rationale)

## Ground rules

- **Never delete price or product data.** Mark it as untracked instead.
- **Never track older than current-minus-2 generations** per product line.
- **Update STATUS.md** before ending any work session.
