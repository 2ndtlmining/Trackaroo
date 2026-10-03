import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { createSeededDb, type SeededDb } from './helpers/seed';
import { BUDGETS } from '$lib/value';

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

describe('/compare loader (#26)', () => {
	it('opens the picker on the requested category with nothing selected', async () => {
		const { load } = await import('../src/routes/compare/+page.server');
		expect(load({ url: new URL('http://x/compare?category=cpu') } as any)).toEqual({
			entries: [],
			pickerCategory: 'cpu',
			pickerError: null
		});
	});

	it('asks again, rather than failing, when the picker names one product twice (Review Focus 3)', async () => {
		const { load } = await import('../src/routes/compare/+page.server');
		const data = load({ url: new URL('http://x/compare?id=5&id=5') } as any);
		expect(data.entries).toEqual([]);
		expect(data.pickerError).toMatch(/two different products/);
	});

	it('accepts the picker’s repeated id parameters', async () => {
		const { load } = await import('../src/routes/compare/+page.server');
		const { getDb } = await import('../src/lib/server/db');
		const ids = (
			getDb().prepare("SELECT id FROM products WHERE category = 'gpu' ORDER BY id LIMIT 2").all() as Array<{ id: number }>
		).map((r) => r.id);
		const data = load({ url: new URL(`http://x/compare?id=${ids[0]}&id=${ids[1]}`) } as any);
		expect(data.entries.map((e) => e.product.id)).toEqual(ids);
	});
});

describe('/value loader (#33)', () => {
	async function loadValue(qs: string) {
		const { load } = await import('../src/routes/value/+page.server');
		return load({ url: new URL(`http://x/value${qs}`), setHeaders: noopSetHeaders } as any);
	}

	it('defaults to GPUs and raster, on the wide layout', async () => {
		const data = await loadValue('');
		expect(data.wide).toBe(true);
		expect(data.category).toBe('gpu');
		expect(data.metric).toBe('gpu_raster_1440p');
		expect(data.metrics).toEqual(['gpu_raster_1440p', 'gpu_rt_1440p']);
		expect(data.metricInfo.label).toBe('1440p raster');
		expect(data.exclude8gb).toBe(false);
		// Shown only when an 8 GB card could sit in a budget card.
		expect(data.show8gbToggle).toBe(
			data.points.some((p) => p.vramGb != null && p.vramGb <= 8 && p.price <= BUDGETS.at(-1)!)
		);
	});

	it('plots only priced points, with a frontier drawn from them and five budgets', async () => {
		const data = await loadValue('?category=cpu');
		expect(data.category).toBe('cpu');
		expect(data.metric).toBe('cpu_gaming_1080p');
		for (const p of data.points) {
			expect(p.price).toBeGreaterThan(0);
			expect(p.perf).toBeGreaterThan(0);
			expect(p.perKilo).toBeCloseTo((p.perf / p.price) * 1000);
		}
		const ids = new Set(data.points.map((p) => p.id));
		for (const id of data.frontier) expect(ids.has(id)).toBe(true);
		if (data.points.length > 0) expect(data.frontier.length).toBeGreaterThan(0);
		expect(data.budgets.map((b) => b.max)).toEqual([400, 700, 1000, 1500, 2500]);
		expect(data.excluded).toBe(data.coverage.noPrice);
		expect(data.coverage.withPerfAndPrice).toBe(data.points.length);
	});

	it('ignores a foreign metric and no8gb outside GPUs', async () => {
		const data = await loadValue('?category=cpu&metric=gpu_rt_1440p&no8gb=1');
		expect(data.metric).toBe('cpu_gaming_1080p');
		expect(data.metrics).toEqual(['cpu_gaming_1080p']);
		expect(data.exclude8gb).toBe(false);
		expect(data.show8gbToggle).toBe(false);
	});

	it('reads the GPU metric and the 8 GB toggle from the URL', async () => {
		const data = await loadValue('?category=gpu&metric=gpu_rt_1440p&no8gb=1');
		expect(data.metric).toBe('gpu_rt_1440p');
		expect(data.exclude8gb).toBe(true);
		// On, so it stays visible and can be turned off.
		expect(data.show8gbToggle).toBe(true);
		for (const b of data.budgets) {
			for (const p of [b.winner, b.runnerUp]) if (p) expect(p.vramGb == null || p.vramGb > 8).toBe(true);
		}
	});
});

describe('/products catalog fields (#23)', () => {
	it('every row carries the columns the table renders', async () => {
		const { load } = await import('../src/routes/products/+page.server');
		const data = load({ url: new URL('http://x/products?category=gpu'), setHeaders: noopSetHeaders } as any);
		for (const g of data.groups) {
			expect(g).toHaveProperty('vramGb');
			expect(g).toHaveProperty('launchDate');
			expect(typeof g.listingCount).toBe('number');
			if (g.neverListed) expect(g.listingCount).toBe(0);
		}
	});
});

describe('/products range90 (#22)', () => {
	it('every row carries range90: low <= high, or null without history', async () => {
		const { load } = await import('../src/routes/products/+page.server');
		const data = load({ url: new URL('http://x/products?category=gpu'), setHeaders: noopSetHeaders } as any);
		let withRange = 0;
		for (const g of data.groups as any[]) {
			expect(g).toHaveProperty('range90');
			if (g.range90 === null) continue;
			withRange++;
			expect(g.range90.low).toBeGreaterThan(0);
			expect(g.range90.low).toBeLessThanOrEqual(g.range90.high);
		}
		expect(withRange).toBeGreaterThan(0);
		const never = (data.groups as any[]).filter((g) => g.neverListed);
		for (const g of never) expect(g.range90).toBeNull();
	});
});

describe('/products catalogue controls data (#23)', () => {
	async function run(q: string) {
		const { load } = await import('../src/routes/products/+page.server');
		return load({ url: new URL(`http://x/products?${q}`), setHeaders: noopSetHeaders } as any);
	}

	it('retailerPrices: any <= inStock per retailer, for both inStock values', async () => {
		for (const q of ['category=gpu', 'category=gpu&in_stock=1', 'category=cpu']) {
			const data = await run(q);
			for (const g of data.groups as any[]) {
				expect(g.retailerPrices).toBeTypeOf('object');
				for (const rp of Object.values(g.retailerPrices) as any[]) {
					if (rp.inStock !== null) expect(rp.any).toBeLessThanOrEqual(rp.inStock);
				}
			}
		}
	});

	it('retailerPrices.any survives the in-stock filter', async () => {
		const all = (await run('category=gpu')).groups as any[];
		const only = (await run('category=gpu&in_stock=1')).groups as any[];
		for (const g of only) {
			const twin = all.find((x) => x.productId === g.productId);
			expect(g.retailerPrices).toEqual(twin.retailerPrices);
			expect(g.listingCount).toBe(twin.listingCount);
		}
	});

	it('CPU rows carry socket/threads keys, GPU rows have them null', async () => {
		const cpu = (await run('category=cpu')).groups as any[];
		for (const g of cpu) {
			expect(g).toHaveProperty('socket');
			expect(g).toHaveProperty('threads');
		}
		// The seed gives the Core Ultra 5 245 real CPU specs (test/helpers/seed.ts).
		const seededCpu = cpu.find((g) => g.socket !== null && g.threads !== null);
		expect(seededCpu).toMatchObject({ socket: 'LGA1851', threads: 10 });
		for (const g of (await run('category=gpu')).groups as any[]) {
			expect(g.socket).toBeNull();
			expect(g.threads).toBeNull();
		}
	});

	it('releaseYear matches launchDate; sparkline is at most 30 positive prices', async () => {
		for (const cat of ['gpu', 'cpu']) {
			for (const g of (await run(`category=${cat}`)).groups as any[]) {
				expect(g.releaseYear).toBe(g.launchDate ? Number(g.launchDate.slice(0, 4)) : null);
				expect(g.sparkline.length).toBeLessThanOrEqual(30);
				for (const p of g.sparkline) expect(p).toBeGreaterThan(0);
			}
		}
	});

	it('gpu groups payload stays under 40 KB', async () => {
		const data = await run('category=gpu');
		const size = JSON.stringify(data.groups).length;
		expect(size).toBeLessThan(40 * 1024);
	});
});

describe('MSRP data (#32)', () => {
	it('/products rows carry msrpUsd and fx is null without a rate', async () => {
		const { load } = await import('../src/routes/products/+page.server');
		const data = load({ url: new URL('http://x/products?category=gpu'), setHeaders: noopSetHeaders } as any);
		expect(data.fx).toBeNull();
		for (const g of data.groups as any[]) expect(g).toHaveProperty('msrpUsd');
	});

	it('/deals returns fx and msrpUsd per row', async () => {
		const { load } = await import('../src/routes/deals/+page.server');
		const data = load({ url: new URL('http://x/deals'), setHeaders: noopSetHeaders } as any);
		expect(data.fx).toBeNull();
		for (const d of [...data.belowAverage, ...data.atAllTimeLow]) expect(d).toHaveProperty('msrpUsd');
	});

	it('/deals?below_msrp=1 is ignored without a rate (the toggle is hidden then)', async () => {
		const { load } = await import('../src/routes/deals/+page.server');
		const all = load({ url: new URL('http://x/deals'), setHeaders: noopSetHeaders } as any);
		expect(all.belowMsrp).toBe(false);
		const data = load({ url: new URL('http://x/deals?below_msrp=1'), setHeaders: noopSetHeaders } as any);
		expect(data.belowMsrp).toBe(false);
		expect(data.totals.category).toBe(all.totals.category);
		expect(data.eligibleCount).toBe(all.eligibleCount);
	});

	it('/product/[id] returns fx and msrpUsd', async () => {
		const { load } = await import('../src/routes/product/[id]/+page.server');
		const { getDb } = await import('../src/lib/server/db');
		const id = (getDb().prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY id LIMIT 1').get() as { id: number }).id;
		const data = load({ params: { id: String(id) } } as any);
		expect(data.fx).toBeNull();
		expect(data).toHaveProperty('msrpUsd');
		expect(data.today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
	});

	it('getLaunchMsrps reads positive MSRPs per category', async () => {
		const { getLaunchMsrps } = await import('../src/lib/server/repos');
		const db = new Database(':memory:');
		db.exec(`CREATE TABLE specs (product_id INTEGER, category TEXT, launch_msrp_usd REAL);
			INSERT INTO specs VALUES (1,'gpu',999),(2,'cpu',299),(3,'gpu',NULL),(4,'gpu',0);`);
		expect([...getLaunchMsrps(db as any, 'gpu')]).toEqual([[1, 999]]);
		expect([...getLaunchMsrps(db as any)].sort()).toEqual([[1, 999], [2, 299]]);
		db.exec(`INSERT INTO specs VALUES (1,'gpu',799),(1,'gpu',1099)`);
		// One rule everywhere: the lowest positive MSRP across a product's spec rows.
		const { getProductMsrp } = await import('../src/lib/server/repos');
		expect(getProductMsrp(db as any, 1)).toBe(799);
		expect(getProductMsrp(db as any, 3)).toBeNull();
		db.close();
	});
});

describe('getLatestFxRate (#32)', () => {
	it('is null without the table, null when empty, else the newest row', async () => {
		const { getLatestFxRate } = await import('../src/lib/server/repos');
		const db = new Database(':memory:');
		expect(getLatestFxRate(db as any)).toBeNull();
		db.exec(`CREATE TABLE fx_rates (rate_date TEXT PRIMARY KEY, aud_per_usd REAL NOT NULL CHECK (aud_per_usd > 0),
			source TEXT NOT NULL, fetched_at TEXT NOT NULL)`);
		expect(getLatestFxRate(db as any)).toBeNull();
		db.exec(`INSERT INTO fx_rates VALUES ('2026-09-30', 1.51, 'rba', 'x'), ('2026-10-01', 1.54, 'frankfurter', 'y')`);
		expect(getLatestFxRate(db as any)).toEqual({ rateDate: '2026-10-01', audPerUsd: 1.54, source: 'frankfurter' });
		db.close();
	});
});

describe('OzBargain deals (#34)', () => {
	it('/product/[id] returns ozb { live, expired }, empty without deals', async () => {
		const { load } = await import('../src/routes/product/[id]/+page.server');
		const { getDb } = await import('../src/lib/server/db');
		const id = (getDb().prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY id LIMIT 1').get() as { id: number }).id;
		const data = load({ params: { id: String(id) } } as any);
		expect(data.ozb).toEqual({ live: [], expired: [] });
		expect(data).toHaveProperty('ozbBest');
	});

	it('/deals rows carry ozb, null without deals', async () => {
		const { load } = await import('../src/routes/deals/+page.server');
		const data = load({ url: new URL('http://x/deals'), setHeaders: noopSetHeaders } as any);
		for (const d of [...data.belowAverage, ...data.atAllTimeLow]) expect(d).toHaveProperty('ozb', null);
	});
});
