<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/Header.svelte';
	import CommandPalette from '$lib/components/CommandPalette.svelte';

	let { data, children } = $props();

	let paletteOpen = $state(false);
</script>

<div class="flex min-h-screen flex-col">
	<Header stats={data.stats} onOpenSearch={() => (paletteOpen = true)} />
	<main class="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
		{@render children()}
	</main>
	<footer class="border-t border-border">
		<div class="mx-auto max-w-6xl px-4 py-4 text-xs text-text-muted">
			Trackaroo — AU CPU &amp; GPU price tracker · Logos are trademarks of their respective owners
		</div>
	</footer>
	<CommandPalette
		items={data.productIndex}
		open={paletteOpen}
		onToggle={() => (paletteOpen = !paletteOpen)}
		onClose={() => (paletteOpen = false)}
	/>
</div>
