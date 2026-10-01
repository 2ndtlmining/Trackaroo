import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import StaleDataBanner from '../src/lib/components/StaleDataBanner.svelte';
import { daysBehindToday, stalenessLabel } from '../src/lib/formats';

function render(props: Record<string, unknown>): string {
	const target = document.createElement('div');
	const comp = mount(StaleDataBanner as never, { target, props });
	const html = target.innerHTML;
	unmount(comp);
	return html;
}

const NOW = new Date('2026-08-23T09:00:00');

describe('daysBehindToday', () => {
	it('treats a snapshot dated today as current', () => {
		expect(daysBehindToday('2026-08-23', NOW)).toBe(0);
	});

	it('counts whole calendar days, not elapsed hours', () => {
		// 15 hours earlier, but a different calendar day -> 1 day behind.
		expect(daysBehindToday('2026-08-22', new Date('2026-08-23T00:30:00'))).toBe(1);
	});

	it('counts a multi-day gap', () => {
		expect(daysBehindToday('2026-08-16', NOW)).toBe(7);
	});

	it('never reports negative staleness when the DB is ahead of the clock', () => {
		expect(daysBehindToday('2026-08-25', NOW)).toBe(0);
	});

	it('returns null with nothing to compare', () => {
		expect(daysBehindToday(null, NOW)).toBeNull();
		expect(daysBehindToday('not-a-date', NOW)).toBeNull();
	});
});

describe('stalenessLabel', () => {
	it('singularises one day', () => {
		expect(stalenessLabel(1)).toBe('1 day behind');
	});

	it('pluralises the rest', () => {
		expect(stalenessLabel(3)).toBe('3 days behind');
	});
});

describe('StaleDataBanner', () => {
	/**
	 * A local calendar date N days ago.
	 *
	 * Built from local date parts, not toISOString(): the component compares
	 * local calendar days, and in a UTC+10 timezone an ISO date is already the
	 * previous day for most of the morning, which would shift every case by one.
	 */
	function daysAgo(n: number): string {
		const d = new Date();
		d.setDate(d.getDate() - n);
		const month = String(d.getMonth() + 1).padStart(2, '0');
		const day = String(d.getDate()).padStart(2, '0');
		return `${d.getFullYear()}-${month}-${day}`;
	}

	it('renders nothing when the data is current', () => {
		// Svelte leaves an anchor comment behind, so "nothing" means no element.
		const html = render({ latestSnapshotDate: daysAgo(0) });
		expect(html).not.toContain('<div');
	});

	it('warns when the newest snapshot is a day old', () => {
		const html = render({ latestSnapshotDate: daysAgo(1) });
		expect(html).toContain('1 day behind');
	});

	it('escalates styling once the gap reaches two days', () => {
		const html = render({ latestSnapshotDate: daysAgo(4) });
		expect(html).toContain('4 days behind');
		// Two days or more is the warning tone -- never the "price fell" green (#24).
		expect(html).toContain('text-warning');
		expect(html).not.toContain('text-down');
	});

	it('explains an empty database instead of showing a staleness gap', () => {
		const html = render({ latestSnapshotDate: null });
		expect(html).toContain('No price snapshots yet');
		expect(html).toContain('run_daily.py');
	});
});
