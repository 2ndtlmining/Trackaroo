<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Badge from './Badge.svelte';
	import { formatAud, formatRelative } from '$lib/formats';
	import type { OzbDeal } from '$lib/models';

	let {
		live,
		expired,
		best,
		now
	}: {
		live: OzbDeal[];
		expired: OzbDeal[];
		// Today's best in-stock price by the alert's rule (R1/R7); null = no best,
		// so no row can claim to beat it.
		best: number | null;
		// ISO instant from the server, so the "3h ago" text cannot differ between
		// the server render and hydration.
		now: string;
	} = $props();

	let showExpired = $state(false);
	const at = $derived(new Date(now));
	const belowBest = (d: OzbDeal) => !d.expired && best !== null && d.priceAud !== null && d.priceAud < best;
</script>

{#snippet row(deal: OzbDeal)}
	{@const below = belowBest(deal)}
	<li
		class="flex flex-wrap items-center gap-x-3 gap-y-1 border-l-2 py-2.5 pl-2.5 pr-3 {below
			? 'border-success'
			: 'border-transparent'}"
		data-testid="ozb-row"
	>
		<div class="w-24 shrink-0">
			{#if deal.priceAud !== null}
				<span class="num text-base font-semibold {deal.expired ? 'text-text-muted' : 'text-text'}"
					>{formatAud(deal.priceAud)}</span
				>
			{:else}
				<span class="text-xs text-text-muted">Price in post</span>
			{/if}
		</div>

		<div class="min-w-0 flex-1 basis-full sm:basis-auto">
			<span
				class="block truncate text-sm {deal.expired ? 'text-text-muted' : 'font-medium text-text'}"
				title={deal.title}>{deal.title}</span
			>
			<span class="flex flex-wrap items-center gap-x-3 text-xs text-text-muted">
				{#if deal.retailer}<span>{deal.retailer}</span>{/if}
				<span class="num">+{deal.votesPos} / −{deal.votesNeg}<span class="sr-only"> votes</span></span>
				{#if deal.postedAt}
					<span>Posted {formatRelative(deal.postedAt, at)}</span>
				{/if}
			</span>
		</div>

		{#if below}
			<Badge tone="success" label="Below our best" />
		{:else if deal.expired}
			<Badge tone="stale" label="Expired" />
		{/if}

		<a
			href={deal.url}
			target="_blank"
			rel="noopener noreferrer"
			aria-label="View deal on OzBargain: {deal.title} (opens in a new tab)"
			class="inline-flex shrink-0 items-center gap-0.5 text-xs text-accent"
		>
			View deal
			<ArrowUpRight size={12} aria-hidden="true" />
		</a>
	</li>
{/snippet}

{#if live.length > 0 || expired.length > 0}
	<section class="rounded-md border border-border bg-surface p-4" aria-labelledby="ozb-heading">
		<h2 id="ozb-heading" class="text-sm font-semibold text-text">OzBargain deals</h2>
		<p class="mt-0.5 text-xs text-text-muted">
			Community-posted deals from OzBargain, checked every 2 hours. Prices are as posted.
		</p>

		{#if live.length > 0}
			<ul class="mt-3 divide-y divide-border overflow-hidden rounded-md border border-border" aria-label="Live deals">
				{#each live as deal (deal.nodeId)}
					{@render row(deal)}
				{/each}
			</ul>
		{:else}
			<p class="mt-3 text-sm text-text-muted">No live deals right now.</p>
		{/if}

		{#if expired.length > 0}
			<button
				type="button"
				class="mt-3 inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs text-text-muted hover:text-text"
				aria-expanded={showExpired}
				aria-controls="ozb-expired"
				onclick={() => (showExpired = !showExpired)}
			>
				<ChevronDown
					size={14}
					aria-hidden="true"
					class="transition-transform motion-reduce:transition-none {showExpired ? 'rotate-180' : ''}"
				/>
				{showExpired ? 'Hide' : 'Show'} expired ({expired.length})
			</button>
			<ul
				id="ozb-expired"
				class="mt-1 divide-y divide-border overflow-hidden rounded-md border border-border"
				aria-label="Expired deals"
				hidden={!showExpired}
			>
				{#if showExpired}
					{#each expired as deal (deal.nodeId)}
						{@render row(deal)}
					{/each}
				{/if}
			</ul>
		{/if}
	</section>
{/if}
