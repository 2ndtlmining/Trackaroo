<script lang="ts">
	import PriceChart, { type ChartSeries } from '$lib/components/PriceChart.svelte';
	import Chip from '$lib/components/Chip.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import SpecPanel from '$lib/components/SpecPanel.svelte';
	import { formatAud, formatDate, stockLabel } from '$lib/formats';
	import type { StockStatus } from '$lib/types';
	import type { BadgeTone } from '$lib/components/Badge.svelte';
	import type { ProductHistory } from '$lib/server/repos';

	let { data }: { data: ProductHistory } = $props();

	const product = $derived(data.product);
	const series = $derived(data.series);

	const chartSeries = $derived<ChartSeries[]>(
		series
			.filter((s) => s.points.length > 0)
			.map((s, i) => ({
				listingId: s.listing.id,
				label:
					s.listing.variant_name ??
					`${s.listing.retailer} SKU ${s.listing.retailer_sku ?? '?'}`,
				points: s.points.map((p) => ({ date: p.snapshot_date, price: p.price_aud }))
			}))
	);

	const allDates = $derived(
		series.flatMap((s) => s.points.map((p) => p.snapshot_date)).sort()
	);
	const span = $derived(
		allDates.length
			? `${formatDate(allDates[0])} – ${formatDate(allDates[allDates.length - 1])}`
			: 'No data'
	);
	const totalPoints = $derived(
		series.reduce((acc, s) => acc + s.points.length, 0)
	);

	function stockTone(stock: StockStatus): BadgeTone {
		switch (stock) {
			case 'in_stock':
				return 'up';
			case 'out_of_stock':
			case 'unknown':
				return 'neutral';
			case 'preorder':
				return 'accent';
		}
	}
</script>

<svelte:head>
	<title>Trackaroo — {product.brand} {product.model}</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<p class="text-sm text-text-muted">{product.brand}</p>
		<h1 class="text-xl font-semibold text-text">
			{product.model}{product.variant ? ` · ${product.variant}` : ''}
		</h1>

		<div class="mt-3 flex flex-wrap items-center gap-2">
			{#if product.category}
				<Chip label="Category" value={product.category} />
			{/if}
			{#if product.generation_tier}
				<Chip label="Generation" value={product.generation_tier} />
			{/if}
			<Chip label="Listings" value={String(series.length)} />
			<Chip label="History span" value={span} />
			<Chip label="Snapshots" value={String(totalPoints)} />
		</div>
	</div>

	{#if chartSeries.length === 0}
		<div
			class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
		>
			No price history recorded for this product yet.
		</div>
	{:else}
		<div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
			<PriceChart series={chartSeries} height={360} />

			<div class="overflow-hidden rounded-md border border-border">
				<h2 class="border-b border-border bg-surface px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
					Retailer listings
				</h2>
				<ul class="divide-y divide-border text-sm">
					{#each series as s (s.listing.id)}
						<li class="flex items-center justify-between gap-3 px-3 py-2.5">
							<a
								href={s.listing.listing_url}
								target="_blank"
								rel="noopener noreferrer"
								class="min-w-0 flex-1"
							>
								<span class="block truncate font-medium text-text">
									{s.listing.variant_name ??
										`${s.listing.retailer} ${s.listing.retailer_sku ?? ''}`.trim()}
								</span>
								<span class="text-xs text-text-muted">
									{s.points.length
										? `${formatDate(s.points[0].snapshot_date)} – ${formatDate(s.points[s.points.length - 1].snapshot_date)}`
										: 'No history'}
								</span>
							</a>
							<div class="shrink-0 text-right">
								{#if s.points.length > 0}
									<span class="num block text-text">
										{formatAud(s.points[s.points.length - 1].price_aud)}
									</span>
									<Badge
										tone={stockTone(s.points[s.points.length - 1].stock_status)}
										label={stockLabel(s.points[s.points.length - 1].stock_status)}
									/>
								{:else}
									<span class="text-xs text-text-muted">—</span>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{/if}

	{#if data.specs}
		<SpecPanel spec={data.specs} />
	{/if}
</div>