<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import BrandIcon from '$lib/components/BrandIcon.svelte';
	import PageHead from '$lib/components/PageHead.svelte';
	import { buildCompareRows } from '$lib/compareRows';
	import type { CompareEntry } from '$lib/server/repos';

	let { data }: { data: { entries: CompareEntry[] } } = $props();

	const entries = $derived(data.entries);

	const rows = $derived(
		buildCompareRows(entries).map((d) => ({ label: d.label, values: entries.map(d.value) }))
	);
</script>

<PageHead title="Compare" description="Specs and current best AU prices side by side." />

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold text-text">Compare</h1>
		<p class="mt-1 text-sm text-text-muted">
			Specs and current best prices side by side. Share the URL to keep a comparison handy.
		</p>
	</div>

	{#if entries.length === 0}
		<div class="rounded-md border border-border bg-surface px-4 py-10 text-center">
			<p class="text-sm text-text">Nothing selected to compare yet.</p>
			<p class="mt-1 text-sm text-text-muted">
				Pick 2–4 products in the same category on the
				<a href="/products" class="text-accent no-underline hover:underline">Products</a>
				page — tick the compare box on each card, then use the Compare bar.
			</p>
		</div>
	{:else}
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
								<BrandIcon brand={entry.product.brand} size={14} />
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
									<span class="text-text-muted">N/A</span>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		</div>
	{/if}
</div>
