<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Badge from './Badge.svelte';
	import BrandIcon from './BrandIcon.svelte';
	import StockBadge from './StockBadge.svelte';
	import { retailerLabel as lookupRetailerLabel } from '$lib/filters';
	import {
		formatAud,
		formatPct,
		formatSeenDate,
		formatShortDate,
		formatSignedAud,
		titleCase,
		todayIso
	} from '$lib/formats';
	import { MSRP_TONE_CLASS, formatMsrpDelta, msrpTone } from '$lib/msrp';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30, type ListingDisplay } from '$lib/offers';

	let {
		offer,
		avg30,
		onToggleChart,
		titleOverride,
		detailHref,
		avgPoints,
		saving,
		lowSince,
		nearLowSince,
		vsMsrp
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
		// Set when the price actually IS the all-time low (or a new one) --
		// the date "all-time" is measured from (#6).
		lowSince?: string | null;
		// Set when the price is only NEAR the all-time low (within the
		// earned-low tolerance) but not actually at or below it -- shows a
		// "Near low since" badge instead, so the row never overclaims (M3,
		// 28-Sep finding). Mutually exclusive with lowSince; lowSince wins if
		// both are somehow given.
		nearLowSince?: string | null;
		// /deals only (Task 3): the price against US launch MSRP in today's AUD
		// (msrpDelta). null shows "–"; undefined leaves the cell out.
		vsMsrp?: number | null;
	} = $props();

	const retailerLabel = $derived(lookupRetailerLabel(offer.retailer));

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
			{#if vsMsrp !== undefined}
				<span data-testid="deal-msrp"
					>· vs MSRP <span
						class="num font-medium {vsMsrp === null ? 'text-text-muted' : MSRP_TONE_CLASS[msrpTone(vsMsrp)]}"
						data-testid="deal-msrp-value">{formatMsrpDelta(vsMsrp)}</span
					></span
				>
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
		{:else if nearLowSince}
			<Badge tone="accent" label={`Near low since ${formatShortDate(nearLowSince)}`} />
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
		class="order-6 inline-flex shrink-0 items-center gap-0.5 text-xs text-accent"
	>
		Buy at {retailerLabel}
		<ArrowUpRight size={12} aria-hidden="true" />
	</a>
</div>
