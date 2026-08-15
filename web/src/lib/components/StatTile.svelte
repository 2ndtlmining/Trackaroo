<script lang="ts">
	let { label, value, sub }: { label: string; value: string; sub?: string } = $props();
</script>

<div class="rounded-md border border-border bg-surface px-4 py-3">
	<div class="text-xs text-text-muted">{label}</div>
	<div class="num mt-1 text-lg font-semibold text-text">{value}</div>
	{#if sub}
		<div class="mt-0.5 text-xs text-text-muted">{sub}</div>
	{/if}
</div>
