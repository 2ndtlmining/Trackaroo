<script lang="ts">
	import { formatAud } from '$lib/formats';
	import { RANGE_SEGMENTS, SEGMENT_TONE, filledSegment } from '$lib/rangeBar';

	let {
		low,
		high,
		current,
		position,
		points = 0,
		size = 'full'
	}: {
		low: number;
		high: number;
		current: number;
		position: number | null;
		// Days on which a cheapest-in-stock price was recorded. Distinguishes
		// "we've only seen one price" from "the price has held steady".
		points?: number;
		// 'compact' is the 96px catalogue-row form with an 11px label.
		size?: 'full' | 'compact';
	} = $props();

	const filled = $derived(filledSegment(position));
	const compact = $derived(size === 'compact');
	const label = $derived(
		`Today's cheapest price ${formatAud(current)}. Over ${points} days the cheapest price per day ` +
			`ranged from ${formatAud(low)} to ${formatAud(high)}.`
	);
</script>

{#if filled === null}
	<!--
		A flat range is not the same as a single reading. Claiming "only one
		price recorded" for a product tracked for weeks at a steady price is
		simply false, and that is what this panel used to say.
	-->
	{#if compact && points > 1}
		<p class="whitespace-nowrap text-[11px] text-text-muted">
			Steady at <span class="num">{formatAud(low)}</span>
		</p>
	{:else if compact}
		<p class="whitespace-nowrap text-[11px] text-text-muted">
			1 price: <span class="num">{formatAud(low)}</span>
		</p>
	{:else if points > 1}
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
	<div class={compact ? 'w-24' : 'max-w-md'}>
		<!--
			Both ends are the cheapest in-stock price on some day: the best and the
			worst day to have bought (U4). Not the cheapest and dearest listing on
			the shelf.
		-->
		{#if !compact}
			<div class="text-meta flex justify-between uppercase tracking-wide text-text-muted">
				<span>Lowest day</span>
				<span>Highest day</span>
			</div>
		{/if}
		<div role="img" aria-label={label} class="flex gap-0.5 {compact ? '' : 'mt-1'}">
			{#each { length: RANGE_SEGMENTS } as _, i (i)}
				<span
					data-segment={i}
					data-filled={i === filled ? 'true' : undefined}
					class="h-1.5 flex-1 rounded-full {i === filled ? SEGMENT_TONE[i] : 'bg-border-strong'}"
				></span>
			{/each}
		</div>
		{#if compact}
			<div class="mt-1 flex justify-between text-[11px] leading-none text-text-muted">
				<span class="num">{formatAud(low)}</span>
				<span class="num">{formatAud(high)}</span>
			</div>
		{:else}
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
		{/if}
	</div>
{/if}
