# Price-to-Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sourced performance metrics and show performance per Australian dollar: catalogue and compare columns, a `/value` page with a price-vs-performance scatter and its Pareto frontier, and best-per-budget winners.

**Architecture:**
- Curated `db/perf_index.json`, bundled into the web build (static JSON import). There is no DB change.
- Pure functions in `web/src/lib/value.ts`.
- A loader that pairs products' current in-stock prices with their perf values.
- A new `/value` route with an SVG scatter.

**Tech Stack:** Python (pytest for the data guard); SvelteKit 2 / Svelte 5 / Tailwind v4, TypeScript, vitest, Playwright + axe.

**Spec:** `docs/superpowers/specs/2026-10-03-price-performance-design.md`

## Global Constraints

- **Data rules:**
  - Every performance value comes from a FETCHED published table, never from memory.
  - Every metric has exactly one source table (`source`, `source_url`, `as_of`, `baseline`), and all its values come from that table.
  - Products missing from the table are listed in `not_in_source` and never estimated.
- **Metric keys:** `gpu_raster_1440p`, `gpu_rt_1440p`, `cpu_gaming_1080p`. Values are relative %, as published.
- **Product keys:**
  - GPUs: `"<watchlist model> <watchlist spec>"` (e.g. `GeForce RTX 3050 8GB`).
  - CPUs: the watchlist `model`.
- **Coverage:**
  - Required for every tracked `current` and `current-1` product (70 today), unless listed in `not_in_source`.
  - `current-2` gaps are allowed and reported as a warning.
- **Value maths:**
  - perf per A$1,000 = `metric / price × 1000`;
  - A$ per point = `price / metric`;
  - either input null or ≤ 0 gives null.
- **Price:** the cheapest in-stock price on the global latest snapshot date (active, non-bundle listings). Reuse the existing `cheapestListingPerProduct` / `dailyCheapestInStock` SQL in `queries/sql.ts`.
- **Frontier:** a point is on the frontier unless another point has price ≤ and perf ≥ with at least one strict. Ties are kept.
- **Budget brackets** (AUD max): 400, 700, 1000, 1500, 2500.
  - Winner: highest perf with price ≤ max; on a perf tie, the lower price wins.
  - Runner-up: the next best.
  - gap = `(winner − runnerUp) / runnerUp`.
  - The "exclude 8 GB" option drops GPUs with VRAM ≤ 8 GB.
- **UI rules:**
  - Every value on screen states its metric and source on hover or focus (`title` plus visible text, or an accessible description).
  - Data-less cells show "–" and sort last.
  - Existing tokens and classes only (`.num`, `text-section`, PageHeader, SegmentedControl).
  - Lucide icons, aria-hidden. No emojis, no `toLocale*`.
  - Client code never imports `$lib/server`, and files stay at or under 350 lines.
  - axe and mobile (320/390) stay green.
- Never open `db/trackaroo.db`.
- **Gate:** after every task, `python -m pytest -q`, then from `web/`: `npm run check` 0/0, `npm test` and `npm run test:e2e`.

## Review Focus

1. **A GPU whose memory variants are separate products** (RTX 5060 Ti 8GB and 16GB): each must resolve to its own entry, and the source chart must list each VRAM variant explicitly. If the chart lists only one, the other goes to `not_in_source` and is never copied. Task 1 and Task 2 test this.
2. **No in-stock price, or only an out-of-stock price:** the product is excluded from /value and the count of excluded products is shown. It never appears at price 0. Tasks 2 and 4 test this.
3. **A bracket with one product or none:** an empty bracket says so, and a single product has no runner-up and no gap (no NaN). Task 2 tests this.
4. **Ties on the frontier, and identical points:** both are kept, with no crash or duplicate rendering. Task 2 tests this.
5. **Phone width:** the scatter must scale down at 320–390 px with no horizontal overflow, and the hidden table must keep the data reachable. Task 4 tests this.

## File Structure

| File | Responsibility |
|---|---|
| `db/perf_index.json` (new) | Curated metrics with sources |
| `unit_testing/test_perf_index.py` (new) | Coverage and shape guard |
| `docs/perf-index-sources.md` (new) | How each metric was transcribed (charts, dates, matching notes) |
| `web/src/lib/value.ts` (new), `web/test/value.test.ts` | Pure maths |
| `web/src/lib/perfIndex.ts` (new) | Typed import of the JSON, key resolution |
| `web/src/lib/server/queries/value.ts` (new) | Price rows for value pages |
| `web/src/routes/value/+page.server.ts`, `+page.svelte` (new), `web/src/lib/components/ValueScatter.svelte` (new), `BudgetWinners.svelte` (new) | /value |
| Products and compare loaders and pages, `catalogColumns.ts`, `catalogView.ts`, `ProductRow.svelte`, `web/src/lib/nav.ts` | Columns, sort and nav |

---

### Task 1: Research and curate the performance index

**Files:**
- Create: `db/perf_index.json`, `unit_testing/test_perf_index.py`, `docs/perf-index-sources.md`

- [ ] **Step 1: Find the source tables, with the WebSearch and WebFetch tools.**
  - **GPUs:** use TechPowerUp's most recent GPU review published 2025–2026 that has a "Relative Performance" chart at 2560×1440 listing the most cards. Their reviews show raster relative performance and a separate ray-tracing relative chart.
  - **CPUs:** use TechPowerUp's most recent CPU review with "Relative Gaming Performance" at 1920×1080 (an RTX 4090/5090 test bed).

  Fetch the actual pages. If a chart is an image whose numbers cannot be read as text, try that review's other pages, or the equivalent chart in another TPU review. If none is readable, use Hardware Unboxed/TechSpot or 3DCenter's index, as long as it is a single table per metric. Record which source you used and why.
- [ ] **Step 2: Transcribe.**
  - For each product in `db/watchlist.csv`, find its row in the chart, matching model and VRAM exactly.
  - Record the published relative % as given (baseline is the chart's 100% card).
  - A product that is not in the chart goes to `not_in_source[metric]`.
  - Never interpolate, average two charts or reuse a sibling's value.
  - Write `docs/perf-index-sources.md` with each metric's source title, URL, date, baseline, and the matching notes (e.g. "RTX 4060 Ti 16GB not listed").
- [ ] **Step 3: Failing test** (`test_perf_index.py`):
  - the file parses and has the three metrics, each with label, unit, source, source_url (https), as_of (YYYY-MM) and baseline;
  - every product key matches a watchlist row (no stray keys);
  - values are positive numbers;
  - every tracked current/current-1 product has its category's required metrics (GPU: raster, and RT where the source lists it; CPU: gaming) or is listed in `not_in_source`;
  - current-2 gaps raise `warnings.warn`.

  Write the test before the file is complete, and see it fail.
- [ ] **Step 4: Complete the data** until the test passes. Report:
  - coverage counts per metric;
  - the `not_in_source` lists;
  - the five values you are least sure of, for the owner's spot-check.
- [ ] **Step 5: Commit**: `feat(data): sourced performance index for tracked GPUs and CPUs (#33)`.

---

### Task 2: Pure value maths and the price loader

**Files:**
- Create: `web/src/lib/value.ts`, `web/src/lib/perfIndex.ts`, `web/test/value.test.ts`, `web/src/lib/server/queries/value.ts` (exported via the `repos.ts` barrel)
- Modify: `web/src/lib/models.ts`

**Interfaces:**
```ts
// perfIndex.ts (client-safe; imports ../../../db/perf_index.json)
export type MetricKey = 'gpu_raster_1440p' | 'gpu_rt_1440p' | 'cpu_gaming_1080p';
export interface MetricInfo { label: string; unit: string; source: string; source_url: string; as_of: string; baseline: string }
export const METRICS: Record<MetricKey, MetricInfo>;
export function perfKey(p: { category: 'gpu' | 'cpu'; model: string; vramGb: number | null }): string; // gpu: `${model} ${vramGb}GB`
export function perfFor(p: { category: 'gpu' | 'cpu'; model: string; vramGb: number | null }, metric: MetricKey): number | null;
export function defaultMetric(category: 'gpu' | 'cpu'): MetricKey; // gpu_raster_1440p | cpu_gaming_1080p
export function sourceNote(metric: MetricKey): string; // "1440p raster, TechPowerUp, <title>, Sep 2026"
// value.ts
export interface ValuePoint { id: number; name: string; price: number; perf: number; vramGb: number | null }
export function perfPerKilo(price: number | null, perf: number | null): number | null;
export function audPerPoint(price: number | null, perf: number | null): number | null;
export function paretoFrontier(points: ValuePoint[]): number[]; // ids, price asc
export const BUDGETS: readonly number[]; // [400, 700, 1000, 1500, 2500]
export function bestPerBudget(points: ValuePoint[], opts?: { exclude8gb?: boolean }): { max: number; winner: ValuePoint | null; runnerUp: ValuePoint | null; gap: number | null }[];
// server
export function getValueRows(db: DB, category: 'gpu' | 'cpu'): { id: number; name: string; model: string; vramGb: number | null; price: number | null }[]; // tracked products, cheapest in-stock today or null; memoised
```
Check how the watchlist `spec` maps to `products.vram_gb`. Write a test for `perfKey` against real watchlist GPU rows, e.g. "GeForce RTX 3050" with 6 GB gives "GeForce RTX 3050 6GB".

- [ ] **Step 1: Failing tests.**
  - `perfPerKilo` and `audPerPoint`: normal values, plus null, zero and negative inputs.
  - `paretoFrontier`:
    - a known 6-point set gives the expected ids;
    - ties and duplicates are both kept;
    - a single point is the frontier;
    - an empty input gives [].
  - `bestPerBudget`:
    - a winner and runner-up per bracket;
    - a perf tie goes to the lower price;
    - a bracket with one product has a null runner-up and a null gap;
    - an empty bracket has all nulls;
    - `exclude8gb` drops VRAM ≤ 8.
  - `perfFor` resolves GPU variants separately.
  - `getValueRows` (in-memory DB from schema.sql):
    - the in-stock cheapest on the latest date;
    - out-of-stock-only gives null;
    - bundle and delisted listings are excluded.
- [ ] **Step 2: Run** and expect FAIL. **Step 3: Implement.** **Step 4: Gate.**
- [ ] **Step 5: Commit**: `feat(web): value maths, perf index lookup and price rows (#33)`.

---

### Task 3: Value columns on /products and /compare

**Files:**
- Modify: `catalogColumns.ts`, `catalogView.ts` (+ tests; the `sort=value` key, descending by default, nulls last), `ProductRow.svelte`, the products loader (rows gain `perfPerKilo`, plus `metric` per category), the compare loader and page (a "Perf / A$1k" row via `compareRows.ts`), `web/e2e/app.spec.ts`, `web/e2e/seed.mjs` (only if fixtures need a perf entry; prefer real product names already in the index).

- [ ] **Step 1: Failing tests.**
  - The catalogue sort on `sort=value` is descending by default, with nulls last in both directions.
  - A ProductRow cell shows a whole number, plus a `title` with `sourceNote`.
  - e2e:
    - `/products?category=gpu` at 1440 px shows the "Perf / A$1k" header and `aria-sort` when sorted;
    - a product with a perf entry shows a number;
    - one without shows "–";
    - `/compare` with two products shows the row.
- [ ] **Step 2–4:** Implement from xl (like the range column). Check that rows don't wrap at 1280 px; the existing e2e already checks this. Run the gate.
- [ ] **Step 5: Commit**: `feat(web): perf per A$1,000 column on /products and /compare (#33)`.

---

### Task 4: The /value page

**Files:**
- Create: `web/src/routes/value/+page.server.ts`, `+page.svelte`, `web/src/lib/components/ValueScatter.svelte`, `BudgetWinners.svelte`
- Modify: `web/src/lib/nav.ts` (add `{ href: '/value', label: 'Value' }` after Compare), `web/e2e/app.spec.ts`, `web/e2e/a11y.spec.ts` (add `/value`), `web/e2e/mobile.spec.ts`

- [ ] **Step 1: Failing tests.**
  - **Loader:** returns points for the category and metric (from the URL params `category`, `metric` and `no8gb`), the frontier ids, budgets, the excluded count and the metric info. It sets `wide: true`.
  - **e2e:**
    - `/value` renders a PageHeader "Value";
    - the scatter has one focusable point per priced product with perf;
    - the frontier points carry `data-frontier="true"`;
    - the hidden table has the same row count;
    - switching to CPU updates the URL and the points;
    - the budget cards show winners;
    - the "Exclude 8 GB cards" toggle changes the GPU results when 8 GB cards exist;
    - the source line is visible;
    - axe passes in both themes;
    - there is no horizontal overflow at 320 and 390 px.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.** **Load the `dataviz` and `frontend-design` skills first.**
  - **ValueScatter:**
    - a responsive SVG (`viewBox`, width 100%) with labelled x (A$) and y (metric unit) axes;
    - muted dots, with frontier dots in the accent colour joined by a step line;
    - each point is a focusable `<a href="/product/<id>">` with an `aria-label` naming the model, price, perf and perf per A$1k;
    - a tooltip on hover and focus;
    - no new hue.
  - **BudgetWinners:** cards per bracket, as in the spec.
  - Below the chart, show the source line ("Performance: TechPowerUp, <title>, Sep 2026. Prices: cheapest in stock today across Scorptec, PCCG, Umart."), plus "N products without an in-stock price are not shown."
- [ ] **Step 4: Gate.** Take light and dark screenshots at 1440 and 390 px into the temp dir, and describe them.
- [ ] **Step 5: Commit**: `feat(web): /value page with price-vs-performance frontier and best per budget (#33)`.

---

### Task 5: Docs, decision log and gate
- [ ] **README:** add a "Value" section covering the metrics and sources, how to update `perf_index.json` (one table per metric, `not_in_source`, the test), and the frontier and budget rules.
- [ ] **`docs/ARCHITECTURE.md`:** add the decision entry from spec §5.
- [ ] **CHANGELOG:** add a line under `## Unreleased` → `### Added`.
- [ ] **STATUS.md:** add a dated bullet.
- [ ] **CLAUDE.md:** update the counts.
- [ ] **Full gate:** pytest, check, vitest, Playwright and build. Commit `docs: price-to-performance (#33)`.
