<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Crumb } from '$lib/breadcrumbs';
	import Breadcrumbs from './Breadcrumbs.svelte';

	// subtitle: a plain string, or a snippet when it carries markup (tabular
	// counts, a bold "and"). meta: block content that belongs to the title,
	// such as the product page's brand line, kept above the bottom rule.
	let {
		title,
		subtitle = null,
		crumbs,
		compact = false,
		actions,
		meta
	}: {
		title: string;
		subtitle?: string | Snippet | null;
		crumbs?: Crumb[];
		compact?: boolean;
		actions?: Snippet;
		meta?: Snippet;
	} = $props();
</script>

<header data-testid="page-header" class="mb-6 border-b border-border pb-4">
	{#if crumbs && crumbs.length > 0}
		<div class="mb-2"><Breadcrumbs {crumbs} /></div>
	{/if}
	<div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
		<div class="min-w-0 max-w-full flex-1 basis-64">
			<h1 class="{compact ? 'text-title' : 'text-display'} break-words text-text">{title}</h1>
			{#if typeof subtitle === 'function'}
				<p class="mt-1 text-body text-text-muted">{@render subtitle()}</p>
			{:else if subtitle}
				<p class="mt-1 text-body text-text-muted">{subtitle}</p>
			{/if}
			{#if meta}
				<div data-testid="page-header-meta" class="mt-2 space-y-1 text-body text-text-muted">{@render meta()}</div>
			{/if}
		</div>
		{#if actions}
			<div class="flex max-w-full flex-wrap items-center gap-2 md:justify-end">{@render actions()}</div>
		{/if}
	</div>
</header>
