<script lang="ts" generics="T extends string">
	// One segmented control instead of nine hand-copied buttons (#5 item 5).
	// Toggle buttons with aria-pressed: each option is announced as pressed or
	// not, and the group label says what the options choose.
	let {
		label,
		options,
		value,
		onChange
	}: {
		label: string;
		options: readonly { value: T; label: string }[];
		value: T;
		onChange: (value: T) => void;
	} = $props();
</script>

<div role="group" aria-label={label} class="flex items-center gap-1 rounded-lg border border-border-card bg-surface-2 p-1">
	{#each options as opt (opt.value)}
		<button
			type="button"
			aria-pressed={opt.value === value}
			onclick={() => onChange(opt.value)}
			class="min-h-7 rounded-md px-2.5 py-1 text-body {opt.value === value
				? 'bg-surface-3 font-medium text-text shadow-card'
				: 'text-text-muted hover:text-text'}"
		>
			{opt.label}
		</button>
	{/each}
</div>
