import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { createSeededDb, type SeededDb } from './helpers/seed';

// getDb() caches its connection in module scope (src/lib/server/db.ts), so
// TRACKAROO_DB must be set before anything first calls it. The loaders below
// are imported dynamically inside each test, after this env var is set, so
// their first getDb() call resolves to the seeded file.
let seeded: SeededDb;

beforeAll(() => {
	seeded = createSeededDb();
	process.env.TRACKAROO_DB = seeded.file;
});

afterAll(async () => {
	// The loaders call getDb(), which opens its own connection to the seeded
	// file and caches it at module scope (db.ts has no reset/close export).
	// On Windows that handle outlives seeded.close()'s db.close() (a
	// different connection object) and blocks the temp dir's rmSync with
	// EPERM, so close it explicitly first.
	const { getDb } = await import('../src/lib/server/db');
	try {
		getDb().close();
	} catch {
		// Never opened (e.g. the /products test threw before reaching getDb) —
		// nothing to close.
	}
	seeded.close();
});

// No-op stand-in for SvelteKit's setHeaders, which the loaders now accept to
// set a short browser cache on list pages (#28). The loaders below call it
// directly (not through the framework), so a real request/response cycle
// never happens here and there is nothing to assert about it.
function noopSetHeaders() {
	// intentionally empty
}

describe('/products payload (#28)', () => {
	it('groups carry no per-listing arrays', async () => {
		const { load } = await import('../src/routes/products/+page.server');
		const data = load({
			url: new URL('http://x/products?category=gpu'),
			setHeaders: noopSetHeaders
		} as any);
		for (const g of data.groups) expect(g).not.toHaveProperty('listings');
	});
});

describe('/movers payload (M1 -- single memo entry for all+movers+sparklines)', () => {
	it('every returned mover has sparkline data computed from the same data_version as the listing set', async () => {
		const { load } = await import('../src/routes/movers/+page.server');
		const { getDb } = await import('../src/lib/server/db');
		const { getSparklines } = await import('../src/lib/server/repos');
		const data = load({
			url: new URL('http://x/movers?window=7d'),
			setHeaders: noopSetHeaders
		} as any);
		// Independently recompute sparklines for the exact listing set the
		// loader returned and compare -- if `all`/`movers` and `sparklines`
		// were ever memoised in separate calls that straddled a data_version
		// change, this would catch a mismatch between the two.
		const db = getDb();
		const expected = getSparklines(
			db,
			data.movers.map((m) => m.listingId),
			7
		);
		for (const m of data.movers) {
			expect(m.sparkline).toEqual(
				(expected.get(m.listingId) ?? []).map((p) => ({ date: p.date, price: p.price }))
			);
		}
	});

	it('reflects a pipeline commit made between requests for both the listing set and its sparklines together', async () => {
		const { load } = await import('../src/routes/movers/+page.server');

		// Baseline load, then a second connection commits a new snapshot for
		// an existing listing -- simulating the pipeline write that used to
		// land between the two separate memo() calls.
		const before = load({
			url: new URL('http://x/movers?window=7d&all=1'),
			setHeaders: noopSetHeaders
		} as any);
		const target = before.movers[0];
		expect(target).toBeTruthy();

		const newDate = '2099-01-01';
		const newPrice = Math.round((target.newPrice ?? 100) * 1.5) + 1;
		const w = new Database(seeded.file);
		try {
			w.prepare(
				`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
				 VALUES (?, ?, ?, 'in_stock', ?)`
			).run(target.listingId, newDate, newPrice, `${newDate}T04:00:00.000Z`);
		} finally {
			w.close();
		}

		const after = load({
			url: new URL('http://x/movers?window=7d&all=1'),
			setHeaders: noopSetHeaders
		} as any);
		const updated = after.movers.find((m) => m.listingId === target.listingId);
		expect(updated).toBeTruthy();
		// The new snapshot must show up both in the recomputed listing (new
		// price) and its sparkline -- not just one of the two, which is what
		// the two-memo-call race could produce.
		expect(updated!.newPrice).toBe(newPrice);
		expect(updated!.sparkline.some((p) => p.date === newDate && p.price === newPrice)).toBe(true);
	});
});

describe('homepage (#28)', () => {
	it('cheapestPrice equals the cheapest deal candidate in each category', async () => {
		const { load } = await import('../src/routes/+page.server');
		const { getDealCandidates, getHeaderStats } = await import('../src/lib/server/repos');
		const { getDb } = await import('../src/lib/server/db');
		// Realistic parent(): +layout.server.ts always resolves to
		// { stats: getHeaderStats(db), productIndex: ... }, so exercise the load
		// against that real shape rather than an empty stub.
		const data = await load({
			parent: async () => ({ stats: getHeaderStats(getDb()) }),
			setHeaders: noopSetHeaders
		} as any);
		for (const s of data.sections) {
			const prices = getDealCandidates(getDb())
				.filter((c) => c.category === s.category)
				.map((c) => c.price);
			expect(s.cheapestPrice).toBe(prices.length ? Math.min(...prices) : null);
		}
	});
});
