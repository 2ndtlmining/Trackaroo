<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import { retailerLabel } from '$lib/filters';
	import { formatAud, formatDate } from '$lib/formats';
	import SignalBadge from './SignalBadge.svelte';
	import type { LowSummary, RetailerOffer, Signal, WindowStats } from '$lib/buySignals';

	// Facts, not a verdict (#31 option A; 17-Aug decision): the low and when it
	// was, a checklist of separate signals each with its evidence, the recent
	// spread, and who has it cheapest right now.
	let {
		low,
		windows,
		where,
		signals = []
	}: {
		low: LowSummary | null;
		windows: WindowStats[];
		where: RetailerOffer[];
		signals?: Signal[];
	} = $props();

	const ROWS = [
		{ label: 'Low', pick: (w: WindowStats) => w.low },
		{ label: 'Median', pick: (w: WindowStats) => w.median },
		{ label: 'High', pick: (w: WindowStats) => w.high }
	];
	const filled = (w: WindowStats) => w.enough && w.low !== null && w.median !== null && w.high !== null;
</script>

<section class="rounded-md border border-border bg-surface p-4" aria-labelledby="buy-heading">
	<h2 id="buy-heading" class="text-sm font-semibold text-text">Is now a good time to buy?</h2>

	<p class="mt-2 text-sm text-text" data-testid="low-summary">
		{#if low === null}
			No in-stock price recorded yet.
		{:else if low.atLow}
			<span class="font-medium text-accent">Today is the lowest price since {formatDate(low.since)}</span>:
			<span class="num font-medium">{formatAud(low.today ?? low.low)}</span>.
		{:else}
			Lowest since {formatDate(low.since)}:
			<span class="num font-medium">{formatAud(low.low)}</span>, last seen {formatDate(low.lowDate)}.
			{#if low.pctAbove !== null}
				Today is <span class="num font-medium">{low.pctAbove.toFixed(1)}%</span> above that.
			{:else}
				Nothing is in stock today.
			{/if}
		{/if}
	</p>

	{#if signals.length > 0}
		<ul class="mt-3 grid gap-2 md:grid-cols-2" aria-label="Buying signals">
			{#each signals as signal (signal.key)}
				<SignalBadge {signal} />
			{/each}
		</ul>
	{/if}

	{#if windows.length > 0}
		<!-- Windows across the top, statistics down the side: a compact 3x3 strip. -->
		<table class="mt-4 w-full max-w-lg text-sm tabular-nums" data-testid="stats-strip">
			<caption class="sr-only">
				Cheapest in-stock price per day: low, median and high over recent windows
			</caption>
			<thead>
				<tr class="text-xs text-text-muted">
					<td class="py-1 pr-3"></td>
					{#each windows as w (w.days)}
						<th scope="col" class="py-1 pl-3 text-right font-medium">{w.days} days</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each ROWS as row, r (row.label)}
					<tr class="border-t border-border">
						<th scope="row" class="py-1.5 pr-3 text-left font-normal text-text-muted">{row.label}</th>
						{#each windows as w (w.days)}
							{#if filled(w)}
								<td class="num py-1.5 pl-3 text-right text-text">{formatAud(row.pick(w) as number)}</td>
							{:else if r === 0}
								<td rowspan={ROWS.length} class="py-1.5 pl-3 text-right align-middle text-xs text-text-muted">
									Gathering history ({w.points} {w.points === 1 ? 'day' : 'days'})
								</td>
							{/if}
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	<h3 class="mt-4 text-xs font-semibold uppercase tracking-wide text-text-muted">Where to buy</h3>
	{#if where.length === 0}
		<p class="mt-1 text-sm text-text-muted">No retailer lists it right now.</p>
	{:else}
		<table class="mt-1 w-full text-sm">
			<caption class="sr-only">Cheapest in-stock price and listing counts per retailer</caption>
			<thead>
				<tr class="text-left text-xs text-text-muted">
					<th scope="col" class="py-1 pr-3 font-medium">Retailer</th>
					<th scope="col" class="py-1 pr-3 text-right font-medium">Price</th>
					<th scope="col" class="py-1 pr-3 text-right font-medium">In stock</th>
					<th scope="col" class="py-1 font-medium"><span class="sr-only">Link</span></th>
				</tr>
			</thead>
			<tbody>
				{#each where as r (r.retailer)}
					<tr class="border-t border-border">
						<th scope="row" class="py-1.5 pr-3 text-left font-medium text-text">
							{retailerLabel(r.retailer)}
						</th>
						<td class="num py-1.5 pr-3 text-right text-text">
							{r.cheapest === null ? '—' : formatAud(r.cheapest)}
						</td>
						<td class="num py-1.5 pr-3 text-right text-text-muted">{r.inStock} of {r.listings}</td>
						<td class="py-1.5 text-right">
							{#if r.cheapestUrl && r.cheapest !== null}
								<!-- Link text is "Buy" plus an arrow icon, not "Buy at X": e2e counts offer-row
								     "Buy at" links, and the aria-label carries the full name. -->
								<a
									href={r.cheapestUrl}
									target="_blank"
									rel="noopener noreferrer"
									aria-label="Buy at {retailerLabel(r.retailer)} for {formatAud(r.cheapest)} (opens in a new tab)"
									class="inline-flex items-center gap-0.5 text-xs text-accent"
									>Buy<ArrowUpRight size={12} aria-hidden="true" /></a
								>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</section>
