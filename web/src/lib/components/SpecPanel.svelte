<script lang="ts">
	import { formatDate, formatRelative, formatUsd } from '$lib/formats';
	import type { SpecRow } from '$lib/server/db';

	let { spec }: { spec: SpecRow } = $props();

	const isGpu = $derived(spec.category === 'gpu');

	const generation = $derived(
		[spec.generation, spec.architecture].filter((v) => v !== null).join(' — ') || null
	);

	const vram = $derived(
		spec.vram_gb !== null
			? `${spec.vram_gb}GB${spec.memory_type ? ` ${spec.memory_type}` : ''}`
			: null
	);

	const coresThreads = $derived(
		spec.core_count !== null
			? spec.thread_count !== null
				? `${spec.core_count} cores / ${spec.thread_count} threads`
				: `${spec.core_count} cores`
			: null
	);

	function ghzNum(mhz: number): string {
		const value = mhz / 1000;
		return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
	}

	const clocks = $derived(
		spec.base_clock_mhz !== null || spec.boost_clock_mhz !== null
			? [spec.base_clock_mhz, spec.boost_clock_mhz]
					.filter((v): v is number => v !== null)
					.map(ghzNum)
					.join(' / ') + ' GHz'
			: null
	);

	const msrp = $derived(spec.launch_msrp_usd !== null ? formatUsd(spec.launch_msrp_usd) : null);
	const tdp = $derived(spec.tdp_watts !== null ? `${spec.tdp_watts} W` : null);
	const shaders = $derived(
		spec.core_count !== null ? new Intl.NumberFormat('en-AU').format(spec.core_count) : null
	);
	const busWidth = $derived(
		spec.memory_bus_width_bit !== null ? `${spec.memory_bus_width_bit}-bit` : null
	);
	const cache = $derived(spec.cache_l3_mb !== null ? `${spec.cache_l3_mb} MB` : null);
</script>

<div class="overflow-hidden rounded-md border border-border">
	<h2 class="border-b border-border bg-surface px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
		Specs
	</h2>

	<div class="divide-y divide-border text-sm">
		{#if generation}
			<div class="flex items-center justify-between gap-3 px-3 py-2">
				<span class="text-text-muted">Generation</span>
				<span class="font-medium text-text">{generation}</span>
			</div>
		{/if}
		{#if isGpu}
			{#if vram}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">VRAM</span>
					<span class="num font-medium text-text">{vram}</span>
				</div>
			{/if}
			{#if msrp}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Launch MSRP</span>
					<span class="num font-medium text-text">{msrp}</span>
				</div>
			{/if}
			{#if shaders}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Shaders</span>
					<span class="num font-medium text-text">{shaders}</span>
				</div>
			{/if}
		{:else}
			{#if coresThreads}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Cores / threads</span>
					<span class="num font-medium text-text">{coresThreads}</span>
				</div>
			{/if}
			{#if msrp}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Launch MSRP</span>
					<span class="num font-medium text-text">{msrp}</span>
				</div>
			{/if}
			{#if clocks}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Base / boost</span>
					<span class="num font-medium text-text">{clocks}</span>
				</div>
			{/if}
		{/if}
		{#if tdp}
			<div class="flex items-center justify-between gap-3 px-3 py-2">
				<span class="text-text-muted">TDP</span>
				<span class="num font-medium text-text">{tdp}</span>
			</div>
		{/if}
	</div>

	<details class="border-t border-border">
		<summary
			class="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted hover:bg-surface"
		>
			Show full specs
		</summary>
		<div class="divide-y divide-border text-sm">
			{#if isGpu && busWidth}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Memory bus</span>
					<span class="num font-medium text-text">{busWidth}</span>
				</div>
			{/if}
			{#if !isGpu && spec.socket}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Socket</span>
					<span class="font-medium text-text">{spec.socket}</span>
				</div>
			{/if}
			{#if cache}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Cache</span>
					<span class="num font-medium text-text">{cache}</span>
				</div>
			{/if}
			{#if spec.launch_date}
				<div class="flex items-center justify-between gap-3 px-3 py-2">
					<span class="text-text-muted">Launched</span>
					<span class="num font-medium text-text">{formatDate(spec.launch_date)}</span>
				</div>
			{/if}
			<div class="flex items-center justify-between gap-3 px-3 py-2">
				<span class="text-text-muted">Source</span>
				<span class="font-medium text-text">
					{spec.source} · synced {formatRelative(spec.last_synced_at)}
				</span>
			</div>
		</div>
	</details>
</div>
