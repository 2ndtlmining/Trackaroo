import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import type { DB } from '../src/lib/server/db';
import {
	MIN_HISTORY_POINTS,
	getCheapestPerModel,
	getLatestListings,
	getMovers,
	getProductHistory,
	getSummary,
	groupListingsByProduct
} from '../src/lib/server/repos';
import { createSeededDb, DATA_DIR, parseDateFromFilename, type SeededDb } from './helpers/seed';

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