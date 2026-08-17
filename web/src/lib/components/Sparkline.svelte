<script lang="ts">
	import { formatAud } from '$lib/formats';
	import type { PricePoint } from '$lib/server/repos';

	let { points }: { points: PricePoint[] | undefined } = $props();

	const values = $derived((points ?? []).map((p) => p.price));
	const ready = $derived(values.length >= 2);

	const direction = $derived.by(() => {
		if (!ready) return 'none' as const;
		const first = values[0];
		const last = values[values.length - 1];
		if (last > first) return 'up' as const;
		if (last < first) return 'down' as const;
		return 'flat' as const;
	});

	const strokeClass = $derived(
		direction === 'up' ? 'stroke-up' : direction === 'down' ? 'stroke-down' : 'stroke-text-muted'
	);

	const polylinePoints = $derived.by(() => {
		if (!ready) return '';
		const min = Math.min(...values);
		const max = Math.max(...values);
		const span = max - min || 1;
		const width = 56;
		const height = 24;
		return values
			.map((v, i) => {
				const x = (i / (values.length - 1)) * width;
				const y = height - 2 - ((v - min) / span) * (height - 4);
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	});

	const title = $derived(
		ready
			? `${formatAud(values[0])} → ${formatAud(values[values.length - 1])}`
			: 'Not enough history'
	);
</script>

{#if ready}
	<svg
		viewBox="0 0 56 24"
		class="h-6 w-14 {strokeClass}"
		fill="none"
		stroke-width="1.8"
		stroke-linecap="round"
		stroke-linejoin="round"
		role="img"
		aria-label={title}
	>
		<title>{title}</title>
		<polyline points={polylinePoints} />
	</svg>
{:else}
	<span class="text-text-muted" title="Not enough history" aria-label="Not enough history">—</span>
{/if}