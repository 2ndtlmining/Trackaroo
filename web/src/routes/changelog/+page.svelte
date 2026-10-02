<script lang="ts">
	import PageHead from '$lib/components/PageHead.svelte';
	import { renderInline, type Release } from '$lib/changelog';
	import { formatDate } from '$lib/formats';

	let { data }: { data: { releases: Release[] } } = $props();
</script>

<PageHead title="What's new" description="Trackaroo releases and what changed in each." />

<h1 class="text-2xl font-semibold text-text">What's new</h1>
<p class="mt-1 text-sm text-text-muted">Every Trackaroo release, newest first.</p>

{#if data.releases.length === 0}
	<p class="mt-6 text-sm text-text-muted">No releases yet.</p>
{:else}
	<ol class="mt-6 space-y-6">
		{#each data.releases as release (release.version)}
			<li
				class="rounded-lg border border-border bg-surface p-4 sm:p-5"
				data-testid="release"
				aria-labelledby="release-{release.version}"
			>
				<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
					<h2 id="release-{release.version}" class="text-lg font-semibold text-text">
						v{release.version}
					</h2>
					{#if release.date}
						<time datetime={release.date} class="text-sm text-text-muted">
							{formatDate(release.date)}
						</time>
					{/if}
				</div>
				{#each release.intro as para, k (k)}
					<p class="changelog-list mt-3 text-sm text-text-muted">{@html renderInline(para)}</p>
				{/each}
				{#each release.sections as section, i (i)}
					{#if section.title}
						<h3 class="mt-4 text-xs font-semibold tracking-wide text-text-muted uppercase">
							{section.title}
						</h3>
					{/if}
					<ul class="changelog-list mt-2 list-disc space-y-1 pl-5 text-sm text-text">
						{#each section.items as item, j (j)}
							<!-- renderInline escapes all HTML first and only adds code/strong/a. -->
							<li>{@html renderInline(item)}</li>
						{/each}
					</ul>
				{/each}
			</li>
		{/each}
	</ol>
{/if}

<style>
	.changelog-list :global(a) {
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.changelog-list :global(code) {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.85em;
		padding: 0.05em 0.3em;
		border-radius: 0.25rem;
		background: var(--surface-hover);
	}
</style>
