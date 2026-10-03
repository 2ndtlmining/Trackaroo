import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import { mount, unmount } from 'svelte';
import Database from 'better-sqlite3';
import PriceRangeBar from '../src/lib/components/PriceRangeBar.svelte';
import ProductRow from '../src/lib/components/ProductRow.svelte';
import { RANGE_SEGMENTS, filledSegment } from '../src/lib/rangeBar';
import { getRange90 } from '../src/lib/server/repos';
import { _resetMemo } from '../src/lib/server/cache';
import { SCHEMA_PATH } from './helpers/seed';

function render(Component: unknown, props: Record<string, unknown>): string {
	const target = document.createElement('div');
	const comp = mount(Component as never, { target, props });
	const html = target.innerHTML;
	unmount(comp);
	return html;
}

describe('filledSegment', () => {
	it('maps a position in [0,1] onto 0..5', () => {
		expect(RANGE_SEGMENTS).toBe(6);
		expect(filledSegment(0)).toBe(0);
		expect(filledSegment(0.49)).toBe(2);
		expect(filledSegment(0.5)).toBe(3);
		expect(filledSegment(1)).toBe(5);
		expect(filledSegment(null)).toBeNull();
	});
	it('never yields NaN or an out-of-range segment', () => {
		expect(filledSegment(Number.NaN)).toBeNull();
		expect(filledSegment(-3)).toBe(0);
		expect(filledSegment(7)).toBe(5);
	});
});

describe('PriceRangeBar segments', () => {
	const props = { low: 1000, high: 2000, current: 1250, position: 0.25, points: 30 };
	const segs = (html: string) => html.match(/data-segment="\d"/g) ?? [];

	it('renders 6 segments with the filled one toned by index', () => {
		const html = render(PriceRangeBar, props);
		expect(segs(html)).toHaveLength(6);
		expect(html.match(/data-filled="true"/g)).toHaveLength(1);
		expect(html).toMatch(/data-segment="1"[^>]*data-filled="true"/);
		expect(html).toContain('Lowest day');
		expect(html).toContain('$1,250');
	});
	it.each([
		[0.0, 'bg-down'],
		[0.4, 'bg-accent'],
		[0.9, 'bg-up']
	])('position %s fills with %s', (position, cls) => {
		const html = render(PriceRangeBar, { ...props, position });
		const m = html.match(/<span[^>]*data-filled="true"[^>]*>/);
		expect(m?.[0]).toContain(cls);
	});
	it('keeps the aria-label wording', () => {
		const html = render(PriceRangeBar, props);
		expect(html).toMatch(
			/aria-label="Today(&#39;|')s cheapest price \$1,250\. Over 30 days the cheapest price per day ranged from \$1,000 to \$2,000\."/
		);
	});
	it('flat range or null position keeps the wording and has no segments', () => {
		const html = render(PriceRangeBar, { ...props, low: 1250, high: 1250, position: null });
		expect(segs(html)).toHaveLength(0);
		expect(html).toContain('for all');
		expect(render(PriceRangeBar, { ...props, position: null, points: 1 })).toContain(
			'Only one price recorded'
		);
	});
	it('compact steady wording quotes the range value, not the shown price', () => {
		const html = render(PriceRangeBar, {
			low: 1250,
			high: 1250,
			current: 1300,
			position: null,
			points: 30,
			size: 'compact'
		});
		expect(html).toContain('Steady at');
		expect(html).toContain('$1,250');
		expect(html).not.toContain('$1,300');
	});
	it('compact single-price wording is short and never wraps', () => {
		const html = render(PriceRangeBar, {
			low: 1250,
			high: 1250,
			current: 1300,
			position: null,
			points: 1,
			size: 'compact'
		});
		expect(html).toContain('1 price:');
		expect(html).not.toContain('Only one price');
		expect(html).toContain('whitespace-nowrap');
		expect(html).toContain('$1,250');
	});
	it('compact size is a 96px bar with a visible label', () => {
		const html = render(PriceRangeBar, { ...props, size: 'compact' });
		expect(segs(html)).toHaveLength(6);
		expect(html).toContain('w-24');
		expect(html).toContain('$1,000');
		expect(html).toContain('$2,000');
	});
});

describe('ProductRow range bar', () => {
	const row = {
		productId: 7,
		category: 'gpu' as const,
		brand: 'NVIDIA',
		model: 'GeForce RTX 5070',
		productVariant: null,
		generationTier: 'current' as const,
		cheapestInStockPrice: 1250,
		cheapestInStockRetailer: 'scorptec' as const,
		inStockCount: 3,
		avg30: 1300,
		avg30Points: 20,
		neverListed: false,
		vramGb: 12,
		launchDate: null,
		listingCount: 5
	};
	const bar = (html: string) => (html.match(/data-segment="\d"/g) ?? []).length;

	it('shows 6 segments against the shown price when range90 exists', () => {
		const html = render(ProductRow, { group: { ...row, range90: { low: 1000, high: 2000, days: 42 } } });
		expect(bar(html)).toBe(6);
		expect(html).toContain('data-testid="row-range"');
		expect(html).toContain('Over 42 days the cheapest price per day');
	});
	it('clamps a shown price outside the range', () => {
		const html = render(ProductRow, {
			group: { ...row, range90: { low: 1500, high: 2000, days: 42 } },
			price: 1200
		});
		expect(html).toMatch(/data-segment="0"[^>]*data-filled="true"/);
	});
	it('flat range uses the steady wording, never NaN', () => {
		const html = render(ProductRow, { group: { ...row, range90: { low: 1250, high: 1250, days: 42 } } });
		expect(bar(html)).toBe(0);
		expect(html).not.toContain('NaN');
		expect(html).toContain('Steady');
	});
	it('a single day of history uses the single-reading wording, not Steady', () => {
		const html = render(ProductRow, { group: { ...row, range90: { low: 1250, high: 1250, days: 1 } } });
		expect(bar(html)).toBe(0);
		expect(html).not.toContain('Steady');
		expect(html).toContain('1 price:');
	});
	it('an out-of-stock shown price renders no bar (never a deal cue)', () => {
		const html = render(ProductRow, {
			group: { ...row, range90: { low: 1000, high: 2000, days: 42 } },
			price: 1010,
			outOfStock: true
		});
		expect(bar(html)).toBe(0);
		expect(html).not.toContain('bg-down');
		expect(html).toContain('data-testid="row-range"');
	});
	it('no range90 or no shown price shows no bar', () => {
		expect(bar(render(ProductRow, { group: { ...row, range90: null } }))).toBe(0);
		expect(bar(render(ProductRow, { group: row }))).toBe(0);
		expect(
			bar(render(ProductRow, { group: { ...row, range90: { low: 1, high: 2, days: 5 } }, price: null }))
		).toBe(0);
	});
});

describe('getRange90', () => {
	let db: Database.Database;
	let listing = 0;
	beforeEach(() => {
		_resetMemo();
		db = new Database(':memory:');
		db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
		for (const id of [1, 2, 3, 4]) {
			db.prepare(
				`INSERT INTO products (id, category, brand, model, generation_tier, tracked) VALUES (?, 'gpu', 'X', ?, 'current', 1)`
			).run(id, `M${id}`);
		}
		listing = 0;
	});
	afterEach(() => db.close());

	function add(
		productId: number,
		opts: { status?: string; name?: string; url?: string },
		snaps: Array<[string, number, string?]>
	) {
		listing++;
		const r = db
			.prepare(
				`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
				 VALUES (?, 'scorptec', ?, ?, ?)`
			)
			.run(productId, opts.name ?? 'Card', opts.url ?? `https://x/${listing}`, opts.status ?? 'active');
		for (const [date, price, stock] of snaps) {
			db.prepare(
				`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
				 VALUES (?, ?, ?, ?, ?)`
			).run(r.lastInsertRowid, date, price, stock ?? 'in_stock', `${date}T04:00:00Z`);
		}
	}

	it('takes min and max of the daily cheapest, one entry per product', () => {
		add(1, {}, [['2026-10-01', 900], ['2026-09-20', 800], ['2026-09-10', 1000]]);
		add(1, {}, [['2026-09-20', 850], ['2026-09-10', 950]]);
		// daily cheapest: 10-01 900, 09-20 min(800,850)=800, 09-10 min(1000,950)=950
		expect(getRange90(db as any).get(1)).toEqual({ low: 800, high: 950, days: 3 });
	});
	it('counts only in-stock, active, non-bundle listings', () => {
		add(1, {}, [['2026-10-01', 500]]);
		add(1, {}, [['2026-10-01', 100, 'out_of_stock']]);
		add(1, { status: 'delisted' }, [['2026-10-01', 90]]);
		add(1, { name: 'CPU power bundle' }, [['2026-10-01', 80]]);
		add(1, { url: 'https://x/bdl-1' }, [['2026-10-01', 70]]);
		expect(getRange90(db as any).get(1)).toEqual({ low: 500, high: 500, days: 1 });
	});
	it('excludes data older than 90 days, keeping day 89', () => {
		add(1, {}, [['2026-10-01', 600], ['2026-07-04', 400], ['2026-07-03', 300]]);
		// 2026-10-01 minus 89 days = 2026-07-04
		expect(getRange90(db as any).get(1)).toEqual({ low: 400, high: 600, days: 2 });
	});
	it('omits products with no history and allows low = high', () => {
		add(2, {}, [['2026-10-01', 750]]);
		add(3, {}, [['2026-01-01', 750]]);
		const m = getRange90(db as any);
		expect(m.has(4)).toBe(false);
		expect(m.has(3)).toBe(false);
		expect(m.get(2)).toEqual({ low: 750, high: 750, days: 1 });
	});
	it('filters by product ids', () => {
		add(1, {}, [['2026-10-01', 700]]);
		add(2, {}, [['2026-10-01', 800]]);
		expect([...getRange90(db as any, [2]).keys()]).toEqual([2]);
	});
});
