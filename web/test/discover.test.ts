// web/test/discover.test.ts
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { createSeededDb, type SeededDb } from './helpers/seed';
import {
	applyDiscoverAction,
	getDiscoverPage,
	getDiscoverPendingCount,
	isDiscoverAction,
	localIsoDate
} from '../src/lib/server/discover';

let seeded: SeededDb;

function insertPart(db: any, key: string, status: string, firstSeen: string, extra: Record<string, unknown> = {}) {
	return Number(
		db
			.prepare(
				`INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen,
				   listing_count, retailers, min_price, min_price_url, sample_titles, suggested_row)
				 VALUES (@category, @key, @name, @status, @firstSeen, @lastSeen, 3, 'pccg,scorptec', 389, 'https://x',
				   '["A title"]', 'gpu,NVIDIA,GeForce RTX 5050,8GB,current,"rtx 5050"')`
			)
			.run({ category: 'gpu', key, name: `Part ${key}`, status, firstSeen, lastSeen: firstSeen, ...extra })
			.lastInsertRowid
	);
}

beforeAll(() => {
	seeded = createSeededDb();
});
afterAll(() => seeded.close());
beforeEach(() => {
	seeded.db.exec('DELETE FROM discovered_parts; DELETE FROM discovery_conflicts; DELETE FROM discovery_runs;');
});

describe('getDiscoverPage', () => {
	it('splits parts by status, newest first, and counts new this week', () => {
		insertPart(seeded.db, 'rtx 5050|8', 'untracked', '2026-10-02');
		insertPart(seeded.db, 'ryzen 5600gt', 'untracked', '2026-08-09');
		insertPart(seeded.db, 'ultra 270k plus', 'requested', '2026-10-01');
		insertPart(seeded.db, 'rx 7600 xt|16', 'ignored', '2026-09-20');
		insertPart(seeded.db, 'rtx 5060|8', 'tracked', '2026-09-01');
		const page = getDiscoverPage(seeded.db, '2026-10-02');
		expect(page.untracked.map((p) => p.partKey)).toEqual(['rtx 5050|8', 'ryzen 5600gt']);
		expect(page.requested.map((p) => p.partKey)).toEqual(['ultra 270k plus']);
		expect(page.ignored.map((p) => p.partKey)).toEqual(['rx 7600 xt|16']);
		expect(page.newThisWeek).toBe(1);
		expect(page.untracked[0].retailers).toEqual(['pccg', 'scorptec']);
		expect(page.untracked[0].sampleTitles).toEqual(['A title']);
	});

	it('is stale without a run today, fresh with one', () => {
		expect(getDiscoverPage(seeded.db, '2026-10-02').isStale).toBe(true);
		seeded.db
			.prepare(
				`INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing) VALUES ('2026-10-02', '2026-10-02T04:41:00', 5, '["umart/gpu"]')`
			)
			.run();
		const page = getDiscoverPage(seeded.db, '2026-10-02');
		expect(page.isStale).toBe(false);
		expect(page.lastRun?.missing).toEqual(['umart/gpu']);
	});

	it('is stale when the run today saw no catalogues', () => {
		seeded.db
			.prepare(
				`INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing) VALUES ('2026-10-02', '2026-10-02T04:41:00', 0, '[]')`
			)
			.run();
		const page = getDiscoverPage(seeded.db, '2026-10-02');
		expect(page.isStale).toBe(true);
		expect(page.lastRun?.catalogueFiles).toBe(0);
	});

	it('returns conflicts with the filed product model', () => {
		const listing = seeded.db
			.prepare('SELECT l.id, l.product_id, p.model FROM retailer_listings l JOIN products p ON p.id = l.product_id LIMIT 1')
			.get() as { id: number; product_id: number; model: string };
		seeded.db
			.prepare(
				`INSERT INTO discovery_conflicts VALUES (?, 'scorptec', ?, 'rx 9070 gre', 'title names rx 9070 gre, product is rx 9070', 'Sapphire RX 9070 GRE', '2026-10-02')`
			)
			.run(listing.id, listing.product_id);
		const [c] = getDiscoverPage(seeded.db, '2026-10-02').conflicts;
		expect(c.filedModel).toBe(listing.model);
		expect(c.reason).toContain('rx 9070 gre');
	});

	it('returns empty data when the tables do not exist (old DB)', () => {
		const bare = new Database(':memory:');
		const page = getDiscoverPage(bare, '2026-10-02');
		expect(page.untracked).toEqual([]);
		expect(page.lastRun).toBeNull();
		expect(getDiscoverPendingCount(bare)).toBe(0);
	});
});

describe('applyDiscoverAction', () => {
	it('follows the allowed transitions', () => {
		const id = insertPart(seeded.db, 'rtx 5050|8', 'untracked', '2026-10-02');
		expect(applyDiscoverAction(seeded.db, id, 'track', '2026-10-02T10:00:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'track', '2026-10-02T10:00:00')).toBe('invalid');
		expect(applyDiscoverAction(seeded.db, id, 'untrack', '2026-10-02T10:01:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'ignore', '2026-10-02T10:02:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'unignore', '2026-10-02T10:03:00')).toBe('ok');
		const row = seeded.db.prepare('SELECT status, decided_at FROM discovered_parts WHERE id = ?').get(id) as any;
		expect(row).toEqual({ status: 'untracked', decided_at: '2026-10-02T10:03:00' });
	});

	it('refuses tracked parts and unknown ids', () => {
		const id = insertPart(seeded.db, 'rtx 5060|8', 'tracked', '2026-09-01');
		expect(applyDiscoverAction(seeded.db, id, 'ignore', 'x')).toBe('invalid');
		expect(applyDiscoverAction(seeded.db, 999999, 'ignore', 'x')).toBe('not-found');
	});

	it('pending count is untracked only', () => {
		insertPart(seeded.db, 'a', 'untracked', '2026-10-02');
		insertPart(seeded.db, 'b', 'requested', '2026-10-02');
		expect(getDiscoverPendingCount(seeded.db)).toBe(1);
	});
});

describe('helpers', () => {
	it('validates actions', () => {
		expect(isDiscoverAction('ignore')).toBe(true);
		expect(isDiscoverAction('delete')).toBe(false);
		expect(isDiscoverAction('constructor')).toBe(false);
		expect(isDiscoverAction('__proto__')).toBe(false);
	});
	it('formats a local date', () => {
		expect(localIsoDate(new Date(2026, 9, 2, 23, 30))).toBe('2026-10-02');
	});
});
