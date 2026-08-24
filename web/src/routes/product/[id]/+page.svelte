<script lang="ts">
	import PriceChart, { type ChartSeries } from '$lib/components/PriceChart.svelte';
	import SpecPanel from '$lib/components/SpecPanel.svelte';
	import ProductHeadline from '$lib/components/ProductHeadline.svelte';
	import OfferList from '$lib/components/OfferList.svelte';
	import BrandIcon from '$lib/components/BrandIcon.svelte';
	import PriceAlerts from '$lib/components/PriceAlerts.svelte';
	import type { AlertChannel } from '$lib/types';
	import { formatDate, formatRelative, titleCase } from '$lib/formats';
	import { generationTierLabel } from '$lib/tiers';
	import { buildHeadline } from '$lib/productHeadline';
	import { toListingDisplays } from '$lib/listingsPanel';
	import { type ProductHistory, type AlertRow } from '$lib/server/repos';

	let {
		data,
		form
	}: {
		data: ProductHistory & { alerts: AlertRow[] };
		form: { error?: string; target_price?: string; channel?: AlertChannel } | null;
	} = $props();

	const product = $derived(data.product);
	const series = $derived(data.series);

	let selected = $state<Set<number>>(new Set());

	function toggleListing(listingId: number) {
		const next = new Set(selected);
		if (next.has(listingId)) next.delete(listingId);
		else next.add(listingId);
		selected = next;
	}

	const allSeries = $derived<ChartSeries[]>(
		series
			.filter((s) => s.points.length > 0)
			.map((s) => ({
				listingId: s.listing.id,
label:
				titleCase(s.listing.variant_name ?? '') ||
				`${s.listing.retailer} SKU ${s.listing.retailer_sku ?? '?'}`,
				points: s.points.map((p) => ({ date: p.snapshot_date, price: p.price_aud }))
			}))
	);

	// Individual listing lines are hidden by default; only the ones the user
	// toggles on in the listings panel are drawn on top of the band chart.
	const overlays = $derived(allSeries.filter((s) => selected.has(s.listingId)));

	const band = $derived(
		data.band.length > 0
			? {
					dates: data.band.map((p) => p.date),
					low: data.band.map((p) => p.low),
					high: data.band.map((p) => p.high)
				}
			: null
	);

	const cheapestInStock = $derived(
		data.band.find((p) => p.cheapestInStock !== null) ?? null
	);

	const hasChartData = $derived(band !== null || overlays.length > 0);

	const allDates = $derived(
		series.flatMap((s) => s.points.map((p) => p.snapshot_date)).sort()
	);
	const span = $derived(
		allDates.length
			? `${formatDate(allDates[0])} – ${formatDate(allDates[allDates.length - 1])}`
			: 'No data'
	);
	const totalPoints = $derived(series.reduce((acc, s) => acc + s.points.length, 0));

	const offers = $derived(toListingDisplays(series, product.brand, selected));
	const headline = $derived(buildHeadline(offers, data.band, data.stats));
</script>

<svelte:head>
	<title>Trackaroo — {product.brand} {product.model}</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<p class="flex items-center gap-1.5 text-sm text-text-muted">
			<BrandIcon brand={product.brand} size={16} />
			{product.brand}
		</p>
		<h1 class="text-xl font-semibold text-text">
			{product.model}{product.variant ? ` · ${product.variant}` : ''}
		</h1>

		<p class="mt-1 text-sm text-text-muted">
			{product.category?.toUpperCase()}
			{#if product.generation_tier}
				· {generationTierLabel(product.brand, product.category, product.generation_tier) ??
					product.generation_tier}
			{/if}
		</p>

		<div class="mt-4">
			<ProductHeadline
				{headline}
				listingCount={series.length}
				snapshotCount={totalPoints}
				{span}
			/>
		</div>
		{#if product.last_snapshot_at}
			<p class="mt-2 text-xs text-text-muted">
				Updated {formatRelative(product.last_snapshot_at)}
			</p>
		{/if}
	</div>

	{#if hasChartData}
		<div class="space-y-4">
			<PriceChart
				series={overlays}
				band={band}
				cheapestInStock={
					cheapestInStock
						? { date: cheapestInStock.date, price: cheapestInStock.cheapestInStock! }
						: null
				}
				height={360}
			/>
			<OfferList
				series={data.series}
				productBrand={product.brand}
				avg30={headline.avg30}
				{selected}
				onToggleListing={toggleListing}
			/>
		</div>
	{:else}
		<div
			class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
		>
			No price history recorded for this product yet.
		</div>
	{/if}

	<PriceAlerts alerts={data.alerts} {form} />

	{#if data.specs}
		<SpecPanel spec={data.specs} />
	{/if}
</div>