<script lang="ts">
	import Badge from './Badge.svelte';
	import BrandIcon from './BrandIcon.svelte';
	import StockBadge from './StockBadge.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct, formatRelative, titleCase } from '$lib/formats';
	import type { ListingDisplay } from '$lib/offers';

	let {
		offer,
		avg30,
		onToggleChart
	}: {
		offer: ListingDisplay;
		avg30: number | null;
		onToggleChart?: (listingId: number) => void;
	} = $props();

	const retailerLabel = $derived(
		RETAILER_OPTIONS.find((o) => o.value === offer.retailer)?.label ?? offer.retailer
	);

	const title = $derived(titleCase(offer.variantName) || `${retailerLabel} listing`);

	// Null whenever the average is untrustworthy (see MIN_HISTORY_POINTS) or the
	// offer has no price — the row then states that instead of showing a number.
	const deltaPct = $derived(
		offer.latestPrice !== null && avg30 !== null && avg30 !== 0
			? ((offer.latestPrice - avg30) / avg30) * 100
			: null
	);
</script>

<div class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-surface-hover">
	<div class="order-1 w-24 shrink-0">
		{#if offer.latestPrice !== null}
			<span class="num text-base font-semibold text-text">{formatAud(offer.latestPrice)}</span>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</div>

	<div class="order-2 min-w-0 flex-1 basis-full sm:basis-auto">
		<span class="block truncate text-sm font-medium text-text" title={title}>{title}</span>
		<span class="flex items-center gap-1.5 text-xs text-text-muted">
			<BrandIcon brand={offer.brand} size={12} />
			{offer.brand} · {retailerLabel}
			{#if offer.lastSeen}
				· updated {formatRelative(offer.lastSeen)}
			{/if}
		</span>
	</div>

	<div class="order-3 shrink-0 text-xs">
		{#if deltaPct !== null}
			<span class={deltaPct < 0 ? 'text-down' : deltaPct > 0 ? 'text-up' : 'text-text-muted'}>
				{deltaPct < 0 ? '▼' : deltaPct > 0 ? '▲' : '·'}
				{formatPct(deltaPct)} vs 30d avg
			</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</div>

	<div class="order-4 shrink-0">
		{#if offer.delisted}
			<Badge tone="stale" label="Delisted" />
		{:else}
			<StockBadge stock={offer.latestStock} />
		{/if}
	</div>

	{#if onToggleChart}
		<button
			type="button"
			aria-pressed={offer.selected}
			onclick={() => onToggleChart(offer.listingId)}
			class="order-5 shrink-0 rounded-md border border-border px-2 py-1 text-xs {offer.selected
				? 'border-accent bg-accent-soft font-medium text-accent'
				: 'bg-surface text-text-muted hover:text-text'}"
		>
			{offer.selected ? 'On chart' : 'Chart'}
		</button>
	{/if}

	<a
		href={offer.listingUrl}
		target="_blank"
		rel="noopener noreferrer"
		class="order-6 shrink-0 text-xs text-accent"
	>
		View →
	</a>
</div>
