<script lang="ts">
	import { formatAud } from '$lib/formats';
	import Badge from './Badge.svelte';
	import LatestListingTable from './LatestListingTable.svelte';
	import type { ProductGroup } from '$lib/server/repos';

	let { group }: { group: ProductGroup } = $props();

	let expanded = $state(false);

	const listingCount = $derived(
		`${group.listings.length} ${group.listings.length === 1 ? 'listing' : 'listings'}`
	);
	const priceLabel = $derived(
		group.cheapestInStockPrice !== null
			? `from ${formatAud(group.cheapestInStockPrice)}`
			: null
	);
	const countLine = $derived(
		group.inStockCount > 0 ? `${listingCount} · ${group.inStockCount} in stock` : listingCount
	);
	const toggleLabel = $derived(expanded ? 'Hide listings' : `Show ${listingCount}`);
</script>

<article class="flex flex-col rounded-md border border-border bg-surface">
	<div class="p-3">
		<div class="flex items-start justify-between gap-2">
			<a
				href="/product/{group.productId}"
				class="text-sm font-semibold text-text no-underline hover:text-accent"
			>
				{group.model}
			</a>
			<Badge tone="neutral" label={group.category.toUpperCase()} />
		</div>
		<div class="mt-0.5 text-xs text-text-muted">{group.brand}</div>
		{#if priceLabel}
			<div class="mt-2 flex items-center gap-2">
				<span class="num text-lg font-semibold text-text">{priceLabel}</span>
				<span
					class="shrink-0 rounded-full border border-border bg-surface-hover px-2 py-0.5 text-[10px] uppercase tracking-wide text-text-muted"
				>
					{group.cheapestInStockRetailer}
				</span>
			</div>
		{:else}
			<div class="mt-2 text-sm text-text-muted">No in-stock listings</div>
		{/if}
		<div class="mt-1 text-xs text-text-muted">{countLine}</div>
	</div>

	<button
		type="button"
		aria-expanded={expanded}
		onclick={() => (expanded = !expanded)}
		class="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-text-muted hover:bg-surface-hover hover:text-text"
	>
		<span>{toggleLabel}</span>
		<span aria-hidden="true">{expanded ? '▴' : '▾'}</span>
	</button>

	{#if expanded}
		<div class="border-t border-border p-2">
			<LatestListingTable rows={group.listings} compact />
		</div>
	{/if}
</article>
