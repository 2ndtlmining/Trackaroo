<script lang="ts">
	import { formatAud } from '$lib/formats';

	let {
		low,
		high,
		current,
		position,
		points = 0
	}: {
		low: number;
		high: number;
		current: number;
		position: number | null;
		// Days on which a cheapest-in-stock price was recorded. Distinguishes
		// "we've only seen one price" from "the price has held steady".
		points?: number;
	} = $props();

	const pct = $derived(position === null ? 0 : Math.round(position * 100));
	const label = $derived(
		`Today's cheapest price ${formatAud(current)}. Over ${points} days the cheapest price per day ` +
			`ranged from ${formatAud(low)} to ${formatAud(high)}.`
	);
</script>

{#if position === null}
	<!--
		A flat range is not the same as a single reading. Claiming "only one
		price recorded" for a product tracked for weeks at a steady price is
		simply false, and that is what this panel used to say.
	-->
	{#if points > 1}
		<p class="text-xs text-text-muted">
			Price has held at <span class="num font-medium text-text">{formatAud(current)}</span>
			for all
			<span class="num">{points}</span> days tracked.
		</p>
	{:else}
		<p class="text-xs text-text-muted">
			Only one price recorded so far: <span class="num">{formatAud(current)}</span>
		</p>
	{/if}
{:else}
	<div class="max-w-md">
		<!--
			Both ends are the cheapest in-stock price on some day: the best and the
			worst day to have bought (U4). Not the cheapest and dearest listing on
			the shelf.
		-->
		<div class="flex justify-between text-[10px] uppercase tracking-wide text-text-muted">
			<span>Lowest day</span>
			<span>Highest day</span>
		</div>
		<div role="img" aria-label={label} class="relative mt-1 h-1.5 rounded-full bg-surface-hover">
			<span
				class="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent"
				style="left: {pct}%"
			></span>
		</div>
		<div class="mt-1 flex justify-between text-xs">
			<span class="num text-text-muted">{formatAud(low)}</span>
			<span class="num font-medium text-text">{formatAud(current)}</span>
			<span class="num text-text-muted">{formatAud(high)}</span>
		</div>
		<!--
			Says what the range actually is. Both ends are the cheapest available
			price on a given day, so "dearest" means the worst day to have bought,
			not the most expensive listing on the shelf.
		-->
		<p class="mt-1 text-[11px] text-text-muted">
			Range of the cheapest price across <span class="num">{points}</span> days tracked
		</p>
	</div>
{/if}
