<script lang="ts">
	import { untrack } from 'svelte';
	import { afterNavigate, goto, replaceState } from '$app/navigation';
	import ProductRow from '$lib/components/ProductRow.svelte';
	import PageHead from '$lib/components/PageHead.svelte';
	import CatalogFilters from '$lib/components/CatalogFilters.svelte';
	import { groupForIndex, type CatalogRow } from '$lib/productIndex';
	import {
		DEFAULT_DIR,
		activeFilterCount,
		applyCatalogView,
		catalogViewParams,
		earliestYear,
		genOptions,
		parseCatalogView,
		brandOptions,
		shownPrice,
		shownStock,
		type CatalogRowInput,
		type CatalogSort,
		type CatalogView
	} from '$lib/catalogView';
	import { COL, catalogColumns } from '$lib/catalogColumns';
	import { retailerLabel } from '$lib/filters';
	import { searchProducts } from '$lib/productSearch';
	import { MAX_COMPARE, parseCompareIds, withParams } from '$lib/urlState';
	import { urlParams } from '$lib/urlParams';
	import { buildDisplayNames, displayName } from '$lib/displayName';
	import type { Category } from '$lib/types';
	import type { FxRate, ProductIndexEntry } from '$lib/models';

	let {
		data
	}: {
		data: {
			category: Category;
			inStockOnly: boolean;
			trackedCount: number;
			listedCount: number;
			fx: FxRate | null;
			groups: (CatalogRow & CatalogRowInput)[];
			// From the root layout's load (merged into page data).
			productIndex: ProductIndexEntry[];
		};
	} = $props();

	const heading = $derived(data.category === 'cpu' ? 'CPUs' : 'GPUs');

	// The base card carries its VRAM where a "<model> <N>GB" sibling exists
	// (display only). Search and rows both use the display name, so
	// "5060 ti 16gb" finds the base card.
	const names = $derived(buildDisplayNames(data.productIndex));
	const named = $derived(
		data.groups.map((g) => ({ ...g, model: displayName(names, g.productId, g.model) }))
	);

	// Search and compare selection live in the URL (#26): a shared
	// /products?category=gpu&q=5070&compare=1,2 renders as it was sent, and Back
	// from a product page restores it. Read through urlParams(), not page.url
	// (see $lib/urlParams for why).

	let query = $state(urlParams().get('q') ?? '');
	let searchEl: HTMLInputElement | undefined = $state();

	const searching = $derived(query.trim().length > 0);

	let compareIds = $state<Set<number>>(
		new Set(parseCompareIds(urlParams().get('compare')))
	);

	// Never-listed products are hidden from browsing by default (#23); search
	// still covers the whole watchlist (25-Aug decision, U-D16). Read through
	// urlParams() like q/compare, so Back restores it.
	let showUnlisted = $state(urlParams().get('unlisted') === '1');
	const unlistedCount = $derived(named.filter((g) => g.neverListed).length);
	const browseItems = $derived(
		showUnlisted ? named : named.filter((g) => !g.neverListed)
	);

	// Catalogue filters and sort (#23). Parsed from the URL the same way on
	// the server and in the browser, and applied here rather than in the
	// loader, so a shared link renders filtered without JS and hydrates to
	// the identical list. The loader keeps returning the whole category.
	let view = $state<CatalogView>(parseCatalogView(urlParams()));
	const shown = $derived(applyCatalogView(browseItems, view, { fx: data.fx }));
	// Filtering happens here, not on the server: the whole category is already
	// in the browser, so narrowing is instant and there is no debounce. The
	// catalogue view narrows the search results too, but search keeps its own
	// relevance order, so the sort is left out.
	const matches = $derived(applyCatalogView(searchProducts(named, query), { ...view, sort: null }, { fx: data.fx }));
	const activeCount = $derived(activeFilterCount(view));
	// Default order keeps the series groups; any sort flattens them.
	const groups = $derived(searching || view.sort ? [] : groupForIndex(shown));

	// A ticked brand or tier keeps its control even when no row has it (the
	// server's in_stock narrowing can empty it), so a filter is never stuck on.
	const brandsPresent = $derived(brandOptions(data.groups, view.brands));
	const gens = $derived(genOptions(data.groups, view.gens));
	const columns = $derived(
		catalogColumns(data.category, view.retailer ? retailerLabel(view.retailer) : null)
	);

	function sortBy(key: CatalogSort) {
		view =
			view.sort === key
				? { ...view, dir: view.dir === 'asc' ? 'desc' : 'asc' }
				: { ...view, sort: key, dir: DEFAULT_DIR[key] };
	}

	function ariaSort(key: CatalogSort): 'ascending' | 'descending' | 'none' {
		if (view.sort !== key) return 'none';
		return view.dir === 'asc' ? 'ascending' : 'descending';
	}

	// Everything but the filters, so Clear keeps the search, selection and sort.
	const clearHref = $derived(
		`/products${withParams(`?category=${data.category}`, {
			q: query.trim() || null,
			compare: compareIds.size ? [...compareIds].join(',') : null,
			unlisted: showUnlisted ? '1' : null,
			sort: catalogViewParams(view).sort,
			dir: catalogViewParams(view).dir
		})}`
	);
	const formHidden = $derived<Record<string, string>>({
		category: data.category,
		...(query.trim() ? { q: query.trim() } : {}),
		...(showUnlisted ? { unlisted: '1' } : {})
	});

	function toggleCompare(productId: number) {
		const next = new Set(compareIds);
		if (next.has(productId)) next.delete(productId);
		else if (next.size < MAX_COMPARE) next.add(productId);
		compareIds = next;
	}

	const compareUrl = $derived(`/compare?ids=${[...compareIds].join(',')}`);

	// GPUs -> CPUs, the In stock toggle and Back/Forward between two /products
	// entries all reuse this component, so re-read the state from the URL it
	// landed on (a nav link carries none of it, so switching category clears
	// the search and the selection, which /compare would reject as mixed).
	// Only assign what differs, so the sync effect below never fires on a no-op.
	afterNavigate(() => {
		const params = urlParams();
		const q = params.get('q') ?? '';
		if (q !== query) query = q;
		const ids = parseCompareIds(params.get('compare'));
		if (ids.length !== compareIds.size || ids.some((id) => !compareIds.has(id))) {
			compareIds = new Set(ids);
		}
		const unlisted = params.get('unlisted') === '1';
		if (unlisted !== showUnlisted) showUnlisted = unlisted;
		const nextView = parseCatalogView(params);
		if (JSON.stringify(nextView) !== JSON.stringify(view)) view = nextView;
	});

	// Shallow URL sync: replaceState rewrites the address bar without re-running
	// load, so filtering stays client-side (25-Aug decision). It must track only
	// the state: replaceState reads page.url internally, so called tracked it
	// would re-run this effect on every navigation and, on Back, write the
	// entry just left over the one landed on. Hence untrack(). The first run is
	// skipped: the state was just read from this URL, and in dev SvelteKit throws
	// if replaceState runs before its router has started. `location`, not
	// page.url: replaceState updates page.state but not page.url.
	let urlSynced = false;
	$effect(() => {
		const next = withParams(location.search, {
			q: query.trim() || null,
			compare: compareIds.size ? [...compareIds].join(',') : null,
			unlisted: showUnlisted ? '1' : null,
			...catalogViewParams(view)
		});
		if (!urlSynced) {
			urlSynced = true;
			return;
		}
		if (next !== location.search) untrack(() => replaceState(`${location.pathname}${next}`, {}));
	});

	function openTopHit() {
		if (matches.length > 0) goto(`/product/${matches[0].productId}`);
	}

	function onSearchKey(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			event.preventDefault();
			openTopHit();
		} else if (event.key === 'Escape') {
			query = '';
		}
	}

	// "/" jumps to search from anywhere on the page — but never while the user
	// is already typing somewhere, or it would swallow the character.
	function onWindowKey(event: KeyboardEvent) {
		if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
		const target = event.target as HTMLElement | null;
		const tag = target?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;
		event.preventDefault();
		searchEl?.focus();
	}

	function setInStock(checked: boolean) {
		// From `location`: page.url does not see replaceState's q/compare.
		goto(`/products${withParams(location.search, { in_stock: checked ? '1' : null })}`, {
			keepFocus: true,
			noScroll: true,
			// Like every other filter: no history entry per toggle.
			replaceState: true
		});
	}
</script>

<svelte:window onkeydown={onWindowKey} />

<PageHead
	title={heading}
	description={`Every tracked ${heading === 'CPUs' ? 'CPU' : 'GPU'} with today's cheapest AU price.`}
/>

<div>
	<div class="flex flex-wrap items-baseline justify-between gap-2">
		<h1 class="text-xl font-semibold text-text">{heading}</h1>
		<p class="text-xs text-text-muted">
			<span class="num">{data.trackedCount}</span> tracked
			{#if data.inStockOnly}
				· <span class="num">{data.groups.length}</span> in stock
			{:else}
				· <span class="num">{data.listedCount}</span> seen at a retailer
			{/if}
		</p>
	</div>

	<div class="mt-3 flex flex-wrap items-center gap-3">
		<div class="min-w-0 flex-1 basis-64">
			<label for="product-search" class="sr-only">Search {heading}</label>
			<input
				id="product-search"
				bind:this={searchEl}
				bind:value={query}
				onkeydown={onSearchKey}
				type="search"
				autocomplete="off"
				placeholder={`Search ${named.length} ${heading}…  (press / )`}
				class="h-9 w-full rounded-md border border-border-input bg-surface px-3 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
		</div>
		{#if unlistedCount > 0 && !data.inStockOnly}
			<button
				type="button"
				aria-pressed={showUnlisted}
				onclick={() => (showUnlisted = !showUnlisted)}
				class="h-9 shrink-0 rounded-md border border-border bg-surface px-2.5 text-sm text-text-muted hover:text-text"
			>
				{showUnlisted ? 'Hide' : 'Show'} {unlistedCount} not currently sold
			</button>
		{/if}
		<CatalogFilters
			{view}
			category={data.category}
			brands={brandsPresent}
			{gens}
			resultCount={searching ? matches.length : shown.length}
			{activeCount}
			{clearHref}
			hidden={formHidden}
			onChange={(next) => (view = next)}
			onInStock={setInStock}
		/>
	</div>

	<p class="mt-2 text-xs text-text-muted" aria-live="polite" data-testid="index-count">
		{#if searching}
			<span class="num">{matches.length}</span> of
			<span class="num">{data.groups.length}</span> match
		{:else if activeCount > 0}
			<span class="num">{shown.length}</span> of
			<span class="num">{browseItems.length}</span> match these filters
		{:else}
			Type to narrow, or press Enter to open the top match
		{/if}
	</p>

	{#if searching}
		{#if matches.length > 0}
			<div
				class="mt-3 divide-y divide-border rounded-lg border border-border bg-surface"
				role="table"
				aria-label={`${heading} matching “${query.trim()}”`}
			>
				{#each matches as group (group.productId)}
					<ProductRow
						{group}
						price={shownPrice(group, view)}
						retailer={view.retailer ?? undefined}
						outOfStock={shownStock(group, view) === 'out'}
						fx={data.fx}
						compareSelected={compareIds.has(group.productId)}
						compareDisabled={!compareIds.has(group.productId) && compareIds.size >= MAX_COMPARE}
						onToggleCompare={toggleCompare}
					/>
				{/each}
			</div>
		{:else}
			<p
				class="mt-3 rounded-lg border border-border bg-surface px-3 py-8 text-center text-sm text-text-muted"
			>
				No {heading} match “{query}”{activeCount > 0 ? ' with these filters' : ''}.
				<button type="button" class="ml-1 text-accent underline" onclick={() => (query = '')}>
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
					class="flex items-center gap-x-3 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted"
				>
					{#each columns as col (col.key)}
						{#if col.sort}
							{@const key = col.sort}
							<span class={COL[col.key]} role="columnheader" aria-sort={ariaSort(key)}>
								<button
									type="button"
									onclick={() => sortBy(key)}
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
						<ProductRow
							group={item}
							price={shownPrice(item, view)}
							retailer={view.retailer ?? undefined}
							outOfStock={shownStock(item, view) === 'out'}
							fx={data.fx}
							compareSelected={compareIds.has(item.productId)}
							compareDisabled={!compareIds.has(item.productId) && compareIds.size >= MAX_COMPARE}
							onToggleCompare={toggleCompare}
						/>
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
								<ProductRow
									group={item}
									price={shownPrice(item, view)}
									retailer={view.retailer ?? undefined}
									outOfStock={shownStock(item, view) === 'out'}
							fx={data.fx}
									compareSelected={compareIds.has(item.productId)}
									compareDisabled={!compareIds.has(item.productId) && compareIds.size >= MAX_COMPARE}
									onToggleCompare={toggleCompare}
								/>
							{/each}
						</div>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>

{#if compareIds.size >= 1}
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
				class="text-sm text-text-muted hover:text-text"
			>
				Clear
			</button>
			{#if compareIds.size === 1}
				<span class="text-sm text-text-muted">Pick 1 more to compare</span>
			{:else}
				<a href={compareUrl} class="text-sm font-medium text-accent no-underline hover:underline">
					Compare ({compareIds.size}) →
				</a>
			{/if}
		</div>
	</div>
{/if}
