<script lang="ts">
	import BrandIcon from './BrandIcon.svelte';
	import PriceRangeBar from './PriceRangeBar.svelte';
	import Sparkline from './Sparkline.svelte';
	import { retailerLabel as lookupRetailerLabel } from '$lib/filters';
	import { formatAud, formatMonthYear, formatPct, formatTrend } from '$lib/formats';
	import { COL } from '$lib/catalogColumns';
	import { rangePosition } from '$lib/rangeBar';
	import { METRICS, defaultMetric, sourceNote } from '$lib/perfIndex';
	import { perfPerKilo } from '$lib/value';
	import { avgWindowLabel, deltaPresentation, deltaVsAvg30 } from '$lib/offers';
	import type { FxRate } from '$lib/models';
	import { MSRP_TONE_CLASS, formatMsrpDelta, msrpAud, msrpDelta, msrpTone } from '$lib/msrp';
	import type { CatalogRow } from '$lib/productIndex';

	let {
		group,
		compareSelected = false,
		compareDisabled = false,
		onToggleCompare,
		price = undefined,
		retailer = undefined,
		outOfStock = false,
		fx = null
	}: {
		// neverListed: tracked in the watchlist but no retailer has ever listed
		// it — a different statement from "listed, currently out of stock".
		// The /products loader drops `listings` from each group (#28) — nothing
		// here reads it — so the prop type omits it too, matching what actually
		// arrives. The catalog columns (#23) are optional: search results and
		// older callers may not carry them.
		group: CatalogRow;
		compareSelected?: boolean;
		compareDisabled?: boolean;
		onToggleCompare?: (productId: number) => void;
		// The catalogue's shown price and its retailer (#23): with a retailer
		// filter on, that retailer's price rather than the cheapest anywhere.
		price?: number | null;
		retailer?: string | null;
		// The shown price is an out-of-stock one (a retailer view with in_stock
		// off, final review #1): muted, labelled, and never a deal cue.
		outOfStock?: boolean;
		// The AUD/USD rate for the vs-MSRP column (Task 3); "–" without it.
		fx?: FxRate | null;
	} = $props();

	const shown = $derived(price === undefined ? group.cheapestInStockPrice : price);
	const retailerSlug = $derived(retailer === undefined ? group.cheapestInStockRetailer : retailer);
	const retailerLabel = $derived(retailerSlug ? lookupRetailerLabel(retailerSlug) : null);

	const deltaPct = $derived(outOfStock ? null : deltaVsAvg30(shown, group.avg30 ?? null));
	// Same price the msrp sort ranks by (catalogView.shownPrice). An
	// out-of-stock price is muted: it is never a deal cue.
	const vsMsrp = $derived(msrpDelta(shown, msrpAud(group.msrpUsd ?? null, fx)));
	const vsMsrpClass = $derived(
		vsMsrp === null || outOfStock ? 'text-text-muted' : MSRP_TONE_CLASS[msrpTone(vsMsrp)]
	);
	// The 90-day bar: only with a range and an in-stock shown price (an out-of-stock one is never a deal cue). A flat range has no
	// position, which PriceRangeBar words as "Steady" rather than drawing.
	const range = $derived(group.range90 ?? null);
	const rangePos = $derived(
		range && shown !== null && !outOfStock ? rangePosition(shown, range.low, range.high) : null
	);
	const cpu = $derived(group.category === 'cpu');
	// Performance per A$1,000 at the shown price, so a retailer view compares
	// that retailer (#33). An out-of-stock shown price gets no figure (R7), the
	// same rule the value sort applies.
	const metric = $derived(group.metric ?? defaultMetric(cpu ? 'cpu' : 'gpu'));
	const value = $derived(outOfStock ? null : perfPerKilo(shown, group.perf ?? null));
	const trend = $derived(formatTrend(group.sparkline ?? []));

	const specHeader = $derived(group.category === 'gpu' ? 'VRAM' : 'Cores');
	const specValue = $derived(
		group.category === 'gpu'
			? group.vramGb
				? `${group.vramGb}GB`
				: '—'
			: group.cores
				? String(group.cores)
				: '—'
	);
	// The sr-only labels below are expressions, not literal text: Svelte trims
	// a literal trailing space, and "Released:—" reads badly aloud.
	const released = $derived(group.launchDate ? formatMonthYear(group.launchDate) : '—');
</script>

<!-- One row of the catalogue's ARIA table (#23): the flex layout wraps on a
     phone, which a native <tr> cannot, so the table semantics are explicit.
     Every child is a cell; cells hidden at a breakpoint simply drop out. -->
<div
	class="flex flex-wrap items-center gap-x-3 xl:gap-x-2 gap-y-1 px-3 py-2 hover:bg-surface-hover"
	role="row"
	data-testid="catalog-row"
>
	{#if onToggleCompare}
		<!-- The padded label is the touch target: a bare 13px checkbox is well
		     under the 24px WCAG 2.2 AA minimum and awkward to hit on a phone.
		     Negative margin keeps the row's visual density unchanged. Its title
		     and aria-label say what ticking does (U5). -->
		<span class="-my-2 flex {COL.compare}" role="cell">
			<label
				class="flex items-center p-2"
				class:cursor-pointer={!compareDisabled}
				title="Add to comparison"
			>
				<input
					type="checkbox"
					class="size-4 shrink-0 accent-accent"
					checked={compareSelected}
					disabled={compareDisabled}
					aria-label={`Compare ${group.model}`}
					onchange={() => onToggleCompare?.(group.productId)}
				/>
			</label>
		</span>
	{/if}

	<span class={COL.price} role="cell" data-testid="row-price">
		{#if shown !== null && outOfStock}
			<span class="num text-sm text-text-muted">{formatAud(shown)}</span>
			<span class="block text-[11px] text-text-muted" aria-hidden="true">(out of stock)</span>
			<span class="sr-only">{', out of stock'}</span>
		{:else if shown !== null}
			<span class="num text-sm font-semibold text-text">{formatAud(shown)}</span>
		{:else}
			<span class="text-sm text-text-muted">—</span>
		{/if}
	</span>

	<span class={COL.model} role="cell">
		<a
			href={`/product/${group.productId}`}
			class="block truncate text-sm no-underline hover:underline {group.neverListed
				? 'text-text-muted'
				: 'text-text'}"
			title={group.model}
		>
			{group.model}
		</a>
	</span>

	<span class="{COL.spec} text-xs text-text-muted" role="cell"
		><span class="sr-only">{`${specHeader}: `}</span><span class="num">{specValue}</span></span
	>
	{#if cpu}
		<span class="{COL.socket} text-xs text-text-muted" role="cell"
			><span class="sr-only">{'Socket: '}</span>{group.socket ?? '—'}</span
		>
		<span class="{COL.threads} text-xs text-text-muted" role="cell"
			><span class="sr-only">{'Threads: '}</span><span class="num">{group.threads ?? '—'}</span
			></span
		>
	{/if}
	<span class="{COL.released} text-xs text-text-muted" role="cell"
		><span class="sr-only">{'Released: '}</span>{released}</span
	>
	<span class="{COL.listings} text-xs text-text-muted" role="cell" title="In stock of listed"
		><span class="sr-only">{'Listings: '}</span><span class="num"
			>{group.inStockCount} of {group.listingCount ?? 0}</span
		></span
	>
	<span class="{COL.trend} text-xs" role="cell" data-testid="row-trend">
		<Sparkline values={group.sparkline ?? []} label={trend ? `30-day trend: ${trend}` : undefined} />
	</span>

	<span class="{COL.range} text-xs" role="cell" data-testid="row-range">
		{#if range && shown !== null && !outOfStock}
			<PriceRangeBar
				size="compact"
				low={range.low}
				high={range.high}
				current={shown}
				position={rangePos}
				points={range.days}
			/>
		{/if}
	</span>

	<span class="{COL.value} text-xs text-text-muted" role="cell" data-testid="row-value" title={sourceNote(metric)}
		><span class="sr-only">{`per A$1,000, ${METRICS[metric].label}: `}</span><span class="num font-medium"
			>{value === null ? '–' : Math.round(value)}</span
		></span
	>

	{#if !cpu}
		<span class="{COL.brand} items-center gap-1.5 text-xs text-text-muted" role="cell">
			<BrandIcon brand={group.brand} size={12} />
			{group.brand}
		</span>
	{/if}

	<span class="{COL.delta} text-xs" role="cell" data-testid="row-delta">
		{#if deltaPct !== null}
			{@const d = deltaPresentation(deltaPct)}
			<span class={d.class}
				>{d.arrow}
				{formatPct(deltaPct)}
				{avgWindowLabel(group.avg30Points)}</span
			>
		{:else if group.neverListed}
			<span class="text-text-muted">Not listed</span>
		{:else if shown === null || outOfStock}
			<span class="text-text-muted">No stock</span>
		{:else}
			<span class="text-text-muted">Not enough history</span>
		{/if}
	</span>

	<span class="{COL.msrp} text-xs" role="cell" data-testid="row-msrp"
		><span class="sr-only">{'vs MSRP: '}</span><span class="num font-medium {vsMsrpClass}"
			>{formatMsrpDelta(vsMsrp)}</span
		></span
	>

	<span
		class="{COL.retailer} text-xs text-text-muted"
		role="cell"
		title={retailerLabel ?? undefined}>{retailerLabel ?? ''}</span
	>
</div>
