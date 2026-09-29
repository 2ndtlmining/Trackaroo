<script lang="ts">
	import { browser } from '$app/environment';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import ProductRow from '$lib/components/ProductRow.svelte';
	import PageHead from '$lib/components/PageHead.svelte';
	import { groupForIndex } from '$lib/productIndex';
	import { searchProducts } from '$lib/productSearch';
	import { MAX_COMPARE, parseCompareIds, withParams } from '$lib/urlState';
	import type { ProductGroup } from '$lib/server/repos';
	import type { Category } from '$lib/types';

	let {
		data
	}: {
		data: {
			category: Category;
			inStockOnly: boolean;
			trackedCount: number;
			listedCount: number;
			groups: (Omit<ProductGroup, 'listings'> & { neverListed?: boolean })[];
		};
	} = $props();

	const heading = $derived(data.category === 'cpu' ? 'CPUs' : 'GPUs');

	// Search and compare selection live in the URL (#26): a shared
	// /products?category=gpu&q=5070&compare=1,2 renders as it was sent, and Back
	// from a product page restores it.
	// In the browser the address bar is the truth, not page.url: replaceState
	// (below) leaves page.url alone, and SvelteKit's popstate navigates Back to
	// the URL the page was *loaded* with, dropping the shallow q/compare. By the
	// time this component mounts or its effects re-run, `location` already holds
	// the target URL (SvelteKit pushes history before it renders).
	function urlParams(): URLSearchParams {
		return browser ? new URLSearchParams(location.search) : page.url.searchParams;
	}

	let query = $state(urlParams().get('q') ?? '');
	let searchEl: HTMLInputElement | undefined = $state();

	// Filtering happens here, not on the server: the whole category is already
	// in the browser, so narrowing is instant and there is no debounce.
	const matches = $derived(searchProducts(data.groups, query));
	const searching = $derived(query.trim().length > 0);
	const groups = $derived(searching ? [] : groupForIndex(data.groups));

	let compareIds = $state<Set<number>>(
		new Set(parseCompareIds(urlParams().get('compare')))
	);

	function toggleCompare(productId: number) {
		const next = new Set(compareIds);
		if (next.has(productId)) next.delete(productId);
		else if (next.size < MAX_COMPARE) next.add(productId);
		compareIds = next;
	}

	const compareUrl = $derived(`/compare?ids=${[...compareIds].join(',')}`);

	// GPUs -> CPUs is the same route with a different query, so this component
	// is reused and would carry the GPU search and selection across (and /compare
	// rejects a mixed-category comparison). Re-read both from the new URL instead
	// (a nav link carries neither, so both clear).
	let lastCategory: Category | undefined;
	$effect(() => {
		const current = data.category;
		// undefined on the first run: the state was just read from this URL.
		if (lastCategory !== undefined && current !== lastCategory) {
			const params = urlParams();
			query = params.get('q') ?? '';
			compareIds = new Set(parseCompareIds(params.get('compare')));
		}
		lastCategory = current;
	});

	// Shallow URL sync: replaceState rewrites the address bar without re-running
	// load, so filtering stays client-side (25-Aug decision). The first run is
	// skipped: the state was just read from this URL, and in dev SvelteKit throws
	// if replaceState runs before its router has started. `location`, not
	// page.url: replaceState updates page.state but not page.url.
	let urlSynced = false;
	$effect(() => {
		const next = withParams(location.search, {
			q: query.trim() || null,
			compare: compareIds.size ? [...compareIds].join(',') : null
		});
		if (!urlSynced) {
			urlSynced = true;
			return;
		}
		if (next !== location.search) replaceState(`${location.pathname}${next}`, {});
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
			noScroll: true
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
				placeholder={`Search ${data.groups.length} ${heading}…  (press / )`}
				class="h-9 w-full rounded-md border border-border-input bg-surface px-3 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
		</div>
		<label
			class="flex h-9 shrink-0 cursor-pointer select-none items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-sm text-text"
		>
			<input
				type="checkbox"
				class="accent-accent"
				checked={data.inStockOnly}
				onchange={(e) => setInStock((e.target as HTMLInputElement).checked)}
			/>
			In stock
		</label>
	</div>

	<p class="mt-2 text-xs text-text-muted" aria-live="polite" data-testid="index-count">
		{#if searching}
			<span class="num">{matches.length}</span> of
			<span class="num">{data.groups.length}</span> match
		{:else}
			Type to narrow, or press Enter to open the top match
		{/if}
	</p>

	{#if searching}
		{#if matches.length > 0}
			<div class="mt-3 divide-y divide-border rounded-lg border border-border bg-surface">
				{#each matches as group (group.productId)}
					<ProductRow
						{group}
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
				No {heading} match “{query}”.
				<button type="button" class="ml-1 text-accent underline" onclick={() => (query = '')}>
					Clear
				</button>
			</p>
		{/if}
	{:else}
		<div class="mt-3 space-y-4">
			{#each groups as group (group.key)}
				<section>
					<h2
						class="border-b border-border pb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted"
					>
						{group.brand} · {group.label}
					</h2>
					<div class="divide-y divide-border">
						{#each group.items as item (item.productId)}
							<ProductRow
								group={item}
								compareSelected={compareIds.has(item.productId)}
								compareDisabled={!compareIds.has(item.productId) && compareIds.size >= MAX_COMPARE}
								onToggleCompare={toggleCompare}
							/>
						{/each}
					</div>
				</section>
			{/each}
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
