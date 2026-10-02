# Project Status

**Last updated:** 2026-10-02

**Current phase:** Phase 5 — frontend/UX improvements, pipeline robustness, and
backup integrity.

> **History note (23-Aug-2026):** this file used to open with a chain of nested
> "Prior update" paragraphs — one of them a single 7,685-character line — that
> had grown to 106 KB and was effectively unreadable. The full original is kept
> verbatim at [`docs/archive/STATUS-history-to-2026-08-21.md`](docs/archive/STATUS-history-to-2026-08-21.md).
> Everything below is the structured content, unchanged. Add new work to
> **Recent changes** as a dated bullet — do not start another nested chain.

## Recent changes

- **2026-10-02 — #30 web code health (refactor) on branch
  `refactor/2026-10-02-web-code-health`; NOT merged, NOT deployed.** The 1,416-line
  `web/src/lib/server/repos.ts` is split into `web/src/lib/server/queries/*`
  (repos.ts stays as the barrel) with DTO types in `$lib/models`; client code
  never imports `$lib/server` (`test/boundaries.test.ts`, `test/sql.test.ts`
  are permanent). No data or schema change; no visible change beyond one planned
  wording change. Proven by a temporary oracle (legacy copy of repos.ts):
  result equivalence, 99 tests green on seeded, seeded-enriched and a
  temp copy of the real DB (`test:equiv-real`), plus SQL-text identity. The
  oracle is removed in this branch (it would rot); the proof is in the PR.
  Timings (warm, temp DB copy, wire bytes / ttfb) before -> after: `/` 7894 ->
  7900 / 4.1ms -> 2.6ms; `/deals` 8276 -> 8273 / 4.2 -> 2.8ms; `/movers?window=7d`
  11925 -> 11983 / 7.6 -> 5.4ms; `/products?category=gpu` 8318 -> 8324 / 3.9 ->
  2.8ms; `/product/1` 8243 -> 8241 / 5.7 -> 4.7ms. No route slower. Pre-existing
  finding, kept as is: `getCheapestPerModel` uses a 31/91-day window; no route
  calls it. Counts: pytest 1182, vitest 823, Playwright 119, svelte-check 0/0.
- **2026-10-02 — #16 new-part discovery BUILT on branch
  `feat/2026-10-02-discovery`; NOT merged, NOT deployed.** Scrapers write full
  catalogues to `data/catalogue/` (`scraper/catalogue_io.py`, 30 days);
  `discover.py` (after ingest, best-effort) fills `discovered_parts`,
  `discovery_conflicts` and `discovery_runs`, and posts new parts once to
  Discord ("New parts at retailers"); `/discover` lets the owner Track, Ignore,
  Undo and Un-ignore; `check_discovery` is WARNING-only. Guide: README
  "Discovering and adding new parts". Counts after Task 8: pytest 1168, vitest
  806, Playwright 119, svelte-check 0/0. **To deploy:** merge, then
  `deploy/redeploy.sh` on the host outside 04:00-09:59 Melbourne. **Expect on
  the first prod run:** the parked "Unmatched" parts (5900XT, 5600GT, 7700X3D
  ...) appear as untracked parts, and possibly a short burst of conflicts
  until `repair_listings.py` has been applied. **After deploy check:**
  `/discover` loads, its "last checked" time is today, `docker compose logs
  trackaroo | grep -i discovery` shows a summary line, `data/catalogue/` has
  that day's files, and one Discord "New parts at retailers" message arrived.
  Track/Ignore buttons have no login (like alerts).
- **2026-10-02 — Phase 6 DONE: prod runs docker compose, build `905d28c`,
  verified. Resume here.** PRs #42 (robustness), #43 (UX), #44 (redeploy)
  merged; #43/#44 were stacked and merged into their base branches, so #45
  (`feat/2026-09-30-ux` → `main`) landed them. The first GitHub CI run failed on
  two `TestScorptecDataQuality` tests that need the gitignored `data/`; they
  now skip when it is empty (`5204243`). CI is green on `main`.
  Host migration (runbook Path A) on `giel@dockerhost`: `.env.pre-compose`
  saved, `ALGOLIA_*` commented out, `db/pre-compose.db` + a tarball
  (`~/trackaroo-pre-compose-2026-10-02.tgz`, also copied to the owner's PC),
  old container kept as `trackaroo-old` (Exited) and image
  `trackaroo:pre-compose` until ~9-Oct. Ran `FORCE=1 SKIP_BACKUP=1
  deploy/redeploy.sh` at 05:15 AEST, inside the window but after confirming
  that morning's run had finished (04:37). Boot catch-up scraped **Umart for
  the first time** (ok, 161 matched). Repair: **65 listings re-pointed**
  (identical to the 1-Oct rehearsal); second dry run 0. `restore_drill.py
  --backup /app/db/pre-compose.db` passed (21,944 snapshots intact).
  Live checks from the PC: footer and `/healthz` show `905d28c`; Umart in the
  health strip; separate RTX 5060 Ti 8GB (#104) / 16GB (#73); RTX 5090 page
  has only 5090 cards; /deals below-average items all ≥2.6% and ≥$28.
  Issues closed after live verification: #1 #3 #4 #5 #6 #7 #8 #12 #13 #14 #24
  #25 #28. Status comments (done / remaining) on #2 #9 #10 #11 #15 #21 #23
  #26 #27 #31. **Next:** switch on `TRACKAROO_HEARTBEAT_URL` (healthchecks.io)
  and `TRACKAROO_BACKUP_MIRROR_DIR` (if a NAS is mounted) with one
  `deploy/redeploy.sh` after 10:00, then close #9/#10; on 3-Oct check
  `/healthz` shows `lastRunStatus: ok` for all three retailers; then Phase 5,
  starting with #16 (discovery report, together with #21).

- **2026-10-01 — Phase 6 Task 6: rehearsal on a copy of prod's DB passed.
  Resume here: next is Task 5 (push + three stacked PRs), then Task 7.**
  Host facts (owner-run, 1-Oct): `~/docker/Trackaroo` is a clean git checkout
  of `main` at `e9bd419` (30-Aug, an ancestor of our `main`) → the migration
  runbook's **Path A**. Container mounts are exactly `db → /app/db` and
  `data → /app/data` (no logs mount); restart `unless-stopped`. `.env` has no
  `$` in values and no quoted values; its `ALGOLIA_*` lines equal the code's
  built-in key — comment them out during the move. Compose v5.5.1, 153 GB free.
  Rehearsal on a `sqlite3 .backup` copy (3.1 MB; 100 products, 485 listings,
  21,058 snapshots, 53 daily snapshot dates 9-Aug..30-Sep, no gaps):
  `migrate.py` (retired RX 9070 XTX, added the three new tables) → `seed.py`
  (+6 products) → `repair_listings.py` dry run: 65 moves, all correct (46
  memory-variant splits, 8 wrong-model fixes, 11 non-matches such as 5900XT,
  5600GT, 7700X3D, board bundles and the 5090 AI box detached to hidden
  "Unmatched" placeholders) → `--apply` → second dry run 0 moves.
  `restore_drill.py --backup <untouched> --db <migrated>` exit 0; per-day
  snapshot counts identical; every snapshot row and listing id/sku identical;
  0 orphans; integrity + FK checks clean; products 100 → 108 (6 seeded + 2
  untracked placeholders). Served on `node web/server.js`: every main page 200,
  placeholders appear on no list page. Expected after deploy: the home page
  shows Umart as "missing" until the first Umart scrape lands.
  Owner to-do on the host: `docker exec trackaroo rm /app/db/rehearsal-copy.db`
  (root-owned copy left in `db/`).
  Task 5 gate from a clean tree at `07e90ea`: pytest **1073 passed**, vitest
  **791 passed** (37 files), Playwright **115 passed**, svelte-check **0 errors,
  0 warnings** (466 files); image built offline with `GIT_SHA`, booted
  `healthy`, `/healthz` reported `"version":"07e90ea"`. All three branches
  are PUSHED (1-Oct); the PRs are NOT opened yet (the agent's `gh pr create`
  was blocked by a permission rule). **Resume 2-Oct:** owner runs, in order,
  `gh pr create --base main --head feat/2026-09-29-robustness --title "Robustness (28-Sep roadmap phase 3)" --body-file docs/pr-bodies/2026-10-01-phase3-robustness.md`,
  then `--base feat/2026-09-29-robustness --head feat/2026-09-30-ux --title "UI/UX and better information (phase 4)" --body-file docs/pr-bodies/2026-10-01-phase4-ux.md`,
  then `--base feat/2026-09-30-ux --head feat/2026-09-30-redeploy --title "Redeploy with docker compose (phase 6)" --body-file docs/pr-bodies/2026-10-01-phase6-redeploy.md`;
  check the first CI run (`gh run list`); merge in order; then Task 7
  (`docs/runbooks/dockerhost-compose-migration.md`, Path A).

- **2026-09-30 (end of day) — Phase 6 "redeploy with docker compose": code
  done, NOT deployed.** Branch `feat/2026-09-30-redeploy`
  (stacked on `feat/2026-09-30-ux` → `feat/2026-09-29-robustness` → `main`;
  PR #41, phases 1–2, is already merged). None of the three branches is
  pushed. Plan: `docs/superpowers/plans/2026-09-30-redeploy.md`; Tasks 1–4
  are done (footer build stamp, `docker-compose.yml`, `deploy/redeploy.sh`,
  docs + migration runbook in DEPLOYMENT.md), plus a fresh-reviewer pass whose
  six findings are fixed (`749586b`). The owner chose compose over the old
  "no compose" rule (30-Sep).
  **Where prod is:** NOT this PC. The live app runs on the owner's separate
  Ubuntu server, `giel@dockerhost:~/docker/Trackaroo`, as a plain
  `docker run` container named `trackaroo` (image `trackaroo`, created ~2 Sep,
  still a pre-31-Aug build: `data/` has pccg + scorptec JSON from 9 Aug to
  30 Sep and no umart). `watchtower`, `portainer` and `ergo-monitor` run on
  the same host. The DB in this working copy is not prod data. Every host step
  is run by the owner on that server (or over ssh if they grant it).
  **Owner priority:** keep all existing prod data; no restart from scratch.
  **Next, in order:** (1) owner runs on dockerhost: `git status -sb`,
  `git log --oneline -1`, `ls` in `~/docker/Trackaroo`, the
  `docker inspect trackaroo` mounts, and checks `.env` for `$`; (2) owner makes
  a consistent DB copy (`docker exec trackaroo python -c "import sqlite3; ...
  s.backup(d)"` into `db/rehearsal-copy.db`) and scps it to this PC; (3) plan
  Task 6: rehearse migrate/seed/repair on a scratch copy here and prove
  per-day snapshot counts are unchanged (`restore_drill.py --backup`);
  (4) Task 5: push, three stacked PRs, first CI run; (5) Task 7: the host
  migration, following the step-by-step guide for that server:
  `docs/runbooks/dockerhost-compose-migration.md`.
  Gate: pytest **1073 passed**, vitest **791 passed**, Playwright **115
  passed**, svelte-check **0 errors, 0 warnings**.

- **2026-09-30** — **Phase 4 "UI/UX and better information" (#25, #24, #31 core,
  #27, #26, #23, #5 items 4–5; U1–U6, D7, three Phase 1–2 follow-ups) on
  `feat/2026-09-30-ux`** (stacked on `feat/2026-09-29-robustness`; not pushed,
  not deployed). The product page answers "is now a good time to buy?":
  lowest price since tracking began and when, today's gap to it, a 30/90-day
  low/median/high strip and cheapest-per-retailer "where to buy", all from data
  the page already loaded. The chart gained a legend, low and today markers, a
  spoken summary, a data table and a text-only tooltip. One `<title>` per page,
  OG tags, PNG icons + manifest, theme-aware `color-scheme`/`theme-color`.
  Status colours are separate from price up/down, and contrast is measured from
  `app.css` in CI. Search, compare, the never-listed toggle and movers
  sort/direction/grouping live in the URL; product pages have breadcrumbs and
  "Compare with…"; /compare has a picker. The catalog hides never-listed products
  by default and shows VRAM/cores, release month and listing counts. /movers is
  one responsive table grouped by product (warm TTFB **5 ms, was 28 ms**). The
  homepage movers follow the product's cheapest price (D7). `/gpus` and `/cpus`
  redirect; MSRPs read "US$". Dates use a fixed month table. "… 8GB"/"… 6GB"
  products match their specs; the base card shows its VRAM beside a memory
  sibling (display only). `mobile.spec.ts` now screenshots every main page at
  390 px in both themes (`web/test-results/mobile/`, gitignored) and was
  reviewed by eye: no fixes needed.
  **Before/after** — `web/scripts/measure.sh` against `npm run build` +
  `node server.js`, both on the same scratch copy of `db/trackaroo.db`;
  "before" is the phase start (`d9cd95e`) built in a separate worktree
  (wire / raw bytes / warm TTFB):

  | Route | Before (`d9cd95e`) | After |
  |---|---|---|
  | `/` | 7,634 / 42,909 / 3 ms | 7,815 / 45,104 / 3 ms |
  | `/deals` | 7,890 / 59,846 / 4 ms | 8,163 / 61,805 / 3 ms |
  | `/movers?window=7d` | 20,267 / 424,391 / 28 ms | 11,911 / 125,690 / 5 ms |
  | `/products?category=gpu` | 7,294 / 109,557 / 3 ms | 8,228 / 90,577 / 3 ms |
  | `/product/1` | 6,519 / 40,199 / 3 ms | 8,128 / 53,510 / 4 ms |

  `/product/1` grows as expected (buy panel + collapsed data table); cold runs
  match warm within a millisecond. Gate from a clean tree: pytest **1042
  passed**, vitest **787 passed** (36 files), Playwright **114 passed**
  (Chromium), svelte-check **0 errors, 0 warnings** (464 files). **Left for
  Phase 5**: #31 percentile/sale-event/successor signals, #23 sortable columns
  and facet filters, #26 per-row "best value" highlighting on /compare, #27's
  30-day-average marker and gap connector, #32 AUD MSRP. **Owner to check**:
  `python sync_specs.py --dry-run --category gpu` for the GRE products (Task 11
  Step 6).

- **2026-09-29** — **Phase 3 "robustness" (#12, #7, #8, #11a, #14, #13, #9,
  #10, R1–R4; #15 in part) on `feat/2026-09-29-robustness`.** One exception
  can no longer skip the digest gate, the alerts or the backup, and the all-fail
  path now alerts. A bad JSON file is skipped and reported. Scrapers exit 0/2/3/4,
  so an empty scrape or a rejected PCCG key alerts while a cooldown only warns.
  Every active retailer shows on the health strip ("missing" if never reported)
  with its last scrape time and matched count. Failed retailers are retried
  hourly until `RETRY_UNTIL_HOUR` (9), and the staleness monitor alerts the same
  morning. Scrapers save per category, so a timeout keeps partial results. Page and
  card telemetry, real-HTML fixtures, selector-drift and trailing-median drop
  rules are in. CI: pytest, vitest, svelte-check, Playwright, `node server.js`
  smoke and an offline `docker build` + boot. `/healthz` plus a Docker HEALTHCHECK
  and build stamp. Backups are `quick_check`ed, pruned by age, and have a
  restore drill. **Built but OFF until Phase 6**: `TRACKAROO_HEARTBEAT_URL`,
  `TRACKAROO_BACKUP_MIRROR_DIR`, and the `GIT_SHA` build arg in the redeploy
  script. Gate: pytest **1017 passed, 0 failed**, vitest **475 passed** (23
  files), Playwright **71 passed** (Chromium), svelte-check **0 errors, 0
  warnings** (433 files). **Deploy notes (Phase 6):** `migrate.py`
  (run by bootstrap on boot) adds `active_retailers`, `scrape_runs` and
  `run_markers`. On deploy day, retailers that already have today's snapshots
  are not re-scraped. `TRACKAROO_BACKUP_KEEP` now counts days. Remove
  `ALGOLIA_*` from prod `.env` unless deliberately overriding. Create the
  mirror directory before pointing `TRACKAROO_BACKUP_MIRROR_DIR` at it —
  Trackaroo never creates it. Set `TRACKAROO_HEARTBEAT_URL` to switch the
  heartbeat on. Build with `--build-arg GIT_SHA=$(git rev-parse --short HEAD)`
  so `/healthz` reports the real version. The image's `HEALTHCHECK
  --start-period=5m` has not been tested against a real first-boot hydrate
  (only CI's offline boot, which has no snapshot history to load). CI's
  docker job only runs after a push, not on every local change. **Left in
  #15**: dead Algolia knobs, logs mount + Docker log rotation, requirements
  split and pinning, the run lock, and alert-delete scoping.

- **2026-09-29** — **Web-speed close-out (issues #28, #5): full regression
  gate + a measured before/after against the built app.**
  Work closed out on `feat/2026-09-28-prices-and-speed` (commits
  `c412a9e..2bee0d7`): a `compression` wrapper server (`web/server.js`)
  gzipping every response adapter-node itself leaves uncompressed, with a
  hand-rolled graceful SIGTERM/SIGINT shutdown restored on top of it; `/products`
  dropping the unused `listings` payload per group and the homepage no longer
  querying the same day-level data twice; `/movers` reworked to surface real
  movers first (no more `++$`, retailer names instead of ids, unchanged rows
  now hidden rather than padding the page) plus a column-header-sort fix so
  those hidden/unknown rows stay pinned last; and a `data_version`-keyed memo
  cache in front of the day-level queries (invalidated only when SQLite's
  `data_version` actually changes) with a 60s `cache-control` on the list
  pages (`/`, `/deals`, `/movers`, `/products`).
  **Full regression gate, run fresh from a clean tree**: backend
  `python -m pytest -q` from the repo root — **863 passed**; frontend from
  `web/`: `npm run check` — **0 errors, 0 warnings** (430 files); `npm test`
  — **462 passed** (22 files); `npm run test:e2e` — **71 passed** (Chromium).
  **Before/after, measured with `web/scripts/measure.sh`** (also switched its
  default base URL from `http://localhost:3000` to `http://127.0.0.1:3000` —
  `localhost` was adding ~200ms of DNS lookup on this Windows box and
  distorting TTFB) against `npm run build` + `node server.js` served from the
  real `db/trackaroo.db` (wire = gzip-requested bytes, raw = uncompressed
  bytes; "now" cold = first request after a fresh server start, warm =
  repeat run against the same process):

  | Route | Task 0 local baseline (raw, uncompressed) | Live prod 28-Sep (raw, ms) | Now — cold (wire / raw / ttfb) | Now — warm (wire / raw / ttfb) |
  |---|---|---|---|---|
  | `/` | 42,786 B | 37,228 B, 100 ms | 7,623 / 42,794 / 5 ms | 7,623 / 42,794 / 4 ms |
  | `/deals` | 59,824 B | 106,125 B, 60 ms | 7,856 / 59,824 / 5 ms | 7,856 / 59,824 / 7 ms |
  | `/movers?window=7d` | 1,961,832 B | 1,523,484 B, 223 ms | 20,216 / 424,369 / 36 ms | 20,216 / 424,369 / 48 ms |
  | `/products?category=gpu` | 405,650 B | 319,675 B, 35 ms | 7,239 / 109,535 / 4 ms | 7,239 / 109,535 / 4 ms |
  | `/product/1` (prod row is `/product/86`) | 40,177 B | 73,748 B, 13 ms | 6,505 / 40,177 / 4 ms | 6,505 / 40,177 / 4 ms |

  Raw-byte drops vs the Task 0 baseline land mostly on `/movers` (−78%, the
  hidden-unchanged-rows work) and `/products?category=gpu` (−73%, dropping
  `listings`); `/`, `/deals` and `/product/1` are essentially unchanged in raw
  bytes (that work targeted query count and compression, not payload shape)
  but ship at ~15–18% of their raw size on the wire once gzip is in front of
  every response, not just the immutable assets. TTFB is single-digit
  milliseconds everywhere against a local DB except `/movers`, which stays in
  the 30–50ms range warm and cold alike — that's render/serialisation cost of
  a still-large page (132 real movers rendered into both a table and a mobile
  list), not a caching gap; Phase 4's single responsive layout is expected to
  close it.
  **Open follow-ups, not done here**: no CI smoke test runs against the real
  `node server.js` (the e2e suite only exercises `vite dev`); #5 items 4 and 5
  — group movers by product, and the segmented-control accessibility / one
  shared responsive layout — remain for Phase 4. GitHub issue comments on #28
  and #5 are deferred to the repo owner, per this task's controller ruling.

- **2026-09-29** — **Task 7 close-out of the "correct prices" branch
  (`feat/2026-09-28-prices-and-speed`, Tasks 1–6): full regression gate +
  a local before/after against a real-data copy of the DB.**
  Tasks 1–6 (already committed going into this session): the canonical
  chip-key matcher + all three scrapers resolving through it, `seed.py`
  syncing `vram_gb`/`cores` for existing products, `repair_listings.py`
  (backup-first, idempotent, re-points listings the old substring matcher
  mis-filed) with ingest made authoritative over it, stale listings excluded
  from the product-page headline/compare price, and `/deals` given a
  2%/$10 floor + earned all-time-low section + one-row-per-product dedupe +
  honest "vs N-day avg" labels.
  **Full regression from a clean tree, counts measured fresh (not trusted
  from earlier sessions)**: backend `python -m pytest -q` **853 passed**;
  frontend from `web/`: `npm run check` **0 errors** (415 files), `npm test`
  **425 passed** (19 files), `npm run test:e2e` **70 passed** (Chromium).
  **Local before/after, run only against a scratch copy of `db/trackaroo.db`**
  (via `TRACKAROO_DB` + `TRACKAROO_BACKUP_DIR` pointed at a temp dir — the
  real `db/trackaroo.db` and `db/backups/` were never touched, confirmed by
  `git status` staying clean throughout): `python seed.py` inserted 5 new
  watchlist products (incl. the new `GeForce RTX 5060 Ti 8GB`) and synced 1
  existing product's spec (`GeForce RTX 5060 Ti`, now correctly 16GB-only);
  `python repair_listings.py --apply` then re-pointed **90 listings** — most
  moving mis-filed 8GB/6GB/GRE/XT variants (5060 Ti, 9060 XT, RTX 3050,
  RX 9070) onto their own new products, the rest a batch of CPU/GPU bundle
  listings (`5900XT`, `7700X3D`, `5600GT`, `5500GT`, `9950X3D2`, Z890/B860
  motherboard bundles, an "AI Box" 5090 listing) correctly reclassified
  `UNMATCHED (stale)` rather than staying wrongly claimed by an unrelated
  tracked product.
  **Verified against the copy with `npm run dev` + curl/HTML (no browser)**:
  (1) `/product/73` (`GeForce RTX 5060 Ti`) headline is **$949 at Scorptec**
  backed by listing "msi geforce rtx 5060 ti 16g shadow 2x oc plus" — every
  remaining offer on that page is a 16GB card, confirming the split actually
  separated the variants. (2) `/product/104` (new `GeForce RTX 5060 Ti 8GB`)
  exists with **36 listings · 348 snapshots**, 9–31 Aug 2026, headline
  **$699 at Scorptec**. (3) `/deals`: **6 below-average** deals, all
  comfortably clear of the 2%/$10 floor (4.0%–6.3%, $24.09–$61.90) + **5
  all-time-low** deals = **11** total, matching both the "All 11" chip and
  11 `data-testid="deal-row"` elements on the page. (4) `/product/77`
  (`GeForce RTX 5090`) headline is **$7,199 at Scorptec**, "seen 31 Aug" —
  no "Not seen since" text appears anywhere on the page.
  **Deploy notes**: on redeploy, run `python seed.py`, then
  `python repair_listings.py` **as a dry run first** — review the printed
  re-points, especially any `UNMATCHED` line for a GPU with no memory size
  in its title (that's the one case that means a genuine matcher gap, not
  an expected split/stale reclassification) — then run
  `python repair_listings.py --apply`. Also: list pages send
  `cache-control: public, max-age=60, stale-while-revalidate=300`, so a
  browser can keep showing a pre-deploy page for a few minutes after this —
  hard-refresh (Ctrl+F5) to confirm the new build.
  **Not done here (deferred to the repo owner, per this task's brief)**:
  commenting on GitHub issues #1, #2, #4, #6 with commit SHAs — left open
  until the prod redeploy (roadmap Phase 6) confirms.

- **2026-09-03 (night)** — **Hardcoded-values cleanup, item 1 of "What's NOT
  done yet".** The retailer half was closed 31-Aug; this closes the rest of
  what STATUS.md named ("health check limits, BATCH_SIZE, timeouts") —
  minus `BATCH_SIZE` itself, which turned out to already be env-configurable
  and is now dead code rather than hardcoded (see CLAUDE.md's note that
  retiring it is a separate cleanup; left alone here).
  **Three genuine hardcoded thresholds found and fixed**, all now
  `_env_int`-backed matching the rest of `config.py`'s convention: (1)
  `DEFAULT_MIN_PER_CATEGORY`/`DEFAULT_MIN_TOTAL` — the match-count health
  check's own fallback thresholds, previously bare literals unlike every
  other value in the file; (2) a shared `NOTIFY_TIMEOUT_SECONDS` (new
  `TRACKAROO_NOTIFY_TIMEOUT_SECONDS`, default 10) replacing four identical
  hardcoded `timeout=10` call sites across `check_alerts.py` (Discord
  webhook, generic webhook, SMTP) and `notify_discord.py` (Discord webhook)
  — the only network calls left in the pipeline without a configurable
  timeout; (3) `RESTOCK_COOLDOWN_HOURS` (new
  `TRACKAROO_RESTOCK_COOLDOWN_HOURS`, default 24), moved from `check_alerts.py`
  into `config.py` alongside its sibling `PCCG_COOLDOWN_HOURS`.
  **Deliberately left alone**: `check_staleness.py`'s own
  `DEFAULT_THRESHOLD_DAYS` (a distinct, intentionally-different-default
  staleness concept for the standalone monitor — conflating it with
  `config.STALE_THRESHOLD_DAYS` risked more confusion than it fixed), and
  presentation-only constants (`notify_discord.TOP_N`, Discord embed hex
  colors) — not thresholds anyone needs to tune without a code change.
  5 new tests (`unit_testing/test_config.py`), following the file's existing
  `_config_value_with_env` subprocess-import pattern. Regression: pytest
  **759/759**, all passing. Frontend untouched (backend-only change).

- **2026-09-03 (evening)** — **Task 2 of the 1-Sep plan decided: Mwave
  parked, not built.** The open question from `THIRD_RETAILER.md` was never
  actually measured — does Mwave restore coverage the way Umart did? Checked
  all 39 tracked-but-unlisted products (22 GPU, 17 CPU) against Mwave's
  complete catalogue (all 3 GPU pages, 276/278 products; a CPU search, 100
  products — exactly 5 requests, reconfirming the WAF's ~5-request budget:
  all served, none challenged). **Result: 0 of 22 unlisted GPUs, 2 of 17
  unlisted CPUs** (`i5-14600KF`, `i9-14900F`; a third apparent hit,
  `Ryzen 9 7950X`, is refurbished-only stock). Mwave's catalogue is
  dominated by current-gen stock exactly like the three retailers already
  live — the RX 6000/7000 and RTX 30/40-series cards driving the gap are
  equally end-of-life there. 2 real new listings out of 39 gaps doesn't
  justify a scraper with zero retry margin against a count-based WAF
  allowance. **Decided: park it.** No scraper code written. Recorded in
  `docs/proposals/THIRD_RETAILER.md` and the decision log
  (`docs/ARCHITECTURE.md` Part 3). Confirmed with the user: **Task 0 (deploy
  to prod) is already done** on their end — both this and the earlier
  3-Sep pieces of work are live.

- **2026-09-03 (later)** — **Fixed the pre-existing `test_full_coverage_ok`
  failure flagged earlier today.** Root cause: `check_spec_coverage()` itself
  is correct — it computes `days_since = (date.today() - last_date).days`
  exactly like every other check in `health_checks.py` (none of them take an
  injectable clock). The bug was in the test: `test_full_coverage_ok` and
  `test_low_coverage_warns` hardcoded the spec's `last_synced_at` as the
  absolute date `2026-08-18T04:21:36Z`, while every *other* date-sensitive
  test in the file computes its date relative to `date.today()` (the sibling
  `test_stale_spec_data_warns` a few lines down is the pattern: `date.today()
  - timedelta(days=...)`). 18-Aug was "fresh" when the test was written;
  16 days later it aged past `SPEC_STALE_THRESHOLD_DAYS` (14) on its own,
  with no code change involved. Fixed both fixtures to use `date.today()`
  directly, matching the rest of the file. `test_low_coverage_warns` didn't
  actually assert on `spec_staleness`, so it was never failing, but was
  fixed too for consistency (same landmine, one assertion away from
  tripping). Regression: pytest **754/754** clean, no failures. Frontend
  untouched (backend-only test file change).

- **2026-09-03** — **Task 1 of the 1-Sep plan done: listings that never age
  out now do.** `check_delisted.py:141` only ever watched Scorptec, so a
  PCCG or Umart listing that quietly stopped appearing in its retailer's grid
  stayed `status='active'` forever — inflating the "N of M tracked" headline
  that was built 31-Aug specifically to stop that kind of overstatement.
  New `check_stale_listings.py` closes the gap for all retailers, built via
  TDD (11 tests, `unit_testing/test_check_stale_listings.py`). **The rule
  that keeps it safe**: a listing is judged against **its own retailer's
  latest snapshot**, never against `today()` — one SQL query (two CTEs +
  `julianday()`) marks a listing a candidate only when its retailer has a
  snapshot within `TRACKAROO_STALE_LISTING_DAYS` (new config knob, default
  **7**) of today *and* the listing itself does not. A retailer with no
  recent data at all (e.g. mid-cooldown) contributes zero candidates,
  however long its listings have been quiet — proven by a dedicated test
  before anything else. `status='stale'` reuses the value already defined in
  `db/schema.sql`'s CHECK constraint (and already written by
  `migrate.py`'s retired-product path) — no migration needed. Wired into
  `run_daily.py` right after the existing delisted check, in its own
  best-effort `try/except`, not gated on any specific retailer's scrape
  succeeding (unlike the Scorptec-only delisted check) since it judges each
  retailer independently. `check_delisted.py` is untouched — `delisted`
  stays the stronger, positive-confirmation signal; `stale` is the weaker,
  retailer-agnostic "stopped appearing" net beneath it.
  **Verified against the real local DB**: 14 candidates (8 pccg, 6
  scorptec — a superset of 31-Aug's 13, one more scorptec bundle having
  aged past the threshold since; correctly **zero** Umart, not because it
  was excluded but because none of its listings have individually gone
  quiet yet — all three retailers' latest snapshot was 2026-08-31, 3 days
  before today, well inside the 7-day window). Backed up first
  (`backup_db.py`), dry-run inspected, then applied for real; a second
  dry-run confirmed 0 further candidates (idempotent).
  Regression: pytest **754** (753 pass + 1 **pre-existing, unrelated**
  failure — `test_full_coverage_ok` hardcodes an 18-Aug spec date against a
  14-day staleness threshold with no `today` injection, so it now fails on
  its own as real time has moved past it; confirmed failing identically on
  `main` before this session's changes, left alone as out of scope), vitest
  **397**, e2e **68**, svelte-check 0 errors.
  **Not done this session**: Task 0 (deploy 31-Aug's work to prod) needs the
  prod host, which this session couldn't reach — confirm separately whether
  it's already been done. Task 2 (Mwave) stays explicitly gated on Task 1,
  which is now satisfied, but wasn't started here.

- **2026-08-31 (late)** - **Audited how a product gets added and gets specs.
  The spec pipeline is sound; the watchlist front door was not.**
  **A one-character typo stopped the container booting.** `parse_spec` did a
  literal `int(spec.replace("GB", ""))`, so a lowercase `16gb` raised
  ValueError out of `load_watchlist`, exited `seed.py` with status **1**, and
  `deploy/entrypoint-single.sh` runs `seed.py` under `set -e`. Every scraper
  failed identically, since they all call `load_watchlist()`. Confirmed by
  running it, not by reading it. Rows are now validated individually and
  **skipped with an error naming the line and field** - `watchlist row 21
  [spec]: cannot read VRAM from '16gib'; expected e.g. '16GB'` - so one bad row
  costs one product rather than the whole pipeline. `parse_spec` also stopped
  being case-sensitive (`16c` / `16C` / `" 16 c "` all work); the unit stays
  required, because a bare `12` is ambiguous between cores and gigabytes.
  **The alias-ordering trap is now documented and guarded.** Scorptec and Umart
  test entries by primary search term **length descending** and break on first
  match, so a base model whose first alias is longer than a variant's silently
  claims that variant's listings - plausible prices, no error, nothing in the
  logs. A test now fails if any base model outranks a more specific sibling.
  **Four AMD parts had sat in the unmatched spec report for weeks** (Ryzen 5
  5500 / 5 5600 / 7 5700X / 9 9900). Not a URL bug: *every* amd.com form for
  them redirects to the homepage, so AMD retired the pages. They are now listed
  separately as "no upstream specs (known)" with a reason and check date in
  `SPECS_UNAVAILABLE_UPSTREAM`, taking the report from `unmatched=4` to
  `unmatched=0`. The point is not tidiness - four permanent entries train you to
  skim the list, which is how a genuinely new gap goes unnoticed.
  **The process had no runbook**: Part 2 said *what* to track and stopped. New
  **Part 2 §7** covers the edit, the alias rule, seeding, that specs arrive on
  the next weekly sync rather than immediately (six days if you add on a
  Monday), how to pull them in early, and that removing a product needs
  `migrate.RETIRED_PRODUCTS` as well as deleting the row.
  **What the audit found healthy**, for the record: `sync_specs` picks up new
  products automatically (the dry run showed `new=1` - the `Core i9-14900` added
  hours earlier), matching is conservative and reports rather than guesses,
  every source reports `records/new/unchanged/conflicts/unmatched/fetch_failed`,
  a failed sync leaves last-known-good data, and `check_spec_coverage` monitors
  it (95/100, threshold 80%).
  **Correction to this morning's note:** `DECISIONS.md` is not missing - it and
  `SCOPE_RULES.md` were merged verbatim into `ARCHITECTURE.md` Parts 3 and 2.
  The stale pointers in `watchlist.csv` and STATUS's own "how to update" section
  now point at the right place. CLAUDE.md's test counts said 611/239 against an
  actual 743/397.
  Regression green: pytest **743**, vitest **397**, e2e **68**, svelte-check 0
  errors.

- **2026-08-31 (night)** - **Umart is live: third retailer scraping, ingesting
  and wired end to end. Plus a data-integrity bug found the hard way.**
  **The `CHECK`-constraint migration is done** - the thing THIRD_RETAILER.md
  called "the sharp edge". Widened to the six slugs `types.ts:7` already
  declares rather than moving to a `retailers` lookup table: the table's selling
  point was that a new retailer becomes a row insert, but that is not true end
  to end, since seven other files enumerate retailers in code as well. The
  rebuild derives its DDL from the live table (a hardcoded column list would rot
  the first time a column is added), turns on `legacy_alter_table` for the
  rename (modern SQLite validates triggers during RENAME, and the trigger
  references a table that does not exist between DROP and RENAME), and runs
  `foreign_key_check` before COMMIT so a rebuild that orphaned snapshots rolls
  back. Applied behind a fresh backup: 478 listings and 101 products unchanged,
  zero FK violations, both indexes restored.
  **`scraper/umart.py` worked on its first live run**: 59 CPUs over 3 pages,
  217 GPUs over 11, **14 requests in ~36 seconds**, 182 matched listings, **180
  rows ingested with zero errors**. Both discovery findings earned their keep -
  the category URLs come from Umart's own homepage rather than a guess, and
  prices are read from the microdata `content` attribute, so the `$&nbsp;`
  entity that twice made this look like an SPA never comes into it. `data-id`
  is the SKU and `link[itemprop=availability]` is the stock state, so nothing is
  parsed out of rendered text at all.
  **The wiring is now one list, not nine sites.** `config.ACTIVE_RETAILERS`
  replaces the hardcoded pairs in ingest, health_checks (three), check_staleness,
  query and run_daily, whose per-retailer flags are generated from it. Retailer
  four is a line in that tuple. It is deliberately narrower than
  `migrate.PERMITTED_RETAILERS` (what the DB accepts), so health checks do not
  alarm about retailers with no scraper. Six existing tests failed on the change,
  every one because a fixture assumed exactly two retailers - which is the wiring
  working.
  **Coverage, which is why Umart was picked over Mwave:** five tracked products
  that had no listing at either existing retailer now have one - Core i5-13400F,
  Core i9-13900F, Ryzen 9 7900, GeForce RTX 3070, Radeon RX 6900 XT. GPUs go
  **23 -> 25 of 46** available, CPUs **34 -> 37 of 54**.
  **The bug, found by causing it.** A bare `python ingest.py` over the whole
  history **flipped all 12 delisted and 11 stale Scorptec listings back to
  active** - `find_or_create_listing` reactivated any listing whose URL appeared
  in the file being ingested, and every delisted listing still appears in the
  JSON from before it was delisted. That silently reversed work
  `check_delisted.py` had done by confirming 404s. The local DB was restored
  from the backup taken minutes earlier, and reactivation is now gated on the
  snapshot being at least as new as the listing's newest data. **This was a real
  defect, not just a misuse:** CLAUDE.md makes a full re-ingest a supported
  operation. `run_daily` was never exposed - it uses `ingest_today()`.
  **Note for later:** Umart's grid lists only purchasable items (217 GPUs, all
  in stock), so a listing vanishing there means out of stock, **not** delisted -
  which matters if `check_delisted.py` is ever extended to it.
  Regression green: pytest **709**, vitest **397**, e2e **68**, svelte-check 0
  errors.

- **2026-08-31 (evening)** - **Mwave and Umart both re-probed. Both earlier
  assessments were wrong, in opposite directions, and both retailers are now
  viable.**
  **Mwave is not blocked - the plan was just aimed at the wrong URL.**
  `/graphics-cards` is a *curated landing page*: 31 cards, no pagination links,
  and `?page=N` and `?cnt=500` are both ignored (pages 1-5 came back
  byte-identical). The real endpoint is **`/searchresult`**, which is fully
  server-rendered and takes a page size and an offset:
  `?w=graphics+card&cnt=100&srt=<offset>&af=categoryPath%3AGraphics+Card`.
  One request returns **100 products**, and the page states the total: **278**
  in Graphics Card. Each card has name, `.SalesPrice`, stock, URL and a **stable
  SKU** (`AC84825`). So a daily run is **~3 requests for GPUs and ~2 for CPUs,
  not 20** - which lands exactly on the measured 5-request WAF allowance. That is
  the real catch: viable, but with **no headroom for a retry**, so a challenged
  fetch must abandon the day rather than retry inside the run.
  **Umart is server-rendered and the URL scheme is now known.** The 30-Aug spike
  filed it "unassessed" after a guessed URL bounced to the homepage - the guess
  used the *goods* form (`_1350G.html`) where categories are path-based with a
  trailing id, and the real ones are simply **listed on the homepage**:
  `/pc-parts/computer-parts/graphics-cards-gpu-610` (11 pages) and
  `/cpu-processors-611` (3 pages), 20 per page, so **~14 requests a day**. No WAF,
  permissive `robots.txt`. Each `.goods-item` carries name, brand,
  `.goods-price`, stock and a numeric SKU from the URL suffix.
  **A trap that cost time twice** and is now written into the proposal: Umart
  renders prices as `$&nbsp;579.00`, so a `\$[\d,]+` regex over the raw HTML
  matches **nothing** and the page reads as a client-rendered SPA. It is not -
  BeautifulSoup decodes the entity and the grid is all there. The genuine SPA
  among the candidates is PLE, not Umart.
  **The choice is now an explicit trade**, written up in `THIRD_RETAILER.md`:
  Mwave is cheaper to integrate (already in the schema `CHECK`, ~5 requests) but
  operationally fragile; Umart is operationally safe but costs the
  `CHECK`-constraint table rebuild up front. **Umart is also the one that answers
  the coverage problem found earlier the same day** - it still stocks RTX 3060,
  GT 710/730 and other parts that Scorptec and PCCG have sold out of, which is
  exactly why 42 of 100 tracked products have no listing.
  The Mwave plan is marked **superseded in part**: its Tasks 2-4 target the wrong
  URL and Task 3's premise (that politeness is spacing) is disproved. Task 1's
  fixture approach, the SKU-keyed rule and Task 5's nine hardcoded places stand.
  No scraper code written; no decision taken on which to build.

- **2026-08-31 (later)** - **Watchlist hygiene: there were no matching failures
  to fix. The data was right and the label was wrong.**
  The 30-Aug write-up split the no-listing products into three kinds - cards
  that do not exist, cards not sold in AU, and **matching failures**. Checking
  both retailers' live catalogues directly (PCCG via one Algolia query per
  category, Scorptec via its category pages) shows the third kind is **empty**.
  All 42 are genuinely absent from both catalogues today. Every apparent
  near-miss is a *variant* SKU the matcher correctly distinguishes - Scorptec's
  `rtx 4070 ti`, `rtx 3080 ti`, `rtx 3090 ti`, `i9 14900k`, `ryzen 9 7900x` -
  and each maps to its own tracked entry that **does** have a live listing.
  **The dominant kind is a fourth one nobody named: end-of-life.** RTX 30/40
  series, RX 6000/7000, Intel 13th gen - sold here once, now aged out of the
  channel as the 50-series and Ryzen 9000 took over. Four were caught in the
  act: RX 6800, RX 7900 XT, RX 7900 XTX and RTX 4060 Ti all went `delisted`
  between 10 and 27-Aug. Arc A770 is the genuine "not sold in AU" case -
  Scorptec stocks A310/A380/B580 instead.
  So the fix is **not** data cleaning. `getCategoryCounts` counts the watchlist,
  which is a statement of *intent*, and the dashboard presented it as
  *coverage*. New `getAvailableCounts` counts tracked products with at least one
  active listing, and `CategorySection` now reads **"23 of 46 tracked"** for
  GPUs and **"34 of 54"** for CPUs. Nothing is untracked, no per-product
  judgement is needed, and it self-corrects if anything is restocked.
  **A gap in the other direction:** PCCG stocks `Intel Core i9 14900` (the
  non-F/non-K part) and it was missing from `watchlist.csv` entirely. Added and
  seeded; the watchlist is 100 products (54 CPU / 46 GPU).
  **Checked and cleared:** in isolation the Scorptec per-entry matcher looks
  over-permissive - `core i9 14900kf` satisfies the `14900k` and `14900`
  predicates too. It is not a bug. `scrape_scorptec` sorts the watchlist by
  primary-term **length descending** and breaks on first match, so the most
  specific entry always wins; the new `Core i9-14900` has the shortest term and
  is therefore tested last. Live data confirms it: the KF listing sits under
  `Core i9-14900KF`, the K under `Core i9-14900K`.
  Regression green: pytest **663**, vitest **397**, e2e **68**, svelte-check 0
  errors.
  **Open at end of session:** three sessions' worth of change (anomaly baseline
  + gate, the event detector, and the available-count headline) are committed
  but **not yet deployed** - Docker is not running on this machine, so the prod
  container has not been rebuilt and is still running the old checks. Nothing
  else is pending: `DISCORD_WEBHOOK_ALERT` is confirmed set in prod, and the
  only decision outstanding is Mwave (park it, build the ~3-hour spread scraper,
  or start Umart and pay for the `CHECK`-constraint migration).

- **2026-08-31** - **Mwave probed and parked; price-anomaly detection fixed,
  and the old check turned out to be worse than "slightly damped".**
  **Mwave: NO-GO at the plan's 5s cadence - but NOT a NO-GO on Mwave**, written
  up in
  [`docs/proposals/mwave-waf-probe.md`](docs/proposals/mwave-waf-probe.md). Task
  0 of the scraper plan ran and **0 of 8 requests** at the plan's own 5s daily
  cadence were served - all HTTP 202 AWS WAF challenges. Two confounders were
  ruled out beyond what the plan asked: the query string is not the trigger (the
  bare URL challenges too) and a cookie jar does not help, because the challenge
  issues its token from JavaScript rather than `Set-Cookie`. Held short of a
  flat NO-GO because one request *did* return a real 159 KB page, so real HTML
  is obtainable; what this data cannot separate is "Mwave challenges every
  JS-less client" from "we are in rate-state from yesterday's spike plus today's
  15 requests". **The cold re-probe settled it, and reversed the reading**:
  after ~45 minutes of no contact a single request returned **200 / 159,056
  bytes**, so the challenge is rate state that clears on its own, not a standing
  block on JS-less clients. Re-running the plan's gate from that clean state
  gave the number that matters: **five requests served at 5s spacing, then
  challenged on the sixth**, and challenged from then on. So
  `MWAVE_PAGE_DELAY = 5.0s` as the plan specifies would fail partway through
  every run - but a once-daily scraper has no time pressure, and 20 pages at 60s
  apart is a 20-minute unattended job. **The cadence sweep then ran, and killed the delay
  theory**: 20 requests at **30s** apart from cold gave *exactly the same*
  result - five served, challenged on the sixth. Six times the spacing changed
  nothing, so the limit is a **count, not a rate**, and no `MWAVE_PAGE_DELAY`
  buys a sixth page. That is ordinary AWS WAF Challenge behaviour: a JS-less
  client gets a small allowance and is then challenged until it presents an
  `aws-waf-token`, issued only by *solving the JavaScript*. Same wall as Centre
  Com, reached by a different route. What remains is a run spread across ~4 cold
  periods over ~3 hours (~45 min of idleness clears one) - technically viable
  for an unattended daily job, but a **different scraper from the one the plan
  describes**: a deliberate choice, not a constant tweak. Second discovery: `?page=1`
  through `?page=5` all returned exactly 159,078 bytes, the same as the bare URL,
  so the `page` parameter is **ignored** and Mwave's real pagination scheme is
  unknown - a Task 4 discovery item, not a constant. Two findings survive either way: the
  healthy page *embeds* `challenge.js` and the string `awswaf` in its normal
  `<head>`, so neither can ever be a challenge marker (Task 3's
  `is_waf_challenge` keys on `awsWafCookieDomainList`/`gokuProps`, absent from
  it, and is correct as specified); and Mwave's `robots.txt` returns a real 200,
  unlike Centre Com's, which is itself a CAPTCHA. Mwave is hostile by rate rule,
  not by policy.
  **Price anomaly detection: options (b) + (c) + (e) implemented**, closing the
  item below. `MIN_HISTORY_FOR_ANOMALY` 3 -> **10**, the baseline now excludes
  the point being tested, and a plain day-over-day move rule
  (`PRICE_MOVE_PCT`, default **0.20**) runs alongside the sigma test.
  **(e) was not optional in the end.** Excluding today from the baseline means a
  listing with a flat price history has a prior sigma of exactly **0**, so the
  z-test divides by nothing and is blind to a jump of any size. The move rule is
  the only thing that catches those, which is precisely the RTX 5070's +45.0% on
  28-Aug. One warning per listing, so a jump on a jittery history is not
  reported twice.
  **The finding that made this worth doing:** with today's point *inside* the
  baseline and a flat prior history, the z-score is **exactly sqrt(N) whatever
  the move is** - the only variance in the sample is the one the tested point
  contributes. Verified algebraically and numerically: 18 flat days plus a **$1**
  move scores 4.24 sigma, identically to a $5000 move. On the real DB this was
  not theoretical - the old check raised **5** warnings, of which **4 were this
  artefact**, including `RTX 5090 @ pccg $7599 -> $7699` (**+1.3%**) reported as
  "4.0 std devs", which is exactly sqrt(16). So the old check was not
  over-sensitive in general; it was *magnitude-blind on flat listings* and fired
  at the sqrt(N) ceiling regardless. The new check raises **2** warnings on the
  same DB, both genuine, and includes an `RTX 5070 Ti @ scorptec $2099 vs a
  $1921 prior mean` (4.3 sigma) that the old one **missed** because today's
  price dragged the mean far enough to damp it under 3. Pinned by a regression
  test that was confirmed to **fail** against the old implementation.
  **31-Aug daily run recovered natively** (Docker is not running on this
  machine, so the scheduled run had not fired): **440 snapshots**, 0 ingest
  errors, backup written. **Note for anyone picking this up cold:** prod runs on
  a *separate host* which keeps its own DB, and that DB is current - so this
  recovery, and every figure quoted in this entry, describes the **local working
  copy**, not prod. Earlier entries (28-Aug, 30-Aug) describe recovering missed
  runs "on this machine" as though the repo held the live data; that has not
  been true since prod moved hosts. A real gap remains in the record - **no snapshots
  exist for 2026-08-29**, which the `missing_days` check reported.
  Regression green: pytest **663**, vitest **393**, e2e **68**, svelte-check 0
  errors (`web/` untouched since that run).
  **Noted:** `DECISIONS.md` does not exist as a file. *(Corrected 31-Aug: it was
  not lost -- it was merged verbatim into `docs/ARCHITECTURE.md` Part 3, along
  with `SCOPE_RULES.md` as Part 2. The stale pointers to both have now been
  repointed.)*

- **2026-08-30 (later)** - **Watchlist hygiene started; anomaly-detection
  options written down.**
  **What "watchlist hygiene" means**, since it was never spelled out: 43 of the
  100 tracked products (24 GPU / 19 CPU) have **no active listing at any
  retailer**, so the dashboard's "47 tracked" for GPUs describes 23 cards you
  can actually buy. The count overstates coverage by nearly half, and the
  thin CPU mover columns are a symptom, not a bug. Those 43 split into three
  kinds, which want different answers: cards that **do not exist** (retire
  them), cards that exist but **aren't sold in AU** (Arc A750/A770/B570 -
  arguably keep, so the absence is itself data), and **matching failures**
  (fix the aliases). Only the first kind is actioned so far.
  **Radeon RX 9070 XTX retired** - announced but never released, so it can
  never have a listing. Removing it from `watchlist.csv` is *not* enough:
  `seed.py` only ever INSERTs, so an existing DB keeps `tracked=1` forever.
  Added `migrate_untrack_retired_products` + `RETIRED_PRODUCTS` to `migrate.py`
  (which `deploy/bootstrap-data.sh` runs on every container start), so prod
  applies it on the next rebuild with no manual SQL. A test asserts anything in
  `RETIRED_PRODUCTS` is absent from `watchlist.csv`, so the migration and the
  seed can never fight. Local DB: 100 -> 99 tracked.
  **Open question deliberately not answered:** should `seed.py` untrack
  *anything* missing from `watchlist.csv`, making the CSV genuinely the source
  of truth its own header claims it is? That would remove the need for
  `RETIRED_PRODUCTS`, but it turns a partial or mis-parsed CSV into a mass
  untracking event. Left as an explicit decision rather than done quietly.
  **Anomaly detection**: no code change - the options are now written up under
  "What's NOT done yet" item 5 with the two real defects named (a
  `MIN_HISTORY_FOR_ANOMALY` of 3 against a 3-sigma gate that needs N>=10, and a
  baseline that includes the point being tested). 71% of listings now have the
  depth to be checked, so this is a decision, not a waiting game.
  `web/__shot2.mjs` deleted. Reverse proxy / TLS confirmed deferred while the
  dashboard stays on the LAN.

- **2026-08-30** - **Dashboard mover dedupe, staleness monitor scheduled, and a
  silent Docker mount trap documented.**
  The dashboard showed the RTX 5070 three times in "Biggest rises (7d)" with
  three different percentages. Not a maths bug: `getMovers` is per-LISTING and
  PCCG carries three MSI 5070 SKUs (Ventus 3X +45.0%, Shadow 2X +27.3%, Shadow
  3X +26.6%), while `MoverRow` rendered only model + retailer and dropped
  `variant_name`. Fixed with a new pure `web/src/lib/movers.ts`
  (`topMoversByProduct`) collapsing the dashboard columns to **one row per
  product**, and `MoverRow` now shows `retailer - variant`. `/movers` is
  untouched: its per-listing detail is correct and has a Variant column.
  Folded in a latent gap found on the way: the dashboard never filtered
  `notEnoughHistory`, so a listing `/movers` badges as untrustworthy would read
  as authoritative there. `topMoversByProduct` now excludes them.
  **Grid blowout caught by e2e**, not by eye: `truncate` implies
  `white-space: nowrap`, so a grid item's automatic minimum is min-content ==
  the full untruncated string, which widened the shared track and overflowed
  the phone viewport at 390px - visibly in the *Top deals* column, a sibling.
  Fixed with `min-w-0` on the `CategorySection` columns.
  **`check_staleness.py` is now actually scheduled** (it was written 27-Aug and
  wired to nothing). `deploy/entrypoint-single.sh` runs it daily at
  `STALENESS_CHECK_HOUR`, default **10**, in its own poll loop beside the spec
  sync; the hour must stay after `RUN_AT_HOUR` or every morning reads as an
  outage. **`DISCORD_WEBHOOK_ALERT` is still unset in `.env`** - until it is,
  the monitor signals only through the container log. *(Closed 31-Aug: confirmed
  set on the prod host. The local `.env` in this working copy still lacks it,
  which only affects native runs from this machine.)*
  **Duplicate listings: nothing to build.** Scorptec 155/337 (both SKU 118277,
  forked 13-Aug by a slug rewrite) looked like it needed a repair script; a
  `dedupe_listings.py` was written and then **deleted** on finding that
  `migrate.py:390` already merges exactly these groups, and more carefully -
  it preserves `scraped_at`, absorbs the newer URL and variant, and repairs the
  survivor's timestamps. It runs on every container start and merged 155 into
  337 during this session's verification. The local DB only carried the fork
  because the container had not been running on this machine.
  **New deployment trap documented**: in Git Bash on Windows, MSYS rewrites
  `-v "$(pwd)/db:/app/db"` so the mount silently lands nowhere - the container
  reports healthy while writing to its own layer, the exact state that cost 165
  snapshots. The tell is `db;C` / `data;C` directories in the repo root (both
  found here, empty). Use `MSYS_NO_PATHCONV=1` or PowerShell, and verify with
  `docker inspect`. Linux and macOS hosts are unaffected.
  Verified by building the image and booting it: dashboard HTTP 200, both
  scheduler loops alive, `check_staleness.py` OK against the mounted DB.
  Regression green: pytest **650**, svelte-check 0 errors, vitest **393**,
  e2e **68**. *(This entry originally said 660; measured at 650 on 31-Aug by
  checking out this commit and re-running, which is also what the Mwave plan
  recorded as its baseline.)*

- **2026-08-28** — **28-Aug snapshot recovered; the 27-Aug work landed in git.**
  The scheduled run had not fired — the container was not running on this
  machine — so the day was recovered with a native `run_daily.py`: **441
  snapshots** (pccg 121 / scorptec 320), four JSON files, zero ingest errors,
  one delisting marked, backup written. The rewritten PCCG scraper was
  exercised on a real run for the first time since the fix and cost **2
  Algolia queries with zero 429s** ("62 products in 1 Algolia query" / "230
  products in 1 Algolia query"). One health WARNING, no ERRORs, so the digest
  fired: RX 9070 XT @ Scorptec $1199 against a $1104 average (4.4 std devs) —
  a real price move, not a parse fault.
  **The whole 27-Aug session was uncommitted** — the PCCG rate-limit fix,
  `check_staleness.py` and the mobile pass existed only in the working tree,
  which matters because `docker build` COPYs the working tree, so the image
  built fine while none of it was in history. Landed as five commits on
  `chore/land-27-aug-work`. Regression re-run green before committing:
  pytest **643** / svelte-check 0 errors, 0 warnings / vitest **373** / e2e
  **67** (1.0m).
  **Still open from that session:** `check_staleness.py` is documented but not
  scheduled anywhere, and `DISCORD_WEBHOOK_ALERT` is still unset in `.env` —
  so the monitor built to catch a missed day would not have caught this one
  either. Untracked `web/__shot2.mjs` (throwaway screenshot script) left alone.
  *(Both resolved 30-Aug: the monitor is scheduled, the webhook is set on the
  prod host, and `__shot2.mjs` is deleted.)*

- **2026-08-27** — **Staleness monitor + mobile viewport pass.**
  **`check_staleness.py`** is the first health check that runs *outside*
  `run_daily.py`, which is the whole point: every existing check runs inside a
  run and so cannot fire when the run never happens — exactly how the 27-Aug
  gap was found by a human rather than by the system. It reads only the DB (no
  scraping, no network, no writes), splits severity deliberately — **ERROR**
  (exit 1 + Discord alert) for a missing/unreadable/empty DB or no data from
  *any* retailer inside the threshold, **WARNING** for a single lagging
  retailer such as PCCG in cooldown, since the pipeline is still running — and
  never raises. Default threshold 1 day: not having run *yet today* is not an
  outage; two days of silence is. Exit code carries the signal even with no
  webhook configured. 14 tests. **Note:** `DISCORD_WEBHOOK_ALERT` is documented
  in `.env.example` but **not set in `.env`**, so alerting is exit-code-only
  until it is.
  **Mobile pass:** audited every route at 320px and 390px with Playwright.
  **The backlog item was largely stale** — no route scrolls horizontally at
  either width, because the `md:` table-to-card split already handles phones.
  One genuine defect found and fixed: the `/products` compare checkbox was a
  bare 13x13px input with no wrapping label — under the WCAG 2.2 AA 24x24
  minimum and awkward to hit. It now sits in a padded `<label>` (32px target,
  negative margin keeps desktop density identical). New
  `web/e2e/mobile.spec.ts` (8 tests) pins no-horizontal-overflow on 5 routes at
  390px plus /products at 320px, and the tap-target size; both tap-target tests
  were confirmed to **fail** against the old markup before the fix.
  Remaining (not fixed, judged acceptable): filter/sort/window chips are 27-28px
  tall — above the 24px AA minimum but below the 44px comfort guideline.
  Regression: pytest **643** / svelte-check 0 errors, 0 warnings / vitest
  **373** / e2e **67** (57.8s) / build green.

- **2026-08-27** — **PCCG rate limiting: root cause found and fixed.** The daily
  429s were never a pacing problem. PCCG's public Algolia search key carries
  **`"maxQueriesPerIPPerHour": 100`** — read directly off `GET /1/keys/<key>`,
  not inferred from behaviour. The scraper issued **one query per watchlist
  product per page**, so 100 tracked products spent the entire hourly budget on
  page 0 alone and most runs 429'd partway through. Two long-standing
  assumptions were wrong: **batching does not help** (Algolia bills each entry
  in a multi-query `requests` array separately, so the "batched requests avoid
  rate limiting" comment was false), and **backoff cannot help** (the quota
  is a rolling ~60-minute window, not an hour-boundary bucket (measured: a heavy
  spend at 18:06 GMT still 429'd at 19:01 GMT) — waiting inside a run only burns it,
  which is exactly why `TRACKAROO_BATCH_SIZE=8 / BATCH_DELAY=3.0` had matched
  zero on 16-Aug).
  **Fix:** `algolia_fetch_catalogue()` pulls each category whole with one empty
  query at `hitsPerPage=1000` (229 GPUs / 60 CPUs each fit a single page) and
  `scrape_category` matches the watchlist against it locally with the existing
  `match_product` — the same authoritative filter that was already applied to
  search hits, so matching is equivalent but can no longer miss a listing that
  fuzzy ranking happened to rank low. **A full run now costs 2 Algolia queries.**
  The old path cost at least 100 (page 0 alone: 53 CPU + 47 GPU queries) and
  up to ~300 once queries paginated to the 3-page cap — i.e. it was over
  budget on every single run, before a byte of pagination.
  **Verified live, same hour the old code was rate-limited:** the rewritten
  scraper produced **byte-identical output** to the morning's run — 21 CPU and
  100 GPU matches, identical names/prices/stock/models — with **zero 429s**
  (04:06 log: four rate-limit warnings; 04:26 log: none, "60 products in 1
  Algolia query" / "229 products in 1 Algolia query").
  **End-to-end verified 05:15** on a clean quota window: full `run_daily.py`
  against an empty DB and empty data dir produced "60 products in 1 Algolia
  query" / "229 products in 1 Algolia query", **0 rate-limit warnings, 0
  ERRORs, no cooldown written**, 441 snapshots inserted (pccg 121 / scorptec
  320 — identical to the real 27-Aug run) and clean JSON/DB parity.
  Two earlier attempts (04:34, 05:01) *did* 429 — not the fix failing, but the
  old code's 04:06 spend still inside the rolling window. That is also how the
  window was measured: 05:01 is a fresh clock hour and was still limited, so
  the budget is rolling, not hour-boundary. **PCCG is effectively
  single-tenant per IP** — a second run inside the hour still collides, which
  the app-side scheduler should guard with a "ran recently" check.
  **Proven on the real path 11:21** at the user's request: the 27th was deleted
  outright (441 DB rows + all four JSON files, after taking rollback copies of
  both) and rebuilt by a normal `run_daily.py`. Result: 2 Algolia queries,
  **0 rate-limit warnings, 0 ERRORs, no cooldown**, 442 rows ingested, parity
  clean. PCCG came back **byte-identical** — cpu 21/21 and gpu 100/100 exactly
  matching the pre-delete backup. Scorptec moved 284 -> 285 GPUs, which is real
  intraday movement (a new Palit RTX 5080 listing; RTX 5060 Ti Dual $749 ->
  $699), not a fault.
  Empty-catalogue now trips the breaker directly (a block, not an empty shop);
  the consecutive-failed-batches breaker is gone with the batching.
  `algolia_single_search` / `algolia_batch_search` are retained for manual
  one-off queries and marked **deprecated** so the per-product path is not
  rewired. New `unit_testing/test_pccg_query_budget.py` (7 tests) pins the
  2-query budget. `CLAUDE.md` and `docs/ARCHITECTURE.md` corrected — both
  previously prescribed the wrong remedy.
  Regression: pytest **629**. Frontend untouched (backend-only change).
  **Follow-up:** `BATCH_SIZE`, `BATCH_DELAY`, `ALGOLIA_CIRCUIT_BREAKER_LIMIT`
  and `ALGOLIA_BATCH_MAX_PAGES` are now unused by the pipeline but still
  imported in `scraper/pccg.py` because `test_config.py` asserts they are
  re-exported; retiring those knobs is a separate cleanup.

- **2026-08-27** — **Daily run for the 27th executed manually** — no data existed
  for the day (latest JSON and `price_snapshots` were both 26-Aug). `run_daily.py`
  completed clean: 441 snapshots inserted, 0 skipped, 0 errors (scorptec 320 /
  pccg 121, in line with the 26th's 319/122); all four JSON snapshots full-size;
  JSON⇄DB parity clean; 40 DB warnings, all `price_anomaly` (informational);
  delisted check 6/6 active; Discord digest sent; backup written.
  PCCG GPU hit the rate limiter and gave up after 3 retries on page 1, but the
  later pages succeeded and `gpu_pccg_27_August_2026.json` landed at 45,558 B
  vs the 26th's 46,024 B — no meaningful loss, and no cooldown file was written.
  **Gap found: nothing schedules this run.** There is no Trackaroo Docker image,
  no container, and no Windows scheduled task on the host, so the "daily"
  pipeline only runs when invoked by hand — which is why the 27th was empty and
  why run times across the week are ragged (04:26, 06:09, 09:25, 03:40).
  Automating it is the next task.

- **2026-08-25** — **`/products` rebuilt as a search-first index**, per
  [`docs/superpowers/specs/2026-08-25-product-index-design.md`](docs/superpowers/specs/2026-08-25-product-index-design.md)
  and its plan. The card grid was a *browse* layout for a *find* job. Now one
  search box and one dense row per product, filtered **in the browser** — the
  whole category (~50 rows) ships on load, so the 450ms debounce and a server
  round trip per keystroke are gone. Empty box shows the catalogue grouped
  **brand-major, newest generation first** with non-collapsing headers from the
  existing `generationTierLabel`; typing gives a flat ranked list, `Enter`
  opens the top hit, `Escape` clears, `/` focuses.
  **Matching is shared with the Ctrl+K palette** (`productSearch.ts`) so the
  two surfaces cannot rank the same catalogue differently — the palette gained
  ranking, having previously done an unranked substring filter.
  **The index starts from the watchlist, not from what has been scraped** —
  39 of 100 tracked products have never matched a listing, and omitting them
  made a search for a tracked model answer "no match". Rows now say
  **Not listed** (never seen at a retailer) as distinct from **No stock**, and
  the header reads "47 tracked · 23 seen at a retailer".
  **Removed:** `ProductCard`, `Filters`, the retailer chip row from stage 4
  (superseded by the search box), and server-side search/sort for this route.
  **Intel Arc was mis-tagged** — A380/A750/A770 (Alchemist) and B570/B580
  (Battlemage) were all `current` with no `intel-gpu` label, so two generations
  would have shared one generic heading. Retagged, with proper labels.
  **That exposed a seeding bug:** the watchlist calls itself the source of
  truth, but `seed.py` skipped existing products outright, so the retag could
  never reach the DB. `seed_products` now syncs `generation_tier` for existing
  rows (reported as `updated`, honoured by `--dry-run`).
  Regression: pytest **622** / svelte-check 0 errors, 0 warnings / vitest
  **373** / e2e **59** / build green / Docker image built and booted.

- **2026-08-25** — **Two honesty fixes on the product page**, both from user
  feedback. **(1) The price-range bar compared two different series**: the low
  was the cheapest listing per day, but the high was the *dearest* listing per
  day, so today's cheapest offer was plotted against the worst price any
  retailer ever asked. 70% of bars had the marker pinned in the bottom fifth
  and only one product sat above the midpoint. Both ends now come from the
  cheapest-per-day series; afterwards 50% sit in the bottom fifth (genuine —
  77% of products really are at their all-time low) and 9 sit above the
  midpoint. Labels are now "Cheapest/Dearest" with a caption naming the series
  and day count. **A flat range no longer claims a single reading** — 24 of 44
  products have never changed price, and used to render "Only one price
  recorded so far"; they now say "Price has held at $120 for all 17 days
  tracked". **(2) "30d avg" overstated the evidence** — the SQL window is 30
  days but the dataset spans 17. New `avgWindowLabel()` states the real
  contributing day count ("vs 17-day avg") and grows into "30-day" on its own.
  Rule-level prose ("below their recent average") is now separate from
  evidence-level numbers. Regression: pytest **619** / svelte-check 0 errors,
  0 warnings / vitest **364** / e2e **63**.

- **2026-08-25** — **Fixed: the Docker container could not start at all.**
  `docker run` died instantly with
  `[FATAL tini (7)] exec /usr/local/bin/trackaroo-entrypoint failed: No such
  file or directory`. The file was present and executable — the path in that
  message is a red herring. `deploy/entrypoint-single.sh` reached the image
  with **CRLF endings**, so the shebang read `#!/bin/sh` + CR and Linux tried
  to exec an interpreter literally named `/bin/sh<CR>`; that ENOENT is
  reported against the *script*, so it reads like a missing `COPY`.
  **The CRLF was never committed.** Git stores these scripts as LF and always
  has — the blob is byte-identical from the commit that added it to today. The
  conversion happens on **checkout**: Git for Windows sets `core.autocrlf=true`
  at *system* scope, and with no `.gitattributes` every Windows clone
  materialised `deploy/*.sh` with CRLF, which `docker build` then copied into
  the image. So it was broken for anyone building on Windows with a default
  Git install, and fine on Linux/macOS — which is how it survived a
  "verified live" note.
  Proven at two levels: the working-tree script mounted into a bare
  `debian:bookworm-slim` reproduces the error while the byte-identical
  CR-stripped file runs fine; and a fresh `git clone` of the parent commit
  yields `CR=162` on that script versus `CR=0` with `.gitattributes` present.
  Three layered guards: **`.gitattributes`** pins `*.sh`/`Dockerfile` to
  `eol=lf` (the actual fix); the **Dockerfile** strips CRs after `COPY` and
  runs `sh -n` on each script so an archive/zip checkout fails the build rather
  than the first boot; and **`unit_testing/test_shell_scripts.py`** (7 tests)
  fails the suite on any tracked `*.sh` whose working copy contains a CR.
  **Verified by actually running it this time:** image rebuilt, container
  booted against the live `db/` and `data/` mounts — all five routes (`/`,
  `/deals`, `/products`, `/movers`, `/compare`) return **HTTP 200**, container
  clock reports **AEST** matching the host with `date.today() = 2026-08-25`,
  boot catch-up correctly skipped because today already has snapshots,
  scheduler armed for 04:00 Australia/Melbourne.
  **Process gaps closed:** pytest/vitest/Playwright never build the image, so a
  green regression run said nothing about whether the app starts — `CLAUDE.md`
  now requires a Docker build-and-boot for changes touching the `Dockerfile`,
  `deploy/`, or container-executed code. Also noted there: `grep -c $'\r'`
  under Git Bash reports false positives and misled the first pass of this
  investigation; count bytes in Python instead.

- **2026-08-25** — **Nav + six-retailer prep — the price-first IA spec is now
  fully implemented (stages 1–4)**, per
  [`docs/superpowers/plans/2026-08-25-nav-and-six-retailer-prep.md`](docs/superpowers/plans/2026-08-25-nav-and-six-retailer-prep.md).
  Nav is now **Deals · GPUs · CPUs · Movers · Compare** — Deals first, category
  a *place* (`/products?category=…`) rather than a filter re-applied everywhere,
  and Compare no longer an orphan reachable only via checkboxes. Active-state
  matching moved to a pure `isActiveLink` in `web/src/lib/nav.ts`: the old
  `path === link.href` check compared a pathname against a string containing a
  query, so **neither category link could ever have highlighted**. The nav
  renders `aria-current="page"`, and below `md` it is a horizontally scrollable
  row, not a hamburger.
  `/products`' retailer `<select>` became a **URL-driven chip row**, making
  `FacetChips` serve three drivers (product page client-side; `/deals` and
  `/products` URL-driven server-side) — deliberately **not** unified, per §7.
  Chip options come from counts over the current result set, so a count always
  equals what a click produces and a retailer with no rows shows no chip.
  **Six-retailer registry** — `Retailer`, `RETAILER_OPTIONS` and
  `notify_discord.RETAILER_LABELS` now carry `mwave`, `umart`, `centrecom`,
  `ple`. **No scraper exists for any of the four**; this is display-side only,
  so landing one is a pipeline change rather than a UI change.
  `/compare` with no `ids` now renders an empty state explaining how to select
  (a request naming exactly one product is still a 400). Dataset stats
  (snapshot days, DB size) moved from the header into the homepage health strip.
  Also fixed a brittle `parseFilters` test that routed any unrecognised slug to
  `tier`, so adding a retailer failed it for an unrelated reason.
  Regression: pytest **612** / svelte-check 0 errors, 0 warnings / vitest
  **357** / e2e **63** / build green.

- **2026-08-25** — **Homepage dashboard rebuilt** — stage 3 of
  [`docs/superpowers/specs/2026-08-23-price-first-ia-design.md`](docs/superpowers/specs/2026-08-23-price-first-ia-design.md)
  (§5), per [`docs/superpowers/plans/2026-08-25-homepage-dashboard.md`](docs/superpowers/plans/2026-08-25-homepage-dashboard.md).
  `/` now answers three questions in order: can I trust this data (a
  **data-health strip** with a per-retailer freshness pill), is anything worth
  buying (**top deals**), what changed (**biggest 7-day drops and rises**),
  split into a GPU and a CPU section. New `getRetailerFreshness` and
  `getCategoryCounts` queries; freshness classification is pure in
  `web/src/lib/health.ts`.
  **Three freshness states, not two** — the spec leaves one-day-behind unnamed,
  yet it is the normal state before the 04:00 run, so `fresh` / `recent` /
  `stale` (≥2 days). **"Cooling down" is deferred**: telling an intended PCCG
  breaker pause apart from real staleness would couple the web app to
  `data/pccg_cooldown.json`; until then it reads as stale, in a warning tone,
  never an error tone.
  Top deals reuse `deals.ts` rather than re-ranking, so `/` and `/deals` can
  never disagree; movers use a **fixed 7-day window** (a 24h window is one
  snapshot pair and a missed run would empty the section). A product can appear
  as both a deal and a mover — different questions — and e2e asserts that.
  **Removed:** the four stat tiles, `CheapestCarousel`, the filter-and-sort
  listing table, and `getSummary`/`Summary` (no remaining caller). The `90d low`
  badge lived only on the carousel and is gone from the product; `/deals`'
  at/near-all-time-low section and the product headline carry that signal
  better. `Filters.svelte` is now used only by `/products`, so its e2e coverage
  moved there rather than being dropped. Regression: pytest **611** /
  svelte-check 0 errors, 0 warnings / vitest **342** / e2e **60** / build green.

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
  - Routes — `/deals` (below-30d-average + at/near-all-time-low sections, URL-driven chip facets), `/` dashboard (data-health strip + per-category deals/drops/rises sections), `/products` (card grid with per-card trend sparklines + expandable variant listings with inline 7-day trend sparklines + compare selection), `/compare` (side-by-side specs + prices), `/movers` (dense table with window-matched trend sparklines), `/product/[id]` with URL-driven filters; global command palette (Ctrl/Cmd+K) on every page
  - `test/` — vitest, **357 tests** across 17 suites (run `npm test` for the current breakdown)
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
- **Frontend:** `svelte-check` 0 errors; vitest **357 passing**; Playwright e2e **63 passing** (real + synthetic seeds); production build green; live `adapter-node` smoke test of all routes against the real DB (dashboard/products/movers/product 200s, unknown product 404, bad window param falls back)
- **Docker:** single all-in-one image built and booted — DB seeded, both scrapers OK, 315 listings ingested, backup created, dashboard HTTP 200 with live stats
- **Feature suggestions §2–§4:** band chart + brand-grouped listings on `/product/[id]`, `/compare?ids=` (2–4 same-category products), `90d low`/`90d high` on product page + dashboard cards — regression green after each milestone
- **Troubleshooting:** the temporary `/troubleshooting` view + `/api/health` JSON built on 18-Aug were **removed** the same day once the PCCG cooldown behaviour and compare/specs issues were confirmed settled — `getCoverageSummary`, its routes, and their tests are gone (see the UI follow-up entry)
- **Regression:** backend **619** passing (pytest); frontend **357** passing (vitest) + 63 e2e (Playwright, real + synthetic)
- **Command palette + sparklines (18-Aug):** Ctrl/Cmd+K palette searches the tracked catalog from any page and Enter-navigates to a product (quick "Compare A vs B" when exactly two match); `/products` card tables, the `/` dashboard table, and the `/movers` table all show per-listing trend sparklines (up=red / down=green, dash when <2 points), and each unexpanded `/products` card shows its cheapest-in-stock trend line — regression green after the batch
- **Round-3 enhancements (18-Aug):** palette results show per-product snapshot counts; dashboard + movers tables have tri-state sortable column headers; the product-page price chart is reactive (re-creates uPlot on prop change — fixes stale chart on navigation AND the inert "Show on chart" toggle); variant names are display-cased consistently (`titleCase()`) at every render site while the DB stays raw; specs confirmed healthy (95 rows / 0 orphans / 95 covered) — the empty-look was a stale Docker DB. Regression: pytest 391 / svelte-check 0 / vitest 187 / e2e 46 / build green.
- **Brand icons + UI polish + Discord digest (19-Aug):** simple-icons AMD/NVIDIA/Intel marks in header, cards, compare + footer (tree-shaking verified); product-page "Updated X ago" freshness, unified card heights + empty-state panels; `notify_discord.py` digest gated on healthy runs (dry-run printed the real digest against live data — 3 moves: RTX 5070 Ti +10.2%, RX 9070 +5.6%, RTX 5070 +4.4%). Regression: pytest 461 / svelte-check 0 / vitest 204 / e2e 48 / build green.
- **Price-drop & restock alerts (20-Aug):** `price_alerts` table + idempotent migration; `check_alerts.py` (price-drop with further-drop re-fire, restock with 24h cooldown, price precedence, cooldowns advance only on successful delivery, stdlib Discord/SMTP/webhook delivery — never raises) wired into `run_daily.py` after a healthy ingest; product-page "Price alerts" panel (arm/list/delete) via a dedicated write DB connection. Regression: pytest **522** / svelte-check 0 / vitest **231** / e2e **51** / build green.
- **Delisted-listing detection (20-Aug):** `check_delisted.py` re-fetches active Scorptec listings missing from today's grid scrape and marks them `delisted` on a positive 404/410 or "No Longer Available" marker (unknown pages left untouched; retries on CDN throttling; per-run fetch cap + 1.5s inter-fetch delay); wired into `run_daily.py` after a successful Scorptec scrape (best-effort). Dashboard: "Delisted" badge instead of price + stock, excluded from in-stock count and group price range. Live run marked 5 delistings (incl. the 119183 repro). Regression: pytest **545** / svelte-check 0 / vitest **234** / e2e **52** / build green.

## What's NOT done yet

1. ~~**Hardcoded values review**~~ — **done 3-Sep.** Retailer half closed
   31-Aug (`config.ACTIVE_RETAILERS` / `migrate.PERMITTED_RETAILERS`). The
   rest closed 3-Sep: match-count fallback thresholds, the shared alert
   delivery timeout, and the restock cooldown are all `config.py` env knobs
   now. `BATCH_SIZE` and three siblings are dead code (unused since the
   Algolia catalogue-fetch rewrite), not hardcoded — retiring them is a
   distinct cleanup, still open, tracked in CLAUDE.md.
2. **Frontend (Phase 3) — complete.** M0–M5 done: views, polish/verify, units + e2e. Remaining: final visual QA eyeball (any new filters/hardening belong to Phase 4).
3. **Detailed deployment** — done: single Docker image + compose split verified. Optional extras for later: reverse proxy (Caddy/nginx/Traefik) for TLS, host-cron option docs already in DEPLOYMENT.md.
4. **Hardening (Phase 4, remaining)** — reverse proxy/TLS, Prometheus-style monitoring, alerting on pipeline failure (current: exit codes + logs).
5. ~~**Price anomaly detection**~~ - **done 31-Aug.** Options (b) + (c) + (e)
   from the analysis below were implemented together: the sigma gate is now
   **10** prior points (matching what a 3-sigma trip can actually reach), the
   baseline **excludes the point being tested**, and a day-over-day
   `PRICE_MOVE_PCT` rule (default 0.20) covers the listings the sigma test
   structurally cannot. (e) turned out to be load-bearing rather than optional:
   once today's point leaves the baseline, a flat price history has a prior
   sigma of exactly 0, so the z-test is blind to a jump of any size and the move
   rule is the only rule that can see it. A same-day follow-up made it an
   **event detector** too - only listings whose price actually changed since the
   previous snapshot are evaluated - because otherwise a step change alarms every
   day for weeks after the fact. See the 31-Aug entry for the sqrt(N)
   artefact this uncovered in the old implementation. Remaining option **(d)**,
   median + MAD, is *not* done and is still a reasonable future refinement if
   the sigma test proves noisy on real spikes.

6. **RAM tracking (RAM_SCOPE.md)** — planned but not started; not required for Phase 3/4
7. **Retailer four (Mwave) — decision pending.** *Retailer three shipped
   31-Aug: Umart is scraping, ingesting and wired end to end (see that day's
   entries).* The `CHECK`-constraint migration is done, so **mwave needs no
   migration** — it is a scraper plus one line in `config.ACTIVE_RETAILERS`.

   What the 31-Aug probing established: `/graphics-cards` is a curated landing
   page, and the real endpoint is `/searchresult?...&cnt=100&srt=<offset>`,
   server-rendered, **100 products per request** out of 278. **But the WAF limit
   is a count, not a rate** — five requests then challenged, at 5s *and* 30s
   spacing — so a ~5-request run sits exactly on the allowance with **no
   headroom for a retry**. A challenged fetch must abandon the day.

   **That fragility is the decision**, not a detail to engineer around: accept
   intermittent gaps, or spread a run over ~4 cold periods (~3 hours), which is
   a different scraper from anything here. Recorded in
   [`THIRD_RETAILER.md`](docs/proposals/THIRD_RETAILER.md) and
   [`mwave-waf-probe.md`](docs/proposals/mwave-waf-probe.md);
   [`2026-08-31-mwave-scraper.md`](docs/superpowers/plans/2026-08-31-mwave-scraper.md)
   is **superseded in part** (its Tasks 2-4 target the wrong URL).
   **Centre Com stays ruled out**; PLE is a genuine client-rendered SPA.

8. ~~**Listings that never age out**~~ — **done 3-Sep.** `check_delisted.py`
   still only watches Scorptec, but `check_stale_listings.py` is now the
   retailer-agnostic net beneath it, wired into `run_daily.py`. See the
   3-Sep entry in Recent changes.

## Next up (planned 18-Aug — picked up tomorrow)

### ✅ Price-drop & restock alerts (Discord-first) — done 20-Aug
Shipped per the agreed design — see the "COMPLETE: Price-drop & restock alerts" entry in Active Issues. The daily Discord digest (`notify_discord.py`) from the polish/notifications batch shipped alongside it on 19-Aug.

### Backlog (UX, ranked by value/effort)
1. ✅ **Products-page filters** — done (pre-existing): `/products` grid already has category/retailer/brand/generation selects + debounced text search + in-stock toggle + sort (see `web/src/lib/components/Filters.svelte`).
2. ✅ **"Since tracked" stat chips** — done 20-Aug: product page shows **All-time low / All-time high** (the band was always unwindowed) + a **30d avg** chip (mean of per-day cheapest in-stock over the trailing 30 days, ≥3 days of history).
3. ✅ **Deal highlight** — done 20-Aug: green **Deal** badge on `/products` cards + the dashboard carousel when the cheapest in-stock price is below the 30-day average (binary, ≥3 days of history).
4. ✅ **Mobile responsiveness pass** — done 27-Aug. Audited at 320px/390px:
   no route overflowed (the `md:` table-to-card split already covered phones),
   so the item was largely stale. Fixed the one real defect — the `/products`
   compare checkbox was a bare 13x13px input, under the WCAG 2.2 AA 24x24
   minimum. Pinned by `web/e2e/mobile.spec.ts`.
5. ~~**RSS feed of biggest movers**~~ — dropped 27-Aug, not wanted.

## Next concrete steps

> [`docs/superpowers/plans/2026-09-01-next-steps.md`](docs/superpowers/plans/2026-09-01-next-steps.md)
> is **fully closed out as of 3-Sep-2026**: Task 0 (deploy to prod) confirmed
> done by the user, Task 1 (age out stale listings) shipped, Task 2 (Mwave)
> decided — parked, not built (see Recent changes and
> `docs/proposals/THIRD_RETAILER.md`). Task 3 (confirm the weekly spec sync
> fires on prod) was never explicitly checked — worth a look next time
> someone's on the prod host, but low urgency.
>
> No specific task is queued next. The remaining lower-priority backlog
> lives in "What's NOT done yet" above — items 1 (hardcoded-values review,
> partly done), 4 (reverse proxy/TLS, deferred by design), and 6 (RAM
> tracking, not started, not required).


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

Current, as of 29-Sep-2026:

| Suite | Tests | Command (from) |
|---|---|---|
| Backend (pytest) | **853**, all passing | `python -m pytest -q` (repo root) |
| Frontend unit (vitest) | **425** | `npm test` (`web/`) |
| Frontend e2e (Playwright) | **70** | `npm run test:e2e` (`web/`) |
| Type + Svelte check | 0 errors | `npm run check` (`web/`) |

The per-module breakdown that used to live here went stale every session;
`pytest -q` and `vitest` are the source of truth. The 21-Aug snapshot of it
is preserved in
[`docs/archive/STATUS-history-to-2026-08-21.md`](docs/archive/STATUS-history-to-2026-08-21.md).

Backend suites added 23-Aug: `test_snapshot_io.py` (14), 
`test_export_snapshots.py` (16), `test_health_checks_backup.py` (15).

## How to update this file

Whoever (human or AI) makes progress on this project should update this file before ending their session: move completed items out of "Next concrete step" and into "What exists right now," add any newly settled decisions to the list above (with a corresponding entry in the decision log, `docs/ARCHITECTURE.md` Part 3, if it's a meaningful choice), and record any new open questions. This file is what lets the project be picked up cold — keep it honest and current rather than aspirational.