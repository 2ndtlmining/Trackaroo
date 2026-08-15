<script lang="ts">
	import { formatDate, formatPct } from '$lib/formats';
	import Filters from '$lib/components/Filters.svelte';
	import LatestListingTable from '$lib/components/LatestListingTable.svelte';
	import StatTile from '$lib/components/StatTile.svelte';
	import CheapestCarousel from '$lib/components/CheapestCarousel.svelte';
	import type { CheapestListing, LatestListing, Summary } from '$lib/server/repos';

	let {
		data
	}: {
		data: {
			summary: Summary;
			listings: LatestListing[];
			brands: string[];
			cheapestGpu: CheapestListing[];
			cheapestCpu: CheapestListing[];
		};
	} = $props();
</script>

<svelte:head>
	<title>Trackaroo — Dashboard</title>
	<meta name="description" content="Latest tracked prices for AU CPUs and GPUs." />
</svelte:head>

<div class="space-y-6">
	<h1 class="text-xl font-semibold text-text">Dashboard</h1>

	<CheapestCarousel gpu={data.cheapestGpu} cpu={data.cheapestCpu} />

	<div class="grid grid-cols-2 gap-4 md:grid-cols-4">
		<StatTile label="Tracked products" value={String(data.summary.trackedProducts)} />
		<StatTile
			label="Listings today"
			value={String(data.summary.listingsToday)}
			sub={data.summary.latestSnapshotDate ? formatDate(data.summary.latestSnapshotDate) : undefined}
		/>
		<StatTile label="Retailers" value={String(data.summary.retailerCount)} />
		{#if data.summary.biggestMover}
			<StatTile
				label="Biggest mover (24h)"
				value={formatPct(data.summary.biggestMover.pctChange ?? 0)}
				sub="{data.summary.biggestMover.model} · {data.summary.biggestMover.retailer}"
			/>
		{:else}
			<StatTile label="Biggest mover (24h)" value="—" />
		{/if}
	</div>

	<div>
		<div class="mb-3">
			<Filters brands={data.brands} />
		</div>
		<LatestListingTable rows={data.listings} />
	</div>
</div>