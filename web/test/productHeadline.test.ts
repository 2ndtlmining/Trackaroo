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

	// The range must compare like with like. `current` is the cheapest offer
	// available today, so the band it sits in has to be the history of the
	// cheapest offer -- not the dearest listing any retailer ever asked, which
	// would pin the marker to the left on almost every product.
	it('derives the range from the cheapest-per-day series, not the dearest listing', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([
				['2026-03-12', 1249, 1500],
				['2026-08-23', 1300, 1689]
			]),
			STATS
		);
		expect(h.allTimeLow).toBe(1249);
		// 1300 is the highest the *cheapest* price has been; 1689 was merely the
		// dearest listing on one day and must not define the top of the range.
		expect(h.allTimeHigh).toBe(1300);
	});

	it('counts the days of price history behind the range', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([
				['2026-03-12', 1249, 1500],
				['2026-08-23', 1300, 1689]
			]),
			STATS
		);
		expect(h.pricePoints).toBe(2);
	});

	it('reports a flat range when the cheapest price has never moved', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1299 })],
			band([
				['2026-08-21', 1299, 1450],
				['2026-08-22', 1299, 1460],
				['2026-08-23', 1299, 1470]
			]),
			STATS
		);
		expect(h.allTimeLow).toBe(1299);
		expect(h.allTimeHigh).toBe(1299);
		expect(h.rangePosition).toBeNull();
		// Three days of evidence, not one -- the copy must not claim otherwise.
		expect(h.pricePoints).toBe(3);
	});

	it('exposes the day count backing the average so the label can be honest', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1288 })],
			band([['2026-08-23', 1249, 1689]]),
			{ avg30: 1400, avg30Points: 17 }
		);
		expect(h.avgPoints).toBe(17);
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

	it('positions the current price within the cheapest-price range', () => {
		const h = buildHeadline(
			[offer({ latestPrice: 1469 })],
			band([
				['2026-08-22', 1249, 1689],
				['2026-08-23', 1689, 1800]
			]),
			STATS
		);
		// Cheapest series spans 1249..1689; 1469 is the midpoint.
		expect(h.rangePosition).toBeCloseTo(0.5, 2);
	});

	it('clamps the range position into 0..1 when today sits outside the recorded band', () => {
		const below = buildHeadline(
			[offer({ latestPrice: 1000 })],
			band([
				['2026-08-22', 1249, 1689],
				['2026-08-23', 1689, 1800]
			]),
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
