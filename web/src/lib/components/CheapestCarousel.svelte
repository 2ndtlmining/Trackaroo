<script lang="ts">
	import { formatAud, titleCase } from '$lib/formats';
	import type { CheapestListing } from '$lib/server/repos';
	import type { Category } from '$lib/types';

	let { gpu, cpu }: { gpu: CheapestListing[]; cpu: CheapestListing[] } = $props();

	let category = $state<Category>('gpu');
	let paused = $state(false);
	let scrollEl: HTMLDivElement | undefined = $state();

	const STEP = 220;

	function setCategory(next: Category) {
		category = next;
		scrollEl?.scrollTo({ left: 0, behavior: 'auto' });
	}

	function list(): CheapestListing[] {
		return category === 'gpu' ? gpu : cpu;
	}

	function step(delta: number) {
		if (!scrollEl) return;
		scrollEl.scrollBy({ left: delta, behavior: 'smooth' });
	}

	$effect(() => {
		// Auto-scroll left → right; pauses on hover/manual interaction and loops.
		if (!scrollEl || paused) return;
		const el = scrollEl;
		const timer = setInterval(() => {
			const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 4;
			if (atEnd) {
				el.scrollTo({ left: 0, behavior: 'smooth' });
			} else {
				el.scrollBy({ left: STEP, behavior: 'smooth' });
			}
		}, 3000);
		return () => clearInterval(timer);
	});
</script>

<div class="rounded-md border border-border bg-surface p-4">
	<div class="mb-3 flex flex-wrap items-center justify-between gap-2">
		<h2 class="text-sm font-semibold text-text">Cheapest deals</h2>
		<div class="flex items-center gap-2">
			<div
				class="inline-flex rounded-md border border-border bg-surface p-0.5"
				role="tablist"
				aria-label="Cheapest deals category"
			>
				<button
					type="button"
					role="tab"
					aria-selected={category === 'gpu'}
					onclick={() => setCategory('gpu')}
					class="rounded-md px-2.5 py-1 text-xs {category === 'gpu'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					GPU
				</button>
				<button
					type="button"
					role="tab"
					aria-selected={category === 'cpu'}
					onclick={() => setCategory('cpu')}
					class="rounded-md px-2.5 py-1 text-xs {category === 'cpu'
						? 'bg-surface-hover font-medium text-text'
						: 'text-text-muted hover:text-text'}"
				>
					CPU
				</button>
			</div>
			<div class="flex items-center gap-1">
				<button
					type="button"
					aria-label="Scroll left"
					onclick={() => step(-STEP)}
					onpointerenter={() => (paused = true)}
					onpointerleave={() => (paused = false)}
					class="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-surface text-text-muted hover:bg-surface-hover hover:text-text"
				>
					‹
				</button>
				<button
					type="button"
					aria-label="Scroll right"
					onclick={() => step(STEP)}
					onpointerenter={() => (paused = true)}
					onpointerleave={() => (paused = false)}
					class="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-surface text-text-muted hover:bg-surface-hover hover:text-text"
				>
					›
				</button>
			</div>
		</div>
	</div>

	{#if list().length === 0}
		<div
			class="rounded-md border border-border bg-surface px-4 py-8 text-center text-sm text-text-muted"
		>
			No {category === 'gpu' ? 'GPU' : 'CPU'} models in stock at the latest snapshot.
		</div>
	{:else}
		<div
			bind:this={scrollEl}
			role="list"
			class="no-scrollbar flex snap-x snap-proximity gap-3 overflow-x-auto scroll-px-4 pb-2"
			onpointerenter={() => (paused = true)}
			onpointerleave={() => (paused = false)}
			onwheel={() => (paused = true)}
			onkeydown={() => (paused = true)}
			ontouchstart={() => (paused = true)}
		>
			{#each list() as listing (listing.productId)}
				<article
					role="listitem"
					class="flex w-48 shrink-0 snap-start flex-col rounded-md border border-border bg-surface-hover p-3"
				>
					<div class="flex items-center justify-between gap-2">
						<span class="truncate text-xs font-medium text-text">{listing.model}</span>
						<span
							class="shrink-0 rounded-full border border-border bg-surface px-2 py-0.5 text-[10px] uppercase tracking-wide text-text-muted"
						>
							{listing.retailer}
						</span>
					</div>
					<div class="mt-2 flex items-baseline gap-2">
						<span class="text-lg font-semibold text-text">{formatAud(listing.price)}</span>
						{#if listing.ninetyDayLow !== null && listing.price === listing.ninetyDayLow}
							<span
								class="shrink-0 rounded-full border border-down/30 bg-down/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-down"
								title="Lowest price in the last 90 days"
							>
								90d low
							</span>
						{/if}
					</div>
					<div class="mt-1 line-clamp-2 text-xs text-text-muted" title={titleCase(listing.variantName) || undefined}>
						{titleCase(listing.variantName) || listing.model}
					</div>
					<a
						href="/product/{listing.productId}"
						class="mt-3 text-xs text-accent no-underline hover:underline"
					>
						View deal →
					</a>
				</article>
			{/each}
		</div>
	{/if}
</div>

<style>
	.no-scrollbar::-webkit-scrollbar {
		display: none;
	}
	.no-scrollbar {
		scrollbar-width: none;
		-ms-overflow-style: none;
	}
</style>