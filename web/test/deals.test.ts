import { describe, it, expect } from 'vitest';
import {
	NEAR_ALL_TIME_LOW_PCT,
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	dealDepthPct,
	dealToOffer,
	filterDeals,
	isEligible,
	isNearAllTimeLow,
	toDeals
} from '../src/lib/deals';
import type { DealCandidate } from '../src/lib/server/repos';

function candidate(over: Partial<DealCandidate> = {}): DealCandidate {
	return {
		productId: 1,
		category: 'gpu',
		model: 'GeForce RTX Test',
		brand: 'NVIDIA',
		listingId: 10,
		variantName: 'ASUS RTX Test 16GB',
		retailer: 'scorptec',
		listingUrl: '/p/test',
		price: 900,
		snapshotDate: '2026-08-25',
		allTimeLow: 880,
		avg30: 1000,
		avg30Points: 10,
		...over
	};
}

describe('isEligible', () => {
	it('requires at least MIN_HISTORY_POINTS days of average', () => {
		expect(isEligible(candidate({ avg30Points: 3 }))).toBe(true);
		expect(isEligible(candidate({ avg30Points: 2 }))).toBe(false);
	});

	it('rejects a null average even with enough points', () => {
		expect(isEligible(candidate({ avg30: null, avg30Points: 10 }))).toBe(false);
	});
});

describe('dealDepthPct', () => {
	it('returns how far below the average the price sits, as a positive percent', () => {
		expect(dealDepthPct(900, 1000)).toBeCloseTo(10, 5);
	});

	it('returns a negative depth for a price above the average', () => {
		expect(dealDepthPct(1100, 1000)).toBeCloseTo(-10, 5);
	});

	it('returns null when the average is missing or zero', () => {
		expect(dealDepthPct(900, null)).toBeNull();
		expect(dealDepthPct(900, 0)).toBeNull();
	});
});

describe('isNearAllTimeLow', () => {
	it('accepts a price at the all-time low', () => {
		expect(isNearAllTimeLow(880, 880)).toBe(true);
	});

	it('accepts a price within 2% above the all-time low', () => {
		expect(isNearAllTimeLow(880 * 1.02, 880)).toBe(true);
	});

	it('rejects a price more than 2% above the all-time low', () => {
		expect(isNearAllTimeLow(880 * 1.021, 880)).toBe(false);
	});

	it('accepts a new all-time low below the recorded one', () => {
		expect(isNearAllTimeLow(800, 880)).toBe(true);
	});

	it('rejects when there is no all-time low', () => {
		expect(isNearAllTimeLow(880, null)).toBe(false);
	});

	it('pins the threshold constant at 2', () => {
		expect(NEAR_ALL_TIME_LOW_PCT).toBe(2);
	});
});

describe('toDeals / belowAverage', () => {
	it('drops ineligible candidates entirely', () => {
		const deals = toDeals([candidate({ avg30Points: 1 })]);
		expect(deals).toHaveLength(0);
	});

	it('ranks deepest discount first', () => {
		const deals = belowAverage(
			toDeals([
				candidate({ productId: 1, price: 950, avg30: 1000 }), // 5%
				candidate({ productId: 2, price: 700, avg30: 1000 }), // 30%
				candidate({ productId: 3, price: 900, avg30: 1000 }) // 10%
			])
		);
		expect(deals.map((d) => d.productId)).toEqual([2, 3, 1]);
	});

	it('excludes products at or above their average', () => {
		const deals = belowAverage(
			toDeals([
				candidate({ productId: 1, price: 1000, avg30: 1000 }),
				candidate({ productId: 2, price: 1100, avg30: 1000 })
			])
		);
		expect(deals).toHaveLength(0);
	});
});

describe('atAllTimeLow', () => {
	it('selects only the near-all-time-low deals, deepest first', () => {
		const deals = atAllTimeLow(
			toDeals([
				candidate({ productId: 1, price: 900, avg30: 1000, allTimeLow: 880 }), // >2% above
				candidate({ productId: 2, price: 880, avg30: 1000, allTimeLow: 880 }), // at low
				candidate({ productId: 3, price: 700, avg30: 1000, allTimeLow: 700 }) // at low, deeper
			])
		);
		expect(deals.map((d) => d.productId)).toEqual([3, 2]);
	});

	it('includes a product that is also below average — both claims are true', () => {
		const all = toDeals([candidate({ productId: 7, price: 700, avg30: 1000, allTimeLow: 700 })]);
		expect(belowAverage(all).map((d) => d.productId)).toEqual([7]);
		expect(atAllTimeLow(all).map((d) => d.productId)).toEqual([7]);
	});
});

describe('filterDeals', () => {
	const deals = toDeals([
		candidate({ productId: 1, category: 'gpu', retailer: 'scorptec', brand: 'NVIDIA' }),
		candidate({ productId: 2, category: 'cpu', retailer: 'pccg', brand: 'AMD' })
	]);

	it('returns everything when no facet is active', () => {
		expect(filterDeals(deals, { category: null, retailer: null, brand: null })).toHaveLength(2);
	});

	it('filters by category, retailer and brand', () => {
		expect(
			filterDeals(deals, { category: 'cpu', retailer: null, brand: null }).map((d) => d.productId)
		).toEqual([2]);
		expect(
			filterDeals(deals, { category: null, retailer: 'scorptec', brand: null }).map(
				(d) => d.productId
			)
		).toEqual([1]);
		expect(
			filterDeals(deals, { category: null, retailer: null, brand: 'AMD' }).map((d) => d.productId)
		).toEqual([2]);
	});
});

describe('categoryFacetCounts', () => {
	it('labels categories for display and counts them', () => {
		const counts = categoryFacetCounts(
			toDeals([
				candidate({ productId: 1, category: 'gpu' }),
				candidate({ productId: 2, category: 'gpu' }),
				candidate({ productId: 3, category: 'cpu' })
			])
		);
		expect(counts).toEqual([
			{ value: 'gpu', label: 'GPU', count: 2 },
			{ value: 'cpu', label: 'CPU', count: 1 }
		]);
	});
});

describe('dealToOffer', () => {
	it('presents a deal as an in-stock offer row', () => {
		const [deal] = toDeals([candidate()]);
		const offer = dealToOffer(deal);
		expect(offer).toMatchObject({
			listingId: 10,
			brand: 'NVIDIA',
			retailer: 'scorptec',
			listingUrl: '/p/test',
			latestPrice: 900,
			latestStock: 'in_stock',
			inStock: true,
			delisted: false,
			lastSeen: '2026-08-25',
			selected: false
		});
	});
});
