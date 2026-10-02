<script lang="ts">
	import { untrack } from 'svelte';
	import { afterNavigate, goto, replaceState } from '$app/navigation';
	import PageHead from '$lib/components/PageHead.svelte';
	import PriceChange from '$lib/components/PriceChange.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Sparkline from '$lib/components/Sparkline.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { formatAud, formatPct, formatSignedAud, titleCase } from '$lib/formats';
	import { retailerLabel } from '$lib/filters';
	import {
		groupMoversByProduct,
		moverColumnValue,
		moversHref,
		parseMoverView,
		sortMovers,
		type ColSortKey,
		type MoverDirFilter,
		type MoverGroup,
		type MoverSortKey,
		type MoverView
	} from '$lib/movers';
	import type { Mover } from '$lib/models';
	import type { ChangeDirection } from '$lib/types';
	import { nextSortDir, sortRows, type SortDir } from '$lib/tableSort';
	import { urlParams } from '$lib/urlParams';
	import { withParams } from '$lib/urlState';

	let {
		data
	}: {
		data: {
			movers: Mover[];
			window: string;
			windows: readonly string[];
			showAll: boolean;
			hiddenCount: number;
		};
	} = $props();

	// Sort, direction and grouping come from the URL (#26), read through
	// urlParams() so Back restores what replaceState wrote (see $lib/urlParams).
	let view = $state<MoverView>(parseMoverView(urlParams()));

	// A window change or Back/Forward between two /movers entries reuses this
	// component, so re-read the view from the URL it landed on. Only assign when
	// it differs, so the sync effect below never fires on a no-op.
	afterNavigate(() => {
		const next = parseMoverView(urlParams());
		if (next.sort !== view.sort || next.dir !== view.dir || next.group !== view.group) view = next;
	});

	const SORT_OPTIONS: readonly { value: MoverSortKey; label: string }[] = [
		{ value: 'abs', label: '$ change' },
		{ value: 'pct', label: '% change' },
		{ value: 'price', label: 'Price' }
	];
	const DIR_OPTIONS: readonly { value: MoverDirFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'up', label: 'Up' },
		{ value: 'down', label: 'Down' }
	];
	const GROUP_OPTIONS: readonly { value: 'product' | 'listing'; label: string }[] = [
		{ value: 'product', label: 'By product' },
		{ value: 'listing', label: 'Per listing' }
	];
	const windowOptions = $derived(data.windows.map((w) => ({ value: w, label: w })));

	function direction(m: Mover): ChangeDirection {
		if (m.notEnoughHistory) return 'insufficient';
		if (m.change === null) return 'insufficient';
		if (Math.abs(m.change) < 0.005) return 'flat';
		return m.change > 0 ? 'up' : 'down';
	}

	function pctLabel(m: Mover): string {
		return m.pctChange === null ? '—' : formatPct(m.pctChange);
	}

	function variantLabel(m: Mover): string {
		return titleCase(m.variantName).split(',')[0].trim() || '—';
	}

	function moreLabel(more: number, open: boolean): string {
		const noun = more === 1 ? 'listing' : 'listings';
		return open ? `Hide ${noun}` : `+${more} more ${noun}`;
	}

	function setWindow(w: string) {
		goto(moversHref(w, view, data.showAll));
	}

	// Shallow URL sync: replaceState rewrites the address bar without re-running
	// load (the view is client-side). It must track only `view`: replaceState
	// reads page.url internally, so called tracked it would re-run this effect
	// on every navigation and, on Back, write the old view over the URL just
	// landed on (before afterNavigate could re-read it). Hence untrack().
	// The first run is skipped: the view was just read from this URL, and in dev
	// SvelteKit throws if replaceState runs before its router has started.
	let urlSynced = false;
	$effect(() => {
		const next = withParams(location.search, {
			sort: view.sort === 'abs' ? null : view.sort,
			dir: view.dir === 'all' ? null : view.dir,
			group: view.group ? null : '0'
		});
		if (!urlSynced) {
			urlSynced = true;
			return;
		}
		if (next !== location.search) untrack(() => replaceState(`${location.pathname}${next}`, {}));
	});

	const visible = $derived(data.movers.filter((m) => view.dir === 'all' || direction(m) === view.dir));
	const sorted = $derived(sortMovers(visible, view.sort));

	// Column-header sorting re-orders whatever the controls produced. It is a
	// transient, client-only view (U-D14).
	let colKey = $state<ColSortKey | null>(null);
	let colDir = $state<SortDir>(null);

	function onColHeader(key: ColSortKey) {
		if (colKey === key) colDir = nextSortDir(colDir);
		else {
			colKey = key;
			colDir = 'asc';
		}
	}

	function colArrow(key: ColSortKey): string {
		if (colKey !== key || colDir === null) return '';
		return colDir === 'asc' ? ' ▲' : ' ▼';
	}

	function ariaSort(key: ColSortKey): 'ascending' | 'descending' | 'none' {
		if (colKey !== key || colDir === null) return 'none';
		return colDir === 'asc' ? 'ascending' : 'descending';
	}

	const ordered = $derived(
		colKey !== null && colDir !== null
			? sortRows(sorted, colDir, (m) => moverColumnValue(m, colKey!))
			: sorted
	);
	const groups: MoverGroup[] = $derived(
		view.group
			? groupMoversByProduct(ordered)
			: ordered.map((m) => ({ productId: m.productId, lead: m, rest: [] }))
	);

	let expanded = $state<Set<number>>(new Set());
	function toggleExpanded(productId: number) {
		const next = new Set(expanded);
		if (next.has(productId)) next.delete(productId);
		else next.add(productId);
		expanded = next;
	}

	const hasTrend = $derived(sorted.some((m) => (m.sparkline?.length ?? 0) >= 2));
	const caption = $derived(
		`Price changes over ${data.window}, ${view.group ? 'one row per product' : 'one row per listing'}`
	);
</script>

<PageHead title="Movers" description="The biggest AU CPU and GPU price changes over the last day, week or month." />

{#snippet moverRow(m: Mover, more: number, nested: boolean)}
	<tr class="hover:bg-surface-hover" data-testid="mover-row">
		<!-- w-full + max-w-0 lets the model truncate instead of widening the table
		     past a phone screen; retailer and variant fold under it below md. -->
		<td class="w-full max-w-0 px-3 py-2 {nested ? 'pl-7' : ''}">
			<a href="/product/{m.productId}" class="block truncate no-underline hover:no-underline">{m.model}</a>
			<span class="block truncate text-xs text-text-muted md:hidden" title={titleCase(m.variantName) || undefined}
				>{`${retailerLabel(m.retailer)} · ${variantLabel(m)}`}</span
			>
			{#if more > 0}
				<button
					type="button"
					class="mt-0.5 text-xs text-accent"
					aria-expanded={expanded.has(m.productId)}
					onclick={() => toggleExpanded(m.productId)}>{moreLabel(more, expanded.has(m.productId))}</button
				>
			{/if}
		</td>
		<td class="hidden whitespace-nowrap px-3 py-2 text-text md:table-cell">{retailerLabel(m.retailer)}</td>
		<td class="hidden max-w-56 truncate px-3 py-2 text-text-muted lg:table-cell" title={titleCase(m.variantName) || undefined}>
			{variantLabel(m)}
		</td>
		<td class="num hidden px-3 py-2 text-right text-text-muted md:table-cell">
			{m.oldPrice === null ? '—' : formatAud(m.oldPrice)}
		</td>
		<td class="num whitespace-nowrap px-3 py-2 text-right text-text">{formatAud(m.newPrice)}</td>
		{#if hasTrend}
			<td class="hidden w-16 px-3 py-2 md:table-cell"><Sparkline points={m.sparkline} /></td>
		{/if}
		<td class="whitespace-nowrap px-3 py-2 text-right">
			{#if m.notEnoughHistory}
				<Badge tone="neutral" label="Not enough history" />
			{:else if m.change === null}
				<span class="text-text-muted">—</span>
			{:else}
				<PriceChange direction={direction(m)} label="{formatSignedAud(m.change)} ({pctLabel(m)})" />
			{/if}
		</td>
		<td class="num hidden px-3 py-2 text-text-muted md:table-cell">{m.historyPoints}</td>
	</tr>
{/snippet}

<div class="space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-4">
		<div>
			<h1 class="text-xl font-semibold text-text">Movers</h1>
			<p class="mt-1 text-sm text-text-muted">Biggest price changes over the selected window.</p>
		</div>
		<SegmentedControl label="Window" options={windowOptions} value={data.window} onChange={setWindow} />
	</div>

	{#if data.showAll}
		<a class="text-xs text-accent" href={moversHref(data.window, view, false)}>Hide unchanged and new listings</a>
	{:else if data.hiddenCount > 0}
		<a class="text-xs text-accent" href={moversHref(data.window, view, true)}
			>{`Show ${data.hiddenCount} unchanged or new listings`}</a
		>
	{/if}

	<div class="flex flex-wrap items-center gap-4 text-sm">
		<div class="flex items-center gap-2">
			<span class="text-text-muted" aria-hidden="true">Sort</span>
			<SegmentedControl label="Sort" options={SORT_OPTIONS} value={view.sort} onChange={(v) => (view = { ...view, sort: v })} />
		</div>
		<div class="flex items-center gap-2">
			<span class="text-text-muted" aria-hidden="true">Direction</span>
			<SegmentedControl label="Direction" options={DIR_OPTIONS} value={view.dir} onChange={(v) => (view = { ...view, dir: v })} />
		</div>
		<div class="flex items-center gap-2">
			<span class="text-text-muted" aria-hidden="true">Rows</span>
			<SegmentedControl
				label="Rows"
				options={GROUP_OPTIONS}
				value={view.group ? 'product' : 'listing'}
				onChange={(v) => (view = { ...view, group: v === 'product' })}
			/>
		</div>
	</div>

	{#if sorted.length === 0}
		<div class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted">
			No movers match the current filters.
		</div>
	{:else}
		<!-- One table at every width (#5 item 6): lower-priority columns hide below
		     md instead of a second, mobile-only copy of every row. -->
		<div class="overflow-x-auto rounded-md border border-border">
			<table class="w-full border-collapse text-sm">
				<caption class="sr-only">{caption}</caption>
				<thead>
					<tr class="border-b border-border text-left text-xs text-text-muted">
						<th scope="col" class="px-3 py-2 font-medium">Model</th>
						<th scope="col" class="hidden px-3 py-2 font-medium md:table-cell">Retailer</th>
						<th scope="col" class="hidden px-3 py-2 font-medium lg:table-cell">Variant</th>
						<th scope="col" aria-sort={ariaSort('old')} class="hidden px-3 py-2 text-right font-medium md:table-cell">
							<button type="button" onclick={() => onColHeader('old')} class="font-medium text-text-muted hover:text-text"
								>Old{colArrow('old')}</button
							>
						</th>
						<th scope="col" aria-sort={ariaSort('new')} class="px-3 py-2 text-right font-medium">
							<button type="button" onclick={() => onColHeader('new')} class="font-medium text-text-muted hover:text-text"
								>New{colArrow('new')}</button
							>
						</th>
						{#if hasTrend}
							<th scope="col" class="hidden w-16 px-3 py-2 font-medium md:table-cell">Trend</th>
						{/if}
						<th scope="col" aria-sort={ariaSort('change')} class="px-3 py-2 text-right font-medium">
							<button type="button" onclick={() => onColHeader('change')} class="font-medium text-text-muted hover:text-text"
								>Change{colArrow('change')}</button
							>
						</th>
						<th scope="col" aria-sort={ariaSort('points')} class="hidden px-3 py-2 font-medium md:table-cell">
							<button type="button" onclick={() => onColHeader('points')} class="font-medium text-text-muted hover:text-text"
								>Points{colArrow('points')}</button
							>
						</th>
					</tr>
				</thead>
				{#each groups as g (g.lead.listingId)}
					<tbody class="border-b border-border last:border-b-0">
						{@render moverRow(g.lead, g.rest.length, false)}
						{#if expanded.has(g.productId)}
							{#each g.rest as m (m.listingId)}
								{@render moverRow(m, 0, true)}
							{/each}
						{/if}
					</tbody>
				{/each}
			</table>
		</div>
	{/if}
</div>
