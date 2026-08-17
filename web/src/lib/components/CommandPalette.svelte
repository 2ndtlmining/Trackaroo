<script lang="ts">
	import { goto } from '$app/navigation';
	import Badge from './Badge.svelte';
	import type { ProductIndexEntry } from '$lib/server/repos';

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
			inputEl?.focus();
		}
	});

	const q = $derived(query.trim().toLowerCase());

	const filtered = $derived(
		q
			? items.filter(
					(i) =>
						i.model.toLowerCase().includes(q) ||
						i.brand.toLowerCase().includes(q) ||
						(i.productVariant ?? '').toLowerCase().includes(q)
				)
			: items
	);

	const visible = $derived(filtered.slice(0, 8));

	const quickCompare = $derived(visible.length === 2 ? visible : null);

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

	$effect(() => {
		void q;
		if (open) highlight = 0;
	});

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

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			clampHighlight(highlight + 1);
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			clampHighlight(highlight - 1);
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
			role="dialog"
			aria-modal="true"
			aria-label="Search products"
			class="relative w-full max-w-md overflow-hidden rounded-md border border-border-strong bg-surface shadow-xl"
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
				/>
				<kbd class="shrink-0 rounded border border-border px-1 py-0.5 font-mono text-[10px] text-text-muted">esc</kbd>
			</div>
			{#if results.length === 0}
				<p class="px-3 py-6 text-center text-sm text-text-muted">No matches.</p>
			{:else}
				<ul role="listbox" aria-label="Results" class="max-h-80 overflow-y-auto py-1">
					{#each results as row, i (row.kind === 'compare' ? 'compare' : row.item.id)}
						<li>
							<button
								type="button"
								role="option"
								aria-selected={i === highlight}
								onclick={() => {
									highlight = i;
									activate();
								}}
								onmouseenter={() => (highlight = i)}
								class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm {i === highlight
									? 'bg-surface-hover'
									: ''}"
							>
								{#if row.kind === 'compare'}
									<span class="text-accent">
										Compare {row.a.model} vs {row.b.model}
									</span>
								{:else}
									<span class="flex-1 truncate text-text">{row.item.model}</span>
									<span class="shrink-0 text-xs text-text-muted">{row.item.brand}</span>
									<Badge tone="neutral" label={row.item.category.toUpperCase()} />
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</div>
{/if}