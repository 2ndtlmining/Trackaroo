# Project Status

**Last updated:** 2026-08-25

**Current phase:** Phase 5 — frontend/UX improvements, pipeline robustness, and
backup integrity.

> **History note (23-Aug-2026):** this file used to open with a chain of nested
> "Prior update" paragraphs — one of them a single 7,685-character line — that
> had grown to 106 KB and was effectively unreadable. The full original is kept
> verbatim at [`docs/archive/STATUS-history-to-2026-08-21.md`](docs/archive/STATUS-history-to-2026-08-21.md).
> Everything below is the structured content, unchanged. Add new work to
> **Recent changes** as a dated bullet — do not start another nested chain.

## Recent changes

- **2026-08-25** — **`/deals` shipped** — stage 2 of
  [`docs/superpowers/specs/2026-08-23-price-first-ia-design.md`](docs/superpowers/specs/2026-08-23-price-first-ia-design.md)
  (§4), per the plan in
  [`docs/superpowers/plans/2026-08-25-deals-page.md`](docs/superpowers/plans/2026-08-25-deals-page.md).
  Two deliberately separate sections — **Below 30-day average** (ranked by
  depth, `(avg30 − price) / avg30`, deepest first) and **At or near all-time
  low** (anchored `#all-time-low`, "near" = within 2%). They stay apart because
  they answer different questions and the second is the stronger claim;
  blending them would rebuild the composite `deal_score` declined on 17-Aug
  (see the new decision-log entry in `docs/ARCHITECTURE.md` Part 3). Both
  sections require `avg30Points >= MIN_HISTORY_POINTS`. New
  `getDealCandidates` query (one row per product: cheapest in-stock listing
  today + all-time low + 30-day average); all ranking logic pure in
  `web/src/lib/deals.ts`. Reuses stage-1 `OfferRow` (two additive optional
  props) and `FacetChips`, whose chips here are URL-driven server-side rather
  than client-side. **No nav link yet** — §10 sequences nav last, so `/deals`
  is URL-only until stage 4. Verified live against the real DB: 44 eligible
  products, 10 below average. Regression: pytest **611** / svelte-check 0 /
  vitest **330** / e2e **59** / build green.

- **2026-08-25** — Daily run recovered manually (the container was not running,
  so the 04:00 schedule never fired). 373 snapshots ingested for 25-Aug:
  Scorptec 36 CPU / 283 GPU, PCCG 21 CPU / **33 GPU**. PCCG rate-limited its GPU
  pass hard; a gentler-paced retry (`TRACKAROO_BATCH_SIZE=8`,
  `TRACKAROO_BATCH_DELAY=3.0`) matched zero and tripped the 429 circuit breaker
  (4h cooldown). `snapshot_io` **refused to overwrite** the good 33-product file
  with the empty result and parked it at
  `gpu_pccg_25_August_2026.partial-060913.json` — the backup guarantee working
  as designed. PCCG GPU for 25-Aug is therefore short ~67 listings.
  Branch `hardening/json-backup-docker-ux` merged to `main`. Full regression:
  pytest **611** / svelte-check 0 / vitest **301** / e2e **54**.

- **2026-08-24** — Product page rebuilt around a flat, cheapest-first offer list
  (`OfferList`) replacing the brand→retailer accordion, plus a price-led
  headline with an all-time range bar. In-stock-only is the default and the
  list caps at 8 offers with a "Show all N" expander. Implements stage 1 of
  `docs/superpowers/specs/2026-08-23-price-first-ia-design.md`; E2E coverage
  (facet chips, expander, in-stock filter, chart toggle) added in
  `web/e2e/app.spec.ts`.

### 23-Aug-2026 — JSON backup integrity, missed-day recovery, Docker persistence

**Data recovered.** 23-Aug had no data at all; both retailers were scraped and
441 snapshots ingested (321 Scorptec + 120 PCCG). PCCG needed a second attempt —
the first tripped its 429 circuit breaker.

**The JSON backup was not a backup.** Both scrapers wrote snapshots with a plain
`open(path, "w")`: non-atomic, and unconditional. A rate-limited PCCG re-run that
matched zero products had overwritten the complete file taken earlier the same
day. The DB survived (ingest is idempotent per `(listing, date)`); the JSON did
not. **165 snapshots existed in the DB alone** (54 on 19-Aug, 111 on 21-Aug) and
could not have been rebuilt from `data/`.

- New `scraper/snapshot_io.py` — `save_snapshot()` writes via a temp file plus
  `os.replace()` (atomic), and **refuses to replace a snapshot with a smaller
  one**, parking the weaker result in a `.partial-HHMMSS.json` sidecar. Both
  scrapers now share it, replacing two duplicated write blocks.
- New `export_snapshots.py` — rebuilds `data/*.json` from the DB in the exact
  scraper envelope. `--repair` recovered all 165 orphaned snapshots.
- `run_daily.py` mirrors the DB back out to JSON after every ingest, so the
  invariant *JSON can rebuild the DB* now holds continuously.
- Verified by rebuilding a scratch DB from `data/` alone: it matches the live DB
  except for 70 snapshots attached to `status='stale'` duplicate listing rows,
  none of which is the only record for its SKU+date — the rebuild is *more*
  correct, not lossy.

**Health checks.** `check_price_anomalies` and `check_spec_coverage` existed but
were never wired into `run_daily.py`; they are now. Three new checks:
`check_json_db_parity` (can JSON still rebuild this day?), `check_missing_days`
(was a run skipped?), `check_scraper_cooldown` (is a retailer deliberately
paused, and until when?). Missing days now raise a Discord pipeline alert.

**Ingest resilience.** A malformed record used to propagate out of
`ingest_file` and abort the whole file; per-product handling now catches
`KeyError`/`TypeError`/`ValueError` too, counts the row, and continues.

**Logging.** Every entry point logged to stdout only, so a native run left no
trace once the terminal closed. `config.setup_logging()` adds a date-stamped
`logs/trackaroo-YYYY-MM-DD.log` (plain append handler — the scrapers are
separate processes sharing the file, so rotation would corrupt it) with
`TRACKAROO_LOG_KEEP_DAYS` pruning.

**Docker: single image, plain `docker run`, data mapped.** The running
container had **no volume mounted** — everything it scraped lived in its
writable layer and died with `docker rm` — and ran on UTC, stamping snapshots a
day early. `docker-compose.yml` has been **removed**; the supported way to run
Trackaroo is now one `docker run` against the all-in-one image, mapping
`./db → /app/db` and `./data → /app/data` so the container and native runs
share one DB and one set of JSON snapshots. The image installs `tzdata` and
pins `TZ=Australia/Melbourne`. Verified live: container reports AEST,
`date.today()` matches the host, both mounts resolve to the repo directories,
SQLite reads *and writes* work over the Windows bind mount in WAL mode, and the
data survived a full `stop`/`rm`/rebuild cycle. Both entrypoints replaced the
drifting `sleep ${RUN_INTERVAL_HOURS}h` loop with a wall-clock `RUN_AT_HOUR`
(default 04:00) plus a boot catch-up run when today has no data — restarts can
no longer shift or skip a day. The committed Algolia key defaults went with the
compose file.

**Dashboard UX.** Six gaps closed, highest-value first:

- **Stale-data banner** — every figure on the dashboard reads as current whether
  the pipeline ran this morning or stopped a week ago. A banner now states the
  gap ("Data is 4 days behind — most recent snapshot is 19 Aug 2026"), muted at
  one day (normal before the morning run) and error-toned from two. A separate
  message covers an empty DB.
- **Error pages** — there was no `+error.svelte` and no `hooks.server.ts`, so a
  404, a malformed `/compare` URL, or a missing `trackaroo.db` rendered
  SvelteKit's unstyled default with no way back. Both added; the handler logs
  the real error server-side and maps SQLite failures to actionable messages
  ("run `python migrate.py`").
- **Alert form** — invalid input called `error(400)`, which replaced the whole
  product page. It now returns `fail(400, …)` and renders the message inline,
  preserving what was typed.
- **Navigation feedback** — every filter/sort/window control is a server
  round-trip with no indicator. A top progress bar driven by `$navigating`
  fills the gap (and respects `prefers-reduced-motion`).
- **Mobile** — the app had 7 breakpoint utilities in total and every table fell
  back to horizontal scroll, hiding price and change behind a swipe. Both
  `LatestListingTable` (dashboard + product cards) and `/movers` now render a
  card per row below `md`, with the table kept for `md` and up.
- **Accessibility** — skip-to-content link; a global `:focus-visible` ring
  (several inputs used `focus:outline-none` with only a 1px border change);
  focus trap and focus restore in the command palette, which previously let Tab
  walk out of the open modal and dropped focus to `<body>` on close; `aria-live`
  result counts on the dashboard and `/products`, so a filter change is
  announced rather than silently re-rendering.

**Repo cleanup.** Root markdown went from 11 files to 4. `SPEC.md`,
`SCOPE_RULES.md` and `DECISIONS.md` merged verbatim into
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) as Parts 1–3; implemented plans
archived to `docs/archive/`; the unbuilt RAM plan moved to
`docs/proposals/`. Removed orphaned bytecode, `web/webdev.log`, three empty
directories, and six unused frontend exports (`closeDb`, `closeWriteDb`,
`formatAxisLabel`, `labelFor`, `getPriceExtremes`, plus an unused import);
`ThemeToggle.svelte` now uses the shared `toggleTheme()` it had been
duplicating. New `CLAUDE.md` carries the agent conventions.

**Regression:** pytest **611** (was 566; +45) / svelte-check 0 errors /
vitest **239** (234 minus 6 for the deleted functions, plus 11 for staleness) /
Playwright e2e **52** / production build green.

---

**Git repo:** https://github.com/2ndtlmining/Trackaroo
**Current phase:** Phase 5 — frontend/UX improvements program + PCCG reliability (see Active Issues below).

## Changelog

Completed work, newest first. Each entry's full write-up — problem, fix,
files touched, live verification — is preserved verbatim in
[`docs/archive/STATUS-history-to-2026-08-21.md`](docs/archive/STATUS-history-to-2026-08-21.md).
This table replaced ~65 KB of inlined detail on 23-Aug-2026.

| Date | Status | Work |
|---|---|---|
| 23-Aug-2026 | done | JSON backup integrity, missed-day recovery, Docker persistence + timezone (see Recent changes above) |
| 21-Aug-2026 | done | Discord digest consolidated to one webhook |
| 21-Aug-2026 | done | Scorptec duplicate listings + missing OOS snapshots |
| 21-Aug-2026 | done | Backup on every run |
| 20-Aug-2026 | done | Delisted-listing detection — "why is this still in stock?" |
| 20-Aug-2026 | done | Price-drop & restock alerts — "tell me when to buy" |
| 20-Aug-2026 | done | UX quick wins — "since tracked" chips + deal badges |
| 20-Aug-2026 | done | Robustness pass — pipeline alert webhook, PCCG backoff cap+jitter, synthetic e2e seed, scorptec variant-only reporting |
| 20-Aug-2026 | done | Phase 5 frontend polish — friendly generation names + chart loading skeleton + brand-group motion |
| — | done | Brand icons + UI polish + Discord digest (19-Aug-2026, per `TRACKAROO_POLISH_AND_NOTIFICATIONS.md`) |
| — | done | Round-3 enhancements — snapshot counts, sortable columns, chart reactivity, name casing (18-Aug-2026, per `TRACKAROO_ENHANCEMENTS_ROUND3.md`) |
| 18-Aug-2026 | done | TechPowerUp-grade spec enrichment |
| — | done | Trend sparklines on unexpanded product cards (18-Aug-2026, card-grid idea) |
| — | done | Sparklines on dashboard + movers; troubleshooting scaffolding removed (18-Aug-2026, UI follow-up) |
| — | done | Command palette + inline sparkline trend column (18-Aug-2026, UI additions per `TRACKAROO_UI_ADDITIONS.md`) |
| 18-Aug-2026 | done | Bug fixes from `TRACKAROO_BUGS_AND_TROUBLESHOOTING.md` + temporary troubleshooting view |
| 17-Aug-2026 | done | Weekly spec sync scheduling |
| 17-Aug-2026 | done | Hardcoded-values pass — tuning constants moved to config |
| 17-Aug-2026 | done | Regression coverage pass |
| 17-Aug-2026 | done | Docs-hygiene pass |
| 16-Aug-2026 | done | PCCG reliability — recurring 429 hard-rate-limit fixed |
| 16-Aug-2026 | done | Real spec data (CPU + GPU) per `IMPROVEMENT_16_Aug_V1.md` §3–§9 |
| 17-Aug-2026 | done | Feature suggestions §2–§4 + repo cleanup §6 |
| 15-Aug-2026 | **in progress** | Frontend & UX Improvement Program |
| 15-Aug-2026 | done | Phase 4 Deployment — single Docker image |
| 15-Aug-2026 | done | Frontend M4–M5 |
| — | done | Frontend M0–M3 (14–15 Aug-2026) |
| 13-Aug-2026 | done | PCCG Stock Status Hardening |
| 13-Aug-2026 | done | Frontend-Readiness Hardening |
| — | done | New data point 13-Aug (5 days of history) |
| 12-Aug-2026 | done | Code Quality & Critical Bug Fixes |
| 11-Aug-2026 | done | Multi-Variant Tracking |
| 12-Aug-2026 | done | PCCG Scraper — Live & Verified |

## What exists right now

- Project README (`README.md`) — objectives, what's built, quick start, repo layout
- Full specification (`SPEC.md`) — purpose, architecture, data model, scraping approach, frontend scope, risks, build phases
- Product scope rules (`SCOPE_RULES.md`) — 2-generation tracking limit, defined per product line
- Decision log (`DECISIONS.md`) — rationale for stack choices and key policies
- SQLite schema (`db/schema.sql`) — `products` / `retailer_listings` (with `variant_name`) / `price_snapshots` with triggers
- Watchlist (`db/watchlist.csv`) — 100 products (53 CPUs, 47 GPUs) across 3 generations per SCOPE_RULES.md
- Shared watchlist loader (`db/watchlist.py`) — parse_spec + load_watchlist + load_watchlist_products
- Scorptec scraper (`scraper/scorptec.py`) — working, multi-variant, outputs separate CPU/GPU JSON files (renamed from `fetch_test.py` 17-Aug per feature-suggestions §6.3)
- PCCG scraper (`scraper/pccg.py`) — working, multi-variant, verified live (Algolia API, no Playwright)
- `migrate.py` — schema migration tool for historical upgrades only (adds `variant_name` column + WAL to pre-12-Aug DBs)
- `seed.py` — populates SQLite `products` table from `db/watchlist.csv`
- `ingest.py` — reads scraped JSON files and writes `retailer_listings` + `price_snapshots` into the DB
- `query.py` — query tool with three modes: latest prices, trends, biggest movers (shows variant names)
- `health_checks.py` — validates scraped JSON output and DB state (multi-variant thresholds; variant-count anomaly detection)
- `run_daily.py` — one-command daily runner: scrapes both retailers → validates → ingests → validates DB → posts the Discord digest **and evaluates price alerts** when all health checks pass (`--no-notify` opts out; dry-run / scrape-only / no-health skip it automatically), and runs the **delisted-listing check** after a successful Scorptec scrape (best-effort)
- `notify_discord.py` — **new:** daily Discord digest of the biggest CPU/GPU moves (top 3 up/down per category, per-listing prev-snapshot pairing, dashboard-colour embeds, retailer links; `DISCORD_WEBHOOK_URL` for the CPU+GPU channel, optional `TRACKAROO_PUBLIC_BASE_URL`; `--dry-run` / `--test`; never raises)
- `check_alerts.py` — **new:** price-drop & restock alerts — evaluates `price_alerts` against the two latest snapshots per listing (cheapest in-stock ≤ target with further-drop re-fire; out→in restock with a 24h cooldown; price precedence; cooldowns advance only after successful delivery) and delivers best-effort via stdlib to Discord/SMTP/generic-webhook (`TRACKAROO_DISCORD_WEBHOOK_URL` / `TRACKAROO_SMTP_*` / `TRACKAROO_ALERT_WEBHOOK_URL`); `--db` / `--dry-run`; never raises
- `check_delisted.py` — **new:** delisted-listing detection — re-fetches the product page of active Scorptec listings missing from today's grid scrape and marks them `delisted` on a positive 404/410 or "No Longer Available" marker (unknown/unverifiable pages left untouched); retries on throttling; per-run fetch cap + dedicated inter-fetch delay; `--db` / `--dry-run` / `--all`
- `sync_specs.py` — weekly spec sync: fetches GPU/Intel/AMD spec datasets → matches to `products` → upserts `specs` rows; `--category` / `--dry-run` / `--report-only`; report to `data/spec_sync_report.json`
- `backfill_msrp.py` — **new:** one-off backfill of `launch_msrp_usd` from the curated `db/launch_msrp.json` (shipped with its test suite; re-runnable/upserting)
- `spec_matching.py` — name normalization + product→spec-dataset matching (exact normalized match, no guessing)
- `backup_db.py` — standalone DB backup with retention pruning
- `requirements.txt` — pinned dependencies
- `Dockerfile` — **single all-in-one image** (Python pipeline + dashboard); `docker run -p 3000:3000 -v trackaroo-data:/data trackaroo`
- `docker-compose.yml` — **removed 23-Aug-2026**; the app runs as a single image via `docker run`
- `deploy/entrypoint-single.sh` — all-in-one entrypoint (seed → dashboard → pipeline scheduler + weekly spec sync); `entrypoint.sh` for pipeline-only
- `.dockerignore` — excludes regenerable artifacts and the web build context
- `unit_testing/` — **566 regression tests** across 22 modules (seed, matching, schema, ingestion, scraper, migrate, PCCG reliability, daily runner, health checks, query, concurrency/WAL, E2E pipeline, performance, CLI smoke tests, backup, config, specs schema, specs matching, sync_specs, notify_discord, check_alerts, check_delisted; `test_resync.py` removed 17-Aug with its one-off script)
- RAM tracking scope (`RAM_SCOPE.md`) — plan for adding DDR4/DDR5 RAM price tracking
- Historical data: Scorptec + PCCG snapshots for 09-Aug through 19-Aug (16-Aug PCCG missing — rate-limited; 18-Aug full: both retailers, 306 snapshots ingested; 19-Aug: 2837 snapshots / 345 listings / 306 today rows)
- `.env.example` — committed template documenting Algolia env vars (and `.gitignore` negation)
- `PHASE3_PLAN.md` — executable Phase 3 frontend handoff plan (locked decisions, data model facts, M0–M5 steps)
- `web/` — Phase 3 frontend (SvelteKit + TS + Tailwind v4 + adapter-node):
  - `src/app.css` + `src/lib/theme.ts` — token system, dark/light, theme toggle
  - `src/lib/components/` — `Badge`, `StatTile`, `PriceChange`, `Chip`, `Filters`, `Header` (incl. Ctrl+K search trigger), `LatestListingTable` (also renders `compact` inside product cards), `PriceChart` (uPlot; low/high band + cheapest-in-stock + toggleable listing overlays), `SpecPanel` (product-page spec panel), `CheapestCarousel` (dashboard cheapest-deals, GPU/CPU toggle, 90d-low badge), `ProductCard` (products-page card grid, compare checkbox, per-card trend sparkline, brand icon), `BrandGroupedListings` (product-page grouped listings panel), `CommandPalette` (Ctrl+K quick search), `Sparkline` (trend line: table column + card sparkline), `BrandIcon` (AMD/NVIDIA/Intel marks), `PriceAlerts` (product-page price-drop/restock alert panel), `+layout.svelte`
  - `src/lib/` — `branding.ts` (client-safe AIB brand derivation), `listingsPanel.ts` (pure grouped-listings logic), `formats.ts`/`change.ts`
  - `src/lib/server/` — `db.ts` (better-sqlite3 read-only singleton + write-capable `getWriteDb()` for alert actions), `repos.ts` (incl. `groupListingsByProduct`, `getPriceBand`, `getComparisonData`, `getPriceExtremes`, `upsertAlert` / `deleteAlert` / `getProductAlerts`)
  - Routes — `/deals` (below-30d-average + at/near-all-time-low sections, URL-driven chip facets), `/` dashboard (table with 7-day trend sparklines), `/products` (card grid with per-card trend sparklines + expandable variant listings with inline 7-day trend sparklines + compare selection), `/compare` (side-by-side specs + prices), `/movers` (dense table with window-matched trend sparklines), `/product/[id]` with URL-driven filters; global command palette (Ctrl/Cmd+K) on every page
  - `test/` — vitest, **330 tests** across 14 suites (run `npm test` for the current breakdown)
  - `e2e/` — Playwright: 54 tests (app.spec.ts + seed.mjs deterministic DB — real data, or synthetic via `TRACKAROO_DATA_DIR` empty dir; incl. spec-panel, grouped-listings panel, compare flow/validation, 90d-low badges + chips, all-time low/high + 30d-avg chips, data-driven Deal-badge test, dashboard + movers + products trend sparklines (card + expanded table), command palette open/navigate/escape/quick-compare/snapshot-badge, column-sort tri-state on dashboard + movers, "Show on chart" toggle + chart navigation, products card-grid sparkline, brand icons, product-page freshness, price-alert arm + delete from the product page, delisted-listing "Delisted" badge (no stale in-stock price)) — **54 tests**

## What's verified

- **Backend:** 566 tests pass — seed, matching, schema/triggers, ingestion (incl. URL-key dedup), scrapers (incl. OOS-variant saving), DB migration (incl. price_alerts, retailer_sku backfill, duplicate merge), PCCG reliability (incl. backoff cap+jitter), daily runner (+ digest gating + pipeline alert + alerts-step resilience), health checks, query, concurrent WAL access, E2E pipeline, query performance, CLI entry points, backup, config, specs schema/matching/sync, notify_discord (incl. send_alert), check_alerts (evaluation matrix, message, delivery stubs, CLI), check_delisted (page classification, fetch retries, selection/exclusions, marking)
- **Stock status:** PCCG 13-Aug corrected from 123 all-in_stock to 86 in_stock + 35 out_of_stock + 2 preorder; resync verified idempotent (one-off `resync_stock_status.py` tool since removed — bug fixed at the source)
- **Concurrency:** test proving readers hit no lock errors while a writer commits under WAL (stable 10/10)
- **Performance:** `show_latest_prices` 60ms / `show_biggest_movers` 7ms on ~10k synthetic snapshots; history query provably index-backed
- **Scorptec:** 192 variants matched on 13-Aug (multi-variant)
- **PCCG:** 123 variants matched on 13-Aug (multi-variant, verified live)
- **Health checks:** green on the real DB — JSON validation, freshness, match-count anomalies (variant-based), price anomalies (active; 310 of 333 listings now past the 3-point floor), and the new spec coverage/staleness checks (`spec_coverage OK 95/100`, `spec_staleness OK 0 days`)
- **Schema:** `variant_name` column present; `last_snapshot_at` auto-maintained by triggers; DB in WAL mode
- **Code quality:** all modules type-hinted + logged; shared watchlist module deduplicates logic; secrets moved to env vars
- **Spec sync:** live-fetch coverage verified against the real watchlist — Intel 25/25, AMD 24/28 (4 OEM-only SKUs have no public page), GPU 46/47 (RX 9070 XTX absent from the dataset); upsert conflict/unmatched/vanished-row behaviour locked in by tests; price pipeline untouched (§2 priority rule)
- **Spec panel:** renders below the price chart on `/product/[id]` (E2E bounding-box assertion), hidden when a product has no spec row; fetched via one extra `SELECT` in the detail load only — never joined into list/index queries
- **Frontend:** `svelte-check` 0 errors; vitest **330 passing**; Playwright e2e **59 passing** (real + synthetic seeds); production build green; live `adapter-node` smoke test of all routes against the real DB (dashboard/products/movers/product 200s, unknown product 404, bad window param falls back)
- **Docker:** single all-in-one image built and booted — DB seeded, both scrapers OK, 315 listings ingested, backup created, dashboard HTTP 200 with live stats
- **Feature suggestions §2–§4:** band chart + brand-grouped listings on `/product/[id]`, `/compare?ids=` (2–4 same-category products), `90d low`/`90d high` on product page + dashboard cards — regression green after each milestone
- **Troubleshooting:** the temporary `/troubleshooting` view + `/api/health` JSON built on 18-Aug were **removed** the same day once the PCCG cooldown behaviour and compare/specs issues were confirmed settled — `getCoverageSummary`, its routes, and their tests are gone (see the UI follow-up entry)
- **Regression:** backend **611** passing (pytest); frontend **330** passing (vitest) + 59 e2e (Playwright, real + synthetic)
- **Command palette + sparklines (18-Aug):** Ctrl/Cmd+K palette searches the tracked catalog from any page and Enter-navigates to a product (quick "Compare A vs B" when exactly two match); `/products` card tables, the `/` dashboard table, and the `/movers` table all show per-listing trend sparklines (up=red / down=green, dash when <2 points), and each unexpanded `/products` card shows its cheapest-in-stock trend line — regression green after the batch
- **Round-3 enhancements (18-Aug):** palette results show per-product snapshot counts; dashboard + movers tables have tri-state sortable column headers; the product-page price chart is reactive (re-creates uPlot on prop change — fixes stale chart on navigation AND the inert "Show on chart" toggle); variant names are display-cased consistently (`titleCase()`) at every render site while the DB stays raw; specs confirmed healthy (95 rows / 0 orphans / 95 covered) — the empty-look was a stale Docker DB. Regression: pytest 391 / svelte-check 0 / vitest 187 / e2e 46 / build green.
- **Brand icons + UI polish + Discord digest (19-Aug):** simple-icons AMD/NVIDIA/Intel marks in header, cards, compare + footer (tree-shaking verified); product-page "Updated X ago" freshness, unified card heights + empty-state panels; `notify_discord.py` digest gated on healthy runs (dry-run printed the real digest against live data — 3 moves: RTX 5070 Ti +10.2%, RX 9070 +5.6%, RTX 5070 +4.4%). Regression: pytest 461 / svelte-check 0 / vitest 204 / e2e 48 / build green.
- **Price-drop & restock alerts (20-Aug):** `price_alerts` table + idempotent migration; `check_alerts.py` (price-drop with further-drop re-fire, restock with 24h cooldown, price precedence, cooldowns advance only on successful delivery, stdlib Discord/SMTP/webhook delivery — never raises) wired into `run_daily.py` after a healthy ingest; product-page "Price alerts" panel (arm/list/delete) via a dedicated write DB connection. Regression: pytest **522** / svelte-check 0 / vitest **231** / e2e **51** / build green.
- **Delisted-listing detection (20-Aug):** `check_delisted.py` re-fetches active Scorptec listings missing from today's grid scrape and marks them `delisted` on a positive 404/410 or "No Longer Available" marker (unknown pages left untouched; retries on CDN throttling; per-run fetch cap + 1.5s inter-fetch delay); wired into `run_daily.py` after a successful Scorptec scrape (best-effort). Dashboard: "Delisted" badge instead of price + stock, excluded from in-stock count and group price range. Live run marked 5 delistings (incl. the 119183 repro). Regression: pytest **545** / svelte-check 0 / vitest **234** / e2e **52** / build green.

## What's NOT done yet

1. **Hardcoded values review** — Scan for magic numbers, hardcoded thresholds, paths that should be config-driven (e.g., health check limits, BATCH_SIZE, timeouts). Lower priority; can be done as a separate pass.
2. **Frontend (Phase 3) — complete.** M0–M5 done: views, polish/verify, units + e2e. Remaining: final visual QA eyeball (any new filters/hardening belong to Phase 4).
3. **Detailed deployment** — done: single Docker image + compose split verified. Optional extras for later: reverse proxy (Caddy/nginx/Traefik) for TLS, host-cron option docs already in DEPLOYMENT.md.
4. **Hardening (Phase 4, remaining)** — reverse proxy/TLS, Prometheus-style monitoring, alerting on pipeline failure (current: exit codes + logs).
5. **Price anomaly detection maturity** — a single-day jump only trips the 3σ check once a listing has ~10+ history points (max deviation ≈ √N); most listings still below that depth. See DECISIONS.md.
6. **RAM tracking (RAM_SCOPE.md)** — planned but not started; not required for Phase 3/4

## Next up (planned 18-Aug — picked up tomorrow)

### ✅ Price-drop & restock alerts (Discord-first) — done 20-Aug
Shipped per the agreed design — see the "COMPLETE: Price-drop & restock alerts" entry in Active Issues. The daily Discord digest (`notify_discord.py`) from the polish/notifications batch shipped alongside it on 19-Aug.

### Backlog (UX, ranked by value/effort)
1. ✅ **Products-page filters** — done (pre-existing): `/products` grid already has category/retailer/brand/generation selects + debounced text search + in-stock toggle + sort (see `web/src/lib/components/Filters.svelte`).
2. ✅ **"Since tracked" stat chips** — done 20-Aug: product page shows **All-time low / All-time high** (the band was always unwindowed) + a **30d avg** chip (mean of per-day cheapest in-stock over the trailing 30 days, ≥3 days of history).
3. ✅ **Deal highlight** — done 20-Aug: green **Deal** badge on `/products` cards + the dashboard carousel when the cheapest in-stock price is below the 30-day average (binary, ≥3 days of history).
4. **Mobile responsiveness pass** — card grid / compare / chart on phone viewports (~few hours).
5. **RSS feed of biggest movers** (~1 h).

## Next concrete steps

1. **Accumulate more scrape data** — run daily scrapes to build historical depth (now 10 days, 09–18 Aug; anomaly detection sensitivity improves with each new ≥10-point listing)
2. **Reverse proxy + TLS** — put the dashboard behind Caddy/nginx/Traefik if internet-facing (docs in DEPLOYMENT.md)
3. **Monitoring/alerting** — watch pipeline success via exit codes / logs (health checks already log "DB health: all N checks passed")
4. ✅ **Weekly spec sync cadence** — done 17-Aug: `deploy/entrypoint-single.sh` now runs `sync_specs.py` once a week in-container at `SPEC_SYNC_DOW` @ `SPEC_SYNC_HOUR` (default Sunday 03:00, clear of the daily price run); DEPLOYMENT.md/README/AGENTS updated
5. ✅ **Bug fixes + troubleshooting view** — done 18-Aug: `getComparisonData` per-listing latest fix, category-aware compare rows; the temporary `/troubleshooting` + `/api/health` diagnostics were added and then **deleted** once the PCCG cooldown and compare/specs issues were confirmed settled
6. ✅ **Command palette + sparkline trend column** — done 18-Aug: Ctrl/Cmd+K palette (`getProductIndex` in the root layout, client-side filter, quick compare row), 7-day trend sparklines on products rows (`getSparklines` + `Sparkline.svelte` + Trend column); extended to the dashboard + movers tables the same session, then to the unexpanded product cards (`getProductSparklines` — cheapest in-stock per day per product)
7. ✅ **Round-3 enhancements** — done 18-Aug per `TRACKAROO_ENHANCEMENTS_ROUND3.md`: palette snapshot counts, sortable dashboard/movers columns, PriceChart reactivity (chart rebuild + "Show on chart" fix), `titleCase()` name casing; specs §3 verified healthy (no change). Full regression green (391/187/46).
8. ✅ **Brand icons + UI polish + Discord digest** — done 19-Aug per `TRACKAROO_POLISH_AND_NOTIFICATIONS.md`: simple-icons brand marks (header/cards/compare/footer), product-page freshness + card-height/empty-state polish, and the health-gated `notify_discord.py` digest (`DISCORD_WEBHOOK_URL`, `--dry-run`/`--test`, `run_daily --no-notify`). Full regression green (461/204/48).
9. ✅ **Robustness pass + UX quick wins** — done 20-Aug: pipeline alert webhook (`DISCORD_WEBHOOK_ALERT` + `send_alert`), PCCG backoff cap+jitter, scorptec variant-only unmatched reporting, synthetic e2e seed (`TRACKAROO_DATA_DIR` empty dir); friendly generation names (`tiers.ts`), chart loading skeleton + brand-group expand/collapse motion; product-page all-time low/high + 30d-avg chips, and binary **Deal** badges on `/products` cards + the dashboard carousel (below-30d-avg, ≥3 days of history). Fixed the `MIN_HISTORY_POINTS` server-import hydration bug (moved to shared `web/src/lib/constants.ts`). Full regression green (479/226/50, real + synthetic e2e).
10. ✅ **Price-drop & restock alerts** — done 20-Aug: `price_alerts` table (+ idempotent `migrate.py` migration), `check_alerts.py` (price-drop / restock / 24h cooldown, stdlib Discord/SMTP/webhook delivery, never raises) wired into `run_daily.py` after a healthy ingest, product-page "Price alerts" panel (arm/list/delete) via a dedicated write DB connection, env vars in `.env.example` / `docker-compose.yml` / `deploy/entrypoint-single.sh`. Full regression green (522/231/51).
11. ✅ **Delisted-listing detection** — done 20-Aug: `check_delisted.py` re-fetches active Scorptec listings missing from today's grid scrape and marks them `delisted` on a positive 404/410 or "No Longer Available" marker (unknown pages left untouched; retries on CDN throttling; `TRACKAROO_SCORPTEC_DELIST_CHECK_MAX` fetch cap + `TRACKAROO_SCORPTEC_DELIST_PAGE_DELAY` 1.5s inter-fetch delay); wired into `run_daily.py` after a successful Scorptec scrape (best-effort); dashboard "Delisted" badge + exclusion from in-stock count / group price range. Live run marked 5 delistings (incl. the 119183 repro). Full regression green (545/234/52).

## Regression test count

Current, as of 25-Aug-2026:

| Suite | Tests | Command (from) |
|---|---|---|
| Backend (pytest) | **611** | `python -m pytest -q` (repo root) |
| Frontend unit (vitest) | **330** | `npm test` (`web/`) |
| Frontend e2e (Playwright) | **59** | `npm run test:e2e` (`web/`) |
| Type + Svelte check | 0 errors | `npm run check` (`web/`) |

The per-module breakdown that used to live here went stale every session;
`pytest -q` and `vitest` are the source of truth. The 21-Aug snapshot of it
is preserved in
[`docs/archive/STATUS-history-to-2026-08-21.md`](docs/archive/STATUS-history-to-2026-08-21.md).

Backend suites added 23-Aug: `test_snapshot_io.py` (14), 
`test_export_snapshots.py` (16), `test_health_checks_backup.py` (15).

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in `DECISIONS.md` if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.