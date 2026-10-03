# Trackaroo — Architecture & Decisions

Everything about *what* Trackaroo is, *what* it tracks, and *why* it was built
this way. Three previously separate root-level documents were merged here
unchanged:

| Part | Was | Answers |
|---|---|---|
| [Part 1 — Specification](#part-1--specification) | `SPEC.md` | What the system does and how the pieces fit |
| [Part 2 — Product scope rules](#part-2--product-scope-rules) | `SCOPE_RULES.md` | Which CPUs and GPUs are tracked, and why |
| [Part 3 — Decision log](#part-3--decision-log) | `DECISIONS.md` | Why each significant choice was made |

Operational docs live elsewhere: [`README.md`](../README.md) for setup and
day-to-day commands, [`DEPLOYMENT.md`](../DEPLOYMENT.md) for running it,
[`STATUS.md`](../STATUS.md) for current state and changelog.

When adding a decision, append to Part 3 — don't rewrite history.

---

## Part 1 — Specification
### 1. Purpose

Track daily pricing and stock status for **CPUs and GPUs** across two Australian retailers (Scorptec, PC Case Gear — Mwave was removed 10-Aug over bot protection), store the history, and surface trends — biggest price movers, potential good deals, and long-term price charts per product.

This is a personal-use, self-hosted project. It is not a public-facing price comparison service.

### 2. Retailers in scope

| Retailer | Base URL | Platform notes |
|---|---|---|
| Scorptec | https://www.scorptec.com.au/ | Custom platform, server-rendered HTML, clean category pages (`/product/cpu/...`, `/product/graphics-cards/...`) |
| PC Case Gear | https://www.pccasegear.com/ | Algolia InstantSearch (JS-rendered) — query the embedded Algolia search API directly, no browser needed |
| ~~Mwave~~ | ~~https://www.mwave.com.au/~~ | ~~Removed — CloudFront bot protection blocks all automated requests~~ |

**Confirmed during planning:** none of the retailers expose a public product/pricing API. All data will be sourced via scraping their public category/listing pages.

**Verified during Phase 1 (2026-08-09):**
- **Scorptec** — server-rendered HTML, plain HTTP fetch + BeautifulSoup works perfectly
- **PC Case Gear** — Algolia InstantSearch; the Algolia app ID + read-only search key embedded in page source let us query the search API directly (see Part 3 of this document) — no Playwright/JS rendering needed
- **Mwave** — removed from scope due to CloudFront bot protection blocking all automated requests

### 3. Product scope

- **In scope:** desktop CPUs (Intel + AMD) and desktop/consumer GPUs (NVIDIA + AMD, and Intel Arc). Workstation/server CPUs and professional GPUs (Quadro/RTX Ada/etc.) are **excluded** entirely to keep matching simple.
- **Decided:** curated watchlist, not "track everything." The watchlist is governed by a **2-generation rule** — track the current generation plus two prior (current, −1, −2) per product line; exclude anything older. Full generation tables and maintenance instructions live in the companion file Part 2 of this document — that file is the source of truth for exactly which products are in/out, and should be consulted (and updated) whenever a new generation launches.

### 4. Goals

1. Take a daily snapshot of price + stock status for every tracked product at every retailer.
2. Store full price history (not just latest value) so trends can be computed over arbitrary windows.
3. Match the "same" physical product across retailers so it can be compared directly (e.g. one RTX 5070 Ti card, priced at all three).
4. Surface, via a web dashboard:
   - Price history chart per product (and per retailer listing)
   - Biggest price increases / decreases over a selected window (7d / 30d / all-time)
   - Cheapest current price per product across retailers
   - Basic "good deal" signal — e.g. price is at or near its historical low
5. Run unattended, on existing home infrastructure, with visibility when something breaks (a scrape fails, a retailer's page structure changes, zero products found, etc.).
6. **Never delete price/product data.** See §7a, Data Retention Policy.

### 5. Non-goals (for now)

- Not tracking any category beyond CPU/GPU.
- Not building user accounts, alerts/notifications, or public access — single-user, local dashboard.
- Not attempting real-time pricing — daily cadence is the target.
- Not scraping product review content, images, or full specs beyond what's needed to identify and match products.

### 6. Architecture overview

Three components, consistent with prior projects (FluxTracker/FluxFlow pattern):

```
┌─────────────────┐      ┌──────────────────┐      ┌───────────────────┐
│  Python scraper   │ ---> │   SQLite database  │ <--- │  SvelteKit frontend │
│  (ingestion job)  │      │  (price history)   │      │  (charts & stats)   │
└─────────────────┘      └──────────────────┘      └───────────────────┘
      runs daily               single file              reads DB directly
      via scheduler/cron                                  or via small API layer
```

- **Scraper/ingestion (Python):** fetches category pages per retailer, parses product name/price/stock/URL, normalizes, writes a snapshot row per product per retailer per day.
- **Database (SQLite):** single-file, zero-ops, easy to back up on TrueNAS. Chosen over Convex/Supabase for this project because the core analytics need (price-change queries across hundreds of SKUs over time windows) is a natural fit for SQL, and this keeps the stack simple.
- **Frontend (SvelteKit):** matches the FluxTracker stack already running on your infrastructure. Charts via uPlot (chosen for dense time-series performance — see Part 3 of this document).
- **Deployment:** Docker container(s) on the existing Proxmox cluster, following the same pattern as FluxTracker.

### 7. Data model (draft)

Three core tables, designed to separate canonical product identity from retailer-specific listings from time-series price data:

**`products`** — canonical, cross-retailer identity
- `id`, `category` (cpu/gpu), `brand`, `model` (e.g. "RTX 5070 Ti"), `variant` (e.g. AIB partner/edition if tracked), `vram_gb` / `cores` (category-specific spec fields), `created_at`
- `generation_tier` (enum: `current` / `current-1` / `current-2`) — which Part 2 of this document tier this product sits in. Kept even after a product rolls out of scope, as a historical record of where it sat. Makes scope management queryable without parsing model names.
- `tracked` (bool) — is this product currently in the active watchlist per Part 2 of this document? Set to `false` when a generation rolls out of scope. **Never delete the row** — see §7a.
- `last_snapshot_at` — timestamp of the most recent successful price snapshot for this product (across any retailer). Lets any consumer (frontend, another AI, a future you) instantly tell how fresh a product's data is without scanning `price_snapshots`.

**`retailer_listings`** — a specific retailer's page for a product
- `id`, `product_id` (FK), `retailer` (scorptec/pccg/mwave), `retailer_sku_or_url`, `listing_url`, `first_seen_at`, `last_seen_at`
- `status` (enum: `active` / `delisted` / `stale`) — replaces a plain boolean so we can distinguish "retailer removed the listing" (`delisted`) from "we stopped scraping it, e.g. rolled out of scope" (`stale`) from "currently tracked" (`active`). **Rows are never deleted** — see §7a.
- `last_snapshot_at` — timestamp of the most recent successful snapshot for this specific listing.

**`price_snapshots`** — one row per listing per scrape
- `id`, `retailer_listing_id` (FK), `snapshot_date`, `price_aud`, `stock_status` (enum: `in_stock` / `out_of_stock` / `preorder` / `unknown`), `scraped_at`
  - An enum rather than a plain boolean, to handle real-world states like PCCG's "Stock at Supplier" (`preorder`) without losing information. Defaults to `unknown`.
- Append-only. **No updates, no deletes**, ever — see §7a.

**`specs`** — one row per canonical product, from external spec datasets (added 16-Aug-2026, see `archive/IMPROVEMENT_16_Aug_V1.md`)
- `product_id` (FK to `products`), `source` (`rightnow-gpu-db` / `intel-processors-csv` / `amd-com`), `source_record_key` (the identifying name in the source dataset, kept for traceability), `category`, `architecture`, `generation`, `launch_date`, `launch_msrp_usd`
- GPU-specific (nullable on CPU rows): `vram_gb`, `memory_bus_width_bit`, `memory_type`, `tdp_watts`
- CPU-specific (nullable on GPU rows): `thread_count`, `base_clock_mhz`, `boost_clock_mhz`, `socket`, `cache_l3_mb`
- `core_count` is deliberately shared — shading units for GPU rows, physical cores for CPU rows (one column, documented, rather than two over-loaded ones)
- `raw_json` — the full original source record verbatim, so new fields can be read later without a schema migration
- Populated by the weekly `sync_specs.py` (a separate, best-effort job — never part of the daily price pipeline). Fetched only on the product detail page; **never joined into list/index queries** (the /products Released column reads `launch_date` through its own memoised per-category query — decision log 2026-09-30). Rows are never deleted; a conflicting re-match is flagged in the sync report, never silently overwritten.

This structure is what makes "biggest movers" and "cheapest across retailers" clean SQL queries (window functions over `price_snapshots` joined through `retailer_listings` to `products`) rather than something hand-rolled in application code.

#### 7a. Data retention policy

**Rule: never delete data. Freeze it instead.**

When a product/listing stops being actively tracked — because a generation rolled out of scope (Part 2 of this document), a retailer delisted it, or a scraper issue means we can't match it anymore — the correct action is:

1. Stop writing new `price_snapshots` rows for it.
2. Flip `products.tracked` to `false` (generation rolled out of scope) and/or `retailer_listings.status` to `delisted` or `stale` as appropriate.
3. Leave every existing row exactly as it is. The last snapshot simply becomes the permanent last data point for that product/listing.

**Consuming "freshness" correctly:** any view or query that shows current prices should check `last_snapshot_at` and clearly indicate when a product's data is not from today (e.g. "last seen 14 days ago") rather than silently presenting stale data as current. This applies to the frontend, any future analytics, and any AI picking up this project — do not infer "current price" without checking how recent the snapshot actually is.

This rule is absolute and applies regardless of the reason data stopped updating (delisted, rolled out of scope, scraper broke, retailer changed page structure). Deletion is never the right response to any of those situations.

**Open question for Phase 1:** how strict to make product matching — automatic fuzzy matching (brand+model+VRAM) vs. a manually curated mapping table. **Recommendation: start manual/semi-manual**, since real-world product names vary a lot between retailers (e.g. "ASUS TUF Gaming RTX 5070 Ti OC 16GB" vs "ASUS TUF-RTX5070TI-O16G-GAMING"), and premature automation risks silently mismatching products.

### 8. Scraping approach

- Plain HTTP fetch (requests) + HTML parse (BeautifulSoup) per retailer's category pages, paginating through results. PCCG is fetched via its Algolia search API directly.
- Playwright held in reserve only if a retailer turns out to need JS rendering for price/stock (not needed so far — Scorptec is server-rendered, PCCG uses Algolia).
- One scraper module per retailer (`scraper/scorptec.py` for Scorptec, `scraper/pccg.py` for PCCG), each returning a common normalized record shape, so the ingestion pipeline and DB layer are retailer-agnostic.
- Daily cadence, run via cron or APScheduler inside the container. Reasonable delay between requests within a retailer; no need to hit any site more than once a day.
- Identify the scraper honestly via a descriptive User-Agent string.
- **Resilience requirement:** each scrape run should validate its own output (e.g. "did we get a plausible number of products for this category?") and log/alert if a retailer returns zero results or wildly different data than expected — a sign the page structure changed and the parser needs updating, not that all stock vanished. Implemented in `health_checks.py` (match-count thresholds per retailer/category, freshness, anomaly detection).

### 9. Frontend features (initial scope)

1. Product list/table view — current price per retailer, cheapest highlighted, in-stock status.
2. Price history chart per product — line chart per retailer over time.
3. "Biggest movers" view — largest % price change over a selectable window.
4. Simple deal signal — flag products currently at or near their tracked historical low.
5. Filter by category (CPU/GPU) and brand.

Later/nice-to-have (not in initial build): watchlist-based alerts, cross-category comparisons, export to CSV.

### 10. Risks & considerations

- **Site structure changes** will break scrapers silently unless monitored — build in basic sanity checks from day one (see §8).
- **Product matching accuracy** is the main ongoing maintenance burden — expect to manually reconcile mappings periodically, especially for new product launches.
- **Politeness/ToS** — daily-cadence, low-volume scraping with a clear user-agent is a reasonable, low-impact approach for a personal project; avoid aggressive polling.
- **Retailer promotional pricing/bundles** may create noisy "price changes" that aren't genuine trend signals (e.g. bundle deals, multi-buy discounts) — worth filtering or flagging distinctly if they show up in early data.

### 11. Build phases

**Phase 1 — Foundation** *(complete)*
- Finalize product watchlist scope (which CPUs/GPUs to track)
- Design and create SQLite schema
- Build Scorptec scraper end-to-end (cleanest HTML of the three) → validate daily snapshot loop works

**Phase 2 — Full ingestion** *(complete)*
- Add PC Case Gear scraper to the same pipeline (Mwave dropped — CloudFront bot protection)
- Build the manual/semi-manual cross-retailer product matching layer (search-term based)
- Add scrape-health checks/alerting (health_checks.py; variant-count anomaly detection)

**Phase 3 — Frontend** *(complete — SvelteKit dashboard shipped 15-Aug-2026: dashboard, products card grid, movers, uPlot price-history charts, spec panel; see STATUS.md)*
- Product table + current pricing view
- Price history charts per product
- Biggest movers + deal-signal views

**Phase 4 — Hardening** *(partially complete)*
- Deploy to Proxmox/Docker on the daily schedule — **complete** (single all-in-one Docker image + optional compose split, verified live 15-Aug; see DEPLOYMENT.md)
- Backups of the SQLite file — **complete** (`backup_db.py` with retention pruning, wired into the daily pipeline and container entrypoints)
- Revisit matching automation and watchlist scope based on real data collected
- Remaining: reverse proxy/TLS for internet-facing use, monitoring/alerting on pipeline failure (tracked in STATUS.md)

### 12. Stack summary

| Layer | Choice |
|---|---|
| Scraper | Python (requests + BeautifulSoup; Playwright in reserve) |
| Scheduling | Cron or APScheduler in-container |
| Database | SQLite |
| Frontend | SvelteKit + uPlot |
| Deployment | Docker on existing Proxmox cluster |

---

## Part 2 — Product scope rules
This file defines which CPUs and GPUs are in scope for tracking. It is the source of truth for the watchlist — consult it whenever adding, questioning, or excluding a product.

### Core rule: 2-generation limit

**Track the current generation plus the two generations before it. Do not track anything older than that (current minus 3 or beyond).**

In other words: `current`, `current - 1`, `current - 2` are tracked. `current - 3` and older are excluded.

This rule applies independently per product line (AMD CPU, Intel CPU, NVIDIA GPU, AMD GPU), since each moves on its own release cadence. It is **not** a fixed calendar cutoff — it moves forward as new generations launch, and this file should be revisited/updated when that happens (see §6).

### 1. AMD Ryzen desktop CPUs

| Tier | Series | Architecture | Socket |
|---|---|---|---|
| Current | Ryzen 9000 | Zen 5 | AM5 |
| −1 | Ryzen 7000 (incl. 8000G APUs — see note) | Zen 4 | AM5 |
| −2 | Ryzen 5000 | Zen 3 | AM4 |
| **Excluded (−3)** | Ryzen 3000 and older (e.g. 3900X) | Zen 2 and older | AM4 |

**Note on naming:** the Ryzen 8000G series is a desktop APU line built on Zen 4 silicon, not a new architecture — despite the "8000" number, it sits in the same generation tier as the 7000 series (−1), not its own tier.

### 2. Intel desktop CPUs

| Tier | Series | Codename | Socket |
|---|---|---|---|
| Current | Core Ultra 200 series | Arrow Lake | LGA1851 |
| −1 | Core 14th Gen | Raptor Lake Refresh | LGA1700 |
| −2 | Core 13th Gen | Raptor Lake | LGA1700 |
| **Excluded (−3)** | Core 12th Gen and older | Alder Lake and older | LGA1700 and older |

**Note:** Intel's Core Ultra 300 series ("Panther Lake") launched in Jan 2026 but is a mobile/laptop-first platform — no desktop socket parts as of this writing. Desktop stays on Core Ultra 200 as current until a desktop Panther Lake or Nova Lake part ships; revisit this file when that happens.

### 3. NVIDIA GeForce GPUs

| Tier | Series | Architecture |
|---|---|---|
| Current | RTX 50 series | Blackwell |
| −1 | RTX 40 series | Ada Lovelace |
| −2 | RTX 30 series | Ampere |
| **Excluded (−3)** | RTX 20 series and older | Turing and older |

### 4. AMD Radeon GPUs

| Tier | Series | Architecture |
|---|---|---|
| Current | RX 9000 series | RDNA 4 |
| −1 | RX 7000 series | RDNA 3 |
| −2 | RX 6000 series | RDNA 2 |
| **Excluded (−3)** | RX 5000 series and older | RDNA 1 and older |

### 5. Intel Arc GPUs

Intel's discrete GPU line is younger and has had far fewer generations than AMD/NVIDIA, so the strict 2-gen rule isn't meaningful yet. **Track all current Arc desktop GPUs (Alchemist A-series and Battlemage B-series) without an exclusion tier.** Revisit this exception once Arc has 3+ generations on the market.

### 6. Maintenance of this file

- When a new generation launches for any product line (new Ryzen/Core/GeForce/Radeon series), update the relevant table: promote the new series to "Current," shift the others down one tier, and drop the oldest tier from tracking.
- Dropping a generation from scope means: stop taking new snapshots for those products going forward. Existing historical price data for dropped products should be retained, not deleted, in case it's useful later — just excluded from the active watchlist / "biggest movers" views.
- Workstation/server CPUs (Threadripper, Xeon, EPYC) and professional GPUs (RTX PRO/Ada, Radeon Pro) remain **out of scope entirely**, per §3 of the main spec — this file only governs the consumer desktop CPU/GPU lines listed above.

### 7. Adding or removing a product — the actual steps

Most additions start on **/discover** (README, 'Discovering and adding new parts'), which gives you the row.

Part 2 above says *what* belongs in the watchlist. This section is *how*, because
three things about the process are not obvious from the CSV.

**1. Edit `db/watchlist.csv`.** One row per product:

```
category,brand,model,spec,gen_tier,search_aliases
gpu,NVIDIA,GeForce RTX 5070,12GB,current,"rtx 5070|5070 nvidia|nvidia rtx 5070"
```

`spec` is cores for a CPU (`16c`) or VRAM for a GPU (`16GB`). Case and spacing
are tolerated — `16c`, `16C` and ` 16 c ` all work — but the unit is required,
because a bare `12` is ambiguous between cores and gigabytes and is rejected
rather than guessed.

> **Note:** this item predates the chip-key matcher (#1). Scrapers now resolve
> through an exact chip-key `Matcher`, so alias ordering no longer decides
> matching; see the note in `unit_testing/test_watchlist_validation.py`. The
> text below is kept for history.

**2. Mind the alias ordering — this is the one that bites.** `scrape_scorptec`
and `scrape_umart` test watchlist entries by **primary search term length,
descending**, and stop at the first match, so the most specific entry wins. That
only holds while a base model's *first* alias is shorter than its variants':

| Model | First alias | Length |
|---|---|---|
| `GeForce RTX 5070 Ti` | `rtx 5070 ti` | 11 |
| `GeForce RTX 5070` | `rtx 5070` | 8 |

Give the base model a first alias of `nvidia geforce rtx 5070` (23) and it
outranks the Ti, silently claiming every Ti listing — the prices look plausible
and nothing errors. `unit_testing/test_watchlist_validation.py` pins this: any
base model whose primary alias is not shorter than a more specific sibling's
fails the suite.

**3. Run the seeder.** `python seed.py` inserts new rows; existing products are
never overwritten, so re-running is safe.

```bash
python seed.py            # Inserted: 1, Skipped (already exists): 99
```

A malformed row is **skipped, not fatal** — it is reported with its line number
and field (`watchlist row 21 [spec]: cannot read VRAM from '16gib'`) and the
rest of the file loads. That matters because `deploy/entrypoint-single.sh` runs
`seed.py` under `set -e`: before 31-Aug-2026 a single typo stopped the container
from booting. The cost is now one missing product, which the log states plainly.

**4. Specs arrive on the next weekly sync, not immediately.** `sync_specs.py`
runs in-container on `SPEC_SYNC_DOW` at `SPEC_SYNC_HOUR` (default Sunday 03:00),
so a product added on Monday shows no specs on its product page for six days.
That is expected, not a fault. To pull them in immediately:

```bash
python sync_specs.py --category cpu --dry-run   # check it matches first
python sync_specs.py --category cpu
```

Matching is deliberately conservative: anything not confidently matched is
reported and left alone rather than guessed. Read the summary — `unmatched`
means *a gap worth investigating*, while products the upstream source genuinely
does not carry are listed separately under "no upstream specs (known)" and
tracked in `sync_specs.SPECS_UNAVAILABLE_UPSTREAM` with a reason and a date.

**5. Verify.** `check_spec_coverage` warns below `TRACKAROO_SPEC_COVERAGE_MIN_PCT`
(default 80%), and the daily run reports per-retailer match counts. A new product
that no retailer stocks is normal — it will show on `/products` with a
"never listed" marker and count against available coverage on the dashboard,
which is the honest reading rather than a bug.

**Removing** a product: delete its row *and* add the model to
`migrate.RETIRED_PRODUCTS`. Deleting the row alone is not enough — `seed.py`
only ever INSERTs, so an existing database keeps `tracked=1` forever. Never
delete price history; retired products get `tracked=0`.
---

## Part 3 — Decision log
Rationale behind key choices, so anyone (human or AI) picking this project up later understands *why*, not just *what*. Add a new entry whenever a significant decision is made or revisited — don't rewrite history, append.

---

#### Data source: scraping, not an API
No public product/pricing API exists for Scorptec, PC Case Gear, or Mwave — confirmed by checking each site directly (custom platforms, not Shopify/Magento/BigCommerce, which would have exposed something usable). All three have clean, server-rendered category listing pages, so scraping is low-complexity and shouldn't require JS rendering for core fields (name/price/stock). This should be re-verified per retailer in Phase 1 in case a site behaves differently than its category pages suggested.

#### Database: SQLite (not Convex, not self-hosted Supabase)
Considered three options:
- **Convex** — appealing because schema/backend logic live in code (TypeScript) and self-hosting is real. Rejected because: (a) Convex's backend functions are TS-native — the Python scraper would need to call in via its Python client while business logic still lives in TS, splitting the data layer across two languages; (b) Convex isn't built for OLAP-style aggregation — "biggest % change over N days across 500+ SKUs" is a SQL window-function problem, and Convex has no equivalent, so it'd be hand-rolled; (c) self-hosted Convex has no official support plan and is less battle-tested than SQLite/Postgres for this kind of workload.
- **Self-hosted Supabase (Postgres)** — a real contender since it's already running in the home infrastructure and gives full SQL. Not chosen for this project specifically because SQLite gives the same SQL analytics capability with zero additional ops (no new service to run), and this project doesn't need Supabase's other features (auth, realtime, storage).
- **SQLite (chosen)** — zero-ops, single file, backs up trivially, and the analytics needs of this project (time-series price aggregation) are squarely SQL's strength. If the project outgrows SQLite later, migrating to Postgres/Supabase is a well-trodden path.

#### Scraper language: Python (not Node/TypeScript)
FluxTracker (a prior project) used Node/SvelteKit, so reusing that stack was considered for consistency. Python was chosen instead for the scraper specifically because its scraping ecosystem (httpx, BeautifulSoup, Playwright as fallback) is stronger and faster to iterate with for this kind of per-retailer HTML parsing work. The frontend remains SvelteKit — only the ingestion layer is Python.

#### Frontend: SvelteKit
Matches the existing FluxTracker deployment pattern (Docker on Proxmox, adapter-node), which is proven infrastructure. SvelteKit's reactivity model also suits a filterable stats dashboard well, and its compiled output keeps chart-heavy pages fast even with hundreds of SKUs and dense time-series data.

#### Product matching strategy: manual/semi-manual first, not automatic fuzzy matching
Real-world product names vary significantly between retailers for the same physical card/chip (e.g. "ASUS TUF Gaming RTX 5070 Ti OC 16GB" vs. "ASUS TUF-RTX5070TI-O16G-GAMING"). Automatic fuzzy matching risks silently mismatching products, which would corrupt price-comparison data in a hard-to-detect way. Starting with a manual or semi-manual mapping table trades some upfront effort for correctness; automation can be revisited once there's real data to see how messy the matching problem actually is in practice.

#### Product scope: curated watchlist via 2-generation rule (not "track everything")
Tracking every CPU/GPU a retailer lists would blow out both scrape time and matching effort, and much of that long tail (old, discontinued, rarely-priced-competitively products) wouldn't be useful for "current market" price tracking anyway. The 2-generation rule (current + 2 prior generations per product line) keeps the watchlist meaningful and bounded. Full rules and per-line generation tables live in Part 2 of this document.

#### Data retention: never delete, freeze instead
When a product/listing stops being tracked (rolls out of scope, gets delisted by a retailer, or a scraper breaks), the rule is to stop writing new snapshots and mark it (`tracked=false` / `status=delisted|stale`) rather than delete any historical rows. This preserves price history for later analysis and avoids silently losing data due to a scope change or a temporary scraper issue. See spec §7a for the full policy and schema fields that implement it.

#### Mwave removed from scope (2026-08-10)
Mwave uses CloudFront bot protection that blocks all automated requests — even with stealth headers and Playwright. No viable scraping path was found. Removed from Part 1 of this document retailer table and from active work. PCCG and Scorptec remain as the two data sources.

#### PCCG uses Algolia API, not Playwright (2026-08-10)
PCCG's product search is powered by Algolia InstantSearch. The Algolia credentials (app ID + read-only API key) are embedded in PCCG's page source. This means we can query the Algolia search API directly — no Playwright, no headless browser, no JS rendering needed. Much faster and more reliable. **The key is rate-limited to 100 queries per IP per hour** (`"maxQueriesPerIPPerHour": 100`, read straight off `GET /1/keys/<key>` on 27-Aug-2026). Earlier notes here guessed "~429 after ~30 rapid queries" and prescribed batched requests with delays; that was wrong on both counts. Batching is irrelevant — Algolia bills each entry in a multi-query `requests` array as its own query — and in-run delay is irrelevant because the budget is a rolling ~60-minute window, not an hour-boundary bucket — measured 27-Aug-2026, a heavy spend at 18:06 GMT was still 429ing at 19:01 GMT, after a fresh clock hour had begun. Quota frees up roughly an hour after whatever consumed it. Querying once per watchlist product spent the whole budget on page 0 alone (100 tracked products, 100 queries), which is why runs 429'd most days. The scraper now fetches each category whole with a single empty query (`hitsPerPage=1000`; 229 GPUs and 60 CPUs each fit one page) and matches the watchlist locally — **2 queries per run**.

#### Scorptec scraper outputs separate CPU/GPU JSON files (2026-08-10)
User requested separate files per category: `cpu_scorptec_10_August_2026.json`, `gpu_scorptec_10_August_2026.json`. Same convention applies to PCCG. This makes it easier to reason about per-category match rates and debug issues.

#### Historical JSON data is never deleted (2026-08-10)
Scraped JSON files in `data/` are retained indefinitely — they serve as the raw audit trail and can be re-ingested if the DB needs rebuilding. New daily snapshots get new filenames with the date. Old files are not removed.

#### Shared watchlist loader module `db/watchlist.py` (2026-08-12)
The watchlist CSV parsing + spec parsing logic (`parse_spec`, `load_watchlist`) was copy-pasted three times — in `fetch_test.py`, `scraper/pccg.py`, and `seed.py`, with slight drift between them. Extracted into a single `db/watchlist.py` module with three entry points: `load_watchlist` (scraper-shaped rows with `search_terms`), `load_watchlist_products` (seed-shaped rows for the `products` table), and `parse_spec`. The importing modules re-export or delegate to it, so behavior is identical but no longer duplicated. Kept next to `db/watchlist.csv` since it is the loader for that data file.

#### Match-count anomaly checks count listings, not products (2026-08-12)
`health_checks.py`'s `check_match_count_anomalies` originally counted `COUNT(DISTINCT product_id)` per retailer per date. Once multi-variant tracking landed, that under-reported massively (e.g. Scorptec 54 products but 192 variant listings), producing false "Match count dropped" warnings against thresholds calibrated for variants. Fixed to count `COUNT(DISTINCT retailer_listings.id)` so the metric and the thresholds mean the same thing. Lesson: when the semantics of a metric change (products → variants), everything calibrated on it must change together.

#### Algolia credentials via environment variables (2026-08-12)
The PCCG scraper embeds the Algolia app ID and read-only search key found in PCCG's page source. Hardcoded in the repo, they risk being committed/forgotten alongside unrelated changes. Now read from `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` env vars with the known-good values as defaults (they are read-only public search keys, so the defaults keep zero-config local use working).

#### WAL journal mode enabled for frontend-safe concurrent access (2026-08-13)
The DB previously ran with the default rollback-journal (`journal_mode=delete`). Now that a frontend will read the DB while `run_daily.py` writes on a cron schedule, WAL (`PRAGMA journal_mode=WAL`) is the mechanism that makes concurrent reads safe. Set by the writer/init paths (`ingest.init_db`, `seed.init_db`, `migrate`) — the mode persists in the DB file header, so every later connection runs in WAL automatically. The real DB was flipped on 13-Aug-2026.

**Lesson learned (proved by the concurrency test):** readers must NEVER toggle journal mode at connection time. `query.get_connection` originally ran `PRAGMA journal_mode=WAL` on open; while a writer held its lock, the mode *change* needed an exclusive lock and raised `database is locked`. Reassigning journal mode is a write-side operation — readers just open and inherit. This is why `query.py` now sets only `busy_timeout` (covering the brief WAL checkpoint write-lock window) and lets the file header handle the rest. The future better-sqlite3 frontend should follow the same rule: read, don't reconfigure.

#### Frontend DB access: direct SQLite via better-sqlite3 (2026-08-13)
Decision for Phase 3: SvelteKit server routes read `db/trackaroo.db` directly with better-sqlite3, rather than standing up a thin read API. Rationale: single-user, self-hosted, one database file, and the dashboard's queries are already proven fast (see perf numbers below). An API layer would add a service to deploy for no benefit at this scale. WAL makes the direct read safe against the cron writer. (Node's built-in `node:sqlite` is a viable fallback if a native build of better-sqlite3 becomes a nuisance.)

#### Frontend location: `web/` subdirectory in this repo (2026-08-13)
SvelteKit scaffolds under `web/`, sharing the same clone, `db/` file, and Docker build as the Python pipeline. Chosen over a separate repo so the daily runner and the dashboard deploy together and always agree on the DB file they read.

#### No new indexes needed — measured, not assumed (2026-08-13)
The proposed `price_snapshots (product_id, snapshot_date)` index doesn't map to the schema — `price_snapshots` references `retailer_listing_id`, not `product_id`. `EXPLAIN QUERY PLAN` confirms the per-product price-history path already uses `idx_retailer_listings_product` (covering) + `idx_snapshots_listing_date` with no full scan. Measured on a synthetic 333-listing × 30-day DB (~10k snapshots): `show_latest_prices` = 60 ms, `show_biggest_movers` = 7 ms. Adding a covering `(retailer_listing_id, snapshot_date, price_aud, stock_status)` index would shave the `price_aud` table-lookup off the history query, but at this scale it's ~nothing; revisit if snapshots grow past ~50k rows or the dashboard's history query shows up hot in profiling.

#### Price-anomaly sensitivity is history-dependent (2026-08-13)
With N stable price points plus one jump, the jump's max detectable deviation is about √N standard deviations. A 3× spike over only 5–6 days computes to ~2.2σ and does NOT trip the 3σ threshold; it needs ~10+ history points to be flagged. On 13-Aug real data, 226 of 333 listings sit at exactly 3 points, so the anomaly check currently misses most single-day jumps — by design (the threshold avoids false positives on thin data). Worth revisiting `PRICE_ANOMALY_STD_DEVS` or adding history-depth awareness once listings accumulate more days. Test `test_appearing_disappearing_variants_no_false_positive` locks in the intended behavior: a genuine jump on a mature listing flags; a vanished or freshly-appeared variant does not.

#### PCCG stock status fix: _map_stock_label() retains sold-out/preorder variants (2026-08-13)
The PCCG scraper originally marked every product `in_stock` regardless of actual stock state. The Algolia index carries an `indicator.label` field with values like "In stock", "Sold Out", "ETA: DD/MM/YY", and "Stock at Supplier". The fix introduced `_map_stock_label()` in `scraper/pccg.py` which maps these labels to the schema enum (`in_stock`, `out_of_stock`, `preorder`, `unknown`).

**Why retain sold-out products?** Their price still matters for history — a sold-out product's last price is the reference point for when it restocks. Dropping them would create gaps in the price timeline.

**Impact:** On 13-Aug PCCG GPU data, 32 of 102 variants were `out_of_stock` and 2 were `preorder`. The DB had all 123 PCCG rows marked `in_stock` from the buggy ingest. A new `resync_stock_status.py` script was created to compare buggy vs. fixed JSON and update the affected 37 rows (3 CPU + 34 GPU). The script supports `--dry-run` and is idempotent.

**Lesson:** When a scraper bug corrupts data that's already been ingested, a targeted resync script is better than re-ingesting everything. It's scoped to the affected date and retailer, supports dry-run, and leaves unrelated data untouched.

#### Backup files are excluded from ingestion (2026-08-13)
The `data/` directory contains `.backup_buggy.json` files preserving the original buggy scrape output for audit purposes. The ingest pipeline and E2E tests now filter out any file containing `.backup` in the filename, preventing these archive files from being re-ingested or causing parse errors. This keeps the raw audit trail intact while preventing accidental double-processing.

#### Resync script for stock_status corrections (2026-08-13)
`resync_stock_status.py` is a standalone tool that:
- Compares buggy vs. fixed JSON pairs for a given date
- Identifies rows where `stock_status` was incorrect in the DB
- Supports `--dry-run` (preview only) and apply mode
- Is idempotent — safe to re-run
- Only affects PCCG rows for the specified date
- Does NOT touch Scorptec data or other dates

9 new regression tests cover: dry-run behavior, apply mode, idempotency, backup file filtering, and helper function correctness.

#### Charts: uPlot, single accent hue + line styles (2026-08-15)
Phase 3 dashboard charts settled on **uPlot** (~8kb, zero default theme) rather than a heavier charting lib (ECharts/Recharts) or D3 by hand. All price lines share the one accent token `--accent`; variant/retailer series are distinguished by line style (solid / dashed / dotted) instead of extra hues, keeping the plot within the design system's "one restrained accent" rule. Crosshair + tooltip are hand-rolled: cursor data comes through uPlot's `setCursor` hook reading `u.cursor.idx`, tooltip HTML is token-styled (`text-text`, `border-border`, `bg-surface`). On a theme toggle, the chart rebuilds (read `getComputedStyle` once at mount); ResizeObserver keeps it responsive.

#### Theme strategy: CSS variables + `data-theme`, dark default (2026-08-15)
Design tokens live as CSS custom properties in `src/app.css` with a dark-default `:root` and a light override under `[data-theme='light']`; Tailwind v4 maps them via `@theme inline` (`bg-surface`, `text-muted`, etc.). The theme toggle (`src/lib/theme.ts`) persists to `localStorage` (`trackaroo-theme`), and `app.html` has an inline pre-hydration script applying the stored theme to `documentElement.dataset.theme` before paint to avoid FOUC. Default is dark.

#### Frontend DB path resolution (2026-08-15)
The default DB path in `web/src/lib/server/db.ts` is resolved relative to the server module with `fileURLToPath(import.meta.url)` up to the repo root: `../../../../db/trackaroo.db` (from `src/lib/server/`, that lands on `<repo>/db/trackaroo.db`). `TRACKAROO_DB` env overrides it when deploying elsewhere. Read-only open, `busy_timeout=5000`, WAL inherited from file header — mirrors the Python reader rule (never toggle journal mode).

#### SvelteKit pages receive load results as a single `data` prop (2026-08-15)
Under Svelte 5 runes, `+page.svelte` components must destructure the load result through the single `data` prop (`let { data } = $props()`), NOT as individual top-level props. Initially the views destructured `{ summary, listings }` etc. directly, which SSR-rendered with every page 500ing (`Cannot read properties of undefined`). A production smoke test caught it — svelte-check and vitest did not, because component compile succeeds either way. Lesson: always smoke-test SSR-rendered routes against the real DB, not just typecheck/unit tests.

#### Component smoke tests via client `mount()` (2026-08-15)
Vitest runs modules under node conditions, so `import { render } from 'svelte/server'` fails against client-compiled components and `mount()` from the bare `svelte` main resolves to the server build (which throws `lifecycle_function_unavailable`). Fix: in `vite.config.js`, when `process.env.VITEST` is set, alias the bare `svelte` specifier to `node_modules/svelte/src/index-client.js` so arrays of integration-style component tests can `mount()` in jsdom. The alias is scoped to vitest only — the production build keeps its node/server condition resolution.

#### Cheapest-deals carousel: single carousel with GPU/CPU toggle (2026-08-15)
Per user feedback, the "cheapest per model" deal-browsing component is a single horizontally-scrolling carousel (`CheapestCarousel.svelte`) placed at the top of the Dashboard, with an in-component GPU/CPU toggle rather than two separate carousels or a URL-driven filter. This resolves the open question in archive/FRONTEND_IMPROVEMENTS.md item 4: build BOTH GPU and CPU variants, selectable via the toggle, since the query and card markup are identical for either category. Data comes from `getCheapestPerModel(db, category)` in `web/src/lib/server/repos.ts`: it targets the global MAX snapshot date, requires `stock_status='in_stock'` on active listings, and picks the single lowest `price_aud` per product (= per model) via a correlated subquery. Models with no in-stock listing at the latest date are omitted entirely (per item 4's "omit or grey out" allowance) - shown as an empty-state message if the whole category has nothing in stock. No schema change required (no `sort_rank`/`tier_rank` added yet; carousel currently orders by model name COLLATE NOCASE). Toggle state is local component state; the page still loads both categories so the toggle is instant with no refetch.

#### Spec data sources: GitHub raw JSON/CSV + AMD first-party pages, not scraping (2026-08-16)
Hardware specs (VRAM, cores, clocks, TDP, launch dates) come from external datasets fetched weekly, never scraped live per request — the same politeness principle that dropped Mwave. Final sources: **GPU** — `RightNow-AI/RightNow-GPU-Database` (Apache-2.0, not MIT as the plan guessed), plain JSON on GitHub carrying TechPowerUp data via the `dbgpu` project (attribution noted in README). **Intel** — `toUpperCase78/intel-processors` raw CSVs on GitHub (core + Core Ultra files). **AMD** — first-party `amd.com` product pages, fetched politely (browser user-agent, 1s delay between pages); 24 of 28 tracked SKUs resolve, the 4 OEM-only SKUs (5500, 5600, 5700X, 9900) have no public page by design. The plan's Option A (`felixsteinke/cpu-spec-dataset`) was rejected: AGPL-3.0 license and missing current-generation parts. Scraping TechPowerUp directly was explicitly ruled out — it reopens the bot-detection/ToS risk this approach exists to avoid.

#### Spec sync: separate weekly best-effort job, never inside the price pipeline (2026-08-16)
`sync_specs.py` is a wholly separate entry point — never called from or by `run_daily.py`. Specs don't change once a part launches, so the cadence is weekly (best-effort), not daily. The priority rule from the plan is absolute: the price pipeline is highest priority, and a spec-sync failure must never break ingestion, delete price data, or take down `run_daily.py` — the site keeps working with stale or absent spec data. Fetch failures are definitive on 4xx, retried with backoff on 5xx/network errors; the run exits 1 on source failure but writes nothing destructive. A report of matched/unmatched/conflicting records lands in `data/spec_sync_report.json` for review.

#### Spec matching: no guessing, no silent overwrites (2026-08-16)
Matching happens at the canonical `products` level (not per retailer listing), normalizing both sides (strip brand/AIB prefixes, lowercase, collapse whitespace) and exact-matching on the normalized model string. Anything that doesn't match is logged to the unmatched report — never auto-guessed. If a product already has a `specs` row and a new sync produces a *different* record, the conflict is flagged in the report and the existing row is kept — spec data should be as stable and trustworthy as the "never delete price data" rule is for prices. Rows for products whose source record vanishes upstream are kept (last-known value), never deleted.

#### Spec display: product detail page only, below the price chart (2026-08-16)
Specs are static-ish (weekly refresh), so they're fetched with the product page's existing detail load — one extra `SELECT ... FROM specs WHERE product_id = ?` inside `getProductHistory` — and are **never** joined into list/index page queries (site performance on the main price pages must not regress). The `SpecPanel` renders below the price chart/listings, and simply doesn't render at all when a product has no spec row — no placeholder, no "specs coming soon" empty state. Launch MSRP was originally shown in USD as published (no FX rate); that was superseded on 3-Oct-2026, see the MSRP entry at the end of this log.

#### Products page: card grid grouped by product, expandable variant listings (2026-08-16)
Per archive/FRONTEND_IMPROVEMENTS.md item 3, the Products page now renders one card per product instead of one row per listing — deal-browsing is visual, and 8 AIB variants of an RTX 3050 as 8 flat rows is noise. Each `ProductCard` shows the model (linking to `/product/[id]`), brand, category badge, the cheapest in-stock "from $X" price with the retailer that has it, and a listing count; expanding it reveals the per-variant listings as the existing `LatestListingTable` in a new `compact` mode (Model/Category columns hidden — the card header already shows them). Grouping is a pure, tested function `groupListingsByProduct()` in `repos.ts` (called in the products page load, no SQL change): `sort=price-asc/desc` orders cards by cheapest in-stock price with unpriced products always last; the default keeps the SQL's category/model order. The dense table stays on the Dashboard and Movers — those are comparison/analysis views where density is the point. No schema change.

#### Repo cleanup per feature-suggestions §6 (2026-08-17)
Per `TRACKAROO_FEATURE_SUGGESTIONS.md` §6, the pushed repo was checked against reality and tidied:
- **`resync_stock_status.py` removed** — it was a one-off correction for the 13-Aug PCCG stock-status bug. The bug is fixed at the source (`_map_stock_label()`), the data was already corrected, and nothing (production or test) referenced it except its own 9-test module, so it and `unit_testing/test_resync.py` were deleted. Historical entries describing the fix remain in STATUS.md/Part 3 of this document.
- **`fetch_test.py` renamed → `scraper/scorptec.py`** — the name implied a throwaway test harness when it is the production Scorptec scraper; it now lives beside its PCCG counterpart under `scraper/`. References updated in `run_daily.py` (`python -m scraper.scorptec`), `unit_testing/test_scraper.py`, `unit_testing/test_matching.py`, and README.
- **`migrate.py` clarified as historical-only** — `db/schema.sql` already creates tables with `variant_name` + WAL from scratch, so `migrate.py` exists only to upgrade pre-12-Aug databases; a comment now says so.

#### Product detail page redesign: band chart + brand grouping (2026-08-17)
Per feature-suggestions §2, the product page stops plotting every listing as its own line. Default chart = a shaded min–max band over in-stock prices per day plus a "cheapest in stock" marker; individual listing lines are hidden unless explicitly toggled on in the listings panel. The listings panel is grouped by AIB brand with collapsible groups (header shows price range + in-stock count), a free-text search over `variant_name`, an "in stock only" filter, and per-listing "show on chart" toggles. **Brand is derived at render time** (`deriveListingBrand(variant_name, product_brand)` — first token of the variant name normalized, falling back to the product brand) rather than adding a `retailer_listings.brand` column and re-scraping: the variant names already carry the AIB brand as their first token, and a pure, vitest-tested function avoids a migration + scraper changes for a single-user app. No schema change.

#### Compare view: read-only, no value score (2026-08-17)
Per feature-suggestions §3, a `/compare?ids=1,2,3` route shows up to 4 products (same category enforced) side by side — spec fields aligned per row (N/A where missing) plus the current best price per retailer. It is a read-only join of `products` + `specs` + latest `price_snapshots` (`getComparisonData` in `repos.ts`), no new tables. Deliberately no computed "value" score ($/GB VRAM, $/core): a single formula can't fairly rank something as use-case-dependent as GPU/CPU value — raw numbers side by side, user draws the conclusion. Selection happens on the Products page via per-card checkboxes feeding a floating "Compare (N) →" bar.

#### Deal score: declined, removed from the plan (2026-08-17)
The user decided not to build the deal-score feature (archive/FRONTEND_IMPROVEMENTS.md item 1 — `deal_score` / `pct_below_30d_avg` / `is_all_time_low` gated behind ≥7 snapshot days). It is dropped from the plan entirely rather than deferred: no SQL/logic will be pre-built "just in case". Nothing depended on it — the cheapest-deals carousel shipped without it (it uses cheapest-in-stock at the latest snapshot, not history), and the remaining item (sparklines) reads raw price history directly, so the only effect is that the dashboard's "is this a good deal" signal stays out of scope. The "basic good-deal signal" goal in Part 1 of this document §4 remains unimplemented by choice; if it's ever revisited, the gate (≥7 snapshot days) and the "Gathering price history" placeholder from the original brief are still the right shape.

#### 90-day low/high badge (§4.1): in-stock extremes anchored to the latest snapshot day (2026-08-17)
Feature-suggestions §4.1 ("lowest price in 90 days") shipped as `getPriceExtremes(productId, days)` — MIN/MAX over **in-stock** snapshots only (consistent with the band chart and the "cheapest currently in stock" marker), excluding bundle listings, and anchored to `MAX(snapshot_date)` in the DB rather than `date('now')` so results are deterministic in tests and don't drift with wall-clock time. Because the app is only ~9 days old, "90 days" currently means "the full available window". Rendered as a green `90d low` badge on dashboard deal cards when the current price equals the window low, and as `90d low`/`90d high` chips on the product page. §4.2 (carousel `title=` tooltip) and §4.3 (insufficient-history state) were already implemented in earlier passes.

#### /deals: two sections, not one blended score (2026-08-25)
Stage 2 of the price-first IA spec (`docs/superpowers/specs/2026-08-23-price-first-ia-design.md` §4) ships `/deals`. This **revisits the "Deal score: declined" entry above (2026-08-17)** — that decision rejected a *composite* `deal_score` that would have collapsed several signals into one ranking number, and that rejection still stands. What shipped instead is two explicitly separate, individually explainable lists:

- **Below 30-day average** — ranked by depth, `(avg30 − price) / avg30`, deepest first.
- **At or near all-time low** — anchored at `#all-time-low`, where "near" means **within 2%** of the lowest price ever recorded.

They are kept apart because they answer different questions ("cheap versus its own recent history" vs "cheap versus all history") and the second is the stronger claim. Blending them would reproduce exactly the unexplainable single number the 17-Aug entry rejected. A product may legitimately appear in both lists.

Eligibility for **both** sections requires `avg30Points >= MIN_HISTORY_POINTS` (3). The spec states this gate for the average; it is applied to the all-time-low section too, because an "all-time low" drawn from three days of history is no more meaningful than a three-day average.

One new query, `getDealCandidates` in `repos.ts` — one row per tracked product (its cheapest in-stock listing on the latest snapshot date, plus all-time low and 30-day average), deliberately mirroring the proven shape of `getCheapestPerModel` but spanning both categories and reporting an all-time rather than 90-day low. All ranking and section logic is pure and lives in `web/src/lib/deals.ts`. The page reuses the stage-1 `OfferRow` (given two additive optional props for a product-level title and detail link) and `FacetChips`; its chips are **URL-driven server-side**, unlike the product page's client-side chips — same presentational component, two different drivers, per spec §7.

No nav link ships in this stage: spec §10 sequences nav last, so `/deals` is reachable by URL until stage 4.

#### Homepage: health first, then deals, then movers (2026-08-25)
Stage 3 of the price-first IA spec (§5) replaces the homepage's filter-and-sort listing table with a question-answering dashboard: a data-health strip, then one section per category carrying top deals, biggest 7-day drops and biggest 7-day rises. Three decisions worth recording:

**Three freshness states, not the spec's two.** §5 names *fresh* (snapshot today), *cooling down* and *stale* (≥ 2 days). That leaves **exactly one day behind** unnamed — and it is the most common state of all, because the pipeline runs at 04:00, so every retailer is one day behind until the morning run. Calling it stale would cry wolf; calling it fresh would be false. Implemented as `fresh` (0 days) / `recent` (1 day, muted) / `stale` (≥ 2 days, warning), matching the treatment `StaleDataBanner` already shipped. The ≥ 2 day stale boundary is exactly the spec's. Classification is pure, in `web/src/lib/health.ts`, so the boundaries are pinned by tests rather than by how a pill renders.

**"Cooling down" is deliberately deferred, and displays as stale.** Distinguishing an intended PCCG circuit-breaker pause from real staleness requires the web app to read `data/pccg_cooldown.json`, coupling it to the pipeline's file layout. That coupling is not worth it yet. Until it lands a cooling-down retailer reads as stale — honest, since its data *is* older, just less specific — and the pill uses a **warning** tone, never an error tone: the breaker is working as designed and the UI must not imply the pipeline is broken.

**The homepage reuses `deals.ts`, it does not re-rank.** Top deals come from the same `getDealCandidates` → `toDeals` → `belowAverage` path `/deals` uses, filtered by category and capped at three. A second ranking would eventually disagree with the first. Movers stay separate and come from `getMovers` at a **fixed 7-day window** (the `/movers` selector stays on `/movers`): the scrape cadence is daily, so a 24-hour window is a single snapshot pair and one missed run would empty the section outright. A product can legitimately appear as both a deal and a mover — they answer different questions — and the e2e suite asserts exactly that rather than deduplicating.

**What was removed with it.** The four stat tiles, `CheapestCarousel`, and the filtered listing table come off `/`; `getSummary`/`Summary` went with them, having no other caller. The `90d low` badge lived only on the carousel and is now gone from the product entirely — the all-time-low signal it approximated is carried better by `/deals`' at-or-near-all-time-low section and the product-page headline. `Filters.svelte` is now used only by `/products`, so its e2e coverage moved there rather than being dropped.

#### Navigation, and a display layer ready for six retailers (2026-08-25)
Stage 4 — the last stage of the price-first IA spec (§6, §7). Three things worth recording.

**Active-state matching had to become query-string aware.** `Header.svelte` checked `path === link.href` against `pathname` only. Once `GPUs` and `CPUs` are both `/products` distinguished solely by `?category=`, that check can *never* highlight either one — it compares a pathname to a string containing a query. Matching moved into a pure `isActiveLink(href, pathname, search)` in `web/src/lib/nav.ts`: the link's path must equal the pathname, and every parameter the link pins must match, while unrelated parameters (`sort`, `q`, `window`) are ignored — they change what you are looking at, not which place you are in. Being pure, the rule is pinned by unit tests rather than by inspecting rendered classes, and the nav renders `aria-current="page"` so the state is exposed to assistive technology, not just to colour.

**One chip component, three drivers — deliberately not unified further.** `FacetChips` now serves the product page (filters an already-loaded list **client-side**, instant, no navigation), `/deals` (**URL-driven**, server-side) and `/products` (**URL-driven**, server-side). The spec is explicit that these must not be collapsed into one mechanism: the product page's offer list is already in the browser, while `/products` and `/deals` result sets are too large to ship to the client. They share presentation and nothing else. The `/products` chip options come from **counts over the current result set** (every axis except retailer applied), so a chip's count always equals the number of rows clicking it produces, and a retailer with no rows shows no chip at all.

**The six-retailer registry is display-side only.** `Retailer`, `RETAILER_OPTIONS` and `notify_discord.RETAILER_LABELS` now carry `mwave`, `umart`, `centrecom` and `ple` alongside `scorptec` and `pccg`. **No scraper exists for any of the four.** The point is that landing one becomes a pipeline change rather than a UI change: slugs validate through `parseFilters`, labels resolve everywhere, and the Discord digest will not print raw slugs. Because chip options are data-derived, adding a slug renders nothing until data arrives. Writing the four scrapers stays out of scope — each needs its own reconnaissance (API vs HTML, rate limits, SKU extraction) and its own spec, and PCCG has shown how much that varies.

**Also in this stage:** `/compare` joins the nav and, opened with no `ids`, renders an empty state explaining how to select products instead of a 400 — a request naming exactly one product is still a 400, since that comes from a broken link rather than from clicking Compare. The dataset stats (snapshot days, DB size) moved from the header into the homepage health strip, their honest home; the user-facing staleness signal was already `StaleDataBanner`. Below `md` the nav is a horizontally scrollable row rather than a hamburger — five short items fit, and a menu would add a tap to every navigation.

#### Shell scripts pinned to LF on checkout; the container could not start (2026-08-25)
`docker run` failed immediately with `[FATAL tini (7)] exec /usr/local/bin/trackaroo-entrypoint failed: No such file or directory`. The file was present and executable - the path in that message is a red herring. `deploy/entrypoint-single.sh` reached the image with CRLF endings, so the shebang read `#!/bin/sh` + CR and the kernel tried to exec an interpreter literally named `/bin/sh<CR>`. Linux reports that ENOENT against the script rather than the interpreter, which makes it read as a missing `COPY`.

**The CRLF was never committed.** Git stores these scripts as LF and always has - the blob for `entrypoint-single.sh` is byte-identical from the commit that added it through to today. The conversion happens on **checkout**: Git for Windows sets `core.autocrlf=true` at *system* scope, and with no `.gitattributes` every Windows clone materialised `deploy/*.sh` with CRLF. `docker build` then COPYs the working-tree file, carrying the CR into the image. So the image was broken for anyone building on Windows with a default Git install, and fine for anyone building on Linux or macOS - which is why it survived a "verified live" note.

Proven at two levels. Mechanism: the working-tree script mounted into a bare `debian:bookworm-slim` reproduces `exec ...: no such file or directory`, while the byte-identical file with CRs stripped executes normally. Provenance: a fresh `git clone` of the parent commit yields `CR=162` on that script, and a fresh clone with `.gitattributes` present yields `CR=0`.

Three guards, layered because each closes a different route:
- **`.gitattributes`** pins `*.sh` and `Dockerfile` to `eol=lf`, overriding `autocrlf` so the checkout is right in the first place. This is the actual fix.
- **The Dockerfile** strips CRs after `COPY` and runs `sh -n` on each script. A source zip, an exported archive or a stray editor bypasses git entirely; this makes such a checkout fail the *build* rather than the first boot.
- **`unit_testing/test_shell_scripts.py`** fails the regression suite on any tracked `*.sh` whose working-tree copy contains a CR - deliberately checking the working tree, since that is both the layer that breaks and the layer `docker build` reads.

**Two process lessons.** First, the test suites never build the image, so a fully green pytest/vitest/Playwright run said nothing about whether the app could start; `CLAUDE.md` now requires a Docker build-and-boot for any change touching the `Dockerfile`, `deploy/`, or container-executed code. Second, `grep -c $'\r'` under Git Bash reports false positives (it claimed 98 CRs in a file that had none) and sent the first pass of this investigation down a wrong path - count bytes in Python instead.

#### Price-range bar compares like with like; average labels state real evidence (2026-08-25)
Two honesty defects, both reported from use.

**The range bar mixed two different series.** `allTimeLow` was the min of each day's *cheapest* in-stock listing, but `allTimeHigh` was the max of each day's *dearest* listing. The marker -- today's cheapest offer -- was therefore plotted against the worst price any retailer had ever asked, so it could only sit high if today's best deal approached the dearest-ever price. Measured on live data: 70% of bars had the marker pinned in the bottom fifth, and only one product sat above the midpoint. Both ends now come from the same series, the cheapest-per-day price, which answers the question the bar is actually asking -- is today cheap in this product's own history? The same measurement afterwards: 50% in the bottom fifth (genuine -- 77% of products really are at their all-time low), and 9 products above the midpoint instead of 1. Labels changed from "All-time low/high" to "Cheapest/Dearest" with a caption naming the series and the day count, because "all-time high" now means the worst day to have bought rather than the priciest listing on the shelf.

**A flat range was reported as a single reading.** When low equalled high the bar degraded to "Only one price recorded so far" -- false for a product tracked for 17 days at a steady price, which is 24 of 44 products on the current dataset. `Headline.pricePoints` now carries the number of days with a recorded price, and the copy distinguishes "Price has held at $120 for all 17 days tracked" from a genuine single reading.

**"30d avg" overstated the evidence.** The SQL window genuinely is 30 days, but the dataset spans 17, so every delta was labelled with a month of evidence it did not have. `avgWindowLabel()` renders the real contributing day count -- "vs 17-day avg" -- and grows into "vs 30-day avg" by itself once the history is deep enough. Rule-level prose ("below their recent average") is now kept separate from evidence-level numbers, so a heading never claims a window the data cannot back.

#### /products becomes a search-first index (2026-08-25)
The GPU/CPU pages were a filter-and-sort card grid: six selects, a debounced text box, one ~150px card per product. Reported as clucky, and correctly so — the stated job is **"find a model I already have in mind"**, and a browse layout is the wrong tool for a find task. 100 products across three generations today, and every launch adds ~15 more.

Rebuilt as a dense index: one search box, one row per product, filtered **in the browser**. The whole category (~50 rows) ships on load, so narrowing is instant and the 450ms debounce plus a server round trip per keystroke are gone. This is deliberately the opposite of the `/deals` and chip-facet decision (price-first IA §7), where the result set is listings and too large to ship; here it is one row per *product* and shipping it is cheaper than querying it.

**Matching is shared with the Ctrl+K palette** (`productSearch.ts`). Two search surfaces over one catalogue must not rank differently. The palette previously did an unranked substring filter, so it gained ranking too: exact model, then prefix, then word boundary, then substring, then brand/variant-only, with an alphabetical tie-break for stability. Every term must appear, in any order, so `5070 ti` and `ti 5070` agree.

**Grouping is brand-major, newest generation first** (`productIndex.ts`), labelled from the existing `generationTierLabel` — no new derivation, and a new generation gets a header as soon as the watchlist tags it. Brand-major because buying is brand-anchored; the cost is that an older NVIDIA generation sits above a newer AMD one, which the explicit headers make legible. Headers do not collapse: collapsing would add a click to the task the page exists for.

**The index starts from the watchlist, not from what has been scraped.** 39 of 100 tracked products have never matched a listing. Building the page from `getLatestListings` alone silently omitted them, so searching a genuinely tracked model answered "no match" — a different claim from "nobody stocks it". `getTrackedProducts` supplies the full category and rows say **Not listed**, distinct from **No stock**. It also means the header count is honest: "47 tracked · 23 seen at a retailer".

**Removed:** `ProductCard`, `Filters` (no consumer left), the retailer chip row added days earlier in price-first IA stage 4 — the search box supersedes it — and server-side text search, sort and debounce for this route. The in-stock toggle survives.

**Intel Arc was mis-tagged.** A380/A750/A770 (Alchemist) and B570/B580 (Battlemage) were all `current`, and `intel-gpu` had no label mapping, so five cards from two generations would have sat under one generic "Current gen" heading. Retagged in the watchlist, with `Arc B (Battlemage)` / `Arc A (Alchemist)` labels.

**That exposed a seeding bug worth its own note.** `db/watchlist.csv` calls itself the source of truth, but `seed.py` skipped every existing product outright, so a corrected `gen_tier` could never reach the database — the retag did nothing until `seed_products` learned to sync that one column (reported as `updated`, honoured by `--dry-run`). Only `generation_tier` is synced; the rest of the row is either immutable identity or enriched elsewhere.

#### Retailer four: Mwave decided against, not attempted (2026-09-03)
Supersedes the "Mwave removed from scope (2026-08-10)" entry above, which was itself superseded by the 30/31-Aug re-probes (`docs/proposals/mwave-waf-probe.md`, `THIRD_RETAILER.md`) that found it *is* scrapable — real 200s with real HTML, not the blanket CloudFront block first recorded. This entry is the final call on top of that research, not another reversal of the technical facts.

Two things were true going into the decision: Mwave sits behind AWS WAF with a **count-based** allowance (not rate-based — 5s and 30s spacing gave identical results, 5 requests served then challenged on the 6th, repeatably) and **zero retry headroom** at the realistic daily cost (~5 requests via `/searchresult?cnt=100`); and Umart, which shipped 31-Aug as retailer three, was picked specifically because it *measurably* restored coverage (23→25/46 GPUs, 34→37/54 CPUs).

Mwave's equivalent coverage value was never measured — until now. Checked all 39 tracked-but-unlisted products (22 GPU, 17 CPU, per `check_stale_listings`-adjacent DB query) against Mwave's complete GPU catalogue (all 3 pages, 276 of 278 products) and a CPU search (100 products), using the repo's own `scraper.scorptec.match_product`. **Zero of the 22 unlisted GPUs appear anywhere in Mwave's GPU catalogue** — it is dominated by current-gen stock (RTX 50-series, RX 9000-series) exactly like the three retailers already tracked, and the RX 6000/7000-series and RTX 30/40-series cards that make up the gap are equally end-of-life there. On CPUs, only 2 of 17 gaps are genuine current listings (`i5-14600KF`, `i9-14900F`); a third apparent hit (`Ryzen 9 7950X`) is refurbished stock only, and three more were matcher false positives (Mwave stocks the KF/X3D/X variant, not the base part tracked).

**Decision: park Mwave.** 2 real new CPU listings and 0 new GPU listings out of 39 gaps does not justify building a scraper with no retry margin against a count-based WAF. No scraper code was written. Revisit only if a specific future watchlist addition is confirmed to live at Mwave and nowhere else.

#### /products becomes a catalog table; specs read once per category (2026-09-30)
The GPU/CPU pages were search-first rows showing only price, name, delta and retailer, and on the live site most rows were end-of-life "Not listed" parts (#23). Browsing now hides products with no active listing by default. A "Show N not currently sold" toggle, kept in `?unlisted=1`, brings them back at the bottom of each group. **Search still covers the whole watchlist**, so the 25-Aug rule that a search for a tracked model never answers "no match" stands.

The new columns are VRAM (GPU) or cores (CPU), Released, and listings ("in stock of listed"). VRAM and cores come from `products`, which the watchlist fills. Released comes from `specs.launch_date`. That is an explicit, narrow exception to "specs are never joined into list queries": `getLaunchDates` is a **separate** per-category query over `specs` alone, memoised on `data_version` with the rest of the page, never a JOIN in the listing SQL. Column sorting and facet filters (#23 items 4–5) are deferred.

---

#### MSRP converted to AUD at today's RBA rate, inc. GST (2026-10-03, #32)
Supersedes the 16-Aug "MSRP stays USD" note. `fx.py` caches the daily RBA F11.1 rate (inverted to AUD per USD; Frankfurter/ECB as fallback; only 1.0 to 2.5 accepted) in `fx_rates`, best-effort after ingest with a WARNING-only `check_fx_rate`. The web shows `launch_msrp_usd x rate x 1.10` as "N% under/over US launch MSRP (about A$X inc. GST)". It is today's rate, not the rate at launch, because the question is "what would this cost me to buy new now", and the 10% GST is added because AU shelf prices include it. US MSRP excludes sales tax, so the figure is an indicator, not a promise. Until the first rate exists the UI shows "-" rather than a guess.

#### OzBargain posts are a separate table, never price history (2026-10-03, #34)
OzBargain posts are community deals, not retailer snapshots, so they go in `ozb_deals` (with `ozb_polls` as the poll log) and never in `retailer_listings` or `price_snapshots`; charts, deals maths and backups are unchanged. Only the RSS tag feeds are read (video-card and cpu, 2 GETs per poll, 18 a day), because `robots.txt` disallows `/goto/`, `/api/` and `/search/` and per-product feeds would break the budget. The alert compares against the same best in-stock rule the web uses (global latest snapshot date, active non-bundle listings), and a "live" deal must have a future expiry and have been seen in the feed within 7 days.

#### Buying signals complement the declined deal score (2026-10-03, #31)
The 2026-08-17 decision not to build a single numeric deal score stands. The signals checklist (`buySignals.ts`) is a set of separate, plainly worded facts, each with its evidence (percentile of days, lowest in N days, vs 30-day average, 7-day trend, sale event, successor), and there is no combined score or verdict. It states what the history shows and leaves the decision with the reader. Below a history gate it says "Gathering history" instead of guessing. Curated sale dates are flagged as estimates until announced.

#### Visual refresh: polish + signature; terminal wordmark; self-hosted fonts (2026-10-03, #22)
The owner chose "polish + signature" over a redesign: the dark default, CSS-variable tokens and one-accent charts stay, and we add a type scale, deeper surfaces, a shared `PageHeader`, mono tabular prices and the 6-segment `PriceRangeBar` as the signature element. The wordmark is the terminal style (mono `trackaroo` plus an accent `_`), and the favicon and app icons match it (`node web/scripts/render-icons.mjs`). Fonts (Bricolage Grotesque, IBM Plex Sans, IBM Plex Mono, latin subset, OFL) are self-hosted in `web/static/fonts/`, so no request leaves for a font host; a vitest guard pins that. Table pages are wide through a `wide` loader flag read by the layout. The catalogue row shows the range bar from xl, not lg (fixed-width columns already fill 1024px at lg). `--border-card` keeps the signed-off values; its test asserts it is more visible than `--border`, not a 1.5:1 bar, because it is a decorative edge. Pressed filter chips and the /deals Below MSRP toggle show a heavier weight plus a check icon, not colour alone (ruling R5). `range90` rows carry `{low, high, days}` (`days` feeds the accessible label). The product-page bar spans all recorded history while the row bar spans 90 days, and each says which in its label.

#### Price-to-performance: separate sourced metrics and Pareto frontier (2026-10-03, #33)
Supersedes the 17-Aug "Compare view: read-only, no value score" note for this transparent form only. The rejection of a single blended score still stands. What ships instead: separate, labelled metrics (GPU raster 1440p, GPU ray tracing 1440p, CPU gaming 1080p), each from one published TechPowerUp chart with its source and date in `db/perf_index.json`; a "Perf/A$1k" column on /products and /compare; and a `/value` page with a price-against-performance scatter, the Pareto frontier and the best buy per budget bracket. The index is researched from fetched sources and spot-checked, never recalled from memory, and a product the chart lacks is listed in `not_in_source` rather than estimated. The file is bundled by a static import (like the changelog), so there is no table, migration or pipeline step; updates are a PR plus a redeploy. CPU coverage is partial (the best single eligible chart), and the UI states "N of M". Widening it needs a second source with documented normalisation or a newer large review, tracked as a follow-up. Head-to-head matchups are a follow-up too.
