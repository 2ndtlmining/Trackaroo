import { describe, expect, it } from 'vitest';
import type { PriceBandPoint, ProductStats } from '../src/lib/server/repos';
import type { ListingDisplay } from '../src/lib/offers';
import { buildHeadline } from '../src/lib/productHeadline';
import { offer } from './helpers/offers';

function band(points: Array<[string, number, number]>): PriceBandPoint[] {
	return points.map(([date, low, high]) => ({
		date,
		low,
		high,
		cheapestInStock: low
	})) as PriceBandPoint[];
}

const STATS: ProductStats = { avg30: 1400, avg30Points: 30 };
const THIN_STATS: ProductStats = { avg30: 1400, avg30Points: 2 };

describe('buildHeadline', () => {
	it('takes the cheapest in-stock offer as the current price', () => {
		const offers: ListingDisplay[] = [
			offer({ listingId: 1, latestPrice: 1499, retailer: 'pccg' }),
			offer({ listingId: 2, latestPrice: 1299, retailer: 'scorptec' })
		];
		const h = buildHeadline(offers, band([['2026-08-23', 1249, 1689]]), STATS);
		expect(h.currentPrice).toBe(1299);
		expect(h.currentRetailer).toBe('scorptec');
	});

	it('ignores out-of-stock and delisted offers when picking the current price', () => {
		const offers: ListingDisplay[] = [
			offer({ listingId: 1, latestPrice: 999, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 2, latestPrice: 1, delisted: true, inStock: false }),
			offer({ listingId: 3, latestPrice: 1299 })
		];
		expect(buildHeadline(offers, band([['2026-08-23', 1249, 1689]]), STATS).currentPrice).toBe(1299);
	});

	it('derives all-time low and high across the whole band', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([
				['2026-03-12', 1249, 1500],
				['2026-08-23', 1300, 1689]
			]),
			STATS
		);
		expect(h.allTimeLow).toBe(1249);
		expect(h.allTimeHigh).toBe(1689);
	});

	it('computes the delta against the 30-day average', () => {
		const h = buildHeadline([offer({ latestPrice: 1288 })], band([['2026-08-23', 1249, 1689]]), STATS);
		expect(h.vsAvg30Pct).toBeCloseTo(-8, 1);
	});

	it('suppresses the 30-day delta below MIN_HISTORY_POINTS', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1288 })],
			band([['2026-08-23', 1249, 1689]]),
			THIN_STATS
		);
		expect(h.vsAvg30Pct).toBeNull();
		expect(h.avg30).toBeNull();
	});

	it('computes the delta above the all-time low', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.vsAllTimeLowPct).toBeCloseTo(4, 0);
	});

	it('positions the current price within the all-time range', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1469 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.rangePosition).toBeCloseTo(0.5, 2);
	});

	it('clamps the range position into 0..1 when today sits outside the recorded band', () => {
		const below = buildHeadline(
			[offer({ latestPrice: 1000 })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(below.rangePosition).toBe(0);
	});

	it('returns a null range position when high equals low, so the bar degrades to text', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([['2026-08-23', 1299, 1299]]),
			STATS
		);
		expect(h.rangePosition).toBeNull();
	});

	it('handles a product with no in-stock offers', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299, inStock: false, latestStock: 'out_of_stock' })],
			band([['2026-08-23', 1249, 1689]]),
			STATS
		);
		expect(h.currentPrice).toBeNull();
		expect(h.vsAvg30Pct).toBeNull();
		expect(h.rangePosition).toBeNull();
	});

	it('handles an empty band', () => {
		const h = buildHeadline([offer({ latestPrice: 1299 })], [], STATS);
		expect(h.allTimeLow).toBeNull();
		expect(h.allTimeHigh).toBeNull();
		expect(h.rangePosition).toBeNull();
		expect(h.vsAllTimeLowPct).toBeNull();
	});
});
