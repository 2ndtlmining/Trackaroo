# Finish the Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catalogue filters and sorting in the URL (max price, brand, generation, in stock, retailer), compare best-value markers, chart 30-day average / gap / axis note, accessible palette and error page, and automated axe checks.

**Architecture:** The products page already ships the whole category to the browser and filters there. The new view state (`max`, `brand`, `gen`, `retailer`, `sort`, `dir`) is parsed by one pure module (`catalogView.ts`) that both the server render and the client use, so a link renders correctly without JS and updates live with JS. The loader adds the small per-product data the new controls need: per-retailer cheapest prices, a 30-day product sparkline, CPU socket and threads, and release year. Compare and chart changes are pure helpers plus markup. axe runs in Playwright as a dev-only dependency.

**Tech Stack:** SvelteKit 2 / Svelte 5 runes, TypeScript, better-sqlite3, uPlot (existing chart), vitest, Playwright, `@axe-core/playwright` (dev).

**Spec:** `docs/superpowers/specs/2026-10-02-finish-pages-design.md`

## Global Constraints

- Read-only feature work. No changes to `db/schema.sql`, `migrate.py`, Python, scrapers, `data/`, backups, Docker or deploy files. No new writes. Tests never open `db/trackaroo.db`.
- One new read query only: `getProductSparklines(db, category, days)`, built on `dailyCheapestInStock` in `web/src/lib/server/queries/sql.ts`.
- Invalid or unknown URL values are dropped by the parser, never an error.
- URL params: `max`, `brand`, `gen`, `in_stock`, `retailer`, `sort`, `dir`. Existing `q`, `compare`/`ids`, `unlisted` and `category` keep working.
- Sort defaults: price asc, name asc, spec desc, released desc, listings desc. Any non-default sort flattens the series groups.
- Compare: higher is better for VRAM, memory bus, bandwidth, L2 cache, base clock, boost clock, cores/shaders, threads. Lower is better for current price, TDP, process. Everything else is neutral. Ties mark every tied cell. Mark only when there are 2+ numeric values and not all equal.
- axe: `@axe-core/playwright` as a devDependency only. Fail on `serious` or `critical`. A rule may be disabled only with a written reason in the spec file.
- Existing conventions:
  - `web/test/determinism.test.ts` forbids `toLocale*`; use `$lib/formats`.
  - `web/test/boundaries.test.ts` forbids client imports of server code, and server files over 350 lines.
  - e2e must use the `goto()` helper and `networkidle`.
  - Tabs, single quotes.
- After every task: `npm run check` 0 errors 0 warnings, `npm test`, `npm run test:e2e` green; backend `python -m pytest -q` untouched and green.

## Review Focus

1. **A shared link with stale or invalid params** (`?max=abc&brand=Foo&sort=bogus&dir=up`) must render the unfiltered default view, not an error or an empty page. Task 1 `parseCatalogView` tests.
2. **Retailer filter + max price on a product with only out-of-stock listings at that retailer.** With `in_stock=1`, the product is hidden. Without it, its price is that retailer's cheapest of any stock. Task 1 tests.
3. **Never-listed products** (no price) under a `max` filter or a price sort: excluded by `max`, sorted last by price in both directions. Task 1 tests.
4. **Hydration mismatch:** server and client must compute the same filtered list from the same URL. Task 3 Playwright reloads a filtered URL and asserts no console hydration error.
5. **Phone panel focus:** opening the 390 px filter dialog moves focus inside, and closing it returns focus to the button. Task 3 Playwright.

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/catalogView.ts` (new) | Parse/serialise view params; pure `applyCatalogView(rows, view)` filter + sort |
| `web/src/lib/server/queries/catalog.ts` (modify) | `getProductSparklines`; CPU socket/threads read |
| `web/src/routes/products/+page.server.ts` (modify) | Add `retailerPrices`, `sparkline`, `socket`, `threads`, `releaseYear` per row |
| `web/src/routes/products/+page.svelte` + `web/src/lib/components/CatalogFilters.svelte` (new) + `ProductRow.svelte` (modify) | Controls, sortable headers, columns, phone dialog |
| `web/src/lib/compareRows.ts` + `web/src/routes/compare/+page.svelte` | `direction` + `bestIndexes()` |
| `web/src/lib/chartExtras.ts` (new) + `PriceChart.svelte` | Gap segments, axis note, average line |
| `web/src/routes/+error.svelte`, `web/src/lib/components/CommandPalette.svelte` | Error page, combobox ARIA |
| `web/e2e/a11y.spec.ts` (new) | axe over main pages, light and dark |

---

### Task 1: Catalogue view state (pure)

**Files:**
- Create: `web/src/lib/catalogView.ts`, `web/test/catalogView.test.ts`

**Interfaces:**
- Produces:
```ts
export type CatalogSort = 'price' | 'name' | 'spec' | 'released' | 'listings';
export type SortDir = 'asc' | 'desc';
export interface CatalogView {
	max: number | null;
	brands: string[];          // subset of 'NVIDIA' | 'AMD' | 'Intel', canonical case
	gens: GenerationTier[];    // 'current' | 'current-1' | 'current-2'
	inStock: boolean;
	retailer: Retailer | null; // 'scorptec' | 'pccg' | 'umart'
	sort: CatalogSort | null;  // null = default grouped order
	dir: SortDir;              // resolved: explicit dir, else the key's default
}
export interface CatalogRowInput {
	productId: number; brand: string; model: string; generationTier: GenerationTier | null;
	cheapestInStockPrice: number | null;
	retailerPrices: Partial<Record<Retailer, { inStock: number | null; any: number | null }>>;
	vramGb: number | null; cores: number | null; launchDate: string | null;
	listingCount: number; neverListed: boolean;
}
export const DEFAULT_DIR: Record<CatalogSort, SortDir>;
export function parseCatalogView(params: URLSearchParams): CatalogView;
export function catalogViewParams(view: CatalogView): Record<string, string | null>; // null = delete param
export function shownPrice(row: CatalogRowInput, view: CatalogView): number | null;
export function applyCatalogView<T extends CatalogRowInput>(rows: T[], view: CatalogView): T[];
export function activeFilterCount(view: CatalogView): number;
```

- [ ] **Step 1: Failing tests** (`web/test/catalogView.test.ts`):

```ts
import { describe, expect, it } from 'vitest';
import {
	activeFilterCount, applyCatalogView, catalogViewParams, parseCatalogView, shownPrice,
	type CatalogRowInput
} from '../src/lib/catalogView';

const p = (q: string) => parseCatalogView(new URLSearchParams(q));
const row = (o: Partial<CatalogRowInput> & { productId: number }): CatalogRowInput => ({
	brand: 'NVIDIA', model: `M${o.productId}`, generationTier: 'current', cheapestInStockPrice: null,
	retailerPrices: {}, vramGb: null, cores: null, launchDate: null, listingCount: 0, neverListed: false, ...o
});

describe('parseCatalogView', () => {
	it('defaults', () => {
		expect(p('')).toEqual({ max: null, brands: [], gens: [], inStock: false, retailer: null, sort: null, dir: 'asc' });
	});
	it('reads every param, repeatable and comma lists, canonical brand case', () => {
		const v = p('max=1000&brand=nvidia,AMD&brand=Intel&gen=current&gen=current-1&in_stock=1&retailer=pccg&sort=price&dir=desc');
		expect(v).toEqual({ max: 1000, brands: ['NVIDIA', 'AMD', 'Intel'], gens: ['current', 'current-1'], inStock: true, retailer: 'pccg', sort: 'price', dir: 'desc' });
	});
	it('drops invalid values instead of failing', () => {
		expect(p('max=abc&brand=Foo&gen=old&retailer=amazon&sort=bogus&dir=up&in_stock=yes')).toEqual(p(''));
		expect(p('max=-5').max).toBeNull();
		expect(p('max=0').max).toBeNull();
		expect(p('max=1e9').max).toBeNull(); // only plain positive integers up to 100000
	});
	it('sort without dir uses the key default', () => {
		expect(p('sort=spec').dir).toBe('desc');
		expect(p('sort=released').dir).toBe('desc');
		expect(p('sort=name').dir).toBe('asc');
	});
});

describe('catalogViewParams round-trip', () => {
	it('serialises only non-default values', () => {
		expect(catalogViewParams(p(''))).toEqual({ max: null, brand: null, gen: null, in_stock: null, retailer: null, sort: null, dir: null });
		const v = p('max=500&brand=AMD&gen=current&in_stock=1&retailer=umart&sort=price&dir=desc');
		const back = new URLSearchParams(Object.entries(catalogViewParams(v)).filter(([, x]) => x !== null) as [string, string][]);
		expect(parseCatalogView(back)).toEqual(v);
	});
	it('omits dir when it equals the key default', () => {
		expect(catalogViewParams(p('sort=price&dir=asc')).dir).toBeNull();
	});
});

describe('shownPrice', () => {
	const r = row({ productId: 1, cheapestInStockPrice: 900, retailerPrices: { pccg: { inStock: null, any: 850 }, umart: { inStock: 950, any: 950 } } });
	it('is the overall cheapest in stock without a retailer', () => expect(shownPrice(r, p(''))).toBe(900));
	it("is the retailer's cheapest of any stock without in_stock", () => expect(shownPrice(r, p('retailer=pccg'))).toBe(850));
	it("is the retailer's cheapest in stock with in_stock", () => {
		expect(shownPrice(r, p('retailer=pccg&in_stock=1'))).toBeNull();
		expect(shownPrice(r, p('retailer=umart&in_stock=1'))).toBe(950);
	});
	it('is null for a retailer that does not list it', () => expect(shownPrice(r, p('retailer=scorptec'))).toBeNull());
});

describe('applyCatalogView', () => {
	const rows = [
		row({ productId: 1, brand: 'NVIDIA', cheapestInStockPrice: 1200, vramGb: 16, launchDate: '2025-01-30', listingCount: 9, retailerPrices: { pccg: { inStock: 1200, any: 1200 } } }),
		row({ productId: 2, brand: 'AMD', generationTier: 'current-1', cheapestInStockPrice: 600, vramGb: 16, launchDate: '2024-01-24', listingCount: 3, retailerPrices: { umart: { inStock: 600, any: 600 } } }),
		row({ productId: 3, brand: 'Intel', cheapestInStockPrice: 400, vramGb: 12, launchDate: '2024-12-12', listingCount: 5, retailerPrices: { pccg: { inStock: null, any: 380 } } }),
		row({ productId: 4, brand: 'NVIDIA', neverListed: true, vramGb: 8, launchDate: null })
	];
	const ids = (q: string) => applyCatalogView(rows, p(q)).map((r) => r.productId);

	it('no view: unchanged order', () => expect(ids('')).toEqual([1, 2, 3, 4]));
	it('max hides pricier and unpriced', () => expect(ids('max=700')).toEqual([2, 3]));
	it('brand and gen', () => {
		expect(ids('brand=NVIDIA')).toEqual([1, 4]);
		expect(ids('gen=current-1')).toEqual([2]);
		expect(ids('brand=NVIDIA,Intel&gen=current')).toEqual([1, 3, 4]);
	});
	it('in_stock hides products without an in-stock price', () => expect(ids('in_stock=1')).toEqual([1, 2, 3]));
	it('retailer keeps only products listed there', () => {
		expect(ids('retailer=pccg')).toEqual([1, 3]);
		expect(ids('retailer=pccg&in_stock=1')).toEqual([1]);
		expect(ids('retailer=pccg&max=500')).toEqual([3]); // 380 at pccg (any stock)
	});
	it('price sort puts unpriced last in both directions', () => {
		expect(ids('sort=price')).toEqual([3, 2, 1, 4]);
		expect(ids('sort=price&dir=desc')).toEqual([1, 2, 3, 4]);
	});
	it('other sorts, ties broken by name then id', () => {
		expect(ids('sort=spec')).toEqual([1, 2, 3, 4]);           // vram desc
		expect(ids('sort=released')).toEqual([1, 3, 2, 4]);       // newest first, unknown last
		expect(ids('sort=listings')).toEqual([1, 3, 2, 4]);
		expect(ids('sort=name&dir=desc')).toEqual([4, 3, 2, 1]);
	});
	it('counts active filters (not sort)', () => {
		// brand counts once however many brands are ticked; sort is not a filter
		expect(activeFilterCount(p('max=500&brand=AMD,Intel&in_stock=1&sort=price'))).toBe(3);
	});
});
```

For CPUs, `spec` sorts by `cores` (add one CPU row assertion while implementing: `sort=spec` on rows that have `cores` uses cores).

- [ ] **Step 2: Run** `npx vitest run test/catalogView.test.ts` and expect FAIL (module missing).
- [ ] **Step 3: Implement** `web/src/lib/catalogView.ts` to satisfy the tests:
  - `max` is accepted only when it matches `/^\d{1,6}$/` and is between 1 and 100000.
  - Brands are matched case-insensitively against `['NVIDIA','AMD','Intel']` and emitted in canonical case, deduplicated, in first-seen order.
  - `gens` uses the `GenerationTier` values from `$lib/types`.
  - `retailer` uses the `RETAILERS` list in `$lib/filters`.
  - Sort comparator: by key, `dir` applied, nulls always last, then ties by `model` (simple `<`/`>` string compare, no `localeCompare` with a locale argument; use `a < b ? -1 : a > b ? 1 : 0`), then `productId`.
  - `spec` is `vramGb ?? cores`.
  - `released` is `launchDate`, compared as an ISO string.
  - No `toLocale*`.
- [ ] **Step 4: Run** the test, then `npm run check` (0/0). GREEN.
- [ ] **Step 5: Commit**: `feat(web): catalogue view state — parse, serialise, filter and sort (#23)`.

---

### Task 2: Loader data for the new controls

**Files:**
- Modify: `web/src/lib/server/queries/catalog.ts`, `web/src/routes/products/+page.server.ts`, `web/src/lib/models.ts` (row type if one is declared there)
- Test: `web/test/catalogSparklines.test.ts` (new), `web/test/loaders.test.ts` (extend)

**Interfaces:**
- Consumes: `CatalogRowInput` (Task 1); `dailyCheapestInStock` (existing, `queries/sql.ts`); existing loader shape.
- Produces:
  - `getProductSparklines(db: DB, category: Category, days?: number): Map<number, Array<{ date: string; price: number }>>`. Per tracked product, the daily cheapest in-stock price over the trailing window, oldest first. Built on `dailyCheapestInStock`, with the window bound as a parameter.
  - Each loader row gains:
    - `retailerPrices` (as in `CatalogRowInput`);
    - `sparkline: number[]` (prices oldest first, at most 30);
    - `socket: string | null` and `threads: number | null` (CPUs, from `specs.socket` / `specs.thread_count`; null for GPUs);
    - `releaseYear: number | null` (from `launchDate`).

- [ ] **Step 1: Failing tests.**
  - `catalogSparklines.test.ts` against `createSeededDb()`:
    - the result has entries only for tracked products;
    - each series is date-ascending, at most 30 points, all prices > 0;
    - a product with in-stock snapshots on N days in the window has N points.
  - Extend `loaders.test.ts` with a `/products` loader test:
    - every row has `retailerPrices` whose `any` ≤ every `inStock` for the same retailer;
    - CPU rows have the `socket`/`threads` keys and GPU rows have them as `null`;
    - `releaseYear` matches `launchDate`.
  - Payload guard: the JSON size of `data.groups` for gpu stays under 40 KB. Record the before/after sizes in the report.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - `retailerPrices` is computed from `listings` inside the loader's memo, before `listings` is dropped. It is the cheapest `latestPrice` per retailer, overall and in stock (`latestStock === 'in_stock'`).
  - The sparkline uses one call to `getProductSparklines(db, category, 30)` inside the same memo.
  - Socket/threads come from the existing per-category specs read in `catalog.ts`. Look for the memoised specs read near line 130 and reuse it; do not add a per-product query.
  - Keep `catalog.ts` under 350 lines. If it would exceed that, put `getProductSparklines` in a new `queries/sparklines.ts` and re-export it from the `repos.ts` barrel.
- [ ] **Step 4: Run** the tests and `npm run check`. GREEN. Run `npm test` in full.
- [ ] **Step 5: Commit**: `feat(web): loader data for catalogue filters, sparklines and CPU columns (#23)`.

---

### Task 3: Catalogue UI

**Files:**
- Create: `web/src/lib/components/CatalogFilters.svelte`
- Modify: `web/src/routes/products/+page.svelte`, `web/src/lib/components/ProductRow.svelte`, `web/src/lib/productIndex.ts` (if grouping lives there), `web/e2e/app.spec.ts`, `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: Task 1 (`parseCatalogView`, `catalogViewParams`, `applyCatalogView`, `shownPrice`, `activeFilterCount`, `DEFAULT_DIR`) and Task 2 row fields.

Behaviour (spec §4):
- **Controls:**
  - Max price: preset buttons $500 / $1,000 / $2,000 / Any, with `aria-pressed`, plus a number input.
  - Brand checkboxes NVIDIA/AMD/Intel, showing only brands present in the category.
  - Generation checkboxes, labelled by series per tier, derived from the rows' series names for that tier (look at how `groupForIndex` names groups).
  - In stock: the existing control.
  - Retailer select (Any / Scorptec / PCCG / Umart).
  - "Clear filters" link when `activeFilterCount > 0`.
- **URL sync:** use the page's existing `urlParams()` / `replaceState` / `withParams` pattern. Do not push history per keystroke; debounce the number input by about 300 ms. Without JS, the controls sit in a `<form method="get">` with a submit button, hidden when JS is active.
- **Price column:** shows `shownPrice(row, view)`. When a retailer is set, the column header reads "Price at PCCG".
- **Sortable headers:** Price, Name, VRAM (GPU) / Cores (CPU), Released, Listings. Each is a `<button>` that sets sort and direction (a second click toggles `dir`). The active `<th>` has `aria-sort="ascending|descending"` and the others have `aria-sort="none"`.
  - `view.sort === null` keeps the existing grouped layout, with each group header gaining ` · {releaseYear}` (the earliest release year in the group).
  - Any sort flattens to one list.
- **Columns:**
  - a 30-day sparkline per row, using the existing `Sparkline.svelte` if suitable, with `aria-label` "30-day trend: down 4%" (first vs last point, rounded, from `$lib/formats`);
  - CPU: Socket and Threads ("–" when null).
- **Empty state:** "No products match these filters." plus a "Clear filters" link.
- **Phone (390 px):** the filters render inside a native `<dialog>`, opened by a "Filters (N active)" button. "Show N results" closes it. Focus moves into the dialog on open and returns to the button on close. Above `md`, the filters render inline.
- **Search:** the existing text search (`q`) keeps working. While searching, the search results view takes over as today.

- [ ] **Step 1: Failing Playwright tests** in `web/e2e/app.spec.ts` (use `goto()`; the seeded e2e DB). Test cases:
  - "max price preset filters rows and writes ?max=": click $1,000, assert every visible price is ≤ $1,000 and the URL has `max=1000`.
  - "brand + gen + retailer combine and survive reload": set them, reload, assert the controls are restored and the rows are unchanged.
  - "sort by price toggles direction and aria-sort": click Price, assert ascending prices and `aria-sort="ascending"`; click again and assert descending.
  - "shared link renders without JS": open the page with `javaScriptEnabled: false` and `?max=500&sort=price`, and assert the rows are filtered and sorted.
  - "invalid params render the default view": `?max=abc&sort=bogus` shows the same row count as no params.
  - "no hydration errors on a filtered URL": collect console errors on `?brand=AMD&sort=price` and expect none containing "hydration".
  - "empty state": `?max=1` shows "No products match these filters." and Clear filters restores rows.
  - "CPU columns": `/products?category=cpu` shows Socket and Threads headers.

  In `web/e2e/mobile.spec.ts`, using the PHONE viewport and the existing helpers:
  - "filter dialog opens, focuses inside, applies, returns focus": open the dialog, check focus is inside, set a brand, click "Show N results", check focus is back on the button and the URL has the brand;
  - no horizontal overflow with the dialog open.
- [ ] **Step 2: Run** them and expect FAIL.
- [ ] **Step 3: Implement** the UI. Keep `+page.svelte` readable: extract the controls into `CatalogFilters.svelte`, and the header logic into a small helper if it grows. No `toLocale*`.
- [ ] **Step 4: Run** `npm run check` (0/0), `npm test` and `npm run test:e2e`. GREEN. Measure `/products?category=gpu` warm TTFB with `web/scripts/measure.sh` against a temp DB copy (same method as #30: copy `db/trackaroo.db` to a temp file, `TRACKAROO_DB=<copy> PORT=3911 node server.js`). It must be under 20 ms. Record it.
- [ ] **Step 5: Commit**: `feat(web): catalogue filters, sortable columns, sparklines, CPU columns, phone panel (#23)`.

---

### Task 4: Compare best-value markers

**Files:**
- Modify: `web/src/lib/compareRows.ts`, `web/src/routes/compare/+page.svelte`
- Test: `web/test/compareRows.test.ts` (extend), `web/e2e/app.spec.ts`

**Interfaces:**
- Produces:
  - `CompareRow` gains `direction?: 'higher' | 'lower'` (absent = neutral) and `numeric?: (entry) => number | null`.
  - `export function bestIndexes(row: CompareRow, entries: CompareEntry[]): Set<number>`.

- [ ] **Step 1: Failing unit tests** in `compareRows.test.ts`:

```ts
import { bestIndexes, buildCompareRows } from '../src/lib/compareRows';
// Build CompareEntry fixtures the way the existing tests in this file do.
it('higher-is-better marks the max; ties mark all; equal values mark none', () => {
	// VRAM 16 / 12 / 16 -> {0, 2}; 16 / 16 / 16 -> {} ; single numeric value -> {}
});
it('lower-is-better marks the min (TDP, cheapest in stock price)', () => {});
it('neutral rows never mark (socket, launch date, MSRP, architecture)', () => {});
it('null values are ignored, not treated as 0', () => {});
```

  Fill in each body with concrete fixtures and `expect(bestIndexes(row, entries)).toEqual(new Set([...]))` assertions.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - Add `direction` and `numeric` to the rows listed in the Global Constraints. Read the numeric from the same `e.spec` field the `value` formatter uses; for price rows, use the price number.
  - In `compare/+page.svelte`, a best cell renders its value in `font-semibold` plus `<span class="...">Best</span>`, and the cell gets an accessible name that includes "best".
  - Tokens only, no new colours.
- [ ] **Step 4: Playwright:** on `/compare?ids=<two seeded GPU ids with different VRAM>`, the higher-VRAM cell in the VRAM row contains "Best". Read the ids from the e2e DB the way existing specs do.
- [ ] **Step 5: Run** all suites, then commit: `feat(web): compare marks the best value per spec row (#26)`.

---

### Task 5: Price chart — 30-day average, gaps, axis note

**Files:**
- Create: `web/src/lib/chartExtras.ts`, `web/test/chartExtras.test.ts`
- Modify: `web/src/lib/components/PriceChart.svelte`, `web/src/routes/product/[id]/+page.svelte` (pass `avg30`), `web/e2e/app.spec.ts`

**Interfaces:**
- Produces:
  - `gapSegments(dates: string[], values: (number | null)[]): Array<{ from: number; to: number }>`. These are index pairs of the last known point before a run of nulls and the next known point after it, used to draw dotted connectors.
  - `axisStartsAtZero(min: number): boolean`.

- [ ] **Step 1: Failing unit tests** (`chartExtras.test.ts`):

```ts
import { axisStartsAtZero, gapSegments } from '../src/lib/chartExtras';
it('finds gaps between known points', () => {
	expect(gapSegments(['d1','d2','d3','d4','d5'], [10, null, null, 12, 13])).toEqual([{ from: 0, to: 3 }]);
	expect(gapSegments(['d1','d2'], [10, 11])).toEqual([]);
	expect(gapSegments(['d1','d2','d3'], [null, 5, null])).toEqual([]); // leading/trailing nulls are not gaps
});
it('axis note only when the minimum is above zero', () => {
	expect(axisStartsAtZero(0)).toBe(true);
	expect(axisStartsAtZero(450)).toBe(false);
});
```

- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement** the helpers, then in `PriceChart.svelte`:
  - Add an optional `avg30?: number | null` prop. When it is set, draw a dashed horizontal line at that value with the legend entry "30-day avg {formatAud(avg30)}". uPlot has no built-in reference lines: add a constant-value series with `dash` and no points, or use a `draw` hook, whichever fits the existing build. The textContent tooltip must not list it as a retailer.
  - Turn off solid gap bridging (`spanGaps`) for the real series, and draw the `gapSegments` as dotted connectors in a `draw` hook.
  - Read the y-axis minimum after scale calculation and render the caption "Axis doesn't start at $0." under the chart when `!axisStartsAtZero(min)`.
  - The accessible summary and the data table stay.
- [ ] **Step 4: Playwright:** on a seeded product page with enough history:
  - the legend contains "30-day avg";
  - the caption "Axis doesn't start at $0." is present when prices are well above 0 (assert presence for a GPU product).
- [ ] **Step 5: Run** all suites, then commit: `feat(web): chart 30-day average line, dotted gaps, axis note (#27)`.

---

### Task 6: Error page and accessible command palette

**Files:**
- Modify: `web/src/routes/+error.svelte`, `web/src/lib/components/CommandPalette.svelte`
- Test: `web/test/components.test.ts` (extend if it renders components), `web/e2e/app.spec.ts`

- [ ] **Step 1: Failing Playwright tests:**
  - "error page is styled and offers retry": open `/product/999999`, which is a 404 that renders `+error.svelte`. Assert a level-1 heading, a "Try again" link whose href is the current path, a link home, and that the status code text is present.
  - "palette is a combobox":
    - press Ctrl+K and assert the input has `role="combobox"` and `aria-expanded="true"`;
    - type a model name, ArrowDown, and assert `aria-activedescendant` points at an element with `role="option"` and `aria-selected="true"`;
    - Enter navigates to the product page;
    - reopen, press Escape, and assert the dialog is closed and focus is on the element that opened it;
    - Tab while open keeps focus inside the palette.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - Restyle `+error.svelte` with existing tokens and `PageHead`:
    - heading by status (404 "Page not found", otherwise "Something went wrong");
    - `page.error.message` (the friendly text from `hooks.server.ts`);
    - "Try again" (`href={page.url.pathname + page.url.search}`) and "Home" links;
    - the status in small text.
  - Palette: apply the WAI-ARIA combobox + listbox pattern from spec §7, keeping existing behaviour and styling.
- [ ] **Step 4: Run** all suites, then commit: `feat(web): styled error page; command palette follows the combobox pattern (#29)`.

---

### Task 7: Automated accessibility checks

**Files:**
- Modify: `web/package.json` (devDependency `@axe-core/playwright`)
- Create: `web/e2e/a11y.spec.ts`
- Modify: whatever markup axe flags

- [ ] **Step 1: Install:** `npm install --save-dev @axe-core/playwright` (from `web/`). Confirm it lands only in `devDependencies` and that `npm run build` output does not include it.
- [ ] **Step 2: Write the spec:**

```ts
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

async function goto(page: Page, path: string) {
	await page.goto(path);
	await page.waitForLoadState('networkidle');
}

// Rules disabled here need a written reason (spec §7). Keep this list empty
// unless a violation is a false positive that cannot be fixed in markup.
const DISABLED_RULES: string[] = [];

const PAGES = ['/', '/products?category=gpu', '/products?category=cpu', '/product/1', '/deals', '/movers', '/discover', '/product/999999'];

for (const theme of ['light', 'dark'] as const) {
	test.describe(`axe (${theme})`, () => {
		test.use({ colorScheme: theme });
		for (const path of PAGES) {
			test(`${path} has no serious or critical violations`, async ({ page }) => {
				await goto(page, path);
				const results = await new AxeBuilder({ page }).disableRules(DISABLED_RULES).analyze();
				const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
				expect(bad.map((v) => `${v.id}: ${v.nodes.length} node(s) — ${v.help}`)).toEqual([]);
			});
		}
	});
}
```

  - Add `/compare?ids=<two seeded ids>`, reading the ids the way other specs do.
  - If the site's theme toggle uses a stored preference rather than `prefers-color-scheme`, set it the way the existing theme tests do.
- [ ] **Step 3: Run** `npx playwright test e2e/a11y.spec.ts`. List every violation in the report.
- [ ] **Step 4: Fix each violation in markup or tokens.** Typical fixes:
  - contrast: adjust an existing token only if `web/test/contrast.test.ts` still passes;
  - missing labels;
  - duplicate ids;
  - landmark issues.

  Do not disable rules to get green. If one truly cannot be fixed, add it to `DISABLED_RULES` with a reason comment, and add the same reason to spec §7.
- [ ] **Step 5: Run** all suites, then commit: `test(web): axe accessibility checks on main pages, light and dark (#29)`.

---

### Task 8: Docs and gate

**Files:** `README.md` (a short "Browsing the catalogue" paragraph: the filters, shareable URLs, sort), `CLAUDE.md` (counts), `STATUS.md` (dated bullet: what shipped, not deployed, TTFB measured)

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2: Full gate.** Backend `python -m pytest -q`; from `web/`: `npm run check` (0/0), `npm test`, `npm run test:e2e`, `npm run build`. Record the counts.
- [ ] **Step 3: Commit**: `docs: catalogue filters and page polish (#23 #26 #27 #29)`.
