<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import BrandIcon from '$lib/components/BrandIcon.svelte';
	import PageHead from '$lib/components/PageHead.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { bestIndexes, buildCompareRows } from '$lib/compareRows';
	import { buildDisplayNames, displayName } from '$lib/displayName';
	import type { CompareEntry, ProductIndexEntry } from '$lib/models';
	import type { Category } from '$lib/types';

	// productIndex arrives from the root layout's load (merged into page data).
	let {
		data
	}: {
		data: {
			entries: CompareEntry[];
			pickerCategory: Category;
			pickerError: string | null;
			productIndex: ProductIndexEntry[];
		};
	} = $props();

	const entries = $derived(data.entries);
	const rows = $derived(
		buildCompareRows(entries).map((d) => ({
			label: d.label,
			mono: d.mono === true || d.numeric !== undefined,
			values: entries.map(d.value),
			best: bestIndexes(d, entries)
		}))
	);
	// Only products with price history are worth comparing; the index already
	// knows which, so the picker costs no query.
	const options = $derived(
		data.productIndex.filter((p) => p.category === data.pickerCategory && p.snapshotCount > 0)
	);
	// The base card carries its VRAM where a memory sibling exists (display only).
	const names = $derived(buildDisplayNames(data.productIndex));
	const categoryLabel = $derived(data.pickerCategory === 'cpu' ? 'CPUs' : 'GPUs');
</script>

<PageHead title="Compare" description="Specs and current best AU prices side by side." />

<div class="space-y-6">
	<PageHeader
		title="Compare"
		subtitle="Specs and current best prices side by side. Share the URL to keep a comparison handy."
	/>

	{#if entries.length === 0}
		<section class="rounded-xl border border-border-card bg-surface shadow-card p-4" aria-labelledby="pick-heading">
			<h2 id="pick-heading" class="text-sm font-semibold text-text">Nothing selected to compare yet.</h2>
			<p class="mt-1 text-sm text-text-muted">
				Pick two below, or tick <span class="font-medium text-text">Compare</span> on up to four rows of
				the <a href="/products?category={data.pickerCategory}" class="text-accent">{categoryLabel} list</a>.
			</p>

			<div class="mt-3 flex gap-1 text-sm" role="group" aria-label="Category">
				{#each [{ value: 'gpu', label: 'GPUs' }, { value: 'cpu', label: 'CPUs' }] as c (c.value)}
					<a
						href="/compare?category={c.value}"
						aria-current={data.pickerCategory === c.value ? 'page' : undefined}
						class="rounded-md px-2.5 py-1 no-underline {data.pickerCategory === c.value
							? 'bg-surface-hover font-medium text-text'
							: 'text-text-muted hover:text-text'}">{c.label}</a
					>
				{/each}
			</div>

			<form method="GET" action="/compare" class="mt-3 flex flex-wrap items-end gap-2">
				{#each [1, 2] as n (n)}
					<label class="flex min-w-0 flex-1 basis-56 flex-col gap-1 text-xs text-text-muted">
						Product {n}
						<select
							name="id"
							required
							class="h-9 rounded-md border border-border-input bg-surface px-2 text-sm text-text"
						>
							<option value="">Choose a {data.pickerCategory === 'cpu' ? 'CPU' : 'GPU'}…</option>
							{#each options as p (p.id)}
								<option value={p.id}>{displayName(names, p.id, p.model)}</option>
							{/each}
						</select>
					</label>
				{/each}
				<button
					type="submit"
					class="h-9 rounded-md border border-border-input bg-surface px-3 text-sm text-text hover:bg-surface-hover"
				>
					Compare
				</button>
			</form>
			{#if data.pickerError}
				<p role="alert" class="mt-2 text-sm text-danger">{data.pickerError}</p>
			{/if}
		</section>
	{:else}
		<div class="overflow-x-auto rounded-xl border border-border-card bg-surface shadow-card">
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
								{displayName(names, entry.product.id, entry.product.model)}
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
						{#each row.values as value, i}
							<td class="px-3 py-2 text-text {row.mono ? 'num' : ''}">
								{#if value !== null && row.best.has(i)}
									<span class="font-semibold">{value}</span>
									<span
										class="ml-1.5 rounded-sm bg-accent-soft px-1.5 py-0.5 font-sans text-xs font-medium text-accent"
										aria-hidden="true">Best</span
									>
									<span class="sr-only">(best value in this row)</span>
								{:else if value !== null}
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
