<script lang="ts">
	import { onDestroy } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';
	import { formatAud, formatChartTick, formatDate, formatShortDate } from '$lib/formats';
	import { saleEventsInRange, type SaleEvent } from '$lib/saleEvents';
	import { renderTooltip, type TooltipRow } from '$lib/chartTooltip';
	import { axisStartsAtZero, gapSegments } from '$lib/chartExtras';

	export interface ChartSeries {
		listingId: number;
		label: string;
		points: { date: string; price: number }[];
	}

	export interface ChartBand {
		dates: string[];
		low: (number | null)[];
		high: (number | null)[];
	}

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
	// series whose missing days get dotted connectors. Set by buildSeries().
	let avgIdx = -1;
	let realIdx: number[] = [];
	let xDates: string[] = [];
	let resizeObserver: ResizeObserver | null = null;
	let themeObserver: MutationObserver | null = null;

	const LINE_STYLES: number[][] = [[], [5, 4], [1, 3]];

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

	function eventSpan(e: SaleEvent): string {
		return e.start === e.end ? formatDate(e.start) : `${formatShortDate(e.start)} – ${formatDate(e.end)}`;
	}
	// Curated dates not yet announced are marked in the legend and the
	// screen-reader list (R9); the canvas label stays short.
	const eventName = (e: SaleEvent) => (e.estimated ? `${e.name} (estimated)` : e.name);
	const eventDetail = (e: SaleEvent) =>
		`${e.name} (${e.estimated ? 'estimated, ' : ''}${eventSpan(e)})`;
	// At most this many label rows; further labels are skipped (the line stays)
	// so labels never cover more of the plot.
	const MAX_LABEL_ROWS = 2;

	function cssVar(name: string): string {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

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

	function buildAxes() {
		const text = cssVar('--text-muted');
		const border = cssVar('--border');
		return [
			{
				stroke: text,
				grid: { stroke: border },
				ticks: { stroke: border },
				size: 40,
				values: (_uInstance: uPlot, splits: number[]) => splits.map(formatChartTick)
			},
			{
				stroke: text,
				grid: { stroke: border },
				ticks: { stroke: border },
				size: 56,
				values: (_uInstance: uPlot, splits: number[]) => splits.map((v) => formatAud(v))
			}
		];
	}

	function buildSeries() {
		const accent = cssVar('--accent');
		const muted = cssVar('--text-muted');

		const result: Partial<uPlot.Series>[] = [{ label: 'Date' }];
		avgIdx = -1;
		realIdx = [];

		if (band) {
			result.push({
				label: 'Cheapest in stock',
				stroke: muted,
				width: 1,
				// A missing day bridges the line instead of breaking it (U-D12).
				spanGaps: true,
				points: { show: false },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
			result.push({
				label: 'Dearest in stock',
				stroke: muted,
				width: 1,
				spanGaps: true,
				points: { show: false },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
		}

		if (lowMarker !== null) {
			result.push({
				label: `Lowest ${formatAud(lowMarker)}`,
				stroke: muted,
				width: 1,
				dash: [4, 4],
				points: { show: false },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
		}

		// "Today" is the one accent hue, not the price-direction green (#24).
		if (cheapestInStock) {
			result.push({
				label: 'Today',
				stroke: accent,
				width: 2,
				dash: [],
				points: { show: true, size: 8 },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
		}

		if (avg30 !== null) {
			avgIdx = result.length;
			result.push({
				label: `30-day avg ${formatAud(avg30)}`,
				stroke: muted,
				width: 1,
				dash: [8, 4],
				points: { show: false },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
		}

		for (const s of series) {
			realIdx.push(result.length);
			result.push({
				label: s.label,
				stroke: accent,
				width: 1.75,
				// Gaps break the line; drawGaps() adds a dotted connector instead.
				spanGaps: false,
				dash: LINE_STYLES[result.length % LINE_STYLES.length],
				points: { show: true, size: 4 },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			});
		}

		return result;
	}

	function buildData(): uPlot.AlignedData {
		const dates = new Set<string>();
		if (band) {
			for (const d of band.dates) dates.add(d);
		}
		for (const s of series) for (const p of s.points) dates.add(p.date);
		if (cheapestInStock) dates.add(cheapestInStock.date);
		const xAxis = [...dates].sort();
		xDates = xAxis;
		const xs = xAxis.map((d) => new Date(`${d}T00:00:00Z`).getTime());

		const ys: (number | null)[][] = [];
		if (band) {
			const lowByDate = new Map(band.dates.map((d, i) => [d, band.low[i]]));
			const highByDate = new Map(band.dates.map((d, i) => [d, band.high[i]]));
			ys.push(xAxis.map((d) => lowByDate.get(d) ?? null));
			ys.push(xAxis.map((d) => highByDate.get(d) ?? null));
		}
		// Same position as in buildSeries: after the band pair, before today.
		if (lowMarker !== null) {
			ys.push(xAxis.map(() => lowMarker));
		}
		if (cheapestInStock) {
			ys.push(xAxis.map((d) => (d === cheapestInStock.date ? cheapestInStock.price : null)));
		}
		if (avg30 !== null) {
			ys.push(xAxis.map(() => avg30));
		}
		for (const s of series) {
			const byDate = new Map(s.points.map((p) => [p.date, p.price]));
			ys.push(xAxis.map((d) => byDate.get(d) ?? null));
		}

		return [xs, ...ys] as uPlot.AlignedData;
	}

	// Dotted connectors across missing days of each real series (#27).
	function drawGaps(uInstance: uPlot) {
		const ctx = uInstance.ctx;
		const xs = uInstance.data[0];
		ctx.save();
		ctx.strokeStyle = cssVar('--accent');
		ctx.lineWidth = 1.5 * devicePixelRatio;
		ctx.setLineDash([2 * devicePixelRatio, 4 * devicePixelRatio]);
		for (const idx of realIdx) {
			const ys = uInstance.data[idx] as (number | null)[];
			for (const { from, to } of gapSegments(xDates, ys)) {
				ctx.beginPath();
				ctx.moveTo(
					uInstance.valToPos(xs[from] as number, 'x', true),
					uInstance.valToPos(ys[from] as number, 'y', true)
				);
				ctx.lineTo(
					uInstance.valToPos(xs[to] as number, 'x', true),
					uInstance.valToPos(ys[to] as number, 'y', true)
				);
				ctx.stroke();
			}
		}
		ctx.restore();
	}

	// One dashed line where each event starts (or at the left edge when it was
	// already running), labelled at the top of the plot. Labels that would
	// collide drop to the next row.
	function drawSales(uInstance: uPlot) {
		if (saleEvents.length === 0) return;
		const ctx = uInstance.ctx;
		const dpr = devicePixelRatio;
		const { left, top, width, height: h } = uInstance.bbox;
		const xMin = uInstance.scales.x.min ?? 0;
		const muted = cssVar('--text-muted');
		const surface = cssVar('--surface');
		const fontFamily = getComputedStyle(document.body).fontFamily || 'sans-serif';
		ctx.save();
		ctx.strokeStyle = muted;
		ctx.fillStyle = muted;
		ctx.lineWidth = dpr;
		ctx.font = `${11 * dpr}px ${fontFamily}`;
		ctx.textBaseline = 'top';
		ctx.textAlign = 'left';
		const rowEnds: number[] = [];
		for (const e of saleEvents) {
			const ts = Math.max(new Date(`${e.start}T00:00:00Z`).getTime(), xMin);
			const x = Math.round(uInstance.valToPos(ts, 'x', true)) + 0.5;
			if (x < left - 1 || x > left + width + 1) continue;
			ctx.setLineDash([3 * dpr, 3 * dpr]);
			ctx.beginPath();
			ctx.moveTo(x, top);
			ctx.lineTo(x, top + h);
			ctx.stroke();
			const textW = ctx.measureText(e.name).width;
			const pad = 4 * dpr;
			// Flip the label to the left of the line near the right edge.
			const x0 = x + pad + textW > left + width ? x - pad - textW : x + pad;
			let row = rowEnds.findIndex((end) => x0 > end + pad);
			if (row === -1) row = rowEnds.length;
			if (row >= MAX_LABEL_ROWS) continue;
			rowEnds[row] = x0 + textW;
			ctx.setLineDash([]);
			// Knock the gridlines out behind the label so it reads cleanly.
			const y0 = top + 6 * dpr + row * 15 * dpr;
			ctx.fillStyle = surface;
			ctx.fillRect(x0 - 2 * dpr, y0 - dpr, textW + 4 * dpr, 13 * dpr);
			ctx.fillStyle = muted;
			ctx.fillText(e.name, x0, y0);
		}
		ctx.restore();
	}

	function mount() {
		if (!chartEl) return;
		if (!tooltipEl || !chartEl.contains(tooltipEl)) {
			tooltipEl = document.createElement('div');
			tooltipEl.setAttribute('data-tooltip', '');
			tooltipEl.className =
				'pointer-events-none absolute z-10 min-w-32 rounded-md border border-border bg-surface/95 px-2.5 py-2 text-sm shadow-md';
			tooltipEl.style.display = 'none';
			chartEl.appendChild(tooltipEl);
		}

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
				series: buildSeries(),
				cursor: { y: false },
				focus: { alpha: 0.25 },
				hooks: {
					draw: [drawGaps, drawSales],
					setScale: [
						(uInstance, key) => {
							if (key === 'y') yMin = uInstance.scales.y.min ?? null;
						}
					],
					setCursor: [(uInstance) => showTooltip(uInstance, uInstance.cursor.idx ?? null)]
				}
			},
			buildData(),
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
		void buildData();
		void buildSeries();
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
		class="relative w-full overflow-hidden rounded-md border border-border bg-surface"
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
	<!-- The legend explains the two lines, the band and the markers (#27). Line
	     styles, not new hues: the chart keeps its one accent colour. -->
	<figcaption>
		<ul class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted" aria-label="Chart legend">
			{#if band}
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
					30-day avg {formatAud(avg30)}
				</li>
			{/if}
			{#if cheapestInStock}
				<li class="flex items-center gap-1.5">
					<svg width="10" height="10" aria-hidden="true"
						><circle cx="5" cy="5" r="4" fill="var(--accent)" /></svg
					>
					Today <span class="num">{formatAud(cheapestInStock.price)}</span>
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
			{#if series.length > 0}
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
	</figcaption>
</figure>
