<script lang="ts">
	import { onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';
	import { formatAud, formatChartTick } from '$lib/formats';
	import { saleEventsInRange, type SaleEvent } from '$lib/saleEvents';
	import { renderTooltip, type TooltipRow } from '$lib/chartTooltip';
	import {
		buildAxes,
		buildData,
		buildSeries,
		cssVar,
		drawGaps,
		drawSales,
		type ChartBand,
		type ChartSeries,
		type PlotInputs
	} from '$lib/priceChartPlot';
	import PriceChartLegend from './PriceChartLegend.svelte';

	let {
		series,
		band = null,
		cheapestInStock = null,
		lowMarker = null,
		avg30 = null,
		summary,
		height = 300
	}: {
		series: ChartSeries[];
		band?: ChartBand | null;
		cheapestInStock?: { date: string; price: number } | null;
		// Dashed horizontal line at the lowest recorded cheapest price (#27).
		lowMarker?: number | null;
		// Dashed horizontal line at the 30-day average (#27). Not a retailer.
		avg30?: number | null;
		// Accessible name for the canvas: see chartSummary.ts.
		summary: string;
		height?: number;
	} = $props();

	let chartEl: HTMLDivElement;
	let u: uPlot | null = null;
	let tooltipEl: HTMLDivElement | null = null;
	let chartReady = $state(false);
	let yMin = $state<number | null>(null);
	// avgIdx: series index the tooltip skips (reference line). realIdx: the real
	// series whose missing days get dotted connectors. Set by mount().
	let avgIdx = -1;
	let realIdx: number[] = [];
	let xDates: string[] = [];
	let resizeObserver: ResizeObserver | null = null;
	let themeObserver: MutationObserver | null = null;

	const inputs = (): PlotInputs => ({ series, band, cheapestInStock, lowMarker, avg30 });

	// AU sale events inside the plotted date range (#31): dashed vertical
	// markers in the muted text colour, no new hue. The same list is written
	// out in the caption, since the canvas itself says nothing to a reader.
	const plotted = $derived.by(() => {
		const dates: string[] = [];
		if (band) dates.push(...band.dates);
		for (const s of series) for (const p of s.points) dates.push(p.date);
		if (cheapestInStock) dates.push(cheapestInStock.date);
		dates.sort();
		return dates.length ? { from: dates[0], to: dates[dates.length - 1] } : null;
	});
	const saleEvents = $derived<SaleEvent[]>(plotted ? saleEventsInRange(plotted.from, plotted.to) : []);

	function hideTooltip() {
		if (tooltipEl) tooltipEl.style.display = 'none';
	}

	function showTooltip(uInstance: uPlot, didx: number | null) {
		if (!tooltipEl || didx == null) {
			hideTooltip();
			return;
		}
		const x = uInstance.data[0][didx];
		if (x == null) {
			hideTooltip();
			return;
		}
		const date = formatChartTick(x);
		const rows: TooltipRow[] = [];
		uInstance.series.slice(1).forEach((s, i) => {
			if (i + 1 === avgIdx) return;
			const raw = uInstance.data[i + 1][didx];
			if (raw == null) return;
			rows.push({ label: typeof s.label === 'string' ? s.label : '', value: formatAud(raw) });
		});
		renderTooltip(tooltipEl, date, rows);
		const left = uInstance.valToPos(x, 'x', true);
		tooltipEl.style.left = `${Math.min(left, chartEl.clientWidth - 140)}px`;
		tooltipEl.style.top = '8px';
		tooltipEl.style.display = 'block';
	}

	function mount() {
		if (!chartEl) return;
		if (!tooltipEl || !chartEl.contains(tooltipEl)) {
			tooltipEl = document.createElement('div');
			tooltipEl.setAttribute('data-tooltip', '');
			tooltipEl.className =
				'pointer-events-none absolute z-10 min-w-32 rounded-lg border border-border-card bg-surface-3 px-2.5 py-2 text-sm shadow-md';
			tooltipEl.style.display = 'none';
			chartEl.appendChild(tooltipEl);
		}

		const plot = buildSeries(inputs());
		avgIdx = plot.avgIdx;
		realIdx = plot.realIdx;
		const built = buildData(inputs());
		xDates = built.xDates;

		u = new uPlot(
			{
				width: chartEl.clientWidth || 600,
				height,
				padding: [12, 10, 4, 4],
				legend: { show: false },
				bands: band
					? [{ series: [1, 2], fill: cssVar('--accent-soft') || `${cssVar('--accent')}26` }]
					: undefined,
				scales: {
					x: { time: true },
					y: { auto: true }
				},
				axes: buildAxes(),
				series: plot.series,
				cursor: { y: false },
				focus: { alpha: 0.25 },
				hooks: {
					draw: [(ui) => drawGaps(ui, realIdx, xDates), (ui) => drawSales(ui, saleEvents)],
					setScale: [
						(uInstance, key) => {
							if (key === 'y') yMin = uInstance.scales.y.min ?? null;
						}
					],
					setCursor: [(uInstance) => showTooltip(uInstance, uInstance.cursor.idx ?? null)]
				}
			},
			built.data,
			chartEl
		);
		chartReady = true;

		if (!resizeObserver) {
			resizeObserver = new ResizeObserver(() => {
				if (u && chartEl) u.setSize({ width: chartEl.clientWidth, height });
			});
		}
		resizeObserver.observe(chartEl);

		if (!themeObserver) {
			themeObserver = new MutationObserver(() => {
				if (!u) return;
				u.destroy();
				u = null;
				mount();
			});
		}
		themeObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-theme']
		});
	}

	function destroy() {
		resizeObserver?.disconnect();
		themeObserver?.disconnect();
		if (u) {
			u.destroy();
			u = null;
		}
		chartReady = false;
	}

	// Reactive rebuild: buildData/buildSeries read the current props, so this
	// effect re-runs when the route data changes (client-side navigation
	// between products) or when listing overlays are toggled on/off. The chart
	// is recreated from scratch so series indices and band layout always match
	// the incoming data (no stale state survives).
	$effect(() => {
		void buildData(inputs());
		void buildSeries(inputs());
		void saleEvents;
		if (!chartEl) return;
		destroy();
		mount();
	});

	onDestroy(destroy);
</script>

<figure class="m-0">
	<div
		bind:this={chartEl}
		role="img"
		aria-label={summary}
		class="relative w-full overflow-hidden rounded-xl border border-border-card bg-surface shadow-card"
	>
		{#if !chartReady}
			<!-- No role="status": children of role="img" are presentational. -->
			<div class="chart-skeleton" aria-hidden="true">
				<div class="skeleton-bar" style="height: 42%"></div>
				<div class="skeleton-bar" style="height: 68%"></div>
				<div class="skeleton-bar" style="height: 55%"></div>
				<div class="skeleton-bar" style="height: 80%"></div>
				<div class="skeleton-bar" style="height: 61%"></div>
				<div class="skeleton-bar" style="height: 74%"></div>
				<div class="skeleton-bar" style="height: 48%"></div>
				<div class="skeleton-bar" style="height: 66%"></div>
			</div>
		{/if}
	</div>
	<figcaption>
		<PriceChartLegend
			hasBand={band !== null}
			{lowMarker}
			{avg30}
			todayPrice={cheapestInStock?.price ?? null}
			{saleEvents}
			hasListings={series.length > 0}
			{yMin}
		/>
	</figcaption>
</figure>
