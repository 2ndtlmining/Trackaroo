import { describe, expect, it } from 'vitest';
import {
	formatAud,
	formatAxisLabel,
	formatBytes,
	formatDate,
	formatPct,
	formatRelative,
	formatSignedAud,
	freshnessLabel,
	stockLabel
} from '../src/lib/formats';

describe('formatAud', () => {
	it('formats whole dollars without cents', () => {
		expect(formatAud(749)).toBe('$749');
	});

	it('formats cent values with two decimals', () => {
		expect(formatAud(749.5)).toBe('$749.50');
	});

	it('formats large numbers with grouping', () => {
		expect(formatAud(1234.56)).toBe('$1,234.56');
	});

	it('handles zero and negative', () => {
		expect(formatAud(0)).toBe('$0');
		expect(formatAud(-10)).toBe('-$10');
	});
});

describe('formatSignedAud', () => {
	it('prefixes positive changes with +', () => {
		expect(formatSignedAud(50)).toBe('+$50');
	});

	it('prefixes negative changes with a minus', () => {
		expect(formatSignedAud(-50)).toBe('−$50');
	});

	it('returns zero without a sign', () => {
		expect(formatSignedAud(0)).toBe('$0');
	});
});

describe('formatPct', () => {
	it('prefixes positive values with +', () => {
		expect(formatPct(5.678)).toBe('+5.7%');
	});

	it('prefixes negative values with a minus sign', () => {
		expect(formatPct(-3.25)).toBe('−3.3%');
	});

	it('returns zero without a sign', () => {
		expect(formatPct(0)).toBe('0.0%');
	});

	it('rounds to one decimal', () => {
		expect(formatPct(1.04)).toBe('+1.0%');
	});
});

describe('formatRelative', () => {
	const now = new Date('2026-08-15T12:00:00Z');

	it('returns never for null input', () => {
		expect(formatRelative(null, now)).toBe('never');
	});

	it('just now for under a minute', () => {
		expect(formatRelative('2026-08-15T11:59:30Z', now)).toBe('just now');
	});

	it('minutes for under an hour', () => {
		expect(formatRelative('2026-08-15T11:30:00Z', now)).toBe('30m ago');
	});

	it('hours for under a day', () => {
		expect(formatRelative('2026-08-15T04:00:00Z', now)).toBe('8h ago');
	});

	it('days for under a week', () => {
		expect(formatRelative('2026-08-13T12:00:00Z', now)).toBe('2d ago');
	});

	it('weeks up to a month', () => {
		expect(formatRelative('2026-08-01T12:00:00Z', now)).toBe('2w ago');
	});

	it('months beyond', () => {
		expect(formatRelative('2026-04-01T12:00:00Z', now)).toBe('4mo ago');
	});
});

describe('formatDate', () => {
	it('formats a YYYY-MM-DD date', () => {
		expect(formatDate('2026-08-15')).toBe('15 Aug 2026');
	});

	it('returns the input unchanged when unparseable', () => {
		expect(formatDate('not-a-date')).toBe('not-a-date');
	});
});

describe('formatAxisLabel', () => {
	it('formats a short month-day label', () => {
		expect(formatAxisLabel('2026-08-15')).toBe('15 Aug');
	});
});

describe('freshnessLabel', () => {
	const now = new Date('2026-08-15T12:00:00Z');
	const ts = (d: string) => new Date(`${d}T00:00:00Z`).toISOString();

	it('returns no data for null', () => {
		expect(freshnessLabel(null, now)).toBe('no data');
	});

	it('today for the same day', () => {
		expect(freshnessLabel(ts('2026-08-15'), now)).toBe('today');
	});

	it('yesterday for one day back', () => {
		expect(freshnessLabel(ts('2026-08-14'), now)).toBe('yesterday');
	});

	it('n days ago beyond', () => {
		expect(freshnessLabel(ts('2026-08-10'), now)).toBe('5d ago');
	});
});

describe('stockLabel', () => {
	it('maps known statuses', () => {
		expect(stockLabel('in_stock')).toBe('In stock');
		expect(stockLabel('out_of_stock')).toBe('Out of stock');
		expect(stockLabel('preorder')).toBe('Preorder');
	});

	it('falls back to unknown', () => {
		expect(stockLabel('anything')).toBe('Unknown');
	});
});

describe('formatBytes', () => {
	it('formats zero and common magnitudes', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(500)).toBe('500 B');
		expect(formatBytes(1536)).toBe('1.5 KB');
		expect(formatBytes(1048576)).toBe('1.0 MB');
	});
});