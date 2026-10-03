// @vitest-environment node
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';
import { openDatabase, type DB } from '../src/lib/server/db';
import { _resetMemo } from '../src/lib/server/cache';
import {
	getComparisonData,
	getLatestListings,
	getValueData,
	getValueRows,
	groupListingsByProduct
} from '../src/lib/server/repos';
import {
	METRICS,
	defaultMetric,
	isIndexed,
	perfFor,
	perfKey,
	sourceNote
} from '../src/lib/perfIndex';
import {
	BUDGETS,
	audPerPoint,
	bestPerBudget,
	paretoFrontier,
	perfPerKilo,
	valueCoverage,
	type ValuePoint
} from '../src/lib/value';
import { SCHEMA_PATH } from './helpers/seed';

const pt = (id: number, price: number, perf: number, vramGb: number | null = 12): ValuePoint => ({
	id,
	name: `P${id}`,
	price,
	perf,
	vramGb
});

describe('perfPerKilo / audPerPoint', () => {
	it('computes normal values', () => {
		expect(perfPerKilo(500, 50)).toBeCloseTo(100);
		expect(audPerPoint(500, 50)).toBeCloseTo(10);
	});
	it('returns null for null, zero and negative inputs', () => {
		for (const [price, perf] of [
			[null, 50],
			[500, null],
			[0, 50],
			[500, 0],
			[-5, 50],
			[500, -1]
		] as const) {
			expect(perfPerKilo(price, perf)).toBeNull();
			expect(audPerPoint(price, perf)).toBeNull();
		}
	});
});

describe('paretoFrontier', () => {
	it('returns the frontier of a known 6-point set, price ascending', () => {
		const pts = [pt(1, 300, 20), pt(2, 500, 40), pt(3, 450, 30), pt(4, 800, 60), pt(5, 700, 35), pt(6, 1200, 60)];
		expect(paretoFrontier(pts)).toEqual([1, 3, 2, 4]);
	});
	it('keeps ties and duplicates', () => {
		expect(paretoFrontier([pt(1, 500, 40), pt(2, 500, 40)])).toEqual([1, 2]);
		expect(paretoFrontier([pt(1, 500, 40), pt(2, 500, 30)])).toEqual([1]);
		expect(paretoFrontier([pt(1, 400, 40), pt(2, 500, 40)])).toEqual([1]);
	});
	it('handles a single point and empty input', () => {
		expect(paretoFrontier([pt(7, 100, 5)])).toEqual([7]);
		expect(paretoFrontier([])).toEqual([]);
	});
});

describe('bestPerBudget', () => {
	it('picks a winner, runner-up and gap per bracket', () => {
		const r = bestPerBudget([pt(1, 350, 20), pt(2, 390, 25), pt(3, 600, 40)]);
		expect(r.map((b) => b.max)).toEqual([...BUDGETS]);
		expect(r[0].winner?.id).toBe(2);
		expect(r[0].runnerUp?.id).toBe(1);
		expect(r[0].gap).toBeCloseTo(0.25);
		expect(r[1].winner?.id).toBe(3);
		expect(r[1].runnerUp?.id).toBe(2);
	});
	it('gives a perf tie to the lower price', () => {
		const r = bestPerBudget([pt(1, 390, 25), pt(2, 350, 25)]);
		expect(r[0].winner?.id).toBe(2);
		expect(r[0].runnerUp?.id).toBe(1);
		expect(r[0].gap).toBe(0);
	});
	it('has a null runner-up and gap for a one-product bracket', () => {
		const r = bestPerBudget([pt(1, 350, 20)]);
		expect(r[0].winner?.id).toBe(1);
		expect(r[0].runnerUp).toBeNull();
		expect(r[0].gap).toBeNull();
	});
	it('has all nulls for an empty bracket', () => {
		const r = bestPerBudget([pt(1, 3000, 90)]);
		for (const b of r) expect(b).toMatchObject({ winner: null, runnerUp: null, gap: null });
	});
	it('drops VRAM <= 8 with exclude8gb and keeps CPUs (null VRAM)', () => {
		const pts = [pt(1, 350, 30, 8), pt(2, 380, 20, 12), pt(3, 390, 10, null)];
		expect(bestPerBudget(pts)[0].winner?.id).toBe(1);
		const r = bestPerBudget(pts, { exclude8gb: true })[0];
		expect(r.winner?.id).toBe(2);
		expect(r.runnerUp?.id).toBe(3);
	});
});

describe('valueCoverage', () => {
	it('splits tracked products into data, no data and no price', () => {
		expect(
			valueCoverage([
				{ price: 100, perf: 10 },
				{ price: null, perf: 10 },
				{ price: 100, perf: null },
				{ price: null, perf: null }
			])
		).toEqual({ tracked: 4, withPerf: 2, withoutPerf: 2, withPerfAndPrice: 1, noPrice: 1 });
	});
});

describe('perfKey / perfFor', () => {
	const gpu = (model: string, vramGb: number | null) => ({ category: 'gpu' as const, model, vramGb });
	it('uses the model alone when it already ends with the spec', () => {
		expect(perfKey(gpu('GeForce RTX 5060 Ti 8GB', 8))).toBe('GeForce RTX 5060 Ti 8GB');
		expect(perfKey(gpu('Radeon RX 9060 XT 8GB', 8))).toBe('Radeon RX 9060 XT 8GB');
		expect(perfKey(gpu('GeForce RTX 3050 6GB', 6))).toBe('GeForce RTX 3050 6GB');
	});
	it('appends the spec for plain GPU rows', () => {
		expect(perfKey(gpu('GeForce RTX 3050', 8))).toBe('GeForce RTX 3050 8GB');
		expect(perfKey(gpu('GeForce RTX 5060 Ti', 16))).toBe('GeForce RTX 5060 Ti 16GB');
	});
	it('uses the model for CPUs', () => {
		expect(perfKey({ category: 'cpu', model: 'Ryzen 7 7700X', vramGb: null })).toBe('Ryzen 7 7700X');
	});
	it('resolves memory variants separately', () => {
		const rt = (v: number, m: string) => perfFor(gpu(m, v), 'gpu_rt_1440p');
		expect(rt(16, 'GeForce RTX 5060 Ti')).toBe(35);
		expect(rt(8, 'GeForce RTX 5060 Ti 8GB')).toBe(25);
	});
	it('returns null for a product or metric with no data', () => {
		expect(perfFor(gpu('GeForce RTX 3050 6GB', 6), 'gpu_raster_1440p')).toBeNull();
		expect(perfFor(gpu('Nope', 8), 'gpu_raster_1440p')).toBeNull();
	});
	it('exposes metrics, defaults and a source note', () => {
		expect(defaultMetric('gpu')).toBe('gpu_raster_1440p');
		expect(defaultMetric('cpu')).toBe('cpu_gaming_1080p');
		expect(METRICS.gpu_raster_1440p.source_url).toMatch(/^https:/);
		expect(sourceNote('gpu_raster_1440p')).toMatch(/^1440p raster, TechPowerUp, .+, Apr 2026$/);
	});
});

describe('watchlist coverage via perfKey', () => {
	const rows = fs
		.readFileSync(path.resolve(__dirname, '..', '..', 'db', 'watchlist.csv'), 'utf-8')
		.split(/\r?\n/)
		.filter((l) => l.trim() && !l.startsWith('#'))
		.slice(1)
		.map((l) => {
			const [category, , model, spec, tier] = l.split(',');
			return { category: category as 'gpu' | 'cpu', model, spec, tier };
		});

	it('resolves every required (current, current-1) product to an indexed key', () => {
		expect(rows.length).toBeGreaterThan(70);
		const missing = rows
			.filter((r) => r.tier !== 'current-2')
			.filter((r) => {
				const vramGb = r.category === 'gpu' ? Number(r.spec.replace(/GB$/, '')) : null;
				return !isIndexed(perfKey({ category: r.category, model: r.model, vramGb }));
			})
			.map((r) => r.model);
		expect(missing).toEqual([]);
	});
});

describe('one price rule across /products, /compare and /value (#59)', () => {
	let db: DB;
	beforeEach(() => {
		_resetMemo();
		db = openDatabase(':memory:', { readonly: false, fileMustExist: false });
		db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
		// Umart missed the latest scrape (2026-10-03): its in-stock $650 from the
		// day before is still each listing's latest price.
		db.exec(`INSERT INTO products (id, category, brand, model, vram_gb, tracked) VALUES
				(1, 'gpu', 'NVIDIA', 'GeForce RTX 5060 Ti', 16, 1);
			INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url, status) VALUES
				(1, 1, 'scorptec', 'A', 'https://x/1', 'active'),
				(2, 1, 'umart', 'B', 'https://x/2', 'active');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES
				(1, '2026-10-02', 720, 'in_stock'), (1, '2026-10-03', 700, 'in_stock'),
				(2, '2026-10-02', 650, 'in_stock');`);
	});

	it('gives the same cheapest in-stock price on every surface', () => {
		const catalogue = groupListingsByProduct(getLatestListings(db, { category: 'gpu' }))[0]
			.cheapestInStockPrice;
		const compare = getComparisonData(db, [1])[0].cheapestInStock?.price;
		const value = getValueRows(db, 'gpu')[0].price;
		expect(catalogue).toBe(650);
		expect(compare).toBe(650);
		expect(value).toBe(650);
	});

	it('ignores a listing whose latest snapshot is out of stock, on every surface', () => {
		// PCCG was cheapest and in stock yesterday, sold out today.
		db.exec(`INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url, status) VALUES
				(3, 1, 'pccg', 'C', 'https://x/3', 'active');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES
				(3, '2026-10-02', 500, 'in_stock'), (3, '2026-10-03', 500, 'out_of_stock');`);
		_resetMemo();
		const catalogue = groupListingsByProduct(getLatestListings(db, { category: 'gpu' }))[0]
			.cheapestInStockPrice;
		expect(catalogue).toBe(650);
		expect(getComparisonData(db, [1])[0].cheapestInStock?.price).toBe(650);
		expect(getValueRows(db, 'gpu')[0].price).toBe(650);
	});

	it('lists every retailer that has an in-stock latest price', () => {
		expect(getValueData(db, 'gpu', 'gpu_raster_1440p').retailers).toEqual(['scorptec', 'umart']);
	});
});

describe('getValueRows / getValueData', () => {
	let db: DB;
	beforeEach(() => {
		_resetMemo();
		db = openDatabase(':memory:', { readonly: false, fileMustExist: false });
		db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
		db.exec(`INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0), ('umart', 1);
			INSERT INTO products (id, category, brand, model, vram_gb, tracked) VALUES
				(1, 'gpu', 'NVIDIA', 'GeForce RTX 5060 Ti', 16, 1),
				(2, 'gpu', 'NVIDIA', 'GeForce RTX 5060 Ti 8GB', 8, 1),
				(3, 'gpu', 'NVIDIA', 'GeForce RTX 3050 6GB', 6, 1),
				(4, 'gpu', 'NVIDIA', 'GeForce RTX 3060', 12, 1),
				(5, 'gpu', 'NVIDIA', 'GeForce RTX 3070', 8, 0),
				(6, 'cpu', 'AMD', 'Ryzen 7 7700X', NULL, 1);
			INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url, status) VALUES
				(1, 1, 'scorptec', 'A', 'https://x/1', 'active'),
				(2, 1, 'umart', 'B', 'https://x/2', 'active'),
				(3, 2, 'scorptec', 'C', 'https://x/3', 'active'),
				(4, 3, 'scorptec', 'D', 'https://x/4', 'active'),
				(5, 4, 'scorptec', 'E bundle', 'https://x/5', 'active'),
				(6, 4, 'umart', 'F', 'https://x/6', 'delisted'),
				(7, 5, 'umart', 'G', 'https://x/7', 'active'),
				(8, 6, 'umart', 'H', 'https://x/8', 'active');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES
				(1, '2026-10-02', 900, 'in_stock'), (1, '2026-10-03', 700, 'in_stock'),
				(2, '2026-10-03', 650, 'in_stock'),
				(3, '2026-10-03', 600, 'out_of_stock'),
				(4, '2026-10-03', 300, 'in_stock'),
				(5, '2026-10-03', 100, 'in_stock'),
				(6, '2026-10-03', 120, 'in_stock'),
				(7, '2026-10-03', 400, 'in_stock'),
				(8, '2026-10-03', 450, 'in_stock');`);
	});

	it('returns the cheapest in-stock price on the latest date', () => {
		const byId = new Map(getValueRows(db, 'gpu').map((r) => [r.id, r]));
		expect(byId.get(1)?.price).toBe(650);
		expect(byId.get(1)?.vramGb).toBe(16);
	});
	it('gives null for out-of-stock-only products', () => {
		expect(getValueRows(db, 'gpu').find((r) => r.id === 2)?.price).toBeNull();
	});
	it('excludes bundle and delisted listings', () => {
		expect(getValueRows(db, 'gpu').find((r) => r.id === 4)?.price).toBeNull();
	});
	it('lists tracked products of the category only', () => {
		expect(getValueRows(db, 'gpu').map((r) => r.id).sort()).toEqual([1, 2, 3, 4]);
		expect(getValueRows(db, 'cpu').map((r) => [r.id, r.price])).toEqual([[6, 450]]);
	});
	it('builds points and coverage counts', () => {
		const { points, coverage } = getValueData(db, 'gpu', 'gpu_raster_1440p');
		expect(points.map((p) => p.id).sort()).toEqual([1]);
		// 5060 Ti 16GB and 8GB have data; 3050 6GB is not in source; 3060 has data but no price.
		expect(coverage.tracked).toBe(4);
		expect(coverage.withPerf).toBe(coverage.withPerfAndPrice + coverage.noPrice);
		expect(coverage.withPerfAndPrice).toBe(1);
		expect(coverage.noPrice).toBe(2);
		expect(coverage.withoutPerf).toBe(1);
	});
	it('counts required-tier coverage and names the retailers priced today (R6, /value)', () => {
		db.exec(`UPDATE products SET generation_tier = 'current' WHERE id IN (1, 3);
			UPDATE products SET generation_tier = 'current-2' WHERE id = 4;`);
		_resetMemo();
		const { required, retailers } = getValueData(db, 'gpu', 'gpu_raster_1440p');
		// 5060 Ti 16GB (perf) and 3050 6GB (not in source) are current; 3060 is current-2.
		expect(required).toEqual({ tracked: 2, withPerf: 1 });
		expect(retailers).toEqual(['scorptec', 'umart']);
	});
});

describe('tierCoverage (#33)', () => {
	it('counts only current and current-1 products', async () => {
		const { tierCoverage } = await import('../src/lib/value');
		expect(
			tierCoverage([
				{ tier: 'current', perf: 10 },
				{ tier: 'current-1', perf: null },
				{ tier: 'current-1', perf: 5 },
				{ tier: 'current-2', perf: 5 },
				{ tier: null, perf: null }
			])
		).toEqual({ withPerf: 2, tracked: 3 });
	});
});
