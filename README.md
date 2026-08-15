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
| **Regression tests** | ✅ Complete | 251 tests across 15 modules via pytest |
| **Health checks** | ✅ Complete | JSON validation, DB freshness, match anomalies, price anomalies |
| **Concurrent DB access** | ✅ Complete | WAL mode active — safe reads while cron writes |
| **Frontend** | ✅ Complete | SvelteKit dashboard (`web/`) — dashboard, products, movers, price-history charts; reads the DB directly via better-sqlite3 |
| **Frontend tests** | ✅ Complete | 90 vitest + 19 Playwright e2e (with a `goto()` hydration helper) |
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

# Run health checks standalone
python health_checks.py
python health_checks.py --json-only
python health_checks.py --db-only

# Query latest prices
python query.py

# Search for a specific product
python query.py --model "RTX 5090"

# Show price trends
python query.py --trends --category gpu

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
(default 24h). Knobs: `RUN_INTERVAL_HOURS`, `BACKUP_KEEP` (default 14),
`-p 8080:3000` to change the host port. A docker-compose two-service split is
also kept for those who prefer it — see [DEPLOYMENT.md](DEPLOYMENT.md).

## Frontend (`web/`)

SvelteKit dashboard that reads `db/trackaroo.db` directly (read-only, WAL-safe). Routes: `/` dashboard, `/products` (filterable table), `/movers` (24h/7d/30d, sortable), `/product/[id]` (meta + uPlot history chart).

```bash
cd web
npm install

# Dev server (open http://localhost:5173)
npm run dev

# Lint/type check
npm run check

# Production build (adapter-node)
npm run build

# Run frontend unit tests (90 vitest)
npm test

# Run browser e2e regression tests (19 Playwright, against a seeded dev server)
npm run test:e2e
```

Point it at a different DB file with `TRACKAROO_DB=/path/to/trackaroo.db`. The default path resolves to `<repo>/db/trackaroo.db` relative to the server module.

## Data model

```
products ────── retailer_listings ────── price_snapshots
(canonical)    (per retailer)           (daily snapshot, append-only)
```

- **products** — canonical identity (category, brand, model, generation tier)
- **retailer_listings** — a specific retailer's page for a product variant (e.g., GIGABYTE, ASUS, Zotac 5090 each get their own listing with `variant_name`)
- **price_snapshots** — one row per listing per day. Never updated or deleted.

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
│
├── run_daily.py        # one-command daily scraper + ingest runner (with health checks)
├── health_checks.py    # validate JSON output + DB state after each run
├── seed.py             # populate products table from watchlist.csv
├── ingest.py           # read JSON snapshots → write to DB
├── query.py            # query tool (latest prices, trends, movers)
├── backup_db.py        # standalone DB backup with retention pruning
├── fetch_test.py       # Scorptec scraper
├── migrate.py          # schema migration script
├── requirements.txt    # pinned dependencies
│
├── Dockerfile          # all-in-one image: Python pipeline + dashboard (see DEPLOYMENT.md)
├── docker-compose.yml  # optional two-service split of that image
├── deploy/
│   ├── entrypoint.sh          # pipeline-only scheduler loop (used by compose `cron`)
│   └── entrypoint-single.sh   # all-in-one: seed → dashboard → pipeline scheduler
│
├── scraper/
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
├── unit_testing/       # Python regression tests (251 via pytest)
│   ├── conftest.py             # shared pytest fixtures (in-memory DB)
│   ├── test_seed.py            # seed + schema tests
│   ├── test_matching.py        # product matching tests
│   ├── test_schema.py          # SQLite schema tests
│   ├── test_ingest.py          # ingestion + pipeline tests
│   ├── test_scraper.py         # scraper data quality tests
│   ├── test_run_daily.py       # daily runner + health check integration tests
│   ├── test_health_checks.py   # health check validation tests
│   ├── test_query.py           # query tool tests
│   ├── test_concurrency.py     # WAL + concurrent read/write tests
│   ├── test_e2e.py             # scrape → ingest → query → health-check pipeline
│   ├── test_performance.py     # query performance + index-usage tests
│   ├── test_cli.py             # CLI entry-point smoke tests
│   ├── test_resync.py          # resync_stock_status.py tests
│   ├── test_backup.py          # backup_db.py retention tests
│   └── test_config.py          # config.py env-override tests
│
└── web/                # Phase 3 frontend (SvelteKit, adapter-node)
    ├── src/lib/components/     # Badge, StatTile, PriceChange, Filters, Header, LatestListingTable, PriceChart (uPlot), …
    ├── src/lib/server/         # db.ts (better-sqlite3), repos.ts
    ├── src/routes/             # /, /products, /movers, /product/[id]
    ├── test/                   # 90 vitest regression tests (6 suites)
    ├── e2e/                    # 19 Playwright regression tests (app.spec.ts, seed.mjs)
    ├── vite.config.js          # sveltekit + tailwind + vitest (client runtime alias for component tests)
    └── package.json
```

## Documentation reading order

1. **[STATUS.md](STATUS.md)** — where are we right now
2. **[SPEC.md](SPEC.md)** — full specification, architecture, data model
3. **[SCOPE_RULES.md](SCOPE_RULES.md)** — which products are tracked and why
4. **[DECISIONS.md](DECISIONS.md)** — rationale behind key choices
5. **[DEPLOYMENT.md](DEPLOYMENT.md)** — Docker (single image), compose, host cron

## Ground rules

- **Never delete price or product data.** Mark it as untracked instead.
- **Never track older than current-minus-2 generations** per product line.
- **Update STATUS.md** before ending any work session.
