<script lang="ts">
	import type { FacetOption } from '$lib/offers';

	let {
		label,
		options,
		selected,
		allCount,
		onSelect
	}: {
		label: string;
		options: FacetOption[];
		selected: string | null;
		allCount: number;
		onSelect: (value: string | null) => void;
	} = $props();

	// A row offering one value is not a choice — it is clutter. Hide it.
	const useful = $derived(options.length > 1);

	function chipClass(active: boolean): string {
		return active
			? 'rounded-full border border-accent bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent'
			: 'rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-text-muted hover:bg-surface-hover hover:text-text';
	}
</script>

{#if useful}
	<div class="flex flex-wrap items-center gap-1.5">
		<span class="w-16 shrink-0 text-xs text-text-muted">{label}</span>
		<button
			type="button"
			aria-pressed={selected === null}
			onclick={() => onSelect(null)}
			class={chipClass(selected === null)}
		>
			All <span class="num">{allCount}</span>
		</button>
		{#each options as opt (opt.value)}
			<button
				type="button"
				aria-pressed={selected === opt.value}
				onclick={() => onSelect(opt.value)}
				class={chipClass(selected === opt.value)}
			>
				{opt.label} <span class="num">{opt.count}</span>
			</button>
		{/each}
	</div>
{/if}
