# Offer Row & Product Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the product page's brand→retailer accordion nesting with a flat, cheapest-first offer list and a price-led headline, so the cheapest buyable offer is the first thing on the page.

**Architecture:** All display logic lives in pure functions in `web/src/lib/` (testable without a DOM), consumed by thin Svelte components. `offers.ts` handles the offer list (sorting, facets, volume defaults); `productHeadline.ts` handles the headline stats (deltas, range position). Both build on the existing `ListingDisplay` type from `listingsPanel.ts` rather than duplicating it. No server, schema, or pipeline changes — every field consumed already exists on `ProductHistory`.

**Tech Stack:** SvelteKit 2 + Svelte 5 (runes: `$props`, `$state`, `$derived`), TypeScript, Tailwind, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-23-price-first-ia-design.md` — this plan implements **Stage 1 only** (§1 offer row, §2 product page, §3 headline). Stages 2–4 (`/deals`, homepage, nav) get their own plans.

## Global Constraints

- **Svelte 5 runes only.** `$props()`, `$state()`, `$derived()`. No `export let`, no `$:`. Match the existing components.
- **No new colours.** Only existing tokens from `web/src/app.css`: `--bg`, `--surface`, `--surface-hover`, `--border`, `--border-strong`, `--text`, `--text-muted`, `--accent`, `--accent-soft`, `--up`, `--down`, `--flat`, `--stale`. Used via Tailwind classes (`text-text-muted`, `bg-surface-hover`, `border-border`, `text-down`, `text-up`).
- **`--accent` is reserved for interactive affordances.** Deal/cheap emphasis uses `--down`.
- **Direction is never colour-only.** Every up/down indicator carries an arrow glyph (`▲`/`▼`) AND a signed number.
- **Prices use the `.num` class** (monospace) so columns align.
- **Client components must NOT import runtime values from `$lib/server/...`.** Type-only imports (`import type`) are fine and are what the existing components do. Shared runtime constants go in `web/src/lib/constants.ts`.
- **`MIN_HISTORY_POINTS = 3`** (from `web/src/lib/constants.ts`) gates every 30-day-average figure. Below it, render "not enough history", never a number.
- **Test commands** run from `web/`: `npm test` (Vitest), `npm run check` (svelte-check, must report 0 errors), `npm run test:e2e` (Playwright).
- **Commit messages** follow the repo convention (`feat:`, `fix:`, `refactor:`, `test:`).

---

## File Structure

**Create:**
- `web/src/lib/offers.ts` — offer sorting, facet counts, volume defaults. Pure functions.
- `web/src/lib/productHeadline.ts` — headline deltas and range position. Pure functions.
- `web/src/lib/components/OfferRow.svelte` — one offer (§1).
- `web/src/lib/components/FacetChips.svelte` — one row of filter chips.
- `web/src/lib/components/OfferList.svelte` — composes chips + rows + volume controls (§2).
- `web/src/lib/components/PriceRangeBar.svelte` — the low↔high position bar (§3).
- `web/src/lib/components/ProductHeadline.svelte` — price-led headline (§3).
- `web/test/offers.test.ts`
- `web/test/productHeadline.test.ts`

**Modify:**
- `web/src/lib/listingsPanel.ts` — remove `buildBrandGroups` and `BrandGroup`; keep `toListingDisplays`, `priceRange`, `ListingDisplay`, `PanelFilters`.
- `web/test/listingsPanel.test.ts` — drop `buildBrandGroups` tests.
- `web/test/components.test.ts` — drop the `BrandGroupedListings` import and test; add the new components.
- `web/src/routes/product/[id]/+page.svelte` — swap in the new components.
- `web/e2e/app.spec.ts` — product-page assertions.

**Delete:**
- `web/src/lib/components/BrandGroupedListings.svelte`

**Why this split:** `offers.ts` and `productHeadline.ts` answer different questions (which offers to show vs. is this price good) and change for different reasons. Keeping them separate keeps each file small enough to hold in context, which is why the existing `filters.ts` / `listingsPanel.ts` / `tableSort.ts` split works well in this repo.

---

## Task 1: Offer sorting

**Files:**
- Create: `web/src/lib/offers.ts`
- Create: `web/test/helpers/offers.ts` (shared fixture)
- Test: `web/test/offers.test.ts`

**Interfaces:**
- Consumes: `ListingDisplay` and `toListingDisplays` from `web/src/lib/listingsPanel.ts` (already exist, unchanged).
- Produces: `export type OfferTier = 'in_stock' | 'out_of_stock' | 'delisted'`, `export function offerTier(o: ListingDisplay): OfferTier`, `export function sortOffers(offers: ListingDisplay[]): ListingDisplay[]`. Plus the test fixture `offer(overrides?): ListingDisplay` from `web/test/helpers/offers.ts`, used by Tasks 4 and 5.

Spec §1 "Ordering": cheapest in-stock first, out-of-stock below, delisted last. Never interleave — an out-of-stock $999 above an in-stock $1,099 would misrepresent what is buyable.

- [ ] **Step 1: Write the shared fixture and the failing test**

The fixture lives in `web/test/helpers/` (alongside the existing `seed.ts`) rather than being exported from a `.test.ts` file — importing one test file from another re-registers its `describe` blocks and runs them twice.

Create `web/test/helpers/offers.ts`:

```ts
import type { ListingDisplay } from '../../src/lib/offers';

export function offer(overrides: Partial<ListingDisplay> = {}): ListingDisplay {
	return {
		listingId: 1,
		brand: 'ASUS',
		variantName: 'ASUS TUF RTX 5070 Ti OC 16GB',
		retailer: 'scorptec',
		listingUrl: 'https://example.com/1',
		latestPrice: 1299,
		latestStock: 'in_stock',
		delisted: false,
		inStock: true,
		firstSeen: '2026-03-12',
		lastSeen: '2026-08-23',
		selected: false,
		...overrides
	};
}
```

Create `web/test/offers.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { ListingDisplay } from '../src/lib/offers';
import { offerTier, sortOffers } from '../src/lib/offers';
import { offer } from './helpers/offers';

describe('offerTier', () => {
	it('ranks in stock, then out of stock, then delisted', () => {
		expect(offerTier(offer())).toBe('in_stock');
		expect(offerTier(offer({ inStock: false, latestStock: 'out_of_stock' }))).toBe(
			'out_of_stock'
		);
		expect(offerTier(offer({ delisted: true, inStock: false }))).toBe('delisted');
	});
});

describe('sortOffers', () => {
	it('never places an out-of-stock offer above an in-stock one, even when cheaper', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 999, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 2, latestPrice: 1099 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('sorts in-stock offers cheapest first', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 1499 }),
			offer({ listingId: 2, latestPrice: 1099 }),
			offer({ listingId: 3, latestPrice: 1299 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 3, 1]);
	});

	it('puts delisted offers last regardless of price', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 1, delisted: true, inStock: false }),
			offer({ listingId: 2, latestPrice: 1499 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('sorts null prices last within their tier', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: null, inStock: false, latestStock: 'unknown' }),
			offer({ listingId: 2, latestPrice: 1499, inStock: false, latestStock: 'out_of_stock' })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('does not mutate its input', () => {
		const input = [offer({ listingId: 1, latestPrice: 1499 }), offer({ listingId: 2, latestPrice: 1099 })];
		sortOffers(input);
		expect(input.map((r) => r.listingId)).toEqual([1, 2]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: FAIL — cannot resolve `../src/lib/offers`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/offers.ts`:

```ts
// Offer-list logic for the product page: ordering, facets and volume control.
// Kept separate from productHeadline.ts — this answers "which offers do we
// show", that one answers "is this price any good".
import type { ListingDisplay } from './listingsPanel';

export type { ListingDisplay };

export type OfferTier = 'in_stock' | 'out_of_stock' | 'delisted';

const TIER_ORDER: Record<OfferTier, number> = {
	in_stock: 0,
	out_of_stock: 1,
	delisted: 2
};

export function offerTier(o: ListingDisplay): OfferTier {
	if (o.delisted) return 'delisted';
	return o.inStock ? 'in_stock' : 'out_of_stock';
}

// Cheapest in-stock first. Tiers never interleave: an out-of-stock $999 above
// an in-stock $1,099 would misrepresent what is actually buyable.
export function sortOffers(offers: ListingDisplay[]): ListingDisplay[] {
	return [...offers].sort((a, b) => {
		const tier = TIER_ORDER[offerTier(a)] - TIER_ORDER[offerTier(b)];
		if (tier !== 0) return tier;
		if (a.latestPrice === null && b.latestPrice === null) return 0;
		if (a.latestPrice === null) return 1;
		if (b.latestPrice === null) return -1;
		return a.latestPrice - b.latestPrice;
	});
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/offers.ts web/test/offers.test.ts web/test/helpers/offers.ts
git commit -m "feat(web): offer tier ordering — in-stock cheapest first, delisted last"
```

---

## Task 2: Facet counts

**Files:**
- Modify: `web/src/lib/offers.ts`
- Test: `web/test/offers.test.ts`

**Interfaces:**
- Consumes: `ListingDisplay`, `offerTier` from Task 1.
- Produces: `export interface FacetOption { value: string; label: string; count: number }`, `export function facetCounts(offers: ListingDisplay[], key: 'retailer' | 'brand'): FacetOption[]`.

Spec §2: each chip shows its result count; a chip row hides itself when it would offer only one value (the caller decides that from `facetCounts(...).length <= 1`).

- [ ] **Step 1: Write the failing test**

Append to `web/test/offers.test.ts`:

```ts
import { facetCounts } from '../src/lib/offers';
import { RETAILER_OPTIONS } from '../src/lib/filters';

describe('facetCounts', () => {
	it('counts offers per value, most common first', () => {
		const rows = [
			offer({ listingId: 1, retailer: 'scorptec' }),
			offer({ listingId: 2, retailer: 'pccg' }),
			offer({ listingId: 3, retailer: 'scorptec' })
		];
		expect(facetCounts(rows, 'retailer')).toEqual([
			{ value: 'scorptec', label: 'Scorptec', count: 2 },
			{ value: 'pccg', label: 'PCCG', count: 1 }
		]);
	});

	it('labels retailers from RETAILER_OPTIONS and falls back to the raw slug', () => {
		const known = RETAILER_OPTIONS[0];
		const rows = [offer({ retailer: known.value }), offer({ listingId: 2, retailer: 'newshop' })];
		const counts = facetCounts(rows, 'retailer');
		expect(counts.find((c) => c.value === known.value)?.label).toBe(known.label);
		expect(counts.find((c) => c.value === 'newshop')?.label).toBe('newshop');
	});

	it('uses the brand string as its own label', () => {
		const rows = [offer({ brand: 'ASUS' }), offer({ listingId: 2, brand: 'MSI' })];
		expect(facetCounts(rows, 'brand').map((c) => c.label)).toEqual(['ASUS', 'MSI']);
	});

	it('breaks count ties alphabetically so ordering is stable', () => {
		const rows = [offer({ brand: 'ZOTAC' }), offer({ listingId: 2, brand: 'ASUS' })];
		expect(facetCounts(rows, 'brand').map((c) => c.value)).toEqual(['ASUS', 'ZOTAC']);
	});

	it('returns one entry when every offer shares a value, so the caller can hide the row', () => {
		const rows = [offer({ brand: 'ASUS' }), offer({ listingId: 2, brand: 'ASUS' })];
		expect(facetCounts(rows, 'brand')).toHaveLength(1);
	});

	it('returns an empty array for no offers', () => {
		expect(facetCounts([], 'brand')).toEqual([]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: FAIL — `facetCounts` is not exported.

- [ ] **Step 3: Write minimal implementation**

Append to `web/src/lib/offers.ts`:

```ts
import { RETAILER_OPTIONS } from './filters';

export interface FacetOption {
	value: string;
	label: string;
	count: number;
}

const RETAILER_LABELS = new Map(RETAILER_OPTIONS.map((o) => [o.value as string, o.label]));

// Brand is already a display string (derived by deriveListingBrand); retailer
// is a slug that needs its label. An unknown slug falls back to itself so a
// newly-added retailer shows up rather than rendering blank.
function facetLabel(key: 'retailer' | 'brand', value: string): string {
	if (key === 'brand') return value;
	return RETAILER_LABELS.get(value) ?? value;
}

export function facetCounts(
	offers: ListingDisplay[],
	key: 'retailer' | 'brand'
): FacetOption[] {
	const counts = new Map<string, number>();
	for (const o of offers) {
		const value = o[key];
		counts.set(value, (counts.get(value) ?? 0) + 1);
	}
	return [...counts.entries()]
		.map(([value, count]) => ({ value, label: facetLabel(key, value), count }))
		.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: PASS — 11 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/offers.ts web/test/offers.test.ts
git commit -m "feat(web): facet counts for offer-list retailer and brand chips"
```

---

## Task 3: Volume control — stock default and the 8-row cap

**Files:**
- Modify: `web/src/lib/offers.ts`
- Test: `web/test/offers.test.ts`

**Interfaces:**
- Consumes: `sortOffers`, `offerTier` from Task 1.
- Produces: `export const OFFER_PAGE_SIZE = 8`, `export interface OfferFilters { inStockOnly: boolean; retailer: string | null; brand: string | null; query: string }`, `export interface OfferView { visible: ListingDisplay[]; matched: number; total: number; inStockCount: number; showExpander: boolean; stockFilterApplied: boolean; stockFilterForcedOff: boolean }`, `export function buildOfferView(offers: ListingDisplay[], filters: OfferFilters, expanded: boolean): OfferView`.

This is spec §2 "Volume control" — the part most likely to produce a confusing page, so the interaction rules are tested explicitly:

- The stock filter applies **before** the 8-row cap, so the expander's total matches what the filter left.
- A product with **zero** in-stock listings auto-disables the filter (`stockFilterForcedOff`) rather than rendering an empty page for a product that plainly has prices.
- No expander below 9 offers.
- Chip filtering re-computes both the visible slice and the expander total.

- [ ] **Step 1: Write the failing test**

Append to `web/test/offers.test.ts`:

```ts
import { buildOfferView, OFFER_PAGE_SIZE, type OfferFilters } from '../src/lib/offers';

const NO_FILTERS: OfferFilters = { inStockOnly: false, retailer: null, brand: null, query: '' };

function manyOffers(n: number, overrides: Partial<ListingDisplay> = {}): ListingDisplay[] {
	return Array.from({ length: n }, (_, i) =>
		offer({ listingId: i + 1, latestPrice: 1000 + i, ...overrides })
	);
}

describe('buildOfferView volume control', () => {
	it('caps the visible list at OFFER_PAGE_SIZE and offers an expander', () => {
		const view = buildOfferView(manyOffers(31), NO_FILTERS, false);
		expect(view.visible).toHaveLength(OFFER_PAGE_SIZE);
		expect(view.matched).toBe(31);
		expect(view.showExpander).toBe(true);
	});

	it('shows every offer when expanded', () => {
		const view = buildOfferView(manyOffers(31), NO_FILTERS, true);
		expect(view.visible).toHaveLength(31);
	});

	it('renders no expander at or below the page size', () => {
		expect(buildOfferView(manyOffers(8), NO_FILTERS, false).showExpander).toBe(false);
		expect(buildOfferView(manyOffers(9), NO_FILTERS, false).showExpander).toBe(true);
	});

	it('applies the stock filter BEFORE the cap so the expander total matches the filter', () => {
		const rows = [
			...manyOffers(18),
			...manyOffers(13, { inStock: false, latestStock: 'out_of_stock' }).map((o, i) => ({
				...o,
				listingId: 100 + i
			}))
		];
		const view = buildOfferView(rows, { ...NO_FILTERS, inStockOnly: true }, false);
		expect(view.visible).toHaveLength(OFFER_PAGE_SIZE);
		expect(view.matched).toBe(18);
		expect(view.total).toBe(31);
		expect(view.visible.every((o) => o.inStock)).toBe(true);
	});

	it('auto-disables the stock filter when nothing is in stock, rather than rendering empty', () => {
		const rows = manyOffers(4, { inStock: false, latestStock: 'out_of_stock' });
		const view = buildOfferView(rows, { ...NO_FILTERS, inStockOnly: true }, false);
		expect(view.stockFilterForcedOff).toBe(true);
		expect(view.stockFilterApplied).toBe(false);
		expect(view.visible).toHaveLength(4);
	});

	it('reports inStockCount for the "18 of 31" label', () => {
		const rows = [
			...manyOffers(18),
			...manyOffers(13, { inStock: false, latestStock: 'out_of_stock' }).map((o, i) => ({
				...o,
				listingId: 100 + i
			}))
		];
		const view = buildOfferView(rows, NO_FILTERS, false);
		expect(view.inStockCount).toBe(18);
		expect(view.total).toBe(31);
	});

	it('re-computes the expander total when a chip filter narrows the set', () => {
		const rows = [
			...manyOffers(10, { retailer: 'scorptec' }),
			...manyOffers(10, { retailer: 'pccg' }).map((o, i) => ({ ...o, listingId: 100 + i }))
		];
		const view = buildOfferView(rows, { ...NO_FILTERS, retailer: 'pccg' }, false);
		expect(view.matched).toBe(10);
		expect(view.visible.every((o) => o.retailer === 'pccg')).toBe(true);
	});

	it('filters by brand chip', () => {
		const rows = [offer({ listingId: 1, brand: 'ASUS' }), offer({ listingId: 2, brand: 'MSI' })];
		const view = buildOfferView(rows, { ...NO_FILTERS, brand: 'MSI' }, false);
		expect(view.visible.map((o) => o.listingId)).toEqual([2]);
	});

	it('matches the free-text query against variant name and retailer, case-insensitively', () => {
		const rows = [
			offer({ listingId: 1, variantName: 'ASUS TUF RTX 5070 Ti OC' }),
			offer({ listingId: 2, variantName: 'MSI Ventus RTX 5070 Ti' })
		];
		expect(buildOfferView(rows, { ...NO_FILTERS, query: 'tuf' }, false).visible).toHaveLength(1);
		expect(buildOfferView(rows, { ...NO_FILTERS, query: '  ' }, false).visible).toHaveLength(2);
	});

	it('returns the cheapest in-stock offer first', () => {
		const rows = [
			offer({ listingId: 1, latestPrice: 1499 }),
			offer({ listingId: 2, latestPrice: 1099 })
		];
		expect(buildOfferView(rows, NO_FILTERS, false).visible[0].listingId).toBe(2);
	});

	it('handles an empty offer list', () => {
		const view = buildOfferView([], NO_FILTERS, false);
		expect(view.visible).toEqual([]);
		expect(view.showExpander).toBe(false);
		expect(view.stockFilterForcedOff).toBe(false);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: FAIL — `buildOfferView` is not exported.

- [ ] **Step 3: Write minimal implementation**

Append to `web/src/lib/offers.ts`:

```ts
// Flattening the accordions removed repetition but not volume: 50 listings is
// still 50 rows. These two defaults are what actually shorten the page.
export const OFFER_PAGE_SIZE = 8;

export interface OfferFilters {
	inStockOnly: boolean;
	retailer: string | null;
	brand: string | null;
	query: string;
}

export interface OfferView {
	visible: ListingDisplay[];
	// Offers matching the active filters (the expander's total).
	matched: number;
	// Offers before any filtering (the "of 31" in "18 of 31").
	total: number;
	inStockCount: number;
	showExpander: boolean;
	// Whether the stock filter actually ran. False when forced off.
	stockFilterApplied: boolean;
	// The product has no in-stock offers at all, so the stock filter was
	// ignored to avoid rendering an empty page for a product that has prices.
	stockFilterForcedOff: boolean;
}

export function buildOfferView(
	offers: ListingDisplay[],
	filters: OfferFilters,
	expanded: boolean
): OfferView {
	const total = offers.length;
	const inStockCount = offers.filter((o) => o.inStock).length;

	const stockFilterForcedOff = filters.inStockOnly && inStockCount === 0 && total > 0;
	const stockFilterApplied = filters.inStockOnly && !stockFilterForcedOff;

	const q = filters.query.trim().toLowerCase();
	const matchedOffers = offers.filter((o) => {
		if (stockFilterApplied && !o.inStock) return false;
		if (filters.retailer && o.retailer !== filters.retailer) return false;
		if (filters.brand && o.brand !== filters.brand) return false;
		if (q) {
			const haystack = `${o.variantName ?? ''} ${o.retailer}`.toLowerCase();
			if (!haystack.includes(q)) return false;
		}
		return true;
	});

	const sorted = sortOffers(matchedOffers);
	return {
		visible: expanded ? sorted : sorted.slice(0, OFFER_PAGE_SIZE),
		matched: sorted.length,
		total,
		inStockCount,
		showExpander: sorted.length > OFFER_PAGE_SIZE,
		stockFilterApplied,
		stockFilterForcedOff
	};
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/offers.test.ts`
Expected: PASS — 22 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/offers.ts web/test/offers.test.ts
git commit -m "feat(web): offer-list volume control — in-stock default and 8-row cap"
```

---

## Task 4: Headline stats

**Files:**
- Create: `web/src/lib/productHeadline.ts`
- Test: `web/test/productHeadline.test.ts`

**Interfaces:**
- Consumes: `ListingDisplay` (Task 1), `MIN_HISTORY_POINTS` from `web/src/lib/constants.ts`, `PriceBandPoint` and `ProductStats` types from `web/src/lib/server/repos.ts` (type-only import).
- Produces: `export interface Headline { currentPrice: number | null; currentRetailer: string | null; allTimeLow: number | null; allTimeHigh: number | null; avg30: number | null; vsAvg30Pct: number | null; vsAllTimeLowPct: number | null; rangePosition: number | null }`, `export function buildHeadline(offers: ListingDisplay[], band: PriceBandPoint[], stats: ProductStats): Headline`.

Spec §3. `rangePosition` is `0..1` for the bar, or `null` when the bar would be meaningless (high === low, or missing data) — the component then falls back to text.

- [ ] **Step 1: Write the failing test**

Create `web/test/productHeadline.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { PriceBandPoint, ProductStats } from '../src/lib/server/repos';
import type { ListingDisplay } from '../src/lib/offers';
import { buildHeadline } from '../src/lib/productHeadline';
import { offer } from './helpers/offers';

function band(points: Array<[string, number, number]>): PriceBandPoint[] {
	return points.map(([date, low, high]) => ({
		date,
		low,
		high,
		cheapestInStock: low
	})) as PriceBandPoint[];
}

const STATS: ProductStats = { avg30: 1400, avg30Points: 30 };
const THIN_STATS: ProductStats = { avg30: 1400, avg30Points: 2 };

describe('buildHeadline', () => {
	it('takes the cheapest in-stock offer as the current price', () => {
		const offers: ListingDisplay[] = [
			offer({ listingId: 1, latestPrice: 1499, retailer: 'pccg' }),
			offer({ listingId: 2, latestPrice: 1299, retailer: 'scorptec' })
		];
		const h = buildHeadline(offers, band([['2026-08-23', 1249, 1689]]), STATS);
		expect(h.currentPrice).toBe(1299);
		expect(h.currentRetailer).toBe('scorptec');
	});

	it('ignores out-of-stock and delisted offers when picking the current price', () => {
		const offers: ListingDisplay[] = [
			offer({ listingId: 1, latestPrice: 999, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 2, latestPrice: 1, delisted: true, inStock: false }),
			offer({ listingId: 3, latestPrice: 1299 })
		];
		expect(buildHeadline(offers, band([['2026-08-23', 1249, 1689]]), STATS).currentPrice).toBe(1299);
	});

	it('derives all-time low and high across the whole band', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([
				['2026-03-12', 1249, 1500],
				['2026-08-23', 1300, 1689]
			]),
			STATS
		);
		expect(h.allTimeLow).toBe(1249);
		expect(h.allTimeHigh).toBe(1689);
	});

	it('computes the delta against the 30-day average', () => {
		const h = buildHeadline([offer({ latestPrice: 1288 })], band([['2026-08-23', 1249, 1689]]), STATS);
		expect(h.vsAvg30Pct).toBeCloseTo(-8, 1);
	});

	it('suppresses the 30-day delta below MIN_HISTORY_POINTS', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1288 })],
			band([['2026-08-23', 1249, 1689]]),
			THIN_STATS
		);
		expect(h.vsAvg30Pct).toBeNull();
		expect(h.avg30).toBeNull();
	});

	it('computes the delta above the all-time low', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.vsAllTimeLowPct).toBeCloseTo(4, 0);
	});

	it('positions the current price within the all-time range', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1469 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.rangePosition).toBeCloseTo(0.5, 2);
	});

	it('clamps the range position into 0..1 when today sits outside the recorded band', () => {
		const below = buildHeadline(
			[offer({ latestPrice: 1000 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(below.rangePosition).toBe(0);
	});

	it('returns a null range position when high equals low, so the bar degrades to text', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([['2026-08-23', 1299, 1299]]),
			STATS
		);
		expect(h.rangePosition).toBeNull();
	});

	it('handles a product with no in-stock offers', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299, inStock: false, latestStock: 'out_of_stock' })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.currentPrice).toBeNull();
		expect(h.vsAvg30Pct).toBeNull();
		expect(h.rangePosition).toBeNull();
	});

	it('handles an empty band', () => {
		const h = buildHeadline([offer({ latestPrice: 1299 })], [], STATS);
		expect(h.allTimeLow).toBeNull();
		expect(h.allTimeHigh).toBeNull();
		expect(h.rangePosition).toBeNull();
		expect(h.vsAllTimeLowPct).toBeNull();
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/productHeadline.test.ts`
Expected: FAIL — cannot resolve `../src/lib/productHeadline`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/productHeadline.ts`:

```ts
// Headline stats for the product page: the cheapest buyable price and the two
// deltas that answer "is now a good time to buy". Separate from offers.ts,
// which decides which rows to show.
import { MIN_HISTORY_POINTS } from './constants';
import type { ListingDisplay } from './offers';
import type { PriceBandPoint, ProductStats } from './server/repos';

export interface Headline {
	currentPrice: number | null;
	currentRetailer: string | null;
	allTimeLow: number | null;
	allTimeHigh: number | null;
	// Null when there is not enough history to trust it.
	avg30: number | null;
	vsAvg30Pct: number | null;
	vsAllTimeLowPct: number | null;
	// 0..1 for the range bar, or null when a bar would be meaningless.
	rangePosition: number | null;
}

export function buildHeadline(
	offers: ListingDisplay[],
	band: PriceBandPoint[],
	stats: ProductStats
): Headline {
	let currentPrice: number | null = null;
	let currentRetailer: string | null = null;
	for (const o of offers) {
		if (!o.inStock || o.delisted || o.latestPrice === null) continue;
		if (currentPrice === null || o.latestPrice < currentPrice) {
			currentPrice = o.latestPrice;
			currentRetailer = o.retailer;
		}
	}

	let allTimeLow: number | null = null;
	let allTimeHigh: number | null = null;
	for (const p of band) {
		if (p.low !== null && (allTimeLow === null || p.low < allTimeLow)) allTimeLow = p.low;
		if (p.high !== null && (allTimeHigh === null || p.high > allTimeHigh)) allTimeHigh = p.high;
	}

	// The same guard the old "30d avg" chip used: a three-day average is not an
	// average, and presenting one as a deal signal would mislead.
	const avg30 =
		stats.avg30 !== null && stats.avg30Points >= MIN_HISTORY_POINTS ? stats.avg30 : null;

	const vsAvg30Pct =
		currentPrice !== null && avg30 !== null && avg30 !== 0
			? ((currentPrice - avg30) / avg30) * 100
			: null;

	const vsAllTimeLowPct =
		currentPrice !== null && allTimeLow !== null && allTimeLow !== 0
			? ((currentPrice - allTimeLow) / allTimeLow) * 100
			: null;

	const rangePosition =
		currentPrice !== null && allTimeLow !== null && allTimeHigh !== null && allTimeHigh > allTimeLow
			? Math.min(1, Math.max(0, (currentPrice - allTimeLow) / (allTimeHigh - allTimeLow)))
			: null;

	return {
		currentPrice,
		currentRetailer,
		allTimeLow,
		allTimeHigh,
		avg30,
		vsAvg30Pct,
		vsAllTimeLowPct,
		rangePosition
	};
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/productHeadline.test.ts`
Expected: PASS — 11 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/productHeadline.ts web/test/productHeadline.test.ts
git commit -m "feat(web): product headline stats — deltas and all-time range position"
```

---

## Task 5: OfferRow component

**Files:**
- Create: `web/src/lib/components/OfferRow.svelte`
- Modify: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `ListingDisplay` from `$lib/offers`; existing `StockBadge`, `Badge`, `BrandIcon` components; `formatAud`, `formatPct`, `formatRelative`, `titleCase` from `$lib/formats`; `RETAILER_OPTIONS` from `$lib/filters`.
- Produces: component with props `{ offer: ListingDisplay, avg30: number | null, onToggleChart?: (listingId: number) => void }`.

Spec §1. Price leads. Brand and retailer visible on every row. `View →` links out.

- [ ] **Step 1: Write the failing test**

Append to `web/test/components.test.ts` (inside the existing top-level `describe`, reusing the file's existing `renderComponent` helper):

```ts
import OfferRow from '../src/lib/components/OfferRow.svelte';
import { offer as offerRow } from './helpers/offers';

describe('OfferRow', () => {
	it('shows the price, brand and retailer on every row', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toContain('$1,299');
		expect(html).toContain('ASUS');
		expect(html).toContain('Scorptec');
	});

	it('links out to the retailer with a safe target', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toContain('href="https://example.com/1"');
		expect(html).toContain('rel="noopener noreferrer"');
	});

	it('shows a down-arrow delta with a signed number when below the 30-day average', () => {
		const html = renderComponent(OfferRow, { offer: offerRow({ latestPrice: 1288 }), avg30: 1400 });
		expect(html).toContain('▼');
		expect(html).toContain('vs 30d avg');
	});

	it('shows an up arrow when above the average', () => {
		const html = renderComponent(OfferRow, { offer: offerRow({ latestPrice: 1500 }), avg30: 1400 });
		expect(html).toContain('▲');
	});

	it('says so plainly when there is not enough history, rather than showing a number', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: null });
		expect(html).toContain('Not enough history');
		expect(html).not.toContain('vs 30d avg');
	});

	it('marks a delisted offer and omits its stock badge', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ delisted: true, inStock: false }),
			avg30: 1400
		});
		expect(html).toContain('Delisted');
	});

	it('renders no price for an offer that has never had one', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ latestPrice: null, inStock: false, latestStock: 'unknown' }),
			avg30: 1400
		});
		expect(html).toContain('—');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: FAIL — cannot resolve `../src/lib/components/OfferRow.svelte`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/components/OfferRow.svelte`:

```svelte
<script lang="ts">
	import Badge from './Badge.svelte';
	import BrandIcon from './BrandIcon.svelte';
	import StockBadge from './StockBadge.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct, formatRelative, titleCase } from '$lib/formats';
	import type { ListingDisplay } from '$lib/offers';

	let {
		offer,
		avg30,
		onToggleChart
	}: {
		offer: ListingDisplay;
		avg30: number | null;
		onToggleChart?: (listingId: number) => void;
	} = $props();

	const retailerLabel = $derived(
		RETAILER_OPTIONS.find((o) => o.value === offer.retailer)?.label ?? offer.retailer
	);

	const title = $derived(titleCase(offer.variantName) || `${retailerLabel} listing`);

	// Null whenever the average is untrustworthy (see MIN_HISTORY_POINTS) or the
	// offer has no price — the row then states that instead of showing a number.
	const deltaPct = $derived(
		offer.latestPrice !== null && avg30 !== null && avg30 !== 0
			? ((offer.latestPrice - avg30) / avg30) * 100
			: null
	);
</script>

<div class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-surface-hover">
	<div class="order-1 w-24 shrink-0">
		{#if offer.latestPrice !== null}
			<span class="num text-base font-semibold text-text">{formatAud(offer.latestPrice)}</span>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</div>

	<div class="order-2 min-w-0 flex-1 basis-full sm:basis-auto">
		<span class="block truncate text-sm font-medium text-text" title={title}>{title}</span>
		<span class="flex items-center gap-1.5 text-xs text-text-muted">
			<BrandIcon brand={offer.brand} size={12} />
			{offer.brand} · {retailerLabel}
			{#if offer.lastSeen}
				· updated {formatRelative(offer.lastSeen)}
			{/if}
		</span>
	</div>

	<div class="order-3 shrink-0 text-xs">
		{#if deltaPct !== null}
			<span class={deltaPct < 0 ? 'text-down' : deltaPct > 0 ? 'text-up' : 'text-text-muted'}>
				{deltaPct < 0 ? '▼' : deltaPct > 0 ? '▲' : '·'}
				{formatPct(deltaPct)} vs 30d avg
			</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</div>

	<div class="order-4 shrink-0">
		{#if offer.delisted}
			<Badge tone="stale" label="Delisted" />
		{:else}
			<StockBadge stock={offer.latestStock} />
		{/if}
	</div>

	{#if onToggleChart}
		<button
			type="button"
			aria-pressed={offer.selected}
			onclick={() => onToggleChart(offer.listingId)}
			class="order-5 shrink-0 rounded-md border border-border px-2 py-1 text-xs {offer.selected
				? 'border-accent bg-accent-soft font-medium text-accent'
				: 'bg-surface text-text-muted hover:text-text'}"
		>
			{offer.selected ? 'On chart' : 'Chart'}
		</button>
	{/if}

	<a
		href={offer.listingUrl}
		target="_blank"
		rel="noopener noreferrer"
		class="order-6 shrink-0 text-xs text-accent"
	>
		View →
	</a>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS — the 7 new OfferRow tests plus all existing component tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/OfferRow.svelte web/test/components.test.ts
git commit -m "feat(web): OfferRow component — price-led row with brand, retailer and link"
```

---

## Task 6: FacetChips component

**Files:**
- Create: `web/src/lib/components/FacetChips.svelte`
- Modify: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `FacetOption` from `$lib/offers` (Task 2).
- Produces: component with props `{ label: string, options: FacetOption[], selected: string | null, allCount: number, onSelect: (value: string | null) => void }`.

Spec §2: chips are `<button aria-pressed>`, keyboard reachable, `--accent-soft` when active. **The row hides itself when it would offer only one value.**

- [ ] **Step 1: Write the failing test**

Append to `web/test/components.test.ts`:

```ts
import FacetChips from '../src/lib/components/FacetChips.svelte';

describe('FacetChips', () => {
	const twoOptions = [
		{ value: 'scorptec', label: 'Scorptec', count: 4 },
		{ value: 'pccg', label: 'PCCG', count: 3 }
	];

	it('renders a chip per option with its count, plus an All chip', () => {
		const html = renderComponent(FacetChips, {
			label: 'Retailer',
			options: twoOptions,
			selected: null,
			allCount: 7,
			onSelect: () => {}
		});
		expect(html).toContain('Scorptec');
		expect(html).toContain('4');
		expect(html).toContain('All');
	});

	it('renders nothing when there is only one value to choose from', () => {
		const html = renderComponent(FacetChips, {
			label: 'Brand',
			options: [{ value: 'ASUS', label: 'ASUS', count: 5 }],
			selected: null,
			allCount: 5,
			onSelect: () => {}
		});
		expect(html.trim()).toBe('');
	});

	it('renders nothing for no options', () => {
		const html = renderComponent(FacetChips, {
			label: 'Brand',
			options: [],
			selected: null,
			allCount: 0,
			onSelect: () => {}
		});
		expect(html.trim()).toBe('');
	});

	it('marks the selected chip with aria-pressed for assistive tech', () => {
		const html = renderComponent(FacetChips, {
			label: 'Retailer',
			options: twoOptions,
			selected: 'pccg',
			allCount: 7,
			onSelect: () => {}
		});
		expect(html).toContain('aria-pressed="true"');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: FAIL — cannot resolve `../src/lib/components/FacetChips.svelte`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/components/FacetChips.svelte`:

```svelte
<script lang="ts">
	import type { FacetOption } from '$lib/offers';

	let {
		label,
		options,
		selected,
		allCount,
		onSelect
	}: {
		label: string;
		options: FacetOption[];
		selected: string | null;
		allCount: number;
		onSelect: (value: string | null) => void;
	} = $props();

	// A row offering one value is not a choice — it is clutter. Hide it.
	const useful = $derived(options.length > 1);

	function chipClass(active: boolean): string {
		return active
			? 'rounded-full border border-accent bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent'
			: 'rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-text-muted hover:bg-surface-hover hover:text-text';
	}
</script>

{#if useful}
	<div class="flex flex-wrap items-center gap-1.5">
		<span class="w-16 shrink-0 text-xs text-text-muted">{label}</span>
		<button
			type="button"
			aria-pressed={selected === null}
			onclick={() => onSelect(null)}
			class={chipClass(selected === null)}
		>
			All <span class="num">{allCount}</span>
		</button>
		{#each options as opt (opt.value)}
			<button
				type="button"
				aria-pressed={selected === opt.value}
				onclick={() => onSelect(opt.value)}
				class={chipClass(selected === opt.value)}
			>
				{opt.label} <span class="num">{opt.count}</span>
			</button>
		{/each}
	</div>
{/if}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS — 4 new FacetChips tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/FacetChips.svelte web/test/components.test.ts
git commit -m "feat(web): FacetChips component, self-hiding when it offers one value"
```

---

## Task 7: OfferList component

**Files:**
- Create: `web/src/lib/components/OfferList.svelte`
- Modify: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `buildOfferView`, `facetCounts`, `OfferFilters` from `$lib/offers`; `toListingDisplays` from `$lib/listingsPanel`; `OfferRow` (Task 5); `FacetChips` (Task 6).
- Produces: component with props `{ series: Series[], productBrand: string, avg30: number | null, selected: ReadonlySet<number>, onToggleListing: (listingId: number) => void }`.

Spec §2, including both volume defaults. **`inStockOnly` starts `true`.**

- [ ] **Step 1: Write the failing test**

Append to `web/test/components.test.ts` (reusing the file's existing `series` helper style — build `Series` objects with `ListingRow` + `SnapshotRow` as `listingsPanel.test.ts` does):

```ts
import OfferList from '../src/lib/components/OfferList.svelte';
import type { Series } from '../src/lib/server/repos';
import type { ListingRow, SnapshotRow } from '../src/lib/server/db';

function snap(date: string, price: number, stock: string): SnapshotRow {
	return {
		id: 1,
		retailer_listing_id: 1,
		snapshot_date: date,
		price_aud: price,
		stock_status: stock as SnapshotRow['stock_status'],
		scraped_at: `${date}T04:00:00.000Z`
	};
}

function ser(id: number, variant: string, price: number, stock = 'in_stock'): Series {
	const listing: ListingRow = {
		id,
		product_id: 1,
		retailer: 'scorptec',
		variant_name: variant,
		retailer_sku: `SKU${id}`,
		listing_url: `https://example.com/${id}`,
		status: 'active',
		first_seen_at: '2026-03-12T04:00:00.000Z',
		last_seen_at: '2026-08-23T04:00:00.000Z',
		last_snapshot_at: '2026-08-23T04:00:00.000Z'
	};
	return { listing, points: [snap('2026-08-23', price, stock)] };
}

describe('OfferList', () => {
	const base = {
		productBrand: 'NVIDIA',
		avg30: 1400,
		selected: new Set<number>(),
		onToggleListing: () => {}
	};

	it('shows at most 8 offers and an expander stating the true total', () => {
		const series = Array.from({ length: 12 }, (_, i) =>
			ser(i + 1, `ASUS Card ${i + 1}`, 1000 + i)
		);
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('Show all 12 offers');
	});

	it('renders no expander when there are 8 or fewer offers', () => {
		const series = Array.from({ length: 8 }, (_, i) => ser(i + 1, `ASUS Card ${i + 1}`, 1000 + i));
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).not.toContain('Show all');
	});

	it('defaults to in-stock only and says what it is hiding', () => {
		const series = [
			ser(1, 'ASUS In Stock', 1299, 'in_stock'),
			ser(2, 'ASUS Sold Out', 999, 'out_of_stock')
		];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('1 of 2');
		expect(html).toContain('ASUS In Stock');
		expect(html).not.toContain('ASUS Sold Out');
	});

	it('shows everything when nothing is in stock, rather than an empty list', () => {
		const series = [
			ser(1, 'ASUS Sold Out', 1299, 'out_of_stock'),
			ser(2, 'MSI Sold Out', 1199, 'out_of_stock')
		];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('ASUS Sold Out');
		expect(html).toContain('MSI Sold Out');
	});

	it('puts the cheapest in-stock offer first', () => {
		const series = [ser(1, 'ASUS Pricey', 1499), ser(2, 'MSI Cheap', 1099)];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html.indexOf('MSI Cheap')).toBeLessThan(html.indexOf('ASUS Pricey'));
	});

	it('renders an empty state when there are no listings at all', () => {
		const html = renderComponent(OfferList, { ...base, series: [] });
		expect(html).toContain('No listings');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: FAIL — cannot resolve `../src/lib/components/OfferList.svelte`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/components/OfferList.svelte`:

```svelte
<script lang="ts">
	import FacetChips from './FacetChips.svelte';
	import OfferRow from './OfferRow.svelte';
	import { toListingDisplays } from '$lib/listingsPanel';
	import { buildOfferView, facetCounts, type OfferFilters } from '$lib/offers';
	import type { Series } from '$lib/server/repos';

	let {
		series,
		productBrand,
		avg30,
		selected,
		onToggleListing
	}: {
		series: Series[];
		productBrand: string;
		avg30: number | null;
		selected: ReadonlySet<number>;
		onToggleListing: (listingId: number) => void;
	} = $props();

	// Out-of-stock listings are noise for someone shopping today, and on a
	// popular GPU they are often half the rows. The control states what it
	// hides, so nothing is silently disappeared.
	let inStockOnly = $state(true);
	let retailer = $state<string | null>(null);
	let brand = $state<string | null>(null);
	let query = $state('');
	let expanded = $state(false);

	const offers = $derived(toListingDisplays(series, productBrand, selected));
	const filters = $derived<OfferFilters>({ inStockOnly, retailer, brand, query });
	const view = $derived(buildOfferView(offers, filters, expanded));
	const retailerFacets = $derived(facetCounts(offers, 'retailer'));
	const brandFacets = $derived(facetCounts(offers, 'brand'));
</script>

<div class="overflow-hidden rounded-md border border-border">
	<div class="space-y-2 border-b border-border bg-surface px-3 py-2">
		<h2 class="text-xs font-semibold uppercase tracking-wide text-text-muted">Offers</h2>

		<FacetChips
			label="Retailer"
			options={retailerFacets}
			selected={retailer}
			allCount={offers.length}
			onSelect={(v) => {
				retailer = v;
				expanded = false;
			}}
		/>
		<FacetChips
			label="Brand"
			options={brandFacets}
			selected={brand}
			allCount={offers.length}
			onSelect={(v) => {
				brand = v;
				expanded = false;
			}}
		/>

		<div class="flex flex-wrap items-center gap-2">
			<input
				type="search"
				aria-label="Filter offers by name"
				placeholder="Filter by name…"
				bind:value={query}
				class="w-full min-w-0 flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
			{#if !view.stockFilterForcedOff}
				<label class="flex items-center gap-1.5 text-xs text-text-muted">
					<input type="checkbox" bind:checked={inStockOnly} class="accent-accent" />
					In stock only ({view.inStockCount} of {view.total})
				</label>
			{/if}
		</div>
	</div>

	{#if view.stockFilterForcedOff}
		<p class="border-b border-border bg-surface px-3 py-2 text-xs text-text-muted">
			Nothing is in stock right now — showing all {view.total} offers.
		</p>
	{/if}

	{#if view.visible.length === 0}
		<p class="px-4 py-8 text-center text-sm text-text-muted">
			No listings match the current filters.
		</p>
	{:else}
		<div class="divide-y divide-border">
			{#each view.visible as o (o.listingId)}
				<OfferRow offer={o} {avg30} onToggleChart={onToggleListing} />
			{/each}
		</div>
	{/if}

	{#if view.showExpander}
		<button
			type="button"
			aria-expanded={expanded}
			onclick={() => (expanded = !expanded)}
			class="w-full border-t border-border px-3 py-2 text-xs text-accent hover:bg-surface-hover"
		>
			{expanded ? 'Show fewer offers' : `Show all ${view.matched} offers`}
		</button>
	{/if}
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS — 6 new OfferList tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/OfferList.svelte web/test/components.test.ts
git commit -m "feat(web): OfferList — flat cheapest-first offers with facets and volume defaults"
```

---

## Task 8: PriceRangeBar component

**Files:**
- Create: `web/src/lib/components/PriceRangeBar.svelte`
- Modify: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `formatAud` from `$lib/formats`.
- Produces: component with props `{ low: number, high: number, current: number, position: number | null }`.

Spec §3: `role="img"` with an `aria-label` stating all three figures in words, because a positional bar is invisible to assistive tech. Degrades to text when `position` is null.

- [ ] **Step 1: Write the failing test**

Append to `web/test/components.test.ts`:

```ts
import PriceRangeBar from '../src/lib/components/PriceRangeBar.svelte';

describe('PriceRangeBar', () => {
	it('describes itself in words for assistive tech', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1249,
			high: 1689,
			current: 1469,
			position: 0.5
		});
		expect(html).toContain('role="img"');
		expect(html).toContain('$1,249');
		expect(html).toContain('$1,689');
		expect(html).toContain('$1,469');
	});

	it('places the marker at the given position', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1000,
			high: 2000,
			current: 1250,
			position: 0.25
		});
		expect(html).toContain('25%');
	});

	it('degrades to a plain text line when a bar would be meaningless', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1299,
			high: 1299,
			current: 1299,
			position: null
		});
		expect(html).not.toContain('role="img"');
		expect(html).toContain('$1,299');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: FAIL — cannot resolve `../src/lib/components/PriceRangeBar.svelte`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/components/PriceRangeBar.svelte`:

```svelte
<script lang="ts">
	import { formatAud } from '$lib/formats';

	let {
		low,
		high,
		current,
		position
	}: { low: number; high: number; current: number; position: number | null } = $props();

	const pct = $derived(position === null ? 0 : Math.round(position * 100));
	const label = $derived(
		`Currently ${formatAud(current)}. All-time low ${formatAud(low)}, all-time high ${formatAud(high)}.`
	);
</script>

{#if position === null}
	<p class="text-xs text-text-muted">
		Only one price recorded so far: <span class="num">{formatAud(current)}</span>
	</p>
{:else}
	<div class="max-w-md">
		<div class="flex justify-between text-[10px] uppercase tracking-wide text-text-muted">
			<span>All-time low</span>
			<span>All-time high</span>
		</div>
		<div role="img" aria-label={label} class="relative mt-1 h-1.5 rounded-full bg-surface-hover">
			<span
				class="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent"
				style="left: {pct}%"
			></span>
		</div>
		<div class="mt-1 flex justify-between text-xs">
			<span class="num text-text-muted">{formatAud(low)}</span>
			<span class="num font-medium text-text">{formatAud(current)}</span>
			<span class="num text-text-muted">{formatAud(high)}</span>
		</div>
	</div>
{/if}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS — 3 new PriceRangeBar tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/PriceRangeBar.svelte web/test/components.test.ts
git commit -m "feat(web): PriceRangeBar with accessible label and text fallback"
```

---

## Task 9: ProductHeadline component

**Files:**
- Create: `web/src/lib/components/ProductHeadline.svelte`
- Modify: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `Headline` from `$lib/productHeadline` (Task 4); `PriceRangeBar` (Task 8); `RETAILER_OPTIONS` from `$lib/filters`; `formatAud`, `formatPct` from `$lib/formats`.
- Produces: component with props `{ headline: Headline, listingCount: number, snapshotCount: number, span: string }`.

Spec §3: current cheapest price is the headline number; two deltas; provenance demoted to one muted line.

- [ ] **Step 1: Write the failing test**

Append to `web/test/components.test.ts`:

```ts
import ProductHeadline from '../src/lib/components/ProductHeadline.svelte';
import type { Headline } from '../src/lib/productHeadline';

function headline(overrides: Partial<Headline> = {}): Headline {
	return {
		currentPrice: 1299,
		currentRetailer: 'scorptec',
		allTimeLow: 1249,
		allTimeHigh: 1689,
		avg30: 1400,
		vsAvg30Pct: -7.2,
		vsAllTimeLowPct: 4.0,
		rangePosition: 0.11,
		...overrides
	};
}

describe('ProductHeadline', () => {
	const base = { listingCount: 6, snapshotCount: 47, span: '12 Mar – 23 Aug 2026' };

	it('leads with the current cheapest price and its retailer', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('$1,299');
		expect(html).toContain('Scorptec');
	});

	it('shows both deltas with arrows, not colour alone', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('▼');
		expect(html).toContain('vs 30d avg');
		expect(html).toContain('above all-time low');
	});

	it('demotes provenance to one muted line', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('6 listings');
		expect(html).toContain('47 snapshots');
		expect(html).toContain('12 Mar – 23 Aug 2026');
	});

	it('says there is no in-stock price rather than printing a bare dash', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ currentPrice: null, currentRetailer: null, rangePosition: null }),
			...base
		});
		expect(html).toContain('No in-stock listings');
	});

	it('omits the 30-day delta when history is too thin', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ avg30: null, vsAvg30Pct: null }),
			...base
		});
		expect(html).not.toContain('vs 30d avg');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: FAIL — cannot resolve `../src/lib/components/ProductHeadline.svelte`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/components/ProductHeadline.svelte`:

```svelte
<script lang="ts">
	import PriceRangeBar from './PriceRangeBar.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import type { Headline } from '$lib/productHeadline';

	let {
		headline,
		listingCount,
		snapshotCount,
		span
	}: {
		headline: Headline;
		listingCount: number;
		snapshotCount: number;
		span: string;
	} = $props();

	const retailerLabel = $derived(
		headline.currentRetailer
			? (RETAILER_OPTIONS.find((o) => o.value === headline.currentRetailer)?.label ??
				headline.currentRetailer)
			: null
	);
</script>

<div class="space-y-3">
	{#if headline.currentPrice !== null}
		<div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
			<span class="num text-3xl font-semibold text-text">{formatAud(headline.currentPrice)}</span>
			<span class="flex flex-wrap items-center gap-x-3 text-sm">
				{#if headline.vsAvg30Pct !== null}
					<span class={headline.vsAvg30Pct < 0 ? 'text-down' : 'text-up'}>
						{headline.vsAvg30Pct < 0 ? '▼' : '▲'}
						{formatPct(headline.vsAvg30Pct)} vs 30d avg
					</span>
				{/if}
				{#if headline.vsAllTimeLowPct !== null && headline.vsAllTimeLowPct > 0}
					<span class="text-text-muted">
						▲ {formatPct(headline.vsAllTimeLowPct)} above all-time low
					</span>
				{:else if headline.vsAllTimeLowPct !== null}
					<span class="text-down">At its all-time low</span>
				{/if}
			</span>
		</div>
		{#if retailerLabel}
			<p class="text-sm text-text-muted">at {retailerLabel}</p>
		{/if}
	{:else}
		<p class="text-sm text-text-muted">No in-stock listings right now.</p>
	{/if}

	{#if headline.allTimeLow !== null && headline.allTimeHigh !== null && headline.currentPrice !== null}
		<PriceRangeBar
			low={headline.allTimeLow}
			high={headline.allTimeHigh}
			current={headline.currentPrice}
			position={headline.rangePosition}
		/>
	{/if}

	<p class="text-xs text-text-muted">
		{listingCount}
		{listingCount === 1 ? 'listing' : 'listings'} · {snapshotCount} snapshots · {span}
	</p>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS — 5 new ProductHeadline tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/ProductHeadline.svelte web/test/components.test.ts
git commit -m "feat(web): ProductHeadline — price-led headline with range bar"
```

---

## Task 10: Wire into the product page and remove the accordion

**Files:**
- Modify: `web/src/routes/product/[id]/+page.svelte`
- Modify: `web/src/lib/listingsPanel.ts` (remove `buildBrandGroups`, `BrandGroup`)
- Modify: `web/test/listingsPanel.test.ts` (remove `buildBrandGroups` tests)
- Modify: `web/test/components.test.ts` (remove the `BrandGroupedListings` import and tests)
- Delete: `web/src/lib/components/BrandGroupedListings.svelte`

**Interfaces:**
- Consumes: `OfferList` (Task 7), `ProductHeadline` (Task 9), `buildHeadline` (Task 4), `toListingDisplays` from `$lib/listingsPanel`.
- Produces: nothing downstream — this is the integration task.

- [ ] **Step 1: Replace the headline and listings panel in the product page**

In `web/src/routes/product/[id]/+page.svelte`:

Replace the `BrandGroupedListings` import with the new components, and drop the now-unused `Chip` import:

```ts
import ProductHeadline from '$lib/components/ProductHeadline.svelte';
import OfferList from '$lib/components/OfferList.svelte';
import { buildHeadline } from '$lib/productHeadline';
import { toListingDisplays } from '$lib/listingsPanel';
```

Add the derived headline alongside the existing `$derived` block, replacing the `allTimeLow` / `allTimeHigh` / `avg30` chip derivations:

```ts
const offers = $derived(toListingDisplays(series, product.brand, selected));
const headline = $derived(buildHeadline(offers, data.band, data.stats));
```

Replace the flat `<Chip …>` row (`Category`, `Generation`, `All-time low`, `All-time high`, `30d avg`, `Listings`, `History span`, `Snapshots`) with:

```svelte
<p class="mt-1 text-sm text-text-muted">
	{product.category?.toUpperCase()}
	{#if product.generation_tier}
		· {generationTierLabel(product.brand, product.category, product.generation_tier) ??
			product.generation_tier}
	{/if}
</p>

<div class="mt-4">
	<ProductHeadline
		{headline}
		listingCount={series.length}
		snapshotCount={totalPoints}
		{span}
	/>
</div>
```

Replace the `<BrandGroupedListings …>` element with:

```svelte
<OfferList
	series={data.series}
	productBrand={product.brand}
	avg30={headline.avg30}
	{selected}
	onToggleListing={toggleListing}
/>
```

- [ ] **Step 2: Delete the accordion component and its logic**

```bash
rm web/src/lib/components/BrandGroupedListings.svelte
```

In `web/src/lib/listingsPanel.ts`, delete the `BrandGroup` interface and the entire `buildBrandGroups` function. Keep `ListingDisplay`, `PanelFilters`, `toListingDisplays` and `priceRange` — `offers.ts` and `OfferList` depend on them.

In `web/test/listingsPanel.test.ts`, remove `buildBrandGroups` from the import and delete its `describe` block. Keep the `toListingDisplays` and `priceRange` tests.

In `web/test/components.test.ts`, remove the `BrandGroupedListings` import and its `describe` block.

- [ ] **Step 3: Run type check and unit tests**

Run: `cd web && npm run check && npm test`
Expected: `npm run check` reports **0 errors**; all Vitest tests pass. Any remaining reference to `buildBrandGroups` or `BrandGroupedListings` surfaces here as a type error.

- [ ] **Step 4: Verify the page in the running app**

Run: `cd web && npm run dev`, open a product page with several listings, and confirm:
- the cheapest in-stock price is the largest element;
- the offer list shows at most 8 rows with a "Show all N offers" button;
- "In stock only" is checked by default and states "N of M";
- retailer and brand are visible on every row and `View →` opens the retailer.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/product/\[id\]/+page.svelte web/src/lib/listingsPanel.ts web/test/listingsPanel.test.ts web/test/components.test.ts
git rm web/src/lib/components/BrandGroupedListings.svelte
git commit -m "refactor(web): flat offer list and price-led headline replace brand accordion"
```

---

## Task 11: E2E coverage and full validation

**Files:**
- Modify: `web/e2e/app.spec.ts`

**Interfaces:**
- Consumes: everything above. No new exports.

Per `CLAUDE.md`: every navigation must go through the local `goto()` helper (which waits for `networkidle`, i.e. hydration), never `page.goto()` directly. The chips and expander are client-side, so a click landing before hydration would silently do nothing.

- [ ] **Step 1: Write the failing E2E test**

Add to `web/e2e/app.spec.ts`, following the file's existing product-page test structure and its seeded product id:

```ts
test('product page leads with the cheapest price and caps the offer list', async ({ page }) => {
	await goto(page, '/product/1');

	// In-stock-only is the default and states what it hides.
	await expect(page.getByText(/In stock only \(\d+ of \d+\)/)).toBeVisible();

	// Every offer row shows its retailer and links out.
	const firstOffer = page.locator('a', { hasText: 'View →' }).first();
	await expect(firstOffer).toHaveAttribute('rel', 'noopener noreferrer');
	await expect(firstOffer).toHaveAttribute('target', '_blank');
});

test('offer list expander reveals the full list', async ({ page }) => {
	await goto(page, '/product/1');
	const expander = page.getByRole('button', { name: /Show all \d+ offers/ });
	if (await expander.count()) {
		const before = await page.locator('a', { hasText: 'View →' }).count();
		await expander.click();
		expect(await page.locator('a', { hasText: 'View →' }).count()).toBeGreaterThan(before);
	}
});
```

- [ ] **Step 2: Run the E2E suite to verify the new tests fail or pass meaningfully**

Run: `cd web && npm run test:e2e`
Expected: the new tests run against the seeded DB. If `/product/1` has fewer than 9 seeded offers the expander branch is skipped — if so, extend `web/e2e/seed.mjs` to give one product at least 10 listings, then re-run.

- [ ] **Step 3: Run the full validation suite**

From the repo root:

```bash
python -m pytest -q
```

Then from `web/`:

```bash
npm run check
npm test
npm run test:e2e
npm run build
```

Expected: pytest passes (611 tests); `npm run check` reports 0 errors; Vitest passes; Playwright passes in under ~60s; the production build succeeds.

- [ ] **Step 4: Update STATUS.md**

Per `CLAUDE.md`, add one dated bullet under **Recent changes**. Do not start a nested "Prior update" chain.

```markdown
- **2026-08-23** — Product page rebuilt around a flat, cheapest-first offer list
  (`OfferList`) replacing the brand→retailer accordion, plus a price-led
  headline with an all-time range bar. In-stock-only is the default and the
  list caps at 8 offers with a "Show all N" expander. Implements stage 1 of
  `docs/superpowers/specs/2026-08-23-price-first-ia-design.md`.
```

- [ ] **Step 5: Commit**

```bash
git add web/e2e/app.spec.ts STATUS.md
git commit -m "test(web): e2e coverage for the flat offer list; update STATUS"
```

---

## Self-Review

**Spec coverage (Stage 1 = §1, §2, §3):**

| Spec requirement | Task |
|---|---|
| §1 offer row: price leads, brand + retailer visible, `View →` links out | 5 |
| §1 ordering: in-stock / out-of-stock / delisted never interleave | 1 |
| §1 delta suppressed below `MIN_HISTORY_POINTS` | 4, 5 |
| §1 responsive two-line row below `sm` | 5 (`basis-full sm:basis-auto`) |
| §2 facet chips with counts, client-side | 2, 6, 7 |
| §2 chip row hides itself at one value | 6 |
| §2 chips are `<button aria-pressed>` | 6 |
| §2 volume: in-stock default ON, states what it hides | 3, 7 |
| §2 volume: auto-disable when nothing in stock | 3, 7 |
| §2 volume: 8-row cap, expander states true total, no expander below 9 | 3, 7 |
| §2 volume: filter applies before cap | 3 |
| §2 `buildBrandGroups` removed, `toListingDisplays`/`priceRange` kept | 10 |
| §2 chart toggle preserved | 5, 7, 10 |
| §3 current cheapest price is the headline | 4, 9 |
| §3 two deltas | 4, 9 |
| §3 range bar with `role="img"` + `aria-label` | 8 |
| §3 range bar degrades when high === low | 4, 8 |
| §3 provenance demoted to one muted line | 9 |
| §9 pure-logic Vitest tests | 1–4 |
| §9 E2E + full validation | 11 |

No gaps.

**Placeholder scan:** none — every code step contains runnable code, and every test step contains real assertions.

**Type consistency check:** `ListingDisplay` is defined once in `listingsPanel.ts` and re-exported from `offers.ts`; `OfferView.matched` (filtered count) and `OfferView.total` (unfiltered count) are used consistently in Tasks 3 and 7; `Headline` field names in Task 4 match every usage in Task 9; `FacetOption` in Task 2 matches the `FacetChips` prop type in Task 6.
