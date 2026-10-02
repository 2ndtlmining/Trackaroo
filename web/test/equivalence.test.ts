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
import { fileURLToPath } from 'node:url';
import { createSeededDb, type SeededDb } from './helpers/seed';
import * as legacy from './legacy/repos.legacy';
import * as current from '../src/lib/server/repos';

// Tagged, order-preserving conversion: Map/Set keep insertion order, Dates and
// undefined-valued keys survive, so toStrictEqual catches order and type drift.
function normalise(v: unknown): unknown {
	if (v instanceof Map) return { __map: [...v.entries()].map(([k, x]) => [normalise(k), normalise(x)]) };
	if (v instanceof Set) return { __set: [...v].map(normalise) };
	if (v instanceof Date) return { __date: v.toISOString() };
	if (Array.isArray(v)) return v.map(normalise);
	if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normalise(x)]));
	return v;
}

type AnyDb = any;
interface Target { name: string; db: AnyDb; close: () => void }
const targets: Target[] = [];
let seeded: SeededDb;

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_DB_DIR = path.resolve(here, '..', '..', 'db');

function enrich(file: string): AnyDb {
	const db = new Database(file);
	// Delisted / stale listings: one of each per retailer, on the copy only.
	db.exec(`UPDATE retailer_listings SET status = 'delisted' WHERE id IN (SELECT MIN(id) FROM retailer_listings GROUP BY retailer)`);
	db.exec(`UPDATE retailer_listings SET status = 'stale' WHERE id IN (
		SELECT MIN(id) FROM retailer_listings WHERE status = 'active' GROUP BY retailer)`);
	const pids = db.prepare('SELECT id FROM products ORDER BY id LIMIT 3').all().map((r: any) => r.id);
	const ins = db.prepare('INSERT INTO price_alerts (product_id, target_price, channel, notify_on_restock, active) VALUES (?, ?, ?, ?, ?)');
	ins.run(pids[0], 500, 'discord', 1, 1);
	ins.run(pids[0], 450, 'email', 0, 0);
	ins.run(pids[1], 300, 'webhook', 1, 0);
	ins.run(pids[2], 999, 'discord', 0, 1);
	const retailers = db.prepare('SELECT DISTINCT retailer FROM retailer_listings ORDER BY retailer').all().map((r: any) => r.retailer);
	const run = db.prepare('INSERT INTO scrape_runs (retailer, run_date, started_at, finished_at, status, exit_code, matched) VALUES (?, ?, ?, ?, ?, ?, ?)');
	const today = new Date().toISOString().slice(0, 10);
	const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
	retailers.forEach((r: string, i: number) => {
		run.run(r, yesterday, `${yesterday}T04:00:00`, `${yesterday}T04:05:00`, 'ok', 0, 100 + i);
		run.run(r, today, `${today}T04:00:00`, `${today}T04:05:00`, i === 0 ? 'failed' : 'ok', i === 0 ? 1 : 0, i === 0 ? null : 90 + i);
	});
	return db;
}

let enrichedDir = '';
beforeAll(() => {
	seeded = createSeededDb();
	targets.push({ name: 'seeded', db: seeded.db, close: () => seeded.close() });
	enrichedDir = fs.mkdtempSync(path.join(os.tmpdir(), 'equiv-enriched-'));
	const efile = path.join(enrichedDir, 'enriched.db');
	fs.copyFileSync(seeded.file, efile);
	const edb = enrich(efile);
	targets.push({ name: 'seeded-enriched', db: edb, close: () => edb.close() });
	const real = process.env.TRACKAROO_EQUIV_DB;
	if (real) {
		const rel = path.relative(REPO_DB_DIR, path.resolve(real));
		if (!rel.startsWith('..') && !path.isAbsolute(rel)) {
			throw new Error(`TRACKAROO_EQUIV_DB must be a temp copy, not a file inside ${REPO_DB_DIR}`);
		}
		const db = new Database(real, { readonly: true, fileMustExist: true });
		targets.push({ name: 'real-copy', db, close: () => db.close() });
	}
});
afterAll(() => {
	targets.forEach((t) => t.close());
	if (enrichedDir) fs.rmSync(enrichedDir, { recursive: true, force: true });
});

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
	['getSparklines 1', (r, db, ids) => r.getSparklines(db, ids.listings, 1)],
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
	['getMovers 1', (r, db) => r.getMovers(db, 1)],
	['getMovers 30', (r, db) => r.getMovers(db, 30)],
	['getProductMoves 7', (r, db) => r.getProductMoves(db, 7)],
	['getProductMoves 1', (r, db) => r.getProductMoves(db, 1)],
	['getProductMoves 30', (r, db) => r.getProductMoves(db, 30)],
	['getComparisonData', (r, db, ids) => r.getComparisonData(db, ids.some)],
	['getComparisonData four', (r, db, ids) => r.getComparisonData(db, ids.all.slice(0, 4))],
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
				expect(normalise(call(current, t.db, ids)), `${name} on ${t.name}`).toStrictEqual(normalise(call(legacy, t.db, ids)));
			}
		});
	}

	it('exports the same names as legacy', () => {
		expect(Object.keys(current).sort()).toEqual(Object.keys(legacy).sort());
	});

	it('exported non-function values are equal', () => {
		const keys = Object.keys(legacy).filter((k) => typeof (legacy as any)[k] !== 'function');
		expect(keys).toContain('DEFAULT_WINDOW_DAYS');
		for (const k of keys) expect(normalise((current as any)[k]), k).toStrictEqual(normalise((legacy as any)[k]));
	});

	it('write paths produce identical rows (upsertAlert/deleteAlert)', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'equiv-'));
		try {
			// created_at is the wall clock at insert; the only field allowed to differ.
			const stampless = (rows: any[]) => normalise(rows.map((r) => ({ ...r, created_at: typeof r.created_at })));
			const run = (repo: any) => {
				const file = path.join(dir, `${repo === legacy ? 'legacy' : 'current'}.db`);
				fs.copyFileSync(seeded.file, file);
				const db = new Database(file);
				const id = (db.prepare('SELECT id FROM products ORDER BY id LIMIT 1').get() as { id: number }).id;
				repo.upsertAlert(db, id, 500, 'discord', true);
				repo.upsertAlert(db, id, 450, 'discord', false);
				repo.upsertAlert(db, id, 400, 'email', true);
				const toDelete = (db.prepare("SELECT id FROM price_alerts WHERE channel = 'email'").get() as { id: number }).id;
				const beforeDelete = stampless(repo.getProductAlerts(db, id));
				repo.deleteAlert(db, toDelete);
				const afterDelete = stampless(repo.getProductAlerts(db, id));
				const rows = db.prepare('SELECT product_id, target_price, channel, notify_on_restock, active FROM price_alerts ORDER BY id').all();
				db.close();
				return { rows, beforeDelete, afterDelete };
			};
			const got = run(current);
			expect(got.beforeDelete).toHaveLength(2);
			expect(got.afterDelete).toHaveLength(1);
			expect(got).toStrictEqual(run(legacy));
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
