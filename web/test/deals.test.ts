import { describe, it, expect } from 'vitest';
import {
	NEAR_ALL_TIME_LOW_PCT,
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	dealDepthPct,
	dealToOffer,
	filterDeals,
	isAtNewLow,
	isEligible,
	isNearAllTimeLow,
	shownDeals,
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
		windowHigh: null,
		historyStart: null,
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

// M3 (28-Sep finding): earnedLow/isNearAllTimeLow allow a price up to 2%
// above the all-time low, but the "Lowest since" badge claims the price IS
// the all-time low. isAtNewLow is the stricter, zero-tolerance check the
// page uses to pick "Lowest since" vs "Near low since".
describe('isAtNewLow', () => {
	it('accepts a price at the all-time low', () => {
		expect(isAtNewLow(880, 880)).toBe(true);
	});

	it('accepts a new all-time low below the recorded one', () => {
		expect(isAtNewLow(800, 880)).toBe(true);
	});

	it('rejects a price above the all-time low, even within the near-low band', () => {
		expect(isAtNewLow(880 * 1.01, 880)).toBe(false);
	});

	it('rejects when there is no all-time low', () => {
		expect(isAtNewLow(880, null)).toBe(false);
	});
});

describe('Deal.atNewLow (M3, 28-Sep finding)', () => {
	it('is true when the price is at or below the all-time low', () => {
		const [deal] = toDeals([candidate({ price: 880, allTimeLow: 880 })]);
		expect(deal.atNewLow).toBe(true);
	});

	it('is false when the price is only within the near-low band', () => {
		const [deal] = toDeals([candidate({ price: 880 * 1.01, allTimeLow: 880 })]);
		expect(deal.nearAllTimeLow).toBe(true);
		expect(deal.atNewLow).toBe(false);
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

describe('deal floors (#6)', () => {
	it('drops a -0.1% ($0.13) move', () => {
		const d = toDeals([candidate({ price: 129.87, avg30: 130, avg30Points: 30 })]);
		expect(belowAverage(d)).toEqual([]);
	});
	it('drops 3% when it is under $10', () => {
		const d = toDeals([candidate({ price: 97, avg30: 100, avg30Points: 30 })]);
		expect(belowAverage(d)).toEqual([]);
	});
	it('keeps 2% and $10 together', () => {
		const d = toDeals([candidate({ price: 490, avg30: 500, avg30Points: 30 })]);
		expect(belowAverage(d).map((x) => x.savingAud)).toEqual([10]);
	});
});

describe('earned all-time low (#6)', () => {
	it('a price that never moved is not a new low', () => {
		const d = toDeals([
			candidate({ price: 300, avg30: 300, allTimeLow: 300, windowHigh: 300, avg30Points: 30 })
		]);
		expect(atAllTimeLow(d)).toEqual([]);
	});
	it('a drop from 3%+ higher is an earned low', () => {
		const d = toDeals([
			candidate({ price: 300, avg30: 302, allTimeLow: 300, windowHigh: 310, avg30Points: 30 })
		]);
		expect(atAllTimeLow(d)).toHaveLength(1);
	});
	it('a product that is also below average appears only there', () => {
		const d = toDeals([
			candidate({ price: 450, avg30: 500, allTimeLow: 450, windowHigh: 520, avg30Points: 30 })
		]);
		expect(belowAverage(d)).toHaveLength(1);
		expect(atAllTimeLow(d)).toEqual([]);
		expect(shownDeals(d)).toHaveLength(1);
		expect(belowAverage(d)[0].earnedLow).toBe(true);
	});
});

describe('atAllTimeLow', () => {
	// Changed for #6: atAllTimeLow now requires an EARNED low (windowHigh
	// at least EARNED_LOW_RISE_PCT above price), not just proximity to
	// allTimeLow, and product 1's higher avg30/windowHigh gap no longer
	// applies since it fails isNearAllTimeLow outright (>2% above the low).
	it('selects only earned near-all-time-low deals, deepest first (#6)', () => {
		const deals = atAllTimeLow(
			toDeals([
				candidate({ productId: 1, price: 900, avg30: 903, allTimeLow: 880, windowHigh: 930 }), // >2% above the low
				candidate({ productId: 2, price: 880, avg30: 882, allTimeLow: 880, windowHigh: 910 }), // at low, earned, not a real deal
				candidate({ productId: 3, price: 700, avg30: 703, allTimeLow: 700, windowHigh: 730 }) // at low, earned, deeper, not a real deal
			])
		);
		expect(deals.map((d) => d.productId)).toEqual([3, 2]);
	});

	// Changed for #6: a product that is both a real deal AND an earned low is
	// shown only once, under belowAverage — atAllTimeLow excludes it.
	it('a product that is also a real deal is shown only in belowAverage (#6)', () => {
		const all = toDeals([
			candidate({ productId: 7, price: 700, avg30: 1000, allTimeLow: 700, windowHigh: 1000 })
		]);
		expect(belowAverage(all).map((d) => d.productId)).toEqual([7]);
		expect(atAllTimeLow(all)).toEqual([]);
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
