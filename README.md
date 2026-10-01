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
| **Regression tests** | ✅ Complete | 566 tests across 22 modules via pytest |
| **Health checks** | ✅ Complete | JSON validation, DB freshness, match anomalies, price anomalies, spec coverage + staleness |
| **Concurrent DB access** | ✅ Complete | WAL mode active — safe reads while cron writes |
| **Frontend** | ✅ Complete | SvelteKit dashboard (`web/`) — dashboard, products (card grid with per-card trend sparklines, expandable per-variant listings, compare selection, inline 7-day trend sparklines, "Deal" badges), compare (`/compare?ids=` side-by-side specs + prices), movers (dense table + trend sparklines), price-history charts (low/high band + togglable listing lines + brand-grouped listings panel), product-page "since tracked" chips (all-time low/high + 30-day average), price-drop & restock alerts panel on the product page, command palette (Ctrl+K quick search → product/compare, with snapshot-count badges), sortable column headers on the dashboard + movers tables, display-cased variant names; reads the DB directly via better-sqlite3 |
| **Price alerts** | ✅ Complete | `check_alerts.py` — price-drop (≤ target, re-fires on further drops) + restock (24h cooldown) alerts, delivered best-effort via Discord/SMTP/webhook after each healthy run |
| **Delisted detection** | ✅ Complete | `check_delisted.py` — re-checks stale Scorptec listings that vanished from the grid; a positive 404/410 or "No Longer Available" page marks them `delisted` (shown with a Delisted badge, excluded from price ranges); unverifiable pages are left untouched |
| **Staleness monitor** | ✅ Complete | `check_staleness.py` — the only check that runs *outside* the pipeline, so it can detect the run that never happened; ERROR (exit 1 + Discord alert) when no retailer has data inside the threshold, WARNING when a single retailer lags |
| **Frontend tests** | ✅ Complete | 234 vitest + 52 Playwright e2e (with a `goto()` hydration helper) |
| **Deployment** | ✅ Complete | Single all-in-one Docker image: pipeline + dashboard in one container, run with `docker compose` (`deploy/redeploy.sh`)

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

# Preview (or run) price-drop & restock alerts standalone
python check_alerts.py --dry-run
python check_alerts.py

# Preview (or run) the delisted-listing check standalone
python check_delisted.py --dry-run
python check_delisted.py

# Staleness monitor — alerts when the pipeline has not run at all.
# Exit 1 = stale, so a scheduler can act on the exit code alone.
python check_staleness.py --dry-run
python check_staleness.py

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
scrape → ingest → mirror → health-check → backup pipeline. Deploy it with
`docker compose` via `deploy/redeploy.sh` (see [DEPLOYMENT.md](DEPLOYMENT.md));
the plain `docker run` forms below still work for one-off runs.

### Build

```bash
docker build -t trackaroo .        # context = repo root, not web/
```

### Run — with the data mapped to the host

The two `-v` mounts are the important part. `/app/db` holds the SQLite database
and its backups; `/app/data` holds the JSON snapshots. **Without them, both
live inside the container's writable layer and are destroyed the moment you
`docker rm` it** — that is exactly how an earlier container silently threw away
everything it had scraped.

Mapping them onto the repo's own `db/` and `data/` directories means the
container and anything you run natively (`python run_daily.py`, `npm run dev`)
read and write the same files. One source of truth.

**PowerShell (Windows):**

```powershell
docker run -d --name trackaroo `
  -p 3000:3000 `
  --restart unless-stopped `
  --env-file .env `
  -v "${PWD}\db:/app/db" `
  -v "${PWD}\data:/app/data" `
  trackaroo
```

**bash (Linux/macOS/Git Bash):**

```bash
docker run -d --name trackaroo \
  -p 3000:3000 \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/db:/app/db" \
  -v "$(pwd)/data:/app/data" \
  trackaroo
```

Dashboard: <http://localhost:3000> · Logs: `docker logs -f trackaroo`

`--env-file .env` supplies the Discord webhook and any `TRACKAROO_*` overrides
(see `.env.example`). Drop it if you have no `.env` yet — the app runs fine
without one, it just won't send notifications.

### What the mounts contain

| Host path | Container path | Contents |
|---|---|---|
| `./db` | `/app/db` | `trackaroo.db` (SQLite, WAL), `backups/`, `schema.sql`, `watchlist.csv` |
| `./data` | `/app/data` | `{cpu,gpu}_{scorptec,pccg}_DD_Month_YYYY.json` daily snapshots |

Both are gitignored. `data/*.json` is the backup the DB is rebuilt from, so map
it too — not just the DB. If you only map `/app/db`, the pipeline still works
but the JSON backup is lost with the container.

#### Prefer a named volume?

If you don't want the data in the repo directory, use a volume instead. It
survives `docker rm` (unlike no mount at all), but the files are then only
reachable through Docker:

```bash
docker volume create trackaroo-db
docker volume create trackaroo-data
docker run -d --name trackaroo -p 3000:3000 --restart unless-stopped \
  -v trackaroo-db:/app/db -v trackaroo-data:/app/data trackaroo
```

### On boot

1. Seeds the DB from `db/watchlist.csv` if it doesn't exist.
2. Hydrates a fresh DB from the snapshot history baked into the image
   (skipped once the DB has data).
3. Starts the dashboard on :3000.
4. **Runs the pipeline immediately if today has no data yet** — so a container
   that was down over the scheduled hour catches up instead of losing the day.
5. Thereafter runs daily at `RUN_AT_HOUR` (default 04:00 local), plus a weekly
   spec sync at `SPEC_SYNC_DOW` @ `SPEC_SYNC_HOUR` (default Sunday 03:00).

### Settings

| Setting | Default | Override |
|---|---|---|
| Daily run hour (local) | `04` | `-e RUN_AT_HOUR=6` |
| Timezone | `Australia/Melbourne` | `-e TZ=Europe/Berlin` |
| Backups retained | 14 | `-e TRACKAROO_BACKUP_KEEP=30` |
| Dashboard host port | 3000 | `-p 8080:3000` — the right-hand number must stay **3000** unless you also set `PORT`; `-p 2222:2222` without `PORT=2222` starts the container but nothing listens on it |
| Spec-sync day / hour | Sun / 03 | `-e SPEC_SYNC_DOW=1 -e SPEC_SYNC_HOUR=12` |

The timezone matters for correctness, not display: the scrapers stamp snapshots
with the local date, so a UTC container running before 10:00 AEST would file
today's prices under yesterday.

### Other run modes

```bash
# One-shot pipeline, then exit (e.g. from a host scheduler)
docker run --rm -e RUN_ONCE=1 \
  -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" trackaroo

# Pipeline only, no dashboard
docker run -d --name trackaroo-pipeline \
  -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" \
  --entrypoint /usr/bin/tini trackaroo -- /usr/local/bin/trackaroo-entrypoint-pipeline

# Dashboard only, no pipeline (read-only; DB written elsewhere)
docker run -d --name trackaroo-web -p 3000:3000 \
  -v "$(pwd)/db:/app/db" \
  --entrypoint /usr/bin/tini trackaroo -- node web/server.js
```

### Verifying a deployment

```bash
docker exec trackaroo date                    # should print your local time, not UTC
docker inspect trackaroo --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}
{{end}}'                                      # both mounts present?
docker exec trackaroo python -c "import sqlite3;print(sqlite3.connect('/app/db/trackaroo.db').execute('select max(snapshot_date),count(*) from price_snapshots').fetchone())"
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/
```

### Upgrading

```bash
deploy/redeploy.sh    # pull, back up, build with the git SHA, start, verify
```

(With plain `docker run`: `docker stop trackaroo && docker rm trackaroo`,
`docker build -t trackaroo .`, then re-run the command above.)

Your data is untouched by this because it lives in the mounts, not the
container. That is the whole point of mapping them.

See [DEPLOYMENT.md](DEPLOYMENT.md) for host scheduling, reverse-proxy notes,
and monitoring.

## Frontend (`web/`)

SvelteKit dashboard that reads `db/trackaroo.db` directly (read-only, WAL-safe). Routes: `/` dashboard (sortable table — click a column header for ▲/▼ price/change/freshness sorting), `/products` (card grid grouped by product — each card shows a cheapest-in-stock trend sparkline, expandable variant listings with inline 7-day trend sparklines, compare checkboxes), `/compare?ids=` (side-by-side specs + per-retailer best prices for 2–4 same-category products), `/movers` (24h/7d/30d, sortable by window/abs-pct/price *and* clickable ▲/▼ column headers, per-row trend sparklines), `/product/[id]` (meta + uPlot history chart with low/high band and all-time/30d-avg chips + brand-grouped listings panel + spec panel + a **price alerts** panel to arm "tell me under $X" / restock alerts). A global **command palette** (Ctrl/Cmd+K) searches the tracked products from any page and jumps straight to a product (or offers a quick "Compare A vs B" when exactly two match); each result shows its snapshot-count badge. Retailer variant names are display-cased (`titleCase()` — e.g. `rtx`→`RTX`, `5600x`→`5600X`) at render time; the stored data stays raw.

```bash
cd web
npm install

# Dev server (open http://localhost:5173)
npm run dev

# Lint/type check
npm run check

# Production build (adapter-node)
npm run build

# Run frontend unit tests (234 vitest)
npm test

# Run browser e2e regression tests (52 Playwright, against a seeded dev server)
npm run test:e2e
```

Point it at a different DB file with `TRACKAROO_DB=/path/to/trackaroo.db`. The default path resolves to `<repo>/db/trackaroo.db` relative to the server module.

## Data model

```
products ────── retailer_listings ────── price_snapshots
(canonical)    (per retailer)           (daily snapshot, append-only)
     │
     ├── specs (per product, from external datasets via sync_specs.py)
     │
     └── price_alerts (per product × channel, user-set target price / restock notify)
```

- **products** — canonical identity (category, brand, model, generation tier)
- **retailer_listings** — a specific retailer's page for a product variant (e.g., GIGABYTE, ASUS, Zotac 5090 each get their own listing with `variant_name`)
- **price_snapshots** — one row per listing per day. Never updated or deleted.
- **specs** — one row per canonical product, sourced from the external spec datasets above (fetched weekly by `sync_specs.py`). Fetched only on the product detail page — never joined into list/index queries.
- **price_alerts** — one row per product × channel (`UNIQUE(product_id, channel)`): target price, optional restock notify, and cooldown columns (`last_notified_at` / `last_notified_price`) that advance only after a successful delivery.

The DB runs in `WAL` mode (set by the ingestion writers), so the frontend can read it while the daily cron job writes — no lock errors. Rows are never deleted. Products that roll out of scope are marked `tracked=0`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) Part 1 §7a for the full retention policy.

## Product scope

Track the **current generation plus two prior generations** per product line. Nothing older.

| Product line | Current | −1 | −2 |
|---|---|---|---|
| AMD CPU | Ryzen 9000 (Zen 5) | Ryzen 7000 (Zen 4) | Ryzen 5000 (Zen 3) |
| Intel CPU | Core Ultra 200 (Arrow Lake) | Core 14th Gen | Core 13th Gen |
| NVIDIA GPU | RTX 50 (Blackwell) | RTX 40 (Ada) | RTX 30 (Ampere) |
| AMD GPU | RX 9000 (RDNA 4) | RX 7000 (RDNA 3) | RX 6000 (RDNA 2) |

Full rules in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) Part 2.

## Repo layout

```
Trackaroo/
├── README.md           # this file
├── STATUS.md           # current progress — read this first
├── CLAUDE.md           # agent/contributor conventions (AGENTS.md points here)
├── DEPLOYMENT.md       # running it — Docker and native
├── docs/
│   ├── ARCHITECTURE.md # spec (Pt 1) + scope rules (Pt 2) + decision log (Pt 3)
│   ├── archive/        # implemented or declined plans, kept for rationale
│   └── proposals/      # not-yet-built work (RAM tracking)
│
├── run_daily.py        # one-command daily scraper + ingest runner (health checks + Discord digest + price alerts + delisted check)
├── notify_discord.py   # daily Discord digest of biggest CPU/GPU moves (top 3 up/down per category)
├── check_alerts.py     # price-drop & restock alerts (Discord/SMTP/webhook delivery, best-effort)
├── check_delisted.py   # re-check stale Scorptec listings; mark delisted on positive 404/410 or "No Longer Available"
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
├── deploy/
│   ├── entrypoint.sh          # pipeline-only scheduler loop (pipeline-only entrypoint override)
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
│   │                   #   adding one? docs/ARCHITECTURE.md Part 2 §7
│   ├── watchlist.py    # shared watchlist loader (parse_spec, load_watchlist)
│   └── trackaroo.db    # SQLite database (generated)
│
├── data/               # scraped JSON snapshots (never deleted)
│   ├── cpu_scorptec_10_August_2026.json
│   ├── gpu_scorptec_10_August_2026.json
│   ├── cpu_pccg_10_August_2026.json
│   └── gpu_pccg_10_August_2026.json
│
├── unit_testing/       # Python regression tests (545 via pytest)
│   ├── conftest.py             # shared pytest fixtures (in-memory DB)
│   ├── test_seed.py            # seed + schema tests
│   ├── test_matching.py        # product matching tests
│   ├── test_schema.py          # SQLite schema tests
│   ├── test_migrate.py         # migrate.py: legacy-DB migrations (variant_name, specs, price_alerts) + main()
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
│   ├── test_notify_discord.py  # Discord digest: pairing, movers, embeds, POST, routing, gating
│   ├── test_check_alerts.py    # price alerts: evaluation matrix, message, delivery stubs, CLI
│   └── test_check_delisted.py  # delisted check: page classification, fetch retries, selection, marking
│
└── web/                # Phase 3 frontend (SvelteKit, adapter-node)
    ├── src/lib/components/     # Badge, StatTile, PriceChange, Filters, Header, LatestListingTable, PriceChart (uPlot band chart), SpecPanel, CheapestCarousel, ProductCard, BrandGroupedListings, CommandPalette (Ctrl+K), Sparkline, PriceAlerts, …
    ├── src/lib/branding.ts     # client-safe AIB brand derivation (grouped listings)
    ├── src/lib/listingsPanel.ts # pure grouped-listings logic (search, filters, sort)
    ├── src/lib/tableSort.ts     # pure tri-state column-sort logic (dashboard + movers)
    ├── src/lib/server/         # db.ts (better-sqlite3), repos.ts
    ├── src/routes/             # /, /products, /compare, /movers, /product/[id]
    ├── test/                   # 239 vitest regression tests (11 suites)
    ├── e2e/                    # 52 Playwright regression tests (app.spec.ts, seed.mjs)
    ├── vite.config.js          # sveltekit + tailwind + vitest (client runtime alias for component tests)
    └── package.json
```

## Documentation reading order

1. **[STATUS.md](STATUS.md)** — where are we right now
2. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — specification and data model (Part 1), which products are tracked and why (Part 2), rationale behind key choices (Part 3)
3. **[DEPLOYMENT.md](DEPLOYMENT.md)** — running it: Docker, host scheduling, native
4. **[CLAUDE.md](CLAUDE.md)** — conventions and guardrails for anyone (human or agent) changing the code
5. **[docs/archive/](docs/archive/)** — completed plans, kept for the reasoning behind what shipped

## Ground rules

- **Never delete price or product data.** Mark it as untracked instead.
- **Never track older than current-minus-2 generations** per product line.
- **Update STATUS.md** before ending any work session.
