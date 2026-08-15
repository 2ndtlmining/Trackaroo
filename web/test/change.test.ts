import { describe, expect, it } from 'vitest';
import { classifyChange, STALE_THRESHOLD_DAYS } from '../src/lib/change';

const NOW = '2026-08-15T12:00:00Z';

function input(overrides: Partial<Parameters<typeof classifyChange>[0]> = {}) {
	return {
		latestPrice: 95,
		windowStartPrice: 100,
		pointsInWindow: 5,
		lastSnapshotAt: NOW,
		now: NOW,
		...overrides
	};
}

describe('classifyChange', () => {
	it('classifies a price drop as down', () => {
		expect(classifyChange(input())).toBe('down');
	});

	it('classifies a price rise as up', () => {
		expect(classifyChange(input({ windowStartPrice: 90 }))).toBe('up');
	});

	it('classifies tiny deltas as flat', () => {
		expect(classifyChange(input({ windowStartPrice: 94.998 }))).toBe('flat');
		expect(classifyChange(input({ latestPrice: 100.001, windowStartPrice: 100 }))).toBe('flat');
	});

	it('returns insufficient without a window start price', () => {
		expect(classifyChange(input({ windowStartPrice: null }))).toBe('insufficient');
	});

	it('returns insufficient with fewer than 2 points in the window', () => {
		expect(classifyChange(input({ pointsInWindow: 1 }))).toBe('insufficient');
	});

	it('returns stale when the last snapshot is older than the threshold', () => {
		expect(
			classifyChange(
				input({ lastSnapshotAt: '2026-08-11T12:00:00Z', staleThresholdDays: 3 })
			)
		).toBe('stale');
	});

	it('does not flag as stale within the threshold', () => {
		expect(
			classifyChange(input({ lastSnapshotAt: '2026-08-12T12:00:00Z', staleThresholdDays: 3 }))
		).toBe('down');
	});

	it('stale takes priority over up/down', () => {
		expect(
			classifyChange(input({ windowStartPrice: 105, lastSnapshotAt: '2026-08-10T12:00:00Z' }))
		).toBe('stale');
	});

	it('defaults the stale threshold to 3 days', () => {
		expect(STALE_THRESHOLD_DAYS).toBe(3);
	});

	it('uses Date objects for now', () => {
		expect(
			classifyChange(input({ now: new Date(NOW), lastSnapshotAt: NOW }))
		).toBe('down');
	});

	it('accepts an explicit stale threshold of zero to flag immediately', () => {
		expect(
			classifyChange(
				input({ staleThresholdDays: 0, lastSnapshotAt: '2026-08-15T11:30:00Z' })
			)
		).toBe('stale');
	});
});