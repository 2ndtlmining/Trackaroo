<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import PageHead from '$lib/components/PageHead.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import ValueScatter, { type ScatterPoint } from '$lib/components/ValueScatter.svelte';
	import BudgetWinners from '$lib/components/BudgetWinners.svelte';
	import { METRICS, defaultMetric, sourceNote, type MetricInfo, type MetricKey } from '$lib/perfIndex';
	import { retailerLabel } from '$lib/filters';
	import { withParams } from '$lib/urlState';
	import type { BudgetPick } from '$lib/value';
	import type { ValueCoverage } from '$lib/models';

	let {
		data
	}: {
		data: {
			category: 'gpu' | 'cpu';
			metric: MetricKey;
			metrics: MetricKey[];
			metricInfo: MetricInfo;
			citation: string;
			points: ScatterPoint[];
			frontier: number[];
			budgets: BudgetPick[];
			exclude8gb: boolean;
			excluded: number;
			coverage: ValueCoverage;
			required: { tracked: number; withPerf: number };
			retailers: string[];
		};
	} = $props();

	const CATEGORY_OPTIONS = [
		{ value: 'gpu', label: 'GPUs' },
		{ value: 'cpu', label: 'CPUs' }
	] as const;
	// "1440p raster" -> "Raster": the toggle only has to tell the two apart.
	const SHORT: Record<MetricKey, string> = {
		gpu_raster_1440p: 'Raster',
		gpu_rt_1440p: 'Ray tracing',
		cpu_gaming_1080p: 'Gaming'
	};

	const noun = $derived(data.category === 'gpu' ? 'GPUs' : 'CPUs');
	const note = $derived(sourceNote(data.metric));
	const metricOptions = $derived(data.metrics.map((m) => ({ value: m, label: SHORT[m] })));
	const retailerList = $derived(listJoin(data.retailers.map(retailerLabel)));

	function listJoin(items: string[]): string {
		if (items.length <= 1) return items.join('');
		return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
	}

	// Every control is URL state; the loader recomputes, so the server and the
	// first client render always agree (no hydration mismatch).
	function set(changes: Record<string, string | null>) {
		goto(`/value${withParams(page.url.search, changes)}`, { replaceState: true, keepFocus: true, noScroll: true });
	}
	function setCategory(c: 'gpu' | 'cpu') {
		set({ category: c === 'gpu' ? null : c, metric: null, no8gb: null });
	}
	function setMetric(m: MetricKey) {
		set({ metric: m === defaultMetric(data.category) ? null : m });
	}
</script>

<PageHead
	title="Value"
	description="Price against performance for AU GPUs and CPUs: the value frontier and the best buy at each budget."
/>

<div class="space-y-6">
	<PageHeader title="Value" subtitle={`What today's cheapest in-stock price buys in ${METRICS[data.metric].label} performance.`}>
		{#snippet actions()}
			<SegmentedControl label="Category" options={CATEGORY_OPTIONS} value={data.category} onChange={setCategory} />
			{#if data.metrics.length > 1}
				<SegmentedControl label="Metric" options={metricOptions} value={data.metric} onChange={setMetric} />
			{:else}
				<span
					data-testid="value-metric-label"
					class="rounded-lg border border-border-card bg-surface-2 px-3 py-1.5 text-body text-text-muted"
					>{data.metricInfo.label}</span
				>
			{/if}
		{/snippet}
	</PageHeader>

	<section aria-labelledby="value-chart-heading" class="rounded-xl border border-border-card bg-surface p-4 shadow-card">
		<div class="mb-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
			<h2 id="value-chart-heading" class="text-section">Price against {data.metricInfo.label}</h2>
			<ul class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted" aria-label="Legend">
				<li class="flex items-center gap-1.5">
					<svg width="22" height="10" aria-hidden="true" class="shrink-0">
						<path d="M1,9H11V2H21" fill="none" class="stroke-accent" stroke-width="2" />
						<circle cx="11" cy="5" r="3.5" class="fill-accent" />
					</svg>
					Value frontier: nothing faster for less
				</li>
				<li class="flex items-center gap-1.5">
					<svg width="10" height="10" aria-hidden="true" class="shrink-0"><circle cx="5" cy="5" r="3.5" class="fill-text-muted" /></svg>
					Other {noun}
				</li>
			</ul>
		</div>

		{#if data.points.length > 0}
			<ValueScatter
				points={data.points}
				frontier={data.frontier}
				metricLabel={data.metricInfo.label}
				unit={data.metricInfo.unit}
				{note}
				{noun}
			/>
		{:else}
			<p class="py-12 text-center text-sm text-text-muted">
				No {noun} have both performance data and an in-stock price today.
			</p>
		{/if}

		<div class="mt-3 space-y-1 border-t border-border pt-3 text-xs text-text-muted">
			<p data-testid="value-source">
				Performance: <a href={data.metricInfo.source_url} class="text-text-muted underline underline-offset-2 hover:text-text"
					>{data.citation}</a
				>, relative to {data.metricInfo.baseline}. Prices: cheapest in stock today across {retailerList || 'tracked retailers'}.
			</p>
			<p data-testid="value-coverage">
				Performance data for <span class="num">{data.coverage.withPerf}</span> of
				<span class="num">{data.coverage.tracked}</span> {noun} (<span class="num">{data.required.withPerf}</span> of
				<span class="num">{data.required.tracked}</span> current and previous generation).
				{#if data.excluded > 0}
					<span data-testid="value-excluded"
						><span class="num">{data.excluded}</span>
						{data.excluded === 1 ? 'product' : 'products'} without an in-stock price {data.excluded === 1 ? 'is' : 'are'} not
						shown.</span
					>
				{/if}
			</p>
		</div>
	</section>

	<section aria-labelledby="value-budget-heading" class="space-y-3">
		<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
			<h2 id="value-budget-heading" class="text-section">Best per budget</h2>
			{#if data.category === 'gpu'}
				<label
					class="flex h-9 cursor-pointer select-none items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-sm text-text"
				>
					<input
						type="checkbox"
						class="size-4 accent-accent"
						checked={data.exclude8gb}
						onchange={(e) => set({ no8gb: (e.target as HTMLInputElement).checked ? '1' : null })}
					/>
					Exclude 8 GB cards
				</label>
			{/if}
		</div>
		<BudgetWinners budgets={data.budgets} metricLabel={data.metricInfo.label} {note} />
	</section>
</div>
