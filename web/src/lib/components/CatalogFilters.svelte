<script lang="ts">
	import { onMount } from 'svelte';
	import { formatAud } from '$lib/formats';
	import {
		ACTIVE_RETAILER_OPTIONS,
		DEFAULT_DIR,
		parseCatalogView,
		type CatalogSort,
		type CatalogView,
		type SortDir
	} from '$lib/catalogView';
	import type { Category, GenerationTier, Retailer } from '$lib/types';

	// The catalogue's controls (#23, spec §4). One set of controls in one
	// native <dialog>: above md it is forced open inline by CSS; on a phone it
	// is a modal opened by the "Filters (N active)" button. Rendering them once
	// keeps one id, one label and one tab stop per control.
	//
	// Without JS this is a plain GET form. With JS every control writes the
	// view straight back through onChange (the page syncs the URL with
	// replaceState); the form's submit is only a fallback.
	let {
		view,
		category,
		brands,
		gens,
		resultCount,
		activeCount,
		clearHref,
		hidden,
		onChange,
		onInStock
	}: {
		view: CatalogView;
		category: Category;
		// Only the brands present in this category.
		brands: string[];
		gens: { value: GenerationTier; label: string }[];
		resultCount: number;
		activeCount: number;
		clearHref: string;
		// Page state the GET form must carry along (category, q, unlisted).
		hidden: Record<string, string>;
		onChange: (next: CatalogView) => void;
		onInStock: (checked: boolean) => void;
	} = $props();

	const PRESETS: { label: string; value: number | null }[] = [
		{ label: formatAud(500), value: 500 },
		{ label: formatAud(1000), value: 1000 },
		{ label: formatAud(2000), value: 2000 },
		{ label: 'Any', value: null }
	];

	const SORT_LABELS = $derived<Record<CatalogSort, string>>({
		price: 'Price',
		name: 'Model',
		spec: category === 'cpu' ? 'Cores' : 'VRAM',
		released: 'Released',
		listings: 'Listings'
	});

	// The submit button exists for the no-JS form only. It stays in the DOM
	// (hidden) once hydrated because it is the form's default button: Enter in
	// a field "clicks" it, and the submit handler below turns that into a
	// no-op instead of letting a $500 preset be the button that gets clicked.
	let hydrated = $state(false);
	onMount(() => {
		hydrated = true;
	});

	let dialog: HTMLDialogElement | undefined = $state();
	let opener: HTMLButtonElement | undefined = $state();

	function openDialog() {
		dialog?.showModal();
	}

	function closeDialog() {
		dialog?.close();
	}

	// Escape, "Show N results" and close() all land here.
	function onDialogClose() {
		opener?.focus();
	}

	function set(patch: Partial<CatalogView>) {
		onChange({ ...view, ...patch });
	}

	// The number box: typed text is local and applied after a ~300 ms pause,
	// so the URL is not rewritten per keystroke. The parser validates it, so
	// "0" or "abc" means no limit, exactly as it would in a link.
	// A writable derived: typing overrides it locally, and any change to
	// view.max (a preset, Clear, Back) resets it to the applied value.
	let maxText = $derived(view.max === null ? '' : String(view.max));
	let maxTimer: ReturnType<typeof setTimeout> | undefined;
	// A pending keystroke must not apply after the page has moved on.
	$effect(() => () => clearTimeout(maxTimer));

	function parseMax(text: string): number | null {
		return parseCatalogView(new URLSearchParams({ max: text.trim() })).max;
	}

	function commitMax() {
		clearTimeout(maxTimer);
		maxTimer = undefined;
		const next = parseMax(maxText);
		if (next !== view.max) set({ max: next });
	}

	function onMaxInput(event: Event) {
		maxText = (event.target as HTMLInputElement).value;
		clearTimeout(maxTimer);
		maxTimer = setTimeout(commitMax, 300);
	}

	function preset(event: MouseEvent, value: number | null) {
		event.preventDefault();
		clearTimeout(maxTimer);
		maxText = value === null ? '' : String(value);
		set({ max: value });
	}

	function onSubmit(event: SubmitEvent) {
		event.preventDefault();
		if (maxTimer !== undefined) commitMax();
	}

	function toggle<T extends string>(list: T[], value: T, on: boolean): T[] {
		return on ? [...list.filter((v) => v !== value), value] : list.filter((v) => v !== value);
	}

	function onSort(value: string) {
		const sort = value ? (value as CatalogSort) : null;
		set({ sort, dir: sort ? DEFAULT_DIR[sort] : 'asc' });
	}

	const control =
		'h-9 rounded-md border border-border-input bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none';
	const chip =
		'h-9 rounded-md border border-border bg-surface px-2.5 text-sm text-text-muted hover:text-text aria-pressed:border-accent aria-pressed:bg-accent-soft aria-pressed:font-medium aria-pressed:text-accent';
	const legend = 'mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted';
</script>

<button
	type="button"
	bind:this={opener}
	onclick={openDialog}
	class="h-9 shrink-0 rounded-md border border-border bg-surface px-2.5 text-sm text-text md:hidden"
>
	Filters ({activeCount} active)
</button>

<dialog
	bind:this={dialog}
	onclose={onDialogClose}
	aria-label="Filters"
	class="m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border border-border bg-surface p-4 text-text backdrop:bg-bg/80 md:static md:m-0 md:block md:w-full md:max-w-none md:border-0 md:bg-transparent md:p-0"
>
	<form
		method="get"
		action="/products"
		onsubmit={onSubmit}
		class="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-end md:gap-x-4"
	>
		<!-- First in the tree so it is the default button (see `hydrated`);
		     shown last. -->
		<button
			type="submit"
			class="order-last h-9 self-start rounded-md border border-border bg-surface px-3 text-sm text-text md:self-end"
			class:hidden={hydrated}
		>
			Apply filters
		</button>
		{#each Object.entries(hidden) as [name, value] (name)}
			<input type="hidden" {name} {value} />
		{/each}

		<fieldset>
			<legend class={legend}>Max price</legend>
			<div class="flex flex-wrap items-center gap-1.5">
				<!-- Submit buttons named "max" so a preset works as a plain GET
				     form; they precede the number box, so the clicked preset's
				     value is the first "max" the parser reads. -->
				{#each PRESETS as p (p.label)}
					<button
						type="submit"
						name="max"
						value={p.value ?? ''}
						aria-pressed={view.max === p.value}
						onclick={(e) => preset(e, p.value)}
						class={chip}
					>
						{p.label}
					</button>
				{/each}
				<input
					type="number"
					name="max"
					min="1"
					step="1"
					inputmode="numeric"
					placeholder="Max $"
					aria-label="Max price"
					value={maxText}
					oninput={onMaxInput}
					onblur={() => maxTimer !== undefined && commitMax()}
					class="{control} w-24"
				/>
			</div>
		</fieldset>

		{#if brands.length > 1}
			<fieldset>
				<legend class={legend}>Brand</legend>
				<div class="flex flex-wrap items-center gap-3">
					{#each brands as b (b)}
						<label class="flex h-9 cursor-pointer select-none items-center gap-1.5 text-sm text-text">
							<input
								type="checkbox"
								name="brand"
								value={b}
								class="size-4 accent-accent"
								checked={view.brands.includes(b)}
								onchange={(e) =>
									set({ brands: toggle(view.brands, b, (e.target as HTMLInputElement).checked) })}
							/>
							{b}
						</label>
					{/each}
				</div>
			</fieldset>
		{/if}

		{#if gens.length > 1}
			<fieldset>
				<legend class={legend}>Generation</legend>
				<div class="flex flex-wrap items-center gap-3">
					{#each gens as g (g.value)}
						<label class="flex h-9 cursor-pointer select-none items-center gap-1.5 text-sm text-text">
							<input
								type="checkbox"
								name="gen"
								value={g.value}
								class="size-4 accent-accent"
								checked={view.gens.includes(g.value)}
								onchange={(e) =>
									set({ gens: toggle(view.gens, g.value, (e.target as HTMLInputElement).checked) })}
							/>
							{g.label}
						</label>
					{/each}
				</div>
			</fieldset>
		{/if}

		<label
			class="flex h-9 shrink-0 cursor-pointer select-none items-center gap-1.5 self-start rounded-md border border-border bg-surface px-2.5 text-sm text-text md:self-end"
		>
			<input
				type="checkbox"
				name="in_stock"
				value="1"
				class="accent-accent"
				checked={view.inStock}
				onchange={(e) => onInStock((e.target as HTMLInputElement).checked)}
			/>
			In stock
		</label>

		<label class="flex flex-col text-sm text-text">
			<span class={legend}>Retailer</span>
			<select
				name="retailer"
				class={control}
				value={view.retailer ?? ''}
				onchange={(e) =>
					set({ retailer: ((e.target as HTMLSelectElement).value || null) as Retailer | null })}
			>
				<option value="">Any</option>
				{#each ACTIVE_RETAILER_OPTIONS as r (r.value)}
					<option value={r.value}>{r.label}</option>
				{/each}
			</select>
		</label>

		<!-- The column headers sort too; these are for a phone (the header row
		     is hidden there) and for the no-JS form. -->
		<div class="flex items-end gap-2">
			<label class="flex flex-col text-sm text-text">
				<span class={legend}>Sort</span>
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
				<span class={legend}>Order</span>
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

		{#if activeCount > 0}
			<a href={clearHref} class="self-start text-sm text-accent underline md:self-end md:pb-2">
				Clear filters
			</a>
		{/if}

		<button
			type="button"
			onclick={closeDialog}
			class="h-10 rounded-md border border-accent bg-accent-soft px-3 text-sm font-medium text-accent md:hidden"
		>
			Show {resultCount}
			{resultCount === 1 ? 'result' : 'results'}
		</button>
	</form>
</dialog>
