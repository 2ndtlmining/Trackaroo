<script lang="ts">
	import '../app.css';
	import { navigating, page } from '$app/state';
	import Header from '$lib/components/Header.svelte';
	import CommandPalette from '$lib/components/CommandPalette.svelte';
	import StaleDataBanner from '$lib/components/StaleDataBanner.svelte';

	let { data, children } = $props();

	let paletteOpen = $state(false);

	// Table pages (loaders return `wide: true`) get the wider column; header and footer follow.
	const wide = $derived((page.data as { wide?: boolean }).wide === true);
	const widthClass = $derived(wide ? 'max-w-7xl' : 'max-w-6xl');
</script>

<!--
	Every filter, sort and window control is a server round-trip via goto(), which
	gives no visual feedback on its own — on a slow query the page just sits
	there. This bar is the only signal that a navigation is in flight.
-->
{#if navigating.to}
	<div
		class="fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden bg-transparent"
		role="status"
		aria-label="Loading"
	>
		<div class="nav-progress h-full w-full bg-accent"></div>
	</div>
{/if}

<a
	href="#main"
	class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-border focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-text focus:no-underline"
>
	Skip to content
</a>

<div class="flex min-h-screen flex-col">
	<Header onOpenSearch={() => (paletteOpen = true)} {widthClass} />
	<main id="main" class="mx-auto w-full {widthClass} flex-1 px-4 py-6">
		<StaleDataBanner latestSnapshotDate={data.stats.latestSnapshotDate} />
		{@render children()}
	</main>
	<footer class="border-t border-border">
		<div class="mx-auto {widthClass} px-4 py-4 text-xs text-text-muted">
			Trackaroo — AU CPU &amp; GPU price tracker · Logos are trademarks of their respective owners
			· <span data-testid="version-line"
				><a
					href="/changelog"
					class="underline underline-offset-2 hover:text-text"
					data-testid="release-version"
					aria-label="v{data.release}, what's new">v{data.release}</a
				>
				· <span data-testid="build-version">build {data.version}</span></span
			>
		</div>
	</footer>
	<CommandPalette
		items={data.productIndex}
		open={paletteOpen}
		onToggle={() => (paletteOpen = !paletteOpen)}
		onClose={() => (paletteOpen = false)}
	/>
</div>

<style>
	.nav-progress {
		transform-origin: 0 50%;
		animation: nav-progress 1.4s ease-out infinite;
	}

	@keyframes nav-progress {
		0% {
			transform: scaleX(0);
			opacity: 1;
		}
		70% {
			transform: scaleX(0.85);
		}
		100% {
			transform: scaleX(1);
			opacity: 0.4;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.nav-progress {
			animation: none;
			transform: scaleX(1);
			opacity: 0.7;
		}
	}
</style>
