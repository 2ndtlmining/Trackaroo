<script lang="ts">
	// Floating bar on /products once a product is ticked for comparison.
	let { count, href, onClear }: { count: number; href: string; onClear: () => void } = $props();
</script>

{#if count >= 1}
	<div
		class="fixed inset-x-0 bottom-4 z-20 flex justify-center px-4"
		role="region"
		aria-label="Compare bar"
	>
		<div
			class="flex items-center gap-3 rounded-full border border-border bg-surface px-4 py-2 shadow-lg"
		>
			<span class="text-sm text-text-muted">{count} selected</span>
			<button
				type="button"
				onclick={onClear}
				class="text-sm text-text-muted hover:text-text"
			>
				Clear
			</button>
			{#if count === 1}
				<span class="text-sm text-text-muted">Pick 1 more to compare</span>
			{:else}
				<a {href} class="text-sm font-medium text-accent no-underline hover:underline">
					Compare ({count}) →
				</a>
			{/if}
		</div>
	</div>
{/if}
