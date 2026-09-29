<script lang="ts">
	import BrandIcon from './BrandIcon.svelte';
	import { retailerLabel as lookupRetailerLabel } from '$lib/filters';
	import { formatAud, formatMonthYear, formatPct } from '$lib/formats';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30 } from '$lib/offers';
	import type { CatalogRow } from '$lib/productIndex';

	let {
		group,
		compareSelected = false,
		compareDisabled = false,
		onToggleCompare
	}: {
		// neverListed: tracked in the watchlist but no retailer has ever listed
		// it — a different statement from "listed, currently out of stock".
		// The /products loader drops `listings` from each group (#28) — nothing
		// here reads it — so the prop type omits it too, matching what actually
		// arrives. The catalog columns (#23) are optional: search results and
		// older callers may not carry them.
		group: CatalogRow;
		compareSelected?: boolean;
		compareDisabled?: boolean;
		onToggleCompare?: (productId: number) => void;
	} = $props();

	const retailerLabel = $derived(
		group.cheapestInStockRetailer ? lookupRetailerLabel(group.cheapestInStockRetailer) : null
	);

	const deltaPct = $derived(deltaVsAvg30(group.cheapestInStockPrice, group.avg30 ?? null));

	const specHeader = $derived(group.category === 'gpu' ? 'VRAM' : 'Cores');
	const specValue = $derived(
		group.category === 'gpu'
			? group.vramGb
				? `${group.vramGb}GB`
				: '—'
			: group.cores
				? String(group.cores)
				: '—'
	);
	// The sr-only labels below are expressions, not literal text: Svelte trims
	// a literal trailing space, and "Released:—" reads badly aloud.
	const released = $derived(group.launchDate ? formatMonthYear(group.launchDate) : '—');
</script>

<div
	class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-surface-hover"
	data-testid="catalog-row"
>
	{#if onToggleCompare}
		<!-- The padded label is the touch target: a bare 13px checkbox is well
		     under the 24px WCAG 2.2 AA minimum and awkward to hit on a phone.
		     Negative margin keeps the row's visual density unchanged. Its title
		     and aria-label say what ticking does (U5). -->
		<label
			class="-m-2 flex w-14 shrink-0 items-center p-2"
			class:cursor-pointer={!compareDisabled}
			title="Add to comparison"
		>
			<input
				type="checkbox"
				class="size-4 shrink-0 accent-accent"
				checked={compareSelected}
				disabled={compareDisabled}
				aria-label={`Compare ${group.model}`}
				onchange={() => onToggleCompare?.(group.productId)}
			/>
		</label>
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
		class="min-w-0 flex-1 basis-40 truncate text-sm no-underline hover:underline {group.neverListed
			? 'text-text-muted'
			: 'text-text'}"
		title={group.model}
	>
		{group.model}
	</a>

	<span class="hidden w-16 shrink-0 text-right text-xs text-text-muted md:inline"
		><span class="sr-only">{`${specHeader}: `}</span><span class="num">{specValue}</span></span
	>
	<span class="hidden w-20 shrink-0 text-xs text-text-muted md:inline"
		><span class="sr-only">{'Released: '}</span>{released}</span
	>
	<span
		class="hidden w-20 shrink-0 text-right text-xs text-text-muted md:inline"
		title="In stock of listed"
		><span class="sr-only">{'Listings: '}</span><span class="num"
			>{group.inStockCount} of {group.listingCount ?? 0}</span
		></span
	>

	<span class="hidden shrink-0 items-center gap-1.5 text-xs text-text-muted lg:flex">
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
