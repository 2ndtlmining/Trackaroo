<script lang="ts">
	import Filters from '$lib/components/Filters.svelte';
	import LatestListingTable from '$lib/components/LatestListingTable.svelte';
	import type { LatestListing } from '$lib/server/repos';

	let { data }: { data: { listings: LatestListing[]; brands: string[] } } = $props();
</script>

<svelte:head>
	<title>Trackaroo — Products</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Products</h1>
		<p class="mt-1 text-sm text-text-muted">
			Latest tracked price for every active listing, with a 7-day change.
		</p>
	</div>

	<div>
		<div class="mb-3">
			<Filters brands={data.brands} />
		</div>
		<LatestListingTable rows={data.listings} />
	</div>
</div>