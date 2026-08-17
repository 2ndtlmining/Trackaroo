import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { openDatabase, type DB } from '../src/lib/server/db';
import {
	MIN_HISTORY_POINTS,
	deriveListingBrand,
	getCheapestPerModel,
	getComparisonData,
	getCoverageSummary,
	getLatestListings,
	getMovers,
	getPriceBand,
	getPriceExtremes,
	getProductHistory,
	getProductIndex,
	getSparklines,
	getSummary,
	groupListingsByProduct
} from '../src/lib/server/repos';
import { createSeededDb, DATA_DIR, SCHEMA_PATH, parseDateFromFilename, type SeededDb } from './helpers/seed';

let seeded: SeededDb;
let db: DB;

beforeAll(() => {
	seeded = createSeededDb();
	db = seeded.db;
});

afterAll(() => {
	seeded.close();
});

describe('getSummary', () => {
	it('reports tracked products, listings today, retailers and date', () => {
		const summary = getSummary(db);
		const expectedLatest = fs
			.readdirSync(DATA_DIR)
			.filter((f) => f.endsWith('.json'))
			.map(parseDateFromFilename)
			.filter(Boolean)
			.sort()
			.reverse()[0];
		expect(summary.trackedProducts).toBeGreaterThan(0);
		expect(summary.listingsToday).toBeGreaterThan(0);
		expect(summary.retailerCount).toBe(2);
		expect(summary.latestSnapshotDate).toBe(expectedLatest);
	});

	it('reports a biggest mover or null', () => {
		const summary = getSummary(db);
		if (summary.biggestMover) {
			expect(summary.biggestMover.pctChange).not.toBeNull();
			expect(summary.biggestMover.notEnoughHistory).toBe(false);
		}
	});

	it('reports snapshot count, distinct days and db size', () => {
		const summary = getSummary(db);
		expect(summary.snapshotCount).toBeGreaterThan(0);
		expect(summary.snapshotDays).toBeGreaterThan(0);
		expect(summary.dbSizeBytes).toBeGreaterThan(0);
	});
});

describe('getLatestListings', () => {
	it('returns all active listings with a latest snapshot', () => {
		const rows = getLatestListings(db);
		expect(rows.length).toBeGreaterThan(0);
		for (const row of rows) {
			expect(row.latestPrice).toBeGreaterThan(0);
			expect(row.latestDate).toBeTruthy();
			expect(row.category).toMatch(/^(cpu|gpu)$/);
			expect(row.retailer).toMatch(/^(scorptec|pccg)$/);
			expect(row.listingUrl).toMatch(/^https/);
		}
	});

	it('filters by category', () => {
		const gpu = getLatestListings(db, { category: 'gpu' });
		const cpu = getLatestListings(db, { category: 'cpu' });
		expect(gpu.length + cpu.length).toBe(getLatestListings(db).length);
		expect(gpu.every((r) => r.category === 'gpu')).toBe(true);
		expect(cpu.every((r) => r.category === 'cpu')).toBe(true);
	});

	it('filters by retailer', () => {
		const scorptec = getLatestListings(db, { retailer: 'scorptec' });
		expect(scorptec.length).toBeGreaterThan(0);
		expect(scorptec.every((r) => r.retailer === 'scorptec')).toBe(true);
	});

	it('filters by brand', () => {
		const nvidia = getLatestListings(db, { brand: 'NVIDIA' });
		expect(nvidia.length).toBeGreaterThan(0);
		expect(nvidia.every((r) => r.brand === 'NVIDIA')).toBe(true);
	});

	it('filters by a case-insensitive model search', () => {
		const sample = getLatestListings(db)[0];
		const needle = sample.model.toLowerCase().slice(0, 6);
		const results = getLatestListings(db, { query: needle });
		expect(results.length).toBeGreaterThan(0);
		for (const row of results) {
			const haystack = `${row.brand} ${row.model} ${row.productVariant ?? ''} ${row.variantName ?? ''}`.toLowerCase();
			expect(haystack).toContain(needle);
		}
	});

	it('returns no results for a nonsense search', () => {
		expect(getLatestListings(db, { query: 'zzz-zzz-nonsense' })).toEqual([]);
	});

	it('sorts by price ascending and descending', () => {
		const asc = getLatestListings(db, { sort: 'price-asc' });
		const desc = getLatestListings(db, { sort: 'price-desc' });
		expect(asc.length).toBeGreaterThan(0);
		expect(desc.length).toBe(asc.length);
		const ascPrices = asc.map((r) => r.latestPrice);
		const descPrices = desc.map((r) => r.latestPrice);
		for (let i = 1; i < ascPrices.length; i += 1) {
			expect(ascPrices[i]).toBeGreaterThanOrEqual(ascPrices[i - 1]);
			expect(descPrices[i]).toBeLessThanOrEqual(descPrices[i - 1]);
		}
	});

	it('filters by generation tier', () => {
		const current = getLatestListings(db, { generation_tier: 'current' });
		expect(current.length).toBeGreaterThan(0);
		expect(current.every((r) => r.generationTier === 'current')).toBe(true);
	});

	it('combines filters with AND', () => {
		const rows = getLatestListings(db, { category: 'gpu', retailer: 'scorptec' });
		expect(rows.every((r) => r.category === 'gpu' && r.retailer === 'scorptec')).toBe(true);
	});

	it('produces a window start price and point count per listing', () => {
		const rows = getLatestListings(db);
		const withStart = rows.filter((r) => r.windowStartPrice !== null);
		expect(withStart.length).toBeGreaterThan(0);
		for (const row of withStart) {
			expect(row.pointsInWindow).toBeGreaterThanOrEqual(1);
		}
	});

	it('exposes freshness from the listing last_snapshot_at', () => {
		const rows = getLatestListings(db);
		for (const row of rows) {
			expect(row.lastSnapshotAt).toBeTruthy();
			expect(new Date(row.lastSnapshotAt!).getTime()).not.toBeNaN();
		}
	});
});

describe('groupListingsByProduct', () => {
	it('groups all rows into one entry per product', () => {
		const rows = getLatestListings(db);
		const groups = groupListingsByProduct(rows);
		expect(groups.length).toBeGreaterThan(0);
		expect(groups.reduce((n, g) => n + g.listings.length, 0)).toBe(rows.length);
		const ids = groups.map((g) => g.productId);
		expect(new Set(ids).size).toBe(ids.length);
		for (const g of groups) {
			expect(g.listings.every((r) => r.productId === g.productId)).toBe(true);
		}
	});

	it('computes the cheapest in-stock price and count per product', () => {
		const groups = groupListingsByProduct(getLatestListings(db));
		for (const g of groups) {
			const inStock = g.listings.filter((r) => r.latestStock === 'in_stock');
			if (inStock.length === 0) {
				expect(g.cheapestInStockPrice).toBeNull();
				expect(g.cheapestInStockRetailer).toBeNull();
				expect(g.inStockCount).toBe(0);
			} else {
				const min = Math.min(...inStock.map((r) => r.latestPrice));
				expect(g.cheapestInStockPrice).toBeCloseTo(min, 2);
				expect(g.inStockCount).toBe(inStock.length);
				const cheapest = inStock.filter((r) => r.latestPrice === min);
				expect(cheapest.some((r) => r.retailer === g.cheapestInStockRetailer)).toBe(true);
			}
		}
	});

	it('keeps category/model order by default and sorts by price on request', () => {
		const rows = getLatestListings(db);
		const asc = groupListingsByProduct(rows, 'price-asc');
		const desc = groupListingsByProduct(rows, 'price-desc');

		const priced = (gs: typeof asc) =>
			gs.filter((g) => g.cheapestInStockPrice !== null).map((g) => g.cheapestInStockPrice!);
		for (let i = 1; i < priced(asc).length; i += 1) {
			expect(priced(asc)[i]).toBeGreaterThanOrEqual(priced(asc)[i - 1]);
		}
		for (let i = 1; i < priced(desc).length; i += 1) {
			expect(priced(desc)[i]).toBeLessThanOrEqual(priced(desc)[i - 1]);
		}

		// Products with nothing in stock sink to the end for both price sorts.
		for (const gs of [asc, desc]) {
			const firstUnpriced = gs.findIndex((g) => g.cheapestInStockPrice === null);
			if (firstUnpriced !== -1) {
				for (let i = firstUnpriced; i < gs.length; i += 1) {
					expect(gs[i].cheapestInStockPrice).toBeNull();
				}
			}
		}
	});
});

describe('getCheapestPerModel', () => {
	it('returns at most one in-stock listing per model for the latest date', () => {
		const gpu = getCheapestPerModel(db, 'gpu');
		const cpu = getCheapestPerModel(db, 'cpu');
		expect(gpu.length + cpu.length).toBeGreaterThan(0);

		const latest = db
			.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
			.get() as { d: string };
		for (const rows of [gpu, cpu]) {
			const models = new Set(rows.map((r) => r.model));
			expect(models.size).toBe(rows.length);
			for (const row of rows) {
				expect(row.snapshotDate).toBe(latest.d);
				expect(row.price).toBeGreaterThan(0);
				expect(row.retailer).toMatch(/^(scorptec|pccg)$/);
			}
		}
	});

	it('chooses the cheapest price among in-stock listings for each model', () => {
		const rows = getCheapestPerModel(db, 'gpu');
		for (const row of rows) {
			const minForProduct = db
				.prepare(
					`SELECT MIN(ps2.price_aud) AS m
					 FROM price_snapshots ps2
					 JOIN retailer_listings l2 ON l2.id = ps2.retailer_listing_id
					 WHERE l2.product_id = ?
					   AND ps2.snapshot_date = ?
					   AND ps2.stock_status = 'in_stock'
					   AND l2.status = 'active'`
				)
				.get(row.productId, row.snapshotDate) as { m: number | null };
			expect(minForProduct.m).not.toBeNull();
			expect(row.price).toBeCloseTo(minForProduct.m as number, 2);
		}
	});

	it('carries 90-day low/high for each model', () => {
		const rows = getCheapestPerModel(db, 'gpu');
		expect(rows.length).toBeGreaterThan(0);
		for (const row of rows) {
			expect(row.ninetyDayLow).not.toBeNull();
			expect(row.ninetyDayHigh).not.toBeNull();
			expect(row.ninetyDayLow as number).toBeLessThanOrEqual(row.price);
			expect(row.ninetyDayHigh as number).toBeGreaterThanOrEqual(row.price);
		}
	});
});

describe('getPriceExtremes', () => {
	it('returns low/high within the trailing window, excluding bundles', () => {
		const product = db.prepare("SELECT id FROM products WHERE category = 'cpu' LIMIT 1").get() as {
			id: number;
		};
		const { low, high } = getPriceExtremes(db, product.id, 90);
		expect(low).not.toBeNull();
		expect(high).not.toBeNull();
		expect(low as number).toBeLessThanOrEqual(high as number);

		const day = db
			.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
			.get() as { d: string };
		const agg = db
			.prepare(
				`SELECT MIN(s.price_aud) AS mn, MAX(s.price_aud) AS mx
				 FROM retailer_listings l
				 JOIN price_snapshots s ON s.retailer_listing_id = l.id
				 WHERE l.product_id = ?
				   AND s.snapshot_date >= date(?, '-90 days')
				   AND s.stock_status = 'in_stock'
				   AND lower(l.variant_name) NOT LIKE '%bundle%'
				   AND lower(l.variant_name) NOT LIKE '%combo%'
				   AND lower(l.listing_url) NOT LIKE '%bundle%'
				   AND lower(l.listing_url) NOT LIKE '%bdl-%'`
			)
			.get(product.id, day.d) as { mn: number | null; mx: number | null };
		expect(low).toBeCloseTo(agg.mn as number, 2);
		expect(high).toBeCloseTo(agg.mx as number, 2);
	});

	it('honours the window length for a zero-day window', () => {
		const product = db.prepare("SELECT id FROM products WHERE category = 'cpu' LIMIT 1").get() as {
			id: number;
		};
		const { low, high } = getPriceExtremes(db, product.id, 0);
		const day = db
			.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
			.get() as { d: string };
		const band = getPriceBand(db, product.id);
		const last = band[band.length - 1];
		expect(last.date).toBe(day.d);
		// Zero-day window anchors to the latest day only
		expect(low).toBe(last.low);
		expect(high).toBe(last.high);
	});
});

describe('getProductHistory', () => {
	it('returns null for an unknown product', () => {
		expect(getProductHistory(db, 999_999)).toBeNull();
	});

	it('returns product meta and per-listing series for a known product', () => {
		const row = db.prepare('SELECT id FROM products LIMIT 1').get() as { id: number } | undefined;
		expect(row).toBeDefined();
		const history = getProductHistory(db, row!.id);
		expect(history).not.toBeNull();
		expect(history!.product.id).toBe(row!.id);
		expect(history!.series.length).toBeGreaterThan(0);
		for (const series of history!.series) {
			expect(series.listing.product_id).toBe(row!.id);
			expect(series.points.length).toBeGreaterThan(0);
			expect(series.points[0].price_aud).toBeGreaterThan(0);
		}
	});

	it('attaches the spec row for a product that has specs', () => {
		const history = getProductHistory(db, 1);
		expect(history).not.toBeNull();
		expect(history!.specs).not.toBeNull();
		expect(history!.specs!.product_id).toBe(1);
		expect(history!.specs!.category).toBe('cpu');
		expect(history!.specs!.architecture).toBe('Arrow Lake');
		expect(history!.specs!.core_count).toBe(10);
	});

	it('returns null specs for a product without specs', () => {
		const history = getProductHistory(db, 2);
		expect(history).not.toBeNull();
		expect(history!.specs).toBeNull();
	});

	it('attaches gpu specs for a gpu product', () => {
		const row = db
			.prepare("SELECT id FROM products WHERE category = 'gpu' ORDER BY id LIMIT 1")
			.get() as { id: number } | undefined;
		expect(row).toBeDefined();
		const history = getProductHistory(db, row!.id);
		expect(history!.specs).not.toBeNull();
		expect(history!.specs!.category).toBe('gpu');
		expect(history!.specs!.vram_gb).toBe(16);
		expect(history!.specs!.memory_type).toBe('GDDR7');
	});

	it('orders series points by snapshot date', () => {
		const row = db
			.prepare(
				`SELECT product_id FROM retailer_listings GROUP BY product_id LIMIT 1`
			)
			.get() as { product_id: number } | undefined;
		expect(row).toBeDefined();
		const history = getProductHistory(db, row!.product_id);
		for (const series of history!.series) {
			const dates = series.points.map((p) => p.snapshot_date);
			expect([...dates].sort()).toEqual(dates);
		}
	});
});

describe('deriveListingBrand', () => {
	it('maps known AIB first-tokens to canonical display names', () => {
		expect(deriveListingBrand('Gigabyte GeForce RTX 5060 Windforce OC 8GB', 'NVIDIA')).toBe(
			'Gigabyte'
		);
		expect(deriveListingBrand('msi geforce rtx 3050 ventus 2x e 6g oc', 'NVIDIA')).toBe('MSI');
		expect(deriveListingBrand('ASUS Dual GeForce RTX 5060 Ti', 'NVIDIA')).toBe('ASUS');
		expect(deriveListingBrand('zotac gaming geforce rtx 3050 6gb', 'NVIDIA')).toBe('ZOTAC');
		expect(deriveListingBrand('inno3d geforce rtx 5060 low profile, 8gb', 'NVIDIA')).toBe(
			'Inno3D'
		);
		expect(deriveListingBrand('palit geforce rtx 5060 infinity 2 oc, 8gb', 'NVIDIA')).toBe(
			'Palit'
		);
		expect(deriveListingBrand('pny geforce rtx 5060 overclocked dual fan, 8gb', 'NVIDIA')).toBe(
			'PNY'
		);
	});

	it('maps silicon brand prefixes for CPU listings', () => {
		expect(deriveListingBrand('AMD Ryzen 7 9800X3D Processor', 'AMD')).toBe('AMD');
		expect(deriveListingBrand('intel core i5 14400 desktop processor', 'Intel')).toBe('Intel');
	});

	it('falls back to the product brand for unknown prefixes and null names', () => {
		expect(deriveListingBrand('Ryzen 5 7600, Tray, 65W', 'AMD')).toBe('AMD');
		expect(deriveListingBrand(null, 'NVIDIA')).toBe('NVIDIA');
	});
});

describe('getPriceBand', () => {
	it('returns one row per snapshot day, sorted ascending, with low <= high', () => {
		const row = db.prepare('SELECT id FROM products LIMIT 1').get() as { id: number };
		const band = getPriceBand(db, row.id);
		expect(band.length).toBeGreaterThan(0);
		const dates = band.map((p) => p.date);
		expect([...dates].sort()).toEqual(dates);
		for (const p of band) {
			if (p.low !== null && p.high !== null) {
				expect(p.low).toBeLessThanOrEqual(p.high);
			}
		}
	});

	it('computes the exact min/max in-stock price for a known day', () => {
		const sample = db
			.prepare(
				`SELECT p.id AS pid, s.snapshot_date AS date
				 FROM products p
				 JOIN retailer_listings l ON l.product_id = p.id
				 JOIN price_snapshots s ON s.retailer_listing_id = l.id
				 WHERE s.stock_status = 'in_stock'
				   AND lower(l.variant_name) NOT LIKE '%bundle%'
				   AND lower(l.variant_name) NOT LIKE '%combo%'
				   AND lower(l.listing_url) NOT LIKE '%bundle%'
				   AND lower(l.listing_url) NOT LIKE '%bdl-%'
				 LIMIT 1`
			)
			.get() as { pid: number; date: string };
		expect(sample).toBeDefined();
		const band = getPriceBand(db, sample.pid);
		const point = band.find((p) => p.date === sample.date);
		expect(point).toBeDefined();
		const agg = db
			.prepare(
				`SELECT MIN(s.price_aud) AS mn, MAX(s.price_aud) AS mx
				 FROM retailer_listings l
				 JOIN price_snapshots s ON s.retailer_listing_id = l.id
				 WHERE l.product_id = ? AND s.snapshot_date = ? AND s.stock_status = 'in_stock'
				   AND lower(l.variant_name) NOT LIKE '%bundle%'
				   AND lower(l.variant_name) NOT LIKE '%combo%'
				   AND lower(l.listing_url) NOT LIKE '%bundle%'
				   AND lower(l.listing_url) NOT LIKE '%bdl-%'`
			)
			.get(sample.pid, sample.date) as { mn: number | null; mx: number | null };
		expect(point!.low).toBeCloseTo(agg.mn as number, 2);
		expect(point!.high).toBeCloseTo(agg.mx as number, 2);
	});

	it('is null on days where nothing is in stock', () => {
		const candidate = db
			.prepare(
				`SELECT p.id AS pid, s.snapshot_date AS date
				 FROM products p
				 JOIN retailer_listings l ON l.product_id = p.id
				 JOIN price_snapshots s ON s.retailer_listing_id = l.id
				 GROUP BY p.id, s.snapshot_date
				 HAVING SUM(CASE WHEN s.stock_status = 'in_stock' THEN 1 ELSE 0 END) = 0
				 LIMIT 1`
			)
			.get() as { pid: number; date: string } | undefined;
		expect(candidate).toBeDefined();
		const band = getPriceBand(db, candidate!.pid);
		const point = band.find((p) => p.date === candidate!.date);
		expect(point).toBeDefined();
		expect(point!.low).toBeNull();
		expect(point!.high).toBeNull();
	});

	it('sets cheapestInStock only on the latest date with an in-stock listing', () => {
		const gpu = db
			.prepare(
				`SELECT p.id AS pid FROM products p
				 WHERE p.category = 'gpu'
				   AND EXISTS (SELECT 1 FROM retailer_listings l JOIN price_snapshots s ON s.retailer_listing_id = l.id
				               WHERE l.product_id = p.id AND s.stock_status = 'in_stock')
				 LIMIT 1`
			)
			.get() as { pid: number } | undefined;
		expect(gpu).toBeDefined();
		const band = getPriceBand(db, gpu!.pid);
		const latest = db
			.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
			.get() as { d: string };
		const marked = band.filter((p) => p.cheapestInStock !== null);
		expect(marked.length).toBe(1);
		expect(marked[0].date).toBe(latest.d);
	});
});

describe('getComparisonData', () => {
	it('returns one entry per requested product, in order, with spec', () => {
		const all = db
			.prepare('SELECT id FROM products ORDER BY id LIMIT 2')
			.all() as Array<{ id: number }>;
		const entries = getComparisonData(db, [all[0].id, all[1].id]);
		expect(entries.length).toBe(2);
		expect(entries[0].product.id).toBe(all[0].id);
		expect(entries[1].product.id).toBe(all[1].id);
		expect(entries[0].spec).not.toBeNull();
	});

	it('skips product ids that do not exist', () => {
		const all = db.prepare('SELECT id FROM products LIMIT 1').all() as Array<{ id: number }>;
		const entries = getComparisonData(db, [all[0].id, 999999]);
		expect(entries.length).toBe(1);
		expect(entries[0].product.id).toBe(all[0].id);
	});

	it('computes the cheapest in-stock price per product from the latest day', () => {
		const gpu = db
			.prepare(
				`SELECT p.id AS pid FROM products p
				 WHERE p.category = 'gpu'
				   AND EXISTS (SELECT 1 FROM retailer_listings l JOIN price_snapshots s ON s.retailer_listing_id = l.id
				               WHERE l.product_id = p.id AND s.stock_status = 'in_stock')
				 LIMIT 1`
			)
			.get() as { pid: number } | undefined;
		expect(gpu).toBeDefined();
		const entries = getComparisonData(db, [gpu!.pid]);
		const day = db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get() as {
			d: string;
		};
		const agg = db
			.prepare(
				`SELECT MIN(s.price_aud) AS mn FROM retailer_listings l
				 JOIN price_snapshots s ON s.retailer_listing_id = l.id
				 WHERE l.product_id = ? AND s.snapshot_date = ? AND s.stock_status = 'in_stock'
				   AND lower(l.variant_name) NOT LIKE '%bundle%'
				   AND lower(l.variant_name) NOT LIKE '%combo%'
				   AND lower(l.listing_url) NOT LIKE '%bundle%'
				   AND lower(l.listing_url) NOT LIKE '%bdl-%'`
			)
			.get(gpu!.pid, day.d) as { mn: number | null };
		expect(entries[0].cheapestInStock).not.toBeNull();
		expect(entries[0].cheapestInStock!.price).toBeCloseTo(agg.mn as number, 2);
		expect(entries[0].cheapestInStock!.price).toBe(
			Math.min(...entries[0].prices.map((p) => p.price!))
		);
	});

	it('returns prices only for retailers with an in-stock listing that day', () => {
		const cpu = db.prepare("SELECT id FROM products WHERE category = 'cpu' LIMIT 1").get() as {
			id: number;
		};
		const entries = getComparisonData(db, [cpu.id]);
		expect(entries.length).toBe(1);
		expect(entries[0].prices.length).toBeGreaterThan(0);
		for (const p of entries[0].prices) {
			expect(p.price).not.toBeNull();
		}
	});

	it('uses each listing’s latest snapshot rather than a single global date', () => {
		const mini = createMiniCompareDb(true);
		try {
			const entries = getComparisonData(mini.db, [1]);
			expect(entries.length).toBe(1);
			const byRetailer = Object.fromEntries(
				entries[0].prices.map((p) => [p.retailer, p.price])
			);
			expect(byRetailer.scorptec).toBe(490);
			// PCCG's last snapshot is 8-16, not the global max 8-17 — its real
			// price must still surface instead of vanishing.
			expect(byRetailer.pccg).toBe(510);
			expect(entries[0].cheapestInStock).toEqual({ price: 490, retailer: 'scorptec' });
		} finally {
			mini.close();
		}
	});

	it('excludes a retailer whose latest snapshot is out of stock', () => {
		const mini = createMiniCompareDb(false);
		try {
			const entries = getComparisonData(mini.db, [1]);
			expect(entries.length).toBe(1);
			const byRetailer = Object.fromEntries(
				entries[0].prices.map((p) => [p.retailer, p.price])
			);
			expect(byRetailer.scorptec).toBe(490);
			expect(byRetailer.pccg).toBeUndefined();
			expect(entries[0].cheapestInStock).toEqual({ price: 490, retailer: 'scorptec' });
		} finally {
			mini.close();
		}
	});
});

// One CPU product, one listing per retailer. Scorptec has snapshots on 8-16 and
// 8-17; PCCG has only 8-16 (optionally in stock). Global max date is 8-17, so
// the old exact-date lookup would miss PCCG entirely.
function createMiniCompareDb(pccgInStock: boolean): { db: DB; close: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-mini-'));
	const file = path.join(dir, 'mini.db');
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('cpu', 'AMD', 'Ryzen 5 7600', 'current', 1)"
	).run();
	const scorptecId = Number(
		db.prepare(
			"INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) VALUES (1, 'scorptec', 'A', 'https://scorptec/a', 'active')"
		).run().lastInsertRowid
	);
	const pccgId = Number(
		db.prepare(
			"INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) VALUES (1, 'pccg', 'B', 'https://pccg/b', 'active')"
		).run().lastInsertRowid
	);
	const insertSnapshot = db.prepare(
		'INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) VALUES (?, ?, ?, ?, ?)'
	);
	insertSnapshot.run(scorptecId, '2026-08-16', 500, 'in_stock', '2026-08-16T04:00:00.000Z');
	insertSnapshot.run(scorptecId, '2026-08-17', 490, 'in_stock', '2026-08-17T04:00:00.000Z');
	insertSnapshot.run(
		pccgId,
		'2026-08-16',
		510,
		pccgInStock ? 'in_stock' : 'out_of_stock',
		'2026-08-16T04:00:00.000Z'
	);
	return {
		db,
		close: () => {
			db.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	};
}

describe('getCoverageSummary', () => {
	it('summarises retailers and per-product rows on the seeded db', () => {
		const summary = getCoverageSummary(db);
		expect(summary.referenceDate).toBeTruthy();
		expect(summary.retailers.map((r) => r.retailer).sort()).toEqual(['pccg', 'scorptec']);
		expect(summary.rows.length).toBeGreaterThan(0);
		expect(Array.isArray(summary.zeroListings)).toBe(true);
		for (const row of summary.rows) {
			expect(row.last7.length).toBe(7);
			expect(row.snapshotCount).toBeGreaterThanOrEqual(0);
		}
	});

	it('marks every day of a full-week history and reports gap 0', () => {
		const mini = createCoverageMiniDb();
		try {
			const summary = getCoverageSummary(mini.db);
			const today = new Date().toISOString().slice(0, 10);
			expect(summary.referenceDate).toBe(today);
			const row = summary.rows.find(
				(r) => r.retailer === 'scorptec' && r.model === 'Ryzen 5 7600'
			);
			expect(row).toBeDefined();
			expect(row!.snapshotCount).toBe(7);
			expect(row!.lastDate).toBe(today);
			expect(row!.gapDays).toBe(0);
			expect(row!.last7).toEqual([true, true, true, true, true, true, true]);
		} finally {
			mini.close();
		}
	});

	it('flags tracked products with no in-stock data in the last 7 days', () => {
		const mini = createCoverageMiniDb();
		try {
			const summary = getCoverageSummary(mini.db);
			expect(summary.zeroListings.some((p) => p.model === 'Core i5-14600K')).toBe(true);
		} finally {
			mini.close();
		}
	});
});

// Two tracked products (one with a full 7-day listing history, one never
// listed) plus an untracked throwaway product. Product 1 is listed at
// Scorptec with snapshots on every day ending today.
function createCoverageMiniDb(): { db: DB; close: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-cov-'));
	const file = path.join(dir, 'cov.db');
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('cpu', 'AMD', 'Ryzen 5 7600', 'current', 1)"
	).run();
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5060 Ti', 'current', 1)"
	).run();
	db.prepare(
		"INSERT INTO products (category, brand, model, generation_tier, tracked) VALUES ('cpu', 'Intel', 'Core i5-14600K', 'current-1', 1)"
	).run();
	const listingId = Number(
		db.prepare(
			"INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) VALUES (1, 'scorptec', 'A', 'https://scorptec/a', 'active')"
		).run().lastInsertRowid
	);
	const today = new Date().toISOString().slice(0, 10);
	const insertSnapshot = db.prepare(
		'INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) VALUES (?, ?, ?, ?, ?)'
	);
	for (let i = 6; i >= 0; i -= 1) {
		const d = new Date(`${today}T00:00:00Z`);
		d.setUTCDate(d.getUTCDate() - i);
		const iso = d.toISOString().slice(0, 10);
		insertSnapshot.run(listingId, iso, 400 + i, 'in_stock', `${iso}T04:00:00.000Z`);
	}
	return {
		db,
		close: () => {
			db.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	};
}

describe('getMovers', () => {
	it('returns movers for a 7-day window', () => {
		const movers = getMovers(db, 7);
		expect(movers.length).toBeGreaterThan(0);
	});

	it('sorts by absolute pct change descending', () => {
		const movers = getMovers(db, 7);
		const abs = movers.map((m) => (m.pctChange === null ? -1 : Math.abs(m.pctChange)));
		const sorted = [...abs].sort((a, b) => b - a);
		expect(abs).toEqual(sorted);
	});

	it('flags listings with insufficient history', () => {
		const movers = getMovers(db, 7);
		for (const m of movers) {
			expect(m.notEnoughHistory).toBe(m.historyPoints < MIN_HISTORY_POINTS);
			if (!m.notEnoughHistory) {
				expect(m.historyPoints).toBeGreaterThanOrEqual(MIN_HISTORY_POINTS);
			}
		}
	});

	it('computes change and pctChange consistently', () => {
		const movers = getMovers(db, 7).filter((m) => m.oldPrice !== null);
		for (const m of movers.slice(0, 20)) {
			expect(m.change).toBeCloseTo(m.newPrice - m.oldPrice!, 2);
			expect(m.pctChange).toBeCloseTo(((m.newPrice - m.oldPrice!) / m.oldPrice!) * 100, 1);
		}
	});

	it('yields more movers for longer windows', () => {
		const oneDay = getMovers(db, 1).filter((m) => m.oldPrice !== null);
		const sevenDay = getMovers(db, 7).filter((m) => m.oldPrice !== null);
		expect(sevenDay.length).toBeGreaterThanOrEqual(oneDay.length);
	});
});

describe('getProductIndex', () => {
	it('returns tracked products with the fields the palette needs', () => {
		const index = getProductIndex(db);
		expect(index.length).toBeGreaterThan(0);
		for (const entry of index) {
			expect(entry.id).toBeGreaterThan(0);
			expect(entry.category).toMatch(/^(cpu|gpu)$/);
			expect(entry.brand.length).toBeGreaterThan(0);
			expect(entry.model.length).toBeGreaterThan(0);
			expect('productVariant' in entry).toBe(true);
		}
	});

	it('is ordered by category then model', () => {
		const index = getProductIndex(db);
		const keys = index.map((e) => `${e.category}|${e.model}`);
		expect(keys).toEqual([...keys].sort());
	});
});

describe('getSparklines', () => {
	it('returns an empty map for no listing ids', () => {
		expect(getSparklines(db, []).size).toBe(0);
	});

	it('returns one ascending-dated series per listing within the window', () => {
		const listings = getLatestListings(db).slice(0, 5);
		const ids = new Set(listings.map((l) => l.listingId));
		const sparklines = getSparklines(db, [...ids]);

		expect(sparklines.size).toBeGreaterThan(0);
		expect(sparklines.size).toBeLessThanOrEqual(ids.size);
		for (const [listingId, points] of sparklines) {
			expect(ids.has(listingId)).toBe(true);
			expect(points.length).toBeGreaterThanOrEqual(1);
			const dates = points.map((p) => p.date);
			expect(dates).toEqual([...dates].sort());
			for (const p of points) {
				expect(p.listingId).toBe(listingId);
				expect(p.price).toBeGreaterThan(0);
			}
		}
	});

	it('only returns points inside the requested window', () => {
		const listings = getLatestListings(db).slice(0, 3);
		const ids = listings.map((l) => l.listingId);
		const maxDate = db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get() as {
			d: string;
		};
		const windowStart = new Date(`${maxDate.d}T00:00:00Z`);
		windowStart.setUTCDate(windowStart.getUTCDate() - 7);
		const sparklines = getSparklines(db, ids, 7);
		for (const points of sparklines.values()) {
			for (const p of points) {
				expect(p.date >= windowStart.toISOString().slice(0, 10)).toBe(true);
			}
		}
	});
});