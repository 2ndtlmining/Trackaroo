<script lang="ts">
	// The /products list (#61: split out of the route): search hits, the empty
	// states, and the sortable table in either flat or series-grouped order.
	import ProductRow from '$lib/components/ProductRow.svelte';
	import { COL, type CatalogColumn } from '$lib/catalogColumns';
	import { earliestYear, shownPrice, shownStock, type CatalogRowInput, type CatalogSort, type CatalogView } from '$lib/catalogView';
	import type { CatalogRow, IndexGroup } from '$lib/productIndex';
	import { MAX_COMPARE } from '$lib/urlState';
	import type { FxRate } from '$lib/models';

	type Item = CatalogRow & CatalogRowInput;

	let {
		heading,
		query,
		searching,
		matches,
		shown,
		groups,
		columns,
		view,
		activeCount,
		clearHref,
		compareIds,
		fx,
		onSort,
		onToggleCompare,
		onClearQuery
	}: {
		heading: string;
		query: string;
		searching: boolean;
		matches: Item[];
		shown: Item[];
		groups: IndexGroup<Item>[];
		columns: CatalogColumn[];
		view: CatalogView;
		activeCount: number;
		clearHref: string;
		compareIds: Set<number>;
		fx: FxRate | null;
		onSort: (key: CatalogSort) => void;
		onToggleCompare: (productId: number) => void;
		onClearQuery: () => void;
	} = $props();

	function ariaSort(key: CatalogSort): 'ascending' | 'descending' | 'none' {
		if (view.sort !== key) return 'none';
		return view.dir === 'asc' ? 'ascending' : 'descending';
	}
</script>

{#snippet row(item: Item)}
	<ProductRow
		group={item}
		price={shownPrice(item, view)}
		retailer={view.retailer ?? undefined}
		outOfStock={shownStock(item, view) === 'out'}
		{fx}
		compareSelected={compareIds.has(item.productId)}
		compareDisabled={!compareIds.has(item.productId) && compareIds.size >= MAX_COMPARE}
		{onToggleCompare}
	/>
{/snippet}

{#if searching}
	{#if matches.length > 0}
		<div
			class="mt-3 divide-y divide-border rounded-xl border border-border-card bg-surface shadow-card"
			role="table"
			aria-label={`${heading} matching “${query.trim()}”`}
		>
			{#each matches as group (group.productId)}
				{@render row(group)}
			{/each}
		</div>
	{:else}
		<p
			class="mt-3 rounded-lg border border-border bg-surface px-3 py-8 text-center text-sm text-text-muted"
		>
			No {heading} match “{query}”{activeCount > 0 ? ' with these filters' : ''}.
			<button type="button" class="ml-1 text-accent underline" onclick={onClearQuery}>
				Clear
			</button>
		</p>
	{/if}
{:else if shown.length === 0}
	<p
		class="mt-3 rounded-lg border border-border bg-surface px-3 py-8 text-center text-sm text-text-muted"
		data-testid="catalog-empty"
	>
		No products match these filters.
		<a href={clearHref} class="ml-1 text-accent underline">Clear filters</a>
	</p>
{:else}
	<p class="mt-3 text-xs text-text-muted md:hidden">Tick a box to compare up to four.</p>
	<!-- An ARIA table over the flex rows (#23): ProductRow explains why not
	     <table>. The header row is hidden on a phone, where every cell keeps
	     its own sr-only label and the filter panel offers the sort. -->
	<div role="table" aria-label={heading}>
		<div
			role="rowgroup"
			class="sticky top-0 z-10 mt-3 hidden border-b border-border bg-bg md:block"
			data-testid="catalog-header"
		>
			<div
				role="row"
				class="flex items-center gap-x-3 xl:gap-x-2 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted"
			>
				{#each columns as col (col.key)}
					{#if col.sort}
						{@const key = col.sort}
						<span class={COL[col.key]} role="columnheader" aria-sort={ariaSort(key)}>
							<button
								type="button"
								onclick={() => onSort(key)}
								class="inline-flex items-center gap-1 uppercase tracking-wide hover:text-text"
								class:text-text={view.sort === key}
							>
								{col.label}
								<span aria-hidden="true" class="w-2">
									{view.sort === key ? (view.dir === 'asc' ? '↑' : '↓') : ''}
								</span>
							</button>
						</span>
					{:else}
						<span
							class={COL[col.key]}
							role="columnheader">{col.label}</span
						>
					{/if}
				{/each}
			</div>
		</div>
		{#if view.sort}
			<div role="rowgroup" class="divide-y divide-border">
				{#each shown as item (item.productId)}
					{@render row(item)}
				{/each}
			</div>
		{:else}
			{#each groups as group (group.key)}
				{@const inStock = group.items.filter((i) => i.cheapestInStockPrice !== null).length}
				{@const year = earliestYear(group.items)}
				<div role="rowgroup" class="mt-4 first:mt-0">
					<div role="row">
						<div role="cell" aria-colspan={columns.length}>
							<h2
								class="border-b border-border pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-text-muted"
							>
								{group.brand} · {group.label}{year ? ` · ${year}` : ''}
								<span class="normal-case tracking-normal">
									· {group.items.length} {group.items.length === 1 ? 'model' : 'models'} · {inStock} in stock
								</span>
							</h2>
						</div>
					</div>
					<div class="divide-y divide-border">
						{#each group.items as item (item.productId)}
							{@render row(item)}
						{/each}
					</div>
				</div>
			{/each}
		{/if}
	</div>
{/if}
