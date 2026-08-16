<script lang="ts">
	import { classifyChange } from '$lib/change';
	import { formatAud, formatPct, freshnessLabel } from '$lib/formats';
	import PriceChange from './PriceChange.svelte';
	import StockBadge from './StockBadge.svelte';
	import Badge from './Badge.svelte';
	import type { LatestListing } from '$lib/server/repos';
	import type { ChangeDirection } from '$lib/types';

	// compact: hide the Model/Category columns (used inside product cards,
	// where the card header already shows them).
	let { rows, compact = false }: { rows: LatestListing[]; compact?: boolean } = $props();

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
		return name.split(',')[0].trim();
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
						<th class="px-3 py-2 font-medium">Model</th>
						<th class="px-3 py-2 font-medium">Category</th>
					{/if}
					<th class="px-3 py-2 font-medium">Retailer</th>
					<th class="px-3 py-2 font-medium">Variant</th>
					<th class="px-3 py-2 text-right font-medium">Price</th>
					<th class="px-3 py-2 font-medium">Stock</th>
					<th class="px-3 py-2 font-medium">7-day change</th>
					<th class="px-3 py-2 font-medium">Freshness</th>
				</tr>
			</thead>
			<tbody>
{#each rows as row (row.listingId)}
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