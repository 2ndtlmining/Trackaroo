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
| **PCCG scraper** | ✅ Code ready | Multi-variant code complete (live data blocked by Algolia rate limit) |
| **Seed script** | ✅ Complete | Populates `products` table from `watchlist.csv` |
| **Ingestion** | ✅ Complete | Reads JSON → writes DB, idempotent, supports dry-run |
| **Query tool** | ✅ Complete | Latest prices, trends, biggest movers |
| **Daily runner** | ✅ Complete | One command to scrape both retailers + ingest |
| **Regression tests** | ✅ Complete | 173 tests across 7 modules (~0.82s) |
| **Health checks** | ✅ Complete | JSON validation, DB freshness, match anomalies, price anomalies |
| **Frontend** | ⏳ Planned | SvelteKit dashboard (Phase 3) |
| **Deployment** | ⏳ Planned | Docker + cron on Proxmox (Phase 4) |

## Quick start

```bash
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

## Data model

```
products ────── retailer_listings ────── price_snapshots
(canonical)    (per retailer)           (daily snapshot, append-only)
```

- **products** — canonical identity (category, brand, model, generation tier)
- **retailer_listings** — a specific retailer's page for a product variant (e.g., GIGABYTE, ASUS, Zotac 5090 each get their own listing with `variant_name`)
- **price_snapshots** — one row per listing per day. Never updated or deleted.

Rows are never deleted. Products that roll out of scope are marked `tracked=0`. See [SPEC.md §7a](SPEC.md#7a-data-retention-policy) for the full retention policy.

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
├── fetch_test.py       # Scorptec scraper
│
├── scraper/
│   └── pccg.py         # PCCG scraper (Algolia API)
│
├── db/
│   ├── schema.sql      # SQLite schema with triggers
│   ├── watchlist.csv   # 100-product watchlist (source of truth)
│   └── trackaroo.db    # SQLite database (generated)
│
├── data/               # scraped JSON snapshots (never deleted)
│   ├── cpu_scorptec_10_August_2026.json
│   ├── gpu_scorptec_10_August_2026.json
│   ├── cpu_pccg_10_August_2026.json
│   └── gpu_pccg_10_August_2026.json
│
└── unit_testing/
    ├── conftest.py             # shared pytest fixtures (in-memory DB)
    ├── test_seed.py            # seed + schema tests
    ├── test_matching.py        # product matching tests
    ├── test_schema.py          # SQLite schema tests
    ├── test_ingest.py          # ingestion + pipeline tests
    ├── test_scraper.py         # scraper data quality tests
    ├── test_run_daily.py       # daily runner + health check integration tests
    └── test_health_checks.py   # health check validation tests
```

## Documentation reading order

1. **[STATUS.md](STATUS.md)** — where are we right now
2. **[SPEC.md](SPEC.md)** — full specification, architecture, data model
3. **[SCOPE_RULES.md](SCOPE_RULES.md)** — which products are tracked and why
4. **[DECISIONS.md](DECISIONS.md)** — rationale behind key choices

## Ground rules

- **Never delete price or product data.** Mark it as untracked instead.
- **Never track older than current-minus-2 generations** per product line.
- **Update STATUS.md** before ending any work session.
