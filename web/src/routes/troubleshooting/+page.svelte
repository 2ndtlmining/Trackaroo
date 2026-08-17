<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import type { BadgeTone } from '$lib/components/Badge.svelte';
	import type { CoverageRow, CoverageSummary } from '$lib/server/repos';

	let { data }: { data: { summary: CoverageSummary } } = $props();

	const summary = $derived(data.summary);

	const gapThreshold = 2;
	const dayTitles = ['6d ago', '5d ago', '4d ago', '3d ago', '2d ago', '1d ago', 'today'];

	const groups = $derived(
		(['scorptec', 'pccg'] as const).map((retailer) => ({
			retailer,
			categories: (['cpu', 'gpu'] as const).map((category) => ({
				category,
				rows: summary.rows
					.filter((r) => r.retailer === retailer && r.category === category)
					.sort((a, b) => b.snapshotCount - a.snapshotCount || a.model.localeCompare(b.model))
			}))
		}))
	);

	const today = new Date().toISOString().slice(0, 10);

	function daysSince(dateStr: string | null): number | null {
		if (dateStr === null) return null;
		return Math.round(
			(Date.parse(`${today}T00:00:00Z`) - Date.parse(`${dateStr}T00:00:00Z`)) / 86_400_000
		);
	}

	function gapLabel(row: CoverageRow): string {
		if (row.lastDate === null) return 'no data';
		if (row.gapDays === 0) return 'today';
		if (row.gapDays === 1) return 'yesterday';
		return `${row.gapDays} days ago`;
	}

	function gapTone(row: CoverageRow): BadgeTone {
		if (row.lastDate === null || row.gapDays === null) return 'stale';
		return row.gapDays >= gapThreshold ? 'stale' : 'flat';
	}
</script>

<svelte:head>
	<title>Trackaroo — Troubleshooting</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Troubleshooting</h1>
		<p class="mt-1 text-sm text-text-muted">
			Temporary diagnostic view — retailer → category → model snapshot coverage. Delete once the
			PCCG cooldown behaviour and compare/specs issues are confirmed fixed.
		</p>
	</div>

	{#if !summary.referenceDate}
		<p class="text-sm text-text-muted">No snapshot data in the database yet.</p>
	{:else}
		<div class="grid gap-3 sm:grid-cols-2">
			{#each summary.retailers as r}
				<div class="rounded-md border border-border bg-surface p-3">
					<div class="flex items-center justify-between">
						<span class="font-medium capitalize text-text">{r.retailer}</span>
						{#if r.lastDate && (daysSince(r.lastDate) ?? 999) < gapThreshold}
							<Badge tone="accent" label="fresh" />
						{:else}
							<Badge tone="stale" label="stale" />
						{/if}
					</div>
					<p class="mt-1 text-xs text-text-muted">
						Last snapshot: {r.lastDate ?? '—'} · {r.dateCount} dates · {r.referenceDateVariants}
						variants on {summary.referenceDate}
					</p>
				</div>
			{/each}
		</div>

		{#each groups as group}
			<div class="rounded-md border border-border">
				<div class="border-b border-border bg-surface px-3 py-2 font-medium capitalize text-text">
					{group.retailer}
				</div>
				{#each group.categories as cat}
					<div class="border-b border-border last:border-b-0">
						<div class="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
							{cat.category}
						</div>
						{#if cat.rows.length === 0}
							<p class="px-3 pb-2 text-sm text-text-muted">No tracked products at this retailer.</p>
						{:else}
							<table class="w-full text-sm">
								<thead>
									<tr class="border-b border-border text-left text-xs text-text-muted">
										<th class="px-3 py-1.5 font-medium">Model</th>
										<th class="px-3 py-1.5 font-medium">Snapshots</th>
										<th class="px-3 py-1.5 font-medium">Last</th>
										<th class="px-3 py-1.5 font-medium">Last 7 days</th>
									</tr>
								</thead>
								<tbody>
									{#each cat.rows as row}
										<tr class="border-b border-border last:border-b-0">
											<td class="px-3 py-1.5 text-text">
												<span class="font-medium">{row.model}</span>
												<span class="text-xs text-text-muted"> · {row.brand}</span>
											</td>
											<td class="px-3 py-1.5 text-text">{row.snapshotCount}</td>
											<td class="px-3 py-1.5">
												<Badge tone={gapTone(row)} label={`${row.lastDate ?? 'no data'} · ${gapLabel(row)}`} />
											</td>
											<td class="px-3 py-1.5">
												<span class="flex items-center gap-1">
													{#each row.last7 as present, i}
														<span
															title={dayTitles[i]}
															class="h-2.5 w-2.5 rounded-sm {present ? 'bg-accent' : 'border border-border bg-surface'}"
														></span>
													{/each}
												</span>
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>
				{/each}
			</div>
		{/each}

		{#if summary.zeroListings.length > 0}
			<div class="rounded-md border border-stale/40">
				<div class="border-b border-border bg-surface px-3 py-2 font-medium text-text">
					Products tracked but with no in-stock data in the last 7 days
				</div>
				<ul class="divide-y divide-border">
					{#each summary.zeroListings as p}
						<li class="flex items-center justify-between px-3 py-1.5 text-sm">
							<span class="text-text">
								<span class="font-medium">{p.model}</span>
								<span class="text-xs text-text-muted"> · {p.brand}</span>
							</span>
							<Badge tone="neutral" label={p.category.toUpperCase()} />
						</li>
					{/each}
				</ul>
			</div>
		{/if}
	{/if}
</div>