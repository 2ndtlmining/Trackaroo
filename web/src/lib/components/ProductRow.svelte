<script lang="ts">
	import BrandIcon from './BrandIcon.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30 } from '$lib/offers';
	import type { ProductGroup } from '$lib/server/repos';

	let {
		group,
		compareSelected = false,
		compareDisabled = false,
		onToggleCompare
	}: {
		// neverListed: tracked in the watchlist but no retailer has ever listed
		// it — a different statement from "listed, currently out of stock".
		group: ProductGroup & { neverListed?: boolean };
		compareSelected?: boolean;
		compareDisabled?: boolean;
		onToggleCompare?: (productId: number) => void;
	} = $props();

	const retailerLabel = $derived(
		group.cheapestInStockRetailer
			? (RETAILER_OPTIONS.find((o) => o.value === group.cheapestInStockRetailer)?.label ??
				group.cheapestInStockRetailer)
			: null
	);

	const deltaPct = $derived(deltaVsAvg30(group.cheapestInStockPrice, group.avg30 ?? null));
</script>

<div class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-surface-hover">
	{#if onToggleCompare}
		<input
			type="checkbox"
			class="shrink-0 accent-accent"
			checked={compareSelected}
			disabled={compareDisabled}
			aria-label={`Compare ${group.model}`}
			onchange={() => onToggleCompare?.(group.productId)}
		/>
	{/if}

	<span class="w-24 shrink-0">
		{#if group.cheapestInStockPrice !== null}
			<span class="num text-sm font-semibold text-text"
				>{formatAud(group.cheapestInStockPrice)}</span
			>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</span>

	<a
		href={`/product/${group.productId}`}
		class="min-w-0 flex-1 basis-40 truncate text-sm text-text no-underline hover:underline"
		title={group.model}
	>
		{group.model}
	</a>

	<span class="hidden shrink-0 items-center gap-1.5 text-xs text-text-muted sm:flex">
		<BrandIcon brand={group.brand} size={12} />
		{group.brand}
	</span>

	<span class="w-36 shrink-0 text-xs">
		{#if deltaPct !== null}
			{@const d = deltaPresentation(deltaPct)}
			<span class={d.class}
				>{d.arrow}
				{formatPct(deltaPct)}
				{avgWindowLabel(group.avg30Points)}</span
			>
		{:else if group.neverListed}
			<span class="text-text-muted">Not listed</span>
		{:else if group.cheapestInStockPrice === null}
			<span class="text-text-muted">No stock</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</span>

	<span class="w-20 shrink-0 text-right text-xs text-text-muted">{retailerLabel ?? ''}</span>
</div>
