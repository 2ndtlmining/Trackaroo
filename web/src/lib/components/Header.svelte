<script lang="ts">
	import { page } from '$app/state';
	import ThemeToggle from './ThemeToggle.svelte';
	import { formatBytes } from '$lib/formats';

	let { stats, onOpenSearch }: { stats: import('$lib/server/repos').HeaderStats; onOpenSearch?: () => void } = $props();

	const links = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/products', label: 'Products' },
		{ href: '/movers', label: 'Movers' }
	];

	const path = $derived(page.url.pathname);
</script>

<header class="border-b border-border bg-surface">
	<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
		<a href="/" class="flex items-center gap-2 text-sm font-semibold tracking-tight text-text no-underline hover:no-underline">
			<span class="h-2 w-2 rounded-full bg-accent"></span>
			Trackaroo
		</a>
		<nav class="flex items-center gap-1 text-sm" aria-label="Main">
			{#each links as link}
				<a
					href={link.href}
					class="rounded-md px-2.5 py-1.5 no-underline hover:no-underline {path === link.href
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:bg-surface-hover hover:text-text'}"
				>
					{link.label}
				</a>
			{/each}
		</nav>
		<div class="flex items-center gap-4">
			<p class="hidden items-center gap-3 text-xs text-text-muted lg:flex">
				{#if stats.latestSnapshotDate}
					<span title="Most recent price snapshot date">
						{stats.latestSnapshotDate}
					</span>
				{/if}
				{#if stats.snapshotDays > 0}
					<span class="inline-flex items-center gap-1.5" title="Distinct days with a snapshot">
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
							<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
							<circle cx="12" cy="13" r="4" />
						</svg>
						{stats.snapshotDays} days
					</span>
				{/if}
				{#if stats.dbSizeBytes > 0}
					<span class="inline-flex items-center gap-1.5" title="SQLite database size">
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
							<ellipse cx="12" cy="5" rx="9" ry="3" />
							<path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
							<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
						</svg>
						{formatBytes(stats.dbSizeBytes)}
					</span>
				{/if}
			</p>
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