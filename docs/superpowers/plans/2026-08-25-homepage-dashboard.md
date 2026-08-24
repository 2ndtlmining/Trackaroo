# Homepage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the homepage's filter-and-sort database view with a
question-answering dashboard: a per-retailer data-health strip, then one
section per category showing top deals, biggest 7-day drops and biggest 7-day
rises.

**Architecture:** Two trivial new grouped queries (`getRetailerFreshness`,
`getCategoryCounts`). Freshness classification is pure and lives in
`web/src/lib/health.ts`. Top deals **reuse `deals.ts` from stage 2** rather
than re-deriving a ranking, so the homepage and `/deals` can never disagree.
Movers come from the existing `getMovers`, split by the `category` field it
already carries. Three new presentational components; the stat tiles,
`CheapestCarousel`, filters and listing table come off the homepage.

**Tech Stack:** SvelteKit 2 (Svelte 5 runes), TypeScript, Tailwind v4,
better-sqlite3, Vitest, Playwright.

**Spec:** [`docs/superpowers/specs/2026-08-23-price-first-ia-design.md`](../specs/2026-08-23-price-first-ia-design.md) — this plan implements **stage 3** (§5), per the sequencing in §10.

## Global Constraints

- **Tokens only.** All colour from the existing tokens in `web/src/app.css`. No new hex values.
- **Direction is never colour-only.** Every up/down indicator carries an arrow glyph and a signed number; every health pill states its age in text.
- **Numbers are monospaced** via `.num`.
- **One accent.** `--accent` is for interactive affordances; deal emphasis uses `--down`.
- **Reduced motion respected.**
- **Live regions retained** where a count changes.
- **Client/server boundary.** No runtime imports from `$lib/server/...` in client components; `import type` is fine. Shared runtime constants in `web/src/lib/constants.ts`.
- **`MIN_HISTORY_POINTS = 3`** gates every average-derived claim.
- **7-day mover window on the homepage**, fixed (spec §5): the scrape cadence is daily, so a 24-hour window is a single snapshot pair and one missed run empties the section. The window selector stays on `/movers`.
- **No nav changes in this stage.** §6/§7 are stage 4. Do not touch `Header.svelte`.
- **E2E determinism** — assertions rest on seeded fixtures, never scraped-live values. Navigation via the local `goto()` helper.

### Decision: three freshness states, not two

§5 names three states — fresh (snapshot today), cooling down (deferred, see
below), stale (no snapshot in ≥ 2 days). That leaves **exactly one day behind**
unnamed, and it is the single most common state: the pipeline runs at 04:00, so
before the morning run every retailer is one day behind and nothing is wrong.

Calling it "stale" would cry wolf; calling it "fresh" would be false. This plan
implements `fresh` (0 days) / `recent` (1 day, muted) / `stale` (≥ 2 days,
warning), matching the treatment `StaleDataBanner` already ships — "muted at
one day (normal before the morning run) and error-toned from two"
(`STATUS.md`, 23-Aug). The ≥ 2 day stale boundary is exactly as the spec sets it.

### Decision: cooling down is deferred, and displays as stale

Per §5, distinguishing an intended circuit-breaker pause from staleness needs
the web app to read `data/pccg_cooldown.json`, coupling it to the pipeline's
file layout. That is deliberately **out of this stage**. Until it lands, a
cooling-down retailer shows as stale — honest, since its data *is* older, just
less specific. Do not add a `--stale`-toned "error" framing that implies the
pipeline is broken.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/server/repos.ts` (modify) | Add `getRetailerFreshness` and `getCategoryCounts`; remove the now-unused `getSummary` + `Summary`. |
| `web/src/lib/health.ts` (create) | Pure freshness classification shared by the strip. |
| `web/src/lib/components/HealthStrip.svelte` (create) | The one slim row: overall currency + a pill per retailer. |
| `web/src/lib/components/MoverRow.svelte` (create) | Compact mover row (price, model link, retailer, signed % with arrow). |
| `web/src/lib/components/CategorySection.svelte` (create) | Per-category panel: header stats + three columns with empty states. |
| `web/src/routes/+page.server.ts` (rewrite) | Load freshness, counts, deals, movers, cheapest. |
| `web/src/routes/+page.svelte` (rewrite) | Health strip + one `CategorySection` per category. |
| `web/src/lib/components/CheapestCarousel.svelte` (delete) | Folded into the section headers (§5). |
| `web/test/health.test.ts` (create) | Vitest for classification. |
| `web/test/repos.test.ts` (modify) | Tests for the two new queries; drop the `getSummary` tests. |
| `web/test/components.test.ts` (modify) | Tests for the three new components; drop the `CheapestCarousel` tests. |
| `web/e2e/app.spec.ts` (modify) | Homepage coverage; replace the carousel test. |
| `STATUS.md`, `docs/ARCHITECTURE.md` (modify) | Documentation, final task. |

---

### Task 1: Freshness and category-count queries

**Files:**
- Modify: `web/src/lib/server/repos.ts`
- Test: `web/test/repos.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export interface RetailerFreshness { retailer: Retailer; latestSnapshotDate: string | null; }
  export function getRetailerFreshness(db: DB): RetailerFreshness[]
  export function getCategoryCounts(db: DB): Map<Category, number>
  ```

- [ ] **Step 1: Write the failing tests**

Add to `web/test/repos.test.ts`, reusing the shared `db` from the top-level
`createSeededDb()` fixture (the same one `getSummary`'s tests used):

```ts
describe('getRetailerFreshness', () => {
	it('returns the latest snapshot date per retailer', () => {
		const rows = getRetailerFreshness(db);
		expect(rows.length).toBeGreaterThan(0);
		for (const row of rows) {
			expect(['scorptec', 'pccg']).toContain(row.retailer);
			expect(row.latestSnapshotDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
		}
	});

	it('orders retailers deterministically by slug', () => {
		const slugs = getRetailerFreshness(db).map((r) => r.retailer);
		expect([...slugs].sort()).toEqual(slugs);
	});
});

describe('getCategoryCounts', () => {
	it('counts tracked products per category', () => {
		const counts = getCategoryCounts(db);
		expect((counts.get('gpu') ?? 0) + (counts.get('cpu') ?? 0)).toBeGreaterThan(0);
	});
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run test/repos.test.ts -t "getRetailerFreshness"`
Expected: FAIL — `getRetailerFreshness is not a function`.

- [ ] **Step 3: Write the implementation**

Add to `web/src/lib/server/repos.ts`, next to `getHeaderStats`:

```ts
export interface RetailerFreshness {
	retailer: Retailer;
	latestSnapshotDate: string | null;
}

// Per-retailer currency for the homepage health strip. Deliberately DB-only:
// distinguishing an intended circuit-breaker pause from real staleness would
// require reading data/pccg_cooldown.json, coupling the web app to the
// pipeline's file layout (spec §5 defers this).
export function getRetailerFreshness(db: DB): RetailerFreshness[] {
	return db
		.prepare(
			`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
			 FROM retailer_listings l
			 JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 GROUP BY l.retailer
			 ORDER BY l.retailer ASC`
		)
		.all() as Array<{ retailer: Retailer; latest: string | null }>
		.map((r) => ({ retailer: r.retailer, latestSnapshotDate: r.latest }));
}

export function getCategoryCounts(db: DB): Map<Category, number> {
	const rows = db
		.prepare(
			`SELECT category, COUNT(*) AS n FROM products WHERE tracked = 1 GROUP BY category`
		)
		.all() as Array<{ category: Category; n: number }>;
	return new Map(rows.map((r) => [r.category, r.n]));
}
```

> TypeScript note: `.all() as Array<…>.map(…)` does not parse — assign the cast
> result to a local first, then map. Write it as:
> ```ts
> const rows = db.prepare(`…`).all() as Array<{ retailer: Retailer; latest: string | null }>;
> return rows.map((r) => ({ retailer: r.retailer, latestSnapshotDate: r.latest }));
> ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run test/repos.test.ts`
Expected: PASS, all pre-existing tests included.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/server/repos.ts web/test/repos.test.ts
git commit -m "feat(home): per-retailer freshness and tracked-count-per-category queries"
```

---

### Task 2: Freshness classification (`health.ts`)

**Files:**
- Create: `web/src/lib/health.ts`
- Test: `web/test/health.test.ts`

**Interfaces:**
- Consumes: `daysBehindToday` from `$lib/formats`, `RetailerFreshness` (Task 1).
- Produces:
  ```ts
  export type FreshnessState = 'fresh' | 'recent' | 'stale' | 'never';
  export interface RetailerHealth {
      retailer: string; label: string; state: FreshnessState;
      days: number | null; text: string;
  }
  export function classifyFreshness(days: number | null): FreshnessState
  export function retailerHealth(rows: RetailerFreshness[], now?: Date): RetailerHealth[]
  ```

- [ ] **Step 1: Write the failing test**

Create `web/test/health.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { classifyFreshness, retailerHealth } from '../src/lib/health';

const NOW = new Date('2026-08-25T09:00:00');

describe('classifyFreshness', () => {
	it('treats a snapshot from today as fresh', () => {
		expect(classifyFreshness(0)).toBe('fresh');
	});

	// The pipeline runs at 04:00, so before the morning run every retailer is
	// one day behind and nothing is wrong. Neither "fresh" nor "stale" is honest.
	it('treats one day behind as recent, not stale', () => {
		expect(classifyFreshness(1)).toBe('recent');
	});

	it('treats two or more days behind as stale', () => {
		expect(classifyFreshness(2)).toBe('stale');
		expect(classifyFreshness(9)).toBe('stale');
	});

	it('treats a missing date as never', () => {
		expect(classifyFreshness(null)).toBe('never');
	});
});

describe('retailerHealth', () => {
	it('labels known retailers and states their age in text', () => {
		const rows = retailerHealth(
			[
				{ retailer: 'scorptec', latestSnapshotDate: '2026-08-25' },
				{ retailer: 'pccg', latestSnapshotDate: '2026-08-23' }
			],
			NOW
		);
		expect(rows[0]).toMatchObject({ retailer: 'scorptec', label: 'Scorptec', state: 'fresh', days: 0 });
		expect(rows[0].text).toBe('today');
		expect(rows[1]).toMatchObject({ retailer: 'pccg', label: 'PCCG', state: 'stale', days: 2 });
		expect(rows[1].text).toBe('2 days behind');
	});

	it('says one day behind in the singular', () => {
		const [row] = retailerHealth([{ retailer: 'pccg', latestSnapshotDate: '2026-08-24' }], NOW);
		expect(row.state).toBe('recent');
		expect(row.text).toBe('1 day behind');
	});

	it('falls back to the slug for an unknown retailer, so a new one is visible', () => {
		const [row] = retailerHealth([{ retailer: 'mwave', latestSnapshotDate: '2026-08-25' }], NOW);
		expect(row.label).toBe('mwave');
	});

	it('reports a retailer that has never reported', () => {
		const [row] = retailerHealth([{ retailer: 'pccg', latestSnapshotDate: null }], NOW);
		expect(row.state).toBe('never');
		expect(row.text).toBe('no data');
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run test/health.test.ts`
Expected: FAIL — cannot resolve `../src/lib/health`.

- [ ] **Step 3: Write the implementation**

Create `web/src/lib/health.ts`:

```ts
// Per-retailer data-health classification for the homepage strip. Pure, so the
// boundaries are pinned by tests rather than by how a pill happens to render.
import { daysBehindToday, stalenessLabel } from './formats';
import { RETAILER_OPTIONS } from './filters';
import type { RetailerFreshness } from './server/repos';

export type FreshnessState = 'fresh' | 'recent' | 'stale' | 'never';

export interface RetailerHealth {
	retailer: string;
	label: string;
	state: FreshnessState;
	days: number | null;
	// Always states the age in words — colour is never the only carrier.
	text: string;
}

// The spec names fresh / cooling-down / stale but leaves one-day-behind
// unnamed, which is the most common state of all: the pipeline runs at 04:00,
// so every retailer is one day behind until the morning run. "recent" keeps
// that honest without crying wolf. The >= 2 day stale boundary is the spec's.
export function classifyFreshness(days: number | null): FreshnessState {
	if (days === null) return 'never';
	if (days === 0) return 'fresh';
	if (days === 1) return 'recent';
	return 'stale';
}

const RETAILER_LABELS = new Map(RETAILER_OPTIONS.map((o) => [o.value as string, o.label]));

export function retailerHealth(rows: RetailerFreshness[], now: Date = new Date()): RetailerHealth[] {
	return rows.map((row) => {
		const days = daysBehindToday(row.latestSnapshotDate, now);
		const state = classifyFreshness(row.latestSnapshotDate === null ? null : days);
		return {
			retailer: row.retailer,
			// An unknown slug falls back to itself so a newly-added retailer
			// shows up rather than rendering blank.
			label: RETAILER_LABELS.get(row.retailer) ?? row.retailer,
			state,
			days: row.latestSnapshotDate === null ? null : days,
			text:
				state === 'never'
					? 'no data'
					: days === 0
						? 'today'
						: stalenessLabel(days as number)
		};
	});
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run test/health.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/health.ts web/test/health.test.ts
git commit -m "feat(home): pure per-retailer freshness classification"
```

---

### Task 3: `HealthStrip` component

**Files:**
- Create: `web/src/lib/components/HealthStrip.svelte`
- Test: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `RetailerHealth[]` (Task 2), `HeaderStats` fields.
- Produces:
  ```ts
  { retailers: RetailerHealth[]; latestSnapshotDate: string | null;
    snapshotDays: number; snapshotCount: number }
  ```

- [ ] **Step 1: Write the failing test**

Add to `web/test/components.test.ts` (import `HealthStrip` at the top):

```ts
describe('HealthStrip', () => {
	const health = [
		{ retailer: 'scorptec', label: 'Scorptec', state: 'fresh' as const, days: 0, text: 'today' },
		{ retailer: 'pccg', label: 'PCCG', state: 'stale' as const, days: 3, text: '3 days behind' }
	];

	it('states each retailer and its age in words, not colour alone', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('Scorptec');
		expect(html).toContain('today');
		expect(html).toContain('PCCG');
		expect(html).toContain('3 days behind');
	});

	it('shows the dataset depth', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('17');
		expect(html).toContain('4,988');
	});

	it('handles an empty database without crashing', () => {
		const html = renderComponent(HealthStrip, {
			retailers: [],
			latestSnapshotDate: null,
			snapshotDays: 0,
			snapshotCount: 0
		});
		expect(html).toContain('No snapshots yet');
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts -t HealthStrip`
Expected: FAIL.

- [ ] **Step 3: Write the component**

Create `web/src/lib/components/HealthStrip.svelte`:

```svelte
<script lang="ts">
	import { formatDate } from '$lib/formats';
	import type { RetailerHealth } from '$lib/health';

	let {
		retailers,
		latestSnapshotDate,
		snapshotDays,
		snapshotCount
	}: {
		retailers: RetailerHealth[];
		latestSnapshotDate: string | null;
		snapshotDays: number;
		snapshotCount: number;
	} = $props();

	// A cooling-down retailer currently reads as stale (spec §5 defers reading
	// data/pccg_cooldown.json). Warning tone, never an error tone: the PCCG
	// circuit breaker is working as designed and the UI must not cry wolf.
	function pillClass(state: RetailerHealth['state']): string {
		if (state === 'fresh') return 'border-down/40 bg-down/10 text-down';
		if (state === 'recent') return 'border-border bg-surface text-text-muted';
		return 'border-up/40 bg-up/10 text-up';
	}

	function marker(state: RetailerHealth['state']): string {
		if (state === 'fresh') return '●';
		if (state === 'recent') return '○';
		return '▲';
	}

	const numberFormat = new Intl.NumberFormat('en-AU');
</script>

<section
	class="mb-6 rounded-lg border border-border bg-surface px-3 py-2.5"
	aria-label="Data health"
>
	{#if latestSnapshotDate}
		<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
			<p class="text-sm text-text">
				Most recent snapshot <span class="font-medium">{formatDate(latestSnapshotDate)}</span>
			</p>
			<p class="text-xs text-text-muted">
				<span class="num">{snapshotDays}</span> days ·
				<span class="num">{numberFormat.format(snapshotCount)}</span> snapshots
			</p>
		</div>
		<div class="mt-2 flex flex-wrap items-center gap-1.5">
			{#each retailers as r (r.retailer)}
				<span
					class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs {pillClass(
						r.state
					)}"
				>
					<span aria-hidden="true">{marker(r.state)}</span>
					<span class="font-medium">{r.label}</span>
					<span>{r.text}</span>
				</span>
			{/each}
		</div>
	{:else}
		<p class="text-sm text-text-muted">No snapshots yet — run the pipeline to collect prices.</p>
	{/if}
</section>
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts -t HealthStrip`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/HealthStrip.svelte web/test/components.test.ts
git commit -m "feat(home): data-health strip with per-retailer freshness pills"
```

---

### Task 4: `MoverRow` component

**Files:**
- Create: `web/src/lib/components/MoverRow.svelte`
- Test: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `Mover` from `$lib/server/repos` (already carries `category`, `pctChange`, `newPrice`, `model`, `productId`, `retailer`).
- Produces: `{ mover: Mover }`.

- [ ] **Step 1: Write the failing test**

Add to `web/test/components.test.ts`. Build the fixture from the `Mover`
interface — there is no existing mover helper, so define one locally:

```ts
describe('MoverRow', () => {
	function mover(over: Partial<Mover> = {}): Mover {
		return {
			listingId: 1, productId: 5, category: 'gpu', brand: 'NVIDIA',
			model: 'GeForce RTX 5070 Ti', retailer: 'scorptec',
			variantName: 'ASUS TUF RTX 5070 Ti OC 16GB',
			listingUrl: 'https://example.com/1', oldPrice: 1400, newPrice: 1299,
			change: -101, pctChange: -7.2, pointsInWindow: 7, historyPoints: 30,
			notEnoughHistory: false, windowStart: '2026-08-18', windowEnd: '2026-08-25',
			...over
		};
	}

	it('shows a down arrow and a signed percentage for a drop', () => {
		const html = renderComponent(MoverRow, { mover: mover() });
		expect(html).toContain('▼');
		expect(html).toContain('7.2%');
		expect(html).toContain('$1,299');
		expect(html).toContain('GeForce RTX 5070 Ti');
	});

	it('shows an up arrow for a rise', () => {
		const html = renderComponent(MoverRow, {
			mover: mover({ pctChange: 5.4, change: 70, oldPrice: 1229, newPrice: 1299 })
		});
		expect(html).toContain('▲');
		expect(html).toContain('5.4%');
	});

	it('links to the product page', () => {
		const html = renderComponent(MoverRow, { mover: mover() });
		expect(html).toContain('href="/product/5"');
	});

	it('renders a mover with no percentage without crashing', () => {
		const html = renderComponent(MoverRow, {
			mover: mover({ pctChange: null, change: null, oldPrice: null })
		});
		expect(html).toContain('GeForce RTX 5070 Ti');
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts -t MoverRow`
Expected: FAIL.

- [ ] **Step 3: Write the component**

Create `web/src/lib/components/MoverRow.svelte`:

```svelte
<script lang="ts">
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import { deltaPresentation } from '$lib/offers';
	import type { Mover } from '$lib/server/repos';

	let { mover }: { mover: Mover } = $props();

	const retailerLabel = $derived(
		RETAILER_OPTIONS.find((o) => o.value === mover.retailer)?.label ?? mover.retailer
	);
	// Same three-way treatment as the offer row: a rise is red, a drop green,
	// and exactly zero is neither.
	const presentation = $derived(mover.pctChange === null ? null : deltaPresentation(mover.pctChange));
</script>

<div class="flex items-center gap-2 px-3 py-2">
	<span class="num w-20 shrink-0 text-sm font-semibold text-text">{formatAud(mover.newPrice)}</span>
	<div class="min-w-0 flex-1">
		<a
			href={`/product/${mover.productId}`}
			class="block truncate text-sm text-text no-underline hover:underline"
			title={mover.model}>{mover.model}</a
		>
		<span class="text-xs text-text-muted">{retailerLabel}</span>
	</div>
	{#if presentation && mover.pctChange !== null}
		<span class="shrink-0 text-xs {presentation.class}">
			{presentation.arrow}
			{formatPct(mover.pctChange)}
		</span>
	{:else}
		<span class="shrink-0 text-xs text-text-muted">—</span>
	{/if}
</div>
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts -t MoverRow`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/MoverRow.svelte web/test/components.test.ts
git commit -m "feat(home): compact mover row"
```

---

### Task 5: `CategorySection` component

**Files:**
- Create: `web/src/lib/components/CategorySection.svelte`
- Test: `web/test/components.test.ts`

**Interfaces:**
- Consumes: `Deal` (stage 2 `deals.ts`), `Mover`, `OfferRow`, `MoverRow`, `dealToOffer`.
- Produces:
  ```ts
  { title: string; href: string; trackedCount: number; cheapestPrice: number | null;
    deals: Deal[]; drops: Mover[]; rises: Mover[] }
  ```

- [ ] **Step 1: Write the failing test**

Add to `web/test/components.test.ts`:

```ts
describe('CategorySection', () => {
	const base = {
		title: 'GPUs', href: '/products?category=gpu', trackedCount: 47,
		cheapestPrice: 329, deals: [], drops: [], rises: []
	};

	it('shows the tracked count and cheapest price in the header', () => {
		const html = renderComponent(CategorySection, base);
		expect(html).toContain('GPUs');
		expect(html).toContain('47');
		expect(html).toContain('$329');
		expect(html).toContain('href="/products?category=gpu"');
	});

	it('gives every empty column real copy, not a blank panel', () => {
		const html = renderComponent(CategorySection, base);
		expect(html).toContain('Nothing below its 30-day average today.');
		expect(html).toContain('No significant price moves in the last 7 days.');
	});

	it('omits the cheapest figure when there is no in-stock price', () => {
		const html = renderComponent(CategorySection, { ...base, cheapestPrice: null });
		expect(html).not.toContain('cheapest');
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts -t CategorySection`
Expected: FAIL.

- [ ] **Step 3: Write the component**

Create `web/src/lib/components/CategorySection.svelte`:

```svelte
<script lang="ts">
	import MoverRow from './MoverRow.svelte';
	import OfferRow from './OfferRow.svelte';
	import { dealToOffer, type Deal } from '$lib/deals';
	import { formatAud } from '$lib/formats';
	import type { Mover } from '$lib/server/repos';

	let {
		title,
		href,
		trackedCount,
		cheapestPrice,
		deals,
		drops,
		rises
	}: {
		title: string;
		href: string;
		trackedCount: number;
		cheapestPrice: number | null;
		deals: Deal[];
		drops: Mover[];
		rises: Mover[];
	} = $props();
</script>

<section class="rounded-lg border border-border bg-surface" aria-label={title}>
	<header
		class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-3 py-2.5"
	>
		<h2 class="text-sm font-semibold text-text">{title}</h2>
		<p class="text-xs text-text-muted">
			<span class="num">{trackedCount}</span> tracked
			{#if cheapestPrice !== null}
				· cheapest <span class="num">{formatAud(cheapestPrice)}</span>
			{/if}
			· <a {href} class="text-accent no-underline hover:underline">All {title} →</a>
		</p>
	</header>

	<div class="grid gap-px bg-border md:grid-cols-3">
		<div class="bg-surface">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Top deals</h3>
			{#if deals.length > 0}
				<div class="divide-y divide-border">
					{#each deals as deal (deal.productId)}
						<OfferRow
							offer={dealToOffer(deal)}
							avg30={deal.avg30}
							titleOverride={deal.model}
							detailHref={`/product/${deal.productId}`}
						/>
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">Nothing below its 30-day average today.</p>
			{/if}
		</div>

		<div class="bg-surface">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Biggest drops (7d)</h3>
			{#if drops.length > 0}
				<div class="divide-y divide-border">
					{#each drops as m (m.listingId)}
						<MoverRow mover={m} />
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">
					No significant price moves in the last 7 days.
				</p>
			{/if}
		</div>

		<div class="bg-surface">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Biggest rises (7d)</h3>
			{#if rises.length > 0}
				<div class="divide-y divide-border">
					{#each rises as m (m.listingId)}
						<MoverRow mover={m} />
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">
					No significant price moves in the last 7 days.
				</p>
			{/if}
		</div>
	</div>
</section>
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts -t CategorySection`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/CategorySection.svelte web/test/components.test.ts
git commit -m "feat(home): per-category section with deals, drops and rises"
```

---

### Task 6: Rewrite the homepage

**Files:**
- Rewrite: `web/src/routes/+page.server.ts`, `web/src/routes/+page.svelte`
- Delete: `web/src/lib/components/CheapestCarousel.svelte`
- Modify: `web/src/lib/server/repos.ts` (remove `getSummary` + `Summary`)
- Modify: `web/test/components.test.ts` (remove the `CheapestCarousel` block + import), `web/test/repos.test.ts` (remove the `getSummary` block + import)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: the homepage load returns
  ```ts
  { retailers: RetailerHealth[]; latestSnapshotDate: string | null;
    snapshotDays: number; snapshotCount: number;
    sections: Array<{ category: Category; title: string; href: string;
      trackedCount: number; cheapestPrice: number | null;
      deals: Deal[]; drops: Mover[]; rises: Mover[] }> }
  ```

**Why the deletions:** §5 states the four stat tiles are removed and
`CheapestCarousel` is folded into the section headers. That leaves
`getSummary`/`Summary` and the carousel with no callers. This repo removes dead
exports rather than leaving them (`STATUS.md`, 23-Aug: "six unused frontend
exports" removed), so they go with the change that orphans them.

- [ ] **Step 1: Rewrite the server load**

Replace `web/src/routes/+page.server.ts` entirely:

```ts
import {
	getCategoryCounts,
	getCheapestPerModel,
	getDealCandidates,
	getHeaderStats,
	getMovers,
	getRetailerFreshness,
	type Mover
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { belowAverage, toDeals, type Deal } from '$lib/deals';
import { retailerHealth } from '$lib/health';
import type { Category } from '$lib/types';

// Fixed 7 days, not the /movers window selector: the scrape cadence is daily,
// so a 24-hour window is a single snapshot pair and one missed run would empty
// the section outright (spec §5).
const HOME_MOVER_DAYS = 7;
const PER_COLUMN = 3;

const SECTIONS: Array<{ category: Category; title: string }> = [
	{ category: 'gpu', title: 'GPUs' },
	{ category: 'cpu', title: 'CPUs' }
];

export function load() {
	const db = getDb();
	const stats = getHeaderStats(db);
	const counts = getCategoryCounts(db);
	// Same source as /deals, so the two surfaces can never disagree about
	// what counts as a deal or how deep it is.
	const allDeals = belowAverage(toDeals(getDealCandidates(db)));
	const movers = getMovers(db, HOME_MOVER_DAYS);

	const sections = SECTIONS.map(({ category, title }) => {
		const cheapest = getCheapestPerModel(db, category);
		const inCategory = (m: Mover) => m.category === category && m.pctChange !== null;
		const drops = movers
			.filter((m) => inCategory(m) && (m.pctChange as number) < 0)
			.sort((a, b) => (a.pctChange as number) - (b.pctChange as number));
		const rises = movers
			.filter((m) => inCategory(m) && (m.pctChange as number) > 0)
			.sort((a, b) => (b.pctChange as number) - (a.pctChange as number));

		return {
			category,
			title,
			href: `/products?category=${category}`,
			trackedCount: counts.get(category) ?? 0,
			cheapestPrice: cheapest.reduce<number | null>(
				(min, c) => (min === null || c.price < min ? c.price : min),
				null
			),
			deals: allDeals.filter((d: Deal) => d.category === category).slice(0, PER_COLUMN),
			drops: drops.slice(0, PER_COLUMN),
			rises: rises.slice(0, PER_COLUMN)
		};
	});

	return {
		retailers: retailerHealth(getRetailerFreshness(db)),
		latestSnapshotDate: stats.latestSnapshotDate,
		snapshotDays: stats.snapshotDays,
		snapshotCount: stats.snapshotCount,
		sections
	};
}
```

- [ ] **Step 2: Rewrite the page**

Replace `web/src/routes/+page.svelte` entirely:

```svelte
<script lang="ts">
	import CategorySection from '$lib/components/CategorySection.svelte';
	import HealthStrip from '$lib/components/HealthStrip.svelte';

	let { data } = $props();
</script>

<svelte:head>
	<title>Trackaroo — Dashboard</title>
	<meta name="description" content="Latest tracked prices for AU CPUs and GPUs." />
</svelte:head>

<div>
	<h1 class="mb-4 text-xl font-semibold text-text">Dashboard</h1>

	<HealthStrip
		retailers={data.retailers}
		latestSnapshotDate={data.latestSnapshotDate}
		snapshotDays={data.snapshotDays}
		snapshotCount={data.snapshotCount}
	/>

	<div class="space-y-6">
		{#each data.sections as section (section.category)}
			<CategorySection
				title={section.title}
				href={section.href}
				trackedCount={section.trackedCount}
				cheapestPrice={section.cheapestPrice}
				deals={section.deals}
				drops={section.drops}
				rises={section.rises}
			/>
		{/each}
	</div>
</div>
```

- [ ] **Step 3: Remove the orphaned carousel and summary query**

```bash
cd web && rm src/lib/components/CheapestCarousel.svelte
```

In `web/test/components.test.ts`: delete the `import CheapestCarousel …` line
and the whole `describe('CheapestCarousel', … )` block.

In `web/src/lib/server/repos.ts`: delete the `Summary` interface and the
`getSummary` function.

In `web/test/repos.test.ts`: delete `getSummary` from the import block and the
whole `describe('getSummary', … )` block.

- [ ] **Step 4: Confirm nothing else referenced them**

Run:
```bash
cd web && grep -rn "CheapestCarousel\|getSummary\|Summary\b" src/ test/ e2e/
```
Expected: no matches other than unrelated words. If `e2e/app.spec.ts` still has
the carousel test, leave it for Task 7, which replaces it.

- [ ] **Step 5: Type check and verify**

Run: `cd web && npm run check`
Expected: 0 errors.

Run: `cd web && npx vitest run`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A web/src web/test
git commit -m "feat(home): question-answering dashboard replaces the listing table"
```

---

### Task 7: E2E coverage, docs and full validation

**Files:**
- Modify: `web/e2e/app.spec.ts`
- Modify: `STATUS.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1: Replace the carousel E2E test with homepage coverage**

In `web/e2e/app.spec.ts`, delete the test named
`renders the cheapest-deals carousel with a GPU/CPU toggle`, and any other
homepage test that asserts on the removed stat tiles, filters or listing table.
Add:

```ts
test.describe('homepage dashboard', () => {
	test('shows a data-health strip naming each retailer and its age', async ({ page }) => {
		await goto(page, '/');
		const strip = page.getByLabel('Data health');
		await expect(strip).toBeVisible();
		await expect(strip.getByText('Scorptec')).toBeVisible();
		await expect(strip.getByText('PCCG')).toBeVisible();
	});

	test('renders a GPU and a CPU section with links through to the category', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByRole('link', { name: 'All GPUs →' })).toHaveAttribute(
			'href',
			'/products?category=gpu'
		);
		await expect(page.getByRole('link', { name: 'All CPUs →' })).toHaveAttribute(
			'href',
			'/products?category=cpu'
		);
	});

	test('surfaces the seeded deal fixture in the GPU top-deals column', async ({ page }) => {
		await goto(page, '/');
		await expect(
			page.getByLabel('GPUs').getByRole('link', { name: 'E2E Deal Demo GPU' })
		).toBeVisible();
	});

	test('no longer renders the filter-and-sort listing table', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByRole('table')).toHaveCount(0);
	});
});
```

- [ ] **Step 2: Run the E2E suite**

Run: `cd web && npm run test:e2e`
Expected: all pass. Any failure here is almost certainly a homepage test from
an earlier stage still asserting on removed elements — delete or update it, do
not restore the removed elements.

- [ ] **Step 3: Full validation**

```bash
python -m pytest -q            # from the repo root
cd web && npm run check        # 0 errors
npm test
npm run test:e2e
npm run build
```

- [ ] **Step 4: Verify the page live**

Run `cd web && npm run dev`, open `/`, confirm the health strip and both
category sections render against the real DB. Stop the server.

- [ ] **Step 5: Update the documentation**

`STATUS.md`: bump **Last updated**, add a dated bullet at the top of **Recent
changes** (no nested "Prior update" chain) covering the homepage rewrite, the
three freshness states and why one-day-behind is its own state, the deferred
cooling-down signal, the removal of the stat tiles / carousel / listing table /
`getSummary`, and the final regression counts. Update the **Regression test
count** table and the Routes line.

`docs/ARCHITECTURE.md` Part 3: append a decision entry recording (a) the
fresh/recent/stale three-state split and the 04:00-run rationale, (b) that
cooling-down is deliberately deferred to avoid coupling the web app to
`data/pccg_cooldown.json`, and (c) that the homepage reuses `deals.ts` rather
than deriving a second ranking.

- [ ] **Step 6: Commit**

```bash
git add web/e2e/app.spec.ts STATUS.md docs/ARCHITECTURE.md
git commit -m "test(home): homepage dashboard e2e coverage; docs"
```

---

## Self-Review

**1. Spec coverage (§5):**

| §5 requirement | Task |
|---|---|
| Health strip at the top, one slim row | Tasks 1–3 |
| Fresh / stale states, age stated in text | Task 2 (`classifyFreshness`), Task 3 |
| Cooling down deferred, shows as stale, not error-toned | Task 2 + Task 3 (`pillClass` comment) |
| Per-retailer last snapshot (the one new query) | Task 1 |
| Per-category: top deals, biggest drops (7d), biggest rises (7d) | Tasks 4–6 |
| 7-day mover window fixed on the homepage | Task 6 (`HOME_MOVER_DAYS`) |
| Deal ≠ mover — both lists shown | Task 5 (separate columns), Task 6 (separate sources) |
| Tracked count + cheapest in section header | Task 1 (`getCategoryCounts`), Task 6 |
| Stat tiles removed | Task 6 |
| `CheapestCarousel` folded in | Task 6 (deleted) |
| Listing table moves to `/products` | Task 6 (removed from `/`; `/products` already has it) |
| Empty-state copy for deals and movers | Task 5 |
| Insufficient-history state | Inherited from stage 2: `toDeals` drops products below `MIN_HISTORY_POINTS`, so they never reach the column; the column then shows its empty copy. |

**Deliberately out of scope:** nav/header changes (§6), the six-retailer chip
row (§7) — both stage 4; reading `data/pccg_cooldown.json` (§5 follow-up).

**2. Placeholder scan:** no TBD/TODO. Task 6 Step 3 and Task 7 Step 1 describe
*deletions* by exact symbol and test name rather than showing code, which is the
correct form for a removal.

**3. Type consistency:** `RetailerFreshness` (Task 1) is consumed by
`retailerHealth` (Task 2) with matching field names. `RetailerHealth` (Task 2)
is the `retailers` prop of `HealthStrip` (Task 3). `Mover` is used unchanged
from `repos.ts` in Tasks 4–6. `Deal` and `dealToOffer` come from stage 2's
`deals.ts` unchanged. `CategorySection`'s seven props (Task 5) match exactly
what the load function builds per section (Task 6).
