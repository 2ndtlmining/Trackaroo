# Generations, retirement and the watchlist CLI — design

**Date:** 2026-10-06
**Issues:** #17 (generation launches), #18 (retiring products), #19 (`manage_watchlist.py`)
**Status:** approved in brainstorm 2026-10-06; awaiting written-spec review

## Why

Zen 6 and a new GPU generation are expected soon. Today a generation launch is a
10-12 file hand edit (watchlist retags, `RETIRED_PRODUCTS`, `tiers.ts` labels,
tests, docs), and the web labels only change with a web rebuild. The owner also
wants old parts to stop being tracked once retailers stop selling them.

**Success:**
- A launch is one config line plus the new SKU rows (plus their MSRPs).
- Retirement is one CSV value, reversible, and can never happen silently in bulk.
- Parts that vanish from every retailer are *suggested* for retirement; the owner
  confirms. Nothing untracks without the CSV changing.

## Decisions (owner, 2026-10-06)

- Data model: issue #17 option A (config file, derived tier, labels from DB).
- Retirement: two mechanisms, both ending in a CSV `status`:
  - **(c)** a series falling off the end of its line retires the whole generation;
  - **(a)** a "ready to retire" list flags single tracked products with no
    snapshot anywhere for 30 days; the owner confirms each one.
- Fully automatic untracking (option b) rejected: CSV/DB drift and flicker.
- Delivered as three PRs (below), each green on its own.

## 1. Data model

### `db/generations.toml` (new, read with stdlib `tomllib`)

One `[[line]]` per product line, series newest first:

```toml
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)" },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)" },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)" },
]
```

- Five lines: `amd-cpu`, `intel-cpu`, `nvidia-gpu`, `amd-gpu`, `intel-gpu`
  (line id = `lower(brand)-category`, the same key `tiers.ts` uses today).
- Optional `keep_all = true` on a line: every series stays tracked regardless of
  position (Intel GPU, replacing the "track all Arc" scope rule).
- Labels are exactly today's `TIER_LINE_LABELS` strings, so the first deploy
  changes no visible text.
- Keys are unique within the whole file (a key names one series everywhere).
- Each series also has a `chips` list for discovery (see "Discovery scope").

### `db/watchlist.csv`

- `gen_tier` column replaced by **`series`** (a key from the toml). Ryzen 8000G
  rows are tagged `zen4` explicitly (the reason the tier is never inferred from
  the model number).
- New **`status`** column: `active` | `retired`.
- Rows are never deleted again. `RETIRED_PRODUCTS` (`migrate.py:329`, only
  `Radeon RX 9070 XTX`) becomes a `retired` row and the tuple, its migration
  function and its CSV-pairing test are removed. The header comment block is
  rewritten to describe series/status.

### Derived values

- **position** = index of the row's series in its line (0 = newest).
- **generation_tier** = `current` / `current-1` / `current-2` for positions
  0 / 1 / 2. Position >= 3 (or `status = retired`) keeps the product's last
  stored tier — the column is "where it sat", per its schema comment — so the
  `CHECK` constraint does not change. A row that is new *and* already retired
  gets `current-2`.
- **tracked** = `status == active AND (position <= 2 OR line.keep_all)`.

### Schema (`db/schema.sql` + idempotent `migrate.py` step)

- `products.series TEXT` (nullable; NULL for holding-brand `Unmatched` rows and
  any product not in the CSV).
- New table `generations (line_id TEXT, series_key TEXT PRIMARY KEY, label TEXT
  NOT NULL, position INTEGER NOT NULL, keep_all INTEGER NOT NULL DEFAULT 0)`,
  fully rewritten by seed each run (it mirrors the toml; no history).

### Web

- Product queries join `products.series -> generations.label`; DTOs carry a
  `seriesLabel` (nullable).
- `generationTierLabel()` keeps its signature role but takes the DB label first
  and falls back to `GENERIC_TIER_LABELS`; `TIER_LINE_LABELS` is deleted.
- `/products` group headers come from the DB label. A relabel or a new series
  shows without a web code change.

### Watchlist loader and scrapers

`db/watchlist.py` loads the CSV + toml and returns each row with its `series`,
`status`, derived `gen_tier` and `tracked`. The scrapers keep reading
`wp["gen_tier"]` (now derived) and keep writing `watchlist_gen_tier` into the
JSON, so the JSON format, `ingest.py` and `export_snapshots.py` are unchanged.

### Matching ("sinks")

Retired rows stay in the scrapers' watchlist: a listing whose chip key equals a
retired row's matches that row, so e.g. retired RTX 3060 Ti listings can't fall
onto the RTX 3060. Matches to a retired row are **dropped** from the snapshot
output (logged as a count per run), so retired products get no new snapshots and
nothing downstream changes. Retired products are hidden from the dashboard
exactly as `tracked = 0` products are today.

### Discovery scope (`discover_rules.py`)

Its hard-coded tier tables (`_GPU_TIERS`, `_RYZEN_TIERS`, `_CORE_TIERS`, the
Arc and Ultra branches) are a fourth copy of the generations and would go stale
at a launch. Each toml series gains a `chips` list of `"family:gen"` tokens in
the terms `series_tier()` already parses, e.g. `rtx50 -> ["rtx:5"]`,
`zen4 -> ["ryzen:7", "ryzen:8"]`, `arrow-lake -> ["ultra:2"]`,
`raptor-14 -> ["core:14"]`, `battlemage -> ["arc:b"]`. `series_tier()` keeps its
parsing and workstation filters but looks the token up in the toml: tier =
the series' position (positions >= 3 are out of scope -> `None`, unless the line
is `keep_all`); a numeric gen **newer** than every known gen of that family stays
`current` (a launch surfaces instead of being dropped); older unknown gens stay
`None`. `test_discover_rules.py` pins the toml instead of its own table.

## 2. Seeding and safety (`seed.py`)

Per run:

1. **Load and validate** `generations.toml` and the CSV. Fatal (nothing written,
   message names the line): unknown/duplicate series key, unknown line, a CSV
   `series` not in the row's own line, a `status` value other than
   active/retired, a line with no series.
2. **Rewrite `generations`.**
3. **Per CSV row:** insert if new; otherwise sync `series`, `generation_tier`,
   `vram_gb`, `cores` and **`tracked` in both directions** (setting `status`
   back to `active` un-retires).
4. **Bulk guard:** if the run would flip `tracked` on more than
   5 products (flat limit, see Refinements: R7), abort before writing and list every flip, unless
   `--allow-bulk` is passed. `--dry-run` always lists the flips.
5. **Products in the DB but not in the CSV** (excluding brand `Unmatched`) are
   reported as warnings and never changed.

**Fresh-boot revival (#18).** Boot order (verified in `deploy/entrypoint*.sh`
and `bootstrap-data.sh`) is `seed.py` -> `migrate.py` -> hydrate via `ingest.py`.
Today a retired product has no CSV row, so on a fresh DB ingest recreates it as
`tracked=1`. With retired rows kept in the CSV, seed creates them `tracked=0`
before hydration and ingest finds them. A test rebuilds a DB from JSON in boot
order and asserts retired products stay at 0.

**Tests keyed to tracked rows:** the `SPECS_UNAVAILABLE_UPSTREAM`
(`sync_specs.py:366`) exact-set tests only consider tracked products, so a
retirement needs no test edit.

**First deploy:** `migrate.py` adds the column and table; the first seed
backfills `series` for every CSV product. Derived tiers are identical to today's
`gen_tier` values, so the expected result is **0 tracked flips** (the bulk guard
proves it). Prod's `redeploy.sh` needs no change; the container entrypoint does
not pass `--allow-bulk`, so a real rollover on prod is applied by the owner with
`docker compose exec trackaroo python seed.py --allow-bulk` after reviewing the
dry run (documented in the runbook section of ARCHITECTURE §7).

## 3. The "ready to retire" list

**Stale:** a product that is `tracked = 1`, was created more than 30 days ago,
and has **no snapshot at any retailer in the last 30 days**. Out of stock still
counts as live (the listing is still scraped). This covers every way a part
leaves a retailer without depending on per-retailer delisting signals. The
30 days is one config value (`TRACKAROO_RETIRE_STALE_DAYS`, default 30).

**Storage:** table `retire_suggestions (product_id INTEGER PRIMARY KEY
REFERENCES products(id), first_flagged TEXT NOT NULL, last_seen TEXT,
last_seen_retailer TEXT, decision TEXT NOT NULL DEFAULT 'pending' CHECK
(decision IN ('pending','requested','kept')), keep_until TEXT, notified INTEGER
NOT NULL DEFAULT 0)`.

**Daily step** (new module `retire_suggest.py`, run by `run_daily.py` after
ingest, best-effort like discovery):
- inserts newly stale products as `pending`;
- deletes `pending`/`kept` rows for products that are live again (a fresh
  snapshot) — `requested` rows are kept until the CSV retires them;
- deletes rows for products that are now `tracked = 0`;
- re-opens `kept` rows whose `keep_until` has passed (back to `pending`,
  not re-notified).

**Discord:** new-only, one embed listing products flagged for the first time
("Ready to retire: Ryzen 7 5800X3D — last seen 3 Sep at PCCG"), then
`notified = 1`. Same webhook and helpers as discovery (`notify_discord`).

**`/discover` page:** a "Ready to retire" section (product, last seen date,
retailer). Buttons:
- **Retire** -> `decision = 'requested'`; the row shows "Requested". Claude flips
  the CSV `status` in a PR (same flow as Track requests); seed applies it on
  redeploy and the daily step then drops the row.
- **Keep** -> `decision = 'kept'`, `keep_until = today + 90 days`.

Look and feel follows the existing `/discover` sections (Lucide icons, no emojis).

**Never** untracks anything itself.

## 4. `manage_watchlist.py` CLI

Edits files (CSV, toml); seed applies them. Only `reassign` writes the DB. Every
command has `--dry-run`, which prints the exact diff and writes nothing. File
edits preserve the CSV header comments and row order (new rows are appended
after the last row of the same line/series).

| Command | Behaviour |
|---|---|
| `rollover <line> --new <key> --label "<label>"` | Inserts the series at the top of the line in the toml; prints every derived retag and every retirement it implies (it computes tracked flips the same way seed does). |
| `add "<model>" --spec <16c\|16GB> --series <key> [--brand X --category Y]` | Appends an `active` row (brand/category inferred from the series' line). Computes the chip key (`scraper/chip_key.py`), refuses a collision with a sibling unless the spec (VRAM) differs, and prints the manual follow-ups: `launch_msrp.json`, `perf_index.json`, specs availability. |
| `retire <model>` / `retire --series <key>` / `retire --stale` | Sets `status = retired`. `--stale` reads `retire_suggestions` (pending + requested) from the DB at `TRACKAROO_DB`. |
| `reassign <listing_id> "<model>"` | Moves `retailer_listings.product_id` to the named product. Takes a `backup_db.py` backup first; dry run prints the listing and its snapshot count. Snapshots stay attached to the listing (no history change). Run on prod via `docker compose exec trackaroo python manage_watchlist.py reassign ...`. |
| `check` | All watchlist validators: toml/CSV consistency (seed's step 1), chip-key collisions, VRAM consistency, orphaned `SPECS_UNAVAILABLE_UPSTREAM` keys. Exit 1 on any failure. Added to CI's python job. |

`discover` from the issue is dropped: `discover.py` already exists.

**Launch day (Zen 6):** `rollover amd-cpu --new zen6 --label ...` -> `add` each
SKU -> MSRPs -> `check` -> PR -> redeploy -> `seed.py --allow-bulk` on the host
after its dry run.

## 5. Delivery and testing

Three PRs, each passing the full gate (pytest, `npm run check`, vitest,
Playwright) and adding a CHANGELOG `## Unreleased` line:

1. **Data model + seed (#17, #18):** toml, CSV migration, schema/migrate,
   watchlist loader, retired-match dropping in the scrapers, discovery scope
   from the toml, seed sync + guard, web labels from DB, `RETIRED_PRODUCTS` removal,
   tracked-only specs tests, fresh-boot test.
2. **Ready-to-retire list:** table, daily step, Discord, `/discover` section.
3. **CLI (#19)** + ARCHITECTURE Part 2 §7 rewritten around it (including the
   MSRP/specs steps it omits today) and the Part 2 tier tables replaced by a
   pointer to `generations.toml`.

**Acceptance tests:**
- Adding `zen6` to a temp toml and seeding retags Zen 5/4, untracks all Zen 3
  rows, and changes no CSV row.
- `/products` renders the new series header with no web code change (vitest on
  the loader with a seeded `generations` row).
- Seeding the real CSV + toml over a DB at today's state gives 0 tracked flips
  and identical tiers.
- A rollover (more than 5 flips, e.g. Zen 3 = 8) is refused without `--allow-bulk`,
  including on a prod-sized DB; a truncated CSV flips nothing (missing rows are never untracked).
- A scraper given a retired row drops its matches (the listing does not fall
  through to a sibling, and no snapshot is written for it).
- Discovery: after a temp `zen6` rollover, a Ryzen 5000 chip is out of scope,
  Zen 5 is `current-1`, and an unknown newer gen is still `current`.
- The JSON written by the scrapers is byte-identical in format (same keys,
  same `watchlist_gen_tier` values) before and after PR 1 for active rows.
- Fresh DB rebuilt from JSON in boot order keeps retired products at
  `tracked = 0`.
- Stale detection: product with last snapshot 31 days ago is flagged, 29 days
  is not, a product created 10 days ago is not; a fresh snapshot removes a
  pending row; Keep hides for 90 days.
- `rollover --dry-run` lists exactly the retags/retirements and writes nothing.
- `reassign` leaves `price_snapshots` rows byte-identical.

**Prod check after PR 1 deploy:** seed log shows 0 tracked flips; `/products`
headers unchanged.

## Refinements made while planning (2026-10-06)

- A CSV row with an unknown or wrong-line `series` is a **row error** (logged
  and skipped, like every other bad row), not a fatal seed error; a skipped
  row is never untracked. A broken `generations.toml` is still fatal for seed.
- Boot runs `seed.py` before `migrate.py`, so seed calls the new migration
  step itself. Seed exits 1 on a bulk refusal or a broken toml, and both
  entrypoints now tolerate a non-zero seed (it wrote nothing to `products`),
  so a rollover deployed without `--allow-bulk` cannot stop the container.
- The web gets labels as a per-line `{tier: label}` map in the root layout's
  data (from `generations`, positions 0-2), not a per-product `seriesLabel`
  DTO field. Same result, far fewer files touched.
- The bulk guard limit is a flat 5 flips, not `max(5, 10%)` (final review, R7):
  every real rollover (Zen 3 = 8, Core 13 = 9, RX 6000 = 8, RTX 30 = 10) must
  need `--allow-bulk`, which a 10% limit on ~108 products (limit 10) did not
  guarantee. The 10% clause guarded a truncated CSV, which no longer flips
  anything because rows missing from the CSV are never untracked.
- The e2e seeder reads the toml with the `smol-toml` web devDependency
  (the web CI job has no Python).

## Out of scope

- Automatic untracking of any kind.
- An admin UI for editing the watchlist (the CLI + PRs are the workflow).
- Changing how chip-key matching works.
- Launch MSRP/perf data entry automation (the CLI only reminds).
