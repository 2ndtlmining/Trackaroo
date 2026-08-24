<script lang="ts">
	import { formatBytes, formatDate } from '$lib/formats';
	import type { RetailerHealth } from '$lib/health';

	let {
		retailers,
		latestSnapshotDate,
		snapshotDays,
		snapshotCount,
		dbSizeBytes = 0
	}: {
		retailers: RetailerHealth[];
		latestSnapshotDate: string | null;
		snapshotDays: number;
		snapshotCount: number;
		// Moved out of the header (spec §6) — this is the stats' honest home.
		dbSizeBytes?: number;
	} = $props();

	// A cooling-down retailer currently reads as stale (spec §5 defers reading
	// data/pccg_cooldown.json). Warning tone, never an error tone: the PCCG
	// circuit breaker is working as designed and the UI must not cry wolf.
	function pillClass(state: RetailerHealth['state']): string {
		if (state === 'fresh') return 'border-down/40 bg-down/10 text-down';
		if (state === 'recent') return 'border-border bg-surface text-text-muted';
		return 'border-up/40 bg-up/10 text-up';
	}

	function marker(state: RetailerHealth['state']): string {
		if (state === 'fresh') return '●';
		if (state === 'recent') return '○';
		return '▲';
	}

	const numberFormat = new Intl.NumberFormat('en-AU');
</script>

<section
	class="mb-6 rounded-lg border border-border bg-surface px-3 py-2.5"
	aria-label="Data health"
>
	{#if latestSnapshotDate}
		<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
			<p class="text-sm text-text">
				Most recent snapshot <span class="font-medium">{formatDate(latestSnapshotDate)}</span>
			</p>
			<p class="text-xs text-text-muted">
				<span class="num">{snapshotDays}</span> days ·
				<span class="num">{numberFormat.format(snapshotCount)}</span> snapshots
				{#if dbSizeBytes > 0}
					· <span class="num">{formatBytes(dbSizeBytes)}</span>
				{/if}
			</p>
		</div>
		<div class="mt-2 flex flex-wrap items-center gap-1.5">
			{#each retailers as r (r.retailer)}
				<span
					class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs {pillClass(
						r.state
					)}"
				>
					<span aria-hidden="true">{marker(r.state)}</span>
					<span class="font-medium">{r.label}</span>
					<span>{r.text}</span>
				</span>
			{/each}
		</div>
	{:else}
		<p class="text-sm text-text-muted">No snapshots yet — run the pipeline to collect prices.</p>
	{/if}
</section>
