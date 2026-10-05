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
| **Regression tests** | ✅ Complete | 1377 tests via pytest |
| **Health checks** | ✅ Complete | JSON validation, DB freshness, match anomalies, price anomalies, spec coverage + staleness |
| **Concurrent DB access** | ✅ Complete | WAL mode active — safe reads while cron writes |
| **Frontend** | ✅ Complete | SvelteKit dashboard (`web/`) — dashboard, products (card grid with per-card trend sparklines, expandable per-variant listings, compare selection, inline 7-day trend sparklines, "Deal" badges), compare (`/compare?ids=` side-by-side specs + prices), movers (dense table + trend sparklines), price-history charts (low/high band + togglable listing lines + brand-grouped listings panel), product-page "since tracked" chips (all-time low/high + 30-day average), price-drop & restock alerts panel on the product page, command palette (Ctrl+K quick search → product/compare, with snapshot-count badges), sortable column headers on the dashboard + movers tables, display-cased variant names; reads the DB directly via better-sqlite3 |
| **Price alerts** | ✅ Complete | `check_alerts.py` — price-drop (≤ target, re-fires on further drops) + restock (24h cooldown) alerts, delivered best-effort via Discord/SMTP/webhook after each healthy run |
| **Delisted detection** | ✅ Complete | `check_delisted.py` — re-checks stale Scorptec listings that vanished from the grid; a positive 404/410 or "No Longer Available" page marks them `delisted` (shown with a Delisted badge, excluded from price ranges); unverifiable pages are left untouched |
| **Staleness monitor** | ✅ Complete | `check_staleness.py` — the only check that runs *outside* the pipeline, so it can detect the run that never happened; ERROR (exit 1 + Discord alert) when no retailer has data inside the threshold, WARNING when a single retailer lags |
| **Frontend tests** | ✅ Complete | 1200 vitest + 225 Playwright e2e (incl. axe accessibility checks) (with a `goto()` hydration helper) |
| **Deployment** | ✅ Complete | Single all-in-one Docker image: pipeline + dashboard in one container, run with `docker compose` (`deploy/redeploy.sh`)

## Quick start

```bash
# Install dependencies (runtime + test; both files are hash-pinned)
python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt

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

Only one `run_daily.py` runs at a time. It holds an OS file lock on
`db/run_daily.lock` (next to the DB) for the whole run, so a manual run started
while the scheduled one is going logs "already running" and exits 0 without
doing anything. The OS drops the lock when the process exits, even on a crash,
so there is never a stale lock to delete.

### Dependencies

Python dependencies are pinned with hashes, in two pairs of files:
`requirements.in` / `requirements.txt` for the runtime (the only file the Docker
image installs) and `requirements-dev.in` / `requirements-dev.txt` for the tests.
Edit the `.in` file, then regenerate both `.txt` files with
[uv](https://docs.astral.sh/uv/) and commit all four:

```bash
uv pip compile requirements.in --universal --generate-hashes --python-version 3.12 -o requirements.txt
uv pip compile requirements-dev.in --universal --generate-hashes --python-version 3.12 -o requirements-dev.txt
```

`--universal` keeps platform markers (pytest needs `colorama` on Windows only),
so the same files install on Linux, in the image and on a Windows dev machine.

## OzBargain deals

Trackaroo reads OzBargain's RSS tag feeds (`/tag/video-card/feed` and `/tag/cpu/feed`)
to show community deals on matching product pages, mark them on `/deals`, and send a
Discord alert when a deal beats our best in-stock price.

- **When:** `ozbargain.py` runs on its own loop in the container, separate from the 04:00
  scrape, at the hours in `OZB_POLL_HOURS` (zero-padded, comma-separated, default
  `07,09,11,13,15,17,19,21,23`, local time). Only `OZB_ENABLED=0` turns it off (any other
  value, or unset, leaves it on); it never starts under `SKIP_PIPELINE=1`. A restart guard
  skips a poll, with an INFO log and no poll row, if the last poll was under 90 minutes ago,
  so a crash loop cannot burn the daily budget.
- **Budget:** one poll is 2 GETs (one per feed), so the default is 18 requests a day.
  RSS only: the `/goto/` redirect, `/api/` and `/search/` are never fetched, and the
  deal link is always the OzBargain node page.
- **Prices** are parsed from the post title. Coupon or saving amounts ("$50 off",
  "Save $100", "$30 cashback") and non-AUD prices (US$, NZ$) are skipped; a post with no
  usable price shows "price in post".
- **Matching** uses the same chip-key matcher as discovery. Deals with ambiguous VRAM,
  prebuilt PCs and bundles are stored but not attached to a product.
- **Alert rule:** a live, matched deal alerts when its price is below the cheapest
  in-stock, non-bundle, active listing at our retailers on the latest scrape date (or
  when nothing is in stock), and its votes are not net-negative. "Live" means not
  expired, started, with an expiry still in the future, and seen in the feed within the
  last 7 days (the product page and /deals use the same rule; date-expired and stale deals
  move under "Show expired"). Each deal alerts once, at most 5 are sent per poll, and a failed Discord
  send is retried on the next poll. It needs `DISCORD_WEBHOOK_URL`.
- **Dry run** (parse and match, print, no writes and no Discord):
  `docker compose exec trackaroo python ozbargain.py --dry-run`
- **Never price history:** deals live in their own `ozb_deals` and `ozb_polls` tables and
  never enter `retailer_listings`, `price_snapshots`, charts or the deals maths. `check_ozbargain`
  only ever warns (no successful poll in 24 hours).

## Discovering and adding new parts

Retailers launch parts faster than the watchlist grows, so Trackaroo tells you
what it is not tracking. Every scraper keeps a 30-day catalogue of everything it
sees in `data/catalogue/` (a report only: never ingested, safe to delete). After
each daily run `discover.py` lists the in-scope CPUs and GPUs that
`db/watchlist.csv` does not track. A part seen for the first time is posted once
to the Discord digest channel as **New parts at retailers**; every untracked part
is always listed on **/discover**, where you **Track** or **Ignore** it. Tracking
does not change the watchlist by itself: it produces the CSV row you add in a PR.

### Example: adding the RTX 5050

1. Discord shows a line like
   `**GeForce RTX 5050 8GB**: 6 listings at pccg, scorptec, umart, from $389`
   (the message title is "New parts at retailers").
2. Open `http://<server>:3000/discover`. The row shows when it was first seen,
   the listing count, the retailers and the lowest price (a link to that
   listing). Click the name to see real listing titles, to check it is the card
   you think it is.
3. Click **Track**. The part moves to **Requested**, which shows the row to add
   (columns `category,brand,model,spec,series,status`):
   `gpu,NVIDIA,GeForce RTX 5050,8GB,rtx50,active`.
   The `series` is the key from `db/generations.toml` that the chip belongs to.
   If it reads `NEW-SERIES` the chip is a new generation with no series yet: run
   `python manage_watchlist.py rollover ...` first and use the key it creates.
   The equivalent command for an existing series is
   `python manage_watchlist.py add "GeForce RTX 5050" --spec 8GB --series rtx50`.
   **Copy row** copies it; **Undo** puts the part back under Untracked.
4. Add that row to `db/watchlist.csv` on a branch and open a PR (or ask Claude to).
   Two rows need a human to finish them, and the pipeline will not guess:
   - A **CPU** row has `?c` as its spec, e.g.
     `cpu,AMD,Ryzen 5 5600GT,?c,zen3,active`. Shop
     titles rarely give core counts, so replace `?c` with the real count
     (`6c`) from the manufacturer's spec page.
   - A **GPU** whose titles never state VRAM has `?GB` (e.g.
     `...,GeForce RTX 5070 Ti Super,?GB,...`). Replace it with the real size
     (`16GB`).
   Until you do, `db/watchlist.py` rejects the row (`cannot read cores from '?c'`):
   the pipeline skips that one row with a logged error and carries on, so nothing
   crashes but the part is not tracked. Model names use "Super" title case
   (`GeForce RTX 5070 Ti Super`), as in the existing rows.
   In the same PR, add the part to `db/perf_index.json`: its figures under
   `products`, or its name (e.g. `Radeon RX 9050 8GB`) in each `not_in_source`
   list if TechPowerUp has no figure yet. CI fails without it. Also add the
   part's US launch MSRP to `db/launch_msrp.json`
   (keyed by the exact model name); it is applied on every container boot.
   Specs follow on the next weekly sync, and until then (7 days) the spec
   report lists the part as pending rather than unmatched.
5. CI checks the row (`unit_testing/test_watchlist_validation.py`,
   `unit_testing/test_discover_rules.py`, `unit_testing/test_perf_index.py`,
   `manage_watchlist.py check`). Merge the PR once all three CI jobs are green.
6. On the server, outside 04:00-09:59 Melbourne (the daily scrape window):
   `cd ~/docker/Trackaroo && deploy/redeploy.sh`. The boot runs `seed.py`, which
   adds the product.
7. At the next daily run the part leaves **Requested** (status `tracked`) and
   appears under GPUs with prices from that day. Specs arrive on the Sunday spec
   sync, or run
   `docker compose exec trackaroo python sync_specs.py --category gpu`
   (`--category cpu` for a CPU).

### Example: ignoring the Ryzen 5 5600GT

Not everything deserves a page. On **/discover** click **Ignore** next to the
part: it is hidden and never notifies again. To undo it, open **Ignored** at the
bottom of /discover and click **Un-ignore**; the part returns to Untracked (it
is not announced a second time).

### Conflicts

The **Conflicts** list is the opposite problem: a listing is filed under the
wrong tracked product. The title is shown first, then the retailer, the product
it is filed under, and why it looks wrong, for example:

> Sapphire Pulse RX 9070 GRE 12GB
> Scorptec · filed under Radeon RX 9070 · title names rx 9070 gre, product is rx 9070

- If the right product already exists in the watchlist, run `repair_listings.py`
  (dry run first, then `--apply`):
  `docker compose exec trackaroo python repair_listings.py`.
- If it does not exist (here, an RX 9070 GRE row), **Track** that part first,
  add its row as above, deploy, then repair.
- If the titles look right and are still flagged, it is a matcher bug: open an
  issue and paste the line.

### When a new generation launches (e.g. RTX 60)

A series newer than `db/generations.toml` is treated as in scope at `current`, so
it shows up on /discover instead of disappearing. Then follow
`docs/ARCHITECTURE.md` Part 2 section 7 (launch day): `python manage_watchlist.py rollover`,
add the SKU rows, `check`, PR, redeploy, `seed.py --allow-bulk`.

### Managing the watchlist: the files, adding and retiring

Every change to what Trackaroo tracks is a change to files in `db/`, made in a
PR. The buttons on /discover (Track, Retire, Keep) only record a *request*;
nothing changes until the files do.

| File | What it holds | Touch it when |
|---|---|---|
| `db/watchlist.csv` | One row per product: `category,brand,model,spec,series,status` | **Always.** Adding = a new `active` row; retiring = set `status` to `retired`; un-retiring = set it back to `active`. Rows are never deleted. |
| `db/perf_index.json` | Performance figures for the /value page and Head to head | **Adding a GPU or CPU.** Add its figures under `products`, or, if the source (TechPowerUp) has none yet, list it under `not_in_source` for each metric. `test_perf_index` fails the PR otherwise. |
| `db/generations.toml` | The ordered series per product line (sets the tiers and labels) | Only when a **new generation** launches (`rollover`). |
| `db/launch_msrp.json` | US launch MSRPs | Adding a part, when its MSRP is known (optional). |

The CLI makes the CSV and toml edits for you, and each writing command takes
`--dry-run` to preview the change:

```bash
python manage_watchlist.py add "<model>" --spec 8GB --series rx9000          # add a part (16c for a CPU)
python manage_watchlist.py retire "<model>"                                  # retire one part
python manage_watchlist.py retire --series zen3                              # retire a whole series
python manage_watchlist.py rollover amd-cpu --new zen6 --label "Ryzen 10000 (Zen 6)" --chips ryzen:10
python manage_watchlist.py check                                             # validate everything (CI runs it too)
```

Run these on your PC in the repo, not on the server: the server's checkout must
stay clean for `deploy/redeploy.sh`. The one exception is `reassign` (moving a
mis-filed listing), which writes the database and is run on the server with
`docker compose exec trackaroo python manage_watchlist.py reassign ...`.

**Adding a part:** Track it on /discover (or pick it yourself), then add the CSV
row and its `perf_index.json` entry, plus the MSRP if known, in one PR. Example:
PR #82 (RX 9050 8GB).

**Retiring a part:** the **Ready to retire** section of /discover lists tracked
parts that no retailer has listed for 30 days. Click **Retire** (or **Keep** to
hide it for 90 days). Then set the row's `status` to `retired` in a PR with
`manage_watchlist.py retire "<model>"`. To see what was requested, run this on
the server: `docker compose exec trackaroo python manage_watchlist.py retire --stale --dry-run`.
A retired part keeps all its price history; it just stops being scraped and shown.

**How a merged change reaches the server.** The container reads `db/` from the
server's checkout (compose mounts `./db`), and `seed.py` applies the CSV to the
database at container start. So:

- Normal route: `cd ~/docker/Trackaroo && deploy/redeploy.sh` (outside
  04:00-09:59). It pulls, rebuilds, restarts and seeds, which covers everything.
  A `perf_index.json` change needs this route, because that file is built into
  the web app.
- Quick route for a CSV-only change: `git pull` then
  `docker compose exec trackaroo python seed.py`.
- A change of more than 5 products at once (a rollover, or retiring a series)
  is refused by seed's bulk guard. Run `docker compose exec trackaroo python seed.py --dry-run`,
  check the list, then `docker compose exec trackaroo python seed.py --allow-bulk`.

More detail: `docs/ARCHITECTURE.md` Part 2 section 7.

### Troubleshooting

- **No Discord message**: check `DISCORD_WEBHOOK_URL`. A part is announced once
  only, so look for it on /discover instead. A failed send is retried on the next
  run.
- **"Discovery has not run today yet" banner**: look in
  `docker compose logs trackaroo | grep -i discovery`. The health check
  `discovery` only ever warns; it never blocks the digest.
- **A real CPU/GPU under "Unrecognised titles"** (bottom of /discover): the
  chip-key patterns in `scraper/chip_key.py` do not know it yet. Open an issue
  with the title.
- **`data/catalogue/`**: kept 30 days, safe to delete, never ingested. Do not
  move its files up into `data/`: the ingest and the web seeders read every
  `data/*.json`.

> **Security:** the Track, Ignore, Undo and Un-ignore buttons have no login,
> like price alerts. Anyone who can open the dashboard can click them. Put the
> site behind a login before exposing it to the internet.

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
| `./db` | `/app/db` | `trackaroo.db` (SQLite, WAL), `backups/`, `schema.sql`, `watchlist.csv`, `generations.toml` (read from the host checkout, so a `git pull` updates them) |
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

1. Runs `seed.py`: creates the DB if it doesn't exist, and on every boot syncs
   `products` with `db/watchlist.csv` and `db/generations.toml` (new rows added,
   `retired` rows untracked; more than 5 tracked changes need `--allow-bulk`).
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
| OzBargain poll hours | `07,09,11,13,15,17,19,21,23` | `-e OZB_POLL_HOURS=08,20` (zero-padded); `-e OZB_ENABLED=0` disables |

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

### Releases and the version in the footer

The footer shows the release and the build, e.g. `v0.4.0 · build 328073f`.
The release links to `/changelog`, which renders [`CHANGELOG.md`](CHANGELOG.md).
`/healthz` reports both: `release` and `version` (the git SHA).

- **Release number:** `web/package.json` `version` is the single source. It is
  baked in at build time.
- **Changelog:** each PR adds its lines under `## Unreleased` in `CHANGELOG.md`.
- **Cutting a release:**
  1. Run `python release.py X.Y.Z` from the repo root. It moves Unreleased into
     `## X.Y.Z — <today>` and bumps `web/package.json` and its lockfile.
  2. Commit, and merge.
  3. Tag the merge commit and push the tag:
     `git tag -a vX.Y.Z -m vX.Y.Z <sha> && git push origin vX.Y.Z`.
  4. Redeploy.
- **Version numbers:** the minor number goes up for features, the patch number
  for fixes.
- **Open PRs during a release:** a feature PR branched before a release merged
  can land its `## Unreleased` line inside the just-released section. After
  merging such a PR, check that its CHANGELOG line still sits under Unreleased.
- **Guards:** pytest (`test_release.py`) and vitest (`changelog.test.ts`) both
  fail if the newest changelog release and `package.json` disagree. Vitest also
  fails if releases are not listed newest first.
- **Docker:** the build context must include `CHANGELOG.md`. The Dockerfile
  copies it into the web build stage.

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

# Run frontend unit tests (1200 vitest)
npm test

# Run browser e2e regression tests (225 Playwright, against a seeded dev server)
npm run test:e2e
```

Point it at a different DB file with `TRACKAROO_DB=/path/to/trackaroo.db`. The default path resolves to `<repo>/db/trackaroo.db` relative to the server module.

### Design system

- **Fonts** are self-hosted in `web/static/fonts/` (Bricolage Grotesque 700/800 for display, IBM Plex Sans 400/500/600 for text, IBM Plex Mono 500/600 for prices), each with its OFL licence. No request goes to Google or any other font host. `web/server.js` serves `/fonts/*` with `Cache-Control: public, max-age=31536000, immutable` (#63), so never change a font file in place: give a new font a new file name.
- **Prices inside sentences** (buy-signal claims and evidence) are split with `splitPrices()` in `$lib/formats` and the amounts set in `.num` (#62), so every price uses the mono number face.
- **Type tokens** in `web/src/app.css`: classes `.text-display`, `.text-title`, `.text-section`, `.text-price`, and theme sizes `text-body` and `text-meta`. Prices use the mono tabular face (`.num` or `text-price`).
- **Surface tokens:** `surface-2`, `surface-3`, `border-card` and the card shadow, in both themes.
- **Components:** `Wordmark` (terminal style: mono `trackaroo` plus an accent `_`), `PageHeader` (one per route, with `actions` and `meta` slots and a snippet subtitle) and `PriceRangeBar` (6 segments, full and compact sizes; catalogue rows show it from xl).
- **Layout:** table pages are wide through the `wide` loader flag. The phone nav wraps.
- **Non-colour state:** pressed filter chips and the /deals Below MSRP toggle show a heavier weight plus a check icon, not colour alone.
- **Range bar scope:** the product-page bar spans all recorded history and the catalogue row bar spans 90 days; both are labelled.
- **Icons:** `node scripts/render-icons.mjs` (from `web/`) regenerates the PNG icons from `static/favicon.svg`.

### Browsing the catalogue

`/products?category=gpu` (or `cpu`) filters and sorts the catalogue, and the whole view lives in the URL, so any filtered list can be bookmarked or shared as a link. Filters: a maximum price (presets of $500, $1000, $2000, or any amount), brand, GPU/CPU generation, in stock only, and a retailer. Sort by price, model, VRAM (GPU) or cores (CPU), release date or number of listings; click a column header, or use the sort control, and click again to reverse. The controls are an inline form on desktop. On a phone they sit behind a "Filters (N active)" button that opens a dialog, and with JavaScript off they stay inline as a plain GET form, so the filters still work. "Clear filters" resets the URL. The compare page marks the best value in each spec row, and the product-page chart can show the 30-day average line.

## Buying signals

Every product page has a "good time to buy" checklist built from the price history (`web/src/lib/buySignals.ts`). Each badge states its evidence.

- **Percentile**: "As cheap as or cheaper than N% of days". It counts the days whose lowest price was at or above today's price.
- **Lowest in N days** and **vs 30-day average**: how today's price sits against recent history.
- **7-day trend**: falling, flat or rising.
- **Sale event**: a named sale that is on now or coming up (below).
- **Successor**: the next generation has been announced (below).
- **Gathering history (N days)**: shown instead of the history badges until the product has enough days of data.

The stats strip shows the 30, 90 and 180-day low, median and high, and the chart marks sale events with dashed lines.

**MSRP in AUD.** `msrpAud = launch_msrp_usd x aud_per_usd x 1.10` (the 10% is GST), shown as "N% under/over US launch MSRP (about A$X inc. GST)". The catalogue has a "vs MSRP" column (`sort=msrp`) and `/deals` has a "Below MSRP" toggle (`?below_msrp=1`). The rate comes from `fx.py`, a best-effort step in `run_daily.py` after ingest: it reads the latest RBA F11.1 rate (FXRUSD, inverted), falls back to Frankfurter (the ECB rate), accepts only 1.0 to 2.5 AUD per USD, and stores it in `fx_rates`. Until the first rate exists the product page shows no MSRP line, the catalogue column shows "–", and `/deals` hides the Below MSRP toggle (and ignores `?below_msrp=1`). `check_fx_rate` only warns when the rate is more than 7 days old or missing. To fetch a rate now:

```bash
docker compose exec trackaroo python fx.py   # production
python fx.py                                  # native
```

**Sale events** (`web/src/lib/saleEvents.ts`). EOFY, Singles Day, Black Friday to Cyber Monday and Boxing Day are rule-based and need no upkeep. Click Frenzy and Prime Day are curated per year in the `CURATED` table, and the current entries are estimates (the tuple's last element is `true`), shown to users as "estimated dates". When a retailer announces the real dates, edit that year's entry and set the last element of its tuple (`[name, start, end, estimated]`) to `false`. Add next year's entries and its year to `CURATED_YEARS` before the year turns: a test fails when next year has no entry. "Today" for sale badges is the Australia/Melbourne date.

**Successors** (`web/src/lib/successors.ts`). `SUCCESSORS` maps a product's specs `generation` string to the successor label and starts empty. The key is the spec value, for example `"GeForce 40"` (not `"RTX 40"`); the badge appears for every product in that generation. Example once the next series is announced: `"GeForce 50": "GeForce 60"`.

Icons are Lucide (`@lucide/svelte`); `web/test/noEmoji.test.ts` fails if an emoji appears in `web/src`.

## Value (price to performance)

`/value` and the "Perf / A$1k" column answer "which part gives the most performance per Australian dollar today?". They use separate, sourced metrics. There is no blended score. Full source notes are in [`docs/perf-index-sources.md`](docs/perf-index-sources.md).

**Metrics and sources** (`db/perf_index.json`, bundled into the web build by a static import):

- GPU 1440p raster and GPU 1440p ray tracing: TechPowerUp, ASUS RTX 5090 Matrix review (Apr 2026), relative to that card.
- CPU 1080p gaming: TechPowerUp, Ryzen 7 7700X3D review (Jul 2026), relative to the 7700X3D.
- One chart per metric, so every value of a metric shares one baseline. A tracked product the chart does not list goes to `not_in_source` and is never estimated.
- CPU coverage is partial, so the UI says "Performance data for N of M (X of Y current and previous generation)".
- Product key: the watchlist model alone when it already ends with its VRAM spec (`GeForce RTX 5060 Ti 8GB`), else `<model> <spec>` (`GeForce RTX 5060 Ti 16GB`). CPUs use the model.

**Columns.** "Perf/A$1k" is `performance / shown price x 1000` (raster for GPUs, gaming for CPUs). It is on `/products` from the xl breakpoint (sortable with `sort=value`) and on `/compare`. A product with no data, or whose shown price is out of stock, shows "–" and sorts last.

**`/value` page.**

- Scatter of price against performance with a log price axis (labelled "log scale"). A y axis that does not start at 0 says so on the chart.
- Frontier rule: a point is on the frontier unless another point has a price at or below and performance at or above, with at least one strictly better. Ties are kept.
- Best per budget: brackets of A$400, 700, 1000, 1500 and 2500. The winner is the highest performance at or under the bracket price. Ties go to the lower price. The runner-up and the gap are shown. "Exclude 8 GB cards" applies to GPUs. The toggle appears only when it can change something (an 8 GB card sits in a budget card) and stays visible while it is on, so it can always be switched off.
- Accessibility: every point is focusable, tab order follows price, and a visually hidden table carries the same rows.
- One price rule (#59, #70): `/products`, `/compare`, `/value`, the Head to head panel and the product headline all use the cheapest in-stock, active, non-bundle listing, each at its own latest snapshot and seen within 7 days of its retailer's latest scrape, so a price or Perf/A$1k figure is the same on every page. `/deals` and the OzBargain alert deliberately count only today's scrape.

**Refreshing the index.**

1. Pick one chart per metric: the recent TechPowerUp chart that lists the most tracked products of that category. Record it in `docs/perf-index-sources.md` and in `metrics` in `db/perf_index.json`.
2. Transcribe every value for that metric from that chart. Never mix old and new values.
3. List each tracked current and previous generation product the chart lacks under `not_in_source`. Coverage rule: GPU raster and CPU gaming are required for current and current-1 products. Ray tracing is required only where the RT chart lists the card; otherwise the card goes to `not_in_source.gpu_rt_1440p`.
4. Update the pinned VRAM-variant values in the tests (`unit_testing/test_perf_index.py`, `web/test/value.test.ts`, `web/test/compareRows.test.ts`).
5. Run `python -m pytest unit_testing/test_perf_index.py` and the web watchlist coverage test (`cd web && npm test`).

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
├── db/perf_index.json  # sourced performance index behind /value (see docs/perf-index-sources.md)
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
├── requirements.in     # runtime deps, top level (edit this)
├── requirements.txt    # runtime deps, hash-pinned (generated; the Docker image installs this)
├── requirements-dev.in # test deps, top level (edit this)
├── requirements-dev.txt # test deps, hash-pinned (generated; CI installs both files)
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
    ├── src/routes/             # /, /products, /product/[id], /compare, /movers, /deals, /discover, /changelog, /healthz
    ├── test/                   # 1028 vitest regression tests (50 suites)
    ├── e2e/                    # 184 Playwright regression tests (app.spec.ts, mobile.spec.ts, a11y.spec.ts, seed.mjs)
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
