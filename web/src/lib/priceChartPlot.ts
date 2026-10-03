// uPlot options, data and draw hooks for PriceChart.svelte (#61: split out of
// the component). Browser-only: reads CSS custom properties and devicePixelRatio.
import type uPlot from 'uplot';
import { formatAud, formatChartTick } from '$lib/formats';
import type { SaleEvent } from '$lib/saleEvents';
import { gapSegments } from '$lib/chartExtras';

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

export interface PlotInputs {
	series: ChartSeries[];
	band: ChartBand | null;
	cheapestInStock: { date: string; price: number } | null;
	lowMarker: number | null;
	avg30: number | null;
}

const LINE_STYLES: number[][] = [[], [5, 4], [1, 3]];
// At most this many label rows; further labels are skipped (the line stays)
// so labels never cover more of the plot.
const MAX_LABEL_ROWS = 2;

export function cssVar(name: string): string {
	return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const audValue = (_self: uPlot, rawValue: number) => (rawValue == null ? '—' : formatAud(rawValue));

export function buildAxes(): uPlot.Axis[] {
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

/**
 * The uPlot series list. avgIdx is the series index the tooltip skips
 * (reference line); realIdx are the real series whose missing days get
 * dotted connectors.
 */
export function buildSeries({ series, band, cheapestInStock, lowMarker, avg30 }: PlotInputs): {
	series: Partial<uPlot.Series>[];
	avgIdx: number;
	realIdx: number[];
} {
	const accent = cssVar('--accent');
	const muted = cssVar('--text-muted');

	const result: Partial<uPlot.Series>[] = [{ label: 'Date' }];
	let avgIdx = -1;
	const realIdx: number[] = [];

	if (band) {
		result.push({
			label: 'Cheapest in stock',
			stroke: muted,
			width: 1,
			// A missing day bridges the line instead of breaking it (U-D12).
			spanGaps: true,
			points: { show: false },
			value: audValue
		});
		result.push({
			label: 'Dearest in stock',
			stroke: muted,
			width: 1,
			spanGaps: true,
			points: { show: false },
			value: audValue
		});
	}

	if (lowMarker !== null) {
		result.push({
			label: `Lowest ${formatAud(lowMarker)}`,
			stroke: muted,
			width: 1,
			dash: [4, 4],
			points: { show: false },
			value: audValue
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
			value: audValue
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
			value: audValue
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
			value: audValue
		});
	}

	return { series: result, avgIdx, realIdx };
}

/** Aligned data in buildSeries order, plus the ISO date of each x position. */
export function buildData({ series, band, cheapestInStock, lowMarker, avg30 }: PlotInputs): {
	data: uPlot.AlignedData;
	xDates: string[];
} {
	const dates = new Set<string>();
	if (band) {
		for (const d of band.dates) dates.add(d);
	}
	for (const s of series) for (const p of s.points) dates.add(p.date);
	if (cheapestInStock) dates.add(cheapestInStock.date);
	const xAxis = [...dates].sort();
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

	return { data: [xs, ...ys] as uPlot.AlignedData, xDates: xAxis };
}

// Dotted connectors across missing days of each real series (#27).
export function drawGaps(uInstance: uPlot, realIdx: number[], xDates: string[]) {
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
export function drawSales(uInstance: uPlot, saleEvents: SaleEvent[]) {
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
	// saleEvents arrive in date order (saleEventsInRange), so label rows pack left to right.
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
