import { describe, expect, it } from 'vitest';
import type { PriceBandPoint } from '../src/lib/server/repos';
import {
	addDays,
	asOfDate,
	dailyLows,
	lowSummary,
	whereToBuy,
	windowStats,
	type DailyLow
} from '../src/lib/buySignals';
import { offer } from './helpers/offers';

function lows(pairs: Array<[string, number]>): DailyLow[] {
	return pairs.map(([date, price]) => ({ date, price }));
}

describe('dailyLows', () => {
	it('keeps only days with an in-stock price, in band order', () => {
		const band: PriceBandPoint[] = [
			{ date: '2026-09-01', low: 700, high: 800, cheapestInStock: null },
			{ date: '2026-09-02', low: null, high: null, cheapestInStock: null },
			{ date: '2026-09-03', low: 690, high: 760, cheapestInStock: 690 }
		];
		expect(dailyLows(band)).toEqual(lows([['2026-09-01', 700], ['2026-09-03', 690]]));
	});
});

describe('addDays', () => {
	it('crosses month and year ends in UTC, whatever the local timezone', () => {
		expect(addDays('2026-09-30', 1)).toBe('2026-10-01');
		expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
		expect(addDays('2026-09-30', -29)).toBe('2026-09-01');
	});
});

describe('lowSummary', () => {
	const history = lows([
		['2026-08-09', 799],
		['2026-08-20', 699],
		['2026-09-01', 749],
		['2026-09-10', 699],
		['2026-09-29', 729]
	]);

	it('names the lowest price, the most recent day it was hit, and the first tracked day', () => {
		const s = lowSummary(history, 729)!;
		expect(s.low).toBe(699);
		expect(s.lowDate).toBe('2026-09-10');
		expect(s.since).toBe('2026-08-09');
		expect(s.pctAbove).toBeCloseTo(4.29, 2);
		expect(s.atLow).toBe(false);
	});

	it('says today IS the low when today matches or beats it', () => {
		expect(lowSummary(history, 699)!.atLow).toBe(true);
		expect(lowSummary(history, 650)!.atLow).toBe(true);
	});

	it('has no "today" figure when nothing is in stock (Review Focus 1)', () => {
		const s = lowSummary(history, null)!;
		expect(s.today).toBeNull();
		expect(s.pctAbove).toBeNull();
		expect(s.atLow).toBe(false);
	});

	it('is null with no price history at all (Review Focus 1)', () => {
		expect(lowSummary([], 500)).toBeNull();
	});
});

describe('windowStats', () => {
	const history = lows([
		['2026-06-15', 900], // outside 90 days of 2026-09-29
		['2026-07-10', 800],
		['2026-09-01', 740], // inside 30 days: the window is 2026-08-31 .. 2026-09-29
		['2026-09-05', 720],
		['2026-09-20', 700],
		['2026-09-29', 710]
	]);

	it('computes low, median and high over the inclusive N-day window ending asOf', () => {
		const w = windowStats(history, '2026-09-29', 30);
		// 2026-08-31 .. 2026-09-29 -> 740, 720, 700, 710
		expect(w).toEqual({ days: 30, points: 4, low: 700, median: 715, high: 740, enough: true });
	});

	it('widens to 90 days', () => {
		const w = windowStats(history, '2026-09-29', 90);
		// 2026-07-02 .. 2026-09-29 -> 800, 740, 720, 700, 710
		expect(w.points).toBe(5);
		expect(w.median).toBe(720);
		expect(w.high).toBe(800);
	});

	it('refuses to summarise fewer than MIN_HISTORY_POINTS days (Review Focus 1)', () => {
		const w = windowStats(lows([['2026-09-28', 700], ['2026-09-29', 690]]), '2026-09-29', 30);
		expect(w.enough).toBe(false);
		expect(w.points).toBe(2);
	});

	it('is empty, not NaN, with no data (Review Focus 1)', () => {
		expect(windowStats([], '2026-09-29', 30)).toEqual({
			days: 30,
			points: 0,
			low: null,
			median: null,
			high: null,
			enough: false
		});
	});
});

describe('asOfDate', () => {
	it('anchors on the newest snapshot across retailers, not the product’s own last day', () => {
		expect(asOfDate({ scorptec: '2026-09-29', pccg: '2026-09-27' }, lows([['2026-07-01', 1]]))).toBe(
			'2026-09-29'
		);
	});

	it('falls back to the product’s own last day, then to null', () => {
		expect(asOfDate({}, lows([['2026-07-01', 1]]))).toBe('2026-07-01');
		expect(asOfDate({}, [])).toBeNull();
	});
});

describe('whereToBuy', () => {
	it('gives each retailer its cheapest buyable price and counts, cheapest retailer first', () => {
		const rows = whereToBuy([
			offer({ listingId: 1, retailer: 'pccg', latestPrice: 749, listingUrl: 'p1' }),
			offer({ listingId: 2, retailer: 'pccg', latestPrice: 729, listingUrl: 'p2' }),
			offer({ listingId: 3, retailer: 'pccg', latestPrice: 700, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 4, retailer: 'scorptec', latestPrice: 719, listingUrl: 's1' }),
			offer({ listingId: 5, retailer: 'umart', latestPrice: 650, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 6, retailer: 'umart', latestPrice: 1, delisted: true, inStock: false })
		]);
		expect(rows).toEqual([
			{ retailer: 'scorptec', cheapest: 719, cheapestUrl: 's1', inStock: 1, listings: 1 },
			{ retailer: 'pccg', cheapest: 729, cheapestUrl: 'p2', inStock: 2, listings: 3 },
			// listed but nothing in stock: shown, last, with no price
			{ retailer: 'umart', cheapest: null, cheapestUrl: null, inStock: 0, listings: 1 }
		]);
	});

	it('leaves out a retailer whose only listings are delisted or stale', () => {
		expect(whereToBuy([offer({ retailer: 'pccg', stale: true, inStock: false })])).toEqual([]);
	});
});
