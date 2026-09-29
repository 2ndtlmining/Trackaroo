<script lang="ts">
	import { daysBehindToday, formatDate, stalenessLabel } from '$lib/formats';

	/**
	 * Warns when the newest snapshot predates today.
	 *
	 * Every number on the dashboard is "as of the latest snapshot", which reads
	 * as current whether the pipeline ran this morning or stopped a week ago.
	 * Days have been lost silently before (16-Aug and 23-Aug 2026), so a gap
	 * needs to be visible rather than inferred from a date in the header.
	 *
	 * The two-day-plus severity renders in the warning tone (#24) -- stale
	 * data is a caution, not the "price fell" green, so it never borrows the
	 * price-direction colours.
	 */
	let { latestSnapshotDate }: { latestSnapshotDate: string | null } = $props();

	const days = $derived(daysBehindToday(latestSnapshotDate));
	// One day behind is normal for most of the day: the pipeline runs early
	// morning, so "yesterday" only becomes suspicious once it's two days old.
	const severity = $derived(days === null ? null : days >= 2 ? 'error' : days >= 1 ? 'warn' : null);
</script>

{#if severity && days !== null}
	<div
		role="status"
		class="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-3 py-2 text-sm {severity ===
		'error'
			? 'border-warning/40 bg-warning-soft text-warning'
			: 'border-border bg-surface text-text-muted'}"
	>
		<svg
			width="15"
			height="15"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			class="shrink-0"
			aria-hidden="true"
		>
			<circle cx="12" cy="12" r="9"></circle>
			<path d="M12 7v5l3 2"></path>
		</svg>
		<span class="font-medium">Data is {stalenessLabel(days)}.</span>
		<span>
			The most recent snapshot is {formatDate(latestSnapshotDate!)} — prices below are from then,
			not today.
		</span>
	</div>
{:else if latestSnapshotDate === null}
	<div
		role="status"
		class="mb-4 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-muted"
	>
		<span class="font-medium">No price snapshots yet.</span>
		Run <code class="rounded bg-surface-hover px-1 py-0.5 text-xs">python run_daily.py</code> to collect
		the first day of data.
	</div>
{/if}
