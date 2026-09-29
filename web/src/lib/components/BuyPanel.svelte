<script lang="ts">
	import { retailerLabel } from '$lib/filters';
	import { formatAud, formatDate } from '$lib/formats';
	import type { LowSummary, RetailerOffer, WindowStats } from '$lib/buySignals';

	// Facts, not a verdict (#31 option A; 17-Aug decision): the low and when it
	// was, the recent spread, and who has it cheapest right now.
	let {
		low,
		windows,
		where
	}: { low: LowSummary | null; windows: WindowStats[]; where: RetailerOffer[] } = $props();
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

	{#if windows.length > 0}
		<table class="mt-3 w-full max-w-md text-sm">
			<caption class="sr-only">
				Cheapest in-stock price per day: low, median and high over recent windows
			</caption>
			<thead>
				<tr class="text-left text-xs text-text-muted">
					<th scope="col" class="py-1 pr-3 font-medium">Last</th>
					<th scope="col" class="py-1 pr-3 text-right font-medium">Low</th>
					<th scope="col" class="py-1 pr-3 text-right font-medium">Median</th>
					<th scope="col" class="py-1 text-right font-medium">High</th>
				</tr>
			</thead>
			<tbody>
				{#each windows as w (w.days)}
					<tr class="border-t border-border">
						<th scope="row" class="py-1 pr-3 text-left font-normal text-text-muted">{w.days} days</th>
						{#if w.enough && w.low !== null && w.median !== null && w.high !== null}
							<td class="num py-1 pr-3 text-right text-text">{formatAud(w.low)}</td>
							<td class="num py-1 pr-3 text-right text-text">{formatAud(w.median)}</td>
							<td class="num py-1 text-right text-text">{formatAud(w.high)}</td>
						{:else}
							<td colspan="3" class="py-1 text-right text-text-muted">
								Gathering history ({w.points} {w.points === 1 ? 'day' : 'days'})
							</td>
						{/if}
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
								<!-- Link text is "Buy ↗", not "Buy at X": e2e counts offer-row
								     "Buy at" links, and the aria-label carries the full name. -->
								<a
									href={r.cheapestUrl}
									target="_blank"
									rel="noopener noreferrer"
									aria-label="Buy at {retailerLabel(r.retailer)} for {formatAud(r.cheapest)} (opens in a new tab)"
									class="text-xs text-accent">Buy ↗</a
								>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</section>
