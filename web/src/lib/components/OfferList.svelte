<script lang="ts">
	import FacetChips from './FacetChips.svelte';
	import OfferRow from './OfferRow.svelte';
	import { toListingDisplays } from '$lib/listingsPanel';
	import { buildOfferView, facetCounts, type OfferFilters } from '$lib/offers';
	import type { Series } from '$lib/server/repos';

	let {
		series,
		productBrand,
		avg30,
		selected,
		onToggleListing
	}: {
		series: Series[];
		productBrand: string;
		avg30: number | null;
		selected: ReadonlySet<number>;
		onToggleListing: (listingId: number) => void;
	} = $props();

	// Out-of-stock listings are noise for someone shopping today, and on a
	// popular GPU they are often half the rows. The control states what it
	// hides, so nothing is silently disappeared.
	let inStockOnly = $state(true);
	let retailer = $state<string | null>(null);
	let brand = $state<string | null>(null);
	let query = $state('');
	let expanded = $state(false);

	const offers = $derived(toListingDisplays(series, productBrand, selected));
	const filters = $derived<OfferFilters>({ inStockOnly, retailer, brand, query });
	const view = $derived(buildOfferView(offers, filters, expanded));
	const retailerFacets = $derived(facetCounts(offers, 'retailer'));
	const brandFacets = $derived(facetCounts(offers, 'brand'));
</script>

<div class="overflow-hidden rounded-md border border-border">
	<div class="space-y-2 border-b border-border bg-surface px-3 py-2">
		<h2 class="text-xs font-semibold uppercase tracking-wide text-text-muted">Offers</h2>

		<FacetChips
			label="Retailer"
			options={retailerFacets}
			selected={retailer}
			allCount={offers.length}
			onSelect={(v) => {
				retailer = v;
				expanded = false;
			}}
		/>
		<FacetChips
			label="Brand"
			options={brandFacets}
			selected={brand}
			allCount={offers.length}
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
				class="w-full min-w-0 flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
			{#if !view.stockFilterForcedOff}
				<label class="flex items-center gap-1.5 text-xs text-text-muted">
					<input type="checkbox" bind:checked={inStockOnly} class="accent-accent" />
					In stock only ({view.inStockCount} of {view.total})
				</label>
			{/if}
		</div>
	</div>

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
				<OfferRow offer={o} {avg30} onToggleChart={onToggleListing} />
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
