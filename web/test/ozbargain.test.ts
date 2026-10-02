import fs from 'node:fs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { SCHEMA_PATH } from './helpers/seed';
import {
	getBestInStockPrice,
	getLiveOzbDealByProduct,
	getOzbDeals
} from '../src/lib/server/queries/ozbargain';

// Melbourne-offset timestamps, as the pipeline writes them. Compared as dates.
const NOW = new Date('2026-10-03T12:00:00+10:00');
const hoursAgo = (h: number) => isoAt(NOW.getTime() - h * 3_600_000);
const daysAgo = (d: number) => hoursAgo(d * 24);
function isoAt(ms: number): string {
	// Render in +10:00 so the strings do NOT sort like UTC instants would.
	const d = new Date(ms + 10 * 3_600_000);
	return `${d.toISOString().slice(0, 19)}+10:00`;
}

let db: Database.Database;

beforeEach(() => {
	db = new Database(':memory:');
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	db.exec(`INSERT INTO products (id, category, brand, model, generation_tier, tracked) VALUES
		(1, 'gpu', 'NVIDIA', 'A', 'current', 1), (2, 'gpu', 'NVIDIA', 'B', 'current', 1),
		(3, 'gpu', 'NVIDIA', 'C', 'current', 1)`);
});
afterEach(() => db.close());

let nextNode = 1000;
function deal(over: Partial<Record<string, unknown>> = {}): number {
	const row = {
		node_id: nextNode++,
		category: 'gpu',
		title: 'MSI RTX 5070 Ventus $899 @ Amazon AU',
		price_aud: 899,
		retailer: 'Amazon AU',
		votes_pos: 10,
		votes_neg: 1,
		comment_count: 3,
		posted_at: hoursAgo(1),
		starts_at: null,
		expires_at: null,
		expired: 0,
		product_id: 1,
		first_seen_at: hoursAgo(1),
		last_seen_at: hoursAgo(1),
		alerted_at: null,
		...over
	};
	db.prepare(
		`INSERT INTO ozb_deals (node_id, category, title, url, price_aud, retailer, votes_pos, votes_neg,
		   comment_count, posted_at, starts_at, expires_at, expired, product_id, first_seen_at, last_seen_at, alerted_at)
		 VALUES (@node_id, @category, @title, @url, @price_aud, @retailer,
		   @votes_pos, @votes_neg, @comment_count, @posted_at, @starts_at, @expires_at, @expired, @product_id,
		   @first_seen_at, @last_seen_at, @alerted_at)`
	).run({ ...row, url: `https://www.ozbargain.com.au/node/${row.node_id}` });
	return row.node_id;
}

describe('getOzbDeals', () => {
	it('maps the row to the DTO', () => {
		const id = deal({ votes_pos: 42, votes_neg: 1 });
		const { live, expired } = getOzbDeals(db as any, 1, NOW);
		expect(expired).toEqual([]);
		expect(live).toEqual([
			{
				nodeId: id,
				title: 'MSI RTX 5070 Ventus $899 @ Amazon AU',
				url: `https://www.ozbargain.com.au/node/${id}`,
				priceAud: 899,
				retailer: 'Amazon AU',
				votesPos: 42,
				votesNeg: 1,
				postedAt: hoursAgo(1),
				expired: false
			}
		]);
	});

	it('splits live from expired, newest first, live capped at 5', () => {
		const ids = [5, 1, 7, 3, 2, 6].map((h) => [h, deal({ posted_at: hoursAgo(h) })] as const);
		const gone = deal({ expired: 1, last_seen_at: daysAgo(2) });
		deal({ product_id: 2 });
		const { live, expired } = getOzbDeals(db as any, 1, NOW);
		const byAge = [...ids].sort((a, b) => a[0] - b[0]).map(([, id]) => id);
		expect(live.map((d) => d.nodeId)).toEqual(byAge.slice(0, 5));
		expect(expired.map((d) => d.nodeId)).toEqual([gone]);
		expect(expired[0].expired).toBe(true);
	});

	it('orders by instant, not by string, across offsets', () => {
		// As strings 10:45 sorts after 10:30, but as instants it is earlier.
		const later = deal({ posted_at: '2026-10-03T10:30:00+10:00' }); // 00:30Z
		const earlier = deal({ posted_at: '2026-10-03T10:45:00+11:00' }); // 23:45Z the day before
		const { live } = getOzbDeals(db as any, 1, NOW);
		expect(live.map((d) => d.nodeId)).toEqual([later, earlier]);
	});

	it('keeps expired deals seen in the last 30 days, newest first, max 10', () => {
		const old = deal({ expired: 1, last_seen_at: daysAgo(31) });
		const recent = Array.from({ length: 12 }, (_, i) => deal({ expired: 1, last_seen_at: daysAgo(i + 1) }));
		const { expired } = getOzbDeals(db as any, 1, NOW);
		expect(expired.map((d) => d.nodeId)).toEqual(recent.slice(0, 10));
		expect(expired.map((d) => d.nodeId)).not.toContain(old);
	});

	it('leaves a deal that has not started yet out of live', () => {
		deal({ starts_at: hoursAgo(-5) });
		const started = deal({ starts_at: hoursAgo(2) });
		expect(getOzbDeals(db as any, 1, NOW).live.map((d) => d.nodeId)).toEqual([started]);
	});

	it('treats a date-expired deal (expired = 0, expiry in the past) as expired, not live', () => {
		deal({ expires_at: hoursAgo(1) });
		const open = deal({ expires_at: hoursAgo(-5) });
		const { live, expired } = getOzbDeals(db as any, 1, NOW);
		expect(live.map((d) => d.nodeId)).toEqual([open]);
		expect(expired).toHaveLength(1);
		expect(expired[0].expired).toBe(true);
	});

	it('treats a deal not seen in the feed for 8 days as expired, 6 days as live', () => {
		const stale = deal({ last_seen_at: daysAgo(8) });
		const fresh = deal({ last_seen_at: daysAgo(6) });
		deal({ last_seen_at: 'garbage' });
		const { live, expired } = getOzbDeals(db as any, 1, NOW);
		expect(live.map((d) => d.nodeId)).toEqual([fresh]);
		expect(expired.map((d) => d.nodeId)).toContain(stale);
		expect(expired.find((d) => d.nodeId === stale)?.expired).toBe(true);
	});

	it('keeps an upcoming deal out of both lists', () => {
		deal({ starts_at: hoursAgo(-5) });
		expect(getOzbDeals(db as any, 1, NOW)).toEqual({ live: [], expired: [] });
	});

	it('is empty, without throwing, when the table is missing', () => {
		const bare = new Database(':memory:');
		expect(getOzbDeals(bare as any, 1, NOW)).toEqual({ live: [], expired: [] });
		expect(getLiveOzbDealByProduct(bare as any, NOW).size).toBe(0);
		bare.close();
	});

	it('rethrows anything but "no such table"', () => {
		const odd = new Database(':memory:');
		odd.exec('CREATE TABLE ozb_deals (node_id INTEGER)');
		expect(() => getOzbDeals(odd as any, 1, NOW)).toThrow(/no such column/i);
		odd.close();
	});
});

describe('getLiveOzbDealByProduct', () => {
	it('picks the cheapest priced live deal per product and ignores null prices', () => {
		deal({ product_id: 1, price_aud: 999 });
		const cheap = deal({ product_id: 1, price_aud: 949 });
		deal({ product_id: 1, price_aud: null });
		deal({ product_id: 1, price_aud: 100, expired: 1 });
		deal({ product_id: 1, price_aud: 50, starts_at: hoursAgo(-1) });
		deal({ product_id: 1, price_aud: 40, expires_at: hoursAgo(1) });
		deal({ product_id: 1, price_aud: 30, last_seen_at: daysAgo(8) });
		deal({ product_id: null, price_aud: 10 });
		deal({ product_id: 2, price_aud: null });
		const map = getLiveOzbDealByProduct(db as any, NOW);
		expect([...map.keys()]).toEqual([1]);
		expect(map.get(1)?.nodeId).toBe(cheap);
		expect(map.get(1)?.priceAud).toBe(949);
	});
});

describe('getBestInStockPrice (same rule as the Python alert, R1/R7)', () => {
	function listing(id: number, productId: number, status: string, variant = 'Card') {
		db.prepare(
			`INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url, status)
			 VALUES (?, ?, 'scorptec', ?, ?, ?)`
		).run(id, productId, variant, `/p/${id}`, status);
	}
	function snap(listingId: number, date: string, price: number, stock = 'in_stock') {
		db.prepare(
			`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
			 VALUES (?, ?, ?, ?, ?)`
		).run(listingId, date, price, stock, `${date}T04:00:00Z`);
	}

	it('is the cheapest in-stock, non-bundle, active listing on the global latest date', () => {
		listing(1, 1, 'active');
		listing(2, 1, 'delisted');
		listing(3, 1, 'active', 'Card power bundle');
		listing(4, 1, 'active');
		snap(1, '2026-10-03', 900);
		snap(2, '2026-10-03', 700);
		snap(3, '2026-10-03', 600);
		snap(4, '2026-10-03', 500, 'out_of_stock');
		snap(4, '2026-10-02', 400);
		expect(getBestInStockPrice(db as any, 1)).toBe(900);
	});

	it('is null when the product has nothing in stock on the global latest date', () => {
		listing(1, 1, 'active');
		listing(2, 2, 'active');
		snap(1, '2026-10-02', 900);
		snap(2, '2026-10-03', 800);
		expect(getBestInStockPrice(db as any, 1)).toBeNull();
		expect(getBestInStockPrice(db as any, 3)).toBeNull();
	});
});
