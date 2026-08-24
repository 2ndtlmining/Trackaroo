import { describe, it, expect } from 'vitest';
import { classifyFreshness, retailerHealth } from '../src/lib/health';

const NOW = new Date('2026-08-25T09:00:00');

describe('classifyFreshness', () => {
	it('treats a snapshot from today as fresh', () => {
		expect(classifyFreshness(0)).toBe('fresh');
	});

	// The pipeline runs at 04:00, so before the morning run every retailer is
	// one day behind and nothing is wrong. Neither "fresh" nor "stale" is honest.
	it('treats one day behind as recent, not stale', () => {
		expect(classifyFreshness(1)).toBe('recent');
	});

	it('treats two or more days behind as stale', () => {
		expect(classifyFreshness(2)).toBe('stale');
		expect(classifyFreshness(9)).toBe('stale');
	});

	it('treats a missing date as never', () => {
		expect(classifyFreshness(null)).toBe('never');
	});
});

describe('retailerHealth', () => {
	it('labels known retailers and states their age in text', () => {
		const rows = retailerHealth(
			[
				{ retailer: 'scorptec', latestSnapshotDate: '2026-08-25' },
				{ retailer: 'pccg', latestSnapshotDate: '2026-08-23' }
			],
			NOW
		);
		expect(rows[0]).toMatchObject({
			retailer: 'scorptec',
			label: 'Scorptec',
			state: 'fresh',
			days: 0
		});
		expect(rows[0].text).toBe('today');
		expect(rows[1]).toMatchObject({ retailer: 'pccg', label: 'PCCG', state: 'stale', days: 2 });
		expect(rows[1].text).toBe('2 days behind');
	});

	it('says one day behind in the singular', () => {
		const [row] = retailerHealth([{ retailer: 'pccg', latestSnapshotDate: '2026-08-24' }], NOW);
		expect(row.state).toBe('recent');
		expect(row.text).toBe('1 day behind');
	});

	it('labels a retailer that has a scraper planned but no data yet', () => {
		const [row] = retailerHealth([{ retailer: 'mwave', latestSnapshotDate: '2026-08-25' }], NOW);
		expect(row.label).toBe('MWave');
	});

	it('falls back to the slug for a retailer missing from the registry entirely', () => {
		const [row] = retailerHealth(
			[{ retailer: 'someshop' as never, latestSnapshotDate: '2026-08-25' }],
			NOW
		);
		expect(row.label).toBe('someshop');
	});

	it('reports a retailer that has never reported', () => {
		const [row] = retailerHealth([{ retailer: 'pccg', latestSnapshotDate: null }], NOW);
		expect(row.state).toBe('never');
		expect(row.text).toBe('no data');
	});
});
