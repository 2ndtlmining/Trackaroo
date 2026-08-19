<script lang="ts">
	import PriceChart, { type ChartSeries } from '$lib/components/PriceChart.svelte';
	import Chip from '$lib/components/Chip.svelte';
	import SpecPanel from '$lib/components/SpecPanel.svelte';
	import BrandGroupedListings from '$lib/components/BrandGroupedListings.svelte';
	import BrandIcon from '$lib/components/BrandIcon.svelte';
	import { formatAud, formatDate, formatRelative, titleCase } from '$lib/formats';
	import { generationTierLabel } from '$lib/tiers';
	import type { ProductHistory } from '$lib/server/repos';

	let { data }: { data: ProductHistory } = $props();

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

	const bandLows = $derived(band ? band.low.filter((v): v is number => v !== null) : []);
	const bandHighs = $derived(band ? band.high.filter((v): v is number => v !== null) : []);
	const ninetyDayLow = $derived(bandLows.length ? Math.min(...bandLows) : null);
	const ninetyDayHigh = $derived(bandHighs.length ? Math.max(...bandHighs) : null);
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

		<div class="mt-3 flex flex-wrap items-center gap-2">
			{#if product.category}
				<Chip label="Category" value={product.category} />
			{/if}
			{#if product.generation_tier}
				<Chip
					label="Generation"
					value={generationTierLabel(product.brand, product.category, product.generation_tier) ?? product.generation_tier}
				/>
			{/if}
			{#if ninetyDayLow !== null}
				<Chip label="90d low" value={formatAud(ninetyDayLow)} />
			{/if}
			{#if ninetyDayHigh !== null}
				<Chip label="90d high" value={formatAud(ninetyDayHigh)} />
			{/if}
			<Chip label="Listings" value={String(series.length)} />
			<Chip label="History span" value={span} />
			<Chip label="Snapshots" value={String(totalPoints)} />
		</div>
		{#if product.last_snapshot_at}
			<p class="mt-2 text-xs text-text-muted">
				Updated {formatRelative(product.last_snapshot_at)}
			</p>
		{/if}
	</div>

	{#if hasChartData}
		<div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
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
			<BrandGroupedListings
				series={data.series}
				productBrand={product.brand}
				selected={selected}
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

	{#if data.specs}
		<SpecPanel spec={data.specs} />
	{/if}
</div>