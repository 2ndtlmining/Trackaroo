// #30 safety net: every exported query in src/lib/server/repos.ts must return
// exactly what the frozen legacy copy returns, on the same DB. Runs on the
// seeded test DB always, and on a read-only copy of the real DB when
// TRACKAROO_EQUIV_DB is set (npm run test:equiv-real). Exact arrays are
// compared: if a rewrite changes tie order, restore the original ORDER BY --
// never sort inside this test.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createSeededDb, type SeededDb } from './helpers/seed';
import * as legacy from './legacy/repos.legacy';
import * as current from '../src/lib/server/repos';

function normalise(v: unknown): unknown {
	if (v instanceof Map) return [...v.entries()].map(([k, x]) => [k, normalise(x)]).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
	if (Array.isArray(v)) return v.map(normalise);
	if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normalise(x)]));
	return v;
}

type AnyDb = any;
interface Target { name: string; db: AnyDb; close: () => void }
const targets: Target[] = [];
let seeded: SeededDb;

beforeAll(() => {
	seeded = createSeededDb();
	targets.push({ name: 'seeded', db: seeded.db, close: () => seeded.close() });
	const real = process.env.TRACKAROO_EQUIV_DB;
	if (real) {
		const db = new Database(real, { readonly: true, fileMustExist: true });
		targets.push({ name: 'real-copy', db, close: () => db.close() });
	}
});
afterAll(() => targets.forEach((t) => t.close()));

function sampleIds(db: AnyDb) {
	const products = db.prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY id').all().map((r: any) => r.id);
	const listings = db.prepare('SELECT id FROM retailer_listings ORDER BY id').all().map((r: any) => r.id);
	return { first: products[0], some: products.slice(0, 3), all: products, listings };
}

// [name, (repo, db, ids) => result]. One entry per exported query and per
// meaningful argument shape. Add an entry whenever a function or parameter is
// added; remove one only when the function is deliberately deleted (Task 2).
const CASES: Array<[string, (r: any, db: AnyDb, ids: ReturnType<typeof sampleIds>) => unknown]> = [
	['getTrackedProducts gpu', (r, db) => r.getTrackedProducts(db, 'gpu')],
	['getTrackedProducts cpu', (r, db) => r.getTrackedProducts(db, 'cpu')],
	['getLaunchDates gpu', (r, db) => r.getLaunchDates(db, 'gpu')],
	['getLaunchDates cpu', (r, db) => r.getLaunchDates(db, 'cpu')],
	['getBrands', (r, db) => r.getBrands(db)],
	['getProductIndex', (r, db) => r.getProductIndex(db)],
	['getHeaderStats', (r, db) => r.getHeaderStats(db)],
	['getRetailerFreshness', (r, db) => r.getRetailerFreshness(db)],
	['getCategoryCounts', (r, db) => r.getCategoryCounts(db)],
	['getAvailableCounts', (r, db) => r.getAvailableCounts(db)],
	['getLatestListings none', (r, db) => r.getLatestListings(db)],
	['getLatestListings gpu', (r, db) => r.getLatestListings(db, { category: 'gpu' })],
	['getLatestListings cpu', (r, db) => r.getLatestListings(db, { category: 'cpu' })],
	['getLatestListings gpu inStock (products route)', (r, db) => r.getLatestListings(db, { category: 'gpu', inStock: true })],
	['getLatestListings cpu inStock (products route)', (r, db) => r.getLatestListings(db, { category: 'cpu', inStock: true })],
	['getLatestListings retailer', (r, db) => r.getLatestListings(db, { retailer: 'pccg' })],
	['getLatestListings brand', (r, db) => r.getLatestListings(db, { brand: 'NVIDIA' })],
	['getLatestListings tier', (r, db) => r.getLatestListings(db, { generation_tier: 'current' })],
	['getLatestListings query', (r, db) => r.getLatestListings(db, { query: 'rtx' })],
	['getLatestListings sort asc', (r, db) => r.getLatestListings(db, { category: 'gpu', sort: 'price-asc' })],
	['getLatestListings sort desc', (r, db) => r.getLatestListings(db, { category: 'gpu', sort: 'price-desc' })],
	['getLatestListings window 30', (r, db) => r.getLatestListings(db, { category: 'gpu' }, 30)],
	['groupListingsByProduct gpu', (r, db) => r.groupListingsByProduct(r.getLatestListings(db, { category: 'gpu', inStock: true }))],
	['groupListingsByProduct cpu', (r, db) => r.groupListingsByProduct(r.getLatestListings(db, { category: 'cpu' }))],
	['groupListingsByProduct price-asc', (r, db) => r.groupListingsByProduct(r.getLatestListings(db, { category: 'gpu' }), 'price-asc')],
	['groupListingsByProduct price-desc', (r, db) => r.groupListingsByProduct(r.getLatestListings(db, { category: 'gpu' }), 'price-desc')],
	['getSparklines', (r, db, ids) => r.getSparklines(db, ids.listings)],
	['getSparklines 30', (r, db, ids) => r.getSparklines(db, ids.listings, 30)],
	['getSparklines empty', (r, db) => r.getSparklines(db, [])],
	['getProductSparklines', (r, db, ids) => r.getProductSparklines(db, ids.all)],
	['getProductSparklines 30', (r, db, ids) => r.getProductSparklines(db, ids.all, 30)],
	['getProductSparklines empty', (r, db) => r.getProductSparklines(db, [])],
	['getProductStats 30', (r, db, ids) => ids.some.map((id: number) => r.getProductStats(db, id))],
	['getProductStats 90', (r, db, ids) => ids.some.map((id: number) => r.getProductStats(db, id, 90))],
	['getProductDealStats', (r, db, ids) => r.getProductDealStats(db, ids.all)],
	['getProductDealStats 90', (r, db, ids) => r.getProductDealStats(db, ids.all, 90)],
	['getProductDealStats empty', (r, db) => r.getProductDealStats(db, [])],
	['getPriceBand', (r, db, ids) => ids.some.map((id: number) => r.getPriceBand(db, id))],
	['getRetailerLatest', (r, db) => r.getRetailerLatest(db)],
	['getProductHistory', (r, db, ids) => ids.all.map((id: number) => r.getProductHistory(db, id, r.getRetailerLatest(db)))],
	['getProductHistory no retailerLatest', (r, db, ids) => ids.some.map((id: number) => r.getProductHistory(db, id))],
	['getProductHistory missing', (r, db) => r.getProductHistory(db, 999999, r.getRetailerLatest(db))],
	['getCheapestPerModel gpu', (r, db) => r.getCheapestPerModel(db, 'gpu')],
	['getCheapestPerModel cpu', (r, db) => r.getCheapestPerModel(db, 'cpu')],
	['getDealCandidates', (r, db) => r.getDealCandidates(db)],
	['getDealCandidates 60', (r, db) => r.getDealCandidates(db, 60)],
	['getMovers 7', (r, db) => r.getMovers(db, 7)],
	['getMovers 30', (r, db) => r.getMovers(db, 30)],
	['getProductMoves 7', (r, db) => r.getProductMoves(db, 7)],
	['getProductMoves 30', (r, db) => r.getProductMoves(db, 30)],
	['getComparisonData', (r, db, ids) => r.getComparisonData(db, ids.some)],
	['getComparisonData two', (r, db, ids) => r.getComparisonData(db, ids.some.slice(0, 2))],
	['getComparisonData missing id', (r, db, ids) => r.getComparisonData(db, [ids.first, 999999])],
	['getComparisonData empty', (r, db) => r.getComparisonData(db, [])],
	['getProductAlerts', (r, db, ids) => ids.all.map((id: number) => r.getProductAlerts(db, id))],
	['tableExists', (r, db) => [r.tableExists(db, 'products'), r.tableExists(db, 'nope')]]
];

describe('repos equivalence (#30)', () => {
	for (const [name, call] of CASES) {
		it(name, () => {
			expect(targets.length).toBeGreaterThan(0);
			for (const t of targets) {
				const ids = sampleIds(t.db);
				expect(normalise(call(current, t.db, ids)), `${name} on ${t.name}`).toEqual(normalise(call(legacy, t.db, ids)));
			}
		});
	}

	it('exports the same names as legacy', () => {
		expect(Object.keys(current).sort()).toEqual(Object.keys(legacy).sort());
	});

	it('write paths produce identical rows (upsertAlert/deleteAlert)', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'equiv-'));
		try {
			const run = (repo: any) => {
				const file = path.join(dir, `${repo === legacy ? 'legacy' : 'current'}.db`);
				fs.copyFileSync(seeded.file, file);
				const db = new Database(file);
				const id = (db.prepare('SELECT id FROM products ORDER BY id LIMIT 1').get() as { id: number }).id;
				repo.upsertAlert(db, id, 500, 'discord', true);
				repo.upsertAlert(db, id, 450, 'discord', false);
				repo.upsertAlert(db, id, 400, 'email', true);
				const toDelete = (db.prepare("SELECT id FROM price_alerts WHERE channel = 'email'").get() as { id: number }).id;
				repo.deleteAlert(db, toDelete);
				const rows = db.prepare('SELECT product_id, target_price, channel, notify_on_restock, active FROM price_alerts ORDER BY id').all();
				db.close();
				return rows;
			};
			expect(run(current)).toEqual(run(legacy));
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
