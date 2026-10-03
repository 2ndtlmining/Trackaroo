<script lang="ts">
	import { retailerLabel as lookupRetailerLabel } from '$lib/filters';
	import { formatAud, formatPct, titleCase } from '$lib/formats';
	import { deltaPresentation } from '$lib/offers';
	import type { MoverRowData } from '$lib/movers';

	let { mover }: { mover: MoverRowData } = $props();

	const retailerLabel = $derived(lookupRetailerLabel(mover.retailer));
	// Which SKU: on the homepage, the listing where today's cheapest price is
	// (D7). Same first-clause treatment the /movers Variant column uses.
	const variantLabel = $derived(titleCase(mover.variantName).split(',')[0].trim());
	const subtitle = $derived(variantLabel ? `${retailerLabel} · ${variantLabel}` : retailerLabel);
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
		<span class="block truncate text-xs text-text-muted" title={subtitle}>{subtitle}</span>
	</div>
	{#if presentation && mover.pctChange !== null}
		<span class="num shrink-0 text-xs {presentation.class}">
			{presentation.arrow}
			{formatPct(mover.pctChange)}
		</span>
	{:else}
		<span class="shrink-0 text-xs text-text-muted">—</span>
	{/if}
</div>
