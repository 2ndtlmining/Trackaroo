<script lang="ts">
	import PriceRangeBar from './PriceRangeBar.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import { deltaPresentation } from '$lib/offers';
	import type { Headline } from '$lib/productHeadline';

	let {
		headline,
		listingCount,
		snapshotCount,
		span
	}: {
		headline: Headline;
		listingCount: number;
		snapshotCount: number;
		span: string;
	} = $props();

	const retailerLabel = $derived(
		headline.currentRetailer
			? (RETAILER_OPTIONS.find((o) => o.value === headline.currentRetailer)?.label ??
				headline.currentRetailer)
			: null
	);
</script>

<div class="space-y-3">
	{#if headline.currentPrice !== null}
		<div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
			<span class="num text-3xl font-semibold text-text">{formatAud(headline.currentPrice)}</span>
			<span class="flex flex-wrap items-center gap-x-3 text-sm">
				{#if headline.vsAvg30Pct !== null}
					{@const d = deltaPresentation(headline.vsAvg30Pct)}
					<span class={d.class}>
						{d.arrow}
						{formatPct(headline.vsAvg30Pct)} vs 30d avg
					</span>
				{:else}
					<span class="text-text-muted">Not enough history</span>
				{/if}
				{#if headline.vsAllTimeLowPct !== null && headline.vsAllTimeLowPct > 0}
					<span class="text-text-muted">
						▲ {formatPct(headline.vsAllTimeLowPct)} above all-time low
					</span>
				{:else if headline.vsAllTimeLowPct !== null}
					<span class="text-down">At its all-time low</span>
				{/if}
			</span>
		</div>
		{#if retailerLabel}
			<p class="text-sm text-text-muted">at {retailerLabel}</p>
		{/if}
	{:else}
		<p class="text-sm text-text-muted">No in-stock listings right now.</p>
		{#if headline.allTimeLow !== null && headline.allTimeHigh !== null}
			<p class="text-sm text-text-muted">
				All-time low <span class="num font-medium text-text">{formatAud(headline.allTimeLow)}</span>
				<span class="mx-1">·</span>
				All-time high <span class="num font-medium text-text">{formatAud(headline.allTimeHigh)}</span>
			</p>
		{/if}
	{/if}

	{#if headline.allTimeLow !== null && headline.allTimeHigh !== null && headline.currentPrice !== null}
		<PriceRangeBar
			low={headline.allTimeLow}
			high={headline.allTimeHigh}
			current={headline.currentPrice}
			position={headline.rangePosition}
		/>
	{/if}

	<p class="text-xs text-text-muted">{listingCount} {listingCount === 1 ? 'listing' : 'listings'} · {snapshotCount} snapshots · {span}</p>
</div>
