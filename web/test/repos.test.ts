import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { DB } from '../src/lib/server/db';
import {
	MIN_HISTORY_POINTS,
	getLatestListings,
	getMovers,
	getProductHistory,
	getSummary
} from '../src/lib/server/repos';
import { createSeededDb, type SeededDb } from './helpers/seed';

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
		expect(summary.trackedProducts).toBeGreaterThan(0);
		expect(summary.listingsToday).toBeGreaterThan(0);
		expect(summary.retailerCount).toBe(2);
		expect(summary.latestSnapshotDate).toBe('2026-08-15');
	});

	it('reports a biggest mover or null', () => {
		const summary = getSummary(db);
		if (summary.biggestMover) {
			expect(summary.biggestMover.pctChange).not.toBeNull();
			expect(summary.biggestMover.notEnoughHistory).toBe(false);
		}
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