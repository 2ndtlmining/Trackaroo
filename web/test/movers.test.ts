import { describe, it, expect } from 'vitest';
import { topMoversByProduct } from '../src/lib/movers';
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
