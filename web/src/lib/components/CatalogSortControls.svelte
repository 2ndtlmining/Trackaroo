<script lang="ts">
	// The Sort and Order selects of CatalogFilters (#61). The column headers
	// sort too; these are for a phone (the header row is hidden there) and for
	// the no-JS form.
	import { DEFAULT_DIR, type CatalogSort, type CatalogView, type SortDir } from '$lib/catalogView';
	import type { Category } from '$lib/types';

	let {
		view,
		category,
		control,
		legendClass,
		set
	}: {
		view: CatalogView;
		category: Category;
		control: string;
		legendClass: string;
		set: (patch: Partial<CatalogView>) => void;
	} = $props();

	const SORT_LABELS = $derived<Record<CatalogSort, string>>({
		price: 'Price',
		name: 'Model',
		spec: category === 'cpu' ? 'Cores' : 'VRAM',
		released: 'Released',
		listings: 'Listings',
		msrp: 'vs MSRP',
		value: 'Perf / A$1k'
	});

	function onSort(value: string) {
		const sort = value ? (value as CatalogSort) : null;
		set({ sort, dir: sort ? DEFAULT_DIR[sort] : 'asc' });
	}
</script>

<div class="flex items-end gap-2">
	<label class="flex flex-col text-sm text-text">
		<span class={legendClass}>Sort</span>
		<select
			name="sort"
			class={control}
			value={view.sort ?? ''}
			onchange={(e) => onSort((e.target as HTMLSelectElement).value)}
		>
			<option value="">By series</option>
			{#each Object.entries(SORT_LABELS) as [value, label] (value)}
				<option {value}>{label}</option>
			{/each}
		</select>
	</label>
	<label class="flex flex-col text-sm text-text">
		<span class={legendClass}>Order</span>
		<select
			name="dir"
			class={control}
			value={view.dir}
			disabled={view.sort === null}
			onchange={(e) => set({ dir: (e.target as HTMLSelectElement).value as SortDir })}
		>
			<option value="asc">Ascending</option>
			<option value="desc">Descending</option>
		</select>
	</label>
</div>
