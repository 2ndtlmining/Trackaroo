<script lang="ts">
	import { formatAud } from '$lib/formats';
	import Badge from './Badge.svelte';
	import BrandIcon from './BrandIcon.svelte';
	import LatestListingTable from './LatestListingTable.svelte';
	import Sparkline from './Sparkline.svelte';
	import type { ProductGroup } from '$lib/server/repos';

	let {
		group,
		compareSelected = false,
		compareDisabled = false,
		onToggleCompare
	}: {
		group: ProductGroup;
		compareSelected?: boolean;
		compareDisabled?: boolean;
		onToggleCompare?: (productId: number) => void;
	} = $props();

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
	const sparklineReady = $derived(!!group.sparkline && group.sparkline.length >= 2);
</script>

<article class="flex flex-col rounded-md border border-border bg-surface">
	<div class="grow p-3">
		<div class="flex items-start justify-between gap-2">
			<a
				href="/product/{group.productId}"
				class="text-sm font-semibold text-text no-underline hover:text-accent"
			>
				{group.model}
			</a>
			<div class="flex shrink-0 items-center gap-2">
				{#if onToggleCompare}
					<label
						class="flex cursor-pointer items-center gap-1 text-[10px] uppercase tracking-wide text-text-muted {compareDisabled
							? 'cursor-not-allowed opacity-50'
							: ''}"
					>
						<input
							type="checkbox"
							aria-label="Add {group.model} to compare"
							checked={compareSelected}
							disabled={compareDisabled}
							onchange={() => onToggleCompare(group.productId)}
							class="accent-accent"
						/>
						Compare
					</label>
				{/if}
				<Badge tone="neutral" label={group.category.toUpperCase()} />
			</div>
		</div>
		<div class="mt-0.5 flex items-center gap-1.5 text-xs text-text-muted">
			<BrandIcon brand={group.brand} size={14} />
			{group.brand}
		</div>
		{#if priceLabel}
			<div class="mt-2 flex min-h-7 items-center gap-2">
				<span class="num text-lg font-semibold text-text">{priceLabel}</span>
				<span
					class="shrink-0 rounded-full border border-border bg-surface-hover px-2 py-0.5 text-[10px] uppercase tracking-wide text-text-muted"
				>
					{group.cheapestInStockRetailer}
				</span>
				{#if sparklineReady}
					<span class="ml-auto shrink-0">
						<Sparkline points={group.sparkline} />
					</span>
				{/if}
			</div>
		{:else}
			<div class="mt-2 flex min-h-7 items-center gap-2">
				<span class="text-sm text-text-muted">No in-stock listings</span>
				{#if sparklineReady}
					<span class="ml-auto shrink-0">
						<Sparkline points={group.sparkline} />
					</span>
				{/if}
			</div>
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
