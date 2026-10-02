// #30 Task 4: the shared "daily cheapest in stock" fragment, run for every
// option set its call sites use, on the seeded DB plus one planted bundle
// listing priced far below everything else.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createSeededDb, type SeededDb } from './helpers/seed';
import {
	cheapestListingPerProduct,
	dailyCheapestInStock,
	MAX_SNAPSHOT_DATE,
	notBundle,
	type DailyCheapestOpts
} from '../src/lib/server/queries/sql';

let seeded: SeededDb;
let productId: number;
let maxDate: string;
const PLANTED = 1.23;

beforeAll(() => {
	seeded = createSeededDb();
	const db = seeded.db;
	productId = (db.prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY id LIMIT 1').get() as { id: number }).id;
	maxDate = (db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get() as { d: string }).d;
});
afterAll(() => seeded.close());

// Plants one in-stock listing at PLANTED on the latest date, runs `fn`, then removes it.
function withPlanted<T>(variantName: string, url: string, fn: () => T): T {
	const db = seeded.db;
	const listingId = Number(
		db
			.prepare("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) VALUES (?, 'scorptec', ?, ?, 'active')")
			.run(productId, variantName, url).lastInsertRowid
	);
	db.prepare("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at) VALUES (?, ?, ?, 'in_stock', ?)").run(
		listingId,
		maxDate,
		PLANTED,
		`${maxDate}T04:00:00.000Z`
	);
	try {
		return fn();
	} finally {
		db.prepare('DELETE FROM price_snapshots WHERE retailer_listing_id = ?').run(listingId);
		db.prepare('DELETE FROM retailer_listings WHERE id = ?').run(listingId);
	}
}

// The correlated form references the outer p.id, so (like its call sites) it
// only runs nested in a scalar subquery over products p. Rows come back via JSON.
function correlated(sql: string, columns: string[], bind: unknown): Array<Record<string, unknown>> {
	const obj = columns.map((c) => `'${c}', dm.${c}`).join(', ');
	const pid = typeof bind === 'object' ? '@pid' : '?';
	const row = seeded.db
		.prepare(`SELECT (SELECT json_group_array(json_object(${obj})) FROM (${sql}) dm) AS j FROM products p WHERE p.id = ${pid}`)
		.get(bind) as { j: string };
	return JSON.parse(row.j);
}

// One entry per call-site option set, with how to bind it and run it for productId.
const SITES: Array<{ name: string; opts: DailyCheapestOpts; run: (sql: string) => Array<Record<string, unknown>> }> = [
	{
		name: 'getProductStats',
		opts: { form: 'standalone', product: '= ?', window: '?' },
		run: (sql) => seeded.db.prepare(sql).all(productId, '-29 days') as Array<Record<string, unknown>>
	},
	{
		name: 'getProductDealStats',
		opts: { form: 'standalone', product: 'IN (?)', perProduct: true, window: '?' },
		run: (sql) => seeded.db.prepare(sql).all(productId, '-29 days') as Array<Record<string, unknown>>
	},
	{
		name: 'getPriceBand latest day',
		opts: { form: 'standalone', product: '= ?', window: null, dateAs: 'date' },
		run: (sql) => seeded.db.prepare(sql).all(productId) as Array<Record<string, unknown>>
	},
	{
		name: 'getCheapestPerModel avg30',
		opts: { form: 'correlated', product: '= p.id', window: "'-30 days'" },
		run: (sql) => correlated(sql, ['snapshot_date', 'price'], productId)
	},
	{
		name: 'getDealCandidates avg30/window_high',
		opts: { form: 'correlated', product: '= p.id', window: '@window' },
		run: (sql) => correlated(sql, ['snapshot_date', 'price'], { window: '-29 days', pid: productId })
	},
	{
		name: 'getProductMoves day_min',
		opts: { form: 'standalone', perProduct: true, window: '@window', dateAs: 'date', anchor: '(SELECT d FROM maxd)' },
		run: (sql) =>
			(
				seeded.db
					.prepare(`WITH maxd AS (SELECT MAX(snapshot_date) AS d FROM price_snapshots), day_min AS (${sql}) SELECT * FROM day_min`)
					.all({ window: '-7 days' }) as Array<Record<string, unknown>>
			).filter((r) => r.product_id === productId)
	}
];

describe('dailyCheapestInStock', () => {
	for (const site of SITES) {
		it(`${site.name}: runs, returns its columns, excludes bundles`, () => {
			const sql = dailyCheapestInStock(site.opts);
			const rows = site.run(sql);
			expect(rows.length).toBeGreaterThan(0);
			const dateCol = site.opts.dateAs ?? 'snapshot_date';
			const expected = [...(site.opts.perProduct ? ['product_id'] : []), dateCol, 'price'];
			expect(Object.keys(rows[0])).toEqual(expected);

			const latestPrice = (rs: Array<Record<string, unknown>>) => rs.find((r) => r[dateCol] === maxDate)?.price;
			expect(latestPrice(rows)).not.toBe(PLANTED);
			// Positive control: an ordinary listing at the planted price does win the day...
			expect(withPlanted('Plain card', 'https://example/plain', () => latestPrice(site.run(sql)))).toBe(PLANTED);
			// ...while bundle-shaped titles and URLs never do.
			for (const [title, url] of [
				['Ryzen power bundle', 'https://example/x'],
				['CPU combo deal', 'https://example/y'],
				['Plain', 'https://example/some-bundle'],
				['Plain', 'https://example/bdl-123']
			]) {
				expect(withPlanted(title, url, () => latestPrice(site.run(sql))), `${title} ${url}`).not.toBe(PLANTED);
			}
		});
	}

	it('dateOnly drops the price column but keeps one row per day', () => {
		const opts: DailyCheapestOpts = { form: 'correlated', product: '= p.id', window: "'-30 days'" };
		const days = correlated(dailyCheapestInStock({ ...opts, dateOnly: true }), ['snapshot_date'], productId);
		expect(days.length).toBeGreaterThan(0);
		expect(days).toEqual(correlated(dailyCheapestInStock(opts), ['snapshot_date', 'price'], productId).map((r) => ({ snapshot_date: r.snapshot_date })));
	});

	it('anchors on the latest snapshot date by default', () => {
		expect(dailyCheapestInStock({ form: 'standalone', window: '?' })).toContain(`date(${MAX_SNAPSHOT_DATE}, ?)`);
	});
});

describe('cheapestListingPerProduct', () => {
	it('returns one row per product and skips bundle listings', () => {
		const sql = cheapestListingPerProduct('p.id AS product_id, l.variant_name, ps.price_aud AS price');
		const pick = () => (seeded.db.prepare(sql).all() as Array<{ product_id: number; price: number }>).find((r) => r.product_id === productId);
		const rows = seeded.db.prepare(sql).all() as Array<{ product_id: number }>;
		expect(new Set(rows.map((r) => r.product_id)).size).toBe(rows.length);
		expect(withPlanted('Plain card', 'https://example/plain', pick)?.price).toBe(PLANTED);
		expect(withPlanted('Ryzen power bundle', 'https://example/x', pick)?.price).not.toBe(PLANTED);
	});

	it('applies the extra where clause', () => {
		const sql = cheapestListingPerProduct('p.id AS product_id, p.category', 'p.category = @category');
		const rows = seeded.db.prepare(sql).all({ category: 'cpu' }) as Array<{ category: string }>;
		expect(rows.length).toBeGreaterThan(0);
		expect(rows.every((r) => r.category === 'cpu')).toBe(true);
	});
});

describe('notBundle', () => {
	it('uses the alias it is given', () => {
		expect(notBundle('l3')).toContain('lower(l3.variant_name)');
		expect(notBundle('l3')).not.toContain('lower(l.');
	});
});
