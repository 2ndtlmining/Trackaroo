# Product Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/products` card grid with a search-first index — one search box, one dense row per product, filtered in the browser.

**Architecture:** Two new pure modules (`productSearch.ts` for match+rank, `productIndex.ts` for grouping+order) and one new row component. **No new database query**: `groupListingsByProduct` already returns every field the row needs, so the server load gets *smaller* — the sparkline and facet-count queries are deleted. `CommandPalette` adopts the shared matcher so the two search surfaces cannot rank differently.

**Tech Stack:** SvelteKit 2 (Svelte 5 runes), TypeScript, Tailwind v4, Vitest, Playwright.

**Spec:** [`docs/superpowers/specs/2026-08-25-product-index-design.md`](../specs/2026-08-25-product-index-design.md)

> **Correction to the spec:** §6 says the index "gets its own query". It does not need one — `ProductGroup` already carries `productId`, `brand`, `model`, `generationTier`, `cheapestInStockPrice`, `cheapestInStockRetailer`, `inStockCount`, `avg30` and `avg30Points`, including for products with nothing in stock. This plan reuses the existing load and removes work from it.

## Global Constraints

- Tokens only; no new hex. Direction never colour-only. `.num` for figures. One accent. Reduced motion respected. `aria-live` on the result count.
- No runtime imports from `$lib/server/…` in client components; `import type` is fine.
- The average label uses `avgWindowLabel()` — never a hardcoded "30d".
- E2E asserts seeded fixtures only, never scraped-live values; navigation via the local `goto()` helper.
- Docker build-and-boot before claiming done (`CLAUDE.md`).

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/productSearch.ts` (create) | Pure match + rank over a product list. |
| `web/src/lib/productIndex.ts` (create) | Pure grouping by (brand, generation) and group ordering. |
| `web/src/lib/components/ProductRow.svelte` (create) | One dense row. |
| `web/src/lib/components/CommandPalette.svelte` (modify) | Use the shared matcher. |
| `web/src/routes/products/+page.server.ts` (modify) | Drop sparkline + facet queries; keep groups. |
| `web/src/routes/products/+page.svelte` (rewrite) | Search box, groups, rows, compare bar. |
| `web/src/lib/components/ProductCard.svelte` (delete) | Superseded by the row. |
| `web/src/lib/components/Filters.svelte` (delete) | No consumer left. |
| `web/src/lib/tiers.ts` (modify) | Add `intel-gpu` labels. |
| `db/watchlist.csv` (modify) | Retag Arc Alchemist as `current-1`. |
| Tests | `productSearch.test.ts`, `productIndex.test.ts` (create); `components.test.ts`, `filters.test.ts`, `app.spec.ts` (modify); `filtersComponent.test.ts` (delete) |

---

### Task 1: `productSearch.ts` — match and rank

**Files:** Create `web/src/lib/productSearch.ts`, `web/test/productSearch.test.ts`

**Interfaces:**
```ts
export interface Searchable { model: string; brand: string; productVariant?: string | null }
export function matchScore(item: Searchable, terms: string[]): number | null
export function searchProducts<T extends Searchable>(items: T[], query: string): T[]
```
`matchScore` returns a rank (lower = better) or `null` for no match.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest';
import { searchProducts } from '../src/lib/productSearch';

const items = [
	{ model: 'GeForce RTX 5070', brand: 'NVIDIA', productVariant: null },
	{ model: 'GeForce RTX 5070 Ti', brand: 'NVIDIA', productVariant: null },
	{ model: 'GeForce RTX 4070', brand: 'NVIDIA', productVariant: null },
	{ model: 'Radeon RX 9070 XT', brand: 'AMD', productVariant: null },
	{ model: 'Ryzen 5 5600', brand: 'AMD', productVariant: null }
];

describe('searchProducts', () => {
	it('returns everything for an empty query', () => {
		expect(searchProducts(items, '   ')).toHaveLength(5);
	});

	it('matches a substring of the model', () => {
		expect(searchProducts(items, '5070').map((i) => i.model)).toEqual([
			'GeForce RTX 5070',
			'GeForce RTX 5070 Ti',
			'Radeon RX 9070 XT'
		]);
	});

	it('ranks an exact model match first', () => {
		const r = searchProducts(items, 'geforce rtx 5070');
		expect(r[0].model).toBe('GeForce RTX 5070');
	});

	it('ranks a prefix match above a mid-string match', () => {
		const r = searchProducts(items, 'rx 9070');
		expect(r[0].model).toBe('Radeon RX 9070 XT');
	});

	it('requires every term, in any order', () => {
		expect(searchProducts(items, '5070 ti').map((i) => i.model)).toEqual(['GeForce RTX 5070 Ti']);
		expect(searchProducts(items, 'ti 5070').map((i) => i.model)).toEqual(['GeForce RTX 5070 Ti']);
	});

	it('matches on brand', () => {
		expect(searchProducts(items, 'amd')).toHaveLength(2);
	});

	it('is case and whitespace insensitive', () => {
		expect(searchProducts(items, '  RyZeN   5600 ').map((i) => i.model)).toEqual(['Ryzen 5 5600']);
	});

	it('returns nothing when a term matches nothing', () => {
		expect(searchProducts(items, '5070 banana')).toEqual([]);
	});

	it('breaks ties on model name for stable ordering', () => {
		const a = searchProducts(items, 'geforce');
		const b = searchProducts([...items].reverse(), 'geforce');
		expect(a.map((i) => i.model)).toEqual(b.map((i) => i.model));
	});
});
```

- [ ] **Step 2: Run it — expect FAIL** (`npx vitest run test/productSearch.test.ts`)

- [ ] **Step 3: Implement**

```ts
// Shared product matching for the /products index and the Ctrl+K palette.
// Two search surfaces over the same catalogue must not rank differently, so
// both call this. Pure, so the ranking rules are pinned by tests rather than
// by whichever component happens to render first.
export interface Searchable {
	model: string;
	brand: string;
	productVariant?: string | null;
}

// Lower is better. Bands are spaced so a model-side match always beats a
// brand-side one regardless of position within the string.
const EXACT = 0;
const PREFIX = 1;
const WORD_BOUNDARY = 2;
const SUBSTRING = 3;
const OTHER_FIELD = 4;

function normalise(value: string): string {
	return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

export function terms(query: string): string[] {
	return normalise(query).split(' ').filter(Boolean);
}

export function matchScore(item: Searchable, queryTerms: string[]): number | null {
	if (queryTerms.length === 0) return SUBSTRING;
	const model = normalise(item.model);
	const other = normalise(`${item.brand} ${item.productVariant ?? ''}`);
	const joined = queryTerms.join(' ');

	// Every term must appear somewhere, so "5070 ti" and "ti 5070" agree.
	for (const term of queryTerms) {
		if (!model.includes(term) && !other.includes(term)) return null;
	}

	if (model === joined) return EXACT;
	if (model.startsWith(joined)) return PREFIX;
	if (model.includes(` ${joined}`)) return WORD_BOUNDARY;
	if (model.includes(joined)) return SUBSTRING;
	if (queryTerms.every((t) => model.includes(t))) return SUBSTRING;
	return OTHER_FIELD;
}

export function searchProducts<T extends Searchable>(items: T[], query: string): T[] {
	const queryTerms = terms(query);
	if (queryTerms.length === 0) return [...items];
	return items
		.map((item) => ({ item, score: matchScore(item, queryTerms) }))
		.filter((r): r is { item: T; score: number } => r.score !== null)
		.sort((a, b) => a.score - b.score || a.item.model.localeCompare(b.item.model))
		.map((r) => r.item);
}
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Adopt in `CommandPalette.svelte`**

Replace the inline `items.filter(...)` block with `searchProducts(items, query)`, keeping the existing `.slice(0, 8)` cap. Import from `$lib/productSearch`.

- [ ] **Step 6: `npx vitest run` — all green. Commit.**

```bash
git add web/src/lib/productSearch.ts web/test/productSearch.test.ts web/src/lib/components/CommandPalette.svelte
git commit -m "feat(index): shared ranked product matcher, adopted by the palette"
```

---

### Task 2: `productIndex.ts` — grouping and order

**Files:** Create `web/src/lib/productIndex.ts`, `web/test/productIndex.test.ts`

**Interfaces:**
```ts
export interface IndexGroup<T> { key: string; brand: string; label: string; items: T[] }
export function groupForIndex<T extends { brand: string; generationTier: GenerationTier | null; model: string; category: Category }>(items: T[]): IndexGroup<T>[]
```

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest';
import { groupForIndex } from '../src/lib/productIndex';

const p = (brand: string, model: string, tier: string | null) =>
	({ brand, model, generationTier: tier, category: 'gpu' }) as never;

describe('groupForIndex', () => {
	const items = [
		p('NVIDIA', 'GeForce RTX 4070', 'current-1'),
		p('AMD', 'Radeon RX 9070', 'current'),
		p('NVIDIA', 'GeForce RTX 5070', 'current'),
		p('NVIDIA', 'GeForce RTX 5060', 'current'),
		p('AMD', 'Radeon RX 7600', 'current-1')
	];

	it('orders brands by how many products they have, biggest first', () => {
		expect(groupForIndex(items).map((g) => g.brand)).toEqual(['NVIDIA', 'NVIDIA', 'AMD', 'AMD']);
	});

	it('puts the newest generation first within a brand', () => {
		const nvidia = groupForIndex(items).filter((g) => g.brand === 'NVIDIA');
		expect(nvidia[0].label).toContain('RTX 50');
		expect(nvidia[1].label).toContain('RTX 40');
	});

	it('labels groups from the shared generation labels', () => {
		expect(groupForIndex(items)[0].label).toBe('RTX 50 (Blackwell)');
	});

	it('sorts models within a group', () => {
		const first = groupForIndex(items)[0];
		expect(first.items.map((i) => i.model)).toEqual(['GeForce RTX 5060', 'GeForce RTX 5070']);
	});

	it('keeps an untagged product visible under a fallback heading', () => {
		const g = groupForIndex([p('Intel', 'Arc B580', null)]);
		expect(g).toHaveLength(1);
		expect(g[0].items).toHaveLength(1);
		expect(g[0].label).toBeTruthy();
	});
});
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```ts
// Grouping for the /products index. Pure so the ordering rule is pinned by
// tests rather than by how the page happens to render.
import { generationTierLabel, GENERIC_TIER_LABELS } from './tiers';
import type { Category, GenerationTier } from './types';

export interface IndexGroup<T> {
	key: string;
	brand: string;
	label: string;
	items: T[];
}

interface Groupable {
	brand: string;
	model: string;
	category: Category;
	generationTier: GenerationTier | null;
}

// Newest first. Anything untagged sorts last rather than vanishing.
const TIER_ORDER: Record<string, number> = { current: 0, 'current-1': 1, 'current-2': 2 };

export function groupForIndex<T extends Groupable>(items: T[]): IndexGroup<T>[] {
	const byKey = new Map<string, IndexGroup<T>>();
	const brandCount = new Map<string, number>();

	for (const item of items) {
		brandCount.set(item.brand, (brandCount.get(item.brand) ?? 0) + 1);
		const key = `${item.brand}::${item.generationTier ?? 'unknown'}`;
		let group = byKey.get(key);
		if (!group) {
			const label =
				generationTierLabel(item.brand, item.category, item.generationTier) ??
				GENERIC_TIER_LABELS.current;
			group = { key, brand: item.brand, label, items: [] };
			byKey.set(key, group);
		}
		group.items.push(item);
	}

	for (const group of byKey.values()) {
		group.items.sort((a, b) => a.model.localeCompare(b.model));
	}

	// Brand-major: buying is brand-anchored, so a brand's generations stay
	// adjacent. Biggest catalogue leads so a new brand lands predictably.
	return [...byKey.values()].sort((a, b) => {
		const byBrand = (brandCount.get(b.brand) ?? 0) - (brandCount.get(a.brand) ?? 0);
		if (byBrand !== 0) return byBrand;
		if (a.brand !== b.brand) return a.brand.localeCompare(b.brand);
		const tierA = TIER_ORDER[a.key.split('::')[1]] ?? 99;
		const tierB = TIER_ORDER[b.key.split('::')[1]] ?? 99;
		return tierA - tierB;
	});
}
```

> `GENERIC_TIER_LABELS` is already exported from `tiers.ts`; `generationTierLabel` returns `null` only for a null tier.

- [ ] **Step 4: Run — expect PASS. Commit.**

```bash
git add web/src/lib/productIndex.ts web/test/productIndex.test.ts
git commit -m "feat(index): brand-major, newest-first product grouping"
```

---

### Task 3: `ProductRow.svelte`

**Files:** Create `web/src/lib/components/ProductRow.svelte`; modify `web/test/components.test.ts`

**Props:** `{ group, compareSelected, compareDisabled, onToggleCompare }` — `group` is `ProductGroup & { avg30?: number | null; avg30Points?: number }`.

- [ ] **Step 1: Write the failing test**

```ts
describe('ProductRow', () => {
	const base = {
		productId: 7, category: 'gpu', brand: 'NVIDIA', model: 'GeForce RTX 5070 Ti',
		productVariant: null, generationTier: 'current', listings: [],
		cheapestInStockPrice: 1599, cheapestInStockRetailer: 'pccg', inStockCount: 3,
		avg30: 1650, avg30Points: 17
	} as never;

	it('shows model, price, retailer and a link to the product', () => {
		const html = renderComponent(ProductRow, { group: base });
		expect(html).toContain('GeForce RTX 5070 Ti');
		expect(html).toContain('$1,599');
		expect(html).toContain('PCCG');
		expect(html).toContain('href="/product/7"');
	});

	it('states the average window honestly', () => {
		const html = renderComponent(ProductRow, { group: base });
		expect(html).toContain('17-day avg');
		expect(html).not.toContain('30d avg');
	});

	it('renders a dash and no delta when nothing is in stock', () => {
		const html = renderComponent(ProductRow, {
			group: { ...base, cheapestInStockPrice: null, cheapestInStockRetailer: null, inStockCount: 0 }
		});
		expect(html).toContain('—');
		expect(html).toContain('No stock');
	});

	it('reflects compare selection', () => {
		const html = renderComponent(ProductRow, { group: base, compareSelected: true });
		expect(html).toContain('checked');
	});
});
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```svelte
<script lang="ts">
	import BrandIcon from './BrandIcon.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30 } from '$lib/offers';
	import type { ProductGroup } from '$lib/server/repos';

	let {
		group,
		compareSelected = false,
		compareDisabled = false,
		onToggleCompare
	}: {
		group: ProductGroup & { avg30?: number | null; avg30Points?: number };
		compareSelected?: boolean;
		compareDisabled?: boolean;
		onToggleCompare?: (productId: number) => void;
	} = $props();

	const retailerLabel = $derived(
		group.cheapestInStockRetailer
			? (RETAILER_OPTIONS.find((o) => o.value === group.cheapestInStockRetailer)?.label ??
				group.cheapestInStockRetailer)
			: null
	);
	const deltaPct = $derived(deltaVsAvg30(group.cheapestInStockPrice, group.avg30 ?? null));
</script>

<div class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-surface-hover">
	{#if onToggleCompare}
		<input
			type="checkbox"
			class="accent-accent"
			checked={compareSelected}
			disabled={compareDisabled}
			aria-label={`Compare ${group.model}`}
			onchange={() => onToggleCompare?.(group.productId)}
		/>
	{/if}

	<div class="order-2 w-24 shrink-0">
		{#if group.cheapestInStockPrice !== null}
			<span class="num text-sm font-semibold text-text">{formatAud(group.cheapestInStockPrice)}</span>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</div>

	<a
		href={`/product/${group.productId}`}
		class="order-3 min-w-0 flex-1 truncate text-sm text-text no-underline hover:underline"
		title={group.model}
	>
		{group.model}
	</a>

	<span class="order-4 hidden shrink-0 items-center gap-1.5 text-xs text-text-muted sm:flex">
		<BrandIcon brand={group.brand} size={12} />
		{group.brand}
	</span>

	<div class="order-5 w-32 shrink-0 text-xs">
		{#if deltaPct !== null}
			{@const d = deltaPresentation(deltaPct)}
			<span class={d.class}>{d.arrow} {formatPct(deltaPct)} {avgWindowLabel(group.avg30Points)}</span>
		{:else if group.cheapestInStockPrice === null}
			<span class="text-text-muted">No stock</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</div>

	<span class="order-6 w-20 shrink-0 text-right text-xs text-text-muted">{retailerLabel ?? ''}</span>
</div>
```

- [ ] **Step 4: Run — expect PASS. Commit.**

---

### Task 4: Rewrite `/products`

**Files:** Modify `+page.server.ts`, rewrite `+page.svelte`; delete `ProductCard.svelte`, `Filters.svelte`, `web/test/filtersComponent.test.ts`

- [ ] **Step 1: Slim the server load**

Remove `getSparklines`, `getProductSparklines` and the retailer facet work. Keep `getLatestListings` (unfiltered except category + in-stock), `groupListingsByProduct`, `getProductDealStats`. Return `{ groups, category }` where each group carries `avg30`, `avg30Points`, `deal`. Category comes from `parseFilters`; default `gpu` when absent so the page always has a subject.

- [ ] **Step 2: Rewrite the page**

Search box (autofocused, labelled), in-stock checkbox, `aria-live` count, groups from `groupForIndex`, flat ranked list when a query is present, compare bar preserved. `/` focuses search unless focus is already in an input; `Escape` clears; `Enter` opens the top hit.

- [ ] **Step 3: Delete the superseded components and their tests**

```bash
cd web && rm src/lib/components/ProductCard.svelte src/lib/components/Filters.svelte test/filtersComponent.test.ts
```

Remove the `ProductCard` and `Filters` imports and `describe` blocks from `components.test.ts`. **When deleting a `describe` block, cut to the start of the next top-level `describe`, and check no shared helper lived between them** — that mistake removed the `sparkline()` helper during stage 3.

- [ ] **Step 4: `npm run check` (0 errors) and `npx vitest run`. Commit.**

---

### Task 5: Fix the Intel Arc generations

**Files:** `db/watchlist.csv`, `web/src/lib/tiers.ts`, `web/test/components.test.ts`

- [ ] **Step 1:** In `db/watchlist.csv`, change `gen_tier` from `current` to `current-1` for `Arc A380`, `Arc A750`, `Arc A770` (Alchemist). B570/B580 (Battlemage) stay `current`.

- [ ] **Step 2:** In `tiers.ts` add:

```ts
	'intel-gpu': {
		current: 'Arc B (Battlemage)',
		'current-1': 'Arc A (Alchemist)',
		'current-2': 'Arc (earlier)'
	},
```

- [ ] **Step 3:** Add a vitest asserting `generationTierLabel('Intel', 'gpu', 'current')` is `'Arc B (Battlemage)'` and that no `(brand, category)` in the watchlist falls back to a generic label unexpectedly.

- [ ] **Step 4:** Re-seed so the DB picks up the retag: `python seed.py`. Confirm with a query that the three A-series products are `current-1`.

- [ ] **Step 5:** `python -m pytest -q`; commit.

---

### Task 6: E2E, docs, full validation

- [ ] **Step 1: Update `app.spec.ts`** — replace the `products page` and `products page filters` blocks (they assert `article` cards and the removed selects/chips) with:

```ts
test.describe('product index', () => {
	test('groups the catalogue by brand and generation when the box is empty', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
		expect(await page.getByRole('link', { name: /GeForce|Radeon|Arc/ }).count()).toBeGreaterThan(3);
	});

	test('typing narrows the list and reports the count', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByLabel(/Search/).fill('5060');
		await expect(page.getByTestId('index-count')).toContainText('match');
		expect(await page.getByRole('link', { name: /GeForce RTX 5060/ }).count()).toBeGreaterThan(0);
	});

	test('Enter opens the top hit', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByLabel(/Search/).fill('5060 ti');
		await page.getByLabel(/Search/).press('Enter');
		await expect(page).toHaveURL(/\/product\/\d+/);
	});

	test('clearing the box restores the groups', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const box = page.getByLabel(/Search/);
		await box.fill('5060');
		await box.press('Escape');
		await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
	});

	test('compare still reaches /compare from the index', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		await boxes.nth(1).check();
		await page.getByRole('link', { name: /Compare/ }).click();
		await expect(page).toHaveURL(/\/compare\?ids=\d+,\d+/);
	});
});
```

Keep the existing "empty state" test but point it at a query with no matches.

- [ ] **Step 2: Full validation** — `pytest`, `npm run check`, `npm test`, `npm run test:e2e`, `npm run build`.

- [ ] **Step 3: Docker build-and-boot**, per `CLAUDE.md`; confirm `/products?category=gpu` returns 200 and renders groups.

- [ ] **Step 4: Docs** — dated `STATUS.md` bullet (no nested chain), regression table, Routes line; `docs/ARCHITECTURE.md` Part 3 entry covering the find-not-browse framing, why filtering moved client-side here while `/deals` stayed server-side, brand-major ordering, and the Arc retag.

- [ ] **Step 5: Commit.**

---

## Self-Review

**Spec coverage:** §1 page → Task 4. §2 matching/ranking → Task 1. §3 grouping/order → Task 2. §4 row → Task 3. §5 removals → Task 4 Step 3. §6 data → Task 4 Step 1 (simplified; correction noted at the top). §7 Arc → Task 5. §8 conventions → Global Constraints + Task 3/4. §9 testing → Tasks 1–3, 6. §10 out of scope → nothing here touches `/deals`, the homepage, `/movers` or the product page.

**Placeholder scan:** none. Tasks 4 and 6 describe edits to existing files by exact symbol and block, which is correct for modifications.

**Type consistency:** `Searchable` (Task 1) is satisfied by both `ProductIndexEntry` (palette) and `ProductGroup` (index) — both have `model`, `brand`, `productVariant`. `Groupable` (Task 2) matches `ProductGroup`'s `brand`/`model`/`category`/`generationTier`. `ProductRow`'s `group` prop is the same augmented `ProductGroup` the load returns and that `ProductCard` used, so the compare handler signature is unchanged.
