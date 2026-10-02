// Per-retailer data-health classification for the homepage strip. Pure, so the
// boundaries are pinned by tests rather than by how a pill happens to render.
import { daysBehindToday, stalenessLabel } from './formats';
import { retailerLabel } from './filters';
import type { RetailerFreshness } from './models';

export type FreshnessState = 'fresh' | 'recent' | 'stale' | 'never' | 'incomplete';

export interface RetailerHealth {
	retailer: string;
	label: string;
	state: FreshnessState;
	days: number | null;
	// Always states the age in words -- colour is never the only carrier.
	text: string;
	// "312 matched" from today's run, when there was one (R3).
	detail?: string | null;
}

// scrape_runs statuses meaning today's data is short (#7, R3). 'skipped' (a
// PCCG cooldown) is expected and not listed.
const INCOMPLETE_STATUSES = new Set(['degraded', 'failed', 'timeout', 'auth']);

// The spec names fresh / cooling-down / stale but leaves one-day-behind
// unnamed, which is the most common state of all: the pipeline runs at 04:00,
// so every retailer is one day behind until the morning run. "recent" keeps
// that honest without crying wolf. The >= 2 day stale boundary is the spec's.
export function classifyFreshness(days: number | null): FreshnessState {
	if (days === null) return 'never';
	if (days === 0) return 'fresh';
	if (days === 1) return 'recent';
	return 'stale';
}

function localIsoDate(now: Date): string {
	const mm = String(now.getMonth() + 1).padStart(2, '0');
	const dd = String(now.getDate()).padStart(2, '0');
	return `${now.getFullYear()}-${mm}-${dd}`;
}

export function retailerHealth(
	rows: RetailerFreshness[],
	now: Date = new Date()
): RetailerHealth[] {
	const today = localIsoDate(now);
	return rows.map((row) => {
		const days = row.latestSnapshotDate === null ? null : daysBehindToday(row.latestSnapshotDate, now);
		// The pipeline stores local wall-clock times, so the time is sliced, not
		// parsed: parsing would shift it by the viewer's timezone and could differ
		// between server and browser.
		const runToday = row.lastRunAt && row.lastRunAt.slice(0, 10) === today ? row.lastRunAt : null;
		const time = runToday ? runToday.slice(11, 16) : null;

		let state = classifyFreshness(days);
		if (runToday && row.lastRunStatus && INCOMPLETE_STATUSES.has(row.lastRunStatus)) {
			state = 'incomplete';
		}

		let text: string;
		if (state === 'incomplete') text = `${row.lastRunStatus} at ${time}`;
		else if (state === 'never') text = 'missing';
		else if (days === 0) text = time ? `today ${time}` : 'today';
		else text = stalenessLabel(days as number);

		return {
			retailer: row.retailer,
			// An unknown slug falls back to itself so a newly-added retailer
			// shows up rather than rendering blank.
			label: retailerLabel(row.retailer),
			state,
			days,
			text,
			detail: runToday && row.lastRunMatched != null ? `${row.lastRunMatched} matched` : null
		};
	});
}
