<script lang="ts">
	let { label, value }: { label: string; value: string } = $props();
</script>

<span
	class="inline-flex min-h-7 items-center gap-1.5 rounded-lg border border-border-card bg-surface-2 px-2.5 py-1 text-body"
>
	<span class="text-meta text-text-muted">{label}</span>
	<span class="num font-medium text-text">{value}</span>
</span>