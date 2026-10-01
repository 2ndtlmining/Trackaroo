# New-part discovery: design

**Date:** 2026-10-02 · **Issues:** #16 (discovery report), #21 (watchlist gaps: track/ignore decisions)
**Status:** approved in conversation 2-Oct-2026, awaiting written-spec review

## 1. Purpose

When a retailer starts selling an in-scope CPU or GPU that Trackaroo does not
track (a new launch such as RTX 5050 or Core Ultra 7 270K Plus, or a variant
such as a GRE or X3D2), the owner should find out the same day, without
looking. They then decide per part: **Track** or **Ignore**.

Today nothing reports this. All three scrapers discard what they did not match
(Scorptec keeps it only for log lines, Umart assigns it to `_`, PCCG holds it in
a local). Since the exact-key matcher (`scraper/chip_key.py`, #1), an unknown
part is *dropped* rather than *mis-filed*, which is correct but silent.

### Benefits over today

| | Today | With discovery |
|---|---|---|
| New part launches | Found by accident, often weeks later | Discord message the first day any retailer lists it |
| Untracked variants | Silently dropped | Listed on /discover with prices, one decision each |
| Parked "Unmatched" parts (5500GT, 5600GT, 5800XT, 5900XT, 7700X3D, 9950X3D2) | No way to decide | Track or Ignore on /discover |
| Matcher mistakes | Found only by audits | "Conflicts" list shows them on the day |
| Adding a product | Hand-research the CSV row | Page gives the row ready-made |
| Extra retailer requests | – | None; PCCG stays at 2 queries |
| Risk to the daily run | – | None; best-effort, never ERROR |

### Success criteria

- A part first sold on day D appears on /discover and in one Discord message on day D.
- A tracked product never appears as untracked.
- An ignored part never notifies again; hourly retry runs never send a duplicate.
- A deliberately mis-filed listing shows under Conflicts.
- No change to snapshot JSON, ingest, the parity check, backups, or the PCCG 2-query budget.
- README.md contains a step-by-step guide with worked examples (section 9).

## 2. Decisions (owner, 2-Oct-2026)

| Question | Decision |
|---|---|
| Delivery | Discord message for **new parts only** (no daily repeats) + a **/discover** dashboard page with the full list |
| Track/Ignore | **Ignore is instant** (stored in the DB). **Track** marks the part `requested` and shows the watchlist row; Claude adds it to `db/watchlist.csv` in a PR; it goes live on the next `deploy/redeploy.sh`. The watchlist stays single-sourced in git. |
| Architecture | Option A: catalogue sidecar files → `discover.py` step → small tables |
| README | Must document the feature with a step-by-step guide and examples |

## 3. Out of scope (possible follow-ups)

- Backfilling price history from catalogue files when a part becomes tracked.
- The "in-scope catalogue coverage %" trend from #16.
- Opening the watchlist PR automatically.
- Login/auth for the dashboard (the buttons have the same exposure as the existing price-alert buttons).

## 4. Component 1: catalogue capture

**New module `scraper/catalogue_io.py`:**

- `save_catalogue(retailer, category, items, run_date, data_dir)` writes
  `data/catalogue_{retailer}_{category}_{DD}_{Month}_{YYYY}.json` (the same date
  format as snapshots), atomically: temp file + `os.replace`.
- File body: `{"retailer", "category", "date", "saved_at", "items": [{"title",
  "url", "price_aud", "in_stock", "sku"}]}`. `sku` is null when the retailer
  has none.
- **Not** via `save_snapshot`: this is a report, not a backup, so the
  never-shrink rule does not apply. A later same-day run replaces the file.
- `prune_catalogues(data_dir, keep_days=30)` deletes catalogue files older than 30 days.

**Scraper changes:** each scraper calls `save_catalogue` once per category,
at the moment it already flushes that category's snapshot and `RunReport`. A
scraper that dies mid-run still leaves the finished categories' catalogues.
The call is wrapped: a failure logs a WARNING and the scrape continues.

| Scraper | Source of the full item list |
|---|---|
| Scorptec | `all_scraped[cat_key]` (already built, `scraper/scorptec.py`) |
| Umart | the third return value of `scrape_umart` (currently `_`) |
| PCCG | the `algolia_fetch_catalogue` result, no extra query |

`ingest._SNAPSHOT_FILENAME_RE` does not match `catalogue_*`, so ingest, the
JSON mirror and `check_json_db_parity` ignore these files. A test pins this.
Backups cover the DB only, so catalogues add nothing to them. Size is about
1,000 items/day, around 250 KB/day, under 10 MB with 30-day retention.

## 5. Component 2: classification (`discover.py`)

Reads **today's** catalogue files. Every item takes the first outcome that applies:

| # | Check | Outcome |
|---|---|---|
| 1 | `chip_key.is_excluded(title)`, extended with: refurbished, open box, ex-demo, RTX PRO, Radeon Pro, Quadro, Threadripper, Xeon, EPYC | dropped (counted) |
| 2 | `chip_key(title, category)` is None | **unrecognised** (counted; up to 20 sample titles kept for the page) |
| 3 | key's series not in the scope table | dropped (out of scope) |
| 4 | `Matcher(watchlist).resolve(title, category)` returns a row | **tracked** (not a discovery) |
| 5 | part key's status is `ignored` | hidden (`last_seen` still updated) |
| 6 | otherwise | **untracked part** |

**Part key** = chip key, plus `|<vram>` for GPUs when `parse_vram` finds one
(e.g. `rtx 5050|8`), so memory variants are distinct parts, consistent with #2.
GPU items without a parseable VRAM group under the bare key.

**Scope table** (`discover.SCOPE`): in-scope series per product line,
transcribed from `docs/ARCHITECTURE.md` Part 2:

- NVIDIA: RTX 50, 40, 30
- AMD GPU: RX 9000, 7000, 6000
- Intel GPU: all Arc desktop GPUs, A-series and B-series, with no exclusion tier (Part 2 §5)
- AMD CPU: Ryzen 9000, 7000 (incl. 8000G APUs), 5000
- Intel CPU: Core Ultra 200 (incl. 200S Plus), Core 14th and 13th Gen

A series newer than everything in the table for its line (e.g. RTX 60) is
treated as **in scope**, so a new generation surfaces instead of being
silently dropped. Two tests guard the table: every tracked watchlist product's
key is in scope, and table entries match ARCHITECTURE Part 2.

**Display name** is built from the key in the watchlist's naming style
("GeForce RTX 5050 8GB", "Ryzen 5 5600GT", "Core Ultra 7 270K Plus").

**Suggested watchlist row:** `category,brand,model,spec,gen_tier,search_aliases`.
GPU spec comes from the VRAM. A CPU's core count is rarely in shop titles, so
the row shows `?c` and Claude fills it in from the spec source in the PR.
`gen_tier` comes from the scope table.

**Conflicts.** For every `retailer_listings` row with status `active` that is
filed under a tracked product, run `resolve` on its title. It is a conflict if
the result is a **different** tracked product, or **none**. Listings under the
hidden "Unmatched" placeholders are not conflicts.

## 6. Component 3: storage, Discord, health

**Tables** (DDL in `migrate.py` + `db/schema.sql`; applied automatically on
container start by the entrypoint's `migrate.py`):

`discovered_parts`: `id`, `category`, `part_key` (UNIQUE with category),
`display_name`, `status` (`untracked` | `ignored` | `requested` | `tracked`),
`first_seen`, `last_seen` (dates), `listing_count`, `retailers` (comma list),
`min_price`, `min_price_url`, `sample_titles` (JSON, ≤5), `suggested_row`,
`notified_at`, `decided_at`.

`discovery_conflicts`: `listing_id`, `filed_product_id`, `resolved_product_id`
(nullable), `title`, `detected_on`. Replaced wholesale each run.

`discovery_runs`: `run_date`, `finished_at`, `catalogue_files` (count),
`missing` (JSON list of retailer/category with no file today),
`unrecognised_count`, `unrecognised_samples` (JSON). One row per run, keeping
the last 30. The page reads its freshness from here.

**Upsert rules.** A new key inserts with `status=untracked`,
`first_seen=today`. An existing key updates its counts, retailers, price and
`last_seen` **only**; `status`, `notified_at` and `decided_at` are never
overwritten by a run. A part whose listings now resolve to a tracked product
flips to `tracked` (this is how a Track request completes after deploy).
**Bootstrap:** the first run sets `first_seen` for parts already in the
"Unmatched" placeholders to their earliest snapshot date.

**Discord.** After the upsert, parts with `status=untracked` and
`notified_at IS NULL` are sent as one embed, **"New parts at retailers"**, to
`DISCORD_WEBHOOK_URL`. Each line gives the name, listing count, retailers,
lowest price and a link to /discover (`TRACKAROO_PUBLIC_BASE_URL` when set).
`notified_at` is stamped only on a 2xx response, so a Discord outage retries
on the next run. The embed is not gated on the health-check result (unlike
the price digest). Nothing new means no message. No webhook configured means
it is skipped silently.

**Health.** `check_discovery` returns a **WARNING** when there are new parts
today or the conflict count is above 0, otherwise OK. It never returns ERROR
and is run through `guarded_check`.

**Pipeline wiring.** In `run_daily.py`, after ingest and the JSON mirror:
`best_effort("discovery", discover.run, ...)`. `prune_catalogues` runs
alongside log pruning.

## 7. Component 4: the /discover page

SvelteKit route `web/src/routes/discover/`. Reads through `getDb()`, writes
through `getWriteDb()`. Added to the header nav as "Discover", with a count
badge when untracked parts are waiting.

1. Summary: "N new this week · N untracked · N conflicts · last checked <date time>". It shows a stale notice if the latest `discovery_runs` row is not today, and names any missing catalogues.
2. **Untracked** table, newest first: part (NEW badge if first seen within 7 days), first seen, listings, retailers, from-price (link ↗), [Track] [Ignore]. A row expands to its sample titles. Parts not seen today are greyed with "last seen <date>".
3. **Requested**: parts marked Track, each with its suggested row in a copy box.
4. **Conflicts**: title, filed under, matcher says. When empty: "None — every listing matches its product."
5. Collapsed: **Ignored** (with Un-ignore) and **Unrecognised titles**.

Actions (SvelteKit form actions, POST, full-navigation like the price-alert
forms): `ignore`, `unignore`, `track`, `untrack`. They act on `id` and set
`status` + `decided_at`. An unknown id or an invalid transition returns a
400. At 390 px the table renders as a single-column list (the /movers pattern).

## 8. Error handling

- `save_catalogue` failure: WARNING in the log, the scrape continues, prices are unaffected.
- `discover.run` crash: caught by `best_effort` (logged ERROR); alerts, digest and backup still run.
- A missing or corrupt catalogue file: skipped and recorded in `discovery_runs.missing`, the rest still processed.
- No catalogues today: no upsert, and the page shows the last run's results with its date.
- Discord failure: logged with the host only (never the webhook URL), retried next run.

## 9. README requirement

README.md gains a section **"Discovering and adding new parts"**:

1. What it does, and how the Discord message and /discover fit together.
2. A worked example: RTX 5050 appears → Discord message (sample text) →
   /discover row → **Track** → the suggested row
   (`gpu,NVIDIA,GeForce RTX 5050,8GB,current,"rtx 5050"`) → PR adds it to
   `db/watchlist.csv` (CPU example with `?c` → `6c` filled from specs) →
   merge → `deploy/redeploy.sh` outside 04:00–09:59 → next run flips it to
   `tracked`, and it appears under /products.
3. Ignoring and un-ignoring (example: Ryzen 5 5600GT).
4. Reading a conflict and what to do (example row, then fix the watchlist or report a matcher bug).
5. When a new generation launches: update `discover.SCOPE` and ARCHITECTURE Part 2 together.
6. Troubleshooting: no Discord message, a part shown as unrecognised, catalogue retention, the stale-run notice.

The work is not complete until this section exists and its examples match the
shipped behaviour.

## 10. Testing

**pytest:**
- A fixture catalogue with a made-up "RTX 6070" and a real "RX 9070 GRE 16GB" yields both as untracked.
- Tracked products never appear.
- Excluded and out-of-scope titles are dropped.
- An ignored part never notifies; a second same-day run sends nothing; a failed send retries.
- Upsert never overwrites status or decisions.
- A requested part flips to `tracked` once the watchlist resolves it.
- A planted mis-filed listing shows as a conflict.
- Every tracked product is in scope.
- Ingest ignores `catalogue_*`.
- PCCG still makes exactly 2 queries (`test_pccg_query_budget.py`).
- `check_discovery` never returns ERROR.
- `save_catalogue` failure does not fail a scrape.
- Pruning keeps 30 days.

**vitest:**
- The /discover load function and each action, including invalid transitions, against a seeded test DB.

**Playwright:**
- The page renders seeded parts.
- Ignore hides a row and Un-ignore restores it.
- Track shows the suggested row.
- Conflicts render.
- The mobile layout works at 390 px.

**Gate:** all four suites green (pytest, svelte-check, vitest, Playwright),
CI green, and the offline image boots healthy.

**After deploy:** on day one, compare /discover against the retailers' own
listings by eye, then close #16. Close #21 once the parked parts each have a
decision.
