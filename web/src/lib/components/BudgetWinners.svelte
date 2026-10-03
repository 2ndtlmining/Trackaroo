<script lang="ts">
	// Best performance at or under each budget (#33): the winner with its price,
	// performance and perf per A$1k, then the runner-up and the gap between them.
	// An empty bracket says so; a lone product has no runner-up and no gap.
	import Trophy from '@lucide/svelte/icons/trophy';
	import { formatAud } from '$lib/formats';
	import { perfPerKilo, type BudgetPick } from '$lib/value';
	import { gapLabel, kiloLabel } from '$lib/valueChart';

	let {
		budgets,
		metricLabel,
		note
	}: {
		budgets: BudgetPick[];
		metricLabel: string;
		/** sourceNote(metric), the hover text on every performance figure. */
		note: string;
	} = $props();
</script>

<ul class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="budget-winners">
	{#each budgets as b (b.max)}
		{@const under = `under ${formatAud(b.max)}`}
		<li
			data-testid="budget-card"
			class="flex flex-col rounded-xl border border-border-card bg-surface p-4 shadow-card"
		>
			<h3 class="text-section">Best {under}</h3>
			{#if b.winner}
				<a
					href="/product/{b.winner.id}"
					data-testid="budget-winner"
					class="mt-2 flex items-start gap-1.5 font-medium text-text no-underline hover:underline"
				>
					<Trophy class="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
					<span class="min-w-0 break-words">{b.winner.name}</span>
				</a>
				<p class="text-price mt-1 text-text">{formatAud(b.winner.price)}</p>
				<dl class="mb-3 mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs text-text-muted">
					<dt>{metricLabel}</dt>
					<dd class="num text-right text-text" title={note}>{b.winner.perf}</dd>
					<dt>Perf per A$1k</dt>
					<dd class="num text-right text-text" title={`${note}, per A$1,000 of today's price`}>
						{kiloLabel(perfPerKilo(b.winner.price, b.winner.perf))}
					</dd>
				</dl>
				<div class="mt-auto border-t border-border pt-2 text-xs text-text-muted">
					{#if b.runnerUp}
						<p class="text-text">{gapLabel(b.gap)}</p>
						<p class="mt-0.5">
							Runner-up: <a href="/product/{b.runnerUp.id}" class="text-text-muted underline-offset-2 hover:text-text"
								>{b.runnerUp.name}</a
							>, <span class="num">{formatAud(b.runnerUp.price)}</span>
						</p>
					{:else}
						<p>The only one in stock {under}</p>
					{/if}
				</div>
			{:else}
				<p class="mt-2 text-sm text-text-muted" data-testid="budget-empty">Nothing in stock {under}</p>
			{/if}
		</li>
	{/each}
</ul>
