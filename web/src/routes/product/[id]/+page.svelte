<script lang="ts">
	import PriceChart from '$lib/components/PriceChart.svelte';
	import type { ChartSeries } from '$lib/priceChartPlot';
	import SpecPanel from '$lib/components/SpecPanel.svelte';
	import ProductHeadline from '$lib/components/ProductHeadline.svelte';
	import BuyPanel from '$lib/components/BuyPanel.svelte';
	import OzbDealsPanel from '$lib/components/OzbDealsPanel.svelte';
	import OfferList from '$lib/components/OfferList.svelte';
	import BrandIcon from '$lib/components/BrandIcon.svelte';
	import PriceAlerts from '$lib/components/PriceAlerts.svelte';
	import PageHead from '$lib/components/PageHead.svelte';
	import PriceDataTable from '$lib/components/PriceDataTable.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { productBreadcrumbs } from '$lib/breadcrumbs';
	import { chartSummary } from '$lib/chartSummary';
	import type { AlertChannel } from '$lib/types';
	import { formatDate, titleCase, updatedLabel } from '$lib/formats';
	import { retailerLabel } from '$lib/filters';
	import { productPageTitle } from '$lib/head';
	import { generationTierLabel } from '$lib/tiers';
	import { buildHeadline } from '$lib/productHeadline';
	import { toListingDisplays } from '$lib/listingsPanel';
	import { asOfDate, buildSignals, dailyLows, lowSummary, whereToBuy, windowStats } from '$lib/buySignals';
	import { buildDisplayNames, displayName } from '$lib/displayName';
	import { type ProductHistory, type AlertRow, type FxRate, type ProductIndexEntry, type OzbDeal } from '$lib/models';

	let {
		data,
		form
	}: {
		data: ProductHistory & {
			alerts: AlertRow[];
			productIndex: ProductIndexEntry[];
			fx: FxRate | null;
			msrpUsd: number | null;
			today: string;
			ozb: { live: OzbDeal[]; expired: OzbDeal[] };
			ozbBest: number | null;
			ozbNow: string;
		};
		form: { error?: string; target_price?: string; channel?: AlertChannel } | null;
	} = $props();

	const product = $derived(data.product);
	const series = $derived(data.series);
	// "GeForce RTX 5060 Ti 16GB" where a "... 8GB" sibling exists (display only).
	const name = $derived(displayName(buildDisplayNames(data.productIndex), product.id, product.model));

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
				`${retailerLabel(s.listing.retailer)} SKU ${s.listing.retailer_sku ?? '?'}`,
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

	const offers = $derived(
		toListingDisplays(series, product.brand, selected, data.retailerLatest)
	);
	const headline = $derived(buildHeadline(offers, data.band, data.stats));

	const lows = $derived(dailyLows(data.band));
	const asOf = $derived(asOfDate(data.retailerLatest, lows));
	const low = $derived(lowSummary(lows, headline.currentPrice));
	const buyWindows = $derived(asOf ? [30, 90, 180].map((d) => windowStats(lows, asOf, d)) : []);
	// The successor map is keyed by the spec's series ("GeForce 50"); the sale
	// lookahead reads today's date in Melbourne inside buildSignals.
	const signals = $derived(
		buildSignals({
			lows,
			today: headline.currentPrice,
			asOf,
			avg30: headline.avg30 ?? null,
			series: data.specs?.generation ?? null,
			todayIso: data.today
		})
	);
	const where = $derived(whereToBuy(offers));
	// Memory / cores in the headline: "RTX 5060 Ti" alone does not say which card
	// this is when an 8GB sibling exists (#31 core; Phase 1 #2 split them).
	// Skipped when the name already ends in the size ("... 16GB" from the
	// display-name rule, or a stored "... 8GB" model), so it is never said twice.
	const nameHasVram = $derived(
		product.vram_gb != null && name.toLowerCase().endsWith(` ${product.vram_gb}gb`)
	);
	const specLabel = $derived(
		product.category === 'gpu' && product.vram_gb && !nameHasVram
			? `${product.vram_gb}GB`
			: product.category === 'cpu' && product.cores
				? `${product.cores} cores`
				: null
	);
</script>

<PageHead
	titleOverride={productPageTitle(
		`${name}${product.variant ? ` · ${product.variant}` : ''}`,
		headline.currentPrice,
		headline.currentRetailer ? retailerLabel(headline.currentRetailer) : null
	)}
	description={`${product.brand} ${name}: AU price history, today's cheapest offer and where to buy.`}
/>

<div class="space-y-6">
	<div>
		<PageHeader
			title={`${name}${product.variant ? ` · ${product.variant}` : ''}`}
			crumbs={productBreadcrumbs({ ...product, model: name })}
		>
			{#snippet meta()}
				<p class="flex items-center gap-1.5 font-medium text-text" data-testid="product-brand">
					<BrandIcon brand={product.brand} size={16} />
					{product.brand}
				</p>
				<p data-testid="product-meta">
					{product.category?.toUpperCase()}
					{#if specLabel}· {specLabel}{/if}
					{#if product.generation_tier}
						· {generationTierLabel(product.brand, product.category, product.generation_tier) ??
							product.generation_tier}
					{/if}
				</p>
			{/snippet}
			{#snippet actions()}
				<a
					href="/products?category={product.category}&compare={product.id}"
					class="inline-flex min-h-9 items-center rounded-lg border border-border-input bg-surface-2 px-3.5 text-body font-semibold text-text no-underline hover:bg-surface-hover"
				>
					Compare with…
				</a>
			{/snippet}
		</PageHeader>

		<div>
			<ProductHeadline
				{headline}
				listingCount={series.length}
				snapshotCount={totalPoints}
				{span}
				msrpUsd={data.msrpUsd}
				fx={data.fx}
			/>
		</div>
		{#if product.last_snapshot_at}
			<p class="mt-2 text-xs text-text-muted">
				{updatedLabel(product.last_snapshot_at)}
			</p>
		{/if}
	</div>

	<BuyPanel {low} windows={buyWindows} {where} {signals} />

	<OzbDealsPanel live={data.ozb.live} expired={data.ozb.expired} best={data.ozbBest} now={data.ozbNow} />

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
				lowMarker={low?.low ?? null}
				avg30={headline.avg30 ?? null}
				summary={chartSummary(lows, headline.currentPrice)}
				height={360}
			/>
			<PriceDataTable band={data.band} />
			<OfferList
				series={data.series}
				productBrand={product.brand}
				avg30={headline.avg30}
				avgPoints={headline.avgPoints}
				{selected}
				onToggleListing={toggleListing}
				retailerLatest={data.retailerLatest}
			/>
		</div>
	{:else}
		<div
			class="rounded-xl border border-border-card bg-surface shadow-card px-4 py-8 text-center text-sm text-text-muted"
		>
			No price history recorded for this product yet.
		</div>
	{/if}

	<PriceAlerts alerts={data.alerts} {form} />

	{#if data.specs}
		<SpecPanel spec={data.specs} />
	{/if}
</div>