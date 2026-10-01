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

	// Status tones, never price-direction colours (#24). A cooling-down or stale
	// retailer is a warning, never an error: the PCCG circuit breaker is working
	// as designed and the UI must not cry wolf. `stale`, `never` and
	// `incomplete` all take the warning tone.
	function pillClass(state: RetailerHealth['state']): string {
		if (state === 'fresh') return 'border-success/40 bg-success-soft text-success';
		if (state === 'recent') return 'border-border bg-surface text-text-muted';
		return 'border-warning/40 bg-warning-soft text-warning';
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
					{#if r.detail}
						<span class="text-text-muted">· {r.detail}</span>
					{/if}
				</span>
			{/each}
		</div>
	{:else}
		<p class="text-sm text-text-muted">No snapshots yet — run the pipeline to collect prices.</p>
	{/if}
</section>
