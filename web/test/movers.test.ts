import { describe, it, expect } from 'vitest';
import {
	groupMoversByProduct,
	isUnknownMover,
	moverColumnValue,
	moversHref,
	parseMoverView,
	sortMovers,
	topMoversByProduct
} from '../src/lib/movers';
import { sortRows } from '../src/lib/tableSort';
import type { Mover } from '../src/lib/server/repos';

function mover(over: Partial<Mover> = {}): Mover {
	return {
		listingId: 1,
		productId: 1,
		category: 'gpu',
		brand: 'NVIDIA',
		model: 'GeForce RTX 5070',
		retailer: 'pccg',
		variantName: 'MSI GeForce RTX 5070 Ventus 3X OC GDDR7 12GB',
		listingUrl: 'https://example.com/1',
		oldPrice: 999,
		newPrice: 1449,
		change: 450,
		pctChange: 45,
		pointsInWindow: 7,
		historyPoints: 16,
		notEnoughHistory: false,
		windowStart: '2026-08-21',
		windowEnd: '2026-08-28',
		...over
	};
}

// The real shape that motivated this helper: PCCG lists three MSI RTX 5070
// SKUs, so the dashboard rendered "GeForce RTX 5070 / pccg" three times with
// three different percentages.
const THREE_5070S = [
	mover({ listingId: 303, pctChange: 45, variantName: 'MSI RTX 5070 Ventus 3X OC' }),
	mover({ listingId: 302, pctChange: 27.3, variantName: 'MSI RTX 5070 Shadow 2X OC' }),
	mover({ listingId: 301, pctChange: 26.6, variantName: 'MSI RTX 5070 Shadow 3X OC' })
];

describe('topMoversByProduct', () => {
	it('collapses several listings of one product into a single row', () => {
		const result = topMoversByProduct(THREE_5070S, 'gpu', 'up', 3);
		expect(result).toHaveLength(1);
	});

	it('keeps the largest move as the product representative', () => {
		const result = topMoversByProduct(THREE_5070S, 'gpu', 'up', 3);
		expect(result[0].listingId).toBe(303);
		expect(result[0].pctChange).toBe(45);
	});

	it('collapses across retailers, not just within one', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, retailer: 'pccg', pctChange: 10 }),
				mover({ listingId: 2, retailer: 'scorptec', pctChange: 20 })
			],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].retailer).toBe('scorptec');
	});

	it('keeps distinct products separate', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, productId: 1, model: 'RTX 5070', pctChange: 45 }),
				mover({ listingId: 2, productId: 2, model: 'RTX 5060', pctChange: 21.6 }),
				mover({ listingId: 3, productId: 3, model: 'RTX 3050', pctChange: 18.5 })
			],
			'gpu',
			'up',
			3
		);
		expect(result.map((m) => m.model)).toEqual(['RTX 5070', 'RTX 5060', 'RTX 3050']);
	});

	it('sorts rises by descending percentage', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, productId: 1, pctChange: 5 }),
				mover({ listingId: 2, productId: 2, pctChange: 30 }),
				mover({ listingId: 3, productId: 3, pctChange: 12 })
			],
			'gpu',
			'up',
			3
		);
		expect(result.map((m) => m.pctChange)).toEqual([30, 12, 5]);
	});

	it('sorts drops by most negative first', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, productId: 1, pctChange: -5 }),
				mover({ listingId: 2, productId: 2, pctChange: -30 }),
				mover({ listingId: 3, productId: 3, pctChange: -12 })
			],
			'gpu',
			'down',
			3
		);
		expect(result.map((m) => m.pctChange)).toEqual([-30, -12, -5]);
	});

	it('picks the steepest drop as the representative, not the steepest rise', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, pctChange: 40 }),
				mover({ listingId: 2, pctChange: -8 }),
				mover({ listingId: 3, pctChange: -3 })
			],
			'gpu',
			'down',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].listingId).toBe(2);
	});

	it('excludes the other direction', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, productId: 1, pctChange: 10 }),
				mover({ listingId: 2, productId: 2, pctChange: -10 })
			],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].pctChange).toBe(10);
	});

	it('excludes exactly-flat listings from both directions', () => {
		const flat = [mover({ pctChange: 0, change: 0 })];
		expect(topMoversByProduct(flat, 'gpu', 'up', 3)).toHaveLength(0);
		expect(topMoversByProduct(flat, 'gpu', 'down', 3)).toHaveLength(0);
	});

	it('excludes listings with no percentage', () => {
		const result = topMoversByProduct(
			[mover({ pctChange: null, change: null, oldPrice: null })],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(0);
	});

	// /movers badges these as "Not enough history"; the dashboard has no such
	// badge, so a thin listing would read as authoritative there.
	it('excludes listings without enough history', () => {
		const result = topMoversByProduct(
			[mover({ notEnoughHistory: true, historyPoints: 2 })],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(0);
	});

	it('falls back to a thinner listing when the biggest mover lacks history', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, pctChange: 45, notEnoughHistory: true }),
				mover({ listingId: 2, pctChange: 12, notEnoughHistory: false })
			],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].listingId).toBe(2);
	});

	it('filters to the requested category', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 1, productId: 1, category: 'gpu', pctChange: 10 }),
				mover({ listingId: 2, productId: 2, category: 'cpu', pctChange: 20 })
			],
			'cpu',
			'up',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].category).toBe('cpu');
	});

	it('respects the limit', () => {
		const many = Array.from({ length: 10 }, (_, i) =>
			mover({ listingId: i, productId: i, pctChange: i + 1 })
		);
		expect(topMoversByProduct(many, 'gpu', 'up', 3)).toHaveLength(3);
	});

	it('returns an empty array when nothing qualifies', () => {
		expect(topMoversByProduct([], 'gpu', 'up', 3)).toEqual([]);
	});

	it('breaks ties on equal percentage deterministically by listing id', () => {
		const result = topMoversByProduct(
			[
				mover({ listingId: 9, productId: 1, pctChange: 16.7 }),
				mover({ listingId: 4, productId: 1, pctChange: 16.7 })
			],
			'gpu',
			'up',
			3
		);
		expect(result).toHaveLength(1);
		expect(result[0].listingId).toBe(4);
	});

	it('does not mutate the input array', () => {
		const input = [...THREE_5070S];
		const snapshot = input.map((m) => m.listingId);
		topMoversByProduct(input, 'gpu', 'up', 3);
		expect(input.map((m) => m.listingId)).toEqual(snapshot);
	});
});

describe('sortMovers (#5)', () => {
	it.each(['abs', 'pct', 'price'] as const)('puts not-enough-history rows last under %s', (key) => {
		const rows = [
			mover({ listingId: 1, change: null, pctChange: null, notEnoughHistory: true, newPrice: 9999 }),
			mover({ listingId: 2, change: -50, pctChange: -5, newPrice: 950 }),
			mover({ listingId: 3, change: 20, pctChange: 2, newPrice: 1020 })
		];
		expect(sortMovers(rows, key).at(-1)!.listingId).toBe(1);
	});

	it('abs sorts by magnitude', () => {
		const rows = [mover({ listingId: 3, change: 20 }), mover({ listingId: 2, change: -50 })];
		expect(sortMovers(rows, 'abs').map((m) => m.listingId)).toEqual([2, 3]);
	});

	it('pct sorts by descending percentage change', () => {
		const rows = [
			mover({ listingId: 1, pctChange: 5 }),
			mover({ listingId: 2, pctChange: 30 }),
			mover({ listingId: 3, pctChange: -10 })
		];
		expect(sortMovers(rows, 'pct').map((m) => m.listingId)).toEqual([2, 1, 3]);
	});

	it('price sorts by descending new price', () => {
		const rows = [
			mover({ listingId: 1, newPrice: 500 }),
			mover({ listingId: 2, newPrice: 1500 }),
			mover({ listingId: 3, newPrice: 1000 })
		];
		expect(sortMovers(rows, 'price').map((m) => m.listingId)).toEqual([2, 3, 1]);
	});

	it('does not mutate the input array', () => {
		const rows = [mover({ listingId: 1, change: 5 }), mover({ listingId: 2, change: -50 })];
		const snapshot = rows.map((m) => m.listingId);
		sortMovers(rows, 'abs');
		expect(rows.map((m) => m.listingId)).toEqual(snapshot);
	});
});

describe('isUnknownMover / moverColumnValue (#5 fix round 1)', () => {
	// A 2-snapshot listing (< MIN_HISTORY_POINTS) can still carry a non-null
	// `change` (old vs. new price within the window) even though it's badged
	// "Not enough history" -- e.g. the e2e seed's "E2E Thin History GPU"
	// (1000 -> 600, 2 points). isUnknownMover must treat it as unknown
	// regardless of that non-null change.
	it('treats a notEnoughHistory row as unknown even with a non-null change', () => {
		const thin = mover({ notEnoughHistory: true, historyPoints: 2, change: -400, pctChange: -40 });
		expect(isUnknownMover(thin)).toBe(true);
	});

	it('treats a row with a real change and enough history as known', () => {
		const real = mover({ notEnoughHistory: false, historyPoints: 16, change: -400 });
		expect(isUnknownMover(real)).toBe(false);
	});

	it('moverColumnValue nulls the change column for an unknown row despite a non-null raw change', () => {
		const thin = mover({ notEnoughHistory: true, historyPoints: 2, change: -400 });
		expect(moverColumnValue(thin, 'change')).toBeNull();
	});

	it('moverColumnValue passes the change column through for a known row', () => {
		const real = mover({ notEnoughHistory: false, change: -400 });
		expect(moverColumnValue(real, 'change')).toBe(-400);
	});

	it('moverColumnValue does not null the old/new/points columns for an unknown row', () => {
		const thin = mover({
			notEnoughHistory: true,
			historyPoints: 2,
			change: -400,
			oldPrice: 1000,
			newPrice: 600
		});
		expect(moverColumnValue(thin, 'old')).toBe(1000);
		expect(moverColumnValue(thin, 'new')).toBe(600);
		expect(moverColumnValue(thin, 'points')).toBe(2);
	});

	// The actual bug: a notEnoughHistory row with a non-null change must sort
	// last under the Change column header in BOTH directions, not just one --
	// sortRows only pins a literal `null` last, so the fix has to be that
	// moverColumnValue returns null, not that the comparator special-cases it.
	it('sorts a notEnoughHistory row with a non-null change last under the Change header, both directions', () => {
		const rows = [
			mover({ listingId: 1, notEnoughHistory: true, historyPoints: 2, change: -400, pctChange: -40 }),
			mover({ listingId: 2, notEnoughHistory: false, change: -50 }),
			mover({ listingId: 3, notEnoughHistory: false, change: 20 })
		];
		const byChange = (m: Mover) => moverColumnValue(m, 'change');
		expect(sortRows(rows, 'asc', byChange).at(-1)!.listingId).toBe(1);
		expect(sortRows(rows, 'desc', byChange).at(-1)!.listingId).toBe(1);
	});
});

describe('parseMoverView (#26, Review Focus 3)', () => {
	it('reads sort, direction and grouping from the URL', () => {
		expect(parseMoverView(new URLSearchParams('sort=pct&dir=down&group=0'))).toEqual({
			sort: 'pct',
			dir: 'down',
			group: false
		});
	});

	it('falls back to the defaults for anything it does not know', () => {
		expect(parseMoverView(new URLSearchParams('sort=bogus&dir=sideways&group=maybe'))).toEqual({
			sort: 'abs',
			dir: 'all',
			group: true
		});
	});
});

describe('moversHref', () => {
	it('always names the window and only writes non-default view keys', () => {
		expect(moversHref('7d', { sort: 'abs', dir: 'all', group: true }, false)).toBe('?window=7d');
		expect(moversHref('30d', { sort: 'pct', dir: 'down', group: false }, true)).toBe(
			'?window=30d&sort=pct&dir=down&group=0&all=1'
		);
	});
});

describe('groupMoversByProduct (#5 item 4)', () => {
	const ordered = [
		mover({ listingId: 11, productId: 1, change: -90 }),
		mover({ listingId: 21, productId: 2, change: -50 }),
		mover({ listingId: 12, productId: 1, change: -40 }),
		mover({ listingId: 13, productId: 1, change: 10 })
	];

	it('keeps the given order: each product is led by its first row, groups in lead order', () => {
		const groups = groupMoversByProduct(ordered);
		expect(groups.map((g) => [g.productId, g.lead.listingId, g.rest.map((m) => m.listingId)])).toEqual([
			[1, 11, [12, 13]],
			[2, 21, []]
		]);
	});

	it('never mutates the memo-shared input (Review Focus 5)', () => {
		const frozen = Object.freeze(ordered.map((m) => Object.freeze({ ...m })));
		expect(() => groupMoversByProduct(frozen)).not.toThrow();
		expect(() => sortMovers(frozen, 'pct')).not.toThrow();
		expect(frozen.map((m) => m.listingId)).toEqual([11, 21, 12, 13]);
	});
});
