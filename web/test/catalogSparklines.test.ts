import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createSeededDb, type SeededDb } from './helpers/seed';
import { getProductSparklines, getTrackedProducts } from '../src/lib/server/repos';
import { dailyCheapestInStock } from '../src/lib/server/queries/sql';

let seeded: SeededDb;
beforeAll(() => {
	seeded = createSeededDb();
});
afterAll(() => seeded.close());

describe('getProductSparklines', () => {
	it('has entries only for tracked products of the category', () => {
		const tracked = new Set(getTrackedProducts(seeded.db, 'gpu').map((p) => p.productId));
		const map = getProductSparklines(seeded.db, 'gpu', 30);
		for (const id of map.keys()) expect(tracked.has(id)).toBe(true);
	});

	it('is date-ascending, at most 30 points, all prices positive', () => {
		for (const category of ['gpu', 'cpu'] as const) {
			const map = getProductSparklines(seeded.db, category, 30);
			for (const series of map.values()) {
				expect(series.length).toBeGreaterThan(0);
				expect(series.length).toBeLessThanOrEqual(30);
				const dates = series.map((p) => p.date);
				expect(dates).toEqual([...dates].sort());
				for (const p of series) expect(p.price).toBeGreaterThan(0);
			}
		}
	});

	it('has one point per in-stock day in the window', () => {
		const map = getProductSparklines(seeded.db, 'gpu', 30);
		expect(map.size).toBeGreaterThan(0);
		const sql = dailyCheapestInStock({
			form: 'standalone',
			product: '= ?',
			window: '?',
			dateOnly: true
		});
		for (const [id, series] of map) {
			const days = seeded.db.prepare(sql).all(id, '-30 days') as unknown[];
			expect(series.length).toBe(Math.min(days.length, 30));
		}
	});
});
