<script lang="ts">
	import { formatAud, formatDate, formatUsd } from '$lib/formats';
	import Badge from '$lib/components/Badge.svelte';
	import type { CompareEntry } from '$lib/server/repos';
	import type { Retailer } from '$lib/types';

	let { data }: { data: { entries: CompareEntry[] } } = $props();

	const entries = $derived(data.entries);

	const retailers = $derived(
		[...new Set<Retailer>(entries.flatMap((e) => e.prices.map((p) => p.retailer)))].sort(
			(a, b) => a.localeCompare(b)
		)
	);

	function clock(mhz: number | null): string | null {
		return mhz === null ? null : `${(mhz / 1000).toFixed(1)} GHz`;
	}

	type RowDef = (e: CompareEntry) => string | null;

	const rowDefs = $derived<{ label: string; value: RowDef }[]>([
		...retailers.map((r) => ({
			label: `Best price — ${r}`,
			value: (e: CompareEntry) => {
				const p = e.prices.find((x) => x.retailer === r);
				return p?.price !== undefined && p.price !== null ? formatAud(p.price) : null;
			}
		})),
		{
			label: 'Cheapest in stock',
			value: (e: CompareEntry) =>
				e.cheapestInStock ? `${formatAud(e.cheapestInStock.price)} · ${e.cheapestInStock.retailer}` : null
		},
		{
			label: 'Launch MSRP (USD)',
			value: (e: CompareEntry) => (e.spec?.launch_msrp_usd ? formatUsd(e.spec.launch_msrp_usd) : null)
		},
		{
			label: 'Launch date',
			value: (e: CompareEntry) => (e.spec?.launch_date ? formatDate(e.spec.launch_date) : null)
		},
		{
			label: 'Architecture',
			value: (e: CompareEntry) => e.spec?.architecture ?? null
		},
		{
			label: 'Generation',
			value: (e: CompareEntry) => e.spec?.generation ?? null
		},
		{
			label: 'VRAM',
			value: (e: CompareEntry) => (e.spec?.vram_gb ? `${e.spec.vram_gb}GB` : null)
		},
		{
			label: 'Memory type',
			value: (e: CompareEntry) => e.spec?.memory_type ?? null
		},
		{
			label: 'Memory bus',
			value: (e: CompareEntry) =>
				e.spec?.memory_bus_width_bit ? `${e.spec.memory_bus_width_bit}-bit` : null
		},
		{
			label: 'TDP',
			value: (e: CompareEntry) => (e.spec?.tdp_watts ? `${e.spec.tdp_watts} W` : null)
		},
		{
			label: 'Cores / shaders',
			value: (e: CompareEntry) =>
				e.spec?.core_count ? e.spec.core_count.toLocaleString() : null
		},
		{
			label: 'Threads',
			value: (e: CompareEntry) => (e.spec?.thread_count ? String(e.spec.thread_count) : null)
		},
		{
			label: 'Base clock',
			value: (e: CompareEntry) => clock(e.spec?.base_clock_mhz ?? null)
		},
		{
			label: 'Boost clock',
			value: (e: CompareEntry) => clock(e.spec?.boost_clock_mhz ?? null)
		},
		{
			label: 'Socket',
			value: (e: CompareEntry) => e.spec?.socket ?? null
		},
		{
			label: 'L3 cache',
			value: (e: CompareEntry) => (e.spec?.cache_l3_mb ? `${e.spec.cache_l3_mb} MB` : null)
		}
	]);

	const rows = $derived(rowDefs.map((d) => ({ label: d.label, values: entries.map(d.value) })));
</script>

<svelte:head>
	<title>Trackaroo — Compare</title>
</svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Compare</h1>
		<p class="mt-1 text-sm text-text-muted">
			Specs and current best prices side by side. Share the URL to keep a comparison handy.
		</p>
	</div>

	<div class="overflow-x-auto rounded-md border border-border">
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-border bg-surface">
					<th
						class="w-40 border-r border-border px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-muted"
					>
						Field
					</th>
					{#each entries as entry}
						<th class="px-3 py-3 text-left align-top">
							<a
								href="/product/{entry.product.id}"
								class="block font-semibold text-text no-underline hover:text-accent"
							>
								{entry.product.model}
							</a>
							<span class="mt-1 flex items-center gap-1.5 text-xs text-text-muted">
								{entry.product.brand}
								<Badge tone="neutral" label={entry.product.category.toUpperCase()} />
							</span>
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as row}
					<tr class="border-b border-border last:border-b-0">
						<th
							class="border-r border-border bg-surface px-3 py-2 text-left text-xs font-medium text-text-muted"
						>
							{row.label}
						</th>
						{#each row.values as value}
							<td class="px-3 py-2 text-text">
								{#if value !== null}
									{value}
								{:else}
									<span class="text-text-muted/60">N/A</span>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>