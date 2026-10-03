<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Crumb } from '$lib/breadcrumbs';
	import Breadcrumbs from './Breadcrumbs.svelte';

	let {
		title,
		subtitle = null,
		crumbs,
		compact = false,
		actions
	}: {
		title: string;
		subtitle?: string | null;
		crumbs?: Crumb[];
		compact?: boolean;
		actions?: Snippet;
	} = $props();
</script>

<header data-testid="page-header" class="mb-6 border-b border-border pb-4">
	{#if crumbs && crumbs.length > 0}
		<div class="mb-2"><Breadcrumbs {crumbs} /></div>
	{/if}
	<div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
		<div class="min-w-0 max-w-full flex-1 basis-64">
			<h1 class="{compact ? 'text-title' : 'text-display'} break-words text-text">{title}</h1>
			{#if subtitle}
				<p class="mt-1 text-body text-text-muted">{subtitle}</p>
			{/if}
		</div>
		{#if actions}
			<div class="flex max-w-full flex-wrap items-center gap-2 md:justify-end">{@render actions()}</div>
		{/if}
	</div>
</header>
