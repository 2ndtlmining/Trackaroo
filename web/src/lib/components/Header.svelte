<script lang="ts">
	import { page } from '$app/state';
	import ThemeToggle from './ThemeToggle.svelte';
	import { formatBytes } from '$lib/formats';

	let { stats } = $props<{ stats: import('$lib/server/repos').HeaderStats }>();

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
			<p class="hidden items-center gap-3 text-xs text-text-muted sm:flex">
				{#if stats.latestSnapshotDate}
					<span title="Date of latest snapshot">Last snapshot: {stats.latestSnapshotDate}</span>
				{/if}
				{#if stats.snapshotCount > 0}
					<span title="Price snapshots in database">{stats.snapshotCount} snapshots</span>
				{/if}
				{#if stats.dbSizeBytes > 0}
					<span title="SQLite database size">{formatBytes(stats.dbSizeBytes)}</span>
				{/if}
			</p>
			<ThemeToggle />
		</div>
	</div>
</header>