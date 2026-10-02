import { describe, expect, it } from 'vitest';
import type { PriceBandPoint } from '../src/lib/server/repos';
import {
	addDays,
	asOfDate,
	buildSignals,
	dailyLows,
	lowestInDays,
	pricePercentile,
	trend7,
	lowSummary,
	whereToBuy,
	windowStats,
	type DailyLow
} from '../src/lib/buySignals';
import { offer } from './helpers/offers';
import { SUCCESSORS } from '../src/lib/successors';

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

const ten = lows(
	[100, 90, 80, 70, 60, 50, 40, 30, 20, 10].map((p, i): [string, number] => [`2026-09-${String(i + 1).padStart(2, '0')}`, p])
);
// A quiet date: no sale event within 21 days.
const QUIET = new Date('2026-09-10T00:00:00Z');

describe('pricePercentile', () => {
	it('is the share of window days with a higher low, and the span', () => {
		expect(pricePercentile(ten, 55, '2026-09-10')).toEqual({ pct: 50, days: 10 });
		expect(pricePercentile(ten, 5, '2026-09-10')).toEqual({ pct: 100, days: 10 });
	});
	it('caps the window at 180 days', () => {
		const long: DailyLow[] = [];
		for (let i = 0; i < 300; i++) long.push({ date: addDays('2026-01-01', i), price: 100 });
		expect(pricePercentile(long, 100, '2026-10-28')?.days).toBe(180);
	});
	it('is null under the history gate', () => {
		expect(pricePercentile(ten.slice(0, 2), 50, '2026-09-02')).toBeNull();
	});
});

describe('lowestInDays', () => {
	it('says since tracking began when no lower day exists', () => {
		expect(lowestInDays(ten, 10, '2026-09-10')).toEqual({ days: 10, sinceStart: true });
	});
	it('counts days since the last lower price', () => {
		expect(lowestInDays(lows([['2026-09-01', 50], ['2026-09-05', 90], ['2026-09-10', 80]]), 80, '2026-09-10'))
			.toEqual({ days: 9, sinceStart: false });
	});
	it('is null with no history', () => {
		expect(lowestInDays([], 80, '2026-09-10')).toBeNull();
	});
});

describe('trend7', () => {
	const t = (a: number, b: number) => trend7(lows([['2026-09-04', a], ['2026-09-10', b]]), '2026-09-10');
	it('classifies falling, flat and rising', () => {
		expect(t(100, 96)).toMatchObject({ dir: 'falling', change: -4 });
		expect(t(100, 100.5)).toMatchObject({ dir: 'flat', change: 0.5 });
		expect(t(100, 103)).toMatchObject({ dir: 'rising', change: 3 });
	});
	it('is null with fewer than 2 points in 7 days', () => {
		expect(trend7(lows([['2026-09-01', 100], ['2026-09-10', 90]]), '2026-09-10')).toBeNull();
	});
});

describe('buildSignals', () => {
	const base = { asOf: '2026-09-10', avg30: 100, series: null, now: QUIET };
	it('gives exactly one gathering signal below the gate', () => {
		const s = buildSignals({ ...base, lows: ten.slice(0, 2), today: 50 });
		expect(s).toHaveLength(1);
		expect(s[0]).toMatchObject({ key: 'gathering', tone: 'neutral', icon: 'dash', claim: 'Gathering history (2 days)' });
	});
	it('maps tones and icons; every signal has evidence and no emoji', () => {
		const s = buildSignals({ ...base, lows: ten, today: 10, avg30: 100 });
		const by = Object.fromEntries(s.map((x) => [x.key, x]));
		expect(by.percentile).toMatchObject({ tone: 'good', icon: 'check' });
		expect(by.lowest).toMatchObject({ tone: 'neutral', icon: 'dash', claim: 'Lowest since tracking began' });
		expect(by.avg).toMatchObject({ tone: 'good', icon: 'check' });
		expect(by.trend).toMatchObject({ tone: 'good', icon: 'down' });
		expect(by.trend.claim).toBe('7-day trend: falling (−85.7%)');
		for (const x of s) {
			expect(x.evidence.length).toBeGreaterThan(0);
			expect(x.claim.length).toBeGreaterThan(0);
			expect(`${x.claim} ${x.evidence}`).not.toMatch(/\p{Extended_Pictographic}/u);
		}
	});
	it('uses 30+ days for a good lowest signal', () => {
		const long: DailyLow[] = [{ date: '2026-06-01', price: 50 }];
		for (let i = 0; i < 40; i++) long.push({ date: addDays('2026-08-01', i), price: 100 });
		const s = buildSignals({ ...base, asOf: '2026-09-09', lows: long, today: 100 });
		expect(s.find((x) => x.key === 'lowest')).toMatchObject({ tone: 'good', icon: 'check', claim: 'Lowest in 100 days' });
	});
	it('applies the +-2% average rule; only above-average is bad', () => {
		const avg = (today: number) => buildSignals({ ...base, lows: ten, today, avg30: 100 }).find((x) => x.key === 'avg')!;
		expect(avg(97.9)).toMatchObject({ tone: 'good', icon: 'check' });
		expect(avg(101)).toMatchObject({ tone: 'neutral', icon: 'dash' });
		expect(avg(99)).toMatchObject({ tone: 'neutral' });
		expect(avg(102.5)).toMatchObject({ tone: 'bad', icon: 'alert', claim: '2.5% above its 30-day average' });
	});
	it('rising trend is warn/up, flat is neutral/dash', () => {
		const up = lows([['2026-09-04', 100], ['2026-09-05', 100], ['2026-09-10', 105]]);
		expect(buildSignals({ ...base, lows: up, today: 105 }).find((x) => x.key === 'trend'))
			.toMatchObject({ tone: 'warn', icon: 'up' });
		const flat = lows([['2026-09-04', 100], ['2026-09-05', 100], ['2026-09-10', 100.5]]);
		expect(buildSignals({ ...base, lows: flat, today: 100.5 }).find((x) => x.key === 'trend'))
			.toMatchObject({ tone: 'neutral', icon: 'dash' });
	});
	it('adds a sale signal near an event and a successor signal when mapped', () => {
		const now = new Date('2026-12-14T00:00:00Z');
		const s = buildSignals({ ...base, asOf: '2026-12-14', lows: ten, today: 10, now });
		expect(s.find((x) => x.key === 'sale')).toMatchObject({ tone: 'warn', icon: 'calendar', claim: 'Boxing Day starts in 12 days' });
		const run = buildSignals({ ...base, lows: ten, today: 10, now: new Date('2026-11-27T00:00:00Z') });
		expect(run.find((x) => x.key === 'sale')?.claim).toBe('Black Friday sale on now');
		SUCCESSORS['RTX 50'] = 'RTX 60';
		try {
			const sc = buildSignals({ ...base, lows: ten, today: 10, series: 'RTX 50' });
			expect(sc.find((x) => x.key === 'successor')).toMatchObject({ tone: 'warn', icon: 'alert', claim: 'Successor announced (RTX 60)' });
		} finally {
			delete SUCCESSORS['RTX 50'];
		}
	});
});
