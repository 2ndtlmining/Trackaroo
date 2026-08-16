<script lang="ts">
	import Filters from '$lib/components/Filters.svelte';
	import ProductCard from '$lib/components/ProductCard.svelte';
	import type { ProductGroup } from '$lib/server/repos';
	import type { Category } from '$lib/types';

	let { data }: { data: { groups: ProductGroup[]; brands: string[] } } = $props();

	let compareIds = $state<Set<number>>(new Set());

	const compareCategory = $derived.by(() => {
		const cats = new Set<Category>();
		for (const g of data.groups) {
			if (compareIds.has(g.productId)) cats.add(g.category);
		}
		return cats.size === 1 ? [...cats][0] : null;
	});

	function toggleCompare(productId: number, category: Category) {
		if (compareIds.has(productId)) {
			const next = new Set(compareIds);
			next.delete(productId);
			compareIds = next;
			return;
		}
		if (compareIds.size >= 4) return;
		if (compareCategory !== null && compareCategory !== category) return;
		const next = new Set(compareIds);
		next.add(productId);
		compareIds = next;
	}

	const compareUrl = $derived(`/compare?ids=${[...compareIds].join(',')}`);
</script>

<svelte:head>
	<title>Trackaroo — Products</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Products</h1>
		<p class="mt-1 text-sm text-text-muted">
			Every tracked product as a card — expand one to see each retailer listing with its
			7-day change. Tick up to 4 in the same category to compare them.
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
					<ProductCard
						{group}
						compareSelected={compareIds.has(group.productId)}
						compareDisabled={compareCategory !== null &&
							compareCategory !== group.category}
						onToggleCompare={(id) => toggleCompare(id, group.category)}
					/>
				{/each}
			</div>
		{/if}
	</div>
</div>

{#if compareIds.size >= 2}
	<div
		class="fixed inset-x-0 bottom-4 z-20 flex justify-center px-4"
		role="region"
		aria-label="Compare bar"
	>
		<div
			class="flex items-center gap-3 rounded-full border border-border bg-surface px-4 py-2 shadow-lg"
		>
			<span class="text-sm text-text-muted">{compareIds.size} selected</span>
			<button
				type="button"
				onclick={() => (compareIds = new Set())}
				class="text-xs text-text-muted hover:text-text"
			>
				Clear
			</button>
			<a
				href={compareUrl}
				class="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-surface no-underline hover:opacity-90"
			>
				Compare ({compareIds.size}) →
			</a>
		</div>
	</div>
{/if}
