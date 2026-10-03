<script lang="ts">
	import { onMount } from 'svelte';
	import { formatAud } from '$lib/formats';
	import { retailerLabel } from '$lib/filters';
	import { ACTIVE_RETAILER_OPTIONS, parseCatalogView, type CatalogView } from '$lib/catalogView';
	import FilterCheckboxGroup from './FilterCheckboxGroup.svelte';
	import CatalogSortControls from './CatalogSortControls.svelte';
	import type { Category, GenerationTier, Retailer } from '$lib/types';

	// The catalogue's controls (#23, spec §4), rendered from one snippet into
	// two forms: inline above md (a form landmark, "Catalogue filters"), and
	// on a phone inside a native modal <dialog> opened by "Filters (N
	// active)". Only one is ever displayed, and the controls carry no ids, so
	// the copy is invisible to the accessibility tree and to tests. With
	// scripting off (Tailwind's noscript: variant, @media (scripting: none))
	// the inline form shows at every width and the opener hides, so a phone
	// without JS still gets the filters, with no hydration layout shift.
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

	// The submit button exists for the no-JS form only. It stays in the DOM
	// (hidden) once hydrated because it is the form's default button: Enter in
	// a field "clicks" it, and the submit handler below turns that into a
	// no-op instead of letting a $500 preset be the button that gets clicked.
	let hydrated = $state(false);

	let dialog: HTMLDialogElement | undefined = $state();
	let opener: HTMLButtonElement | undefined = $state();

	// The dialog is md:hidden, but a modal <dialog> still makes the rest of the
	// page inert. Widening past md with it open (a tablet rotating) would leave
	// an inert page with no visible dialog, so close it there. 48rem is md.
	const MD_QUERY = '(min-width: 48rem)';
	onMount(() => {
		hydrated = true;
		const mq = window.matchMedia(MD_QUERY);
		const onWide = () => {
			if (mq.matches && dialog?.open) dialog.close();
		};
		mq.addEventListener('change', onWide);
		return () => mq.removeEventListener('change', onWide);
	});

	function openDialog() {
		dialog?.showModal();
	}

	function closeDialog() {
		dialog?.close();
	}

	// Escape, "Show N results" and close() all land here. Above md the opener
	// is hidden, so focus is left where the browser puts it.
	function onDialogClose() {
		if (!window.matchMedia(MD_QUERY).matches) opener?.focus();
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

	// A link can name a retailer the pipeline no longer scrapes; the select
	// must still show what the URL says, rather than silently reading "Any".
	const staleRetailer = $derived(
		view.retailer && !ACTIVE_RETAILER_OPTIONS.some((o) => o.value === view.retailer)
			? view.retailer
			: null
	);

	const formClass = 'flex-col gap-3 md:flex-row md:flex-wrap md:items-end md:gap-x-4';
	const control =
		'h-9 rounded-md border border-border-input bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none';
	const chip =
		'h-9 rounded-md border border-border bg-surface px-2.5 text-sm text-text-muted hover:text-text aria-pressed:border-accent aria-pressed:bg-accent-soft aria-pressed:font-medium aria-pressed:text-accent';
	const legend = 'mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted';
</script>

{#snippet controls()}
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

	<!-- A single brand or tier is no choice, unless it is ticked: then it is
	     the control that clears an active filter. -->
	{#if brands.length > 1 || view.brands.length > 0}
		<FilterCheckboxGroup
			legend="Brand"
			legendClass={legend}
			name="brand"
			options={brands.map((b) => ({ value: b, label: b }))}
			selected={view.brands}
			onChange={(next) => set({ brands: next })}
		/>
	{/if}

	{#if gens.length > 1 || view.gens.length > 0}
		<FilterCheckboxGroup
			legend="Generation"
			legendClass={legend}
			name="gen"
			options={gens}
			selected={view.gens}
			onChange={(next) => set({ gens: next })}
		/>
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
			{#if staleRetailer}
				<option value={staleRetailer}>{retailerLabel(staleRetailer)} (no longer tracked)</option>
			{/if}
		</select>
	</label>

	<CatalogSortControls {view} {category} {control} legendClass={legend} {set} />

	{#if activeCount > 0}
		<a href={clearHref} class="self-start text-sm text-accent underline md:self-end md:pb-2">
			Clear filters
		</a>
	{/if}
{/snippet}

<button
	type="button"
	bind:this={opener}
	onclick={openDialog}
	class="h-9 shrink-0 rounded-md border border-border bg-surface px-2.5 text-sm text-text md:hidden noscript:hidden"
>
	Filters ({activeCount} active)
</button>

<form
	method="get"
	action="/products"
	aria-label="Catalogue filters"
	onsubmit={onSubmit}
	class="hidden w-full md:flex noscript:flex {formClass}"
>
	{@render controls()}
</form>

<dialog
	bind:this={dialog}
	onclose={onDialogClose}
	aria-label="Filters"
	class="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-border-card bg-surface-3 p-4 text-text backdrop:bg-bg/80 md:hidden"
>
	<form method="get" action="/products" onsubmit={onSubmit} class="flex {formClass}">
		{@render controls()}
		<button
			type="button"
			onclick={closeDialog}
			class="h-10 rounded-md border border-accent bg-accent-soft px-3 text-sm font-medium text-accent"
		>
			Show {resultCount}
			{resultCount === 1 ? 'result' : 'results'}
		</button>
	</form>
</dialog>
