<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';
	import { formatAud } from '$lib/formats';

	export interface ChartSeries {
		listingId: number;
		label: string;
		points: { date: string; price: number }[];
	}

	let {
		series,
		height = 300
	}: {
		series: ChartSeries[];
		height?: number;
	} = $props();

	let chartEl: HTMLDivElement;
	let u: uPlot | null = null;
	let tooltipEl: HTMLDivElement | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let themeObserver: MutationObserver | null = null;

	const LINE_STYLES: number[][] = [[], [5, 4], [1, 3]];

	function cssVar(name: string): string {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	function formatTick(ts: number): string {
		return new Date(ts).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
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
		const date = formatTick(x);
		const rows = uInstance.series
			.slice(1)
			.map((s, i) => {
				const raw = uInstance.data[i + 1][didx];
				return raw == null
					? null
					: `<div class="flex items-center justify-between gap-4">
						   <span class="text-text-muted">${s.label}</span>
						   <span class="num text-text">${formatAud(raw)}</span>
					   </div>`;
			})
			.filter((r): r is string => r !== null)
			.join('');
		tooltipEl.innerHTML = `
			<div class="mb-1 border-b border-border pb-1 text-xs font-medium text-text">${date}</div>
			${rows}`;
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
				values: (_uInstance: uPlot, splits: number[]) => splits.map(formatTick)
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
		return [
			{ label: 'Date' },
			...series.map((s, i) => ({
				label: s.label,
				stroke: cssVar('--accent'),
				width: 1.75,
				dash: LINE_STYLES[i % LINE_STYLES.length],
				points: { show: true, size: 4 },
				value: (_self: uPlot, rawValue: number) =>
					rawValue == null ? '—' : formatAud(rawValue)
			}))
		];
	}

	function buildData(): uPlot.AlignedData {
		const dates = new Set<string>();
		for (const s of series) for (const p of s.points) dates.add(p.date);
		const xAxis = [...dates].sort();
		const xs = xAxis.map((d) => new Date(`${d}T00:00:00Z`).getTime());
		const ys = series.map((s) => {
			const byDate = new Map(s.points.map((p) => [p.date, p.price]));
			return xAxis.map((d) => byDate.get(d) ?? null);
		});
		return [xs, ...ys] as uPlot.AlignedData;
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
				scales: {
					x: { time: true },
					y: { auto: true }
				},
				axes: buildAxes(),
				series: buildSeries(),
				cursor: { y: false },
				focus: { alpha: 0.25 },
				hooks: {
					setCursor: [(uInstance) => showTooltip(uInstance, uInstance.cursor.idx ?? null)]
				}
			},
			buildData(),
			chartEl
		);

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
	}

	onMount(mount);
	onDestroy(destroy);
</script>

<div
	bind:this={chartEl}
	class="relative w-full overflow-hidden rounded-md border border-border bg-surface"
	aria-label="Price history chart"
></div>