<script lang="ts">
	import { quickComparePair, searchProducts } from '$lib/productSearch';
	import { goto } from '$app/navigation';
	import Badge from './Badge.svelte';
	import { buildDisplayNames, displayName } from '$lib/displayName';
	import type { ProductIndexEntry } from '$lib/models';

	let {
		items,
		open,
		onToggle,
		onClose
	}: {
		items: ProductIndexEntry[];
		open: boolean;
		onToggle: () => void;
		onClose: () => void;
	} = $props();

	let query = $state('');
	let highlight = $state(0);
	let inputEl = $state<HTMLInputElement | undefined>();
	let dialogEl = $state<HTMLElement | undefined>();
	// Whatever had focus before the palette opened, so it can be handed back.
	let previouslyFocused: HTMLElement | null = null;

	$effect(() => {
		const onKey = (event: KeyboardEvent) => {
			if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
				event.preventDefault();
				onToggle();
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});

	$effect(() => {
		if (open) {
			query = '';
			highlight = 0;
			previouslyFocused = document.activeElement as HTMLElement | null;
			inputEl?.focus();
		} else {
			// Returning focus to the trigger is what makes the dialog usable by
			// keyboard: without it, focus falls back to <body> and the next Tab
			// starts from the top of the page.
			previouslyFocused?.focus?.();
			previouslyFocused = null;
		}
	});

	/**
	 * Keep Tab inside the dialog while it is open.
	 *
	 * The palette renders over the page but the page behind it stays in the tab
	 * order, so tabbing walked out of the modal and left a keyboard user typing
	 * into a search box they could no longer see.
	 */
	function trapTab(event: KeyboardEvent) {
		if (event.key !== 'Tab' || !dialogEl) return;
		const focusable = dialogEl.querySelectorAll<HTMLElement>(
			'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
		);
		if (focusable.length === 0) return;
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		const active = document.activeElement;

		if (event.shiftKey && active === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && active === last) {
			event.preventDefault();
			first.focus();
		}
	}

	// Shared with the /products index so the two search surfaces cannot rank
	// the same catalogue differently. Also gains ranking, which the inline
	// filter this replaced did not have.
	// The base card carries its VRAM where a memory sibling exists (display only).
	const names = $derived(buildDisplayNames(items));
	const namedItems = $derived(items.map((i) => ({ ...i, model: displayName(names, i.id, i.model) })));
	const filtered = $derived(searchProducts(namedItems, query));

	const visible = $derived(filtered.slice(0, 8));

	const quickCompare = $derived(quickComparePair(visible));

	const LISTBOX_ID = 'palette-listbox';
	const optionId = (row: (typeof results)[number]) =>
		row.kind === 'compare' ? 'palette-option-compare' : `palette-option-${row.item.id}`;

	const results = $derived.by(() => {
		const list: Array<
			{ kind: 'compare'; a: ProductIndexEntry; b: ProductIndexEntry } | { kind: 'item'; item: ProductIndexEntry }
		> = [];
		if (quickCompare) {
			const [a, b] = quickCompare;
			list.push({ kind: 'compare', a, b });
		}
		for (const item of visible) list.push({ kind: 'item', item });
		return list;
	});

	// Reset the highlight whenever the query changes or the palette reopens,
	// so Enter never fires the previous query's top hit.
	$effect(() => {
		void query;
		if (open) highlight = 0;
	});

	// Arrow keys clamp at the ends (no wrap).
	const activeId = $derived(results[highlight] ? optionId(results[highlight]) : undefined);

	function clampHighlight(index: number) {
		highlight = Math.max(0, Math.min(index, results.length - 1));
	}

	function activate() {
		const row = results[highlight];
		if (!row) return;
		if (row.kind === 'compare') {
			goto(`/compare?ids=${row.a.id},${row.b.id}`);
		} else {
			goto(`/product/${row.item.id}`);
		}
		onClose();
	}

	// The listbox scrolls (max-h-80), so keyboard moves keep the active option
	// on screen; the options' ids never change, so it is already in the DOM.
	function revealHighlight() {
		const row = results[highlight];
		if (row) document.getElementById(optionId(row))?.scrollIntoView({ block: 'nearest' });
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			clampHighlight(highlight + 1);
			revealHighlight();
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			clampHighlight(highlight - 1);
			revealHighlight();
		} else if (event.key === 'Enter') {
			event.preventDefault();
			activate();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			onClose();
		}
	}
</script>

{#if open}
	<div class="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[18vh]">
		<button
			type="button"
			class="absolute inset-0 bg-black/50"
			aria-label="Close search"
			onclick={onClose}
		></button>
		<div
			bind:this={dialogEl}
			role="dialog"
			aria-modal="true"
			aria-label="Search products"
			tabindex="-1"
			onkeydown={trapTab}
			class="relative w-full max-w-md overflow-hidden rounded-xl border border-border-strong bg-surface-3 shadow-xl"
		>
			<div class="flex items-center gap-2 border-b border-border px-3 py-2.5">
				<svg
					class="h-4 w-4 shrink-0 text-text-muted"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<circle cx="11" cy="11" r="8" />
					<path d="m21 21-4.35-4.35" />
				</svg>
				<input
					bind:this={inputEl}
					type="text"
					placeholder="Search {items.length} products…"
					value={query}
					oninput={(e) => (query = e.currentTarget.value)}
					onkeydown={onKeydown}
					class="w-full bg-transparent text-sm text-text outline-none placeholder:text-text-muted"
					aria-label="Search products"
					role="combobox"
					aria-autocomplete="list"
					aria-expanded={results.length > 0}
					aria-controls={LISTBOX_ID}
					aria-activedescendant={activeId}
					autocomplete="off"
				/>
				<kbd class="shrink-0 rounded border border-border px-1 py-0.5 font-mono text-meta text-text-muted">esc</kbd>
			</div>
			{#if results.length === 0}
				<p class="mx-3 my-2 rounded-md border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted">
					No matches.
				</p>
			{/if}
			<ul
				id={LISTBOX_ID}
				role="listbox"
				aria-label="Results"
				class={results.length === 0 ? 'hidden' : 'max-h-80 overflow-y-auto py-1'}
			>
				{#each results as row, i (row.kind === 'compare' ? 'compare' : row.item.id)}
					<!-- Keyboard use goes through the combobox input (Arrow/Enter), per the ARIA pattern. -->
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<li
						id={optionId(row)}
						role="option"
						aria-selected={i === highlight}
						onclick={() => {
							highlight = i;
							activate();
						}}
						onmouseenter={() => (highlight = i)}
						class="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm {i === highlight
							? 'bg-surface-hover'
							: ''}"
					>
						{#if row.kind === 'compare'}
							<span class="text-accent">
								Compare {row.a.model} vs {row.b.model}
							</span>
						{:else}
							<span
								class="flex-1 truncate {row.item.snapshotCount === 0
									? 'text-text-muted'
									: 'text-text'}"
							>
								{row.item.model}
							</span>
							<span class="shrink-0 text-xs text-text-muted">{row.item.brand}</span>
							<span class="shrink-0 text-xs text-text-muted">
								{row.item.snapshotCount === 0
									? 'no data yet'
									: `${row.item.snapshotCount} ${row.item.snapshotCount === 1 ? 'snapshot' : 'snapshots'}`}
							</span>
							<Badge tone="neutral" label={row.item.category.toUpperCase()} />
						{/if}
					</li>
				{/each}
			</ul>
		</div>
	</div>
{/if}