<script lang="ts">
	import { formatAud, formatDate, formatShortDate } from '$lib/formats';
	import type { SaleEvent } from '$lib/saleEvents';
	import { axisStartsAtZero } from '$lib/chartExtras';

	let {
		hasBand,
		lowMarker,
		avg30,
		todayPrice,
		saleEvents,
		hasListings,
		yMin
	}: {
		hasBand: boolean;
		lowMarker: number | null;
		avg30: number | null;
		todayPrice: number | null;
		saleEvents: SaleEvent[];
		hasListings: boolean;
		yMin: number | null;
	} = $props();

	function eventSpan(e: SaleEvent): string {
		return e.start === e.end ? formatDate(e.start) : `${formatShortDate(e.start)} – ${formatDate(e.end)}`;
	}
	// Curated dates not yet announced are marked in the legend and the
	// screen-reader list (R9); the canvas label stays short.
	const eventName = (e: SaleEvent) => (e.estimated ? `${e.name} (estimated)` : e.name);
	const eventDetail = (e: SaleEvent) =>
		`${e.name} (${e.estimated ? 'estimated, ' : ''}${eventSpan(e)})`;
</script>

<!-- Rendered inside PriceChart's <figcaption>. The legend explains the two
     lines, the band and the markers (#27). Line styles, not new hues: the
     chart keeps its one accent colour. -->
<ul class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted" aria-label="Chart legend">
	{#if hasBand}
		<li class="flex items-center gap-1.5">
			<svg width="18" height="10" aria-hidden="true">
				<rect x="0" y="2" width="18" height="6" fill="var(--accent-soft)" />
				<line x1="0" y1="8" x2="18" y2="8" stroke="var(--text-muted)" stroke-width="1" />
				<line x1="0" y1="2" x2="18" y2="2" stroke="var(--text-muted)" stroke-width="1" />
			</svg>
			Cheapest and dearest in-stock price each day
		</li>
	{/if}
	{#if lowMarker !== null}
		<li class="flex items-center gap-1.5">
			<svg width="18" height="10" aria-hidden="true">
				<line
					x1="0"
					y1="5"
					x2="18"
					y2="5"
					stroke="var(--text-muted)"
					stroke-width="1"
					stroke-dasharray="4 4"
				/>
			</svg>
			Lowest recorded <span class="num">{formatAud(lowMarker)}</span>
		</li>
	{/if}
	{#if avg30 !== null}
		<li class="flex items-center gap-1.5">
			<svg width="18" height="10" aria-hidden="true">
				<line
					x1="0"
					y1="5"
					x2="18"
					y2="5"
					stroke="var(--text-muted)"
					stroke-width="1"
					stroke-dasharray="8 4"
				/>
			</svg>
			30-day avg <span class="num">{formatAud(avg30)}</span>
		</li>
	{/if}
	{#if todayPrice !== null}
		<li class="flex items-center gap-1.5">
			<svg width="10" height="10" aria-hidden="true"
				><circle cx="5" cy="5" r="4" fill="var(--accent)" /></svg
			>
			Today <span class="num">{formatAud(todayPrice)}</span>
		</li>
	{/if}
	{#if saleEvents.length > 0}
		<li class="flex items-center gap-1.5">
			<svg width="10" height="12" aria-hidden="true">
				<line
					x1="5"
					y1="0"
					x2="5"
					y2="12"
					stroke="var(--text-muted)"
					stroke-width="1"
					stroke-dasharray="3 3"
				/>
			</svg>
			Sale events: {saleEvents.map(eventName).join(', ')}
		</li>
	{/if}
	{#if hasListings}
		<li class="flex items-center gap-1.5">
			<svg width="18" height="10" aria-hidden="true">
				<line
					x1="0"
					y1="5"
					x2="18"
					y2="5"
					stroke="var(--accent)"
					stroke-width="1.75"
					stroke-dasharray="5 4"
				/>
			</svg>
			Listings you added to the chart
		</li>
	{/if}
</ul>
{#if saleEvents.length > 0}
	<p class="sr-only" data-testid="chart-sale-events">
		Sale events shown: {saleEvents.map(eventDetail).join('; ')}.
	</p>
{/if}
{#if yMin !== null && !axisStartsAtZero(yMin)}
	<p class="mt-1 text-xs text-text-muted">Axis doesn't start at $0.</p>
{/if}
