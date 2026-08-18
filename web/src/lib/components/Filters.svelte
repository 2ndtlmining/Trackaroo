<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		CATEGORY_OPTIONS,
		RETAILER_OPTIONS,
		SORT_OPTIONS,
		TIER_OPTIONS,
		hasActiveFilters,
		parseFilters,
		updateFilter
	} from '$lib/filters';
	import type { ListingFilters } from '$lib/types';

	let { brands = [] }: { brands?: string[] } = $props();

	const filters = $derived(parseFilters(page.url.searchParams));
	const active = $derived(hasActiveFilters(filters));

	async function set(key: keyof ListingFilters, value: string) {
		const next = updateFilter(page.url.searchParams, key, value || null);
		const qs = next.toString();
		await goto(qs ? `?${qs}` : page.url.pathname);
	}

	let queryTimer: ReturnType<typeof setTimeout> | undefined;
	function setQuery(value: string) {
		if (value === (filters.query ?? '')) return;
		clearTimeout(queryTimer);
		queryTimer = setTimeout(() => {
			set('query', value);
		}, 450);
	}

	async function clear() {
		await goto(page.url.pathname);
	}
</script>

<div class="flex flex-wrap items-center gap-2">
	<select
		class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		value={filters.category ?? ''}
		aria-label="Filter by category"
		onchange={(e) => set('category', (e.target as HTMLSelectElement).value)}
	>
		<option value="">All categories</option>
		{#each CATEGORY_OPTIONS as opt}
			<option value={opt.value}>{opt.label}</option>
		{/each}
	</select>

	<select
		class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		value={filters.retailer ?? ''}
		aria-label="Filter by retailer"
		onchange={(e) => set('retailer', (e.target as HTMLSelectElement).value)}
	>
		<option value="">All retailers</option>
		{#each RETAILER_OPTIONS as opt}
			<option value={opt.value}>{opt.label}</option>
		{/each}
	</select>

	<select
		class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		value={filters.brand ?? ''}
		aria-label="Filter by brand"
		onchange={(e) => set('brand', (e.target as HTMLSelectElement).value)}
	>
		<option value="">All brands</option>
		{#each brands as brand}
			<option value={brand}>{brand}</option>
		{/each}
	</select>

	<select
		class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		value={filters.generation_tier ?? ''}
		aria-label="Filter by generation tier"
		onchange={(e) => set('generation_tier', (e.target as HTMLSelectElement).value)}
	>
		<option value="">All generations</option>
		{#each TIER_OPTIONS as opt}
			<option value={opt.value}>{opt.label}</option>
		{/each}
	</select>

	<input
		type="search"
		value={filters.query ?? ''}
		aria-label="Search by model"
		placeholder="Search model…"
		oninput={(e) => setQuery((e.target as HTMLInputElement).value)}
		class="h-8 w-40 rounded-md border border-border bg-surface px-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
	/>

	<label
		class="flex h-8 cursor-pointer select-none items-center gap-1.5 rounded-md border border-border bg-surface px-2 text-sm text-text"
	>
		<input
			type="checkbox"
			class="accent-accent"
			aria-label="In stock only"
			checked={filters.inStock ?? false}
			onchange={(e) => set('inStock', (e.target as HTMLInputElement).checked ? '1' : '')}
		/>
		In stock
	</label>

	<select
		class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		value={filters.sort ?? ''}
		aria-label="Sort by price"
		onchange={(e) => set('sort', (e.target as HTMLSelectElement).value)}
	>
		<option value="">Sort: default</option>
		{#each SORT_OPTIONS as opt}
			<option value={opt.value}>{opt.label}</option>
		{/each}
	</select>

	{#if active}
		<button
			type="button"
			onclick={clear}
			class="h-8 rounded-md border border-border bg-surface px-2.5 text-sm text-text-muted hover:bg-surface-hover hover:text-text"
		>
			Clear filters
		</button>
	{/if}
</div>
