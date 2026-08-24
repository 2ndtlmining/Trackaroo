# Navigation & Six-Retailer Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put `Deals` first in the nav, make category a place rather than a
repeated filter, end `/compare`'s orphan status, move the dataset stats out of
the header into the health strip, and make the display layer ready for six
retailers before any new scraper exists.

**Architecture:** The retailer `<select>` on `/products` becomes a URL-driven
chip row reusing the same `FacetChips` component the product page and `/deals`
already use — one presentational component, now three drivers. Nav active-state
matching becomes a pure, tested function because it must match on the query
string, not just the pathname. The retailer registry grows to six entries in
one place each side (TypeScript and Python).

**Tech Stack:** SvelteKit 2 (Svelte 5 runes), TypeScript, Tailwind v4, Vitest,
Playwright, Python.

**Spec:** [`docs/superpowers/specs/2026-08-23-price-first-ia-design.md`](../specs/2026-08-23-price-first-ia-design.md) — this plan implements **stage 4** (§6, §7), the last stage per §10.

## Global Constraints

- **Tokens only**; no new hex values. **Direction never colour-only.** **Numbers monospaced** via `.num`. **One accent.** **Reduced motion respected.**
- **Client/server boundary** — no runtime imports from `$lib/server/...` in client components.
- **The four scrapers are out of scope.** This stage is display-side only. Adding a retailer slug here must not imply data exists for it.
- **`/products` and `/deals` chips are URL-driven and filter server-side**; the product-page chips filter an already-loaded list client-side. They share presentation and nothing else — do not collapse the distinction (§7).
- **Below `md` the nav is a horizontally scrollable row, not a hamburger** (§6): five short items fit and a menu would add a tap to every navigation.
- **`/compare?ids=1` must keep returning 400** — an existing e2e test pins it. Only the *no-`ids`* case becomes an empty state.
- **E2E determinism**; navigation via the local `goto()` helper.

### Decision: chip options come from the data, not the registry

`RETAILER_OPTIONS` grows to six so `parseFilters` accepts the new slugs and
labels resolve. But the `/products` chip row is built from **counts over the
current result set**, exactly as `/deals` does. A retailer with no rows
therefore shows no chip, so extending the registry never renders a dead chip
that returns an empty page when clicked.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/types.ts` (modify) | `Retailer` gains the four new slugs. |
| `web/src/lib/filters.ts` (modify) | `RETAILER_OPTIONS` gains the four entries. |
| `notify_discord.py` (modify) | `RETAILER_LABELS` gains the four entries. |
| `web/src/lib/nav.ts` (create) | The nav link list + pure active-state matching on pathname *and* query string. |
| `web/src/lib/components/Header.svelte` (modify) | New links, active state via `nav.ts`, scrollable row below `md`, dataset stats removed. |
| `web/src/lib/components/HealthStrip.svelte` (modify) | Gains the DB size — the stats' honest home. |
| `web/src/lib/components/Filters.svelte` (modify) | Retailer `<select>` → `FacetChips` row. |
| `web/src/routes/products/+page.server.ts` (modify) | Compute retailer facet counts; filter by retailer in JS. |
| `web/src/routes/+page.server.ts` (modify) | Pass `dbSizeBytes` to the strip. |
| `web/src/routes/compare/+page.server.ts` / `+page.svelte` (modify) | No-`ids` empty state. |
| `web/test/nav.test.ts` (create) | Active-state matching. |
| `web/test/filters.test.ts`, `web/test/components.test.ts` (modify) | Registry + chip row + header. |
| `unit_testing/test_notify_discord.py` (modify) | Retailer label coverage. |
| `web/e2e/app.spec.ts` (modify) | Nav, chips, compare empty state. |
| `STATUS.md`, `docs/ARCHITECTURE.md` (modify) | Documentation, final task. |

---

### Task 1: Retailer chip row on `/products`

**Files:**
- Modify: `web/src/routes/products/+page.server.ts`, `web/src/lib/components/Filters.svelte`
- Test: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `FacetChips` (unchanged), `facetCounts` from `$lib/offers` (already generic over `{retailer, brand}`).
- Produces: `Filters` gains `retailerFacets: FacetOption[]` and `retailerTotal: number` props.

- [ ] **Step 1: Compute the counts server-side**

In `web/src/routes/products/+page.server.ts`, fetch listings **without** the
retailer filter, count by retailer, then apply the retailer filter in JS. One
query, and the counts are guaranteed to match what a click produces.

Replace the first three statements of `load` with:

```ts
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	// Counted over the set filtered by every axis EXCEPT retailer, so a chip's
	// count always equals the number of rows clicking it produces.
	const forCounts = getLatestListings(db, { ...filters, retailer: undefined });
	const retailerFacets = facetCounts(forCounts, 'retailer');
	const listings = filters.retailer
		? forCounts.filter((l) => l.retailer === filters.retailer)
		: forCounts;
```

Add `import { facetCounts } from '$lib/offers';` at the top, and add to the
returned object:

```ts
		retailerFacets,
		retailerTotal: forCounts.length,
```

- [ ] **Step 2: Write the failing component test**

Add to `web/test/components.test.ts`:

```ts
describe('Filters retailer chips', () => {
	const facets = [
		{ value: 'scorptec', label: 'Scorptec', count: 12 },
		{ value: 'pccg', label: 'PCCG', count: 7 }
	];

	it('renders a retailer chip per option with its count', () => {
		const html = renderComponent(Filters, {
			brands: ['AMD'],
			retailerFacets: facets,
			retailerTotal: 19
		});
		expect(html).toContain('Scorptec');
		expect(html).toContain('12');
		expect(html).toContain('PCCG');
		expect(html).toContain('7');
	});

	it('no longer renders a retailer select', () => {
		const html = renderComponent(Filters, {
			brands: ['AMD'],
			retailerFacets: facets,
			retailerTotal: 19
		});
		expect(html).not.toContain('aria-label="Filter by retailer"');
	});

	it('keeps the other selects', () => {
		const html = renderComponent(Filters, {
			brands: ['AMD'],
			retailerFacets: facets,
			retailerTotal: 19
		});
		expect(html).toContain('aria-label="Filter by category"');
		expect(html).toContain('aria-label="Filter by brand"');
	});
});
```

Import `Filters` at the top of the test file if it is not already imported.

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts -t "Filters retailer chips"`
Expected: FAIL.

- [ ] **Step 4: Replace the select with the chip row**

In `web/src/lib/components/Filters.svelte`:

Add to the imports:
```ts
	import FacetChips from './FacetChips.svelte';
	import type { FacetOption } from '$lib/offers';
```
Remove `RETAILER_OPTIONS` from the `$lib/filters` import list.

Change the props:
```ts
	let {
		brands = [],
		retailerFacets = [],
		retailerTotal = 0
	}: { brands?: string[]; retailerFacets?: FacetOption[]; retailerTotal?: number } = $props();
```

Delete the whole retailer `<select>` block (the one with
`aria-label="Filter by retailer"`).

Wrap the existing control row and add the chip row beneath it. Replace the
outer `<div class="flex flex-wrap items-center gap-2">` opening tag with:

```svelte
<div class="flex flex-col gap-2">
	<div class="flex flex-wrap items-center gap-2">
```

and close it by adding one extra `</div>` at the very end of the file, after
inserting the chip row just before that close:

```svelte
	</div>

	<!--
		URL-driven, server-side — the same presentational component the product
		page drives client-side (spec §7). Options come from counts over the
		current result set, so a retailer with no rows shows no chip.
	-->
	<FacetChips
		label="Retailer"
		options={retailerFacets}
		selected={filters.retailer ?? null}
		allCount={retailerTotal}
		onSelect={(v) => set('retailer', v ?? '')}
	/>
</div>
```

- [ ] **Step 5: Pass the props through**

In `web/src/routes/products/+page.svelte`, change the `<Filters …>` usage to:

```svelte
<Filters
	brands={data.brands}
	retailerFacets={data.retailerFacets}
	retailerTotal={data.retailerTotal}
/>
```

- [ ] **Step 6: Verify**

Run: `cd web && npm run check` (0 errors) then `npx vitest run`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/components/Filters.svelte web/src/routes/products web/test/components.test.ts
git commit -m "feat(nav): /products retailer filter becomes a URL-driven chip row"
```

---

### Task 2: Six-retailer registry

**Files:**
- Modify: `web/src/lib/types.ts`, `web/src/lib/filters.ts`, `notify_discord.py`
- Test: `web/test/filters.test.ts`, `unit_testing/test_notify_discord.py`

**Interfaces:**
- Produces: `Retailer` = `'scorptec' | 'pccg' | 'mwave' | 'umart' | 'centrecom' | 'ple'`.

- [ ] **Step 1: Write the failing tests**

Add to `web/test/filters.test.ts`:

```ts
describe('six-retailer readiness', () => {
	it('offers all six retailers, Scorptec and PCCG first', () => {
		expect(RETAILER_OPTIONS.map((o) => o.value)).toEqual([
			'scorptec',
			'pccg',
			'mwave',
			'umart',
			'centrecom',
			'ple'
		]);
	});

	it('accepts a new retailer slug from the URL', () => {
		const filters = parseFilters(new URLSearchParams('retailer=mwave'));
		expect(filters.retailer).toBe('mwave');
	});

	it('still rejects an unknown slug', () => {
		const filters = parseFilters(new URLSearchParams('retailer=nope'));
		expect(filters.retailer).toBeUndefined();
	});
});
```

Add to `unit_testing/test_notify_discord.py`:

```python
def test_retailer_labels_cover_all_six_planned_retailers():
    """The digest prints raw slugs for any retailer missing a label."""
    from notify_discord import RETAILER_LABELS

    for slug in ("scorptec", "pccg", "mwave", "umart", "centrecom", "ple"):
        assert slug in RETAILER_LABELS, f"{slug} would print as a raw slug"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run test/filters.test.ts` — FAIL.
Run: `python -m pytest unit_testing/test_notify_discord.py -q` — FAIL.

- [ ] **Step 3: Extend the registries**

`web/src/lib/types.ts`:
```ts
// The four beyond scorptec/pccg have no scraper yet — the display layer is
// prepared ahead of them so adding one is a pipeline change, not a UI change
// (spec §7). Slugs must match what a future scraper writes to
// retailer_listings.retailer.
export type Retailer = 'scorptec' | 'pccg' | 'mwave' | 'umart' | 'centrecom' | 'ple';
```

`web/src/lib/filters.ts`:
```ts
export const RETAILER_OPTIONS: { value: Retailer; label: string }[] = [
	{ value: 'scorptec', label: 'Scorptec' },
	{ value: 'pccg', label: 'PCCG' },
	{ value: 'mwave', label: 'MWave' },
	{ value: 'umart', label: 'Umart' },
	{ value: 'centrecom', label: 'Centre Com' },
	{ value: 'ple', label: 'PLE' }
];
```

`notify_discord.py`:
```python
RETAILER_LABELS = {
    "scorptec": "Scorptec",
    "pccg": "PCCG",
    "mwave": "MWave",
    "umart": "Umart",
    "centrecom": "Centre Com",
    "ple": "PLE",
}
```

- [ ] **Step 4: Verify**

Run: `cd web && npx vitest run test/filters.test.ts && npm run check`
Run: `python -m pytest -q` from the repo root.
Expected: PASS both.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/filters.ts web/test/filters.test.ts notify_discord.py unit_testing/test_notify_discord.py
git commit -m "feat(nav): display layer ready for six retailers"
```

---

### Task 3: Nav links and active state

**Files:**
- Create: `web/src/lib/nav.ts`
- Modify: `web/src/lib/components/Header.svelte`, `web/src/lib/components/HealthStrip.svelte`, `web/src/routes/+page.server.ts`
- Test: `web/test/nav.test.ts`, `web/test/components.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export interface NavLink { href: string; label: string }
  export const NAV_LINKS: NavLink[]
  export function isActiveLink(href: string, pathname: string, search: URLSearchParams): boolean
  ```

- [ ] **Step 1: Write the failing test**

Create `web/test/nav.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { NAV_LINKS, isActiveLink } from '../src/lib/nav';

const params = (s: string) => new URLSearchParams(s);

describe('NAV_LINKS', () => {
	it('puts Deals first — the site purpose gets the first slot', () => {
		expect(NAV_LINKS[0]).toEqual({ href: '/deals', label: 'Deals' });
	});

	it('replaces Products with GPUs and CPUs, and includes Compare', () => {
		expect(NAV_LINKS.map((l) => l.label)).toEqual([
			'Deals',
			'GPUs',
			'CPUs',
			'Movers',
			'Compare'
		]);
	});
});

describe('isActiveLink', () => {
	it('matches a plain path', () => {
		expect(isActiveLink('/deals', '/deals', params(''))).toBe(true);
		expect(isActiveLink('/deals', '/movers', params(''))).toBe(false);
	});

	// The old check compared pathname to the whole href, so neither category
	// link could ever highlight.
	it('matches a category link on the query string', () => {
		expect(isActiveLink('/products?category=gpu', '/products', params('category=gpu'))).toBe(true);
		expect(isActiveLink('/products?category=cpu', '/products', params('category=gpu'))).toBe(false);
	});

	it('does not highlight a category link on an unfiltered /products', () => {
		expect(isActiveLink('/products?category=gpu', '/products', params(''))).toBe(false);
	});

	it('ignores unrelated query parameters', () => {
		expect(
			isActiveLink('/products?category=gpu', '/products', params('category=gpu&sort=price-asc'))
		).toBe(true);
		expect(isActiveLink('/movers', '/movers', params('window=30d'))).toBe(true);
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run test/nav.test.ts`
Expected: FAIL — cannot resolve `../src/lib/nav`.

- [ ] **Step 3: Write `nav.ts`**

```ts
// Nav links and active-state matching. Pure and separate from Header.svelte
// because matching has to consider the query string, not just the pathname:
// GPUs and CPUs are both /products, distinguished only by ?category=.
export interface NavLink {
	href: string;
	label: string;
}

// Deals first — the site's purpose gets the first slot. GPUs/CPUs replace
// Products so a category is a place rather than a filter re-applied on every
// page. Compare joins the nav, ending its orphan status (spec §6).
export const NAV_LINKS: NavLink[] = [
	{ href: '/deals', label: 'Deals' },
	{ href: '/products?category=gpu', label: 'GPUs' },
	{ href: '/products?category=cpu', label: 'CPUs' },
	{ href: '/movers', label: 'Movers' },
	{ href: '/compare', label: 'Compare' }
];

export function isActiveLink(href: string, pathname: string, search: URLSearchParams): boolean {
	const [linkPath, linkQuery] = href.split('?');
	if (linkPath !== pathname) return false;
	if (!linkQuery) return true;
	// Every parameter the link pins must match; anything else in the URL
	// (sort, page, search terms) is irrelevant to which place we are in.
	for (const [key, value] of new URLSearchParams(linkQuery)) {
		if (search.get(key) !== value) return false;
	}
	return true;
}
```

- [ ] **Step 4: Rewire the header**

In `web/src/lib/components/Header.svelte`:

- Replace the local `links` array with `import { NAV_LINKS, isActiveLink } from '$lib/nav';`
- Replace `const path = $derived(page.url.pathname);` with nothing; use
  `page.url.pathname` and `page.url.searchParams` directly in the markup.
- Change the `<nav>` to scroll horizontally below `md` and keep items on one line:

```svelte
		<nav
			class="-mx-1 flex max-w-full items-center gap-1 overflow-x-auto px-1 text-sm md:overflow-visible"
			aria-label="Main"
		>
			{#each NAV_LINKS as link (link.href)}
				{@const active = isActiveLink(link.href, page.url.pathname, page.url.searchParams)}
				<a
					href={link.href}
					aria-current={active ? 'page' : undefined}
					class="whitespace-nowrap rounded-md px-2.5 py-1.5 no-underline hover:no-underline {active
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:bg-surface-hover hover:text-text'}"
				>
					{link.label}
				</a>
			{/each}
		</nav>
```

- Delete the whole `<p class="hidden items-center gap-3 text-xs text-text-muted lg:flex"> … </p>`
  block (latest snapshot date, snapshot days, DB size) and the now-unused
  `formatBytes` import. These move to the health strip, their honest home
  (§6); the user-facing staleness signal is already `StaleDataBanner`.
- `stats` is still a prop but is no longer read. Remove it from the props
  block, then remove `stats={data.stats}` from the `<Header …>` usage in
  `web/src/routes/+layout.svelte`. Leave `+layout.server.ts` returning `stats` —
  `StaleDataBanner` still uses `data.stats.latestSnapshotDate`.

- [ ] **Step 5: Give the DB size its new home**

In `web/src/lib/components/HealthStrip.svelte`, add `dbSizeBytes` to the props
block (`dbSizeBytes: number;`), import `formatBytes` from `$lib/formats`, and
extend the depth line:

```svelte
			<p class="text-xs text-text-muted">
				<span class="num">{snapshotDays}</span> days ·
				<span class="num">{numberFormat.format(snapshotCount)}</span> snapshots
				{#if dbSizeBytes > 0}
					· <span class="num">{formatBytes(dbSizeBytes)}</span>
				{/if}
			</p>
```

In `web/src/routes/+page.server.ts`, add `dbSizeBytes: stats.dbSizeBytes,` to
the returned object, and pass `dbSizeBytes={data.dbSizeBytes}` to `<HealthStrip>`
in `web/src/routes/+page.svelte`.

Update the three existing `HealthStrip` tests in `web/test/components.test.ts`
to pass `dbSizeBytes: 0` (or a real value in the depth test, asserting the
formatted size appears).

- [ ] **Step 6: Verify**

Run: `cd web && npm run check` (0 errors) then `npx vitest run`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/nav.ts web/test/nav.test.ts web/src/lib/components web/src/routes web/test/components.test.ts
git commit -m "feat(nav): Deals-first nav, category places, query-string active state"
```

---

### Task 4: `/compare` empty state

**Files:**
- Modify: `web/src/routes/compare/+page.server.ts`, `web/src/routes/compare/+page.svelte`

**Interfaces:**
- Produces: load returns `{ entries: CompareEntry[] }` where `entries` is `[]`
  when no `ids` parameter is present. **`?ids=1` must still 400** — an existing
  e2e test pins that.

- [ ] **Step 1: Return an empty result instead of erroring on no ids**

In `web/src/routes/compare/+page.server.ts`, insert immediately after the `ids`
array is built:

```ts
	// Compare is in the nav now, so it must be openable with nothing selected.
	// A malformed request that names exactly one product is still an error —
	// that comes from a broken link, not from clicking "Compare" in the nav.
	if (raw.trim() === '' && ids.length === 0) {
		return { entries: [] };
	}
```

- [ ] **Step 2: Render the empty state**

In `web/src/routes/compare/+page.svelte`, wrap the results table so the empty
case explains how to select products. Immediately after the closing `</div>` of
the heading block, replace the `<div class="overflow-x-auto …">` opening with:

```svelte
	{#if entries.length === 0}
		<div class="rounded-md border border-border bg-surface px-4 py-10 text-center">
			<p class="text-sm text-text">Nothing selected to compare yet.</p>
			<p class="mt-1 text-sm text-text-muted">
				Pick 2–4 products in the same category on the
				<a href="/products" class="text-accent no-underline hover:underline">Products</a>
				page — tick the compare box on each card, then use the Compare bar.
			</p>
		</div>
	{:else}
	<div class="overflow-x-auto rounded-md border border-border">
```

and close the `{#if}` with `{/if}` after that table's closing `</div>`.

- [ ] **Step 3: Verify**

Run: `cd web && npm run check` (0 errors).

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/compare
git commit -m "feat(nav): /compare opens with an empty state instead of a 400"
```

---

### Task 5: E2E coverage, docs and full validation

**Files:**
- Modify: `web/e2e/app.spec.ts`, `STATUS.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update the navigation E2E block**

The existing `navigation & layout` describe (around line 100) asserts on the old
`Dashboard / Products / Movers` links. Update it, and add:

```ts
test.describe('navigation', () => {
	test('puts Deals first and reaches every page', async ({ page }) => {
		await goto(page, '/');
		const nav = page.getByRole('navigation', { name: 'Main' });
		await expect(nav.getByRole('link').first()).toHaveText('Deals');
		for (const label of ['Deals', 'GPUs', 'CPUs', 'Movers', 'Compare']) {
			await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
		}
	});

	test('highlights the GPUs link on /products?category=gpu', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const nav = page.getByRole('navigation', { name: 'Main' });
		await expect(nav.getByRole('link', { name: 'GPUs', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(nav.getByRole('link', { name: 'CPUs', exact: true })).not.toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	test('no longer shows the dataset stats in the header', async ({ page }) => {
		await goto(page, '/');
		const header = page.locator('header');
		await expect(header.getByText(/days$/)).toHaveCount(0);
	});
});

test('compare opens with an empty state explaining how to select', async ({ page }) => {
	await goto(page, '/compare');
	await expect(page.getByText('Nothing selected to compare yet.')).toBeVisible();
});

test('products retailer chips filter via the URL', async ({ page }) => {
	await goto(page, '/products');
	await page.getByRole('button', { name: /^Scorptec/ }).click();
	await expect(page).toHaveURL(/retailer=scorptec/);
});
```

Delete the superseded `products page filters` retailer-`<select>` test added in
stage 3 (`filters by retailer via the URL`), since the control is now a chip.

- [ ] **Step 2: Run the E2E suite**

Run: `cd web && npm run test:e2e`
Expected: all pass. Fix selectors, not the product, if a stale assertion fails.

- [ ] **Step 3: Full validation**

```bash
python -m pytest -q            # from the repo root
cd web && npm run check        # 0 errors
npm test
npm run test:e2e
npm run build
```

- [ ] **Step 4: Verify live**

`cd web && npm run dev`; confirm the nav highlights GPUs on
`/products?category=gpu`, the retailer chips filter, `/compare` shows its empty
state, and the header no longer carries the dataset stats. Stop the server.

- [ ] **Step 5: Update the documentation**

`STATUS.md`: bump **Last updated**, add a dated bullet (no nested chain)
recording the nav change, the query-string active-state fix, the retailer chip
row and its three-driver `FacetChips` reuse, the six-retailer registry with the
explicit note that **no scraper exists for the four new slugs**, the compare
empty state, and the final regression counts. Update the **Regression test
count** table. Note that the price-first IA spec is now **fully implemented
(stages 1–4)**.

`docs/ARCHITECTURE.md` Part 3: append an entry covering (a) why active-state
matching had to become query-string aware, (b) the one-component/three-drivers
chip arrangement and why the client-side and URL-driven mechanisms must not be
collapsed, and (c) that the six-retailer registry is display-side only.

- [ ] **Step 6: Commit**

```bash
git add web/e2e/app.spec.ts STATUS.md docs/ARCHITECTURE.md
git commit -m "test(nav): navigation, chips and compare empty-state coverage; docs"
```

---

## Self-Review

**1. Spec coverage:**

| §6/§7 requirement | Task |
|---|---|
| Deals first in the nav | Task 3 (`NAV_LINKS[0]`) |
| GPUs/CPUs replace Products, both `/products?category=…` | Task 3 |
| Active state must match on the query string | Task 3 (`isActiveLink`) |
| Compare joins the nav | Task 3 |
| Compare with no `ids` renders an empty state | Task 4 |
| DB size + snapshot days move out of the header into the health strip | Task 3 (Steps 4–5) |
| Below `md`, a scrollable row, not a hamburger | Task 3 (`overflow-x-auto`, `whitespace-nowrap`) |
| Extend `RETAILER_OPTIONS` and the `Retailer` type | Task 2 |
| Retailer `<select>` becomes a chip row, URL-driven server-side | Task 1 |
| Product-page chips stay client-side — mechanisms not collapsed | Unchanged by this plan; asserted by the existing product-page chip tests |
| Extend `RETAILER_LABELS` in `notify_discord.py` | Task 2 |
| The four scrapers stay out of scope | Enforced by the Global Constraints |

**2. Placeholder scan:** no TBD/TODO. Task 3 Step 4 and Task 5 Step 1 describe
edits to existing markup by exact selector and block, which is the correct form
for a modification.

**3. Type consistency:** `NavLink`/`NAV_LINKS`/`isActiveLink` (Task 3) are used
only by `Header.svelte` with the same names. `FacetOption` is reused unchanged
from `offers.ts` for `retailerFacets`, matching what `FacetChips` already
expects. `Retailer` (Task 2) widens a union already referenced throughout
`repos.ts`; no field names change. `HealthStrip` gains exactly one prop,
`dbSizeBytes: number`, supplied by `+page.server.ts` from `HeaderStats`.
