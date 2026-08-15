<script lang="ts">
	import Badge from './Badge.svelte';
	import type { ChangeDirection } from '$lib/types';

	let { direction, label }: { direction: ChangeDirection; label: string } = $props();

	const tone = $derived(direction === 'insufficient' ? 'stale' : direction);
</script>

<Badge tone={tone} {label} />
