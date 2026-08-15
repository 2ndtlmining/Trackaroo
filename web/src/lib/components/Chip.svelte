<script lang="ts">
	let { label, value }: { label: string; value: string } = $props();
</script>

<span
	class="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-sm"
>
	<span class="text-xs text-text-muted">{label}</span>
	<span class="num font-medium text-text">{value}</span>
</span>