<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
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

	// The pressed chip differs by more than colour (WCAG 1.4.1): a check mark
	// and a heavier weight, as well as the accent fill.
	function chipClass(active: boolean): string {
		const base = 'inline-flex min-h-8 items-center gap-1 rounded-full border px-3 text-body';
		return active
			? `${base} border-accent bg-accent-soft font-semibold text-accent`
			: `${base} border-border-input bg-surface font-normal text-text hover:bg-surface-hover`;
	}
</script>

{#if useful}
	<div class="flex flex-wrap items-center gap-1.5">
		<span class="w-16 shrink-0 text-meta text-text-muted">{label}</span>
		<button
			type="button"
			aria-pressed={selected === null}
			onclick={() => onSelect(null)}
			class={chipClass(selected === null)}
		>
			{#if selected === null}<Check size={14} aria-hidden="true" />{/if}
			All <span class="num">{allCount}</span>
		</button>
		{#each options as opt (opt.value)}
			<button
				type="button"
				aria-pressed={selected === opt.value}
				onclick={() => onSelect(opt.value)}
				class={chipClass(selected === opt.value)}
			>
				{#if selected === opt.value}<Check size={14} aria-hidden="true" />{/if}
				{opt.label} <span class="num">{opt.count}</span>
			</button>
		{/each}
	</div>
{/if}
