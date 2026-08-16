<script lang="ts">
	import { formatAud, formatDate } from '$lib/formats';
	import StockBadge from './StockBadge.svelte';
	import { buildBrandGroups, toListingDisplays, type ListingDisplay } from '$lib/listingsPanel';
	import type { Series } from '$lib/server/repos';

	let {
		series,
		productBrand,
		selected,
		onToggleListing
	}: {
		series: Series[];
		productBrand: string;
		selected: ReadonlySet<number>;
		onToggleListing: (listingId: number) => void;
	} = $props();

	let query = $state('');
	let inStockOnly = $state(false);
	let expanded = $state<Set<string>>(new Set());

	const allExpanded = $derived.by(() => {
		const groups = buildBrandGroups(series, productBrand, { query, inStockOnly }, selected);
		return groups.length > 0 && groups.every((g) => expanded.has(g.brand));
	});

	const groups = $derived(
		buildBrandGroups(series, productBrand, { query, inStockOnly }, selected)
	);

	function toggleBrand(brand: string) {
		const next = new Set(expanded);
		if (next.has(brand)) next.delete(brand);
		else next.add(brand);
		expanded = next;
	}

	function toggleAll() {
		const next = allExpanded ? new Set<string>() : new Set(groups.map((g) => g.brand));
		expanded = next;
	}

	function groupHeader(group: (typeof groups)[number]): string {
		const parts: string[] = [group.brand];
		if (group.minPrice !== null && group.maxPrice !== null) {
			parts.push(
				group.minPrice === group.maxPrice
					? formatAud(group.minPrice)
					: `${formatAud(group.minPrice)}–${formatAud(group.maxPrice)}`
			);
		}
		if (group.inStockCount > 0) {
			const n = group.listings.length;
			parts.push(`${n} ${n === 1 ? 'listing' : 'listings'} · ${group.inStockCount} in stock`);
		} else {
			const n = group.listings.length;
			parts.push(`${n} ${n === 1 ? 'listing' : 'listings'}`);
		}
		return parts.join(' · ');
	}

	function dateRange(listing: ListingDisplay): string {
		if (listing.firstSeen && listing.lastSeen) {
			return `${formatDate(listing.firstSeen)} – ${formatDate(listing.lastSeen)}`;
		}
		return 'No history';
	}
</script>

<div class="overflow-hidden rounded-md border border-border">
	<div class="border-b border-border bg-surface px-3 py-2">
		<div class="flex items-center justify-between gap-2">
			<h2 class="text-xs font-semibold uppercase tracking-wide text-text-muted">
				Retailer listings
			</h2>
			{#if groups.length > 1}
				<button
					type="button"
					onclick={toggleAll}
					class="text-xs text-accent hover:underline"
				>
					{allExpanded ? 'Collapse all' : 'Expand all'}
				</button>
			{/if}
		</div>
		<div class="mt-2 flex flex-wrap items-center gap-2">
			<input
				type="search"
				aria-label="Filter listings by name"
				placeholder="Filter by name…"
				bind:value={query}
				class="w-full min-w-0 flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
			<label class="flex items-center gap-1.5 text-xs text-text-muted">
				<input
					type="checkbox"
					aria-label="In stock only"
					bind:checked={inStockOnly}
					class="accent-accent"
				/>
				In stock only
			</label>
		</div>
	</div>

	{#if groups.length === 0}
		<div class="bg-surface px-4 py-6 text-center text-sm text-text-muted">
			No listings match the current filters.
		</div>
	{:else}
		<div class="divide-y divide-border">
			{#each groups as group (group.brand)}
				<div>
					<button
						type="button"
						aria-expanded={expanded.has(group.brand)}
						onclick={() => toggleBrand(group.brand)}
						class="flex w-full items-center justify-between gap-2 bg-surface px-3 py-2.5 text-left hover:bg-surface-hover"
					>
						<span class="min-w-0">
							<span class="text-sm font-medium text-text">{groupHeader(group)}</span>
						</span>
						<span aria-hidden="true" class="text-xs text-text-muted">
							{expanded.has(group.brand) ? '▴' : '▾'}
						</span>
					</button>
					{#if expanded.has(group.brand)}
						<ul class="divide-y divide-border border-t border-border">
							{#each group.listings as listing (listing.listingId)}
								<li class="flex items-center justify-between gap-3 px-3 py-2.5">
									<a
										href={listing.listingUrl}
										target="_blank"
										rel="noopener noreferrer"
										class="min-w-0 flex-1"
									>
										<span class="block truncate font-medium text-text" title={listing.variantName ?? undefined}>
											{listing.variantName ?? `${listing.retailer} listing`}
										</span>
										<span class="text-xs text-text-muted">{dateRange(listing)}</span>
									</a>
									<div class="shrink-0 text-right">
										{#if listing.latestPrice !== null}
											<span class="num block text-text">{formatAud(listing.latestPrice)}</span>
											<span class="inline-block"><StockBadge stock={listing.latestStock} /></span>
										{:else}
											<span class="text-xs text-text-muted">—</span>
										{/if}
									</div>
									<button
										type="button"
										aria-pressed={listing.selected}
										onclick={() => onToggleListing(listing.listingId)}
										class="shrink-0 rounded-md border border-border px-2 py-1 text-xs {listing.selected
											? 'border-accent bg-accent/10 font-medium text-accent'
											: 'bg-surface text-text-muted hover:text-text'}"
									>
										{listing.selected ? 'On chart' : 'Show on chart'}
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>