# Buying Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare today's AU price with the US launch MSRP in today's AUD (inc. GST), and show a "Is now a good time to buy?" checklist of separate signals with Lucide icons, AU sale-event markers and a successor flag.

**Architecture:** A best-effort daily step (`fx.py`) caches the AUD/USD rate in a new `fx_rates` table (RBA primary, Frankfurter fallback). The web reads the latest cached rate and computes the MSRP comparison with pure functions (`msrp.ts`). Signals are pure functions in `buySignals.ts`, `saleEvents.ts` and `successors.ts`, rendered by a redesigned BuyPanel with `@lucide/svelte` icons.

**Tech Stack:** Python 3.12 (requests, sqlite3, pytest); SvelteKit 2 / Svelte 5, TypeScript, better-sqlite3, uPlot, vitest, Playwright + axe; `@lucide/svelte` (new, ISC).

**Spec:** `docs/superpowers/specs/2026-10-02-buying-signals-design.md`

## Global Constraints

- One additive table `fx_rates(rate_date TEXT PK, aud_per_usd REAL NOT NULL CHECK > 0, source TEXT NOT NULL, fetched_at TEXT NOT NULL)`, in `migrate.py` + `db/schema.sql`. No other schema, scraping, snapshot or backup change.
- One outbound request per day, best-effort (`run_daily.best_effort`). Tests never touch the network (conftest blocks it): mock HTTP.
- RBA URL `https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv`, column `FXRUSD` (USD per AUD), stored as `aud_per_usd = 1 / value`. Fallback URL `https://api.frankfurter.app/latest?from=USD&to=AUD`. Accept only 1.0–2.5 AUD per USD.
- `check_fx_rate` returns WARNING when the newest rate is older than 7 days. It never returns ERROR.
- MSRP: `msrpAud = launch_msrp_usd × aud_per_usd × 1.10`; `delta = (shownPrice − msrpAud) / msrpAud`. Every USD amount is labelled "US$".
- Signal thresholds:
  - percentile "good" when ≥ 70%;
  - lowest-in-days "good" when ≥ 30;
  - vs avg30: good when ≥ 2% below, neutral within ±2%, alert when ≥ 2% above;
  - trend: flat within ±1% over the last 7 daily lows;
  - sale event: within 21 days or running now;
  - window up to 180 days;
  - history gate: `MIN_HISTORY_POINTS`.
- Icons: `@lucide/svelte` only (CircleCheck, Minus, TrendingDown, TrendingUp, CalendarClock, TriangleAlert, Info, BadgeDollarSign). Always `aria-hidden="true"`; text carries the meaning.
- No emojis anywhere in `web/src` (enforced by test).
- Existing tokens only. `contrast.test.ts` and the axe checks must stay green in both themes.
- Never open `db/trackaroo.db` (use temp copies only when a task says so).
- After every task: pytest, `npm run check` 0/0, `npm test`, `npm run test:e2e` green.

## Review Focus

1. **The RBA CSV format drifts** (extra header rows, blank trailing days, "Series ID" row): the parser must find the FXRUSD column by series id, skip non-numeric cells, and take the latest numeric row. Task 1 has a fixture with the real multi-row header and blank cells.
2. **No `fx_rates` row yet** (first deploy, before the first run): every MSRP display shows "–" and nothing throws. Tasks 2 and 3 test the null rate.
3. **A product with an MSRP but no current price, or a price but no MSRP:** "–", and it sorts last for `sort=msrp`. Task 2 tests this.
4. **Year boundary for sale events** (late December today, January events next year; Boxing Day spanning into the new year window): `upcomingSaleEvent` looks into next year's list. Task 4 tests 28 Dec → no false "Boxing Day starts in −2 days".
5. **Very short history** (2 days): the history gate shows "Gathering history (2 days)" and none of the percentile, lowest or trend badges. Task 4 tests this.

## File Structure

| File | Responsibility |
|---|---|
| `fx.py` (new) | Fetch + parse + upsert rate; `python fx.py` runs once |
| `migrate.py`, `db/schema.sql`, `health_checks.py`, `run_daily.py` (modify) | Table, health check, daily step |
| `web/src/lib/server/queries/fx.ts` (new) | `getLatestFxRate(db)` |
| `web/src/lib/msrp.ts` (new) | Pure MSRP conversion and delta |
| `web/src/lib/buySignals.ts` (modify), `web/src/lib/saleEvents.ts` (new), `web/src/lib/successors.ts` (new) | Pure signal logic |
| `web/src/lib/components/BuyPanel.svelte`, `SignalBadge.svelte` (new), `MsrpLine.svelte` (new), `ProductHeadline.svelte`, `PriceChart.svelte` | UI |
| Products loader, catalogue view (`sort=msrp`), `/deals` loader and page | MSRP column and filter |
| `web/test/noEmoji.test.ts` (new) | Emoji guard |

---

### Task 1: Exchange-rate cache (Python)

**Files:**
- Create: `fx.py`, `unit_testing/test_fx.py`, `unit_testing/fixtures/rba_f11_1_sample.csv`
- Modify: `migrate.py`, `db/schema.sql`, `health_checks.py`, `run_daily.py`, `unit_testing/test_migrate.py`, `unit_testing/test_health_checks.py`

**Interfaces:**
- Produces:
  - `fx.parse_rba_csv(text: str) -> Optional[Tuple[str, float]]`, returning `(YYYY-MM-DD, aud_per_usd)` for the latest numeric FXRUSD row.
  - `fx.parse_frankfurter(payload: dict) -> Optional[Tuple[str, float]]`.
  - `fx.run(db_path: Optional[Path] = None) -> Optional[Tuple[str, float, str]]`, resolving `DB_PATH` at call time.
  - `migrate.migrate_add_fx_rates_table(conn, dry_run=False)`.
  - `health_checks.check_fx_rate(db_path, today=None) -> list[CheckResult]`.

- [ ] **Step 1: Fixture.** Create `unit_testing/fixtures/rba_f11_1_sample.csv` in the RBA layout. It has:
  - several metadata rows ("F11.1 EXCHANGE RATES", "Title", "Description", "Frequency", "Type", "Units", "Source", "Publication date");
  - a "Series ID" row whose columns include `FXRUSD`;
  - a few dated rows (`DD-Mon-YYYY`, e.g. `30-Sep-2026,0.6480,...`);
  - one trailing row with a blank FXRUSD cell.

  Read the real file's structure from RBA documentation knowledge. Do not download it in tests.
- [ ] **Step 2: Failing tests** (`unit_testing/test_fx.py`):
  - the latest numeric row is parsed and inverted (`0.6480` → `1.5432…`, date `2026-09-30`);
  - a missing FXRUSD column returns None;
  - Frankfurter `{"date":"2026-10-01","rates":{"AUD":1.53}}` → `('2026-10-01', 1.53)`;
  - an out-of-bounds rate (0.8, 3.0) is rejected;
  - `run()` with mocked `requests.get`:
    - RBA ok → one row with source `rba`;
    - RBA raising or returning 403 → Frankfurter is used;
    - both failing → returns None and logs a WARNING, with no exception;
    - a second run on the same date → still one row (upsert).
  - The table is created if missing (call the migration inside `run`).
  - Add to `test_migrate.py`: `migrate_add_fx_rates_table` is idempotent and `schema.sql` creates `fx_rates`.
  - Add to `test_health_checks.py`: `check_fx_rate` is OK when fresh, WARNING when 8 days old or empty, and never ERROR, including without the table.
  - Add to `test_run_daily_resilience.py`, using the `isolated_pipeline` fixture pattern: the fx step crashing does not break the run, and `check_fx_rate` is registered in `_db_checks()`.
- [ ] **Step 3: Run** `python -m pytest unit_testing/test_fx.py -q` and expect FAIL.
- [ ] **Step 4: Implement.**
  - `fx.py`: `requests.get` with timeout 10 and header `User-Agent: Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)`.
    - Parse RBA with `csv.reader`. Find the row whose first cell is "Series ID", take the FXRUSD column index, then walk the data rows and keep the last one whose date parses and whose value is numeric.
    - Upsert with `INSERT ... ON CONFLICT(rate_date) DO UPDATE`.
    - Add a `__main__` that runs it and prints the result.
  - Add the migration and the `schema.sql` DDL (keep them in step).
  - Add `check_fx_rate`.
  - `run_daily`: add `best_effort("FX rate", _run_fx)` after ingest, near the discovery step, skipped on dry-run. Register the check in `_db_checks`.
  - Add an autouse conftest guard that patches `fx.DB_PATH` to tmp, the same way the discovery guard does, so no test can write the real DB.
- [ ] **Step 5: Run** the full `python -m pytest -q`. Green.
- [ ] **Step 6: Commit**: `feat(fx): daily AUD/USD rate cache from the RBA with Frankfurter fallback (#32)`.

---

### Task 2: MSRP comparison logic and data

**Files:**
- Create: `web/src/lib/msrp.ts`, `web/test/msrp.test.ts`, `web/src/lib/server/queries/fx.ts`
- Modify: `web/src/lib/server/repos.ts` (barrel), `web/src/routes/products/+page.server.ts`, `web/src/routes/product/[id]/+page.server.ts`, `web/src/routes/deals/+page.server.ts`, `web/src/lib/catalogView.ts` (+ tests), `web/e2e/seed.mjs` (one `fx_rates` row)

**Interfaces:**
- Consumes: the `fx_rates` table (Task 1).
- Produces:
  - `getLatestFxRate(db: DB): { rateDate: string; audPerUsd: number; source: string } | null`. Returns null when the table is missing or empty.
  - `export const GST = 0.1;`
  - `msrpAud(msrpUsd: number | null, fx: FxRate | null): number | null`
  - `msrpDelta(price: number | null, msrpAudValue: number | null): number | null` (a fraction; negative means under MSRP)
  - `msrpExplanation(msrpUsd: number, fx: FxRate): string`, e.g. `"US$1,099 × 1.5432 AUD/USD (RBA, 1 Oct 2026) + 10% GST"`, using `formatUsd`/`formatShortDate` with no `toLocale*`.
  - Catalogue rows gain `msrpUsd: number | null`, and the products loader returns `fx`. `CatalogSort` gains `'msrp'` (default dir asc), whose sort value is `msrpDelta(shownPrice(row, view), msrpAud(row.msrpUsd, fx))`.
  - The product page data gains `fx` and `msrpUsd`. The deals loader returns `fx`, and each candidate row gets `msrpUsd`.

- [ ] **Step 1: Failing tests.**
  - `msrp.test.ts`:
    - $1,099 × 1.5 × 1.1 = 1813.35;
    - null fx → null;
    - null msrp → null;
    - delta −3% and +12% cases;
    - zero/negative inputs → null;
    - the exact explanation string.
  - `catalogView.test.ts`: `sort=msrp` orders by delta ascending with nulls last in both directions. Extend the row helper with `msrpUsd`, and pass fx through the view or a context argument. Choose the cleanest signature and keep `applyCatalogView(rows, view, ctx?)` backward-compatible.
  - Loader tests (`loaders.test.ts`):
    - products rows carry `msrpUsd`, and `data.fx` is null on the seeded DB without a rate;
    - `getLatestFxRate` returns the newest row and null without the table (use a bare in-memory DB).
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - `msrpUsd` comes from `specs.launch_msrp_usd`. Extend the existing per-category specs read in `queries/catalog.ts` (`getCpuSpecs`, or its GPU equivalent) without adding per-product queries; keep `catalog.ts` ≤ 350 lines.
  - Seed one `fx_rates` row in `web/e2e/seed.mjs` (e.g. today, 1.5, 'rba') so e2e can show values.
- [ ] **Step 4: Run** `npm run check` and `npm test`. Green.
- [ ] **Step 5: Commit**: `feat(web): MSRP in today's AUD — rate read, pure conversion, sort=msrp (#32)`.

---

### Task 3: Lucide icons, emoji guard, MSRP UI

**Files:**
- Modify: `web/package.json` (`@lucide/svelte` dependency)
- Create: `web/test/noEmoji.test.ts`, `web/src/lib/components/MsrpLine.svelte`
- Modify: `ProductHeadline.svelte` (or wherever the headline price renders), the catalogue column (`ProductRow.svelte`, `catalogColumns.ts`, sortable header list), `/deals` page and loader (`below_msrp`), `web/e2e/app.spec.ts`

- [ ] **Step 1: Install** `npm install @lucide/svelte` from `web/`. Confirm `npm run build` works and that only the imported icons end up in the client bundle (grep the build output for an unused icon name; expect none).
- [ ] **Step 2: Failing tests.**
  - `noEmoji.test.ts`: walk `web/src`, read `.svelte`/`.ts` files, and assert no match for `/\p{Extended_Pictographic}/u`, listing the offending file:line.
  - e2e:
    - the product page with an MSRP shows "US launch MSRP" with a percentage and "≈A$", and the Info button reveals the explanation containing "AUD/USD" and "GST";
    - `/products?category=gpu&sort=msrp` shows the "vs MSRP" header with `aria-sort="ascending"`;
    - `/deals?below_msrp=1` shows only rows under MSRP (assert each visible vs-MSRP value starts with "−") or the empty state.
- [ ] **Step 3: Run** them and expect FAIL. The emoji test may already pass; fine.
- [ ] **Step 4: Implement.**
  - **Load the `frontend-design` skill** for the visual decisions.
  - `MsrpLine.svelte`: `BadgeDollarSign` icon, then "3% under US launch MSRP" (or "12% over"), then a muted "≈A$1,745 inc. GST", then an `Info` icon button that toggles a small accessible popover (`aria-expanded`, `aria-controls`, closes on Escape) or a `<details>` with the explanation. Render nothing when any input is null.
  - Catalogue "vs MSRP" column: a signed whole-percent in tabular numerals, tinted by tone (success when under, muted within ±2%, warning when over), "–" when unknown. Shown from `lg` up, like the other new columns; add a `sort=msrp` header button with `aria-sort`, plus an option in the panel's Sort select.
  - `/deals`: a "Below MSRP" toggle (`?below_msrp=1`) that filters candidates whose delta is < 0. Show the same column value on each deal row.
- [ ] **Step 5: Run** all suites, including axe. Commit: `feat(web): MSRP line, vs-MSRP column and filter, Lucide icons, emoji guard (#32)`.

---

### Task 4: Signals, sale events, successors (pure)

**Files:**
- Modify: `web/src/lib/buySignals.ts`, `web/test/buySignals.test.ts`
- Create: `web/src/lib/saleEvents.ts`, `web/test/saleEvents.test.ts`, `web/src/lib/successors.ts`, `web/test/successors.test.ts`

**Interfaces:**
- Produces (exact):
```ts
// buySignals.ts
export type SignalTone = 'good' | 'neutral' | 'warn' | 'bad';
export type SignalIcon = 'check' | 'dash' | 'down' | 'up' | 'calendar' | 'alert';
export interface Signal { key: 'percentile' | 'lowest' | 'avg' | 'trend' | 'sale' | 'successor' | 'gathering'; tone: SignalTone; icon: SignalIcon; claim: string; evidence: string; }
export function pricePercentile(lows: DailyLow[], today: number, asOf: string, maxDays?: number): { pct: number; days: number } | null; // share of days in window with a HIGHER low than today
export function lowestInDays(lows: DailyLow[], today: number, asOf: string): { days: number; sinceStart: boolean } | null;
export function trend7(lows: DailyLow[], asOf: string): { change: number; dir: 'falling' | 'flat' | 'rising' } | null;
export function buildSignals(input: { lows: DailyLow[]; today: number | null; asOf: string | null; avg30: number | null; series: string | null; now: Date }): Signal[];
// saleEvents.ts
export interface SaleEvent { name: string; start: string; end: string } // inclusive ISO dates
export function saleEventsFor(year: number): SaleEvent[];
export function upcomingSaleEvent(todayIso: string, horizonDays?: number): { event: SaleEvent; startsInDays: number; running: boolean } | null;
export const CURATED_YEARS: number[];
// successors.ts
export const SUCCESSORS: Record<string, string>; // series -> successor label, starts {}
export function successorFor(series: string | null): string | null;
```

- [ ] **Step 1: Failing tests:**
  - **Percentile** over a known 10-day series: the stated `pct` and `days`, the window capped at 180, and null when the history is under the gate.
  - **lowestInDays:** "lowest since tracking began" when no lower day exists; correct days otherwise.
  - **trend7:** −4% falling, +0.5% flat, +3% rising, and null with fewer than 2 points in 7 days.
  - **buildSignals:**
    - the gate case gives exactly one `gathering` signal with "Gathering history (2 days)";
    - tones and icons follow the Global Constraints thresholds;
    - every signal has non-empty `evidence`;
    - the avg signal uses the ±2% rule;
    - no emoji in any claim or evidence string.
  - **saleEvents:**
    - Black Friday 2025 = 28 Nov and 2026 = 27 Nov (Thanksgiving is the 4th Thursday);
    - EOFY = 15–30 Jun;
    - Boxing Day = 26–31 Dec;
    - Singles Day = 11 Nov;
    - curated Click Frenzy and Prime Day present for every year in `CURATED_YEARS`;
    - a guard test that `CURATED_YEARS` includes the current calendar year + 1 (this fails when the owner needs to add next year);
    - `upcomingSaleEvent('2026-11-01')` → Singles Day in 10 days;
    - running now → `running: true`;
    - `'2026-12-28'` → the running Boxing Day (never a negative `startsInDays`);
    - nothing within 21 days → null.
  - **successors:** an empty map → null; with a monkeypatched entry it returns the label.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - Fill `CURATED_YEARS` with the current year and the next year. For curated dates:
    - use the published dates where known;
    - where not yet announced, use the usual window (Click Frenzy Main Event: the second Tuesday of November, 2 days; Prime Day: the second week of July, 2 days) with a comment `// estimate — replace when announced`.
  - Note this in the report.
  - All claim strings are plain text. Format numbers with `$lib/formats` (no `toLocale*`).
- [ ] **Step 4: Run** and expect GREEN. Run `npm run check`.
- [ ] **Step 5: Commit**: `feat(web): buying-signal rules, AU sale-event calendar, successor flag (#31)`.

---

### Task 5: Signals UI — checklist, stats strip, chart sale markers

**Files:**
- Create: `web/src/lib/components/SignalBadge.svelte`
- Modify: `web/src/lib/components/BuyPanel.svelte`, `web/src/routes/product/[id]/+page.svelte` (pass the series and now), `web/src/lib/components/PriceChart.svelte`, `web/e2e/app.spec.ts`

- [ ] **Step 1: Failing e2e:**
  - On a seeded product with history, the panel heading reads "Is now a good time to buy?". There is at least one badge (`data-testid="signal"`) whose text includes the evidence, and each badge contains an `svg` with `aria-hidden="true"`.
  - The stats strip has 30 / 90 / 180 columns.
  - When the plotted range includes a sale event, the chart caption or legend lists it. Assert via an accessible text, e.g. the existing chart summary or a visually-hidden list "Sale events shown: Black Friday …"; the canvas cannot be asserted.
  - axe stays green.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.** **Load the `frontend-design` skill first.**
  - `SignalBadge.svelte`: a pill with a 24px tinted circle holding the Lucide icon (`CircleCheck` / `Minus` / `TrendingDown` / `TrendingUp` / `CalendarClock` / `TriangleAlert`), a bold claim and muted evidence.
    - Tone → existing tokens: `good` → success, `warn` → warning, `bad` → danger, `neutral` → text-muted on surface.
    - Both themes; tabular numerals.
  - `BuyPanel`: title, then a responsive grid of `buildSignals(...)` (2 columns ≥ md, 1 column on phone), then the 30/90/180 stats strip (add 180 via `windowStats`).
  - `PriceChart`: draw `saleEventsFor` events overlapping the x range as dashed vertical lines with a short label, in the muted text colour (no new hue), in a uPlot draw hook. Expose the list as visually-hidden text for screen readers.
- [ ] **Step 4: Run** all suites (check 0/0, vitest, Playwright incl. axe). Take a screenshot of `/product/1` in light and dark at desktop and 390 px with Playwright (save to the system temp dir, not the repo). Describe in the report how it looks; fix anything cramped, misaligned or low-contrast.
- [ ] **Step 5: Commit**: `feat(web): "good time to buy" checklist with Lucide icons, 180-day stats, sale markers (#31)`.

---

### Task 6: Docs and gate

- [ ] README:
  - "Buying signals" section: what each badge means, the MSRP conversion, sale events and how to add next year's Click Frenzy / Prime Day dates in `saleEvents.ts`, and how to set a successor in `successors.ts`;
  - the fx step: `docker compose exec trackaroo python fx.py` to fetch now.
- [ ] `docs/ARCHITECTURE.md` decision log: one entry replacing the 16-Aug "MSRP stays USD" note (converted at today's RBA rate, inc. GST), and one noting the signals checklist complements, not replaces, the declined deal score.
- [ ] CLAUDE.md counts and one line on `fx.py` (best-effort, WARNING-only check). STATUS.md dated bullet.
- [ ] Full gate: pytest, check 0/0, vitest, Playwright, build. Commit `docs: buying signals and MSRP in AUD (#31 #32)`.
