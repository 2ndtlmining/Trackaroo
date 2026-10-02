import { describe, expect, it } from 'vitest';
import { CURATED_YEARS, saleEventsFor, saleEventsInRange, upcomingSaleEvent } from '../src/lib/saleEvents';

const ev = (year: number, name: string) => saleEventsFor(year).find((e) => e.name === name)!;

describe('saleEventsFor', () => {
	it('puts Black Friday the day after the 4th Thursday of November', () => {
		expect(ev(2025, 'Black Friday').start).toBe('2025-11-28');
		expect(ev(2026, 'Black Friday').start).toBe('2026-11-27');
	});
	it('has the fixed-date events', () => {
		expect(ev(2026, 'EOFY')).toMatchObject({ start: '2026-06-15', end: '2026-06-30' });
		expect(ev(2026, 'Boxing Day')).toMatchObject({ start: '2026-12-26', end: '2026-12-31' });
		expect(ev(2026, 'Singles Day')).toMatchObject({ start: '2026-11-11', end: '2026-11-11' });
	});
	it('has curated Click Frenzy and Prime Day for every curated year', () => {
		for (const y of CURATED_YEARS) {
			expect(ev(y, 'Click Frenzy')).toBeDefined();
			expect(ev(y, 'Prime Day')).toBeDefined();
		}
	});
	it('CURATED_YEARS covers next calendar year (add it when this fails)', () => {
		expect(CURATED_YEARS).toContain(new Date().getFullYear() + 1);
	});
});

describe('upcomingSaleEvent', () => {
	it('finds the next event within the horizon', () => {
		// Click Frenzy (10 Nov) precedes Singles Day (11 Nov) in 2026.
		const r = upcomingSaleEvent('2026-11-01')!;
		expect(r).toMatchObject({ startsInDays: 9, running: false });
		expect(r.event.name).toBe('Click Frenzy');
	});
	it('reports a running event with startsInDays 0', () => {
		expect(upcomingSaleEvent('2026-11-28')).toMatchObject({ running: true, startsInDays: 0 });
		expect(upcomingSaleEvent('2026-11-28')!.event.name).toBe('Black Friday');
	});
	it('reports Boxing Day running late December, never negative', () => {
		const r = upcomingSaleEvent('2026-12-28')!;
		expect(r.event.name).toBe('Boxing Day');
		expect(r).toMatchObject({ running: true, startsInDays: 0 });
		expect(upcomingSaleEvent('2026-12-31')!.running).toBe(true);
	});
	it('looks into next year at the year end', () => {
		// Boxing Day ends 31 Dec, so on 1 Jan the next event is in next year's calendar.
		const r = upcomingSaleEvent('2026-12-31', 400)!;
		expect(r.running).toBe(true);
		expect(upcomingSaleEvent('2027-01-01', 200)).toMatchObject({ running: false, startsInDays: 165 });
	});
	it('is null when nothing is within the horizon', () => {
		expect(upcomingSaleEvent('2026-09-10')).toBeNull();
	});
});

describe('saleEventsInRange (chart markers)', () => {
	it('returns every event overlapping the inclusive range, in date order', () => {
		const names = saleEventsInRange('2026-06-01', '2026-07-31').map((e) => e.name);
		expect(names).toEqual(['EOFY', 'Prime Day']);
	});
	it('includes an event that started before the range and is still running', () => {
		expect(saleEventsInRange('2026-06-29', '2026-07-01').map((e) => e.name)).toEqual(['EOFY']);
	});
	it('spans year boundaries', () => {
		const names = saleEventsInRange('2025-12-20', '2026-01-05').map((e) => e.name);
		expect(names).toEqual(['Boxing Day']);
		expect(saleEventsInRange('2025-11-25', '2026-06-16').map((e) => e.name)).toEqual([
			'Black Friday',
			'Boxing Day',
			'EOFY'
		]);
	});
	it('is empty for a range with no event, and for an inverted range', () => {
		expect(saleEventsInRange('2026-08-10', '2026-10-03')).toEqual([]);
		expect(saleEventsInRange('2026-07-31', '2026-06-01')).toEqual([]);
	});
});

describe('estimated curated dates (R9)', () => {
	it('flags curated estimates and leaves rule-based events unflagged', () => {
		expect(ev(2026, 'Prime Day').estimated).toBe(true);
		expect(ev(2026, 'Click Frenzy').estimated).toBe(true);
		for (const name of ['EOFY', 'Singles Day', 'Black Friday', 'Boxing Day']) {
			expect(ev(2026, name).estimated).toBeUndefined();
		}
	});
});
