<script lang="ts">
	import FacetChips from './FacetChips.svelte';
	import OfferRow from './OfferRow.svelte';
	import { toListingDisplays } from '$lib/listingsPanel';
	import { applyStockFilter, buildOfferView, facetCounts, type OfferFilters } from '$lib/offers';
	import type { Series } from '$lib/models';

	let {
		series,
		productBrand,
		avg30,
		avgPoints,
		selected,
		onToggleListing,
		retailerLatest = {}
	}: {
		series: Series[];
		productBrand: string;
		avg30: number | null;
		// Days behind avg30, so each row's label states real evidence.
		avgPoints?: number;
		selected: ReadonlySet<number>;
		onToggleListing: (listingId: number) => void;
		// Latest snapshot_date per retailer, used to flag listings unseen for
		// STALE_LISTING_DAYS+ even before the pipeline marks them stale (#4).
		retailerLatest?: Record<string, string>;
	} = $props();

	// Out-of-stock listings are noise for someone shopping today, and on a
	// popular GPU they are often half the rows. The control states what it
	// hides, so nothing is silently disappeared.
	let inStockOnly = $state(true);
	let retailer = $state<string | null>(null);
	let brand = $state<string | null>(null);
	let query = $state('');
	let expanded = $state(false);

	const offers = $derived(toListingDisplays(series, productBrand, selected, retailerLatest));
	const filters = $derived<OfferFilters>({ inStockOnly, retailer, brand, query });
	const view = $derived(buildOfferView(offers, filters, expanded));

	// Facet counts reflect the stock-filtered set, not the raw offer list — the
	// checkbox default hides out-of-stock rows, so a chip's count (and the
	// "All N" total) must agree with what clicking it actually produces.
	// Computed independently of the retailer/brand chips themselves so every
	// chip in a row still shows its own count regardless of which one (if any)
	// is currently selected.
	const stockFiltered = $derived(applyStockFilter(offers, inStockOnly).offers);
	const retailerFacets = $derived(facetCounts(stockFiltered, 'retailer'));
	const brandFacets = $derived(facetCounts(stockFiltered, 'brand'));
	const allCount = $derived(stockFiltered.length);

	// A facet row hides itself once it has one option left (FacetChips), which
	// the stock filter can now trigger. If the chip a visitor had selected is
	// one that just vanished, the selection must clear too — otherwise the
	// list stays filtered by a control that is no longer on screen.
	$effect(() => {
		if (retailer !== null && !retailerFacets.some((o) => o.value === retailer)) {
			retailer = null;
		}
	});
	$effect(() => {
		if (brand !== null && !brandFacets.some((o) => o.value === brand)) {
			brand = null;
		}
	});
</script>

<div class="overflow-hidden rounded-xl border border-border-card bg-surface shadow-card">
	<div class="space-y-2 border-b border-border bg-surface px-3 py-2">
		<h2 class="text-section">Offers</h2>

		<FacetChips
			label="Retailer"
			options={retailerFacets}
			selected={retailer}
			{allCount}
			onSelect={(v) => {
				retailer = v;
				expanded = false;
			}}
		/>
		<FacetChips
			label="Brand"
			options={brandFacets}
			selected={brand}
			{allCount}
			onSelect={(v) => {
				brand = v;
				expanded = false;
			}}
		/>

		<div class="flex flex-wrap items-center gap-2">
			<input
				type="search"
				aria-label="Filter offers by name"
				placeholder="Filter by name…"
				bind:value={query}
				class="w-full min-w-0 flex-1 rounded-md border border-border-input bg-surface px-2.5 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
			{#if !view.stockFilterForcedOff}
				<label class="flex items-center gap-1.5 text-xs text-text-muted">
					<input type="checkbox" bind:checked={inStockOnly} class="accent-accent" />
					In stock only ({view.inStockCount} of {view.total})
				</label>
			{/if}
		</div>
	</div>

	<!--
		Chip and checkbox filters re-render the list client-side with no
		navigation. Sighted users see the rows change; a screen-reader user got
		no announcement at all, so this states the new result count — same
		pattern as the aria-live regions on /products and / (+page.svelte).
	-->
	<p aria-live="polite" class="sr-only">
		{view.matched} {view.matched === 1 ? 'offer' : 'offers'} match the current filters.
	</p>

	{#if view.stockFilterForcedOff}
		<p class="border-b border-border bg-surface px-3 py-2 text-xs text-text-muted">
			Nothing is in stock right now — showing all {view.total} offers.
		</p>
	{/if}

	{#if view.visible.length === 0}
		<p class="px-4 py-8 text-center text-sm text-text-muted">
			No listings match the current filters.
		</p>
	{:else}
		<div class="divide-y divide-border">
			{#each view.visible as o (o.listingId)}
				<OfferRow offer={o} {avg30} {avgPoints} onToggleChart={onToggleListing} />
			{/each}
		</div>
	{/if}

	{#if view.showExpander}
		<button
			type="button"
			aria-expanded={expanded}
			onclick={() => (expanded = !expanded)}
			class="w-full border-t border-border px-3 py-2 text-xs text-accent hover:bg-surface-hover"
		>
			{expanded ? 'Show fewer offers' : `Show all ${view.matched} offers`}
		</button>
	{/if}
</div>
