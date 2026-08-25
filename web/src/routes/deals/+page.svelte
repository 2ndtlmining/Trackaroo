<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import FacetChips from '$lib/components/FacetChips.svelte';
	import OfferRow from '$lib/components/OfferRow.svelte';
	import { dealToOffer, NEAR_ALL_TIME_LOW_PCT } from '$lib/deals';

	let { data } = $props();

	// URL-driven, unlike the product page's client-side chips: /deals is a
	// server-rendered list, so a facet change is a navigation. Same
	// presentational component, different driver — see spec §7.
	function select(key: 'category' | 'retailer' | 'brand', value: string | null) {
		const params = new URLSearchParams(page.url.searchParams);
		if (value === null) params.delete(key);
		else params.set(key, value);
		const qs = params.toString();
		goto(qs ? `/deals?${qs}` : '/deals', { keepFocus: true, noScroll: true });
	}

	const resultCount = $derived(data.belowAverage.length);
</script>

<svelte:head><title>Deals · Trackaroo</title></svelte:head>

<div class="mx-auto max-w-6xl px-4 py-6">
	<h1 class="text-xl font-semibold tracking-tight text-text">Deals</h1>
	<p class="mt-1 text-sm text-text-muted">
		Products whose cheapest in-stock price is below their own recent average (up to 30 days of history).
	</p>

	<div class="mt-4 flex flex-col gap-2">
		<FacetChips
			label="Category"
			options={data.facets.category}
			selected={data.filters.category}
			allCount={data.totals.category}
			onSelect={(v) => select('category', v)}
		/>
		<FacetChips
			label="Retailer"
			options={data.facets.retailer}
			selected={data.filters.retailer}
			allCount={data.totals.retailer}
			onSelect={(v) => select('retailer', v)}
		/>
		<FacetChips
			label="Brand"
			options={data.facets.brand}
			selected={data.filters.brand}
			allCount={data.totals.brand}
			onSelect={(v) => select('brand', v)}
		/>
	</div>

	<p class="mt-3 text-xs text-text-muted" aria-live="polite" data-testid="deals-count">
		{resultCount}
		{resultCount === 1 ? 'product' : 'products'} below their recent average
	</p>

	<section class="mt-4" aria-labelledby="below-average-heading">
		<h2 id="below-average-heading" class="text-sm font-semibold text-text">
			Below recent average
		</h2>
		{#if data.belowAverage.length > 0}
			<div
				class="mt-2 divide-y divide-border rounded-lg border border-border bg-surface"
				data-testid="below-average-list"
			>
				{#each data.belowAverage as deal (deal.productId)}
					<OfferRow
						offer={dealToOffer(deal)}
						avg30={deal.avg30}
						avgPoints={deal.avg30Points}
						titleOverride={deal.model}
						detailHref={`/product/${deal.productId}`}
					/>
				{/each}
			</div>
		{:else}
			<p
				class="mt-2 rounded-lg border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted"
			>
				No products are below their recent average today.
			</p>
		{/if}
	</section>

	<section class="mt-8 scroll-mt-4" id="all-time-low" aria-labelledby="all-time-low-heading">
		<h2 id="all-time-low-heading" class="text-sm font-semibold text-text">
			At or near all-time low
		</h2>
		<p class="mt-0.5 text-xs text-text-muted">
			Within {NEAR_ALL_TIME_LOW_PCT}% of the lowest price ever recorded.
		</p>
		{#if data.atAllTimeLow.length > 0}
			<div
				class="mt-2 divide-y divide-border rounded-lg border border-border bg-surface"
				data-testid="all-time-low-list"
			>
				{#each data.atAllTimeLow as deal (deal.productId)}
					<OfferRow
						offer={dealToOffer(deal)}
						avg30={deal.avg30}
						avgPoints={deal.avg30Points}
						titleOverride={deal.model}
						detailHref={`/product/${deal.productId}`}
					/>
				{/each}
			</div>
		{:else}
			<p
				class="mt-2 rounded-lg border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted"
			>
				No products are within {NEAR_ALL_TIME_LOW_PCT}% of their all-time low today.
			</p>
		{/if}
	</section>
</div>
