<script lang="ts">
	import Filters from '$lib/components/Filters.svelte';
	import ProductCard from '$lib/components/ProductCard.svelte';
	import type { ProductGroup } from '$lib/server/repos';

	let { data }: { data: { groups: ProductGroup[]; brands: string[] } } = $props();
</script>

<svelte:head>
	<title>Trackaroo — Products</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Products</h1>
		<p class="mt-1 text-sm text-text-muted">
			Every tracked product as a card — expand one to see each retailer listing with its
			7-day change.
		</p>
	</div>

	<div>
		<div class="mb-3">
			<Filters brands={data.brands} />
		</div>
		{#if data.groups.length === 0}
			<div
				class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
			>
				No listings match the current filters.
			</div>
		{:else}
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
				{#each data.groups as group (group.productId)}
					<ProductCard {group} />
				{/each}
			</div>
		{/if}
	</div>
</div>
