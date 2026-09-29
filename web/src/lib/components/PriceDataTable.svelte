<script lang="ts">
	import { formatAud, formatDate } from '$lib/formats';
	import type { PriceBandPoint } from '$lib/server/repos';

	// The chart's numbers, reachable by keyboard and screen reader and easy to
	// copy (#27). Collapsed by default so the page does not grow.
	let { band }: { band: PriceBandPoint[] } = $props();

	// Copy before reversing: `band` may be a shared (memoised) array.
	const rows = $derived([...band].reverse());
	const dayCount = $derived(`${band.length} ${band.length === 1 ? 'day' : 'days'}`);
</script>

{#if band.length > 0}
	<details class="rounded-md border border-border bg-surface">
		<summary class="cursor-pointer px-3 py-2 text-sm text-text">
			Show price data ({dayCount})
		</summary>
		<div class="max-h-80 overflow-auto border-t border-border">
			<table class="w-full text-sm">
				<caption class="sr-only">Cheapest and dearest in-stock price per day, newest first</caption>
				<thead>
					<tr class="text-left text-xs text-text-muted">
						<th scope="col" class="px-3 py-1.5 font-medium">Date</th>
						<th scope="col" class="px-3 py-1.5 text-right font-medium">Cheapest in stock</th>
						<th scope="col" class="px-3 py-1.5 text-right font-medium">Dearest in stock</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as p (p.date)}
						<tr class="border-t border-border">
							<th scope="row" class="px-3 py-1.5 text-left font-normal text-text-muted">
								{formatDate(p.date)}
							</th>
							<td class="num px-3 py-1.5 text-right text-text">{p.low === null ? '—' : formatAud(p.low)}</td>
							<td class="num px-3 py-1.5 text-right text-text">{p.high === null ? '—' : formatAud(p.high)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</details>
{/if}
