# Trackaroo — Agent Guide

Monorepo: Python scraper + ingest at the repo root, SvelteKit frontend in `web/`.

Self-hosted AU CPU/GPU price tracker. One SQLite DB (`db/trackaroo.db`) written
by the Python pipeline and read by the dashboard. Daily snapshot cadence.

## Orientation

| Doc | What's in it |
|---|---|
| [`README.md`](README.md) | Setup, commands, repo layout |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Spec (Part 1), watchlist scope rules + **how to add a product (Part 2 §7)**, decision log (Part 3) |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Running it — Docker and native |
| [`STATUS.md`](STATUS.md) | Current state + working log |
| [`CHANGELOG.md`](CHANGELOG.md) | User-facing release notes, shown at `/changelog`; add a line under **Unreleased** in every PR, cut with `python release.py X.Y.Z` |
| `docs/archive/` | Implemented/declined plans, kept for rationale |
| `docs/proposals/` | Not-yet-built work (e.g. RAM tracking) |

## Commands

**Backend** (repo root): `python -m pytest -q` — 1416 tests.

**Frontend** (from `web/`):

- **Unit tests**: `npm test` (Vitest, 1274 tests, ~15s)
- **Watch mode**: `npm run test:watch`
- **E2E tests**: `npm run test:e2e` (Playwright, 231 tests (+1 skipped), Chromium only, must be kept fast)
  - Runs against a deterministic seeded DB (`e2e/seed.mjs` → `e2e/e2e.db`) served by a `vite dev` server on port 4174.
  - `e2e.db`, `test-results/`, and `playwright-report/` are gitignored and regenerated on each run.
- **Type + Svelte check**: `npm run check` (svelte-check, must report 0 errors)
- **Build**: `npm run build` (svelte-kit sync + vite build; run if a change affects the production build).

**Full validation before finishing a task**: backend `python -m pytest -q` from
the repo root, then from `web/`: `npm run check`, `npm test`, `npm run test:e2e`.

## Docker (from the repo root, NOT `web/`)

**Deploy with docker compose** (`docker-compose.yml`, one `trackaroo`
service; owner decision 30-Sep-2026 reversed the earlier "no compose" rule).
Prod is `~/docker/Trackaroo` on the owner's `dockerhost`.

```bash
deploy/redeploy.sh    # pull, backup, build with GIT_SHA, up, wait healthy, repair dry run, verify
docker compose logs -f trackaroo
```

**Never `docker compose up` (or `docker run` with the mounts) in a dev
working copy**: it mounts this checkout's `db/` and starts a live retailer
scrape. Local image checks boot it like CI: `--network none -e SKIP_PIPELINE=1`
and no mounts (see the end of this file).

- **Always map both `/app/db` and `/app/data`** (compose does). Without them the SQLite DB and
  the JSON snapshots live in the container's writable layer and die with
  `docker rm` — a live container was found in exactly that state, discarding
  everything it scraped. Mapping them onto the repo's own directories means the
  container and native runs share one source of truth.
- The image pins `TZ=Australia/Melbourne` and installs `tzdata`. This is
  correctness, not cosmetics: the scrapers stamp snapshots with `date.today()`,
  so a UTC container running before 10:00 AEST files data under the previous
  day and forks the history.
- Both entrypoints schedule on a **wall clock** (`RUN_AT_HOUR`, default 04),
  retry hourly per retailer up to `RETRY_UNTIL_HOUR` (default 09, #8), and run
  an immediate boot catch-up (`--pending-only`) for whatever today is still
  missing. Do not go back to `sleep ${RUN_INTERVAL_HOURS}h` — it drifts on
  every restart and can skip a day outright.
- `deploy/entrypoint-single.sh` is the default entrypoint (pipeline +
  dashboard); `RUN_ONCE=1` runs one pipeline then exits.
  `trackaroo-entrypoint-pipeline` (`deploy/entrypoint.sh`) is the pipeline-only
  override.
- **Critical constraint**: the app NEEDS Python 3.12 (PEP 701 f-strings like
  `f"{wp["vram_gb"]}gb"` are compile errors on 3.11) — so the runtime stage is
  based on `python:3.12-slim` with the Node binary copied from the build stage.
  Never switch the runtime to apt/bookworm `python3`.

## Data integrity — read before touching the pipeline

The JSON files in `data/` are the backup: the DB must be rebuildable from them
via `ingest.py`. That guarantee was broken once and cost 165 snapshots, so it is
now enforced in three places. Keep all three.

- **Never write a snapshot with a bare `open(path, "w")`.** Use
  `scraper.snapshot_io.save_snapshot()` — it writes atomically (temp file +
  `os.replace`) and refuses to replace a snapshot with a smaller one, parking
  the weaker result in a `.partial-HHMMSS.json` sidecar. A rate-limited re-run
  that matched nothing must never destroy a good file.
- **`run_daily.py` mirrors the DB back out to JSON** after every ingest
  (`export_snapshots.run(repair_only=True)`), so JSON ⊇ DB continuously.
- **`check_json_db_parity`** fails the run if a day's JSON can no longer rebuild
  it. Fix with `python export_snapshots.py --repair`.

Listings are identified by their **stable SKU key**
(`ingest.extract_listing_key`), never the raw URL — retailers rewrite slugs, and
matching on the URL forks duplicate listing rows.

- **`data/catalogue/` is a report, not a backup** (#16). Scrapers write every
  item they see there via `scraper/catalogue_io.save_catalogue` (atomic, never
  through `save_snapshot`, kept 30 days). Never move these files to the top of
  `data/`: `ingest_today` globs `data/*_{date}.json` and the web seeders read
  every `data/*.json`.

Never delete price or product data. Products that roll out of scope get
`tracked=0`; listings get `status='delisted'`/`'stale'`.

## Pipeline conventions

- `fx.py` (daily AUD per USD rate, RBA F11.1 with a Frankfurter fallback, into `fx_rates`) is a best-effort `run_daily` step after ingest; `check_fx_rate` is WARNING-only (rate older than 7 days or table empty). Until a rate exists the product page shows no MSRP line, the catalogue column shows "–", and /deals hides the Below MSRP toggle and ignores `?below_msrp=1`. One MSRP rule everywhere: the lowest positive `launch_msrp_usd` across a product's spec rows.
- `ozbargain.py` runs on its own 2-hourly loop in the entrypoint (`ozb_loop`), not in `run_daily`. It is best-effort, `check_ozbargain` is WARNING-only, and a poll is a 2-GET budget (one RSS feed per category) pinned by test. Deals live in `ozb_deals`, never in price history.
- Steps after ingest (delisted check, JSON mirror, alerts, digest) are
  **best-effort**: route them through `run_daily.best_effort()` (or a
  `try/except` that logs). Health checks go through `guarded_check()`, so a
  crashing check becomes an ERROR result. The backup runs in a `finally`.
- `discover.py` runs after ingest through `best_effort`; `check_discovery` is
  WARNING-only. The scope table in `discover_rules.py` must agree with
  ARCHITECTURE Part 2 and `db/watchlist.csv` (`test_discover_rules.py`).
- The Discord digest is gated on zero ERROR-level health results. Checks that
  are informational must return WARNING, not ERROR, or they will suppress it.
- Entry points call `config.setup_logging()`, not `logging.basicConfig` — it
  adds the date-stamped `logs/trackaroo-*.log` file handler. Use a plain
  append `FileHandler`, never a rotating one: the scrapers are separate
  processes sharing the file and concurrent rotation corrupts it.
- Scrapers exit `0` ok, `2` degraded (a category empty / breaker tripped),
  `3` skipped (cooldown), `4` auth rejected (`scraper/run_report.py`), and
  flush a `RunReport` after **each category**, saving that category's snapshot
  at the same moment. Never go back to one save at the end of `main()`: the
  300 s timeout would cost the whole day (R2).
- The schedule lives in `run_daily.py --scheduled` / `--pending-only`, not in
  the entrypoints. A retailer is done today when its latest `scrape_runs` row
  is `ok`.
- `active_retailers`, `scrape_runs` and `run_markers` are bookkeeping
  tables: DDL in `migrate.py` + `db/schema.sql`, access through
  `pipeline_state.py`.
- `unit_testing/conftest.py` blocks every non-loopback socket. A test that
  trips it was going online: mock it, don't loosen the guard.
- **PCCG's Algolia key allows 100 queries per IP per hour.** That is a hard
  fact of the key, confirmed against `GET /1/keys/<key>`
  (`"maxQueriesPerIPPerHour": 100`), not a guess from observed 429s. The
  scraper therefore fetches each category **whole** — one empty query with
  `hitsPerPage=1000` — and matches the watchlist locally
  (`algolia_fetch_catalogue`). A full run costs **2 queries**: 229 GPUs and
  60 CPUs each fit in a single page.
  **Never go back to one query per watchlist product.** That is what caused
  the daily 429s: 100 tracked products spent the entire hourly budget on page
  0 alone. Batching them into one HTTP request does not help — Algolia bills
  each entry in the `requests` array separately. And no amount of backoff can
  help, because the budget is a **rolling ~60-minute window** (measured: a
  heavy spend at 18:06 GMT was still 429ing at 19:01 GMT, after a fresh clock
  hour began). Quota frees up about an hour after whatever spent it, so
  waiting inside a run only burns the run. `algolia_single_search` / `algolia_batch_search` are
  kept for manual one-off queries and are marked deprecated for this reason.
  `unit_testing/test_pccg_query_budget.py` pins the 2-query budget.
- On a circuit-breaker trip (an entirely empty catalogue — a block, not an
  empty shop) the scraper writes `data/pccg_cooldown.json` and later runs skip
  PCCG for `PCCG_COOLDOWN_HOURS`. That is intended — don't "fix" it by removing
  the breaker. If it trips now, suspect something *other* than our own query
  volume: another process on the same IP, or PCCG changing the key.
- A **rejected key** (401/403) is not a block: no cooldown. `scraper/pccg_key.py`
  reads the current key from one pccasegear.com page, caches it in
  `data/pccg_algolia.json` and retries that category **once** per run (#11b);
  if that fails, exit 4 and alert. Keep it one discovery, one retry: a loop
  would spend the 100/hour budget on a dead key.

## E2E conventions

- **Interaction hydration race**: The app is server-rendered; clicks/selects can land before Svelte hydrates and silently do nothing. Every page navigation in `e2e/app.spec.ts` must go through the local `goto()` helper, which waits for `networkidle` (i.e. hydration done) before the test interacts:
  ```ts
  async function goto(page: Page, path: string) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
  }
  ```
  Do **not** call `page.goto(...)` directly in specs; use `goto(page, path)` (and `await page.waitForLoadState('networkidle')` after `page.reload()`).
- **Full-navigation server actions**: some actions are plain HTML POST forms (e.g. the product-page price-alert create/delete), which trigger a full page navigation rather than a client-side update — wait for `networkidle` after submitting before asserting on the reloaded page.
- Keep the suite deterministic: it asserts against fixed seeded data, so assertions must not depend on scraped-live data.
- Keep the suite fast (goal ≲ 60s). Avoid artificial `waitForTimeout` sleeps.

## Guardrails

- Never commit secrets or `.env` values. `.env.example` is the template; pass
  secrets to the container with `--env-file .env`, never baked into an image or
  a committed default.
- Generated/regenerable files (`web/e2e/e2e.db`, Playwright artifacts, `logs/`) must stay gitignored.
- Client Svelte components must not import **runtime values** from `$lib/server/...` (server-only modules) — it breaks client hydration ("An impossible situation occurred"). Shared constants live in `web/src/lib/constants.ts`.
- Server queries live in `web/src/lib/server/queries/*` (barrel: `$lib/server/repos`); DTO types in `$lib/models`; client code never imports `$lib/server` (`test/boundaries.test.ts`).
- `web/src/lib/server/db.ts` `getDb()` is read-only; write paths (e.g. alert create/delete) use `getWriteDb()`.
- Update `STATUS.md` before ending a work session — add a dated bullet under
  **Recent changes**. Do not start a nested "Prior update" chain; that is what
  grew the file to 106 KB.

## Shell scripts must reach the working tree as LF

Git stores `deploy/*.sh` as LF and always has. The damage happens on
**checkout**: Git for Windows ships `core.autocrlf=true` at *system* scope, so
without `.gitattributes` every Windows clone materialises these scripts with
CRLF. `docker build` COPYs the working-tree file, so the CR rides into the
image, the shebang becomes `#!/bin/sh` + CR, and Linux hunts for an interpreter
literally named `/bin/sh<CR>`. The ENOENT is reported against the *script*:

```
[FATAL tini (7)] exec /usr/local/bin/trackaroo-entrypoint failed: No such file or directory
```

which reads as a missing `COPY` and sends you hunting in the wrong place. The
container could not start at all. Three guards, keep all three:

- **`.gitattributes`** pins `*.sh` (and `Dockerfile`) to `eol=lf`, so the
  checkout is correct in the first place.
- **The Dockerfile** strips CRs after `COPY` and runs `sh -n` on each script,
  so a source zip or stray editor fails the build rather than the first boot.
- **`unit_testing/test_shell_scripts.py`** fails the suite if any tracked
  `*.sh` in the working tree gains a CR.

Do not "verify" line endings with `grep -c $'\r'` in Git Bash - it reports
false positives. Count bytes instead:
`python -c "print(open(f,'rb').read().count(bytes([13])))"`.

**Passing `pytest` / `npm test` does not mean the app runs.** The suites never
build the image, so a fully green run says nothing about whether the container
starts. After touching the `Dockerfile`, `deploy/`, or anything the container
executes, build and boot it before calling the work done — offline, with no
mounts, so it can neither scrape nor touch a real DB:

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose build
docker run -d --name trackaroo-verify --network none -e SKIP_PIPELINE=1 trackaroo:latest
for i in $(seq 1 40); do s=$(docker inspect -f '{{.State.Health.Status}}' trackaroo-verify); [ "$s" = healthy ] && break; sleep 10; done; echo "$s"
docker exec trackaroo-verify node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>r.text()).then(console.log)"
docker rm -f trackaroo-verify
```
