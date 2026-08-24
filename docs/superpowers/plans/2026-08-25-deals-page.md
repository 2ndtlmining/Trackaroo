# /deals Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `/deals` — a destination that ranks every tracked product by how
far its cheapest in-stock price sits below its own 30-day average, with a
separate section for products at or near their all-time low.

**Architecture:** One new read query (`getDealCandidates`) returns a single row
per product: its cheapest in-stock listing on the latest snapshot date, plus
that product's all-time low and 30-day average. All ranking, section membership
and facet logic is pure and lives in `web/src/lib/deals.ts`, tested with Vitest.
The page reuses the stage-1 `OfferRow` and `FacetChips` components verbatim —
`OfferRow` gains two additive optional props so a product-level row can carry
the model name and link to the product page.

**Tech Stack:** SvelteKit 2 (Svelte 5 runes), TypeScript, Tailwind v4,
better-sqlite3, Vitest, Playwright.

**Spec:** [`docs/superpowers/specs/2026-08-23-price-first-ia-design.md`](../specs/2026-08-23-price-first-ia-design.md) — this plan implements **stage 2** (§4), per the sequencing in §10.

## Global Constraints

- **Tokens only.** All colour comes from the existing tokens in `web/src/app.css`
  (`--bg`, `--surface`, `--surface-hover`, `--border`, `--text`, `--text-muted`,
  `--accent`, `--accent-soft`, `--up`, `--down`, `--flat`, `--stale`). No new hex values.
- **Direction is never colour-only.** Every up/down indicator carries an arrow glyph and a signed number.
- **Numbers are monospaced** via the `.num` class.
- **One accent.** `--accent` is reserved for interactive affordances. Deal emphasis uses `--down`.
- **Reduced motion respected**, following the existing `@media (prefers-reduced-motion: reduce)` pattern in `+layout.svelte`.
- **Live regions retained.** `aria-live="polite"` result-count announcements on filter changes.
- **Client/server boundary.** Client components must not import *runtime values* from `$lib/server/...`. Importing `import type` from `$lib/server/repos` is fine and already done by `listingsPanel.ts`. Shared runtime constants live in `web/src/lib/constants.ts`.
- **`MIN_HISTORY_POINTS = 3`** (`web/src/lib/constants.ts`) gates every average-derived claim.
- **"Near" all-time low means within 2%** of the all-time low.
- **No nav link in this stage.** `/deals` is reachable by URL only until stage 4 (§10: shipping a `Deals` nav link before `/deals` exists would ship a broken site).
- **E2E determinism.** `web/e2e/seed.mjs` seeds from the live `data/` directory when it has files, so every `/deals` assertion must rest on a fixture the seed injects itself, never on scraped-live values (`CLAUDE.md`, E2E conventions).
- **E2E navigation** goes through the local `goto()` helper in `web/e2e/app.spec.ts`, never `page.goto(...)` directly.

### Decision: eligibility gates both sections

§4 says "Only products with `avg30Points >= MIN_HISTORY_POINTS` are eligible."
That gate is applied to **both** sections, including at-all-time-low. The stated
rationale — three days of history is not a meaningful basis for a claim — applies
just as much to an "all-time low" drawn from three days as to an average.
`avg30Points` is the history-depth proxy for both.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/lib/server/repos.ts` (modify) | Add `DealCandidate` + `getDealCandidates(db)` — one row per product, cheapest in-stock today + all-time low + 30-day average. Also widen `facetCounts`' generic bound in `offers.ts` (see below). |
| `web/src/lib/offers.ts` (modify) | Widen `facetCounts` to any item carrying `retailer`/`brand` so `/deals` reuses it instead of duplicating it. |
| `web/src/lib/deals.ts` (create) | Pure logic: eligibility, depth ranking, section partition, category facets, filtering, and the `Deal → ListingDisplay` adapter that lets `OfferRow` render a product-level row. |
| `web/src/lib/components/OfferRow.svelte` (modify) | Two additive optional props (`titleOverride`, `detailHref`) so the same row serves both the product page and `/deals`. |
| `web/src/routes/deals/+page.server.ts` (create) | URL-driven load: parse facet params, build and filter deals, compute per-axis facet counts. |
| `web/src/routes/deals/+page.svelte` (create) | Two sections, `#all-time-low` anchor, chip facets driven by `goto()`, real empty-state copy. |
| `web/test/deals.test.ts` (create) | Vitest for every pure function in `deals.ts`. |
| `web/test/repos.test.ts` (modify) | Vitest for `getDealCandidates` against the in-memory fixture DB. |
| `web/test/components.test.ts` (modify) | Vitest for the `OfferRow` override props. |
| `web/e2e/seed.mjs` (modify) | Inject the deterministic deal fixtures. |
| `web/e2e/app.spec.ts` (modify) | `/deals` renders, ranks, sections, facets, empty state. |
| `STATUS.md`, `docs/ARCHITECTURE.md` (modify) | Documentation, in the final task. |

---

### Task 1: `getDealCandidates` query

**Files:**
- Modify: `web/src/lib/server/repos.ts` (add after `getCheapestPerModel`, which ends at the `getMovers` declaration)
- Test: `web/test/repos.test.ts`

**Interfaces:**
- Consumes: the existing private `notBundle(alias)` helper (`repos.ts:186`) and the `DB` type from `./db`.
- Produces:
  ```ts
  export interface DealCandidate {
      productId: number;
      category: Category;
      model: string;
      brand: string;
      listingId: number;
      variantName: string | null;
      retailer: Retailer;
      listingUrl: string;
      price: number;
      snapshotDate: string;
      allTimeLow: number | null;
      avg30: number | null;
      avg30Points: number;
  }
  export function getDealCandidates(db: DB, days?: number): DealCandidate[]
  ```

- [ ] **Step 1: Write the failing test**

Add to `web/test/repos.test.ts`. That file builds a purpose-named temp-file DB
per feature (`createMiniStatsDb`, `createMiniCompareDb`, `createMiniAlertsDb`) —
there are **no** generic `makeDb`/`seedProduct` helpers, so follow that same
shape. `openDatabase`, `SCHEMA_PATH`, `fs`, `os` and `path` are already imported
at the top of the file. Add `getDealCandidates` to the existing import block.

```ts
function createMiniDealsDb(): { db: DB; close: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-deals-'));
	const file = path.join(dir, 'deals.db');
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));

	// 1: two listings, a long history, and a much older all-time low.
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('gpu', 'NVIDIA', 'RTX Deal', 'current', 1)"
	).run();
	// 2: only an out-of-stock listing today — must not be a candidate.
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('gpu', 'AMD', 'RTX SoldOut', 'current', 1)"
	).run();
	// 3: untracked — must never appear.
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('cpu', 'AMD', 'Ryzen Untracked', 'current', 0)"
	).run();

	const listing = db.prepare(
		'INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) VALUES (?, ?, ?, ?, ?)'
	);
	const cheapId = Number(
		listing.run(1, 'scorptec', 'Deal A', 'https://scorptec/deal-a', 'active').lastInsertRowid
	);
	const dearId = Number(
		listing.run(1, 'pccg', 'Deal B', 'https://pccg/deal-b', 'active').lastInsertRowid
	);
	const bundleId = Number(
		listing.run(1, 'scorptec', 'Deal A bundle', 'https://scorptec/deal-a-bundle', 'active')
			.lastInsertRowid
	);
	const oosId = Number(
		listing.run(2, 'scorptec', 'SoldOut', 'https://scorptec/soldout', 'active').lastInsertRowid
	);
	const untrackedId = Number(
		listing.run(3, 'pccg', 'Untracked', 'https://pccg/untracked', 'active').lastInsertRowid
	);

	const snap = db.prepare(
		'INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) VALUES (?, ?, ?, ?, ?)'
	);
	// Well outside the 30-day window, so it is the all-time low but not in avg30.
	snap.run(cheapId, '2026-01-01', 55, 'in_stock', '2026-01-01T04:00:00.000Z');
	snap.run(cheapId, '2026-08-18', 120, 'in_stock', '2026-08-18T04:00:00.000Z');
	snap.run(cheapId, '2026-08-19', 140, 'in_stock', '2026-08-19T04:00:00.000Z');
	snap.run(cheapId, '2026-08-20', 100, 'in_stock', '2026-08-20T04:00:00.000Z');
	snap.run(dearId, '2026-08-20', 140, 'in_stock', '2026-08-20T04:00:00.000Z');
	// A bundle priced far below everything — proves notBundle() excludes it
	// from both the cheapest-listing pick and the average.
	snap.run(bundleId, '2026-08-20', 10, 'in_stock', '2026-08-20T04:00:00.000Z');
	snap.run(oosId, '2026-08-20', 90, 'out_of_stock', '2026-08-20T04:00:00.000Z');
	snap.run(untrackedId, '2026-08-20', 80, 'in_stock', '2026-08-20T04:00:00.000Z');

	return {
		db,
		close: () => {
			db.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	};
}

describe('getDealCandidates', () => {
	let fixture: { db: DB; close: () => void };

	beforeAll(() => {
		fixture = createMiniDealsDb();
	});

	afterAll(() => {
		fixture.close();
	});

	it('returns the cheapest in-stock listing per product on the latest date', () => {
		const rows = getDealCandidates(fixture.db);
		expect(rows).toHaveLength(1);
		expect(rows[0].productId).toBe(1);
		expect(rows[0].model).toBe('RTX Deal');
		expect(rows[0].category).toBe('gpu');
		expect(rows[0].price).toBe(100);
		expect(rows[0].retailer).toBe('scorptec');
		expect(rows[0].listingUrl).toBe('https://scorptec/deal-a');
		expect(rows[0].snapshotDate).toBe('2026-08-20');
	});

	it('reports the all-time low across all history, not just the 30-day window', () => {
		const rows = getDealCandidates(fixture.db);
		expect(rows[0].allTimeLow).toBe(55);
	});

	it('averages the per-day cheapest in-stock price within the window and counts days', () => {
		const rows = getDealCandidates(fixture.db);
		// 2026-08-18..20 only: (120 + 140 + 100) / 3. The January row and the
		// $10 bundle are both excluded.
		expect(rows[0].avg30Points).toBe(3);
		expect(rows[0].avg30).toBeCloseTo(120, 5);
	});

	it('omits products with no in-stock listing on the latest date, and untracked products', () => {
		const models = getDealCandidates(fixture.db).map((r) => r.model);
		expect(models).not.toContain('RTX SoldOut');
		expect(models).not.toContain('Ryzen Untracked');
	});
});
```


- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/repos.test.ts -t getDealCandidates`
Expected: FAIL — `getDealCandidates is not a function`.

- [ ] **Step 3: Write the implementation**

Add to `web/src/lib/server/repos.ts`, directly after `getCheapestPerModel`.
It deliberately mirrors that query's proven shape (latest-date join + a
correlated MIN to pick the cheapest listing), differing only in that it spans
both categories and reports an **all-time** low rather than a 90-day low.

```ts
export interface DealCandidate {
	productId: number;
	category: Category;
	model: string;
	brand: string;
	listingId: number;
	variantName: string | null;
	retailer: Retailer;
	listingUrl: string;
	price: number;
	snapshotDate: string;
	allTimeLow: number | null;
	avg30: number | null;
	avg30Points: number;
}

// One row per tracked product: its cheapest in-stock listing on the latest
// snapshot date, plus the two history figures /deals ranks on. Spans both
// categories in a single query — the page filters by category client-side
// from the URL, so splitting it per category would just double the work.
export function getDealCandidates(db: DB, days = 30): DealCandidate[] {
	const rows = db
		.prepare(
			`SELECT
				p.id AS product_id,
				p.category,
				p.model,
				p.brand,
				l.id AS listing_id,
				l.variant_name,
				l.retailer,
				l.listing_url,
				ps.price_aud AS price,
				ps.snapshot_date,
				(SELECT MIN(ps3.price_aud)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id
				   AND ps3.stock_status = 'in_stock'
				   AND ${notBundle('l3')}) AS all_time_low,
				(SELECT AVG(dm.price)
				 FROM (
					SELECT ps3.snapshot_date, MIN(ps3.price_aud) AS price
					FROM price_snapshots ps3
					JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
					WHERE l3.product_id = p.id
					  AND ps3.stock_status = 'in_stock'
					  AND ${notBundle('l3')}
					  AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), @window)
					GROUP BY ps3.snapshot_date
				 ) dm) AS avg30,
				(SELECT COUNT(*)
				 FROM (
					SELECT ps3.snapshot_date
					FROM price_snapshots ps3
					JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
					WHERE l3.product_id = p.id
					  AND ps3.stock_status = 'in_stock'
					  AND ${notBundle('l3')}
					  AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), @window)
					GROUP BY ps3.snapshot_date
				 ) dm) AS avg30_points
			FROM products p
			JOIN retailer_listings l ON l.product_id = p.id AND l.status = 'active'
			JOIN price_snapshots ps
			  ON ps.retailer_listing_id = l.id
			  AND ps.snapshot_date = (SELECT MAX(snapshot_date) FROM price_snapshots)
			  AND ps.stock_status = 'in_stock'
			WHERE p.tracked = 1
			  AND ${notBundle('l')}
			  AND ps.price_aud = (
				SELECT MIN(ps2.price_aud)
				FROM price_snapshots ps2
				JOIN retailer_listings l2 ON l2.id = ps2.retailer_listing_id
				WHERE l2.product_id = p.id
				  AND l2.status = 'active'
				  AND ${notBundle('l2')}
				  AND ps2.snapshot_date = ps.snapshot_date
				  AND ps2.stock_status = 'in_stock'
			  )
			GROUP BY p.id
			ORDER BY p.model COLLATE NOCASE ASC`
		)
		.all({ window: `-${days} days` }) as Array<{
		product_id: number;
		category: Category;
		model: string;
		brand: string;
		listing_id: number;
		variant_name: string | null;
		retailer: Retailer;
		listing_url: string;
		price: number;
		snapshot_date: string;
		all_time_low: number | null;
		avg30: number | null;
		avg30_points: number;
	}>;

	return rows.map((r) => ({
		productId: r.product_id,
		category: r.category,
		model: r.model,
		brand: r.brand,
		listingId: r.listing_id,
		variantName: r.variant_name,
		retailer: r.retailer,
		listingUrl: r.listing_url,
		price: r.price,
		snapshotDate: r.snapshot_date,
		allTimeLow: r.all_time_low,
		avg30: r.avg30,
		avg30Points: r.avg30_points
	}));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/repos.test.ts`
Expected: PASS, and every pre-existing `repos.test.ts` test still passes.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/server/repos.ts web/test/repos.test.ts
git commit -m "feat(deals): getDealCandidates — cheapest in-stock today + all-time low + 30d avg"
```

---

### Task 2: Deal ranking and sections (`deals.ts`)

**Files:**
- Modify: `web/src/lib/offers.ts` (widen the `facetCounts` generic bound only)
- Create: `web/src/lib/deals.ts`
- Test: `web/test/deals.test.ts`

**Interfaces:**
- Consumes: `DealCandidate` (Task 1), `MIN_HISTORY_POINTS` from `$lib/constants`, `FacetOption`/`facetCounts` from `$lib/offers`, `ListingDisplay` from `$lib/listingsPanel`.
- Produces:
  ```ts
  export const NEAR_ALL_TIME_LOW_PCT = 2;
  export interface Deal extends DealCandidate { depthPct: number | null; nearAllTimeLow: boolean; }
  export interface DealFilters { category: string | null; retailer: string | null; brand: string | null; }
  export function isEligible(c: DealCandidate): boolean
  export function dealDepthPct(price: number, avg30: number | null): number | null
  export function isNearAllTimeLow(price: number, allTimeLow: number | null): boolean
  export function toDeals(candidates: DealCandidate[]): Deal[]
  export function belowAverage(deals: Deal[]): Deal[]
  export function atAllTimeLow(deals: Deal[]): Deal[]
  export function filterDeals(deals: Deal[], filters: DealFilters): Deal[]
  export function categoryFacetCounts(deals: Deal[]): FacetOption[]
  export function dealToOffer(deal: Deal): ListingDisplay
  ```

- [ ] **Step 1: Widen `facetCounts` so `/deals` can reuse it**

In `web/src/lib/offers.ts`, change only the signature — the body is unchanged.
`ListingDisplay` still satisfies the new bound, so every existing caller and test
keeps working; `Deal` satisfies it too, which is the point.

Replace:
```ts
export function facetCounts(
	offers: ListingDisplay[],
	key: 'retailer' | 'brand'
): FacetOption[] {
```
with:
```ts
// Generic over the item so /deals reuses this instead of growing a second
// copy: any row carrying a retailer slug and a display brand can be faceted.
export function facetCounts<T extends { retailer: string; brand: string }>(
	offers: T[],
	key: 'retailer' | 'brand'
): FacetOption[] {
```

- [ ] **Step 2: Write the failing test**

Create `web/test/deals.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
	NEAR_ALL_TIME_LOW_PCT,
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	dealDepthPct,
	dealToOffer,
	filterDeals,
	isEligible,
	isNearAllTimeLow,
	toDeals
} from '../src/lib/deals';
import type { DealCandidate } from '../src/lib/server/repos';

function candidate(over: Partial<DealCandidate> = {}): DealCandidate {
	return {
		productId: 1,
		category: 'gpu',
		model: 'GeForce RTX Test',
		brand: 'NVIDIA',
		listingId: 10,
		variantName: 'ASUS RTX Test 16GB',
		retailer: 'scorptec',
		listingUrl: '/p/test',
		price: 900,
		snapshotDate: '2026-08-25',
		allTimeLow: 880,
		avg30: 1000,
		avg30Points: 10,
		...over
	};
}

describe('isEligible', () => {
	it('requires at least MIN_HISTORY_POINTS days of average', () => {
		expect(isEligible(candidate({ avg30Points: 3 }))).toBe(true);
		expect(isEligible(candidate({ avg30Points: 2 }))).toBe(false);
	});

	it('rejects a null average even with enough points', () => {
		expect(isEligible(candidate({ avg30: null, avg30Points: 10 }))).toBe(false);
	});
});

describe('dealDepthPct', () => {
	it('returns how far below the average the price sits, as a positive percent', () => {
		expect(dealDepthPct(900, 1000)).toBeCloseTo(10, 5);
	});

	it('returns a negative depth for a price above the average', () => {
		expect(dealDepthPct(1100, 1000)).toBeCloseTo(-10, 5);
	});

	it('returns null when the average is missing or zero', () => {
		expect(dealDepthPct(900, null)).toBeNull();
		expect(dealDepthPct(900, 0)).toBeNull();
	});
});

describe('isNearAllTimeLow', () => {
	it('accepts a price at the all-time low', () => {
		expect(isNearAllTimeLow(880, 880)).toBe(true);
	});

	it('accepts a price within 2% above the all-time low', () => {
		expect(isNearAllTimeLow(880 * 1.02, 880)).toBe(true);
	});

	it('rejects a price more than 2% above the all-time low', () => {
		expect(isNearAllTimeLow(880 * 1.021, 880)).toBe(false);
	});

	it('accepts a new all-time low below the recorded one', () => {
		expect(isNearAllTimeLow(800, 880)).toBe(true);
	});

	it('rejects when there is no all-time low', () => {
		expect(isNearAllTimeLow(880, null)).toBe(false);
	});

	it('pins the threshold constant at 2', () => {
		expect(NEAR_ALL_TIME_LOW_PCT).toBe(2);
	});
});

describe('toDeals / belowAverage', () => {
	it('drops ineligible candidates entirely', () => {
		const deals = toDeals([candidate({ avg30Points: 1 })]);
		expect(deals).toHaveLength(0);
	});

	it('ranks deepest discount first', () => {
		const deals = belowAverage(
			toDeals([
				candidate({ productId: 1, price: 950, avg30: 1000 }), // 5%
				candidate({ productId: 2, price: 700, avg30: 1000 }), // 30%
				candidate({ productId: 3, price: 900, avg30: 1000 }) // 10%
			])
		);
		expect(deals.map((d) => d.productId)).toEqual([2, 3, 1]);
	});

	it('excludes products at or above their average', () => {
		const deals = belowAverage(
			toDeals([
				candidate({ productId: 1, price: 1000, avg30: 1000 }),
				candidate({ productId: 2, price: 1100, avg30: 1000 })
			])
		);
		expect(deals).toHaveLength(0);
	});
});

describe('atAllTimeLow', () => {
	it('selects only the near-all-time-low deals, deepest first', () => {
		const deals = atAllTimeLow(
			toDeals([
				candidate({ productId: 1, price: 900, avg30: 1000, allTimeLow: 880 }), // >2% above
				candidate({ productId: 2, price: 880, avg30: 1000, allTimeLow: 880 }), // at low
				candidate({ productId: 3, price: 700, avg30: 1000, allTimeLow: 700 }) // at low, deeper
			])
		);
		expect(deals.map((d) => d.productId)).toEqual([3, 2]);
	});

	it('includes a product that is also below average — both claims are true', () => {
		const all = toDeals([candidate({ productId: 7, price: 700, avg30: 1000, allTimeLow: 700 })]);
		expect(belowAverage(all).map((d) => d.productId)).toEqual([7]);
		expect(atAllTimeLow(all).map((d) => d.productId)).toEqual([7]);
	});
});

describe('filterDeals', () => {
	const deals = toDeals([
		candidate({ productId: 1, category: 'gpu', retailer: 'scorptec', brand: 'NVIDIA' }),
		candidate({ productId: 2, category: 'cpu', retailer: 'pccg', brand: 'AMD' })
	]);

	it('returns everything when no facet is active', () => {
		expect(filterDeals(deals, { category: null, retailer: null, brand: null })).toHaveLength(2);
	});

	it('filters by category, retailer and brand', () => {
		expect(
			filterDeals(deals, { category: 'cpu', retailer: null, brand: null }).map((d) => d.productId)
		).toEqual([2]);
		expect(
			filterDeals(deals, { category: null, retailer: 'scorptec', brand: null }).map((d) => d.productId)
		).toEqual([1]);
		expect(
			filterDeals(deals, { category: null, retailer: null, brand: 'AMD' }).map((d) => d.productId)
		).toEqual([2]);
	});
});

describe('categoryFacetCounts', () => {
	it('labels categories for display and counts them', () => {
		const counts = categoryFacetCounts(
			toDeals([
				candidate({ productId: 1, category: 'gpu' }),
				candidate({ productId: 2, category: 'gpu' }),
				candidate({ productId: 3, category: 'cpu' })
			])
		);
		expect(counts).toEqual([
			{ value: 'gpu', label: 'GPU', count: 2 },
			{ value: 'cpu', label: 'CPU', count: 1 }
		]);
	});
});

describe('dealToOffer', () => {
	it('presents a deal as an in-stock offer row', () => {
		const [deal] = toDeals([candidate()]);
		const offer = dealToOffer(deal);
		expect(offer).toMatchObject({
			listingId: 10,
			brand: 'NVIDIA',
			retailer: 'scorptec',
			listingUrl: '/p/test',
			latestPrice: 900,
			latestStock: 'in_stock',
			inStock: true,
			delisted: false,
			lastSeen: '2026-08-25',
			selected: false
		});
	});
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run test/deals.test.ts`
Expected: FAIL — cannot resolve `../src/lib/deals`.

- [ ] **Step 4: Write the implementation**

Create `web/src/lib/deals.ts`:

```ts
// Deal ranking for /deals. Pure — no DB access — so every rule here is
// unit-testable. Answers two different questions that must not be blended:
// "is this cheap versus its own recent history" (below the 30-day average)
// and "is this cheap versus all history" (at or near the all-time low).
import { MIN_HISTORY_POINTS } from './constants';
import { CATEGORY_OPTIONS } from './filters';
import type { FacetOption } from './offers';
import type { ListingDisplay } from './listingsPanel';
import type { DealCandidate } from './server/repos';

export type { DealCandidate };

// "Near" the all-time low, per the spec. A stronger claim than below-average,
// so it gets its own section rather than being folded into one score.
export const NEAR_ALL_TIME_LOW_PCT = 2;

export interface Deal extends DealCandidate {
	// Percent below the 30-day average. Positive = cheaper than average.
	depthPct: number | null;
	nearAllTimeLow: boolean;
}

export interface DealFilters {
	category: string | null;
	retailer: string | null;
	brand: string | null;
}

// A three-day average is not an average. Gating on it keeps a product that has
// barely been tracked from being presented as a bargain — and the same depth
// requirement guards the all-time-low claim, which is no more meaningful over
// three days than the average is.
export function isEligible(c: DealCandidate): boolean {
	return c.avg30 !== null && c.avg30 !== 0 && c.avg30Points >= MIN_HISTORY_POINTS;
}

// Positive means below the average. Note the sign is inverted relative to
// offers.deltaVsAvg30, which is a *delta* (negative = cheaper); this is a
// *depth* (positive = cheaper) because it is a ranking key, and ranking
// "deepest first" reads backwards on a negative scale.
export function dealDepthPct(price: number, avg30: number | null): number | null {
	if (avg30 === null || avg30 === 0) return null;
	return ((avg30 - price) / avg30) * 100;
}

export function isNearAllTimeLow(price: number, allTimeLow: number | null): boolean {
	if (allTimeLow === null || allTimeLow === 0) return false;
	return price <= allTimeLow * (1 + NEAR_ALL_TIME_LOW_PCT / 100);
}

export function toDeals(candidates: DealCandidate[]): Deal[] {
	return candidates.filter(isEligible).map((c) => ({
		...c,
		depthPct: dealDepthPct(c.price, c.avg30),
		nearAllTimeLow: isNearAllTimeLow(c.price, c.allTimeLow)
	}));
}

function byDepthDesc(a: Deal, b: Deal): number {
	return (b.depthPct ?? 0) - (a.depthPct ?? 0) || a.model.localeCompare(b.model);
}

export function belowAverage(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.depthPct !== null && d.depthPct > 0).sort(byDepthDesc);
}

export function atAllTimeLow(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.nearAllTimeLow).sort(byDepthDesc);
}

export function filterDeals(deals: Deal[], filters: DealFilters): Deal[] {
	return deals.filter((d) => {
		if (filters.category && d.category !== filters.category) return false;
		if (filters.retailer && d.retailer !== filters.retailer) return false;
		if (filters.brand && d.brand !== filters.brand) return false;
		return true;
	});
}

const CATEGORY_LABELS = new Map(CATEGORY_OPTIONS.map((o) => [o.value as string, o.label]));

export function categoryFacetCounts(deals: Deal[]): FacetOption[] {
	const counts = new Map<string, number>();
	for (const d of deals) counts.set(d.category, (counts.get(d.category) ?? 0) + 1);
	return [...counts.entries()]
		.map(([value, count]) => ({ value, label: CATEGORY_LABELS.get(value) ?? value, count }))
		.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

// Adapts a product-level deal to the listing-shaped row OfferRow renders. The
// candidate query only ever returns a listing that is in stock on the latest
// snapshot date, so the stock fields are known-good rather than assumed.
export function dealToOffer(deal: Deal): ListingDisplay {
	return {
		listingId: deal.listingId,
		brand: deal.brand,
		variantName: deal.variantName,
		retailer: deal.retailer,
		listingUrl: deal.listingUrl,
		latestPrice: deal.price,
		latestStock: 'in_stock',
		delisted: false,
		inStock: true,
		firstSeen: null,
		lastSeen: deal.snapshotDate,
		selected: false
	};
}
```

> **Verified:** `CATEGORY_OPTIONS` in `web/src/lib/filters.ts` labels these
> `CPU` and `GPU` (not `CPUs`/`GPUs`). The test above expects those exact labels.
> Do not change the constant — `/products` already renders it.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run test/deals.test.ts test/offers.test.ts`
Expected: PASS — including every pre-existing `offers.test.ts` test, which
proves the widened `facetCounts` bound is backward compatible.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/deals.ts web/test/deals.test.ts web/src/lib/offers.ts
git commit -m "feat(deals): depth ranking, all-time-low section and facet logic"
```

---

### Task 3: `OfferRow` serves product-level rows

**Files:**
- Modify: `web/src/lib/components/OfferRow.svelte`
- Test: `web/test/components.test.ts`

**Interfaces:**
- Consumes: the existing `OfferRow` props (`offer`, `avg30`, `onToggleChart`).
- Produces: two additive optional props. Existing call sites are untouched.
  ```ts
  titleOverride?: string;   // replaces the variant-name title
  detailHref?: string;      // renders the title as an internal link
  ```

- [ ] **Step 1: Write the failing test**

Add to `web/test/components.test.ts`, following the file's existing
render helper for Svelte components:

```ts
describe('OfferRow product-level overrides', () => {
    const offer = {
        listingId: 10, brand: 'NVIDIA', variantName: 'ASUS RTX Test 16GB',
        retailer: 'scorptec', listingUrl: 'https://example.test/p',
        latestPrice: 900, latestStock: 'in_stock' as const, delisted: false,
        inStock: true, firstSeen: null, lastSeen: '2026-08-25', selected: false
    };

    it('uses the variant name as the title by default', () => {
        const { container } = render(OfferRow, { offer, avg30: 1000 });
        expect(container.textContent).toContain('ASUS RTX Test 16GB');
    });

    it('renders titleOverride instead of the variant name', () => {
        const { container } = render(OfferRow, {
            offer, avg30: 1000, titleOverride: 'GeForce RTX Test'
        });
        expect(container.textContent).toContain('GeForce RTX Test');
        expect(container.textContent).not.toContain('ASUS RTX Test 16GB');
    });

    it('links the title to detailHref when given', () => {
        const { container } = render(OfferRow, {
            offer, avg30: 1000, titleOverride: 'GeForce RTX Test', detailHref: '/product/5'
        });
        const link = container.querySelector('a[href="/product/5"]');
        expect(link).not.toBeNull();
        expect(link?.textContent).toContain('GeForce RTX Test');
    });

    it('keeps the retailer link separate from the detail link', () => {
        const { container } = render(OfferRow, {
            offer, avg30: 1000, titleOverride: 'GeForce RTX Test', detailHref: '/product/5'
        });
        expect(container.querySelector('a[href="https://example.test/p"]')).not.toBeNull();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run test/components.test.ts -t "OfferRow product-level overrides"`
Expected: FAIL — the override title is not rendered and no `/product/5` link exists.

- [ ] **Step 3: Write the implementation**

In `web/src/lib/components/OfferRow.svelte`, extend the props block:

```svelte
	let {
		offer,
		avg30,
		onToggleChart,
		titleOverride,
		detailHref
	}: {
		offer: ListingDisplay;
		avg30: number | null;
		onToggleChart?: (listingId: number) => void;
		// /deals renders one row per product, so the row shows the model name
		// and links to the product page. The product page passes neither and
		// keeps the variant-name title with only the outbound retailer link.
		titleOverride?: string;
		detailHref?: string;
	} = $props();
```

Change the derived title to prefer the override:

```svelte
	const title = $derived(
		titleOverride ?? (titleCase(offer.variantName) || `${retailerLabel} listing`)
	);
```

Replace the title `<span>` block (the `order-2` div's first child) with:

```svelte
		{#if detailHref}
			<a
				href={detailHref}
				class="block truncate text-sm font-medium text-text no-underline hover:underline"
				title={title}>{title}</a
			>
		{:else}
			<span class="block truncate text-sm font-medium text-text" title={title}>{title}</span>
		{/if}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run test/components.test.ts`
Expected: PASS, including every pre-existing `OfferRow` test.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/components/OfferRow.svelte web/test/components.test.ts
git commit -m "feat(deals): OfferRow accepts a product-level title and detail link"
```

---

### Task 4: The `/deals` route

**Files:**
- Create: `web/src/routes/deals/+page.server.ts`
- Create: `web/src/routes/deals/+page.svelte`

**Interfaces:**
- Consumes: `getDealCandidates` (Task 1); every export of `deals.ts` (Task 2); `OfferRow`'s `titleOverride`/`detailHref` (Task 3); the existing `FacetChips` component.
- Produces: the `/deals` route. Load returns:
  ```ts
  {
      belowAverage: Deal[];
      atAllTimeLow: Deal[];
      filters: DealFilters;
      facets: { category: FacetOption[]; retailer: FacetOption[]; brand: FacetOption[] };
      totals: { category: number; retailer: number; brand: number };
      eligibleCount: number;
  }
  ```

**Facet-count rule (carried over from stage 1):** each axis's counts are computed
over the deals filtered by *the other* active axes, never by its own. A chip's
count must equal the number of rows clicking it produces — the stage-1 bug
fixed in `df421bd` was exactly this.

- [ ] **Step 1: Write the failing E2E-facing route (server load)**

Create `web/src/routes/deals/+page.server.ts`:

```ts
import { getDealCandidates } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import {
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	filterDeals,
	toDeals,
	type DealFilters
} from '$lib/deals';
import { facetCounts } from '$lib/offers';

function param(url: URL, key: string): string | null {
	const value = url.searchParams.get(key);
	return value && value.trim() !== '' ? value : null;
}

export function load({ url }: { url: URL }) {
	const db = getDb();
	const deals = toDeals(getDealCandidates(db));

	const filters: DealFilters = {
		category: param(url, 'category'),
		retailer: param(url, 'retailer'),
		brand: param(url, 'brand')
	};

	// Each axis is counted over the set filtered by the OTHER axes, so a
	// chip's count always equals the number of rows clicking it produces.
	const forCategory = filterDeals(deals, { ...filters, category: null });
	const forRetailer = filterDeals(deals, { ...filters, retailer: null });
	const forBrand = filterDeals(deals, { ...filters, brand: null });

	const visible = filterDeals(deals, filters);

	return {
		belowAverage: belowAverage(visible),
		atAllTimeLow: atAllTimeLow(visible),
		filters,
		facets: {
			category: categoryFacetCounts(forCategory),
			retailer: facetCounts(forRetailer, 'retailer'),
			brand: facetCounts(forBrand, 'brand')
		},
		totals: {
			category: forCategory.length,
			retailer: forRetailer.length,
			brand: forBrand.length
		},
		eligibleCount: deals.length
	};
}
```

- [ ] **Step 2: Write the page**

Create `web/src/routes/deals/+page.svelte`:

```svelte
<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import FacetChips from '$lib/components/FacetChips.svelte';
	import OfferRow from '$lib/components/OfferRow.svelte';
	import { dealToOffer, NEAR_ALL_TIME_LOW_PCT, type Deal } from '$lib/deals';

	let { data } = $props();

	// URL-driven, unlike the product page's client-side chips: /deals is a
	// server-rendered list, so a facet change is a navigation. Same
	// presentational component, different driver — see spec §7.
	function select(key: 'category' | 'retailer' | 'brand', value: string | null) {
		const params = new URLSearchParams(page.url.searchParams);
		if (value === null) params.delete(key);
		else params.set(key, value);
		const qs = params.toString();
		goto(qs ? `/deals?${qs}` : '/deals', { keepFocus: true, noScroll: true });
	}

	const resultCount = $derived(data.belowAverage.length);
</script>

<svelte:head><title>Deals · Trackaroo</title></svelte:head>

<div class="mx-auto max-w-6xl px-4 py-6">
	<h1 class="text-xl font-semibold tracking-tight text-text">Deals</h1>
	<p class="mt-1 text-sm text-text-muted">
		Products whose cheapest in-stock price is below their own 30-day average.
	</p>

	<div class="mt-4 flex flex-col gap-2">
		<FacetChips
			label="Category"
			options={data.facets.category}
			selected={data.filters.category}
			allCount={data.totals.category}
			onSelect={(v) => select('category', v)}
		/>
		<FacetChips
			label="Retailer"
			options={data.facets.retailer}
			selected={data.filters.retailer}
			allCount={data.totals.retailer}
			onSelect={(v) => select('retailer', v)}
		/>
		<FacetChips
			label="Brand"
			options={data.facets.brand}
			selected={data.filters.brand}
			allCount={data.totals.brand}
			onSelect={(v) => select('brand', v)}
		/>
	</div>

	<p class="mt-3 text-xs text-text-muted" aria-live="polite" data-testid="deals-count">
		{resultCount}
		{resultCount === 1 ? 'product' : 'products'} below the 30-day average
	</p>

	<section class="mt-4" aria-labelledby="below-average-heading">
		<h2 id="below-average-heading" class="text-sm font-semibold text-text">
			Below 30-day average
		</h2>
		{#if data.belowAverage.length > 0}
			<div class="mt-2 divide-y divide-border rounded-lg border border-border bg-surface" data-testid="below-average-list">
				{#each data.belowAverage as deal (deal.productId)}
					<OfferRow
						offer={dealToOffer(deal)}
						avg30={deal.avg30}
						titleOverride={deal.model}
						detailHref={`/product/${deal.productId}`}
					/>
				{/each}
			</div>
		{:else}
			<p class="mt-2 rounded-lg border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted">
				No products are below their 30-day average today.
			</p>
		{/if}
	</section>

	<section class="mt-8 scroll-mt-4" id="all-time-low" aria-labelledby="all-time-low-heading">
		<h2 id="all-time-low-heading" class="text-sm font-semibold text-text">
			At or near all-time low
		</h2>
		<p class="mt-0.5 text-xs text-text-muted">
			Within {NEAR_ALL_TIME_LOW_PCT}% of the lowest price ever recorded.
		</p>
		{#if data.atAllTimeLow.length > 0}
			<div class="mt-2 divide-y divide-border rounded-lg border border-border bg-surface" data-testid="all-time-low-list">
				{#each data.atAllTimeLow as deal (deal.productId)}
					<OfferRow
						offer={dealToOffer(deal)}
						avg30={deal.avg30}
						titleOverride={deal.model}
						detailHref={`/product/${deal.productId}`}
					/>
				{/each}
			</div>
		{:else}
			<p class="mt-2 rounded-lg border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted">
				No products are within {NEAR_ALL_TIME_LOW_PCT}% of their all-time low today.
			</p>
		{/if}
	</section>
</div>
```

- [ ] **Step 3: Verify types and the production build**

Run: `cd web && npm run check`
Expected: 0 errors (the pre-existing `CheapestCarousel` a11y **warning** is
allowed; errors are not).

- [ ] **Step 4: Verify the page renders against the real DB**

Run: `cd web && npm run dev` then open `http://localhost:5173/deals`.
Expected: the two sections render; clicking a chip changes the URL and the list.
Stop the dev server afterwards.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/deals
git commit -m "feat(deals): /deals route with below-average and all-time-low sections"
```

---

### Task 5: E2E fixtures, coverage, docs and full validation

**Files:**
- Modify: `web/e2e/seed.mjs`
- Modify: `web/e2e/app.spec.ts`
- Modify: `STATUS.md`, `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: the `/deals` route (Task 4) and the `data-testid` hooks it renders
  (`deals-count`, `below-average-list`, `all-time-low-list`).
- Produces: deterministic deal fixtures in the seeded DB.

- [ ] **Step 1: Add the deterministic deal fixtures to the seed**

In `web/e2e/seed.mjs`, insert immediately after the existing delisted-listing
fixture block (right before the `// Deterministic spec rows …` comment):

```js
	// Deterministic /deals fixtures. The seed builds from the live data/
	// directory when it has files, so real scraped prices cannot be asserted
	// on. These two products are synthetic and pinned:
	//
	//   E2E Deal Demo GPU  — today's price is 90% below its 30-day average and
	//     equal to its all-time low, so it must rank FIRST in both sections.
	//     Real hardware does not swing 90% in a month, which is what makes the
	//     ordering assertion safe against live data.
	//   E2E Thin History GPU — 40% below its 2-day average, but only 2 days of
	//     history, so MIN_HISTORY_POINTS must exclude it from both sections.
	//
	// Snapshots are anchored to the DB's own latest date so the fixtures are
	// always "today" regardless of which scrape files were loaded.
	const latest = db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get();
	if (latest && latest.d) {
		const dayBefore = (n) =>
			db.prepare("SELECT date(?, ?) AS d").get(latest.d, `-${n} days`).d;

		const addFixture = (model, url, history) => {
			const productInfo = db
				.prepare(
					`INSERT INTO products (category, brand, model, generation_tier, tracked)
					 VALUES ('gpu', 'NVIDIA', ?, 'current', 1)`
				)
				.run(model);
			const listingInfo = db
				.prepare(
					`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
					 VALUES (?, 'scorptec', ?, ?, 'active')`
				)
				.run(Number(productInfo.lastInsertRowid), `${model} Variant`, url);
			const listingId = Number(listingInfo.lastInsertRowid);
			for (const [daysAgo, price] of history) {
				db.prepare(
					`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
					 VALUES (?, ?, ?, 'in_stock', ?)`
				).run(listingId, dayBefore(daysAgo), price, `${dayBefore(daysAgo)}T04:00:00.000Z`);
			}
		};

		// [daysAgo, price] — day 0 is the latest snapshot date.
		addFixture('E2E Deal Demo GPU', '/p/e2e-deal-demo', [
			[4, 1000], [3, 1000], [2, 1000], [1, 1000], [0, 100]
		]);
		addFixture('E2E Thin History GPU', '/p/e2e-thin-history', [
			[1, 1000], [0, 600]
		]);
	}
```

- [ ] **Step 2: Write the failing E2E tests**

Add to `web/e2e/app.spec.ts`, using the file's local `goto()` helper:

```ts
test.describe('deals', () => {
	test('ranks the deepest discount first and links to the product page', async ({ page }) => {
		await goto(page, '/deals');
		const rows = page.getByTestId('below-average-list').locator('a[href^="/product/"]');
		await expect(rows.first()).toHaveText('E2E Deal Demo GPU');
	});

	test('lists an at-all-time-low product in its own anchored section', async ({ page }) => {
		await goto(page, '/deals');
		const section = page.locator('#all-time-low');
		await expect(section).toBeVisible();
		await expect(section.getByText('E2E Deal Demo GPU')).toBeVisible();
	});

	test('excludes products without enough history to have an average', async ({ page }) => {
		await goto(page, '/deals');
		await expect(page.getByText('E2E Thin History GPU')).toHaveCount(0);
	});

	test('filtering by retailer narrows the list and survives a reload', async ({ page }) => {
		await goto(page, '/deals');
		await page.getByRole('button', { name: /^PCCG/ }).click();
		await expect(page).toHaveURL(/retailer=pccg/);
		await expect(page.getByTestId('below-average-list').getByText('E2E Deal Demo GPU')).toHaveCount(0);
	});

	test('filtering by category to CPUs hides the GPU fixture', async ({ page }) => {
		await goto(page, '/deals?category=cpu');
		await expect(page.getByText('E2E Deal Demo GPU')).toHaveCount(0);
	});
});
```

- [ ] **Step 3: Run the E2E tests to verify they fail, then pass**

Run: `cd web && npm run test:e2e -- -g deals`
Expected before Task 4 is wired: FAIL. With Tasks 1–4 done and the seed updated: PASS.

> The seed runs via `webServer.command` before the dev server, so `e2e.db` is
> rebuilt on each run — no manual cleanup needed.

- [ ] **Step 4: Full validation**

Run, in order:

```bash
python -m pytest -q            # from the repo root
cd web && npm run check        # 0 errors
npm test
npm run test:e2e
npm run build
```

Expected: pytest 611 passed; svelte-check 0 errors; vitest and Playwright both
green with the new tests included; production build succeeds.

- [ ] **Step 5: Update the documentation**

In `STATUS.md`:
- Bump `**Last updated:**` to the current date.
- Add a dated bullet at the top of **Recent changes** (do **not** start a nested
  "Prior update" chain — see the history note at the top of the file) recording:
  `/deals` shipped as stage 2 of the price-first IA spec; the two sections and
  why they are separate; the `MIN_HISTORY_POINTS` eligibility gate covering both;
  the new `getDealCandidates` query; and the final regression counts.
- Update the **Regression test count** table with the new vitest and Playwright
  totals, and the `Current, as of …` line.
- Add `/deals` to the Routes line in the `web/` entry under **What exists right now**.

In `docs/ARCHITECTURE.md`: add a decision-log entry (Part 3) recording that
"below 30-day average" and "at/near all-time low" are deliberately kept as two
sections rather than one blended score, and that 2% defines "near".

- [ ] **Step 6: Commit**

```bash
git add web/e2e/seed.mjs web/e2e/app.spec.ts STATUS.md docs/ARCHITECTURE.md
git commit -m "test(deals): deterministic deal fixtures + e2e coverage; docs"
```

---

## Self-Review

**1. Spec coverage (§4):**

| §4 requirement | Task |
|---|---|
| One offer row per product | Task 1 (one row per product), Tasks 3–4 (row reuse) |
| Ranked by `(avg30 − price) / avg30`, deepest first | Task 2 (`dealDepthPct`, `byDepthDesc`) |
| Section: below 30-day average | Task 2 (`belowAverage`), Task 4 |
| Section: at/near all-time low, anchored `#all-time-low` | Task 2 (`atAllTimeLow`), Task 4 (`id="all-time-low"`) |
| "Near" = within 2% | Task 2 (`NEAR_ALL_TIME_LOW_PCT`) |
| A product may appear in both sections | Task 2 (explicit test) |
| Category, retailer, brand facets reuse the §2 chips | Task 2 (`categoryFacetCounts`, widened `facetCounts`), Task 4 (`FacetChips`) |
| `avg30Points >= MIN_HISTORY_POINTS` eligibility | Task 2 (`isEligible`), Task 5 (E2E exclusion test) |
| Empty state gets real copy | Task 4 (both sections) |
| §9 testing: pure logic in Vitest, E2E ranking, `goto()` helper, <60s | Tasks 2, 3, 5 |

**Deliberately out of this stage:** the `Deals` nav link (§6, stage 4) and the
stale-retailer fixture (§9) — that fixture serves the homepage health strip,
which is stage 3. Cross-retailer variant matching stays out of scope entirely.

**2. Placeholder scan:** no TBD/TODO steps; every code step carries the literal
code. Two steps carry a deliberate *verification* instruction rather than fixed
text — the `CATEGORY_OPTIONS` label check in Task 2 and the fixture-helper naming
check in Task 1 — because both depend on existing code the executor can read.

**3. Type consistency:** `DealCandidate` field names are identical in Task 1
(producer) and Task 2 (consumer). `Deal extends DealCandidate` adds only
`depthPct` and `nearAllTimeLow`. `dealToOffer` returns exactly the twelve fields
`ListingDisplay` declares in `listingsPanel.ts`. `FacetOption` (`value`/`label`/
`count`) is used unchanged from `offers.ts`, matching what `FacetChips` expects.
`filterDeals` takes `DealFilters` with the same three nullable string fields the
route parses from the URL.
