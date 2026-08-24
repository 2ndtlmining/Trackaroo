// Per-retailer data-health classification for the homepage strip. Pure, so the
// boundaries are pinned by tests rather than by how a pill happens to render.
import { daysBehindToday, stalenessLabel } from './formats';
import { RETAILER_OPTIONS } from './filters';
import type { RetailerFreshness } from './server/repos';

export type FreshnessState = 'fresh' | 'recent' | 'stale' | 'never';

export interface RetailerHealth {
	retailer: string;
	label: string;
	state: FreshnessState;
	days: number | null;
	// Always states the age in words — colour is never the only carrier.
	text: string;
}

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

const RETAILER_LABELS = new Map(RETAILER_OPTIONS.map((o) => [o.value as string, o.label]));

export function retailerHealth(
	rows: RetailerFreshness[],
	now: Date = new Date()
): RetailerHealth[] {
	return rows.map((row) => {
		const days = row.latestSnapshotDate === null ? null : daysBehindToday(row.latestSnapshotDate, now);
		const state = classifyFreshness(days);
		return {
			retailer: row.retailer,
			// An unknown slug falls back to itself so a newly-added retailer
			// shows up rather than rendering blank.
			label: RETAILER_LABELS.get(row.retailer) ?? row.retailer,
			state,
			days,
			text: state === 'never' ? 'no data' : days === 0 ? 'today' : stalenessLabel(days as number)
		};
	});
}
