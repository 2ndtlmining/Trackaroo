<script lang="ts">
	import { formatAud } from '$lib/formats';

	let {
		low,
		high,
		current,
		position
	}: { low: number; high: number; current: number; position: number | null } = $props();

	const pct = $derived(position === null ? 0 : Math.round(position * 100));
	const label = $derived(
		`Currently ${formatAud(current)}. All-time low ${formatAud(low)}, all-time high ${formatAud(high)}.`
	);
</script>

{#if position === null}
	<p class="text-xs text-text-muted">
		Only one price recorded so far: <span class="num">{formatAud(current)}</span>
	</p>
{:else}
	<div class="max-w-md">
		<div class="flex justify-between text-[10px] uppercase tracking-wide text-text-muted">
			<span>All-time low</span>
			<span>All-time high</span>
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
	</div>
{/if}
