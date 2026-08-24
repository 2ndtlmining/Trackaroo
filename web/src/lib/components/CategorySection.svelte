<script lang="ts">
	import MoverRow from './MoverRow.svelte';
	import OfferRow from './OfferRow.svelte';
	import { dealToOffer, type Deal } from '$lib/deals';
	import { formatAud } from '$lib/formats';
	import type { Mover } from '$lib/server/repos';

	let {
		title,
		href,
		trackedCount,
		cheapestPrice,
		deals,
		drops,
		rises
	}: {
		title: string;
		href: string;
		trackedCount: number;
		cheapestPrice: number | null;
		deals: Deal[];
		drops: Mover[];
		rises: Mover[];
	} = $props();
</script>

<section class="rounded-lg border border-border bg-surface" aria-label={title}>
	<header
		class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-3 py-2.5"
	>
		<h2 class="text-sm font-semibold text-text">{title}</h2>
		<p class="text-xs text-text-muted">
			<span class="num">{trackedCount}</span> tracked
			{#if cheapestPrice !== null}
				· cheapest <span class="num">{formatAud(cheapestPrice)}</span>
			{/if}
			· <a {href} class="text-accent no-underline hover:underline">All {title} →</a>
		</p>
	</header>

	<div class="grid gap-px bg-border md:grid-cols-3">
		<div class="bg-surface" data-testid="top-deals">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Top deals</h3>
			{#if deals.length > 0}
				<div class="divide-y divide-border">
					{#each deals as deal (deal.productId)}
						<OfferRow
							offer={dealToOffer(deal)}
							avg30={deal.avg30}
							titleOverride={deal.model}
							detailHref={`/product/${deal.productId}`}
						/>
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">Nothing below its 30-day average today.</p>
			{/if}
		</div>

		<div class="bg-surface" data-testid="biggest-drops">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Biggest drops (7d)</h3>
			{#if drops.length > 0}
				<div class="divide-y divide-border">
					{#each drops as m (m.listingId)}
						<MoverRow mover={m} />
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">
					No significant price moves in the last 7 days.
				</p>
			{/if}
		</div>

		<div class="bg-surface" data-testid="biggest-rises">
			<h3 class="px-3 pt-2.5 text-xs font-medium text-text-muted">Biggest rises (7d)</h3>
			{#if rises.length > 0}
				<div class="divide-y divide-border">
					{#each rises as m (m.listingId)}
						<MoverRow mover={m} />
					{/each}
				</div>
			{:else}
				<p class="px-3 py-4 text-xs text-text-muted">
					No significant price moves in the last 7 days.
				</p>
			{/if}
		</div>
	</div>
</section>
