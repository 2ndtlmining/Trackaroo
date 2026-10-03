<script lang="ts" module>
	export interface ScatterPoint {
		id: number;
		name: string;
		price: number;
		perf: number;
		perKilo: number | null;
	}
</script>

<script lang="ts">
	// Price (x) against performance (y), one dot per product with both (#33).
	// The frontier (nothing is faster for less) is the accent staircase; every
	// other product is muted, so the chart adds no hue. The viewBox follows the
	// measured width, so text keeps its real size from 320 px up.
	import { formatAud } from '$lib/formats';
	import { audTick, kiloLabel, logScale, niceRange, shortName, stepPath } from '$lib/valueChart';

	let {
		points,
		frontier,
		metricLabel,
		unit,
		note,
		noun
	}: {
		points: ScatterPoint[];
		frontier: number[];
		metricLabel: string;
		unit: string;
		/** sourceNote(metric): the citation every value carries on hover. */
		note: string;
		/** "GPUs" / "CPUs", for the table caption. */
		noun: string;
	} = $props();

	let width = $state(0);
	const w = $derived(width > 0 ? width : 720);
	const h = $derived(w < 480 ? 300 : 380);
	const M = { top: 30, right: 14, bottom: 40, left: 40 };

	const onFrontier = $derived(new Set(frontier));
	const xs = $derived(logScale(Math.min(...points.map((p) => p.price)), Math.max(...points.map((p) => p.price))));
	const ys = $derived(niceRange(Math.min(...points.map((p) => p.perf)), Math.max(...points.map((p) => p.perf))));
	const x = (v: number) =>
		M.left + (Math.log(v / xs.lo) / Math.log(xs.hi / xs.lo)) * (w - M.left - M.right);
	const y = (v: number) => h - M.bottom - ((v - ys.lo) / (ys.hi - ys.lo)) * (h - M.top - M.bottom);
	// Drop a price tick that would sit within 40 px of the last one kept.
	const xTicks = $derived.by(() => {
		const kept: number[] = [];
		for (const t of xs.ticks) if (kept.length === 0 || x(t) - x(kept[kept.length - 1]) >= 40) kept.push(t);
		return kept;
	});

	const byId = $derived(new Map(points.map((p) => [p.id, p])));
	const frontPts = $derived(frontier.map((id) => byId.get(id)).filter((p): p is ScatterPoint => !!p));
	const line = $derived(stepPath(frontPts.map((p) => ({ x: x(p.price), y: y(p.perf) }))));
	// The wash under the staircase: what the frontier's money can buy.
	const area = $derived(
		frontPts.length > 0
			? `${line}V${h - M.bottom}H${x(frontPts[0].price).toFixed(1)}Z`
			: ''
	);
	// Muted dots first, frontier on top.
	const ordered = $derived([...points].sort((a, b) => Number(onFrontier.has(a.id)) - Number(onFrontier.has(b.id))));

	// Direct labels: frontier only, desktop only, never two that touch. Each
	// sits above-left of its dot: no product can be there (it would beat the
	// frontier point on both price and performance), and the staircase only
	// reaches a point from below, so the corner is always clear.
	const labels = $derived.by(() => {
		if (w < 560) return [];
		const placed: { id: number; text: string; lx: number; ly: number; anchor: 'start' | 'end' }[] = [];
		const boxes: { x0: number; x1: number; y0: number; y1: number }[] = [];
		for (const p of frontPts) {
			const text = shortName(p.name);
			const tw = text.length * 6.4;
			const px = x(p.price);
			const anchor = px - 11 - tw < M.left ? 'start' : 'end';
			const lx = anchor === 'end' ? px - 11 : px + 11;
			const ly = y(p.perf) - 9;
			const box = { x0: anchor === 'end' ? lx - tw : lx, x1: anchor === 'end' ? lx : lx + tw, y0: ly - 11, y1: ly + 3 };
			if (boxes.some((b) => b.x0 < box.x1 && box.x0 < b.x1 && b.y0 < box.y1 && box.y0 < b.y1)) continue;
			boxes.push(box);
			placed.push({ id: p.id, text, lx, ly, anchor });
		}
		return placed;
	});

	let active = $state<number | null>(null);
	const tip = $derived(active == null ? null : byId.get(active) ?? null);

	function ariaLabel(p: ScatterPoint): string {
		const front = onFrontier.has(p.id) ? ', on the value frontier' : '';
		return `${p.name}: ${formatAud(p.price)}, ${metricLabel} ${p.perf}, ${kiloLabel(p.perKilo)} per A$1,000${front}`;
	}
</script>

<figure class="m-0" aria-label={`Price against ${metricLabel} for each ${noun.slice(0, -1)} in stock`}>
	<div class="relative" bind:clientWidth={width}>
		<svg viewBox="0 0 {w} {h}" width="100%" height={h} class="block overflow-visible" role="group" aria-label="Value scatter">
			<!-- y title sits above the plot, horizontal, so a phone keeps its width -->
			<text x={M.left - 6} y={12} class="fill-text-muted text-[11px]">{metricLabel} ({unit})</text>
			{#each ys.ticks as t (t)}
				<line x1={M.left} x2={w - M.right} y1={y(t)} y2={y(t)} class="stroke-border" stroke-width="1" />
				<text x={M.left - 6} y={y(t) + 3.5} text-anchor="end" class="num fill-text-muted text-[10.5px]">{t}</text>
			{/each}
			{#each xTicks as t (t)}
				<text x={x(t)} y={h - M.bottom + 15} text-anchor="middle" class="num fill-text-muted text-[10.5px]">{audTick(t)}</text>
			{/each}
			<line x1={M.left} x2={w - M.right} y1={h - M.bottom} y2={h - M.bottom} class="stroke-border-strong" stroke-width="1" />
			<text x={w - M.right} y={h - 6} text-anchor="end" class="fill-text-muted text-[11px]">Price (A$, log scale)</text>

			{#if area}
				<path d={area} class="fill-accent-soft" />
				<path d={line} fill="none" class="stroke-accent" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
			{/if}

			{#each labels as l (l.id)}
				<text x={l.lx} y={l.ly} text-anchor={l.anchor} class="pointer-events-none fill-text-muted text-[11px]">{l.text}</text>
			{/each}

			{#each ordered as p (p.id)}
				{@const front = onFrontier.has(p.id)}
				<a
					href="/product/{p.id}"
					data-testid="value-point"
					data-frontier={front ? 'true' : 'false'}
					aria-label={ariaLabel(p)}
					class="point outline-none"
					onmouseenter={() => (active = p.id)}
					onmouseleave={() => (active = null)}
					onfocus={() => (active = p.id)}
					onblur={() => (active = null)}
				>
					<circle cx={x(p.price)} cy={y(p.perf)} r="12" fill="transparent" />
					<circle
						cx={x(p.price)}
						cy={y(p.perf)}
						r="9"
						fill="none"
						stroke-width="2"
						class="ring stroke-text {active === p.id ? 'opacity-100' : 'opacity-0'}"
					/>
					<circle
						cx={x(p.price)}
						cy={y(p.perf)}
						r={front ? 5 : 4}
						stroke-width="2"
						class="stroke-surface {front ? 'fill-accent' : 'fill-text-muted'}"
					/>
				</a>
			{/each}
		</svg>

		{#if tip}
			{@const tx = Math.min(Math.max(x(tip.price), 96), w - 96)}
			{@const below = y(tip.perf) < 110}
			<div
				data-testid="value-tooltip"
				aria-hidden="true"
				class="pointer-events-none absolute z-10 w-48 rounded-lg border border-border-card bg-surface-3 px-3 py-2 text-xs shadow-card"
				style="left: {tx}px; top: {y(tip.perf)}px; transform: translate(-50%, {below ? '16px' : 'calc(-100% - 16px)'});"
			>
				<p class="truncate font-medium text-text">{tip.name}</p>
				<dl class="mt-1 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-text-muted">
					<dt>Price</dt>
					<dd class="num text-right text-text">{formatAud(tip.price)}</dd>
					<dt>{metricLabel}</dt>
					<dd class="num text-right text-text">{tip.perf}</dd>
					<dt>Perf per A$1k</dt>
					<dd class="num text-right text-text">{kiloLabel(tip.perKilo)}</dd>
				</dl>
				{#if onFrontier.has(tip.id)}
					<p class="mt-1 text-accent">On the value frontier</p>
				{/if}
			</div>
		{/if}
	</div>

	<!-- The same rows for screen readers: the chart never gates a value. -->
	<!-- Wrapped: a table ignores the 1px sr-only width and would widen the page. -->
	<div class="sr-only">
	<table data-testid="value-table">
		<caption>{noun} by price and {metricLabel}. {note}.</caption>
		<thead>
			<tr>
				<th scope="col">Model</th>
				<th scope="col">Price</th>
				<th scope="col">{metricLabel} ({unit})</th>
				<th scope="col">Perf per A$1,000</th>
				<th scope="col">On the value frontier</th>
			</tr>
		</thead>
		<tbody>
			{#each frontPts.concat(points.filter((p) => !onFrontier.has(p.id))) as p (p.id)}
				<tr>
					<!-- Text, not a link: the dots are the links, and an off-screen
					     link would take keyboard focus somewhere nobody can see. -->
					<th scope="row">{p.name}</th>
					<td class="num">{formatAud(p.price)}</td>
					<td>{p.perf}</td>
					<td>{kiloLabel(p.perKilo)}</td>
					<td>{onFrontier.has(p.id) ? 'Yes' : 'No'}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	</div>
</figure>
