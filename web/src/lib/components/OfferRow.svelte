<script lang="ts">
	import Badge from './Badge.svelte';
	import BrandIcon from './BrandIcon.svelte';
	import StockBadge from './StockBadge.svelte';
	import { RETAILER_OPTIONS } from '$lib/filters';
	import {
		formatAud,
		formatPct,
		formatSeenDate,
		formatShortDate,
		formatSignedAud,
		titleCase,
		todayIso
	} from '$lib/formats';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30, type ListingDisplay } from '$lib/offers';

	let {
		offer,
		avg30,
		onToggleChart,
		titleOverride,
		detailHref,
		avgPoints,
		saving,
		lowSince
	}: {
		offer: ListingDisplay;
		avg30: number | null;
		onToggleChart?: (listingId: number) => void;
		// /deals renders one row per product, so the row shows the model name
		// and links to the product page. The product page passes neither and
		// keeps the variant-name title with only the outbound retailer link.
		titleOverride?: string;
		detailHref?: string;
		// Days actually behind avg30, so the label states real evidence.
		avgPoints?: number;
		// Dollars below the 30-day average -- when set, replaces the plain
		// delta with the actual saving (#6).
		saving?: number | null;
		// Set when the row earned a new-low badge -- the date "all-time" is
		// measured from (#6).
		lowSince?: string | null;
	} = $props();

	const retailerLabel = $derived(
		RETAILER_OPTIONS.find((o) => o.value === offer.retailer)?.label ?? offer.retailer
	);

	const title = $derived(
		titleOverride ?? (titleCase(offer.variantName) || `${retailerLabel} listing`)
	);

	// Null whenever the average is untrustworthy (see MIN_HISTORY_POINTS) or the
	// offer has no price — the row then states that instead of showing a number.
	const deltaPct = $derived(deltaVsAvg30(offer.latestPrice, avg30));
</script>

<div
	class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-surface-hover"
	data-testid={titleOverride ? 'deal-row' : undefined}
>
	<div class="order-1 w-24 shrink-0">
		{#if offer.latestPrice !== null}
			<span class="num text-base font-semibold text-text">{formatAud(offer.latestPrice)}</span>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</div>

	<div class="order-2 min-w-0 flex-1 basis-full sm:basis-auto">
		{#if detailHref}
			<a
				href={detailHref}
				class="block truncate text-sm font-medium text-text no-underline hover:underline"
				title={title}>{title}</a
			>
		{:else}
			<span class="block truncate text-sm font-medium text-text" title={title}>{title}</span>
		{/if}
		{#if titleOverride && offer.variantName}
			<span class="block truncate text-xs text-text-muted">{titleCase(offer.variantName)}</span>
		{/if}
		<span class="flex items-center gap-1.5 text-xs text-text-muted">
			<BrandIcon brand={offer.brand} size={12} />
			{offer.brand} · {retailerLabel}
			{#if offer.lastSeen}
				· seen {formatSeenDate(offer.lastSeen, todayIso())}
			{/if}
		</span>
	</div>

	<div class="order-3 shrink-0 text-xs">
		{#if typeof saving === 'number' && deltaPct !== null}
			<span class={deltaPresentation(deltaPct).class}>
				{formatSignedAud(-saving)} · {formatPct(deltaPct)} {avgWindowLabel(avgPoints)} ({formatAud(avg30 as number)})
			</span>
		{:else if deltaPct !== null}
			{@const d = deltaPresentation(deltaPct)}
			<span class={d.class}>
				{d.arrow}
				{formatPct(deltaPct)} {avgWindowLabel(avgPoints)}
			</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</div>

	<div class="order-4 shrink-0 flex items-center gap-1.5">
		{#if offer.delisted}
			<Badge tone="stale" label="Delisted" />
		{:else if offer.stale}
			<Badge tone="stale" label={offer.lastSeen ? `Not seen since ${formatShortDate(offer.lastSeen)}` : 'Not seen recently'} />
		{:else}
			<StockBadge stock={offer.latestStock} />
		{/if}
		{#if lowSince}
			<Badge tone="accent" label={`Lowest since ${formatShortDate(lowSince)}`} />
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
		aria-label="Buy at {retailerLabel} (opens in a new tab)"
		class="order-6 shrink-0 text-xs text-accent"
	>
		Buy at {retailerLabel} ↗
	</a>
</div>
