<script lang="ts">
	import { classifyChange } from '$lib/change';
	import { formatAud, formatPct, freshnessLabel, titleCase } from '$lib/formats';
	import PriceChange from './PriceChange.svelte';
	import StockBadge from './StockBadge.svelte';
	import Badge from './Badge.svelte';
	import Sparkline from './Sparkline.svelte';
	import type { LatestListing } from '$lib/server/repos';
	import type { ChangeDirection } from '$lib/types';
	import { nextSortDir, sortRows, type SortDir } from '$lib/tableSort';

	// compact: hide the Model/Category columns (used inside product cards,
	// where the card header already shows them).
	let { rows, compact = false }: { rows: LatestListing[]; compact?: boolean } = $props();

	const hasTrend = $derived(rows.some((row) => (row.sparkline?.length ?? 0) >= 2));

	// Tri-state column header sorting (dashboard view only; the compact card
	// table stays static).
	let sortKey = $state<string | null>(null);
	let sortDir = $state<SortDir>(null);
	const sortable = $derived(!compact);

	function onHeader(key: string) {
		if (!sortable) return;
		if (sortKey === key) {
			sortDir = nextSortDir(sortDir);
		} else {
			sortKey = key;
			sortDir = 'asc';
		}
	}

	function arrow(key: string): string {
		if (sortKey !== key || sortDir === null) return '';
		return sortDir === 'asc' ? ' ▲' : ' ▼';
	}

	function changePct(row: LatestListing): number | null {
		if (row.windowStartPrice === null || row.windowStartPrice === 0) return null;
		return ((row.latestPrice - row.windowStartPrice) / row.windowStartPrice) * 100;
	}

	function columnValue(row: LatestListing, key: string): string | number | null {
		if (key === 'model') return row.model;
		if (key === 'price') return row.latestPrice;
		if (key === 'change') return changePct(row);
		if (key === 'freshness') return row.lastSnapshotAt;
		return null;
	}

	const visibleRows = $derived(
		sortable && sortKey !== null && sortDir !== null
			? sortRows(rows, sortDir, (row) => columnValue(row, sortKey!))
			: rows
	);

	function changeInfo(row: LatestListing): { direction: ChangeDirection; label: string } {
		const direction = classifyChange({
			latestPrice: row.latestPrice,
			windowStartPrice: row.windowStartPrice,
			pointsInWindow: row.pointsInWindow,
			lastSnapshotAt: row.lastSnapshotAt
		});
		if (direction === 'up' || direction === 'down') {
			if (row.windowStartPrice !== null) {
				const pct = ((row.latestPrice - row.windowStartPrice) / row.windowStartPrice) * 100;
				return { direction, label: formatPct(pct) };
			}
		}
		if (direction === 'insufficient') {
			const label = row.pointsInWindow === 0 ? 'No data in window' : 'New listing';
			return { direction, label };
		}
		if (direction === 'flat') return { direction, label: formatPct(0) };
		return { direction, label: 'Stale' };
	}

	function isStale(row: LatestListing): boolean {
		return changeInfo(row).direction === 'stale';
	}

	function freshness(row: LatestListing): string {
		const label = freshnessLabel(row.lastSnapshotAt);
		return isStale(row) ? `last seen ${label}` : label;
	}

	function truncatedVariant(name: string | null): string {
		if (!name) return '—';
		return titleCase(name.split(',')[0].trim());
	}
</script>

{#if rows.length === 0}
	<div
		class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
	>
		No listings match the current filters.
	</div>
{:else}
	<div class="overflow-x-auto rounded-md border border-border">
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs text-text-muted">
					{#if !compact}
						<th class="px-3 py-2 font-medium">
							{#if sortable}
								<button
									type="button"
									onclick={() => onHeader('model')}
									class="font-medium text-text-muted hover:text-text"
								>Model{arrow('model')}</button>
							{:else}
								Model
							{/if}
						</th>
						<th class="px-3 py-2 font-medium">Category</th>
					{/if}
					<th class="px-3 py-2 font-medium">Retailer</th>
					<th class="px-3 py-2 font-medium">Variant</th>
					<th class="px-3 py-2 text-right font-medium">
						{#if sortable}
							<button
								type="button"
								onclick={() => onHeader('price')}
								class="font-medium text-text-muted hover:text-text"
							>Price{arrow('price')}</button>
						{:else}
							Price
						{/if}
					</th>
					{#if hasTrend}
						<th class="w-16 px-3 py-2 font-medium">Trend</th>
					{/if}
					<th class="px-3 py-2 font-medium">Stock</th>
					<th class="px-3 py-2 font-medium">
						{#if sortable}
							<button
								type="button"
								onclick={() => onHeader('change')}
								class="font-medium text-text-muted hover:text-text"
							>7-day change{arrow('change')}</button>
						{:else}
							7-day change
						{/if}
					</th>
					<th class="px-3 py-2 font-medium">
						{#if sortable}
							<button
								type="button"
								onclick={() => onHeader('freshness')}
								class="font-medium text-text-muted hover:text-text"
							>Freshness{arrow('freshness')}</button>
						{:else}
							Freshness
						{/if}
					</th>
				</tr>
			</thead>
			<tbody>
{#each visibleRows as row (row.listingId)}
						<tr
							class="border-b border-border last:border-b-0 {isStale(row) ? '' : 'hover:bg-surface-hover'}"
						>
							{#if !compact}
								<td class="px-3 py-2">
									<a
										href="/product/{row.productId}"
										class="no-underline hover:no-underline"
									>{row.model}<span class="ml-1 text-xs text-text-muted">{row.brand}</span></a
									>
								</td>
								<td class="px-3 py-2">
									<Badge tone="neutral" label={row.category.toUpperCase()} />
								</td>
							{/if}
							<td class="px-3 py-2 text-text">{row.retailer}</td>
							<td class="px-3 py-2 text-text-muted" title={row.variantName ?? undefined}>
								{truncatedVariant(row.variantName)}
							</td>
							<td
								class="num px-3 py-2 text-right {isStale(row) ? 'text-text-muted' : 'text-text'}"
							>
								{formatAud(row.latestPrice)}
							</td>
							{#if hasTrend}
								<td class="w-16 px-3 py-2">
									<Sparkline points={row.sparkline} />
								</td>
							{/if}
							<td class="px-3 py-2"><StockBadge stock={row.latestStock} /></td>
							<td class="px-3 py-2">
								<PriceChange
									direction={changeInfo(row).direction}
									label={changeInfo(row).label}
								/>
							</td>
							<td class="num px-3 py-2 text-text-muted">
								{freshness(row)}
							</td>
						</tr>
					{/each}
			</tbody>
		</table>
	</div>
{/if}