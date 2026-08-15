<script lang="ts">
	export type BadgeTone = 'up' | 'down' | 'flat' | 'stale' | 'accent' | 'neutral';

	let { tone = 'neutral', label }: { tone?: BadgeTone; label: string } = $props();

	const dotClass: Record<BadgeTone, string> = {
		up: 'bg-up',
		down: 'bg-down',
		flat: 'bg-flat',
		stale: 'bg-stale',
		accent: 'bg-accent',
		neutral: 'bg-text-muted'
	};

	const textClass: Record<BadgeTone, string> = {
		up: 'text-up',
		down: 'text-down',
		flat: 'text-text-muted',
		stale: 'text-stale',
		accent: 'text-accent',
		neutral: 'text-text-muted'
	};
</script>

<span
	class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-surface px-2 py-0.5 text-xs"
>
	<span class="h-1.5 w-1.5 shrink-0 rounded-full {dotClass[tone]}"></span>
	<span class="{textClass[tone]}">{label}</span>
</span>
