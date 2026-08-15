<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/Header.svelte';

	let { children } = $props();
</script>

<div class="flex min-h-screen flex-col">
	<Header />
	<main class="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
		{@render children()}
	</main>
	<footer class="border-t border-border">
		<div class="mx-auto max-w-6xl px-4 py-4 text-xs text-text-muted">
			Trackaroo — AU CPU &amp; GPU price tracker
		</div>
	</footer>
</div>
