<script lang="ts">
	import { RETAILER_OPTIONS } from '$lib/filters';
	import { formatAud, formatPct } from '$lib/formats';
	import { deltaPresentation } from '$lib/offers';
	import type { Mover } from '$lib/server/repos';

	let { mover }: { mover: Mover } = $props();

	const retailerLabel = $derived(
		RETAILER_OPTIONS.find((o) => o.value === mover.retailer)?.label ?? mover.retailer
	);
	// Same three-way treatment as the offer row: a rise is red, a drop green,
	// and exactly zero is neither.
	const presentation = $derived(
		mover.pctChange === null ? null : deltaPresentation(mover.pctChange)
	);
</script>

<div class="flex items-center gap-2 px-3 py-2">
	<span class="num w-20 shrink-0 text-sm font-semibold text-text">{formatAud(mover.newPrice)}</span>
	<div class="min-w-0 flex-1">
		<a
			href={`/product/${mover.productId}`}
			class="block truncate text-sm text-text no-underline hover:underline"
			title={mover.model}>{mover.model}</a
		>
		<span class="text-xs text-text-muted">{retailerLabel}</span>
	</div>
	{#if presentation && mover.pctChange !== null}
		<span class="shrink-0 text-xs {presentation.class}">
			{presentation.arrow}
			{formatPct(mover.pctChange)}
		</span>
	{:else}
		<span class="shrink-0 text-xs text-text-muted">—</span>
	{/if}
</div>
