<script lang="ts">
	// Head-to-head with the nearest other-brand rival (#60). Every figure comes
	// from the loader's Matchup; this file only lays it out.
	import Scale from '@lucide/svelte/icons/scale';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import type { Matchup, MatchupSide } from '$lib/models';
	import { METRICS, sourceNote } from '$lib/perfIndex';
	import { formatAud } from '$lib/formats';

	let { matchup }: { matchup: Matchup } = $props();

	const p = $derived(matchup.product);
	const r = $derived(matchup.rival);
	const sources = $derived([...new Set(matchup.lines.map((l) => l.metric))]);
</script>

{#snippet sideFigures(side: MatchupSide)}
	<div class="min-w-0">
		<dt class="truncate text-text-muted">{side.name}</dt>
		<dd class="mt-0.5 text-text">
			<span class="num font-semibold">{formatAud(side.price)}</span>
			<span class="text-text-muted">·</span>
			<span class="num">{Math.round(side.perfPerKilo)}</span>
			<span class="text-text-muted">Perf/A$1k</span>
		</dd>
	</div>
{/snippet}

<section
	class="rounded-xl border border-border-card bg-surface shadow-card p-4"
	aria-labelledby="matchup-heading"
	data-testid="matchup"
>
	<h2 id="matchup-heading" class="flex items-center gap-1.5 text-sm font-semibold text-text">
		<Scale class="size-4 text-text-muted" aria-hidden="true" />
		Head to head
	</h2>
	<p class="mt-0.5 text-xs text-text-muted">
		vs <a
			href="/product/{r.id}"
			class="text-accent underline underline-offset-2 hover:no-underline"
			data-testid="matchup-rival">{r.name}</a
		>, the nearest match from the other brand on {METRICS[matchup.metric].label}, at today's in-stock prices.
	</p>

	<ul class="mt-3 space-y-1.5 text-sm text-text">
		{#each matchup.lines as line (line.metric)}
			<li data-testid="matchup-line">
				{#if line.direction === 'cheaper'}
					<strong class="font-semibold">{p.name} is <span class="num">{line.pct}%</span> cheaper per frame</strong>
					than {r.name} at {METRICS[line.metric].label}
				{:else if line.direction === 'dearer'}
					<strong class="font-semibold">{p.name} costs <span class="num">{line.pct}%</span> more per frame</strong>
					than {r.name} at {METRICS[line.metric].label}
				{:else}
					<strong class="font-semibold">About the same cost per frame</strong>
					as {r.name} at {METRICS[line.metric].label}
				{/if}
			</li>
		{/each}
	</ul>

	<dl class="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
		{@render sideFigures(p)}
		{@render sideFigures(r)}
	</dl>

	<div class="mt-3 flex flex-col gap-1.5 text-xs text-text-muted sm:flex-row sm:items-center sm:justify-between">
		<a
			href="/compare?ids={p.id},{r.id}"
			class="inline-flex items-center gap-1 font-medium text-accent hover:underline"
			data-testid="matchup-compare"
		>
			Compare side by side <ArrowRight class="size-3.5" aria-hidden="true" />
		</a>
		<span>
			Performance:
			{#each sources as metric, i (metric)}{#if i > 0};{' '}{/if}<a
					href={METRICS[metric].source_url}
					class="text-text-muted underline underline-offset-2 hover:text-text">{sourceNote(metric)}</a
				>{/each}
		</span>
	</div>
</section>
