<script lang="ts">
	export type BadgeTone =
		| 'up'
		| 'down'
		| 'flat'
		| 'stale'
		| 'accent'
		| 'neutral'
		| 'success'
		| 'warning'
		| 'danger';

	let { tone = 'neutral', label }: { tone?: BadgeTone; label: string } = $props();

	const dotClass: Record<BadgeTone, string> = {
		up: 'bg-up',
		down: 'bg-down',
		flat: 'bg-flat',
		stale: 'bg-stale',
		accent: 'bg-accent',
		neutral: 'bg-text-muted',
		success: 'bg-success',
		warning: 'bg-warning',
		danger: 'bg-danger'
	};

	// --stale is too faint for text (2.62:1 in light, #24); it stays on the dot
	// only, and the words carry the meaning.
	const textClass: Record<BadgeTone, string> = {
		up: 'text-up',
		down: 'text-down',
		flat: 'text-text-muted',
		stale: 'text-text-muted',
		accent: 'text-accent',
		neutral: 'text-text-muted',
		success: 'text-success',
		warning: 'text-warning',
		danger: 'text-danger'
	};
</script>

<span
	class="inline-flex min-h-6 items-center gap-1.5 whitespace-nowrap rounded-md border border-border-card bg-surface px-2 py-0.5 text-meta font-medium"
>
	<span class="h-1.5 w-1.5 shrink-0 rounded-full {dotClass[tone]}"></span>
	<span class="{textClass[tone]}">{label}</span>
</span>
