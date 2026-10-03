<script lang="ts">
	import MoverRow from './MoverRow.svelte';
	import OfferRow from './OfferRow.svelte';
	import { dealToOffer, type Deal } from '$lib/deals';
	import { formatAud } from '$lib/formats';
	import type { MoverRowData } from '$lib/movers';

	let {
		title,
		href,
		trackedCount,
		availableCount,
		cheapestPrice,
		deals,
		drops,
		rises
	}: {
		title: string;
		href: string;
		trackedCount: number;
		availableCount: number;
		cheapestPrice: number | null;
		deals: Deal[];
		drops: MoverRowData[];
		rises: MoverRowData[];
	} = $props();

	// #22: a column with no rows is not drawn as a blank panel. Its one-line
	// note goes under the grid, and the columns that have rows share the width.
	const empty = $derived(
		[
			deals.length === 0 && 'Nothing below its recent average today.',
			drops.length === 0 && 'No big price drops this week.',
			rises.length === 0 && 'No big price rises this week.'
		].filter((s): s is string => Boolean(s))
	);
	const shown = $derived(3 - empty.length);
	const GRID_COLS = ['', '', 'md:grid-cols-2', 'md:grid-cols-3'];
</script>

{#snippet heading(label: string)}
	<h3 class="text-section px-3 pb-1 pt-3">{label}</h3>
{/snippet}

<section class="overflow-hidden rounded-xl border border-border-card bg-surface shadow-card" aria-label={title}>
	<header
		class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-3 py-3"
	>
		<h2 class="text-title text-text">{title}</h2>
		<p class="text-meta text-text-muted">
			<span class="num">{availableCount}</span> of
			<span class="num">{trackedCount}</span> tracked
			{#if cheapestPrice !== null}
				· cheapest <span class="num font-medium text-text">{formatAud(cheapestPrice)}</span>
			{/if}
			· <a {href} class="text-accent underline">All {title} →</a>
		</p>
	</header>

	<!-- min-w-0 on each column: the mover rows truncate, and `truncate` implies
	     `white-space: nowrap`, so a grid item's automatic minimum (min-content)
	     becomes the full untruncated string and blows the track out past the
	     viewport on a phone. -->
	{#if shown > 0}
		<div class="grid gap-px bg-border {GRID_COLS[shown]}">
			{#if deals.length > 0}
				<div class="min-w-0 bg-surface" data-testid="top-deals">
					{@render heading('Top deals')}
					<div class="divide-y divide-border">
						{#each deals as deal (deal.productId)}
							<OfferRow
								offer={dealToOffer(deal)}
								avg30={deal.avg30}
								avgPoints={deal.avg30Points}
								titleOverride={deal.model}
								detailHref={`/product/${deal.productId}`}
							/>
						{/each}
					</div>
				</div>
			{/if}

			{#if drops.length > 0}
				<div class="min-w-0 bg-surface" data-testid="biggest-drops">
					{@render heading('Biggest drops (7d)')}
					<div class="divide-y divide-border">
						{#each drops as m (m.productId)}
							<MoverRow mover={m} />
						{/each}
					</div>
				</div>
			{/if}

			{#if rises.length > 0}
				<div class="min-w-0 bg-surface" data-testid="biggest-rises">
					{@render heading('Biggest rises (7d)')}
					<div class="divide-y divide-border">
						{#each rises as m (m.productId)}
							<MoverRow mover={m} />
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	{#if empty.length > 0}
		<div class="flex flex-wrap gap-2 px-3 py-3 {shown > 0 ? 'border-t border-border' : ''}">
			{#each empty as line (line)}
				<p class="text-meta text-text-muted">
					{line}
				</p>
			{/each}
		</div>
	{/if}
</section>
