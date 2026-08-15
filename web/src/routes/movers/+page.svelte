<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { formatAud, formatPct, formatSignedAud } from '$lib/formats';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import type { Mover } from '$lib/server/repos';
	import type { ChangeDirection } from '$lib/types';

	let {
		data
	}: {
		data: { movers: Mover[]; window: string; windows: readonly string[] };
	} = $props();

	type SortKey = 'abs' | 'pct' | 'price';
	type DirFilter = 'all' | ChangeDirection;

	let sort = $state<SortKey>('abs');
	let dir = $state<DirFilter>('all');

	function direction(m: Mover): ChangeDirection {
		if (m.notEnoughHistory) return 'insufficient';
		if (m.change === null) return 'insufficient';
		if (Math.abs(m.change) < 0.005) return 'flat';
		return m.change > 0 ? 'up' : 'down';
	}

	function pctLabel(m: Mover): string {
		return m.pctChange === null ? '—' : formatPct(m.pctChange);
	}

	async function setWindow(value: string) {
		const params = new URLSearchParams(page.url.searchParams);
		params.set('window', value);
		await goto(`?${params.toString()}`);
	}

	const visible = $derived(
		data.movers.filter((m) => dir === 'all' || direction(m) === dir)
	);

	const sorted = $derived.by(() => {
		const arr = [...visible];
		arr.sort((a, b) => {
			const av = a.change ?? -Infinity;
			const bv = b.change ?? -Infinity;
			if (sort === 'abs') return Math.abs(bv) - Math.abs(av);
			if (sort === 'price') return b.newPrice - a.newPrice;
			const ap = a.pctChange ?? -Infinity;
			const bp = b.pctChange ?? -Infinity;
			return bp - ap;
		});
		return arr;
	});
</script>

<svelte:head>
	<title>Trackaroo — Movers</title>
</svelte:head>

<div class="space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-4">
		<div>
			<h1 class="text-xl font-semibold text-text">Movers</h1>
			<p class="mt-1 text-sm text-text-muted">Biggest price changes over the selected window.</p>
		</div>
		<div class="flex items-center gap-1 rounded-md border border-border bg-surface p-1">
			{#each data.windows as w}
				<button
					type="button"
					onclick={() => setWindow(w)}
					class="rounded px-3 py-1 text-sm {data.window === w
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					{w}
				</button>
			{/each}
		</div>
	</div>

	<div class="flex flex-wrap items-center gap-4 text-sm">
		<div class="flex items-center gap-2">
			<span class="text-text-muted">Sort</span>
			<div class="flex items-center gap-1 rounded-md border border-border bg-surface p-1">
				<button
					type="button"
					onclick={() => (sort = 'abs')}
					class="rounded px-2.5 py-1 {sort === 'abs'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					Abs
				</button>
				<button
					type="button"
					onclick={() => (sort = 'pct')}
					class="rounded px-2.5 py-1 {sort === 'pct'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					Pct
				</button>
				<button
					type="button"
					onclick={() => (sort = 'price')}
					class="rounded px-2.5 py-1 {sort === 'price'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					Price
				</button>
			</div>
		</div>

		<div class="flex items-center gap-2">
			<span class="text-text-muted">Direction</span>
			<div class="flex items-center gap-1 rounded-md border border-border bg-surface p-1">
				<button
					type="button"
					onclick={() => (dir = 'all')}
					class="rounded px-2.5 py-1 {dir === 'all'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					All
				</button>
				<button
					type="button"
					onclick={() => (dir = 'up')}
					class="rounded px-2.5 py-1 {dir === 'up'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					Up
				</button>
				<button
					type="button"
					onclick={() => (dir = 'down')}
					class="rounded px-2.5 py-1 {dir === 'down'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					Down
				</button>
			</div>
		</div>
	</div>

	{#if sorted.length === 0}
		<div
			class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
		>
			No movers match the current filters.
		</div>
	{:else}
		<div class="overflow-x-auto rounded-md border border-border">
			<table class="w-full border-collapse text-sm">
				<thead>
					<tr class="border-b border-border text-left text-xs text-text-muted">
						<th class="px-3 py-2 font-medium">Model</th>
						<th class="px-3 py-2 font-medium">Retailer</th>
						<th class="px-3 py-2 font-medium">Variant</th>
						<th class="px-3 py-2 text-right font-medium">Old</th>
						<th class="px-3 py-2 text-right font-medium">New</th>
						<th class="px-3 py-2 text-right font-medium">Change</th>
						<th class="px-3 py-2 font-medium">Points</th>
					</tr>
				</thead>
				<tbody>
					{#each sorted as m (m.listingId)}
						<tr class="border-b border-border last:border-b-0 hover:bg-surface-hover">
							<td class="px-3 py-2">
								<a
									href="/product/{m.productId}"
									class="no-underline hover:no-underline"
								>{m.model}</a
								>
							</td>
							<td class="px-3 py-2 text-text">{m.retailer}</td>
							<td class="px-3 py-2 text-text-muted" title={m.variantName ?? undefined}>
								{m.variantName?.split(',')[0].trim() ?? '—'}
							</td>
							<td class="num px-3 py-2 text-right text-text-muted">
								{m.oldPrice === null ? '—' : formatAud(m.oldPrice)}
							</td>
							<td class="num px-3 py-2 text-right text-text">
								{formatAud(m.newPrice)}
							</td>
							<td class="px-3 py-2 text-right">
								{#if m.notEnoughHistory}
									<Badge tone="neutral" label="Not enough history" />
								{:else if m.change === null}
									<span class="text-text-muted">—</span>
								{:else}
									<PriceChange
										direction={direction(m)}
										label="{m.change > 0 ? '+' : ''}{formatSignedAud(m.change)} ({pctLabel(m)})"
									/>
								{/if}
							</td>
							<td class="num px-3 py-2 text-text-muted">{m.historyPoints}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>