import { afterAll, beforeAll, describe, expect, it } from 'vitest';
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
