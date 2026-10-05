// web/test/retire.test.ts
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { applyRetireAction, getRetireSuggestions, isRetireAction } from '../src/lib/server/retire';

const TODAY = '2026-10-06';
let db: Database.Database;

function addProduct(id: number, model: string, category = 'gpu', brand = 'AMD') {
	db.prepare('INSERT INTO products (id, category, brand, model) VALUES (?, ?, ?, ?)').run(id, category, brand, model);
}
function flag(id: number, decision = 'pending', extra: Record<string, unknown> = {}) {
	db.prepare(
		`INSERT INTO retire_suggestions (product_id, first_flagged, last_seen, last_seen_retailer, decision, keep_until)
		 VALUES (@id, '2026-10-01', @lastSeen, @retailer, @decision, @keepUntil)`
	).run({ id, lastSeen: '2026-09-03', retailer: 'pccg', decision, keepUntil: null, ...extra });
}
const state = (id: number) =>
	db.prepare('SELECT decision, keep_until FROM retire_suggestions WHERE product_id = ?').get(id) as {
		decision: string;
		keep_until: string | null;
	};

beforeEach(() => {
	db = new Database(':memory:');
	db.exec(`
		CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, brand TEXT, model TEXT);
		CREATE TABLE retire_suggestions (
			product_id INTEGER PRIMARY KEY REFERENCES products(id),
			first_flagged TEXT NOT NULL, last_seen TEXT, last_seen_retailer TEXT,
			decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','requested','kept')),
			keep_until TEXT, notified INTEGER NOT NULL DEFAULT 0
		);`);
	addProduct(1, 'RX 6600');
	addProduct(2, 'RX 5700');
	addProduct(3, 'GTX 1650');
});
afterEach(() => db.close());

describe('isRetireAction', () => {
	it('accepts the three actions only', () => {
		for (const a of ['retire', 'keep', 'undo']) expect(isRetireAction(a)).toBe(true);
		for (const a of ['toString', 'delete', '', null, 4]) expect(isRetireAction(a)).toBe(false);
	});
});

describe('applyRetireAction', () => {
	it('retire: pending -> requested', () => {
		flag(1);
		expect(applyRetireAction(db, 1, 'retire', TODAY)).toBe('ok');
		expect(state(1)).toEqual({ decision: 'requested', keep_until: null });
	});
	it('keep: pending -> kept for 90 days', () => {
		flag(1);
		expect(applyRetireAction(db, 1, 'keep', TODAY)).toBe('ok');
		expect(state(1)).toEqual({ decision: 'kept', keep_until: '2027-01-04' });
	});
	it('undo: requested and kept -> pending, clearing keep_until', () => {
		flag(1, 'requested');
		flag(2, 'kept', { keepUntil: '2027-01-04' });
		expect(applyRetireAction(db, 1, 'undo', TODAY)).toBe('ok');
		expect(applyRetireAction(db, 2, 'undo', TODAY)).toBe('ok');
		expect(state(1)).toEqual({ decision: 'pending', keep_until: null });
		expect(state(2)).toEqual({ decision: 'pending', keep_until: null });
	});
	it('rejects every invalid transition and leaves the row alone', () => {
		flag(1, 'requested');
		flag(2, 'kept', { keepUntil: '2027-01-04' });
		flag(3, 'pending');
		expect(applyRetireAction(db, 1, 'retire', TODAY)).toBe('invalid');
		expect(applyRetireAction(db, 1, 'keep', TODAY)).toBe('invalid');
		expect(applyRetireAction(db, 2, 'retire', TODAY)).toBe('invalid');
		expect(applyRetireAction(db, 2, 'keep', TODAY)).toBe('invalid');
		expect(applyRetireAction(db, 3, 'undo', TODAY)).toBe('invalid');
		expect(state(1).decision).toBe('requested');
		expect(state(2)).toEqual({ decision: 'kept', keep_until: '2027-01-04' });
		expect(state(3).decision).toBe('pending');
	});
	it('unknown product id is not-found', () => {
		expect(applyRetireAction(db, 999, 'retire', TODAY)).toBe('not-found');
		expect(applyRetireAction(db, 999, 'keep', TODAY)).toBe('not-found');
	});
	it('missing table is not-found, not a throw', () => {
		db.exec('DROP TABLE retire_suggestions');
		expect(applyRetireAction(db, 1, 'retire', TODAY)).toBe('not-found');
	});
});

describe('getRetireSuggestions', () => {
	it('returns [] without the table', () => {
		db.exec('DROP TABLE retire_suggestions');
		expect(getRetireSuggestions(db, TODAY)).toEqual([]);
	});
	it('maps a row', () => {
		flag(1);
		expect(getRetireSuggestions(db, TODAY)).toEqual([
			{
				productId: 1,
				brand: 'AMD',
				category: 'gpu',
				model: 'RX 6600',
				firstFlagged: '2026-10-01',
				lastSeen: '2026-09-03',
				lastSeenRetailer: 'pccg',
				decision: 'pending',
				keepUntil: null
			}
		]);
	});
	it('hides kept rows until keep_until passes', () => {
		flag(1, 'kept', { keepUntil: '2026-10-07' });
		flag(2, 'kept', { keepUntil: TODAY });
		flag(3, 'kept', { keepUntil: '2026-10-05' });
		expect(getRetireSuggestions(db, TODAY).map((s) => s.productId)).toEqual([3, 2]);
	});
	it('orders pending before requested, then by model', () => {
		flag(1, 'requested');
		flag(2, 'pending');
		flag(3, 'pending');
		expect(getRetireSuggestions(db, TODAY).map((s) => s.model)).toEqual(['GTX 1650', 'RX 5700', 'RX 6600']);
	});
});
