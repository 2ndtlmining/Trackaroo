<script lang="ts">
	import type { Crumb } from '$lib/breadcrumbs';

	let { crumbs }: { crumbs: Crumb[] } = $props();
</script>

<nav aria-label="Breadcrumb">
	<ol class="flex flex-wrap items-center gap-1 text-xs text-text-muted">
		{#each crumbs as crumb, i (i)}
			<li class="flex items-center gap-1">
				{#if crumb.href}
					<a href={crumb.href} class="text-text-muted hover:text-text">{crumb.label}</a>
				{:else}
					<span aria-current="page" class="text-text">{crumb.label}</span>
				{/if}
				{#if i < crumbs.length - 1}<span aria-hidden="true">›</span>{/if}
			</li>
		{/each}
	</ol>
</nav>
