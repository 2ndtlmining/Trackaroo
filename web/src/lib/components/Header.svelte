<script lang="ts">
	import { page } from '$app/state';
	import Wordmark from './Wordmark.svelte';
	import ThemeToggle from './ThemeToggle.svelte';
	import { NAV_LINKS, isActiveLink } from '$lib/nav';
	import type { Category } from '$lib/types';

	let { onOpenSearch }: { onOpenSearch?: () => void } = $props();

	// Only the product page's data has a `product`; everywhere else this is null.
	const productCategory = $derived(
		(page.data as { product?: { category?: Category } }).product?.category ?? null
	);
	const discoverPending = $derived((page.data as { discoverPending?: number }).discoverPending ?? 0);
</script>

<header class="border-b border-border bg-surface">
	<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
		<Wordmark />
		<nav
			class="-mx-1 flex max-w-full items-center gap-1 overflow-x-auto px-1 text-sm md:overflow-visible"
			aria-label="Main"
		>
			{#each NAV_LINKS as link (link.href)}
				{@const active = isActiveLink(link.href, page.url.pathname, page.url.searchParams, productCategory)}
				<a
					href={link.href}
					aria-current={active ? 'page' : undefined}
					class="whitespace-nowrap rounded-md px-2.5 py-1.5 no-underline hover:no-underline {active
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:bg-surface-hover hover:text-text'}"
				>
					{link.label}
					{#if link.href === '/discover' && discoverPending}
						<span
							data-testid="nav-discover-badge"
							class="ml-1 rounded-full bg-accent-soft px-1.5 text-xs font-semibold text-accent"
							aria-label="{discoverPending} parts waiting">{discoverPending}</span
						>
					{/if}
				</a>
			{/each}
		</nav>
		<div class="flex items-center gap-4">
			{#if onOpenSearch}
				<button
					type="button"
					onclick={onOpenSearch}
					class="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-text"
					aria-label="Search products"
					title="Search products (Ctrl+K)"
				>
					<svg
						class="h-3.5 w-3.5 shrink-0"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
					>
						<circle cx="11" cy="11" r="8" />
						<path d="m21 21-4.35-4.35" />
					</svg>
					<span class="hidden sm:inline">Search</span>
					<kbd class="rounded border border-border px-1 py-0.5 font-mono text-[10px]">Ctrl K</kbd>
				</button>
			{/if}
			<ThemeToggle />
		</div>
	</div>
</header>