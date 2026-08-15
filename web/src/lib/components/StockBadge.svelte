<script lang="ts">
	import { stockLabel } from '$lib/formats';
	import Badge from './Badge.svelte';
	import type { StockStatus } from '$lib/types';

	let { stock }: { stock: StockStatus } = $props();

	const tone = $derived(
		stock === 'in_stock' ? 'accent' : stock === 'out_of_stock' ? 'neutral' : 'flat'
	);
</script>

<Badge tone={tone} label={stockLabel(stock)} />